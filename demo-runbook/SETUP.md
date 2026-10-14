# Build this from scratch

A linear, copy-pasteable guide to stand up the **KYB Onboarding Agent** and the full
LangSmith ADLC loop on **your own** LangSmith workspace. It assumes you clone this repo
(the agent code, simulator, and evals are the artifact — you don't rewrite them) and
reproduce the running system: build → test → deploy → monitor → improve → govern.

> Everything runs on **synthetic data**. The agent ships with **intentional defects**
> (D1–D5, see [PLAN.md §4.3](PLAN.md)) — they are the material for the Monitor/Improve
> stages. **Do not "fix" them in `main`.** The guide tells you where they surface.

For the design rationale behind each step, read [`PLAN.md`](PLAN.md); for the ~25-minute
live walkthrough, read [`DEMO.md`](DEMO.md). This file is the recipe.

---

## 0. What you'll end up with

- A Managed Deep Agent deployed to a LangSmith **staging** and **prod** Agent Server, every
  model call routed through the **LLM Gateway**.
- A labeled golden dataset (`kyb-golden`) and offline experiments comparing model profiles.
- Synthetic production traffic flowing in, with online evaluators, a dashboard, and a
  reviewer bot producing human feedback.
- An **Engine** board that clusters the planted defects into issues, writes fix PRs, and
  closes the loop into a dataset `v2`.
- Govern controls: Gateway spend/rate policies, and the CI gate + manual-approval deploy
  in [`.github/workflows/`](../.github/workflows/).

Architecture and the business flow are in the [root README](../README.md).

---

## 1. Prerequisites

### Accounts & platform access
- **LangSmith account** on **Cloud** (this demo was built on the **GCP US** region).
- **Managed Deep Agents (MDA)** beta access enabled for your workspace.
- **LLM Gateway** enabled for your workspace.
- A **Gateway provider secret**: add `ANTHROPIC_API_KEY` as a **workspace secret** on the
  Gateway (LangSmith → Gateway → Secrets). The Gateway holds provider keys, **not** the
  project. Without it, model calls fail with
  `424 "Required workspace secret ANTHROPIC_API_KEY is missing"`.
- **Engine** enabled for the workspace (an org-admin action) if you want the Improve stage.
- A **GitHub repo** you own (fork/clone this one). For Engine's PR flow, install the
  **LangChain GitHub App** on it.

### Local tooling
- [`uv`](https://docs.astral.sh/uv/) (manages Python + deps; the `mda` CLI comes with the
  project deps).
- `git`, and optionally `gh` (GitHub CLI) for the Govern stage.
- Python is provisioned by `uv` (project requires `>=3.11`).

### Keys you'll need in hand
| Key | Where it comes from | Used for |
|-----|--------------------|----------|
| `LANGSMITH_API_KEY` | LangSmith → Settings → API Keys | tracing, datasets, experiments, `mda` deploy, Engine API |
| `LANGSMITH_GATEWAY_API_KEY` | LangSmith → Gateway → API Keys | model calls through the Gateway |

---

## 2. Clone & install

```bash
git clone https://github.com/<you>/kyb-agent.git
cd kyb-agent/agent
uv sync                 # installs managed-deepagents, langchain-openai, langgraph, langsmith
```

All later commands run from `agent/` through `uv run` so the project environment (and the
`mda` CLI) is on the path.

---

## 3. Configure credentials

```bash
cp agent/.env.example agent/.env
# edit agent/.env and fill in LANGSMITH_API_KEY and LANGSMITH_GATEWAY_API_KEY
```

**Values must be unquoted.** A quoted `LANGSMITH_GATEWAY_API_KEY` is the most common
first-run failure. `agent/.env` is gitignored.

Smoke-test the Gateway path (one call to each model id should return with token usage):

```bash
cd agent
uv run python -c "from langchain.chat_models import init_chat_model as m; \
print(m('langsmith:anthropic/claude-sonnet-5-5').invoke('ping').content[:40])"
```

---

## 4. Generate the synthetic world  *(Build)*

Creates the data the agent's tools read (`agent/data/`) and the labeled applications used
for the dataset and production traffic (`simulator/out/`).

```bash
python3 simulator/generate_world.py            # stdlib only; from the repo root
```

Produces: `agent/data/*.json` (registry, watchlists, media, customers) and
`simulator/out/{golden_v1,hard_cases,traffic_pool}.jsonl`. Deterministic (`--seed`,
default 7); regenerate with `--traffic N` to change the pool size. The hidden
ground-truth `label` on each application is never sent to the agent.

---

## 5. Run locally & smoke-test  *(Build)*

```bash
cd agent
uv run mda dev --no-browser --no-reload        # local LangGraph dev server + Studio
```

In Studio, send a user message whose content is one application JSON under an
`application` key (copy one from `simulator/out/golden_v1.jsonl`). The agent plans,
delegates to the three subagents, pauses at the compliance interrupt for sanctions cases,
and returns a `KYBDecision`.

> Don't run `mda build` while `mda dev` is live — it rewrites the watched build venv and
> crashes the dev server.

---

## 6. Offline evals  *(Test)*

```bash
cd agent
uv run python ../evals/upload_datasets.py                       # create kyb-golden (60 ex, splits, v1)
uv run python ../evals/run_experiment.py \
    --profiles opus,sonnet,mixed --split sample --max-concurrency 4
# then --split all for the full 60
```

The target builds the agent **in-process** (no deploy needed). Compare the three profiles
in the LangSmith **comparison view** on accuracy **and cost per run**. `sanctions_recall`
is the hard gate (must be 1.0). Add `--require-sanctions-recall` to make the run exit
non-zero if any profile misses — this is what the CI gate uses (§11).

Model profiles live in `agent/models.py`, selected by `KYB_MODEL_PROFILE` (default
`opus`). The golden set is deliberately incomplete — it lacks the harder production
variants, so v1 passes here and ships. That gap is the whole point of the loop.

---

## 7. Deploy  *(Deploy)*

```bash
cd agent
uv run mda deploy --name kyb-agent-staging                      # safe target for CI / Engine replays
uv run mda deploy --name kyb-agent-prod --deployment-type prod  # takes simulated traffic
```

Each prints its Agent Server URL (`https://kyb-agent-<...>.us.langgraph.app`). `.env`
values are forwarded on deploy; no provider keys are needed (the Gateway holds them).
Operate with `uv run mda logs` / `uv run mda delete`.

**Set Gateway policies before sending traffic** (LangSmith → Gateway → Policies; see
[PLAN.md §5 Govern](PLAN.md)):
- a **spend policy** — a daily cap on the deployment's Gateway key (the cost backstop;
  returns `402` when hit). This demo used **$60/day**.
- a **rate-limit policy** — e.g. 10 req/min (one application ≈ 5–8 Gateway calls).

---

## 8. Send production traffic  *(Monitor)*

```bash
cd agent
# smoke test first: 2 apps against staging
uv run python ../simulator/send_traffic.py --count 2 --rate-seconds 2 \
    --url https://kyb-agent-staging-<...>.us.langgraph.app

# then drip to prod, budget-bounded
uv run python ../simulator/send_traffic.py --budget-usd 40 --shuffle --rate-seconds 90

# in a second terminal: resume compliance-paused runs like a human officer
uv run python ../simulator/reviewer_bot.py \
    --url https://kyb-agent-prod-<...>.us.langgraph.app
```

`send_traffic.py` submits only the `application` (never the label), tagging each run with
metadata (`jurisdiction`, `industry`, `revision_id`, `simulated=true`) for dashboards and
Engine scoping. `reviewer_bot.py` approves real sanctions matches / rejects false
positives, errs ~5% of the time, and logs `reviewer_agreed` SDK feedback — a high-priority
signal for Engine.

> **Watch your budget.** A full pool collides with the daily Gateway cap. Size the run
> against remaining daily spend, or slow the rate. The `402` cap is the backstop.

---

## 9. Monitor  *(Monitor)*

In the prod tracing project, configure (see [PLAN.md §5 Monitor](PLAN.md); reference
implementations in `evals/online_evaluators.py`):
- **Online evaluators** — code metrics (`is_reject`, `is_edd`, `all_parties_screened`) and
  an LLM judge. The online code-evaluator contract is `def perform_eval(run):`. The judge
  model must support forced tool calls through the Gateway — use a **pre-5.5 Claude** for
  the judge.
- A **custom dashboard** — EDD rate by jurisdiction (surfaces D4), tool-error rate
  (D2/D3), decision mix, latency.
- Optional: **Slack alerts** and an **annotation queue**.

The planted defects (PLAN §4.3) now surface here: GB/DE EDD spike (D4), ownership
tool-error rate (D2/D3), missed transliterated sanctions (D1).

---

## 10. Improve with Engine  *(Improve)*

1. In the LangSmith UI, turn **Engine** on for the **prod** tracing project, connect the
   GitHub repo, and **accept the generated agent overview**. Scope it with
   `run_filter = metadata.simulated == true` so it only analyzes simulated traffic.
   (The board can also be created via the API: `POST /api/v1/platform/sessions/{SID}/issues-agent`;
   see [PLAN.md §6 Phase 6](PLAN.md) for the exact payload.)
2. Let Engine scan. It clusters the failing traces into **issues** mapping to the defects
   (circular-ownership crash, ownership-unit misparse, missed transliteration, document
   dates → false EDD, decisions omitting evidence).
3. Open an issue → review the evidence traces and root cause → open its **draft PR** (the
   fix Engine wrote) → **Add offline examples** to pull the production inputs into
   `kyb-golden` as the **`v2`** split (reference = Engine *assertions*).
4. **Close the loop** with the v2 harness:

   ```bash
   # v1 (current tree, defects intact) — expect failures (0.0)
   cd agent && uv run python ../evals/run_v2_experiment.py --label v1-defects

   # Engine's fix branch (check it out in a worktree first) — expect pass (1.0)
   cd <worktree>/agent && uv run python ../evals/run_v2_experiment.py --label fix-branch
   ```

   Both land on `kyb-golden` for a side-by-side comparison. **Merging the PR flips the
   Engine issue to "complete."**

> **Replay-safe rule:** the merge is one-shot — a completed issue can't re-stage its
> discovery. For a repeatable demo, generate the issue + draft PR + v2 examples but **hold
> the merge** until you're live. For a clean second run, send a fresh batch from the unused
> pool apps (defects are deterministic, so Engine re-detects).

---

## 11. Govern  *(Govern)*

The CI/CD is already in [`.github/workflows/`](../.github/workflows/):
- **`evals.yml`** — PR eval gate: runs the offline evals in-process on every PR, failing on
  a v2 assertion regression (`--fail-under 1.0`) or a sanctions miss
  (`--require-sanctions-recall`). This is what turns Engine's fix PR green.
- **`deploy.yml`** — `mda deploy` to prod on push to `agent/**` (and manual dispatch),
  gated behind a GitHub **Environment** so nothing ships without approval.

To activate them:
1. Add repo **secrets** (Settings → Secrets and variables → Actions):
   `LANGSMITH_API_KEY` and `LANGSMITH_GATEWAY_API_KEY`.
2. Create an **Environment** named `production` (Settings → Environments) with **Required
   reviewers = you** — that reviewer prompt is the manual deploy approval.
3. Optionally enable **branch protection** on `main` requiring the `evals.yml` check — now
   a sanctions regression *cannot* merge.

Round out Govern in the console: Gateway spend/rate/fallback policies, cost per
application, an Engine project spend limit, and Context Hub edit history.

---

## Appendix — the planted defects (do not fix in `main`)

| # | Where | Bug | Surfaces in |
|---|-------|-----|-------------|
| D1 | `screen_name` | Raw similarity ≥0.92, no transliteration | missed transliterated sanctions → wrongly approved |
| D2 | `compute_effective_ownership` | No cycle detection | `RecursionError` on circular ownership |
| D3 | ownership parsing | `float(value)`, ignores `ownership_unit` | Cyprus `ValueError`; Dutch owners mis-scaled (hides a sanctioned owner) |
| D4 | `check_document` | Parses dates as `%m/%d/%Y` only | GB/DE dates fail/swap → EDD spike |
| D5 | `instructions.md` | No untrusted-input rule | some injected applications approved |

These are intentional and are the raw material for Monitor/Improve. See
[PLAN.md §4.3](PLAN.md) for the full catalog.
