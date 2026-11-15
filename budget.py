"""Monthly budget vs actual spending by category. Pure.

`budget` is {category: monthly target}; `by_category` is one month's actual
spending (cashflow.monthly()[month]["byCategory"]). Categories you spent in but
didn't budget are totalled as `unbudgeted` rather than hidden."""

import cashflow

PACE_SLACK = 1.25   # flag when more than 125% of the month-elapsed share is spent


def compare(budget: dict, by_category: dict, month_fraction: float | None = None) -> dict:
    rows = []
    for cat, target in budget.items():
        actual = float(by_category.get(cat, 0.0))
        target = float(target)
        over = actual > target
        rows.append({
            "category": cat, "label": cashflow.label(cat), "target": round(target, 2),
            "actual": round(actual, 2), "remaining": round(target - actual, 2),
            "pctUsed": round(actual / target * 100.0, 1) if target > 0 else None,
            "over": over,
            "aheadOfPace": bool(month_fraction is not None and not over and target > 0
                                and actual > target * month_fraction * PACE_SLACK),
        })
    rows.sort(key=lambda r: -(r["pctUsed"] if r["pctUsed"] is not None else 0.0))
    return {
        "rows": rows,
        "totalTarget": round(sum(r["target"] for r in rows), 2),
        "totalActual": round(sum(r["actual"] for r in rows), 2),
        "unbudgeted": round(sum(v for c, v in by_category.items() if c not in budget and v > 0), 2),
    }
