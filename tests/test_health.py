"""Tests for health.py (run record + problem detection) and scripts/watchdog.py
(dedupe + notify). The watchdog exists because the daily job once failed for a
week with nobody noticing."""

import datetime
import os
import sys


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import health  # noqa: E402
import watchdog  # noqa: E402

NOW = datetime.datetime(2026, 10, 27, 10, 0)


def good_run(finished="2026-10-27T07:31:00"):
    return {"started": "2026-10-27T07:30:00", "finished": finished, "ok": True,
            "steps": {"prices": {"ok": True}, "plaid_balances": {"ok": True}, "build": {"ok": True}},
            "unpriced": []}


def codes(problems):
    return {p["code"] for p in problems}


def test_healthy_run_has_no_problems():
    assert health.evaluate(good_run(), [], NOW) == []


def test_never_run_is_a_problem():
    assert "never_ran" in codes(health.evaluate(None, [], NOW))


def test_stale_run_flagged_when_job_has_not_fired_in_over_30_hours():
    old = good_run(finished="2026-10-25T07:31:00")  # ~50h before NOW
    assert "stale_run" in codes(health.evaluate(old, [], NOW))


def test_yesterdays_run_is_fine():
    assert health.evaluate(good_run("2026-10-26T07:31:00"), [], NOW) == []


def test_failed_step_is_reported_with_its_error():
    run = good_run()
    run["ok"] = False
    run["steps"]["plaid_balances"] = {"ok": False, "error": "ITEM_LOGIN_REQUIRED"}
    probs = health.evaluate(run, [], NOW)
    assert "step_failed" in codes(probs)
    assert any("plaid_balances" in p["message"] and "ITEM_LOGIN_REQUIRED" in p["message"] for p in probs)


def test_unpriced_tickers_reported():
    run = good_run()
    run["unpriced"] = ["ABCD", "WXYZ"]
    probs = health.evaluate(run, [], NOW)
    assert any(p["code"] == "unpriced" and "ABCD" in p["message"] for p in probs)


def test_stale_plaid_account_reported_but_stale_manual_is_not_a_failure():
    accounts = [
        {"name": "TOTAL CHECKING", "source": "plaid", "updated": "2026-10-20"},   # 7 days
        {"name": "RoboInvestor", "updated": "2026-08-01"},                       # manual: monthly report's job
        {"name": "401k", "source": "plaid", "updated": "2026-10-27"},
    ]
    probs = health.evaluate(good_run(), accounts, NOW)
    assert [p["code"] for p in probs] == ["plaid_stale"]
    assert "TOTAL CHECKING" in probs[0]["message"]


def test_record_run_roundtrip_and_atomic_file(tmp_path):
    path = str(tmp_path / "health.json")
    health.write(path, good_run())
    assert health.read(path)["ok"] is True
    assert not os.path.exists(path + ".tmp")


def test_read_missing_or_corrupt_returns_none(tmp_path):
    path = str(tmp_path / "health.json")
    assert health.read(path) is None
    open(path, "w").write("{oops")
    assert health.read(path) is None


def test_runner_records_failure_and_keeps_going():
    calls = []

    def boom():
        raise RuntimeError("plaid down")

    def ok():
        calls.append("ok")

    run = health.Runner()
    run.step("plaid_balances", boom)
    run.step("build", ok)
    rec = run.finish()
    assert calls == ["ok"]                       # later steps still run
    assert rec["ok"] is False
    assert rec["steps"]["plaid_balances"] == {"ok": False, "error": "RuntimeError: plaid down"}
    assert rec["steps"]["build"]["ok"] is True


def test_runner_all_good():
    run = health.Runner()
    run.step("a", lambda: None)
    assert run.finish()["ok"] is True


# --- watchdog dedupe ------------------------------------------------------------
P1 = [{"code": "stale_run", "message": "m1"}]
P2 = [{"code": "stale_run", "message": "m1"}, {"code": "unpriced", "message": "m2"}]


def test_first_problem_notifies():
    assert watchdog.should_notify(P1, {}, NOW) is True


def test_same_problems_within_a_day_do_not_renotify():
    state = watchdog.new_state(P1, NOW)
    assert watchdog.should_notify(P1, state, NOW + datetime.timedelta(hours=5)) is False


def test_same_problems_renotify_after_24h():
    state = watchdog.new_state(P1, NOW)
    assert watchdog.should_notify(P1, state, NOW + datetime.timedelta(hours=25)) is True


def test_new_problem_notifies_immediately():
    state = watchdog.new_state(P1, NOW)
    assert watchdog.should_notify(P2, state, NOW + datetime.timedelta(minutes=5)) is True


def test_no_problems_never_notifies():
    assert watchdog.should_notify([], {}, NOW) is False


def test_main_logs_notifies_once_and_clears_state_on_recovery(tmp_path, monkeypatch):
    sent = []
    monkeypatch.setattr(watchdog, "notify", lambda title, msg: sent.append((title, msg)))
    monkeypatch.setattr(watchdog, "ROOT", str(tmp_path))
    (tmp_path / "reports").mkdir()
    health.write(str(tmp_path / "health.json"), None or {
        "started": "2026-10-20T07:30:00", "finished": "2026-10-20T07:31:00",
        "ok": True, "steps": {}, "unpriced": []})
    assert watchdog.run(NOW) == 1
    assert watchdog.run(NOW + datetime.timedelta(hours=1)) == 1
    assert len(sent) == 1                                    # deduped
    log = (tmp_path / "reports" / "alerts.log").read_text()
    assert "stale_run" in log
    health.write(str(tmp_path / "health.json"), good_run("2026-10-27T07:31:00"))
    assert watchdog.run(NOW + datetime.timedelta(hours=2)) == 0
    assert not (tmp_path / "alert_state.json").exists()      # recovered -> state cleared


# --- daily_refresh wiring ---------------------------------------------------------
def _stub_refresh(monkeypatch, tmp_path, plaid_boom=False, unpriced=()):
    import daily_refresh as dr
    monkeypatch.setattr(dr, "HEALTH_FILE", str(tmp_path / "health.json"))
    monkeypatch.setattr(dr.import_holdings, "main", lambda: None)
    monkeypatch.setattr(dr.server.pf, "load_portfolio", lambda: [{"ticker": "VTI"}])
    for fn in ("batch_prices", "compute_period_prices", "compute_portfolio_risk"):
        monkeypatch.setattr(dr.server, fn, lambda *a, **k: {})
    monkeypatch.setattr(dr.plaid_sync, "HAS_PLAID", True)

    def pull():
        if plaid_boom:
            raise RuntimeError("ITEM_LOGIN_REQUIRED")
        return {"ok": True}
    monkeypatch.setattr(dr.plaid_sync, "pull_balances", pull)
    monkeypatch.setattr(dr.plaid_sync, "pull_investment_holdings", lambda: {"ok": True})
    built = []
    monkeypatch.setattr(dr.server, "build_nexus_data", lambda force=False: (
        built.append(1) or {"netWorth": 1000.0, "netWorthHistory": [], "pricesIncomplete": list(unpriced)}))
    return dr, built


def test_daily_refresh_writes_health_and_returns_zero(monkeypatch, tmp_path):
    dr, built = _stub_refresh(monkeypatch, tmp_path)
    assert dr.main() == 0
    rec = health.read(str(tmp_path / "health.json"))
    assert rec["ok"] is True and rec["steps"]["build"]["ok"] is True and rec["unpriced"] == []


def test_daily_refresh_survives_plaid_failure_and_exits_nonzero(monkeypatch, tmp_path):
    dr, built = _stub_refresh(monkeypatch, tmp_path, plaid_boom=True)
    assert dr.main() == 1
    assert built                      # snapshot/build still ran
    rec = health.read(str(tmp_path / "health.json"))
    assert rec["steps"]["plaid_balances"]["ok"] is False and rec["steps"]["build"]["ok"] is True


def test_daily_refresh_records_unpriced_tickers(monkeypatch, tmp_path):
    dr, _ = _stub_refresh(monkeypatch, tmp_path, unpriced=["ZZZZ"])
    dr.main()
    assert health.read(str(tmp_path / "health.json"))["unpriced"] == ["ZZZZ"]
