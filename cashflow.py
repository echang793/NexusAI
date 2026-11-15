"""Income, spending and savings rate from stored transactions (transactions.py).

Pure functions. Plaid sign: amount > 0 leaves the account (spending),
amount < 0 comes in. Three kinds of rows are kept OUT of income and spending
so nothing is counted twice:
  - TRANSFER_IN / TRANSFER_OUT  (moving your own money: to Webull, savings...)
  - credit-card payments from checking (the purchases are already counted
    when they hit the card)
  - pending rows (their posted twin arrives later under a new id)
They are totalled separately as `transfers`.

Savings rate is net / income where income is what lands in the linked
accounts, i.e. TAKE-HOME pay: 401(k) payroll deferrals never appear in it.

Category overrides: category_rules.json is a list of
{"match": "text in merchant/name", "category": "PLAID_STYLE_CATEGORY"}; first
match wins. A rule can send something to TRANSFER_OUT to exclude it.
"""

import datetime
import json
import os
import re

RULES_FILE = os.getenv("CATEGORY_RULES_FILE",
                       os.path.join(os.path.dirname(__file__), "category_rules.json"))

EXCLUDED_CATEGORIES = {"TRANSFER_IN", "TRANSFER_OUT"}
EXCLUDED_DETAILED = {"LOAN_PAYMENTS_CREDIT_CARD_PAYMENT"}
INVESTMENT_TRANSFER = "TRANSFER_OUT_INVESTMENT_AND_RETIREMENT_FUNDS"   # money moved to Webull etc.
PARTIAL_FIRST_MONTH_AFTER_DAY = 5   # history starting later than this leaves the first month incomplete
SHORT_HISTORY_MONTHS = 3
AVG_WINDOW_MONTHS = 12

_LABELS = {
    "FOOD_AND_DRINK": "Food & drink", "RENT_AND_UTILITIES": "Rent & utilities",
    "GENERAL_MERCHANDISE": "Shopping", "GENERAL_SERVICES": "Services",
    "PERSONAL_CARE": "Personal care", "HOME_IMPROVEMENT": "Home",
    "LOAN_PAYMENTS": "Loan payments", "BANK_FEES": "Bank fees",
    "GOVERNMENT_AND_NON_PROFIT": "Government & giving", "TRANSFER_IN": "Transfer in",
    "TRANSFER_OUT": "Transfer out",
}


def label(category: str) -> str:
    if category in _LABELS:
        return _LABELS[category]
    return (category or "other").replace("_", " ").capitalize()


def load_rules(path: str | None = None) -> list:
    try:
        with open(path or RULES_FILE) as f:
            rules = json.load(f)
        return [r for r in rules if isinstance(r, dict) and r.get("match") and r.get("category")]
    except Exception:
        return []


_CATEGORY_KEY = re.compile(r"^[A-Z][A-Z_]{0,39}$")
MAX_RULES = 200


def clean_rules(raw) -> list:
    """Keep only well-formed {match, category} rules (match text, UPPER_SNAKE category)."""
    out = []
    for r in (raw if isinstance(raw, list) else []):
        if not isinstance(r, dict) or len(out) >= MAX_RULES:
            continue
        match = str(r.get("match") or "").strip()[:80]
        category = str(r.get("category") or "").strip()
        if match and _CATEGORY_KEY.match(category):
            out.append({"match": match, "category": category})
    return out


def save_rules(rules: list, path: str | None = None) -> list:
    clean = clean_rules(rules)
    path = path or RULES_FILE
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(clean, f, indent=2)
    os.replace(tmp, path)
    return clean


def classify(row: dict, rules) -> tuple[str, bool]:
    """(category, excluded). The first matching user rule wins over Plaid's label."""
    text = f"{row.get('name', '')} {row.get('merchant', '')}".lower()
    for r in rules:
        if r["match"].lower() in text:
            cat = r["category"]
            return cat, cat in EXCLUDED_CATEGORIES
    cat = row.get("cat") or "OTHER"
    return cat, cat in EXCLUDED_CATEGORIES or row.get("detailed") in EXCLUDED_DETAILED


def monthly(rows, rules=()) -> dict:
    out: dict[str, dict] = {}
    for r in rows:
        if r.get("pending"):
            continue
        m = out.setdefault(r["date"][:7], {"income": 0.0, "spending": 0.0, "transfers": 0.0,
                                           "invested": 0.0, "transfersIn": 0.0,
                                           "byCategory": {}, "count": 0})
        cat, excluded = classify(r, rules)
        amt = float(r["amount"])
        m["count"] += 1
        if excluded:
            m["transfers"] += abs(amt)
            if cat == "TRANSFER_OUT" and r.get("detailed") == INVESTMENT_TRANSFER:
                m["invested"] += amt
            elif cat == "TRANSFER_IN":
                m["transfersIn"] += -amt
        elif cat == "INCOME":
            m["income"] += -amt
        else:
            m["spending"] += amt
            m["byCategory"][cat] = m["byCategory"].get(cat, 0.0) + amt
    for m in out.values():
        m["income"] = round(m["income"], 2)
        m["spending"] = round(m["spending"], 2)
        m["transfers"] = round(m["transfers"], 2)
        m["invested"] = round(m["invested"], 2)
        m["transfersIn"] = round(m["transfersIn"], 2)
        m["byCategory"] = {k: round(v, 2) for k, v in m["byCategory"].items() if round(v, 2) != 0}
        m["net"] = round(m["income"] - m["spending"], 2)
        m["savingsRate"] = round(m["net"] / m["income"] * 100, 2) if m["income"] > 0 else None
    return out


def _top(rows, rules, months, key):
    totals: dict[str, float] = {}
    for r in rows:
        if r.get("pending") or r["date"][:7] not in months:
            continue
        cat, excluded = classify(r, rules)
        if excluded or cat == "INCOME" or r["amount"] <= 0:
            continue
        k = key(r, cat)
        if k:
            totals[k] = totals.get(k, 0.0) + r["amount"]
    return sorted(totals.items(), key=lambda kv: -kv[1])[:5]


def summary(rows, today: datetime.date, rules=(), assumed_annual_spend=None) -> dict:
    rows = list(rows)
    by_month = monthly(rows, rules)
    this_month = today.strftime("%Y-%m")
    past = sorted(m for m in by_month if m < this_month)
    partial: list = []
    # History usually starts mid-month; that first month would understate spend.
    if len(past) > 2:   # keep a partial first month only if it's nearly all we have
        first = min(r["date"] for r in rows if r["date"][:7] == past[0])
        if int(first[8:10]) > PARTIAL_FIRST_MONTH_AFTER_DAY:
            partial = [past[0]]
            past = past[1:]
    window = past[-AVG_WINDOW_MONTHS:]

    out = {"completeMonths": len(past), "shortHistory": len(past) < SHORT_HISTORY_MONTHS,
           "avgMonthlySpend": None, "annualizedSpend": None, "avgSavingsRate": None,
           "avgMonthlyIncome": None, "avgMonthlySurplus": None,
           "avgMonthlyInvested": None, "investedExceedsIncome": False, "partialMonths": partial,
           "lastMonth": None, "currentMonth": None, "topCategories": [], "topMerchants": [],
           "months": {m: by_month[m] for m in sorted(by_month)[-24:]}}
    if window:
        avg = sum(by_month[m]["spending"] for m in window) / len(window)
        out["avgMonthlySpend"] = round(avg, 2)
        out["annualizedSpend"] = round(avg * 12, 2)
        inc = sum(by_month[m]["income"] for m in window if by_month[m]["income"] > 0)
        net = sum(by_month[m]["net"] for m in window if by_month[m]["income"] > 0)
        out["avgSavingsRate"] = round(net / inc * 100, 2) if inc > 0 else None
        out["avgMonthlyIncome"] = round(sum(by_month[m]["income"] for m in window) / len(window), 2)
        out["avgMonthlySurplus"] = round(sum(by_month[m]["net"] for m in window) / len(window), 2)
        out["avgMonthlyInvested"] = round(sum(by_month[m]["invested"] for m in window) / len(window), 2)
        out["investedExceedsIncome"] = out["avgMonthlyInvested"] > out["avgMonthlyIncome"]
        out["lastMonth"] = {"month": past[-1], **by_month[past[-1]]}
        recent = set(window[-3:])
        out["topCategories"] = [{"category": c, "label": label(c), "amount": round(a, 2)}
                                for c, a in _top(rows, rules, recent, lambda r, cat: cat)]
        out["topMerchants"] = [{"merchant": k, "amount": round(a, 2)}
                               for k, a in _top(rows, rules, recent, lambda r, cat: r.get("merchant"))]
    if this_month in by_month:
        out["currentMonth"] = {"month": this_month, "partial": True, **by_month[this_month]}
    if assumed_annual_spend and out["annualizedSpend"] is not None:
        out["assumedAnnualSpend"] = round(float(assumed_annual_spend))
        out["fireNumberAtActual"] = round(out["annualizedSpend"] * 25)
        out["spendVsAssumedPct"] = round((out["annualizedSpend"] / assumed_annual_spend - 1) * 100, 1)
    return out
