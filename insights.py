"""Combine cross-feature alerts into one list for the notifications panel.

Pure aggregation — each input is already computed by its own module
(contributions.py, rebalance.py, taxloss.py, coastfire.py); this just
decides which of those results are worth surfacing as an alert.
"""

import datetime

STALE_DAYS = 35


def _stale_accounts(extra_accounts: list, days: int = STALE_DAYS) -> list:
    out = []
    today = datetime.date.today()
    for a in extra_accounts:
        upd = a.get("updated")
        if not upd:
            continue
        try:
            d = datetime.date.fromisoformat(str(upd)[:10])
        except (ValueError, TypeError):
            continue
        if (today - d).days > days:
            out.append(a)
    return out


def build(*, extra_accounts, contributions, rebalance, tax_loss, coastfire) -> list:
    items = []

    for a in _stale_accounts(extra_accounts):
        items.append({
            "type": "stale", "severity": "warn", "title": a.get("name", "Account"),
            "msg": f"Balance hasn't been updated in over {STALE_DAYS} days.",
        })

    for key, c in (contributions or {}).items():
        if c.get("maxed"):
            continue
        if c.get("pctUsed", 0) >= 90:
            items.append({
                "type": "contribution", "severity": "info",
                "title": f"{c['label']} contribution room",
                "msg": f"${c['room']:,.0f} left before the ${c['limit']:,.0f} limit.",
            })

    if rebalance and not rebalance.get("onTarget", True):
        drift = rebalance.get("drift", 0)
        direction = "over" if drift > 0 else "under"
        items.append({
            "type": "rebalance", "severity": "warn", "title": "Allocation drift",
            "msg": f"Stock exposure is {abs(drift):.1f}pt {direction} your "
                   f"{rebalance['targetStockPct']:.0f}% target.",
        })

    for t in (tax_loss or [])[:3]:
        items.append({
            "type": "taxloss", "severity": "info", "title": f"{t['ticker']} tax-loss candidate",
            "msg": f"Down {abs(t['plPct']):.1f}% (${abs(t['unrealizedLoss']):,.0f} unrealized loss).",
        })

    if coastfire and coastfire.get("enabled") and coastfire.get("onTrack"):
        items.append({
            "type": "coastfire", "severity": "good", "title": "CoastFIRE reached",
            "msg": "Your invested balance alone should hit your FIRE number by retirement.",
        })

    return items
