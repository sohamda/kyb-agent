"""Send synthetic production traffic to the deployed KYB Agent Server.

Reads applications from ``simulator/out/traffic_pool.jsonl`` and submits each one
to the prod deployment with ``runs.create`` (fire-and-forget: the server runs the
agent asynchronously and pauses at the compliance interrupt; ``reviewer_bot.py``
resumes paused runs). Only the ``application`` is sent — the hidden ``label`` is
never transmitted. Each run is tagged with metadata (jurisdiction, industry,
portal_locale, revision_id, simulated=true, application_id) for dashboards and
Engine scoping.

Usage (from repo root or anywhere):

    # default: all 1,000 apps, one every 5 minutes (≈290/day)
    python3 simulator/send_traffic.py

    # a quick smoke: 2 apps, 2s apart, against staging
    python3 simulator/send_traffic.py --count 2 --rate-seconds 2 \
        --url https://kyb-agent-staging-....us.langgraph.app

The $60/day Gateway spend cap is the cost backstop; the 10 req/min rate limit
means one application at a time is comfortably within budget.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time

import _env  # noqa: F401  (loads agent/.env)
from langgraph_sdk import get_sync_client


def _application_message(application: dict) -> str:
    """Mirror the eval/Studio input contract (evals/target.py)."""
    return (
        "Review this business onboarding application and return your KYBDecision.\n\n"
        + json.dumps({"application": application}, indent=2)
    )


def _rows(count: int | None, offset: int, shuffle: bool, seed: int) -> list[dict]:
    rows = [json.loads(line) for line in _env.TRAFFIC_POOL.read_text().splitlines() if line.strip()]
    if shuffle:
        random.Random(seed).shuffle(rows)
    rows = rows[offset:]
    if count is not None:
        rows = rows[:count]
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Send synthetic KYB traffic to the deployment.")
    ap.add_argument("--url", default=_env.PROD_URL, help="Agent Server URL (default: prod).")
    ap.add_argument("--assistant", default=_env.ASSISTANT, help="Graph/assistant id.")
    ap.add_argument("--rate-seconds", type=float, default=300.0, help="Seconds between submissions.")
    ap.add_argument("--jitter", type=float, default=0.0, help="± random seconds added to each wait.")
    ap.add_argument("--count", type=int, default=None, help="How many to send (default: all).")
    ap.add_argument("--budget-usd", type=float, default=None,
                    help="Stop once the estimated spend reaches this many USD (cost backstop; "
                         "keep it under the Gateway daily spend cap).")
    ap.add_argument("--cost-per-app", type=float, default=0.384,
                    help="Estimated USD per application for the budget cap "
                         "(Phase 3 finding: opus 0.384, mixed 0.317, sonnet 0.184).")
    ap.add_argument("--offset", type=int, default=0, help="Skip the first N pool rows.")
    ap.add_argument("--shuffle", action="store_true", help="Shuffle the pool (seeded).")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--dry-run", action="store_true", help="Print what would be sent; no calls.")
    args = ap.parse_args(argv)

    rows = _rows(args.count, args.offset, args.shuffle, args.seed)
    # Budget cap: never submit more than the estimated spend allows (stays under the
    # Gateway daily spend cap so the run never trips a 402 mid-stream).
    if args.budget_usd is not None and args.cost_per_app > 0:
        max_by_budget = int(args.budget_usd // args.cost_per_app)
        if len(rows) > max_by_budget:
            print(f"send_traffic: budget ${args.budget_usd:.2f} @ ${args.cost_per_app}/app "
                  f"→ capping {len(rows)} to {max_by_budget} applications.")
            rows = rows[:max_by_budget]
    rid = _env.revision_id()
    est_total = len(rows) * args.cost_per_app
    print(
        f"send_traffic: {len(rows)} applications (~${est_total:.2f} est) → {args.url} "
        f"(assistant={args.assistant}, rate={args.rate_seconds}s, revision={rid})"
    )
    if args.dry_run:
        for i, row in enumerate(rows):
            app = row["application"]
            print(f"  [{i}] {app['application_id']} {app['company']['legal_name']} "
                  f"({row['metadata'].get('jurisdiction')}/{row['metadata'].get('scenario')})")
        return 0

    client = get_sync_client(url=args.url, api_key=_env.api_key())
    sent = 0
    for i, row in enumerate(rows):
        app = row["application"]
        meta = row["metadata"]
        thread = client.threads.create()
        tid = thread["thread_id"]
        run = client.runs.create(
            tid,
            args.assistant,
            input={"messages": [{"role": "user", "content": _application_message(app)}]},
            metadata={
                "application_id": app["application_id"],
                "jurisdiction": meta.get("jurisdiction"),
                "industry": meta.get("industry"),
                "portal_locale": meta.get("portal_locale"),
                "revision_id": rid,
                "simulated": True,
            },
        )
        sent += 1
        print(f"  [{i}] sent {app['application_id']} ({meta.get('jurisdiction')}) "
              f"thread={tid} run={run['run_id']}  [~${sent * args.cost_per_app:.2f} est]")
        if i < len(rows) - 1:
            wait = args.rate_seconds
            if args.jitter:
                wait += random.uniform(-args.jitter, args.jitter)
            time.sleep(max(0.0, wait))

    print(f"send_traffic: done, {sent} applications submitted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
