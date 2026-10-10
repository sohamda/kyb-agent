---
name: risk-rating
description: How to turn KYB findings into a decision (approve / enhanced_due_diligence / reject) and a risk rating (low / medium / high). Load this before deciding any application.
---

# Risk rating and decision mapping

Collect the risk **flags** raised by the subagents, then map them to a decision
and a risk rating with the rules below. Apply them in order; the first rule that
matches wins.

## Flags

Use only these flags:

`sanctions_match`, `pep`, `adverse_media`, `document_mismatch`,
`expired_document`, `opaque_ownership`, `high_risk_jurisdiction`,
`high_risk_industry`, `embedded_instructions`.

The EDD flags are all of the above **except** `sanctions_match`.

## Decision rules

1. **Confirmed sanctions match** → **reject**, risk **high**.
   Also call `escalate_to_compliance` for human sign-off.
2. **No flags at all** → **approve**, risk **low**.
3. **Any EDD flag is present** → **enhanced_due_diligence**. Then set the risk:
   - **high** if any flag is one of `pep`, `adverse_media`, `opaque_ownership`,
     **or** two or more EDD flags are present.
   - **medium** otherwise (a single, less severe EDD flag).

## UBO threshold

A natural person is an ultimate beneficial owner (UBO) when their **effective**
ownership is **25% or more**. List every UBO in `ubos` with their percentage.

## Worked examples

- Clean company, nothing found → `[]` → approve / low.
- One director is a PEP (different person is not sanctioned) → `[pep]` → EDD / high.
- Expired passport only → `[expired_document]` → EDD / medium.
- Expired passport **and** an address mismatch → `[expired_document, document_mismatch]`
  → EDD / high (two EDD flags).
- Director is a confirmed sanctions match → `[sanctions_match]` → reject / high + escalate.
