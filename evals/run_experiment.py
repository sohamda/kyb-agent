"""Run labeled KYB experiments on LangSmith, one per model profile.

    cd agent && uv run python ../evals/run_experiment.py \
        --profiles opus,sonnet,mixed --split sample --max-concurrency 4

Each profile becomes a LangSmith experiment over the `kyb-golden` dataset so you
can compare accuracy and cost in the comparison view. `sanctions_recall` is the
hard gate; the console summary flags any profile below 1.0.
"""

from __future__ import annotations

import argparse
import subprocess

import _env  # noqa: F401  (loads .env + sys.path)
from langsmith import Client, evaluate

import evaluators as E
from target import make_target, make_deployment_target

DATASET_NAME = "kyb-golden"


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=_env.REPO_ROOT, text=True
        ).strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def _split_arg(split: str) -> list[str] | None:
    # "all" means the whole dataset (no split filter).
    return None if split == "all" else [split]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--profiles", default="opus", help="comma list: opus,sonnet,mixed")
    ap.add_argument("--split", default="sample", help="sample | all | <scenario>")
    ap.add_argument("--max-concurrency", type=int, default=4)
    ap.add_argument("--repetitions", type=int, default=1)
    ap.add_argument("--target-url", default=None,
                    help="If set, evaluate a deployed Agent Server instead of in-process.")
    args = ap.parse_args()

    client = Client()
    profiles = [p.strip() for p in args.profiles.split(",") if p.strip()]
    splits = _split_arg(args.split)
    sha = _git_sha()

    data = list(client.list_examples(dataset_name=DATASET_NAME, splits=splits))
    print(f"Dataset {DATASET_NAME!r}: {len(data)} examples (split={args.split}) | revision={sha}")

    summary: dict[str, dict] = {}
    for profile in profiles:
        target = (
            make_deployment_target(args.target_url) if args.target_url else make_target(profile)
        )
        print(f"\n=== profile={profile} ===")
        result = evaluate(
            target,
            data=data,
            evaluators=[*E.CODE_EVALUATORS, *E.JUDGE_EVALUATORS],
            summary_evaluators=E.SUMMARY_EVALUATORS,
            experiment_prefix=f"kyb-{profile}-v1",
            metadata={"profile": profile, "revision_id": sha, "split": args.split},
            max_concurrency=args.max_concurrency,
            num_repetitions=args.repetitions,
        )
        summary[profile] = _collect(result)

    _print_summary(summary)


def _collect(result) -> dict:
    """Average each feedback key across the experiment's rows."""
    totals: dict[str, float] = {}
    counts: dict[str, int] = {}
    for row in result:
        for res in row["evaluation_results"]["results"]:
            if res.score is None:
                continue
            totals[res.key] = totals.get(res.key, 0.0) + float(res.score)
            counts[res.key] = counts.get(res.key, 0) + 1
    return {k: totals[k] / counts[k] for k in totals}


def _print_summary(summary: dict[str, dict]) -> None:
    keys = sorted({k for s in summary.values() for k in s})
    print("\n==================== SUMMARY (mean scores) ====================")
    header = "metric".ljust(26) + "".join(p.ljust(12) for p in summary)
    print(header)
    for k in keys:
        row = k.ljust(26) + "".join(f"{summary[p].get(k, float('nan')):<12.3f}" for p in summary)
        print(row)
    print("\nHard gate — sanctions_recall must be 1.0:")
    for p, s in summary.items():
        val = s.get("sanctions_recall")
        flag = "OK" if val == 1.0 else "FAIL"
        print(f"  {p:8} sanctions_recall={val}  [{flag}]")


if __name__ == "__main__":
    main()
