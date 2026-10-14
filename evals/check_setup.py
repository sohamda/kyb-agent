"""Validate a from-scratch SETUP.md setup against the live LangSmith workspace.

Runs the same API/CLI probes used to verify the demo by hand, as a repeatable,
staged preflight. Run it after each SETUP.md stage — later checks SKIP cleanly
until the thing they test exists.

    cd agent && uv run python ../evals/check_setup.py
    cd agent && uv run python ../evals/check_setup.py --deployment-url https://kyb-agent-prod-....us.langgraph.app
    cd agent && uv run python ../evals/check_setup.py --skip-model   # no Gateway spend

Exit code is non-zero if any hard check FAILs (WARN/SKIP do not fail the run), so
the script also works as a gate. Nothing here mutates anything.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import _env  # noqa: F401  (loads agent/.env + puts agent/ on sys.path)

PASS, WARN, FAIL, SKIP = "PASS", "WARN", "FAIL", "SKIP"
_MARK = {PASS: "✓", WARN: "!", FAIL: "✗", SKIP: "-"}

REQUIRED_ENV = [
    "LANGSMITH_API_KEY",
    "LANGSMITH_GATEWAY_API_KEY",
    "LANGSMITH_GATEWAY",
    "LANGSMITH_TRACING",
    "LANGSMITH_PROJECT",
]
DATA_FILES = ["registry.json", "sanctions.json", "sanctions_additions.json",
              "pep.json", "media.json", "customers.json"]
OUT_FILES = ["golden_v1.jsonl", "hard_cases.jsonl", "traffic_pool.jsonl"]


class Report:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str, str, str | None]] = []
        self._stage = ""

    def stage(self, name: str) -> None:
        self._stage = name

    def add(self, status: str, check: str, detail: str, hint: str | None = None) -> None:
        self.rows.append((self._stage, status, check, detail, hint))
        line = f"  [{_MARK[status]}] {check}: {detail}"
        print(line)
        if hint and status in (WARN, FAIL):
            print(f"        -> {hint}")

    def header(self, name: str) -> None:
        self.stage(name)
        print(f"\n== {name} ==")

    def summarize(self) -> int:
        counts = {s: sum(1 for r in self.rows if r[1] == s) for s in (PASS, WARN, FAIL, SKIP)}
        print(f"\n==== {counts[PASS]} pass · {counts[WARN]} warn · "
              f"{counts[FAIL]} fail · {counts[SKIP]} skip ====")
        if counts[FAIL]:
            print("FAILED checks:")
            for stage, status, check, detail, _ in self.rows:
                if status == FAIL:
                    print(f"  - [{stage}] {check}: {detail}")
        return 1 if counts[FAIL] else 0


# --- Stage 1: credentials & env (SETUP.md §3) --------------------------------

def check_env(r: Report) -> None:
    r.header("Credentials & env (§3)")
    env_path = _env.AGENT_DIR / ".env"
    if not env_path.exists():
        r.add(FAIL, "agent/.env", "missing",
              "cp agent/.env.example agent/.env and fill in the keys")
        return
    r.add(PASS, "agent/.env", "present")

    # Raw-read to catch quoted values (load_env strips quotes, so os.environ hides them).
    raw = {}
    for ln in env_path.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if ln and not ln.startswith("#") and "=" in ln:
            k, v = ln.split("=", 1)
            raw[k.strip()] = v.strip()

    for key in REQUIRED_ENV:
        val = os.environ.get(key)
        if not val:
            r.add(FAIL, key, "not set", "add it to agent/.env (see .env.example)")
            continue
        rawval = raw.get(key, "")
        quoted = len(rawval) >= 2 and rawval[0] == rawval[-1] and rawval[0] in "\"'"
        if quoted:
            r.add(WARN, key, "set but QUOTED in .env",
                  "remove the surrounding quotes — quoted values break Gateway auth")
        else:
            r.add(PASS, key, "set")

    if os.environ.get("LANGSMITH_GATEWAY", "").lower() != "true":
        r.add(WARN, "LANGSMITH_GATEWAY", f"= {os.environ.get('LANGSMITH_GATEWAY')!r} (expected 'true')",
              "set LANGSMITH_GATEWAY=true so langsmith: model ids route through the Gateway")


# --- Stage 2: LangSmith auth (§3) --------------------------------------------

def check_langsmith_auth(r: Report) -> "object | None":
    r.header("LangSmith auth (§3)")
    if not os.environ.get("LANGSMITH_API_KEY"):
        r.add(SKIP, "LangSmith API", "no LANGSMITH_API_KEY")
        return None
    try:
        from langsmith import Client
        client = Client()
        next(iter(client.list_datasets(limit=1)), None)  # forces an authenticated request
        r.add(PASS, "LangSmith API", f"authenticated ({client.api_url})")
        return client
    except Exception as e:  # noqa: BLE001
        r.add(FAIL, "LangSmith API", f"auth failed: {_short(e)}",
              "check LANGSMITH_API_KEY (workspace key, unquoted)")
        return None


# --- Stage 3: Gateway model call — the 424 check (§3) ------------------------

def check_gateway(r: Report, skip_model: bool, all_models: bool) -> None:
    r.header("LLM Gateway (§3)")
    if skip_model:
        r.add(SKIP, "Gateway model call", "--skip-model (no spend)")
        return
    try:
        from models import PROFILES
        ids = [PROFILES["sonnet"]["main"]]
        if all_models:
            ids.append(PROFILES["opus"]["main"])
    except Exception:  # noqa: BLE001
        ids = ["langsmith:anthropic/claude-sonnet-5-5"]

    try:
        from langchain.chat_models import init_chat_model
    except Exception as e:  # noqa: BLE001
        r.add(FAIL, "Gateway", f"cannot import init_chat_model: {_short(e)}")
        return

    for mid in ids:
        try:
            resp = init_chat_model(mid).invoke("ping")
            usage = getattr(resp, "usage_metadata", None) or {}
            tok = usage.get("total_tokens")
            r.add(PASS, f"Gateway · {mid.split('/')[-1]}",
                  f"returned ({tok} tokens)" if tok else "returned")
        except Exception as e:  # noqa: BLE001
            msg = str(e).lower()
            if "424" in msg or "workspace secret" in msg or "anthropic_api_key" in msg:
                hint = "add ANTHROPIC_API_KEY as a Gateway WORKSPACE SECRET (not in .env)"
            elif "402" in msg:
                hint = "Gateway spend cap hit (402) — raise/reset the spend policy"
            elif any(s in msg for s in ("401", "403", "unauthor", "authentic", "api key")):
                hint = "check LANGSMITH_GATEWAY_API_KEY (unquoted) and that the Gateway is enabled"
            else:
                hint = "verify the Gateway is enabled for this workspace"
            r.add(FAIL, f"Gateway · {mid.split('/')[-1]}", _short(e), hint)


# --- Stage 4: synthetic world (§4) -------------------------------------------

def check_data(r: Report) -> None:
    r.header("Synthetic world (§4)")
    data_dir = _env.AGENT_DIR / "data"
    missing = [f for f in DATA_FILES if not (data_dir / f).exists()]
    if missing:
        r.add(FAIL, "agent/data", f"missing {', '.join(missing)}",
              "run: python3 simulator/generate_world.py")
    else:
        r.add(PASS, "agent/data", f"{len(DATA_FILES)} files present")

    out_dir = _env.SIMULATOR_DIR / "out"
    missing = [f for f in OUT_FILES if not (out_dir / f).exists() or (out_dir / f).stat().st_size == 0]
    if missing:
        r.add(FAIL, "simulator/out", f"missing/empty {', '.join(missing)}",
              "run: python3 simulator/generate_world.py")
    else:
        r.add(PASS, "simulator/out", f"{len(OUT_FILES)} files present")


# --- Stage 5: dataset kyb-golden (§6) ----------------------------------------

def check_dataset(r: Report, client, dataset_name: str) -> None:
    r.header("Golden dataset (§6)")
    if client is None:
        r.add(SKIP, dataset_name, "no LangSmith client")
        return
    try:
        if not client.has_dataset(dataset_name=dataset_name):
            r.add(WARN, dataset_name, "not found",
                  "run: cd agent && uv run python ../evals/upload_datasets.py")
            return
        total = sum(1 for _ in client.list_examples(dataset_name=dataset_name))
        r.add(PASS if total >= 60 else WARN, dataset_name,
              f"{total} examples" + ("" if total >= 60 else " (expected ~60)"))
        sample = sum(1 for _ in client.list_examples(dataset_name=dataset_name, splits=["sample"]))
        r.add(PASS if sample else WARN, f"{dataset_name} · sample split", f"{sample} examples")
        v2 = sum(1 for _ in client.list_examples(dataset_name=dataset_name, splits=["v2"]))
        if v2:
            r.add(PASS, f"{dataset_name} · v2 split", f"{v2} examples (Engine close-the-loop)")
        else:
            r.add(SKIP, f"{dataset_name} · v2 split", "none yet (created by Engine in §10)")
    except Exception as e:  # noqa: BLE001
        r.add(FAIL, dataset_name, _short(e))


# --- Stage 6: deployment (§7) ------------------------------------------------

def check_deployments(r: Report, urls: list[str], assistant: str) -> None:
    r.header("Deployment (§7)")
    if not urls:
        r.add(SKIP, "Agent Server", "no --deployment-url given")
        return
    try:
        from langgraph_sdk import get_sync_client
    except Exception as e:  # noqa: BLE001
        r.add(FAIL, "Agent Server", f"langgraph_sdk import failed: {_short(e)}")
        return
    key = os.environ.get("LANGSMITH_API_KEY")
    for url in urls:
        label = url.split("//")[-1].split(".")[0]
        try:
            c = get_sync_client(url=url, api_key=key)
            found = list(c.assistants.search(graph_id=assistant, limit=1))
            if found:
                r.add(PASS, f"deploy · {label}", f"reachable, assistant {assistant!r} present")
            else:
                r.add(WARN, f"deploy · {label}", f"reachable, but no assistant {assistant!r}",
                      "check the --name used in `mda deploy`")
        except Exception as e:  # noqa: BLE001
            r.add(FAIL, f"deploy · {label}", _short(e),
                  "check the URL and that the deployment is live (uv run mda logs)")


# --- Stage 7: Engine board (§10, optional) -----------------------------------

def check_engine(r: Report, client, session_id: str | None, tenant_id: str | None) -> None:
    r.header("Engine board (§10, optional)")
    if not session_id:
        r.add(SKIP, "Engine", "no --session-id (prod tracing session) given")
        return
    try:
        import requests
        base = (client.api_url if client is not None
                else os.environ.get("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com"))
        headers = {"X-API-Key": os.environ.get("LANGSMITH_API_KEY", "")}
        if tenant_id:
            headers["X-Tenant-Id"] = tenant_id
        resp = requests.get(f"{base}/api/v1/platform/issues",
                            params={"session_id": session_id}, headers=headers, timeout=30)
        if resp.status_code != 200:
            r.add(WARN, "Engine issues", f"HTTP {resp.status_code}",
                  "Engine may need a PAT as X-API-Key and the workspace tenant id")
            return
        issues = resp.json()
        issues = issues.get("issues", issues) if isinstance(issues, dict) else issues
        n = len(issues) if isinstance(issues, list) else 0
        r.add(PASS if n else SKIP, "Engine issues",
              f"{n} issue(s) on session {session_id}" if n else "board reachable, no issues yet")
    except Exception as e:  # noqa: BLE001
        r.add(WARN, "Engine", _short(e), "optional — configure Engine in the UI (§10)")


def _short(e: object, n: int = 160) -> str:
    s = " ".join(str(e).split())
    return s[:n] + ("…" if len(s) > n else "")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--deployment-url", action="append", default=[],
                    help="Agent Server URL to probe (repeatable: staging and prod).")
    ap.add_argument("--assistant", default="kyb-agent")
    ap.add_argument("--dataset", default="kyb-golden")
    ap.add_argument("--skip-model", action="store_true",
                    help="Skip the Gateway model call (no spend).")
    ap.add_argument("--all-models", action="store_true",
                    help="Also call the opus model id, not just sonnet.")
    ap.add_argument("--session-id", default=os.environ.get("LANGSMITH_PROD_SESSION_ID"),
                    help="Prod tracing session id, to check the Engine board (optional).")
    ap.add_argument("--tenant-id", default=os.environ.get("LANGSMITH_TENANT_ID"),
                    help="Workspace tenant id for the Engine API (optional).")
    args = ap.parse_args()

    print("KYB setup validation — probing the live LangSmith workspace (read-only).")
    r = Report()
    check_env(r)
    client = check_langsmith_auth(r)
    check_gateway(r, args.skip_model, args.all_models)
    check_data(r)
    check_dataset(r, client, args.dataset)
    check_deployments(r, args.deployment_url, args.assistant)
    check_engine(r, client, args.session_id, args.tenant_id)
    raise SystemExit(r.summarize())


if __name__ == "__main__":
    main()
