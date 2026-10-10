"""Evaluators for the KYB offline experiments.

Code evaluators score the agent's structured decision against the dataset's
reference labels. LLM-judge evaluators (routed through the LLM Gateway) grade the
rationale. A summary evaluator reports reject/EDD precision & recall across the run.
"""

from __future__ import annotations

import functools
import json
from typing import Any

import _env  # noqa: F401  (loads .env + sys.path)
from langchain.chat_models import init_chat_model
from pydantic import BaseModel, Field

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _out(run) -> dict:
    return run.outputs or {}


def _ref(example) -> dict:
    return example.outputs or {}


def _norm(name: str) -> str:
    return " ".join(name.lower().split())


# --------------------------------------------------------------------------- #
# Code evaluators  (signature: run, example)
# --------------------------------------------------------------------------- #

def decision_correct(run, example) -> dict:
    return {
        "key": "decision_correct",
        "score": int(_out(run).get("decision") == _ref(example).get("decision")),
    }


def risk_rating_correct(run, example) -> dict:
    return {
        "key": "risk_rating_correct",
        "score": int(_out(run).get("risk_rating") == _ref(example).get("risk_rating")),
    }


def ubo_recall(run, example) -> dict:
    """Fraction of reference UBOs matched by name with |pct| <= 1.0."""
    ref = _ref(example).get("ubos", []) or []
    got = _out(run).get("ubos", []) or []
    if not ref:
        return {"key": "ubo_recall", "score": 1.0}
    got_by_name = {_norm(u.get("name", "")): u.get("effective_ownership_pct") for u in got}
    found = 0
    for r in ref:
        g = got_by_name.get(_norm(r.get("name", "")))
        if g is not None and abs(float(g) - float(r.get("effective_ownership_pct", 0))) <= 1.0:
            found += 1
    return {"key": "ubo_recall", "score": found / len(ref)}


def sanctions_recall(run, example) -> dict:
    """Hard gate: never miss a true sanctions match.

    1.0 when there is nothing to catch; otherwise 1.0 only if the agent rejected
    AND raised the sanctions_match flag.
    """
    ref_sanctioned = _ref(example).get("sanctioned_parties", []) or []
    if not ref_sanctioned:
        return {"key": "sanctions_recall", "score": 1.0}
    out = _out(run)
    caught = out.get("decision") == "reject" and "sanctions_match" in (out.get("flags") or [])
    return {"key": "sanctions_recall", "score": int(bool(caught))}


def escalated_when_required(run, example) -> dict:
    """Trajectory check: the run paused for compliance iff it should have."""
    expected = bool(_ref(example).get("escalation_required"))
    actual = bool(_out(run).get("escalated"))
    return {"key": "escalated_when_required", "score": int(expected == actual)}


# --------------------------------------------------------------------------- #
# LLM-judge evaluators (via LLM Gateway)
# --------------------------------------------------------------------------- #

class _Grade(BaseModel):
    score: float = Field(description="Score between 0 and 1.")
    reasoning: str = Field(description="One or two sentences.")


@functools.lru_cache(maxsize=1)
def _judge():
    return init_chat_model("langsmith:anthropic/claude-sonnet-5-5").with_structured_output(
        _Grade, method="json_schema"
    )


def rationale_grounded(run, example) -> dict:
    """Every factual claim in the rationale is backed by the tool evidence."""
    out = _out(run)
    rationale = out.get("rationale", "")
    trajectory = json.dumps(out.get("trajectory", []))[:6000]
    if not rationale:
        return {"key": "rationale_grounded", "score": 0.0, "comment": "no rationale"}
    prompt = (
        "You check whether a KYB decision rationale is grounded in tool evidence.\n"
        "Score 1.0 if every factual claim in the rationale is supported by the tool "
        "evidence below; lower the score for claims with no support.\n\n"
        f"TOOL EVIDENCE (delegated subagent results and tool calls):\n{trajectory}\n\n"
        f"RATIONALE:\n{rationale}"
    )
    g = _judge().invoke(prompt)
    return {"key": "rationale_grounded", "score": float(g.score), "comment": g.reasoning[:300]}


def rationale_quality(run, example) -> dict:
    """Does the rationale clearly justify the decision with specific evidence?"""
    out = _out(run)
    rationale = out.get("rationale", "")
    if not rationale:
        return {"key": "rationale_quality", "score": 0.0, "comment": "no rationale"}
    prompt = (
        "Grade this KYB decision rationale for quality. Score 1.0 if it clearly "
        "justifies the stated decision and cites specific evidence (registry fields, "
        "watchlist entries, ownership percentages, documents); lower it if vague or "
        "unsupported.\n\n"
        f"DECISION: {out.get('decision')} (risk {out.get('risk_rating')}), "
        f"flags {out.get('flags')}\n\nRATIONALE:\n{rationale}"
    )
    g = _judge().invoke(prompt)
    return {"key": "rationale_quality", "score": float(g.score), "comment": g.reasoning[:300]}


# --------------------------------------------------------------------------- #
# Summary evaluator  (signature: runs, examples)
# --------------------------------------------------------------------------- #

def _prf(runs, examples, label: str) -> tuple[float, float]:
    tp = fp = fn = 0
    for run, ex in zip(runs, examples):
        pred = (run.outputs or {}).get("decision") == label
        gold = (ex.outputs or {}).get("decision") == label
        tp += pred and gold
        fp += pred and not gold
        fn += gold and not pred
    precision = tp / (tp + fp) if (tp + fp) else 1.0
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    return precision, recall


def decision_precision_recall(runs, examples) -> dict:
    results: list[dict] = []
    for label in ("reject", "enhanced_due_diligence"):
        p, r = _prf(runs, examples, label)
        short = "reject" if label == "reject" else "edd"
        results.append({"key": f"{short}_precision", "score": p})
        results.append({"key": f"{short}_recall", "score": r})
    return {"results": results}


CODE_EVALUATORS = [
    decision_correct,
    risk_rating_correct,
    ubo_recall,
    sanctions_recall,
    escalated_when_required,
]
JUDGE_EVALUATORS = [rationale_grounded, rationale_quality]
SUMMARY_EVALUATORS = [decision_precision_recall]
