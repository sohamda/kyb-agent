"""Reviewer bot: resume compliance-paused runs like a human compliance officer.

Runs alongside ``send_traffic.py``. On each poll it finds threads on the
deployment that are paused for approval, looks up the application's hidden
ground-truth label in ``traffic_pool.jsonl``, and resumes the run through the
Agent Server API — approving a real sanctions match, rejecting a false positive.
It deliberately errs ~5% of the time, then logs **SDK feedback** ``reviewer_agreed``
(1 = approved the escalation, i.e. agreed the agent's sanctions flag was real)
on the application's trace. Engine treats this feedback as a high-priority signal.

Usage:

    # continuous, poll every 60s, 5% error rate, against prod
    python3 simulator/reviewer_bot.py

    # single pass (for testing), against staging
    python3 simulator/reviewer_bot.py --once \
        --url https://kyb-agent-staging-....us.langgraph.app
"""

from __future__ import annotations

import argparse
import json
import random
import time

import _env  # noqa: F401  (loads agent/.env)
from langgraph_sdk import get_sync_client
from langsmith import Client as LangSmithClient


def _pool_by_app_id() -> tuple[dict[str, dict], dict[str, dict]]:
    """Map application_id -> (hidden label, run metadata) from the traffic pool.

    The label is never sent to the agent; it only drives the officer's decision.
    The metadata is re-attached on the resume run so the decision-bearing run
    carries jurisdiction/revision/simulated (the original run pauses before the
    decision exists, so dashboards need the metadata on the resume).
    """
    labels: dict[str, dict] = {}
    metas: dict[str, dict] = {}
    for line in _env.TRAFFIC_POOL.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        app_id = row["application"]["application_id"]
        labels[app_id] = row["label"]
        metas[app_id] = row.get("metadata", {})
    return labels, metas


def _application_id(state: dict) -> str | None:
    """Pull the application_id out of the first human message's JSON payload."""
    for m in state.get("values", {}).get("messages", []) or []:
        content = m.get("content") if isinstance(m, dict) else getattr(m, "content", None)
        if not isinstance(content, str) or "application_id" not in content:
            continue
        try:
            payload = json.loads(content[content.index("{"):])
            return payload.get("application", {}).get("application_id")
        except (ValueError, json.JSONDecodeError):
            continue
    return None


def _decide(label: dict, error_rate: float, rng: random.Random) -> tuple[str, int, str]:
    """Return (resume_decision, reviewer_agreed, note).

    A true sanctions match → approve the escalation (confirm reject). A false
    positive → reject the escalation. ``error_rate`` flips the officer's call.
    ``reviewer_agreed`` reflects the officer's *actual* action (approve = 1).
    """
    is_true_match = bool(label.get("sanctioned_parties"))
    correct = "approve" if is_true_match else "reject"
    actual = correct
    errored = rng.random() < error_rate
    if errored:
        actual = "reject" if correct == "approve" else "approve"
    agreed = 1 if actual == "approve" else 0
    note = ("true sanctions match" if is_true_match else "false positive")
    if errored:
        note += " (reviewer erred)"
    return actual, agreed, note


def _trace_run_id(client, thread_id: str) -> str | None:
    """The run that carries the final decision (the latest = the resume run)."""
    try:
        runs = list(client.runs.list(thread_id))
    except Exception:
        return None
    if not runs:
        return None
    runs.sort(key=lambda r: r.get("created_at") or "")
    return runs[-1].get("run_id")


def _session_id(ls: LangSmithClient, run_id: str, cache: dict) -> str | None:
    """Resolve (and cache) the tracing-project id that owns the runs.

    create_feedback wants session_id (+ trace_id) to batch ingestion and to
    avoid the deprecated session-less path. For a deployment every run lands in
    the same project, so one lookup serves the whole session.
    """
    if "sid" in cache:
        return cache["sid"]
    sid = None
    try:
        run = ls.runs.retrieve(run_id)  # type: ignore[attr-defined]
        sid = getattr(run, "session_id", None)
    except Exception:
        try:
            sid = getattr(ls.read_run(run_id), "session_id", None)
        except Exception:
            sid = None
    cache["sid"] = str(sid) if sid else None
    return cache["sid"]


def poll_once(client, ls: LangSmithClient, labels: dict, metas: dict, revision: str,
              assistant: str, error_rate: float, rng: random.Random, handled: set,
              sid_cache: dict) -> int:
    threads = client.threads.search(status="interrupted", limit=100)
    acted = 0
    for th in threads:
        tid = th["thread_id"]
        if tid in handled:
            continue
        state = client.threads.get_state(tid)
        app_id = _application_id(state)
        label = labels.get(app_id) if app_id else None
        if label is None:
            print(f"  ! {tid}: no label for application_id={app_id}; skipping")
            handled.add(tid)
            continue
        decision, agreed, note = _decide(label, error_rate, rng)
        meta = metas.get(app_id, {})
        resume_meta = {
            "application_id": app_id,
            "jurisdiction": meta.get("jurisdiction"),
            "industry": meta.get("industry"),
            "portal_locale": meta.get("portal_locale"),
            "revision_id": revision,
            "simulated": True,
            "resumed": True,
        }
        try:
            # Re-attach metadata on the resume run: the original run paused before
            # the decision existed, so the decision-bearing run needs it too.
            client.runs.wait(
                tid, assistant,
                command={"resume": {"decisions": [{"type": decision}]}},
                metadata=resume_meta,
            )
        except Exception as e:
            print(f"  ! {tid} ({app_id}): resume failed: {e}")
            continue
        run_id = _trace_run_id(client, tid)
        if run_id:
            try:
                ls.create_feedback(
                    run_id=run_id,
                    key="reviewer_agreed",
                    score=agreed,
                    comment=f"{app_id}: {note}; officer {decision}d escalation",
                    trace_id=run_id,
                    session_id=_session_id(ls, run_id, sid_cache),
                )
            except Exception as e:
                print(f"  ! {tid} ({app_id}): feedback failed: {e}")
        handled.add(tid)
        acted += 1
        print(f"  ✓ {app_id}: {decision} escalation, reviewer_agreed={agreed} ({note})")
    return acted


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Resume paused KYB runs as a compliance officer.")
    ap.add_argument("--url", default=_env.PROD_URL, help="Agent Server URL (default: prod).")
    ap.add_argument("--assistant", default=_env.ASSISTANT, help="Graph/assistant id.")
    ap.add_argument("--poll-seconds", type=float, default=60.0)
    ap.add_argument("--error-rate", type=float, default=0.05)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--once", action="store_true", help="One pass then exit (for testing).")
    args = ap.parse_args(argv)

    labels, metas = _pool_by_app_id()
    revision = _env.revision_id()
    rng = random.Random(args.seed)
    client = get_sync_client(url=args.url, api_key=_env.api_key())
    ls = LangSmithClient(api_key=_env.api_key())
    handled: set = set()
    sid_cache: dict = {}

    print(f"reviewer_bot: watching {args.url} (assistant={args.assistant}, "
          f"error_rate={args.error_rate}, poll={args.poll_seconds}s)")
    while True:
        n = poll_once(client, ls, labels, metas, revision, args.assistant,
                      args.error_rate, rng, handled, sid_cache)
        if args.once:
            print(f"reviewer_bot: single pass handled {n} thread(s).")
            return 0
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
