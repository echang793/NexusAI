"""Score the app's own BUY / SELL / HOLD calls against what happened next.

advisory.get_advice() turns a row of indicators into a signal. This replays it
over past prices, thins the samples (so near-identical neighbouring days don't
all count), and compares each signal's subsequent return with SPY's over the
same window. A BUY earns a "hit" when the stock then beat SPY; a SELL when it
lagged SPY. The baseline row (ALL) is a coin flip on whatever days were
sampled — a signal is only interesting if it beats the baseline.

Honest limits, printed with every report: the tickers are the CURRENT holdings,
which are survivors (you hold them partly because they did well), the windows
overlap, and past results don't predict future ones.
"""

import advisory

MIN_SAMPLE = 30   # fewer calls than this and the percentages are noise
SIGNALS = ("BUY", "SELL", "HOLD")


def signal_rows(df, step: int = 5, warmup: int = 200) -> list[dict]:
    """[{i, date, signal}] every `step` rows once indicators exist. Reuses the
    live advisor so the scorecard can't drift from the rules the app applies."""
    rows = []
    for i in range(warmup - 1, len(df), step):
        signal, _ = advisory.get_advice(df.iloc[[i]])
        if signal == "UNKNOWN":
            continue
        rows.append({"i": i, "date": df.index[i].date().isoformat(), "signal": signal})
    return rows


def forward_return(close, i: int, horizon: int):
    j = i + horizon
    if i < 0 or j >= len(close):
        return None
    a, b = float(close.iloc[i]), float(close.iloc[j])
    return b / a - 1.0 if a > 0 else None


def _mean(xs):
    return sum(xs) / len(xs) if xs else None


def evaluate(per_ticker: dict, spy_close, horizons=(21, 63)) -> dict:
    """per_ticker: {ticker: (rows from signal_rows, close Series)}.
    Returns {signal: {horizon: {n, avgRet, avgExcess, hitRate}}} plus "ALL"."""
    pooled = {s: {h: [] for h in horizons} for s in (*SIGNALS, "ALL")}
    for _t, (rows, close) in per_ticker.items():
        spy = spy_close.reindex(close.index, method="ffill")
        for r in rows:
            for h in horizons:
                ret = forward_return(close, r["i"], h)
                bench = forward_return(spy, r["i"], h)
                if ret is None or bench is None:
                    continue
                obs = (ret, ret - bench)
                pooled[r["signal"]][h].append(obs)
                pooled["ALL"][h].append(obs)

    out = {}
    for sig, by_h in pooled.items():
        out[sig] = {}
        for h, obs in by_h.items():
            rets, exc = [o[0] for o in obs], [o[1] for o in obs]
            if sig == "SELL":
                hits = [e < 0 for e in exc]
            elif sig in ("BUY", "ALL"):
                hits = [e > 0 for e in exc]
            else:
                hits = []
            out[sig][h] = {
                "n": len(obs),
                "avgRet": None if not obs else round(_mean(rets) * 100, 2),
                "avgExcess": None if not obs else round(_mean(exc) * 100, 2),
                "hitRate": None if not hits else round(sum(hits) / len(hits) * 100, 1),
            }
    return out


def render(summary: dict, tickers: list, horizons=(21, 63)) -> str:
    L = ["SIGNAL SCORECARD — how the app's BUY/SELL/HOLD rules did historically",
         f"Replayed over {len(tickers)} tickers; each result is the average over the next N trading days,",
         "compared with SPY over the same days. 'Hit' = BUY then beat SPY, or SELL then lagged SPY.", ""]
    for h in horizons:
        L.append(f"Next {h} trading days:")
        base = summary["ALL"][h]
        L.append(f"  Any day (baseline): beat SPY {base['hitRate']}% of the time, "
                 f"avg vs SPY {base['avgExcess']:+.2f}% (n={base['n']})" if base["n"] else
                 "  Any day (baseline): no data")
        for sig in SIGNALS:
            c = summary[sig][h]
            if not c["n"]:
                L.append(f"  {sig}: no calls in this period")
                continue
            hit = f", hit {c['hitRate']}%" if c["hitRate"] is not None else ""
            flag = "  [too few calls to trust]" if c["n"] < MIN_SAMPLE else ""
            L.append(f"  {sig}: n={c['n']}, avg {c['avgRet']:+.2f}%, vs SPY {c['avgExcess']:+.2f}%{hit}{flag}")
        L.append("")
    L += ["Read it as: a signal only has an edge if it beats the baseline line, over a decent sample.",
          "Limits: these are your CURRENT holdings (survivors), windows overlap, and past results",
          "don't predict future ones. Tool output for your own review, not advice."]
    return "\n".join(L)
