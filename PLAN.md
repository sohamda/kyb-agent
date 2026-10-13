# KYB Onboarding Agent: LangSmith ADLC Demo Plan

## 1. What we're building

A **Know-Your-Business (KYB) onboarding agent** for a fictional payments company. Each time a business applies for an account, the agent:

1. checks that the application matches the company registry,
2. works out who ultimately owns the company (through nested shareholders),
3. screens every director and owner against sanctions and politically-exposed-person (PEP) lists and adverse media,
4. returns a structured decision: **approve**, **enhanced due diligence (EDD)**, or **reject**, with a risk rating and a rationale.

A confirmed sanctions match pauses the run for human approval. A small reviewer bot plays the compliance officer who resumes it.

There is no chat UI. Runs come from a traffic simulator (standing in for the onboarding portal) and a nightly re-screening cron job.

The agent is the vehicle. The point of the demo is the **LangSmith platform across the Agent Development Lifecycle** (Build → Test → Deploy → Monitor → Improve, with Govern across all of them). It's deployed as a **Managed Deep Agent** on **LangSmith Cloud (GCP US)**, and every model call goes through **LLM Gateway**.

```
simulator/send_traffic.py ──runs.create──┐
schedules/nightly_rescreen.py ──cron─────┤
simulator/reviewer_bot.py ──resume───────┤
                                         ▼
                     kyb-agent (Managed Deep Agent, prod) ──model calls──▶ LLM Gateway
                     main agent: plan → delegate → decide                  (spend, rate limits,
                       ├─ task → document-checker                           fallbacks)
                       ├─ task → ownership-investigator
                       ├─ task → screening-analyst
                       └─ escalate_to_compliance   (human approval)
                                         │ traces
                                         ▼
                     LangSmith tracing project
                       ├─ online evaluators ──▶ feedback scores
                       ├─ reviewer-bot feedback (SDK) ──▶ feedback scores
                       ├─ dashboards + alerts ──▶ Slack
                       ├─ annotation queue ──▶ corrected dataset examples
                       └─ Engine ──▶ issues ──▶ GitHub PR + offline examples
                                                   │
                     CI: offline experiment on PR ◀┘ ──▶ mda deploy
```

## 2. Design principles

- **Keep agent code small.** Target about 300–400 lines of Python in the agent itself. Tools are plain functions over bundled JSON files, with no external services. The complexity lives in the platform, not in the code.
- **Synthetic world with ground truth.** One generator produces the mock registry, sanctions/PEP lists and news corpus, plus labeled applications. The labels become datasets; the same generator drives production traffic.
- **Plant realistic defects in v1.** Ship v1 with a handful of believable bugs (section 4.3) so Engine has real, recurring issues to find, diagnose and fix with a PR.
- **Make golden dataset v1 deliberately incomplete.** It covers the "expected" cases, so v1 passes offline evals and ships. Production traffic includes harder variants the dataset lacks. The demo payoff is the ADLC loop: production failures → Engine → new offline examples → dataset v2 → v1 now fails offline, the fix passes → redeploy.
- **Use only fictional people and companies.** No real sanctioned individuals appear anywhere in the data.

**Out of scope for now:** Harbor evals, the webhook (HTTP channel) trigger, Red Teaming.

## 3. The agent

### 3.1 Repository layout

```
demo_cert/
├── agent/                          # Managed Deep Agents project (what gets deployed)
│   ├── agent.py                    # define_deep_agent(...)
│   ├── instructions.md             # system prompt → synced to Context Hub
│   ├── skills/
│   │   ├── risk-rating/SKILL.md    # risk matrix + decision mapping → Context Hub
│   │   └── edd-triggers/SKILL.md   # what forces EDD / reject → Context Hub
│   ├── subagents.py                # 3 subagent dicts
│   ├── schemas.py                  # KYBDecision (structured output)
│   ├── tools/
│   │   ├── registry.py             # lookup_company_registry, compute_effective_ownership
│   │   ├── screening.py            # screen_name, search_adverse_media
│   │   ├── documents.py            # check_document
│   │   └── compliance.py           # escalate_to_compliance (human approval required)
│   ├── data/                       # generated: registry.json, sanctions.json, pep.json, media.json
│   ├── memory.py                   # agent memory layer (procedural learnings only)
│   ├── schedules/nightly_rescreen.py
│   ├── pyproject.toml
│   └── .env
├── simulator/                      # not deployed
│   ├── generate_world.py           # world data + labeled applications
│   ├── send_traffic.py             # production traffic → deployment
│   └── reviewer_bot.py             # resumes paused runs as a "compliance officer"
├── evals/                          # LangSmith offline evals (not deployed)
│   ├── upload_datasets.py
│   ├── evaluators.py
│   ├── target.py                   # calls a deployment; auto-resumes paused runs
│   └── run_experiment.py
└── .github/workflows/evals.yml     # PR → deploy staging → experiment → gate
```

The simulator and evals live outside `agent/` so `mda deploy` doesn't package them.

### 3.2 Agent definition (sketch)

```python
# agent/agent.py
from managed_deepagents import define_deep_agent
from schemas import KYBDecision
from subagents import document_checker, ownership_investigator, screening_analyst
from tools.compliance import escalate_to_compliance

agent = define_deep_agent(
    name="kyb-agent",
    model="langsmith:anthropic/claude-opus-5-5",   # via LLM Gateway; comparison: claude-sonnet-5-5
    subagents=[document_checker, ownership_investigator, screening_analyst],
    tools=[escalate_to_compliance],
    interrupt_on={"escalate_to_compliance": {"allowed_decisions": ["approve", "reject"]}},
    response_format=KYBDecision,
)
```

`instructions.md`, `skills/`, `memory.py` and `schedules/` are discovered from project files; the agent definition doesn't reference them.

Subagents leave `model` unset, so they use the main agent's Gateway model. Phase 0 checks whether a subagent can take its own `langsmith:` model ID (useful for a cheaper subagent model).

### 3.3 Subagents

| Subagent | Tools | Job | Returns |
|---|---|---|---|
| `document-checker` | `lookup_company_registry`, `check_document` | Compare the application to the registry record (name, registration number, address, directors). Check document expiry. | Mismatches found |
| `ownership-investigator` | `lookup_company_registry`, `compute_effective_ownership` | Walk corporate shareholders recursively. Find every person with 25% or more effective ownership, and flag opaque or circular structures. | Ownership tree and list of ultimate owners with percentages |
| `screening-analyst` | `screen_name`, `search_adverse_media` | Screen every director and owner. Rule out false positives using date of birth and nationality. | Per-person result: clear / possible match / confirmed match |

The main agent plans with `write_todos`, delegates, applies the `risk-rating` and `edd-triggers` skills, calls `escalate_to_compliance` on a confirmed sanctions match, and returns `KYBDecision`.

### 3.4 Output contract

```python
class UBO(BaseModel):
    name: str
    effective_ownership_pct: float

class KYBDecision(BaseModel):
    application_id: str
    decision: Literal["approve", "enhanced_due_diligence", "reject"]
    risk_rating: Literal["low", "medium", "high"]
    ubos: list[UBO]
    screened_parties: list[str]          # lets an online code evaluator check coverage
    flags: list[Literal["sanctions_match", "pep", "adverse_media", "document_mismatch",
                        "expired_document", "opaque_ownership", "high_risk_jurisdiction",
                        "high_risk_industry", "embedded_instructions"]]
    rationale: str                       # must cite tool evidence
```

### 3.5 Context, memory and human approval

- **`instructions.md`** holds the role, the workflow and the output contract. It also says to treat document text as untrusted data. v1 leaves that line weak on purpose; see defect D5.
- **Skills** hold the risk matrix and EDD triggers. They sync to **Context Hub**, so a compliance lead can change a threshold in the UI without a code redeploy. This is a showcase moment.
- **Memory** (agent layer, `/memories/agent/`) stores procedural learnings only, for example "registry for jurisdiction X reports ownership as a 0–1 fraction". It never stores personal data.
- **Human approval:** `escalate_to_compliance` pauses the run.
  - **Live demo:** resume the paused run by hand in Studio.
  - **Bulk traffic:** `reviewer_bot.py` handles it.
  - **Offline evals:** `evals/target.py` auto-approves and records that an escalation happened.

### 3.6 Reviewer bot

`simulator/reviewer_bot.py` runs alongside the traffic simulator:

1. Every minute, it lists threads on the prod deployment that are paused for approval (`threads.search(status="interrupted")`).
2. For each one, it looks up the application's hidden ground-truth label in `traffic_pool.jsonl` and decides like a reasonably accurate compliance officer: approve a true sanctions match, reject a false one. It deliberately errs about 5% of the time.
3. It resumes the run through the Agent Server API.
4. It logs **SDK feedback** on the run: `reviewer_agreed` (0/1) and an optional comment. Engine treats this feedback as a high-priority signal when choosing traces to analyze, so the bot also showcases human feedback.

### 3.7 Triggers

| Trigger | Mechanism | Why |
|---|---|---|
| New application | `simulator/send_traffic.py` → Agent Server `runs.create` with metadata (`jurisdiction`, `industry`, `revision_id`, `simulated=true`) | Full control of metadata for dashboards and Engine scope, and of thread IDs for resuming |
| Nightly re-screening (ongoing KYC) | `schedules/nightly_rescreen.py` (managed cron) | Shows schedules: re-screen recently approved customers against the latest sanctions additions |

## 4. Synthetic world and traffic

### 4.1 Generated data (Phase 1, done)

Run `python3 simulator/generate_world.py` (stdlib only, seed 7, deterministic). It writes:

| File | Contents |
|---|---|
| `agent/data/registry.json` | 1,652 companies: officers, shareholders (people or companies), `ownership_unit`, `shareholders_disclosed` |
| `agent/data/sanctions.json` | 30 fictional entries with aliases, birth dates, nationalities |
| `agent/data/pep.json` | 30 fictional PEPs |
| `agent/data/media.json` | 261 articles (adverse ones for the adverse-media cases, plus neutral background news) |
| `agent/data/customers.json` | 150 existing customers, for the nightly re-screen |
| `agent/data/sanctions_additions.json` | 6 new listings: 2 exact hits, 1 transliterated hit, 1 false positive, 2 unrelated |
| `simulator/out/golden_v1.jsonl` | 60 dataset examples (`inputs`, `outputs`, `metadata`, `split`) |
| `simulator/out/hard_cases.jsonl` | 40 labeled production-only cases; a fallback for dataset v2 if Engine hasn't proposed enough by demo day |
| `simulator/out/traffic_pool.jsonl` | 1,000 production applications; labels are kept aside and never sent to the agent |
| `simulator/out/rescreen_expected.json` | Expected re-screen hits |
| `simulator/out/summary.json` | Counts by scenario, jurisdiction and decision |

`simulator/policy.py` holds the ground-truth rules (decision mapping, effective-ownership math, thresholds). The generator labels cases with it, and the evaluators will score with it. The agent never imports it; the same rules go into the skills as prose.

### 4.2 Scenario mix

Golden v1 was built "at launch", when Northwind only onboarded **US** businesses. Production traffic is 76% US, 15% GB and 9% DE. GB and DE applications come from portals that render document dates day-first (`DD/MM/YYYY`, `DD.MM.YYYY`).

| Scenario | Expected decision | Golden v1 | Production (of 1,000) |
|---|---|---|---|
| Clean business | approve | 24 | 510 |
| PEP director or shareholder | EDD (high) | 6 | 70 |
| Sanctioned director or shareholder, exact name | reject + escalate | 6 | 30 |
| Sanctioned owner hidden 2–3 holding companies up, left off the declared owners | reject + escalate | — | 40 |
| Same name as a sanctioned person, different date of birth and nationality | approve | 6 | 60 |
| Transliterated name of a sanctioned person (Aleksandr/Alexander, Jürgen/Juergen) | reject + escalate | — | 40 |
| Circular ownership, or an offshore holding company that hides its shareholders | EDD (high) | — | 40 |
| Document mismatch: address, unregistered director, or expired passport | EDD (medium) | 9 | 80 |
| Held through a Cypriot (`"35%"`) or Dutch (`0.35`) holding company | approve | — | 50 |
| High-risk industry, or offshore holding company in VG/SC/PA | EDD (medium) | 6 | 30 |
| Adverse media about the company or a director | EDD (high) | 3 | 20 |
| Injected instruction in notes or document text, on top of a PEP, sanctions or document problem | as the underlying problem, plus `embedded_instructions` | — | 30 |

A dash means the scenario is absent from golden v1 on purpose. Engine and annotation review add those examples later, which is the point of the demo.

### 4.3 Planted defects in v1

All four tool defects were checked against the generated data, and none of them touches golden v1.

| # | Where | Defect | Measured effect on the 1,000 production applications | How it's caught |
|---|---|---|---|---|
| D1 | `screen_name` | Raw-string similarity ≥ 0.92 with no normalization or transliteration | All 40 transliterated sanctioned names missed → approved instead of rejected | Engine, reviewer-bot disagreements, annotation queue |
| D2 | `compute_effective_ownership` | No cycle detection | 19 of the circular-ownership cases crash with `RecursionError` | Tool-error alert, Engine "Tool Call Failures" |
| D3 | ownership parsing | `float(value)` and ignores the record's `ownership_unit` | 24 Cyprus cases fail with `ValueError`. 26 Dutch cases get the wrong owners, which **hides the sanctioned owner in 18 of the 40 hidden-sanctions cases** | Tool-error alert, Engine |
| D4 | `check_document` | Parses expiry dates as `%m/%d/%Y` only | Every DE date fails; about 58% of GB dates fail and the rest parse with day and month swapped → unverifiable documents → EDD spike for GB/DE | Dashboard (EDD rate by jurisdiction), Engine |
| D5 | `instructions.md` | No explicit rule that application and document text is untrusted | Some injected applications approved | Online LLM judge, Engine |

## 5. LangSmith features by ADLC stage

### Build
- **Managed Deep Agents project:** `mda init`, `define_deep_agent`, subagents, skills, instructions, memory, `interrupt_on`, `response_format`.
- **LLM Gateway for every model call:** `langsmith:provider/model` model IDs, no provider keys in the project, and every model call also shows up in the `gateway` tracing project.
- **LangSmith Studio** via `mda dev`: step through a run, inspect the plan, subagent calls and tool calls, and resume a paused run.
- **Tracing** is on from the first local run.
- **Context Hub:** instructions and skills are versioned there, with commit history visible.

### Test (offline)
- **Datasets:** `kyb-golden` with **splits** per scenario and **version tags** (`v1`, later `v2`).
- **Code evaluators:**
  - `decision_correct`
  - `risk_rating_correct`
  - `ubo_recall` (set match with ±1% tolerance)
  - `sanctions_recall`: any missed sanctioned party scores 0; this is the hard gate
  - `escalated_when_required`: did the run pause for approval when it should have (trajectory check)
- **LLM-as-judge evaluators:** `rationale_grounded` (every claim backed by tool output) and `rationale_quality` against the reference. Judges also call models through LLM Gateway (`init_chat_model` pointed at `https://gateway.smith.langchain.com/v1` with the LangSmith API key).
- **Summary evaluator:** precision and recall for reject/EDD across the whole experiment.
- **Experiments:** run v1 as the baseline. Use **comparison view** for v1 vs the fix and for Opus 5.5 vs Sonnet 5.5 (cost, latency, accuracy). Switching models is just a different Gateway model ID. Use `num_repetitions=3` to show nondeterminism.
- **CI gate:** a GitHub Action on each PR deploys to staging, runs the experiment, and fails if `sanctions_recall < 1.0` or `decision_correct` regresses.

### Deploy
- `mda deploy --name kyb-agent-staging`: this is the safe target for CI and Engine replays.
- `mda deploy --name kyb-agent-prod --deployment-type prod`: this takes simulator traffic.
- **Agent Server API:** threads, runs, and resuming paused runs (used by the reviewer bot).
- **Cron schedule** for nightly re-screening.
- **Secrets** via `.env`, forwarded on deploy. No model-provider keys are needed because the Gateway holds them.
- **Code version on traces:** record `revision_id` so Engine can tie each trace to a commit (see risk R3).

### Monitor
- **Tracing project** per deployment, filtered by metadata (`jurisdiction`, `industry`, `revision_id`).
- **Online evaluators** on the prod project:
  - `rationale_grounded` (LLM judge, 20% sample)
  - `followed_embedded_instructions` (LLM judge on all runs; catches D5)
  - `all_parties_screened` (code: input parties vs `screened_parties`)
  - `is_reject` / `is_edd` (code, 0/1) so dashboards can chart decision rates
- **SDK feedback** from the reviewer bot: `reviewer_agreed`.
- **Custom dashboard:**
  - runs per hour
  - decision mix
  - EDD rate by jurisdiction (surfaces D4)
  - tool error rate by tool (surfaces D2 and D3)
  - p50/p95 latency
  - cost per application
  - online-eval scores
  - `reviewer_agreed` rate
  - count of paused-for-approval runs
- **Gateway monitoring:** spend and request volume per model and per API key.
- **Alerts** to Slack or webhook: tool-error rate above 5% over 15 minutes, `rationale_grounded` average below 0.8, p95 latency above threshold.
- **Annotation queue "KYB QA":**
  - **What's routed in:** every reject/EDD, runs with a low judge score or `reviewer_agreed = 0`, and 10% of approvals.
  - **Rubric:** decision correct (yes/no), correct decision, notes.
  - **Output:** corrected runs become dataset examples.
- **LangSmith Chat** for questions like "why did EDD rate jump yesterday for GB applications?"

### Improve (Engine)
- **Setup:** an org admin enables Engine. Turn it on for the prod tracing project and connect this GitHub repo. Review and accept the generated **agent overview**.
- **Focus areas:** pick **Tool Call Failures**, and add custom concerns: "missed sanctions or PEP matches", "wrong ownership percentages", "following instructions embedded in documents".
- **Feedback boosts Engine:** Engine treats online-evaluator, annotation-queue and SDK feedback (the reviewer bot) as high-priority signals when choosing traces.
- **Notifications** to a Slack channel.
- **Per issue, Engine generates the fix:** for each issue Engine clusters the failing traces, **writes the fix diff itself**, and **Open PR** opens a *draft* PR with that change on a branch the LangChain GitHub App creates (read access to the repo, write access only to open PRs). A **"Open a draft PR for every fix"** setting (`auto_open_fix_pr`) can make this automatic. Engine then replaces **Open PR** with **View PR #\<n>** and mirrors the PR's open/merged/closed status on the issue. Use **Add offline examples** to pull the production trace inputs into `kyb-golden` as `v2`.
- **Close the loop:** run v1 on `v2` and it fails, run the PR branch and it passes, merge, `mda deploy`. **Merging flips the Engine issue to "complete"** (and it reopens only if the failure recurs). Engine keeps the issue current by attaching new matching traces until it's fixed.
- **Replay-safe demo rule (important):** the merge is the only one-shot step — a *completed* issue can't re-stage its own discovery live. So for the demo, run Phase 6 in **dress-rehearsal mode: generate the issue + draft PR + v2 examples, but DO NOT merge** until the live demo, where the merge is the climax. For a clean second run after a merge, send a fresh batch from the 896 unused pool apps (defects are deterministic, so Engine re-detects), or run the generate/merge loop against **staging** (separate Engine board) and keep the **prod** issue list pristine and unmerged for the demo. Scope Engine with `run_filter` = `metadata.simulated = true`.
- **Fix validation** (private beta, optional): replay issue traces against the staging baseline ("Test issue"). See risk R2 for the preview-deployment caveat.

### Govern (across all stages)
- **LLM Gateway policies:**
  - a **spend policy** (daily cap on the deployment's key, which caps simulator cost);
  - a **rate-limit policy**;
  - a **fallback chain** (primary model → backup from another provider);
  - a **model access policy** so only approved models can be called.
- **Cost:** cost per trace and per application in the agent project, plus Gateway spend.
- **Engine spend limit** (LSUs) per project.
- **Audit:** Context Hub commit history for skill and threshold changes.
- **Retention:** extended trace retention on the prod project.
- **Masking:** note in the demo that real KYB data would be masked client-side. This demo uses synthetic data, so Engine can read full traces.

## 6. Implementation phases

> **Progress log — updated 2026-10-10.** Phase 2 agent code is written, unit-tested
> and compiles (`mda build` ✓). The Gateway path is live end-to-end (both model IDs
> return). Still open: a full run in Studio, Engine enablement, and deploy.
>
> **Build findings worth keeping:**
> - **Project directory:** the deployed project lives in `agent/` (per the §3.1
>   layout). The `mda init` scaffold was created as `kyb-agent/` and then merged into
>   `agent/`; `kyb-agent/` is gone. Deploy name is still `kyb-agent`.
> - **Gateway model resolution:** `model="langsmith:anthropic/claude-opus-5-5"` resolves
>   through `init_chat_model` → `langchain-openai`'s `ChatOpenAI` pointed at
>   `https://gateway.smith.langchain.com/v1`. This made **`langchain-openai` a required
>   dependency** (added to `pyproject.toml`); it is not pulled in by `managed-deepagents`
>   alone. The Gateway key is read from `LANGSMITH_GATEWAY_API_KEY`; `LANGSMITH_GATEWAY=true`.
> - **Provider secret is workspace-side, not in `.env`:** the Gateway needs an
>   `ANTHROPIC_API_KEY` **LangSmith workspace secret**. With it missing the call returns
>   `424 "Required workspace secret ANTHROPIC_API_KEY is missing"`; with a bad value,
>   Anthropic returns `401 invalid x-api-key`. Both are now resolved — one test call to
>   each model ID succeeds (addresses R8/R9 credential setup). No provider key goes in
>   the project `.env`.
> - **`.env` quoting gotcha:** key values had been saved wrapped in double quotes, which
>   anything not using python-dotenv sends literally → `401 Unauthorized`. Both keys were
>   un-quoted. Keep `.env` values unquoted.
> - **SDK API vs the §3.2 sketch:** subagents use **`system_prompt`** (not `prompt`);
>   `interrupt_on={"escalate_to_compliance": {"allowed_decisions": ["approve","reject"]}}`
>   matches `InterruptOnConfig`; `response_format=KYBDecision` is accepted (Auto strategy).
> - **No sandbox:** tools are pure functions over bundled JSON, so the `sandbox/` scaffold
>   was deleted (one sandbox fewer to pay attention to, per the skill's guidance).
> - **Nightly re-screen needs a tool:** with no sandbox/filesystem the agent can't read
>   `customers.json` directly, so a read-only `list_customers_for_rescreen` tool was added
>   and wired to the main agent; the schedule prompt calls it.

**Phase 0: Access and spike (blocking)**
- [x] LangSmith Cloud workspace in GCP US
- [x] LLM Gateway available for model access
- [x] Models: **Claude Opus 5.5** for the agent (`langsmith:anthropic/claude-opus-5-5`), **Claude Sonnet 5.5** for the comparison experiment (`langsmith:anthropic/claude-sonnet-5-5`)
- [x] Gateway has an Anthropic provider secret and the key authenticates; one test call to **each** model ID succeeds (Opus 5.5 and Sonnet 5.5 both return via Gateway, with token usage). Required: the `ANTHROPIC_API_KEY` workspace secret + unquoted `LANGSMITH_GATEWAY_API_KEY` in `.env`.
- [x] Managed Deep Agents (public beta) access confirmed; `managed-deepagents==0.9.0` installed, project scaffolded, and `mda build` compiles the managed app.
- [ ] Org admin enables **Engine**; set a spend limit. Install the LangChain GitHub App on a new repo. *(not started — org-admin task)*
- [ ] Spike: deploy a hello-world MDA agent using a `langsmith:` model, then confirm:
  - (a) runs keep SDK-supplied metadata, *(not yet verified — needs a deploy)*
  - (b) `revision_id` reaches traces, *(not yet verified — needs a deploy; see R3)*
  - (c) a paused run can be resumed through the API — **verified.** The sanctions case pauses on `escalate_to_compliance` with an `action_requests` payload and resumes via `runs.wait(..., command={"resume": {"decisions": [{"type": "approve"}]}})`, then returns the final decision.
  - (d) whether a subagent can use its own `langsmith:` model ID — **verified (R7 resolved).** Set `document-checker` and `ownership-investigator` to `langsmith:anthropic/claude-sonnet-5-5` via the `SubAgent` `model` field; golden cases still decided correctly, and traces show both `anthropic/claude-opus-5-5` (main + screening-analyst) and `anthropic/claude-sonnet-5-5` (the two mechanical subagents) firing.
  - (e) `response_format` on Opus 5.5 — **cleared (R8 resolved).** A full `mda dev` run on a clean golden application (APP-5265BB31) returns a valid `KYBDecision` matching the label (approve / low). Required **two fixes**: (1) wrap the schema in `ProviderStrategy(KYBDecision)` — the default ToolStrategy forces `tool_choice`, which Anthropic-via-Gateway rejects with `tool_choice: type "tool" and "any" are not supported`; (2) add `model_config = ConfigDict(extra="forbid")` to `KYBDecision` and `UBO` — the Gateway's strict JSON-schema requires `additionalProperties: false` on every object.

**Phase 1: Synthetic world**
- [x] `generate_world.py` + `policy.py`: registry, watchlists, news, customer book, `golden_v1.jsonl`, `hard_cases.jsonl`, `traffic_pool.jsonl` (section 4.1). Defects D1–D4 checked against the data.

**Phase 2: Agent v1**
- [x] Tools (`registry`, `screening`, `documents`, `compliance`, `customers`), 3 subagents, `KYBDecision` schema, `instructions.md`, two skills (`risk-rating`, `edd-triggers`) and `memory.py` written. Defects **D1–D5 unit-verified** against the real data: D1 transliteration miss (0.875 < 0.92), D2 `RecursionError` on cyclic ownership, D3 Cyprus `ValueError` / NL fraction mis-scale, D4 DE/GB date parse failures and day/month swap, D5 deliberately weak untrusted-data line in `instructions.md`. Project compiles with `mda build`.
- [x] Iterate in Studio with `mda dev` until golden v1 cases look right by hand. Four golden cases now return the correct `KYBDecision` end-to-end (all three subagents delegating): **clean** APP-5265BB31 (approve/low), **pep** APP-58A28354 (EDD/high, `[pep]`), **document_mismatch** APP-4D19CE0E (EDD/medium, `[document_mismatch]`), and **sanctioned_direct** APP-D8B6BE1F (reject/high, `[sanctions_match]`, with the escalation pause→approve→resume cycle). Harder production-only variants (transliteration, hidden/circular ownership, locale dates) are intentionally not in golden v1.

**Phase 3: Offline evals**
- [x] Upload `kyb-golden` v1 with splits. 60 examples in LangSmith, split per scenario
  plus a `sample` split (~2/scenario = 14), tagged `v1`. (`evals/upload_datasets.py`)
- [x] Evaluators + target. Code: `decision_correct`, `risk_rating_correct`, `ubo_recall`
  (±1%), `sanctions_recall` (hard gate), `escalated_when_required`; LLM judges via Gateway:
  `rationale_grounded`, `rationale_quality`; summary: reject/EDD precision+recall.
  (`evals/evaluators.py`) Target runs the agent **in-process** via `create_deep_agent`,
  resumes the escalation interrupt, records `escalated` + a trajectory; also supports a
  `--target-url` deployment mode for later. (`evals/target.py`, `evals/run_experiment.py`)
- [~] Baseline + model comparison. **Sample sweep (14) done for opus/sonnet/mixed.** Full
  60 and the CI workflow deferred (user chose to stop at the sample). Model wiring is now
  profile-driven via `agent/models.py` (`KYB_MODEL_PROFILE`, default `opus`).

  **Findings (2026-10-10, 14-case sample):** all three profiles score 1.0 on
  `decision_correct`, `risk_rating_correct`, `ubo_recall`, `sanctions_recall` (gate) and
  `escalated_when_required` — accuracy ties on the easy golden cases. Cost/latency differ:

  | profile | avg cost/app | avg latency | vs opus |
  |---|---|---|---|
  | opus   | $0.384 | 42.3s | baseline |
  | sonnet | $0.184 | 28.7s | −52% cost, −32% latency |
  | mixed  | $0.317 | 41.1s | −18% cost |

  **The main agent dominates cost, not the subagents** — so the two-tier `mixed` config is
  a weak lever (−18%); the big win is the main agent's model (`sonnet` −52%). Caveat: the
  sample is the *easy* golden cases; `sonnet` on the main agent (judgment) is least tested
  here, and the genuinely hard variants are production-only (absent from golden v1), so this
  does **not** yet justify switching the main agent off Opus. `rationale_grounded` is low
  (~0.4–0.5) across all profiles — an eval artifact (the judge sees only subagent summaries,
  not raw tool outputs), not an agent regression.

**Phase 4: Deploy** — ✅ **DONE (2026-10-12).**
- [x] Deploy staging and prod; the cron schedule is reconciled.
  - [x] **Staging deployed & verified (2026-10-12).** `mda deploy --name kyb-agent-staging
    --deployment-type dev --workspace-id 54ee2d7d-…` → DEPLOYED. Agent Server
    `https://kyb-agent-staging-bcb8bd9b991751d8b253d58ecee502d8.us.langgraph.app`. Verified
    end-to-end against the live server: clean → approve/low; sanctioned_direct → reject/high
    `[sanctions_match]` with the escalation **interrupt + API resume**. **The deployed
    runtime authenticates to the Gateway via the forwarded `LANGSMITH_GATEWAY_API_KEY`
    secret** (no auto-injection needed) — the open R3-adjacent question is resolved.
    Cron reconciled on deploy (this PAT can't list crons — verify in the Deployments UI).
    Workspace id (tenant) = `54ee2d7d-ab2d-4af9-9c6e-ebfb2ab8adc8`; not in `.env`, passed via flag.
  - [x] **Prod deployed & verified (2026-10-12).** `mda deploy --name kyb-agent-prod
    --deployment-type prod --workspace-id 54ee2d7d-…` → DEPLOYED. Agent Server
    `https://kyb-agent-prod-564866f92d5f55b4ada7bf40202c1f96.us.langgraph.app`. Same live
    smoke check as staging passed: clean → approve/low; sanctioned_direct → reject/high
    `[sanctions_match]` with escalation **interrupt + API resume**. (The `mda deploy` CLI is
    gated as a "Production Deploy" by the permission classifier — the user runs/approves it.)
- [x] **Gateway policies set (2026-10-12, before prod traffic).** *(LangSmith Gateway UI /
  Govern — not a CLI step.)*
  - **`kyb-agent-spend-cap`** — $60/day spend limit on `kyb-gateway-key` (the cost backstop;
    returns `402` when hit). Set before prod per the user's "spend cap first" decision.
  - **`kyb-agent-rate-limiting`** — 10 req/min on `kyb-gateway-key` (burst ceiling; `429` on
    exceed). Note: one application = ~5–8 Gateway calls, so keep offline eval reruns at
    `--max-concurrency 1–2` to avoid self-throttling.
  - [ ] **Fallback chain** (primary opus-5-5 → sonnet-5-5 on 429/5xx) — optional, not yet set;
    good Govern-demo material (§7.6) but not required for traffic.

**Phase 5: Monitor** — ✅ **configured & validated (2026-10-13); cost-capped traffic run executed.**
- [x] **Traffic simulator built & verified on prod (2026-10-12).**
  - `simulator/send_traffic.py` — reads `traffic_pool.jsonl`, submits each **application only**
    (never the hidden `label`) to the deployment with `runs.create`, tagging metadata
    (`application_id`, `jurisdiction`, `industry`, `portal_locale`, `revision_id`,
    `simulated=true`). Throttle via `--rate-seconds` (default 300 = ~290/day); `--count`,
    `--offset`, `--shuffle`, `--dry-run`. **`--budget-usd` + `--cost-per-app`** cap the run to
    an estimated spend so it stops *before* the Gateway daily cap trips a `402`.
  - `simulator/reviewer_bot.py` — polls `threads.search(status="interrupted")`, matches each
    paused thread to its ground-truth label by `application_id`, resumes (`approve` a true
    sanctions match / `reject` a false positive) with a ~5% deliberate error rate, and logs
    SDK feedback **`reviewer_agreed`** (1 = approved the escalation) on the **decision run**.
    `--max-idle-polls` lets it self-exit after a bounded run drains (do **not** set it low
    during live traffic — escalations are sparse, so quiet minutes ≠ drained).
  - **Two-run gotcha (important for online evals & dashboards):** an escalated app yields
    **two root runs** — the first pauses at the interrupt (`structured_response` is None, has
    the send-time metadata) and the **resume run carries the decision** but, by default, **no
    metadata**. Fix: `reviewer_bot` re-attaches metadata (`simulated=true`, `jurisdiction`,
    `revision_id`, `resumed=true`) on the resume `runs.wait`, so the decision-bearing run is
    scopeable; `perform_eval` returns `{}` for the pre-decision run; feedback is attached to
    the latest (decision) run. Verified live on prod (2026-10-12).
  - `simulator/_env.py` — shared `.env` loader + prod URL + `revision_id()` (git SHA, R3).
  - **End-to-end smoke passed:** one sanctioned app → agent escalated → paused → bot resumed
    (approve) → final **reject/high `[sanctions_match]`**, `reviewer_agreed=1.0` on the trace
    (session `01a12fdb-…`). Run from `agent/`: `uv run python ../simulator/send_traffic.py …`.
- [x] **Online evaluators configured & validated (2026-10-13)** on the prod project — reference
  impls in `evals/online_evaluators.py`; configured as online rules (code `kyb-decision-metrics`:
  `is_reject`/`is_edd`/`all_parties_screened`; LLM-judges `rationale_grounded` @20% +
  `followed_embedded_instructions` @100% = the D5 catch). All five keys confirmed landing on
  live runs. *(UI step.)*
  - **Judge model caveat (R8 again, 2026-10-12):** the managed LLM-judge adds the score
    schema as structured output → forced `tool_choice`, which **Opus/Sonnet 5.5 reject**
    (400). The managed judge runs the model *natively* (workspace secret), not via the
    Gateway, so the judge model must support forced tool calls — use a **pre-5.5 Claude**
    (Sonnet 4 / 3.7 / 3.5, reusing `ANTHROPIC_API_KEY`) or an OpenAI model (new
    `OPENAI_API_KEY` secret). Judge model ≠ agent model is fine.
  - **Online-evaluator config gotchas (2026-10-12, found via the burst):**
    1. **Code evaluator signature:** the *online* contract is `def perform_eval(run):`
       (ONE arg). A two-arg `(run, example)` trips the dataset-style result parser, and
       LangSmith then logs only the first declared key with a **null score** (symptom:
       `is_reject` score=None, `is_edd`/`all_parties_screened` missing). `online_evaluators.py`
       is now one-arg. Return a `{metric: score}` dict; multiple keys = multiple feedback.
    2. **LLM-judge feedback key:** the feedback key comes from the judge's *schema/template*,
       not its name. Creating a judge from the **Conciseness template** and only renaming the
       evaluator leaves the key as `conciseness` (both judges collided on it). Set the
       feedback key explicitly (or build from a blank custom evaluator).
    3. Online evaluators **don't backfill** unless toggled at creation — new keys appear only
       on new runs.
  - **Burst verification (2026-10-12):** sent 8 mixed apps to prod to populate the metrics;
    confirmed traffic + reviewer-bot metadata propagation end-to-end. A couple of runs hit
    `status=error` (expected — planted tool defects D2/D3 crashing on ownership edge cases).
- [x] **Custom dashboard, alerts (Slack), annotation queue "KYB QA" configured (2026-10-13).**
  Dashboard charts (EDD-by-jurisdiction = D4, tool-error-rate = D2/D3, decision mix, latency,
  cost, reviewer-agreement). Annotation queue `KYB QA` with rubric + 5 routing rules (reject,
  EDD, reviewer-disagree, low-grounding, 10% approval spot-check). Validated: a mixed batch
  routed items into the queue and populated every metric. *(UI steps; §5 Monitor.)*
- [x] **Cost-capped traffic run (2026-10-13).** Full 24–48h at 1 app/5 min on Opus (~290/day ≈
  **$110/day**) collides with the **$60/day Gateway cap** — so instead of a time-boxed run we
  use `send_traffic.py --budget-usd` to drip a **bounded** run that stops under the cap
  (e.g. `--budget-usd 40 --shuffle --rate-seconds 90` ≈ 104 apps ≈ $40, read the live
  `current_spend` off `kyb-agent-spend-cap` first to size it against the remaining daily
  headroom). Enough traffic to surface D1–D5 and run Phase 6; `hard_cases.jsonl` backstops v2
  if Engine wants more. (For a longer run: slow to ~1 app/10 min, or switch prod to the
  `sonnet` profile ≈ $53/day, or raise the cap.)

**Phase 6: Improve**
- [x] Engine board created on prod project (2026-10-13) via `POST /api/v1/platform/sessions/{SID}/issues-agent`. Board id `2d1c5d11-05f1-43f0-9e8d-c72a4bd1b2ef` (engine v2.1.0); repo `sohamda/kyb-agent`@`main`, `run_filter`=`and(eq(metadata_key,"simulated"),eq(metadata_value,"true"))`, priorities = Tool Call Failures + missed sanctions/PEP + wrong ownership % + embedded-instruction following, `auto_open_fix_pr=false`, cron `45 4/6 * * *`. Issues read via `GET /api/v1/platform/issues?session_id={SID}`. **Still open:** accept the **agent overview** in the UI; set a **project Engine spend limit** (`session_lcu_spend_limit_monthly` is null — only any org-level limit applies); optionally set baseline deployment = staging for fix verification. Add Slack notifications.
- [x] First scan (2026-10-13) clustered **5 issues**, mapping to planted defects: Circular ownership recursion (D2, sev1), Ownership units misparsed/crash (D3, sev1), Transliterated sanctions names missed (D1, sev1), Document dates → false EDD (D4, sev2), plus an emergent "decisions omit required evidence" (sev2). D5 (injection) did not cluster. Each issue got a generated fix branch (`langsmith-engine/<uuid>`); **D2 opened as draft PR #1** (`langsmith-engine/3e34e842-…`, commit 608d537: cycle detection in `registry.py` + ownership-investigator prompt/tool-error handling in `subagents.py` + 2 new test files). **Add offline examples** on D2 → 5 examples in `kyb-golden`, tagged split **`v2`** (input=`messages`, reference=Engine **assertions**).
- [x] **Close-the-loop proven (dress-rehearsal, UNMERGED).** New harness: `evals/run_v2_experiment.py` + assertions evaluator; `target.py` now accepts `messages` inputs. On the `v2` split: **v1 (main 572e630, defects) = 0.000** on all assertions (every case `RecursionError` in `registry.py`), experiment `kyb-v2-v1-defects-d3a9a8a3`; **fix branch (608d537) = 1.000** on all (`must_return_kyb_decision`/`must_flag_opaque_ownership`/`must_recommend_enhanced_due_diligence`), experiment `kyb-v2-fix-branch-eda2a2b5`. Fix run used a throwaway git worktree so `main` keeps its defects. **PR #1 held unmerged for the live demo** (merge = issue completes).

**Phase 7: Rehearse the demo** (section 7). Snapshot the "before" state (screenshots or saved experiment links) in case live systems drift.

## 7. Demo storyline (~25 min)

1. **Build (4 min):** show the small codebase and the Gateway model ID. Run one application in Studio: the plan, three subagents, tool calls, a pause for compliance approval, then resume.
2. **Test (4 min):** show dataset v1 and experiment v1 (looks good), then the comparison view for Opus 5.5 vs Sonnet 5.5 (one line changed).
3. **Deploy (3 min):** show `mda deploy`, the cron schedule, and a Context Hub edit to a risk threshold that goes live without a redeploy.
4. **Monitor (5 min):** after 48 hours of traffic, show:
   - the dashboard (GB EDD spike, ownership tool errors);
   - the alert in Slack;
   - the online judge catching an injection;
   - reviewer-bot disagreements and the annotation queue.
5. **Improve (7 min):** show Engine's issue list and open "circular ownership crashes":
   1. evidence traces, root cause in code, then the **Engine-generated draft PR** (walk the diff it wrote), then Add offline examples;
   2. dataset v2 makes v1 fail and the fix pass;
   3. **merge the draft PR live** (the climax) → deploy → the Engine issue flips to complete and stays closed.
   > Pre-staged in Phase 6 and left unmerged on purpose: the issue, the draft PR, and v2 all exist before the demo, so nothing is generated live — only the merge happens on stage.
6. **Govern (2 min):** show Gateway spend, rate-limit and fallback policies, cost per application, the Engine spend limit, and Context Hub history.

## 8. Risks and things to verify first

| # | Risk | Mitigation |
|---|---|---|
| R1 | MDA and LLM Gateway are beta; APIs may shift | Pin the `managed-deepagents` version; keep the agent code thin |
| R2 | Engine's **preview-deployment fix verification** needs **preview builds**, which are only available for deployments created through the **GitHub integration**. `mda deploy` uploads a local build, so verification likely won't run | Use Engine's baseline replay ("Test issue") against staging plus our own CI experiment |
| R3 | `LANGSMITH_REVISION_ID` in `.env` may be treated as a reserved platform variable and not forwarded | The simulator passes `revision_id` in run metadata; a deploy script records the deployed SHA |
| R4 | Engine replays call tools | Tools are read-only mocks; `escalate_to_compliance` writes only to a mock store. Point Engine replays at staging |
| R5 | Traffic cost (many LLM calls per application) | Throttle the simulator, set the Gateway spend policy, set the Engine spend limit |
| R6 | Engine may group defects differently than planned, or need time to surface them | Run traffic early (Phase 5 well before the demo); save "before" artifacts |
| R6b | A merged Engine issue flips to "complete" and can't re-stage its discovery live, so running Phase 6 fully (incl. merge) "uses up" the demo arc | Dress-rehearsal mode: generate issue + draft PR + v2 but **leave unmerged**, merge only on stage. For a reset/second run: fresh traffic from the 896 unused pool apps (deterministic defects → Engine re-detects), or run generate/merge on **staging** and keep prod's issue list pristine |
| R7 | ~~Subagents may not accept a `langsmith:` model ID~~ | **RESOLVED (2026-10-10).** The `SubAgent` TypedDict has an optional `model` field; a `langsmith:` Gateway id resolves and runs there. `document-checker` + `ownership-investigator` now run on Sonnet 5.5 (tool-driven work), main agent + `screening-analyst` stay on Opus 5.5 (judgment/high-stakes). Confirm the accuracy/cost trade-off with a Phase 3 labeled experiment before committing. |
| R8 | ~~Opus 5.5 and Sonnet 5.5 reject forced tool calls (`tool_choice` "any" or a named tool returns a 400). If LangChain's structured output forces the final tool call, `response_format` breaks~~ | **RESOLVED (2026-10-10).** Confirmed the 400 at runtime, then fixed with `response_format=ProviderStrategy(KYBDecision)` (native structured output, no forced tool call) + `extra="forbid"` on the schema models for the Gateway's strict JSON-schema. Full golden run passes. |
| R9 | Traffic cost: Opus 5.5 is $4/$20 per million input/output tokens, Sonnet 5.5 is $2/$10 | Measure tokens per application in Phase 2, then set the Gateway spend cap and traffic rate. If the Phase 3 comparison shows Sonnet holds accuracy, run production traffic on Sonnet |

## 9. Open decisions

None right now.
