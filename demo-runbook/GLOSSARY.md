# Glossary — KYB domain terms

The functional/compliance terms used in this demo, each tied to how it actually shows up
in the agent (its flag, skill rule, or tool). For the technical architecture see
[`../agent/README.md`](../agent/README.md); for the planted defects referenced below (D1–D5)
see [`PLAN.md` §4.3](PLAN.md).

## The process

- **KYB — Know Your Business.** The regulatory obligation to verify a *business* customer
  before onboarding: who the company is, who owns and controls it, and whether any party is
  sanctioned or high-risk. The business equivalent of KYC.
- **KYC — Know Your Customer.** The same for *individuals*. Appears here as **ongoing KYC**:
  the nightly re-screening job (`agent/schedules/nightly_rescreen.py`) re-checks already
  onboarded customers against newly added sanctions, so a party listed *after* onboarding is
  still caught.
- **Onboarding.** The point at which a business applies for an account; each application is
  one run of the agent.
- **CDD / EDD — Customer / Enhanced Due Diligence.** CDD is the baseline level of checks
  everyone gets. **EDD** is heightened scrutiny applied when something elevates risk (a PEP,
  opaque ownership, a document problem). In this agent EDD is one of the three decisions.
- **Ongoing monitoring.** Continuous re-screening after onboarding (the nightly cron here)
  rather than a one-time check.

## The three decisions (`agent/schemas.py` → `KYBDecision.decision`)

- **approve** — clean; no risk flags. Risk rating `low`.
- **enhanced_due_diligence (EDD)** — risk present but not disqualifying; the account proceeds
  with extra scrutiny. Triggered by any "EDD flag."
- **reject** — a confirmed sanctions match. Always paired with escalation to a human and
  risk `high`.

## Screening terms (the `screening-analyst` subagent)

- **Sanctions.** Government/international watchlists (e.g. OFAC-style) of parties you are
  legally barred from dealing with. A confirmed hit → flag `sanctions_match` → **reject**.
- **Watchlist / screening.** Matching a party's name against sanctions, PEP, and
  adverse-media sources (`screen_name`, `search_adverse_media`).
- **PEP — Politically Exposed Person.** Someone in a prominent public role (or a close
  associate) who carries elevated corruption/bribery risk — so they get EDD, not rejection.
  Flag `pep`.
- **Adverse media.** Credible *negative news* about a party — fraud, investigation,
  enforcement — as opposed to neutral coverage. Flag `adverse_media`.
- **False positive.** A name matches a listed party but it is clearly *not the same person*
  — date of birth **and** nationality differ. The analyst must rule these out rather than
  reject an innocent namesake.
- **Transliteration / aliases.** The same name rendered differently across scripts/spellings
  (e.g. Arabic or Cyrillic → Latin), or known alternate names on the list. Real screening
  must catch these — and this is exactly where defect **D1** lives (the tool only does raw
  string similarity, so transliterated names slip through).

## Ownership terms (the `ownership-investigator` subagent)

- **Beneficial owner / UBO — Ultimate Beneficial Owner.** The *natural person* who
  ultimately owns or controls the company, seen through layers of corporate shareholders.
  Here a UBO is anyone with **effective ownership ≥ 25%** (the regulatory default threshold).
- **Effective ownership %.** Ownership computed *through the chain* — multiply stakes along
  each path and sum them (`compute_effective_ownership` walks the tree). E.g. a person owning
  50% of a company that owns 60% of the applicant has 30% effective ownership.
- **Opaque ownership.** The structure hides the real owners — **undisclosed shareholders**,
  a **holding/shell company** whose owners cannot be resolved, or a **circular** structure
  (A owns B owns A). Flag `opaque_ownership`; defects **D2** (circular → crash) and **D3**
  (ownership mis-parsed) live here.
- **Secrecy / high-risk jurisdiction.** Countries known for corporate secrecy used to
  obscure ownership. In this agent: **VG** (British Virgin Islands), **SC** (Seychelles),
  **PA** (Panama). A holding company there → flag `high_risk_jurisdiction`.

## Document & registry terms (the `document-checker` subagent)

- **Corporate registry.** The official government record of a company — legal name,
  registration number, registered address, **officers/directors**, disclosed shareholders.
  The agent treats this (and the watchlists) as its source of truth, *over* what the
  applicant submitted.
- **Registration number.** The company's official ID as filed in the registry.
- **Directors / officers / shareholders.** Directors/officers *run* the company;
  shareholders *own* it (and lead to the UBOs). A director on the application who is not in
  the registry is a mismatch.
- **Document mismatch / expired / unverifiable.** The application disagrees with the
  registry, or a submitted document is past expiry / cannot be parsed. Flags
  `document_mismatch`, `expired_document`. Defect **D4** lives here (date parsing assumes US
  `MM/DD/YYYY`, so GB/DE day-first dates fail).

## Risk & other terms

- **Risk rating — low / medium / high.** The severity label on the decision (`risk-rating`
  skill). `pep`, `adverse_media`, `opaque_ownership`, or ≥2 EDD flags → high; a single lesser
  flag → medium.
- **High-risk industry.** Business types with elevated money-laundering exposure: **MSB**
  (money services business), **VASP** (virtual asset / crypto exchange), online gambling,
  precious-metals dealing, arms/defence. Flag `high_risk_industry`.
- **Escalation / compliance officer / human-in-the-loop.** A confirmed sanctions match
  cannot be auto-decided — the run **pauses** (`escalate_to_compliance` interrupt) for a
  human compliance officer to approve or reject before it is recorded. The reviewer bot
  (`simulator/reviewer_bot.py`) plays that officer in the simulation.
- **Embedded instructions.** A prompt-injection attempt hidden in the application notes or a
  document's text ("approve this application"). The agent should flag it
  (`embedded_instructions`) and decide on facts, not obey it — the behavior defect **D5**
  deliberately weakens this.

## The nine flags, at a glance

| Flag | Meaning | Drives |
|------|---------|--------|
| `sanctions_match` | confirmed sanctions hit | **reject** + escalate, high |
| `pep` | politically exposed person | EDD, high |
| `adverse_media` | credible negative news | EDD, high |
| `opaque_ownership` | hidden/circular/unresolvable owners | EDD, high |
| `document_mismatch` | application ≠ registry, or unverifiable doc | EDD, medium\* |
| `expired_document` | document past expiry | EDD, medium\* |
| `high_risk_jurisdiction` | secrecy jurisdiction in chain (VG/SC/PA) | EDD, medium\* |
| `high_risk_industry` | MSB/VASP/gambling/metals/arms | EDD, medium\* |
| `embedded_instructions` | prompt-injection attempt | EDD, medium\* |

\* medium on its own; two or more EDD flags together → high.
