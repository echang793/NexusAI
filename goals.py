"""Savings goals: progress, and the monthly amount needed to hit each date.

A goal is {id, name, target, date, linked: [account names], extra}. Its saved
amount is the sum of the linked accounts' current balances plus `extra` (money
set aside that isn't in a linked account). Pure functions; the server passes
in a {account name: balance} map built from the dashboard's accounts.
"""

import datetime

DAYS_PER_MONTH = 30.4375


def progress(goals: list, balances: dict, today: datetime.date) -> list:
    out = []
    for g in goals:
        found = [n for n in g.get("linked", []) if n in balances]
        saved = float(g.get("extra", 0) or 0) + sum(float(balances[n]) for n in found)
        target = float(g["target"])
        remaining = max(0.0, target - saved)
        row = {"id": g["id"], "name": g["name"], "target": round(target, 2), "date": g.get("date") or "",
               "saved": round(saved, 2), "remaining": round(remaining, 2),
               "pct": round(min(100.0, saved / target * 100.0), 1) if target > 0 else 0.0,
               "missingAccounts": [n for n in g.get("linked", []) if n not in balances],
               "monthsLeft": None, "requiredMonthly": None}
        if remaining <= 0:
            row.update(status="done", requiredMonthly=0.0)
        elif not row["date"]:
            row["status"] = "no date"
        else:
            days = (datetime.date.fromisoformat(row["date"]) - today).days
            if days <= 0:
                row["status"] = "overdue"
            else:
                months = days / DAYS_PER_MONTH
                row.update(status="active", monthsLeft=round(months, 1),
                           requiredMonthly=round(remaining / months, 2))
        out.append(row)
    return out


def summary(rows: list, monthly_surplus: float | None) -> dict:
    """Do the active goals fit in what you actually have left each month?"""
    total = round(sum(r["requiredMonthly"] for r in rows
                      if r["status"] == "active" and r["requiredMonthly"] is not None), 2)
    return {"totalRequiredMonthly": total,
            "monthlySurplus": None if monthly_surplus is None else round(monthly_surplus, 2),
            "fundable": None if monthly_surplus is None else total <= monthly_surplus,
            "activeCount": sum(1 for r in rows if r["status"] == "active")}
