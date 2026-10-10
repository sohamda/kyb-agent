"""Nightly re-screening of existing customers (ongoing KYC).

Re-screens recently approved customers against the latest sanctions additions,
so a newly listed party on an existing customer is caught without a new
application. Runs every night; the declaration must be static literals only.
"""

from managed_deepagents import define_schedule

schedule = define_schedule(
    cron="0 2 * * *",
    timezone="America/New_York",
    prompt=(
        "Nightly re-screening. Call `list_customers_for_rescreen` to get the "
        "existing customer book. For every customer, have the `screening-analyst` "
        "screen each listed person against the current watchlists, paying "
        "attention to recent sanctions additions. Report any customer with a new "
        "confirmed sanctions match or PEP exposure, citing the party and the "
        "watchlist entry, and escalate confirmed sanctions matches to compliance."
    ),
)
