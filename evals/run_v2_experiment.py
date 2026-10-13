"""Close the ADLC loop: run the KYB agent over Engine's **v2** examples.

Engine (Phase 6) turned the circular-ownership production failures into golden
`kyb-golden` examples under the **`v2`** split. Those examples carry the deployed
run's ``messages`` input and, as reference, Engine's **assertions** (named claims
about a correct answer, e.g. "completes with a KYBDecision instead of a
RecursionError"), not v1's structured labels — so this script scores against the
assertions instead of the v1 evaluators.

    # v1 (current tree, planted defects intact) — expect failures
    cd agent && uv run python ../evals/run_v2_experiment.py --label v1-defects

    # Engine's fix branch (run from a worktree checked out on that branch) — expect pass
    cd <worktree>/agent && uv run python ../evals/run_v2_experiment.py --label fix-branch

The two experiments land on `kyb-golden` for a side-by-side comparison view.
"""

from __future__ import annotations

import argparse
import subprocess

import _env  # noqa: F401  (loads .env + sys.path)
from langsmith import Client, evaluate

from target import make_target

DATASET_NAME = "kyb-golden"

# Coded checks for Engine's assertion keys. Each maps an assertion key to a
# predicate over the agent's output dict (or None when the run errored).
_CHECKS = {
    "must_return_kyb_decision": lambda o: bool(o and o.get("decision")),
    "must_flag_opaque_ownership": lambda o: bool(o and "opaque_ownership" in (o.get("flags") or [])),
    "must_recommend_enhanced_due_diligence":
        lambda o: bool(o and o.get("decision") == "enhanced_due_diligence"),
}


def assertions_eval(run, example) -> dict:
    """Score each of the example's Engine assertions against the run output.

    Returns one feedback per assertion key plus an overall ``assertions_passed``
    fraction. A target that errored (e.g. the D2 ``RecursionError`` on v1) has no
    output, so every assertion scores 0 — exactly the "v1 fails on v2" signal.
    """
    outputs = run.outputs or {}
    assertions = (example.outputs or {}).get("assertions") or []
    results = []
    scored = []
    for a in assertions:
        key = a.get("key")
        check = _CHECKS.get(key)
        if check is None:
            # Unknown assertion key: no coded predicate — leave unscored (would
            # need an LLM judge). None of the current v2 keys hit this path.
            results.append({"key": key, "score": None, "comment": "no coded check"})
            continue
        passed = int(bool(check(outputs)))
        scored.append(passed)
        results.append({"key": key, "score": passed, "comment": a.get("comment", "")})
    if scored:
        results.append({"key": "assertions_passed", "score": sum(scored) / len(scored)})
    return {"results": results}


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=_env.REPO_ROOT, text=True
        ).strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--label", required=True, help="experiment label, e.g. v1-defects | fix-branch")
    ap.add_argument("--profile", default="opus", help="model profile (opus|sonnet|mixed)")
    ap.add_argument("--split", default="v2")
    ap.add_argument("--max-concurrency", type=int, default=3)
    args = ap.parse_args()

    client = Client()
    sha = _git_sha()
    data = list(client.list_examples(dataset_name=DATASET_NAME, splits=[args.split]))
    print(f"Dataset {DATASET_NAME!r} split={args.split}: {len(data)} examples | "
          f"label={args.label} profile={args.profile} revision={sha}")

    result = evaluate(
        make_target(args.profile),
        data=data,
        evaluators=[assertions_eval],
        experiment_prefix=f"kyb-v2-{args.label}",
        metadata={"label": args.label, "profile": args.profile, "revision_id": sha, "split": args.split},
        max_concurrency=args.max_concurrency,
    )

    # Local tally
    totals: dict[str, float] = {}
    counts: dict[str, int] = {}
    for row in result:
        for res in row["evaluation_results"]["results"]:
            if res.score is None:
                continue
            totals[res.key] = totals.get(res.key, 0.0) + float(res.score)
            counts[res.key] = counts.get(res.key, 0) + 1
    print("\n==== v2 assertion scores (mean) ====")
    for k in sorted(totals):
        print(f"  {k:42} {totals[k]/counts[k]:.3f}")


if __name__ == "__main__":
    main()
