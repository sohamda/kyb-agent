"""Upload the labeled golden dataset to LangSmith as `kyb-golden`.

Creates (or reuses) the dataset, uploads the 60 golden_v1 examples, assigns each
example to a split named after its scenario, and adds the first ~2 of each
scenario to a `sample` split for quick runs. Tags the dataset version `v1`.

    cd agent && uv run python ../evals/upload_datasets.py
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone

import _env  # noqa: F401  (loads .env + sys.path)
from langsmith import Client

DATASET_NAME = "kyb-golden"
VERSION_TAG = "v1"
SAMPLE_PER_SCENARIO = 2


def main() -> None:
    client = Client()

    rows = [json.loads(line) for line in _env.GOLDEN_V1.read_text().splitlines() if line.strip()]
    print(f"Loaded {len(rows)} golden examples from {_env.GOLDEN_V1}")

    if client.has_dataset(dataset_name=DATASET_NAME):
        dataset = client.read_dataset(dataset_name=DATASET_NAME)
        existing = list(client.list_examples(dataset_id=dataset.id))
        if existing:
            print(f"Dataset {DATASET_NAME!r} already has {len(existing)} examples; "
                  "delete it in LangSmith to re-upload. Skipping create.")
            return
    else:
        dataset = client.create_dataset(
            dataset_name=DATASET_NAME,
            description="KYB onboarding golden set v1 — labeled applications by scenario.",
        )
        print(f"Created dataset {DATASET_NAME!r} ({dataset.id})")

    # Decide splits per example: its scenario, plus `sample` for the first N/scenario.
    seen: dict[str, int] = defaultdict(int)
    payload = []
    for r in rows:
        scenario = r["metadata"]["scenario"]
        splits = [scenario]
        if seen[scenario] < SAMPLE_PER_SCENARIO:
            splits.append("sample")
        seen[scenario] += 1
        payload.append(
            {
                "inputs": r["inputs"],
                "outputs": r["outputs"],
                "metadata": r["metadata"],
                "split": splits,
            }
        )

    client.create_examples(dataset_id=dataset.id, examples=payload)
    print(f"Uploaded {len(payload)} examples.")

    # Tag this state of the dataset as v1.
    try:
        client.update_dataset_tag(
            dataset_id=dataset.id, as_of=datetime.now(timezone.utc), tag=VERSION_TAG
        )
        print(f"Tagged dataset version {VERSION_TAG!r}.")
    except Exception as e:  # noqa: BLE001
        print(f"(could not tag version {VERSION_TAG!r}: {e})")

    counts = defaultdict(int)
    for p in payload:
        for s in p["split"]:
            counts[s] += 1
    print("Splits:", dict(sorted(counts.items())))


if __name__ == "__main__":
    main()
