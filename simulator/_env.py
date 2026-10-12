"""Load LangSmith + Gateway credentials from agent/.env for the traffic scripts.

`send_traffic.py` and `reviewer_bot.py` talk to the deployed Agent Server and
log feedback to LangSmith, so they need the workspace API key. This module
loads the (gitignored) ``agent/.env`` into ``os.environ`` without printing any
values, and exposes the common paths. It never imports the agent package — the
simulator stays decoupled from the deployed code.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
AGENT_DIR = REPO_ROOT / "agent"
SIMULATOR_DIR = REPO_ROOT / "simulator"
OUT_DIR = SIMULATOR_DIR / "out"
TRAFFIC_POOL = OUT_DIR / "traffic_pool.jsonl"

# Default prod Agent Server (override with --url).
PROD_URL = "https://kyb-agent-prod-564866f92d5f55b4ada7bf40202c1f96.us.langgraph.app"
ASSISTANT = "kyb-agent"


def load_env() -> None:
    """Load agent/.env into os.environ (unquoting values); never prints them."""
    env_path = AGENT_DIR / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key.strip(), value)


def api_key() -> str:
    key = os.environ.get("LANGSMITH_API_KEY")
    if not key:
        raise SystemExit("LANGSMITH_API_KEY not set (expected in agent/.env).")
    return key


def revision_id() -> str:
    """Deployed code version to tag on each run (R3 mitigation).

    Prefer an explicit LANGSMITH_REVISION_ID; otherwise the current git SHA.
    """
    rid = os.environ.get("LANGSMITH_REVISION_ID")
    if rid:
        return rid
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=str(REPO_ROOT), text=True
        ).strip()
    except Exception:
        return "unknown"


load_env()
