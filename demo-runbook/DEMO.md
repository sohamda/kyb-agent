# KYB Agent — Demo Runbook (ADLC on LangSmith)

A ~25-minute walkthrough of the **LangSmith platform across the Agent Development
Lifecycle** using the KYB onboarding agent. The agent is the vehicle; the story is
**Build → Test → Deploy → Monitor → Improve**, with **Govern** throughout.

> Everything runs on **synthetic data** and the agent ships with **intentional defects**
> (PLAN.md §4.3). Do not "fix" them in `main` — they are the demo material. The Improve
> stage is pre-staged and **left unmerged**; the live merge is the climax.

Org (all links): `https://smith.langchain.com/o/54ee2d7d-ab2d-4af9-9c6e-ebfb2ab8adc8`

---

## 0. Pre-demo checklist (morning of)

- [ ] **Spend headroom:** Gateway daily spend well under the $60 cap (policy `kyb-agent-spend-cap`). If a rehearsal burned it, it resets on the daily window.
- [ ] **Improve stage intact:** Engine issue *"Circular ownership recursion aborts reviews"* is **open** and **PR #1 is still a draft / unmerged**. If it was merged in rehearsal, regenerate: send a fresh traffic batch from the 896 unused pool apps (deterministic defects → Engine re-detects) — see PLAN.md R6b.
- [ ] **`main` = defects intact** (`git log -1` → the planted-defect commit, no fix merged).
- [ ] **Agent overview accepted** on the prod Engine board (so the UI shows all 5 issues).
- [ ] **Studio** opens the `kyb-agent` graph; have one sample application JSON ready to paste.
- [ ] Fallback tab open to this file's **§Before-state snapshot** in case any live view drifts.

---

## 1. Build (4 min)

**Open:** the repo (`agent/` — small codebase), then **Studio** on the `kyb-agent` graph.

- Show the thin agent: `agent/agent.py`, `instructions.md`, the three subagents
  (`screening-analyst`, `ownership-investigator`, `document-checker`), the `KYBDecision`
  schema, and the Gateway model id (`langsmith:anthropic/claude-opus-5-5`).
- **Run one application** in Studio: watch the plan → three subagents → tool calls →
  the **pause for compliance approval** (human-in-the-loop interrupt) → resume → a
  `KYBDecision` with risk rating + grounded rationale.

**Say:** one deep agent, every model call through the LLM Gateway, deployed as a Managed
Deep Agent — the same code runs locally, in evals, and in prod.

---

## 2. Test — offline evals (4 min)

**Open:** dataset **`kyb-golden`** and the **model-profile comparison**.

- Dataset `kyb-golden` (id `2bc98f72-de10-4905-98b3-930cb4982bc7`): 60 v1 examples with
  per-scenario splits + a `sample` split, plus the new **`v2`** split from Engine (Improve).
- **Comparison view (opus vs sonnet vs mixed):**
  `…/datasets/2bc98f72-de10-4905-98b3-930cb4982bc7/compare?selectedSessions=c2a6f085-72ef-4f81-b1f8-2f10b76f3e08&selectedSessions=2e67ccdd-8d63-46bd-87ba-09685d1d594a&selectedSessions=d20f7302-5869-40a2-bd0d-08ed57ed00d1`
  - Point at **accuracy + cost together**: `sanctions_recall` is the hard gate (must be 1.0);
    read `decision_correct`, `ubo_recall`, the judges, and **cost per run**.

**Say:** one line (`KYB_MODEL_PROFILE`) swaps the model wiring; the experiment — not a hunch —
decides whether the cheaper profile holds accuracy. Opus stays the prod baseline.

---

## 3. Deploy (3 min)

**Open:** the `kyb-agent` deployment (prod) and the Gateway policies.

- Prod Agent Server: `https://kyb-agent-prod-564866f92d5f55b4ada7bf40202c1f96.us.langgraph.app`
  (staging also deployed). Graph/assistant id `kyb-agent`.
- Show the **cron** traffic schedule and a **Context Hub** edit to a risk threshold that goes
  live **without a redeploy**.
- `revision_id` on every trace ties a run to a commit (so Engine can map traces → code).

**Say:** `mda deploy` ships the local build; Gateway policies and Context Hub are platform-level,
not code.

---

## 4. Monitor (5 min)

**Open:** the prod tracing project `kyb-agent-prod-production`
(`…/projects/p/01a12fdb-d6b4-7672-b173-28631c7e18a7`).

- **Dashboard:** the **EDD-rate spike by jurisdiction** (GB/DE — defect **D4**) and the
  **ownership tool-error** rate (**D2/D3**: `RecursionError` / `ValueError`).
- **Online evaluators** landing on live runs (5 feedback keys): `is_reject`, `is_edd`,
  `all_parties_screened` (code), `rationale_grounded` (judge @20%),
  `followed_embedded_instructions` (judge @100%, the D5 injection catch), plus
  `reviewer_agreed` (the compliance reviewer bot).
- **Alert** in Slack on the error/EDD spike.
- **Annotation queue "KYB QA"** (id `a552a79f-da7a-435c-9952-17ae40213aff`): reviewer
  disagreements + spot-checks routed in by 5 rules.

**Say:** production surfaces the harder variants the golden set never had — exactly the
signal Improve needs.

---

## 5. Improve — Engine (7 min) — the payoff

**Open:** the prod project **Engine** tab (`…/projects/p/01a12fdb-d6b4-7672-b173-28631c7e18a7?tab=5`).

Engine's first scan clustered **5 issues** mapping onto the planted defects (D1–D4) plus one
emergent. Open **"Circular ownership recursion aborts reviews"** (D2):

1. **Evidence traces** → **root cause in code** (`agent/tools/registry.py`, no cycle
   detection + tool exceptions abort the run) → the **Engine-generated draft PR #1** (walk
   the diff it wrote: cycle detection + ownership-investigator prompt + tool-error handling +
   2 new tests) → **Add offline examples** (already done → `kyb-golden` `v2`).
2. **Dataset v2 makes v1 fail and the fix pass** — the comparison:
   `…/datasets/2bc98f72-de10-4905-98b3-930cb4982bc7/compare?selectedSessions=b67db9e3-3718-45a5-88c2-5b20abd28f7d&selectedSessions=6709681e-085d-4150-88ad-e57b267dfb98`
   - **v1 (defects) = 0.000** on every assertion (all 5 crash) · **fix branch = 1.000**.
3. **Merge the draft PR live** (the climax) → deploy → the Engine issue flips to **complete**
   and stays closed.

**Say:** production failure → clustered issue → root-caused fix PR → ground-truth dataset →
v1 now fails offline, the fix passes — the ADLC loop closes itself.

---

## 6. Govern (2 min)

**Open:** Gateway policies + the Engine spend settings.

- **Gateway spend cap** `kyb-agent-spend-cap` ($60/day, block) and **rate limit**
  `kyb-agent-rate-limiting` (10 req/min) — cost per application visible on traces.
- **Engine spend limit** (LSUs) on the board; GitHub App scoped to read + PR-write only.
- **Masking** note: real KYB data would be masked client-side; this demo uses synthetic data.

**Say:** cost, rate, and fix-automation are all bounded by policy, independent of the code.

---

## Before-state snapshot (durable links/IDs — fall back here if a live view drifts)

| Thing | Value |
|---|---|
| Org / workspace | `54ee2d7d-ab2d-4af9-9c6e-ebfb2ab8adc8` |
| Prod Agent Server | `https://kyb-agent-prod-564866f92d5f55b4ada7bf40202c1f96.us.langgraph.app` (assistant `kyb-agent`) |
| Prod tracing project | session `01a12fdb-d6b4-7672-b173-28631c7e18a7` (`kyb-agent-prod-production`) |
| Dataset | `kyb-golden` = `2bc98f72-de10-4905-98b3-930cb4982bc7` (splits: per-scenario, `sample`, `v2`) |
| Test comparison (opus/sonnet/mixed) | sessions `c2a6f085…`, `2e67ccdd…`, `d20f7302…` |
| Engine board | `2d1c5d11-05f1-43f0-9e8d-c72a4bd1b2ef` (v2.1.0); issues via `GET /api/v1/platform/issues?session_id=<prod>` |
| D2 issue / PR | `f00380ca-9a03-4314-a0f4-b40a20bb5d0d` → draft **PR #1**, branch `langsmith-engine/3e34e842-…`, fix commit `608d537` |
| v2 close-the-loop experiments | v1 `kyb-v2-v1-defects-d3a9a8a3` (session `b67db9e3…`, score 0.0) · fix `kyb-v2-fix-branch-eda2a2b5` (session `6709681e…`, score 1.0) |
| Annotation queue | "KYB QA" = `a552a79f-da7a-435c-9952-17ae40213aff` |
| Gateway policies | spend-cap `0d962597-8cde-43a5-8380-25f1625e2edc` ($60/day) · rate-limit `f3a1c678-06da-4541-9d83-ca3147c79730` (10/min) |

## Live-demo gotchas

- **Don't merge PR #1 before the Improve climax** — a merged Engine issue flips to "complete"
  and can't re-stage its discovery (PLAN.md R6b).
- **Fix verification** (Engine preview replay) needs a GitHub-integration deployment; `mda deploy`
  uploads a local build, so rely on the **offline v2 comparison** above for the "fix passes" proof
  (PLAN.md R2).
- Online judges run on a **pre-5.5 Claude** (forced tool-choice; PLAN.md R8).
- Reproduce the v2 proof any time: `cd agent && uv run python ../evals/run_v2_experiment.py --label <name>`
  (from a worktree on the fix branch for the "passes" side).
