"""Load LangSmith + Gateway credentials from agent/.env and expose project paths.

The eval scripts run from the agent's environment but live outside the agent
package. This module loads the (gitignored) ``agent/.env`` into ``os.environ``
without printing any values, and puts the agent package on ``sys.path`` so the
evals can import the real tools, subagents and schema.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
AGENT_DIR = REPO_ROOT / "agent"
SIMULATOR_DIR = REPO_ROOT / "simulator"
GOLDEN_V1 = SIMULATOR_DIR / "out" / "golden_v1.jsonl"


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


def ensure_paths() -> None:
    """Make the agent package importable (tools, subagents, schemas, models)."""
    for p in (AGENT_DIR, SIMULATOR_DIR):
        sp = str(p)
        if sp not in sys.path:
            sys.path.insert(0, sp)


load_env()
ensure_paths()
