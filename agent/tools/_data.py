"""Load the bundled synthetic world data.

All tools read from ``agent/data/*.json``. The files ship inside the deployment
build, so lookups never reach an external service. Results are cached per
process because the data is immutable at runtime.
"""

from __future__ import annotations

import functools
import json
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


@functools.lru_cache(maxsize=None)
def load(name: str) -> Any:
    """Load and cache one JSON file from the data directory."""
    with (DATA_DIR / name).open(encoding="utf-8") as fh:
        return json.load(fh)
