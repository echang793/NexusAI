"""Emergency-fund coverage + rough net-worth-by-age percentile context."""


def emergency_fund(profile: dict, cash_total: float, actual_monthly: float | None = None) -> dict:
    """Months of expenses the cash covers. `monthlyExpense` is the ASSUMED figure
    (profile monthly_expense, else the CoastFIRE spend / 12). When transactions
    give a real average, it is reported beside it (`...Actual`), never in place of it."""
    monthly = float(profile.get("monthly_expense", 0) or 0)
    if not monthly:
        annual_spend = float(profile.get("coastfire_annual_spend", 0) or 0)
        monthly = annual_spend / 12.0
    months = (cash_total / monthly) if monthly else None
    out = {
        "cashTotal": round(cash_total, 2),
        "monthlyExpense": round(monthly, 2),
        "monthsCovered": round(months, 1) if months is not None else None,
        "healthy": months is not None and months >= 3,
    }
    if actual_monthly:
        actual_months = cash_total / actual_monthly
        out.update(monthlyExpenseActual=round(actual_monthly, 2),
                   monthsCoveredActual=round(actual_months, 1),
                   healthyActual=actual_months >= 3)
    return out


# Rough US net-worth-by-age percentile brackets — approximate, aggregated
# from public household-wealth survey data. Informational context only:
# not personalized advice, not a precise/verified figure, and household
# vs. individual composition varies a lot by source.
_PERCENTILE_TABLE = {
    25: [(25, 1000), (50, 8000), (75, 30000), (90, 100000)],
    30: [(25, 5000), (50, 33000), (75, 100000), (90, 300000)],
    35: [(25, 15000), (50, 76000), (75, 200000), (90, 500000)],
    40: [(25, 25000), (50, 105000), (75, 300000), (90, 700000)],
    50: [(25, 50000), (50, 190000), (75, 500000), (90, 1200000)],
    60: [(25, 80000), (50, 290000), (75, 700000), (90, 1800000)],
    999: [(25, 100000), (50, 350000), (75, 900000), (90, 2200000)],
}


def net_worth_percentile(age: int, net_worth: float) -> dict:
    bucket = _PERCENTILE_TABLE[999]
    for max_age in sorted(_PERCENTILE_TABLE):
        if age <= max_age:
            bucket = _PERCENTILE_TABLE[max_age]
            break
    percentile = 10
    for pct, threshold in bucket:
        if net_worth >= threshold:
            percentile = pct
        else:
            break
    return {"percentile": percentile, "approximate": True}
