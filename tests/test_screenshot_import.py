"""Tests for screenshot_import.py: reading account/holdings screenshots with a
local vision model, then validating, previewing and applying the result.

The vision model is always faked; everything writes into tmp_path. The real
data files are never touched.
"""

import base64
import csv
import io
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import accounts as ac  # noqa: E402
import screenshot_import as si  # noqa: E402

TODAY = "2026-11-16"


# --- helpers ---------------------------------------------------------------
def png_bytes(size=(40, 30)):
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", size, (250, 250, 250)).save(buf, "PNG")
    return buf.getvalue()


def row(symbol, qty, price=None, value=None, cost=None, pl=None):
    p = {"symbol": symbol, "quantity": qty}
    if price is not None:
        p["price"] = price
    if value is not None:
        p["value"] = value
    if cost is not None:
        p["avg_cost"] = cost
    if pl is not None:
        p["pl"] = pl
    return p


def holdings_item(positions, bucket="brokerage", mode="merge", **account):
    return {"target": {"type": "holdings", "bucket": bucket}, "mode": mode,
            "account": {"positions": positions, **account}}


def balance_item(name, value):
    return {"target": {"type": "balance", "name": name}, "mode": "merge",
            "account": {"total_value": value, "positions": []}}


@pytest.fixture
def env(tmp_path):
    (tmp_path / "brokerage_holdings.csv").write_text(
        "ticker,shares,avg_cost\nAAPL,2,200.0\nVOO,1,450.0\n")
    (tmp_path / "roth_ira_holdings.csv").write_text("ticker,shares,avg_cost\nBRK-B,1,400.0\n")
    (tmp_path / "hsa_holdings.csv").write_text("ticker,shares,avg_cost\nFXAIX,5,250.0\n")
    accts = tmp_path / "accounts.json"
    accts.write_text(json.dumps({"accounts": [
        {"name": "Webull Cash", "type": "Other Asset", "balance": 251.65, "notes": "", "updated": "2026-08-31"},
        {"name": "RoboInvestor", "type": "Taxable", "balance": 840.5, "notes": "", "updated": "2026-10-02"},
        {"name": "TOTAL CHECKING", "type": "Checking", "balance": 3500.0, "notes": "",
         "updated": "2026-11-14", "source": "plaid", "plaid_account_id": "abc"}]}))
    portfolio = tmp_path / "portfolio.json"
    portfolio.write_text(json.dumps({"holdings": []}))
    return si.Paths(root=str(tmp_path), accounts=str(accts), portfolio=str(portfolio))


def read_csv(path):
    with open(path, newline="") as f:
        return {r["ticker"]: (float(r["shares"]), float(r["avg_cost"])) for r in csv.DictReader(f)}


def snapshot_files(root):
    out = {}
    for name in sorted(os.listdir(root)):
        p = os.path.join(root, name)
        if os.path.isfile(p):
            with open(p, "rb") as f:
                out[name] = f.read()
    return out


# --- number + symbol parsing ---------------------------------------------------
@pytest.mark.parametrize("text,expected", [
    ("$1,234.56", 1234.56), ("1234", 1234.0), (12.5, 12.5), ("(12.30)", -12.3),
    ("-5", -5.0), ("+7.1", 7.1), ("  $0.40 ", 0.4),
])
def test_money_parses(text, expected):
    assert si.parse_number(text) == pytest.approx(expected)


@pytest.mark.parametrize("text", [None, "", "--", "N/A", "abc", "1.2K", "12%", float("nan"),
                                  float("inf"), True])
def test_money_rejects_non_numbers(text):
    assert si.parse_number(text) is None


@pytest.mark.parametrize("raw,expected", [
    ("aapl", "AAPL"), (" voo ", "VOO"), ("BRKB", "BRK-B"), ("brk.b", "BRK-B"), ("BRK-B", "BRK-B"),
])
def test_symbols_are_normalized(raw, expected):
    assert si.clean_symbol(raw) == expected


@pytest.mark.parametrize("raw", ["", None, "AAPL 100", "123", "TOOLONGSYM", "A$B", "<script>"])
def test_bad_symbols_rejected(raw):
    assert si.clean_symbol(raw) is None


# --- normalizing the model's raw output ------------------------------------------
RAW = {"accounts": [{
    "institution": "Webull", "account_label": "Individual Cash",
    "total_value": "$1,540.00", "positions_total": "1,500.00", "cash": "40.00",
    "positions": [
        {"symbol": "VOO", "quantity": "2", "last_price": "500.00", "market_value": "1,000.00",
         "avg_cost": "450.00", "unrealized_pl": "100.00"},
        {"symbol": "brkb", "quantity": "1.25", "last_price": "400", "market_value": "500", "avg_cost": None},
        {"symbol": "??", "quantity": "3"},
        {"symbol": "TSLA", "quantity": "oops"},
    ]}]}


def test_normalize_reads_accounts_and_drops_bad_rows():
    [a] = si.normalize_raw(RAW)
    assert a["label"] == "Individual Cash" and a["institution"] == "Webull"
    assert a["total_value"] == 1540.0 and a["positions_total"] == 1500.0 and a["cash"] == 40.0
    assert [p["symbol"] for p in a["positions"]] == ["VOO", "BRK-B"]
    assert a["positions"][0] == {"symbol": "VOO", "quantity": 2.0, "price": 500.0, "value": 1000.0,
                                 "avg_cost": 450.0, "pl": 100.0}
    assert a["positions"][1]["avg_cost"] is None
    assert len(a["problems"]) == 2  # '??' and TSLA


def test_normalize_accepts_a_bare_account_or_list():
    one = RAW["accounts"][0]
    assert len(si.normalize_raw(one)) == 1
    assert len(si.normalize_raw([one, one])) == 2
    assert si.normalize_raw({}) == []
    assert si.normalize_raw("nonsense") == []
    assert si.normalize_raw({"accounts": "x"}) == []


def test_normalize_is_idempotent_on_its_own_output():
    [a] = si.normalize_raw(RAW)
    assert si.normalize_raw(a)[0]["positions"] == a["positions"]


def test_zero_or_negative_quantity_dropped():
    [a] = si.normalize_raw({"positions": [{"symbol": "AAA", "quantity": 0}, {"symbol": "BBB", "quantity": -3},
                                          {"symbol": "CCC", "quantity": 1}]})
    assert [p["symbol"] for p in a["positions"]] == ["CCC"]


# --- suggesting where an extracted account goes -------------------------------------
def test_suggest_roth_by_label():
    a = {"label": "Roth IRA", "positions": [row("VOO", 1)]}
    assert si.suggest_target(a, []) == {"type": "holdings", "bucket": "roth"}


def test_suggest_taxable_for_other_position_lists():
    a = {"label": "Individual Cash", "positions": [row("VOO", 1)]}
    assert si.suggest_target(a, []) == {"type": "holdings", "bucket": "brokerage"}


def test_suggest_manual_account_by_name():
    a = {"label": "Robo Investor", "institution": None, "positions": []}
    assert si.suggest_target(a, ["Webull Cash", "RoboInvestor"]) == {"type": "balance", "name": "RoboInvestor"}


def test_suggest_skip_when_nothing_matches():
    a = {"label": "Some Bank", "positions": []}
    assert si.suggest_target(a, ["Webull Cash"]) == {"type": "skip"}


# --- plan: holdings ------------------------------------------------------------------
def test_merge_resizes_adds_and_keeps_unseen_positions(env):
    plan = si.build_plan([holdings_item([row("VOO", 2, 500, 1000, cost=450), row("MSFT", 1, 400, 400)])], env)
    assert plan["errors"] == []
    [c] = plan["changes"]
    by = {r["ticker"]: r for r in c["rows"]}
    assert by["VOO"]["status"] == "resized" and by["VOO"]["old_shares"] == 1 and by["VOO"]["new_shares"] == 2
    assert by["MSFT"]["status"] == "added" and by["MSFT"]["cost_estimated"] is True
    assert by["MSFT"]["new_cost"] == 400.0
    assert "AAPL" not in by  # unseen in a merge: untouched
    assert c["removed"] == []


def test_existing_cost_is_kept_when_screenshot_has_none(env):
    plan = si.build_plan([holdings_item([row("VOO", 3, 500, 1500)])], env)
    r = plan["changes"][0]["rows"][0]
    assert r["new_cost"] == 450.0 and r["cost_estimated"] is False


def test_cost_derived_from_unrealized_pl(env):
    plan = si.build_plan([holdings_item([row("MSFT", 2, 500, 1000, pl=100)])], env)
    r = plan["changes"][0]["rows"][0]
    assert r["new_cost"] == pytest.approx(450.0) and r["cost_estimated"] is False


def test_explicit_cost_beats_everything(env):
    plan = si.build_plan([holdings_item([row("VOO", 1, 500, 500, cost=410, pl=50)])], env)
    assert plan["changes"][0]["rows"][0]["new_cost"] == 410.0


def test_new_ticker_with_no_cost_price_or_value_is_an_error(env):
    plan = si.build_plan([holdings_item([row("MSFT", 2)])], env)
    assert any("MSFT" in e for e in plan["errors"])


def test_replace_needs_positions_that_add_up_to_the_shown_total(env):
    items = [holdings_item([row("VOO", 2, 500, 1000, cost=450)], mode="replace")]
    plan = si.build_plan(items, env)
    assert any("replace" in e.lower() for e in plan["errors"])
    items = [holdings_item([row("VOO", 2, 500, 1000, cost=450)], mode="replace", positions_total=1000)]
    plan = si.build_plan(items, env)
    assert plan["errors"] == []
    c = plan["changes"][0]
    assert c["removed"] == ["AAPL"] and c["reconciled"] is True


def test_replace_total_mismatch_is_an_error(env):
    items = [holdings_item([row("VOO", 2, 500, 1000, cost=450)], mode="replace", positions_total=1500)]
    assert si.build_plan(items, env)["errors"]


def test_merge_reports_reconciliation_but_never_removes(env):
    items = [holdings_item([row("VOO", 2, 500, 1000, cost=450)], positions_total=1000)]
    c = si.build_plan(items, env)["changes"][0]
    assert c["reconciled"] is True and c["removed"] == []


def test_quantity_times_price_mismatch_is_a_warning(env):
    plan = si.build_plan([holdings_item([row("VOO", 2, 500, 1100, cost=450)])], env)
    assert plan["errors"] == []
    assert any("VOO" in w for w in plan["warnings"])


def test_rounding_noise_does_not_warn(env):
    # 0.40504 sh x $35.92 = 14.549; screenshot shows $14.55
    plan = si.build_plan([holdings_item([row("AB", 0.40504, 35.92, 14.55, cost=35.0)])], env)
    assert plan["warnings"] == [] and plan["errors"] == []


def test_big_share_count_swing_is_a_warning(env):
    plan = si.build_plan([holdings_item([row("VOO", 10, 500, 5000)])], env)
    assert any("VOO" in w for w in plan["warnings"])


def test_same_ticker_twice_with_different_quantity_is_an_error(env):
    items = [holdings_item([row("MSFT", 1, 400, 400)]), holdings_item([row("MSFT", 2, 400, 800)])]
    assert any("MSFT" in e for e in si.build_plan(items, env)["errors"])


def test_overlapping_screenshots_dedupe_identical_rows(env):
    items = [holdings_item([row("MSFT", 1, 400, 400), row("VOO", 1, 500, 500)]),
             holdings_item([row("VOO", 1, 500, 500), row("NVDA", 3, 100, 300)])]
    plan = si.build_plan(items, env)
    assert plan["errors"] == []
    assert sorted(r["ticker"] for r in plan["changes"][0]["rows"] if r["status"] != "same") == ["MSFT", "NVDA"]
    assert len(plan["changes"]) == 1


def test_holdings_target_with_no_positions_is_an_error(env):
    assert si.build_plan([holdings_item([])], env)["errors"]


def test_unknown_bucket_is_an_error_and_hsa_is_not_allowed(env):
    for bucket in ("hsa", "nonsense", None):
        assert si.build_plan([holdings_item([row("VOO", 1, 500, 500)], bucket=bucket)], env)["errors"]


def test_roth_bucket_targets_the_roth_file(env):
    plan = si.build_plan([holdings_item([row("BRK-B", 2, 400, 800)], bucket="roth")], env)
    assert plan["changes"][0]["bucket"] == "roth"
    assert plan["changes"][0]["rows"][0]["old_shares"] == 1


def test_nothing_to_apply_is_an_error(env):
    assert si.build_plan([], env)["errors"]
    assert si.build_plan([{"target": {"type": "skip"}, "account": {}}], env)["errors"]


def test_skipped_items_are_ignored_next_to_real_ones(env):
    plan = si.build_plan([{"target": {"type": "skip"}, "account": {}},
                          holdings_item([row("VOO", 2, 500, 1000)])], env)
    assert plan["errors"] == [] and len(plan["changes"]) == 1


def test_cash_goes_to_webull_cash_for_the_taxable_account(env):
    plan = si.build_plan([holdings_item([row("VOO", 2, 500, 1000)], cash=88.25)], env)
    c = plan["changes"][0]
    assert c["cash"] == {"name": "Webull Cash", "old": 251.65, "new": 88.25}


def test_cash_without_a_webull_cash_account_is_a_warning(env, tmp_path):
    (tmp_path / "accounts.json").write_text(json.dumps({"accounts": []}))
    plan = si.build_plan([holdings_item([row("VOO", 2, 500, 1000)], cash=88.25)], env)
    assert plan["errors"] == [] and plan["warnings"]
    assert plan["changes"][0]["cash"] is None


def test_roth_cash_is_not_written_to_webull_cash(env):
    plan = si.build_plan([holdings_item([row("BRK-B", 1, 400, 400)], bucket="roth", cash=13.03)], env)
    assert plan["changes"][0]["cash"] is None


# --- plan: manual balances -----------------------------------------------------------
def test_balance_update(env):
    plan = si.build_plan([balance_item("RoboInvestor", 905.2)], env)
    assert plan["errors"] == []
    c = plan["changes"][0]
    assert (c["kind"], c["name"], c["old"], c["new"]) == ("balance", "RoboInvestor", 840.5, 905.2)


def test_plaid_synced_and_unknown_accounts_cannot_be_overwritten(env):
    assert si.build_plan([balance_item("TOTAL CHECKING", 10)], env)["errors"]
    assert si.build_plan([balance_item("Nope", 10)], env)["errors"]


def test_negative_or_missing_balance_is_an_error(env):
    assert si.build_plan([balance_item("RoboInvestor", -5)], env)["errors"]
    assert si.build_plan([balance_item("RoboInvestor", None)], env)["errors"]


def test_huge_balance_change_is_a_warning(env):
    plan = si.build_plan([balance_item("RoboInvestor", 5000)], env)
    assert plan["errors"] == [] and plan["warnings"]


def test_two_different_values_for_one_account_is_an_error(env):
    assert si.build_plan([balance_item("RoboInvestor", 900), balance_item("RoboInvestor", 901)], env)["errors"]


# --- apply -----------------------------------------------------------------------------
def test_apply_writes_everything_and_backs_up(env):
    items = [holdings_item([row("VOO", 2, 500, 1000, cost=450), row("MSFT", 1, 400, 400)], cash=88.25),
             holdings_item([row("BRK-B", 2, 400, 800)], bucket="roth"),
             balance_item("RoboInvestor", 905.2)]
    result = si.apply_plan(items, env, accept_warnings=False, today=TODAY)
    assert result["ok"] is True
    brk = read_csv(os.path.join(env.root, "brokerage_holdings.csv"))
    assert brk["VOO"] == (2.0, 450.0) and brk["MSFT"] == (1.0, 400.0) and brk["AAPL"] == (2.0, 200.0)
    assert read_csv(os.path.join(env.root, "roth_ira_holdings.csv"))["BRK-B"][0] == 2.0
    assert read_csv(os.path.join(env.root, "hsa_holdings.csv")) == {"FXAIX": (5.0, 250.0)}
    accts = {a["name"]: a for a in ac.load_accounts(env.accounts)}
    assert accts["RoboInvestor"]["balance"] == 905.2 and accts["RoboInvestor"]["updated"] == TODAY
    assert accts["Webull Cash"]["balance"] == 88.25 and accts["Webull Cash"]["updated"] == TODAY
    assert accts["TOTAL CHECKING"]["plaid_account_id"] == "abc"  # untouched, still tagged
    port = json.load(open(env.portfolio))["holdings"]
    assert {(h["ticker"], h["account"]) for h in port} >= {("VOO", "brokerage"), ("BRK-B", "roth"),
                                                           ("FXAIX", "hsa")}
    assert os.path.isdir(result["backup"])
    assert os.path.exists(os.path.join(result["backup"], "brokerage_holdings.csv"))


def test_apply_replace_removes_positions(env):
    items = [holdings_item([row("VOO", 2, 500, 1000, cost=450)], mode="replace", positions_total=1000)]
    si.apply_plan(items, env, accept_warnings=False, today=TODAY)
    assert read_csv(os.path.join(env.root, "brokerage_holdings.csv")) == {"VOO": (2.0, 450.0)}


def test_apply_with_errors_writes_nothing(env):
    before = snapshot_files(env.root)
    with pytest.raises(si.PlanError):
        si.apply_plan([holdings_item([row("VOO", 2, 500, 1000)]), balance_item("TOTAL CHECKING", 1)],
                      env, accept_warnings=True, today=TODAY)
    assert snapshot_files(env.root) == before


def test_apply_blocks_on_warnings_until_accepted(env):
    items = [holdings_item([row("VOO", 2, 500, 1100, cost=450)])]
    before = snapshot_files(env.root)
    with pytest.raises(si.PlanBlocked) as ei:
        si.apply_plan(items, env, accept_warnings=False, today=TODAY)
    assert ei.value.warnings
    assert snapshot_files(env.root) == before
    si.apply_plan(items, env, accept_warnings=True, today=TODAY)
    assert read_csv(os.path.join(env.root, "brokerage_holdings.csv"))["VOO"][0] == 2.0


def test_apply_never_writes_non_finite_numbers(env):
    before = snapshot_files(env.root)
    for bad in (float("nan"), float("inf")):
        with pytest.raises(si.PlanError):
            si.apply_plan([holdings_item([row("VOO", bad, 500, 1000)])], env, accept_warnings=True, today=TODAY)
        with pytest.raises(si.PlanError):
            si.apply_plan([balance_item("RoboInvestor", bad)], env, accept_warnings=True, today=TODAY)
    assert snapshot_files(env.root) == before


# --- images ------------------------------------------------------------------------------
def test_check_image_accepts_png_jpeg_webp():
    from PIL import Image
    assert si.check_image(png_bytes()) == "image/png"
    buf = io.BytesIO()
    Image.new("RGB", (10, 10)).save(buf, "JPEG")
    assert si.check_image(buf.getvalue()) == "image/jpeg"
    buf = io.BytesIO()
    Image.new("RGB", (10, 10)).save(buf, "WEBP")
    assert si.check_image(buf.getvalue()) == "image/webp"


@pytest.mark.parametrize("blob", [b"", b"GIF89a....", b"<html></html>", b"%PDF-1.4", b"\x89PNG"[:2]])
def test_check_image_rejects_everything_else(blob):
    with pytest.raises(si.ImageError):
        si.check_image(blob)


def test_check_image_rejects_oversize():
    with pytest.raises(si.ImageError):
        si.check_image(b"\x89PNG\r\n\x1a\n" + b"0" * (si.MAX_IMAGE_BYTES + 1))


def test_prepare_image_shrinks_big_images_and_keeps_small_ones():
    from PIL import Image
    small = png_bytes((300, 200))
    assert si.prepare_image(small) == small
    big = png_bytes((4000, 1000))
    out = Image.open(io.BytesIO(si.prepare_image(big)))
    assert max(out.size) == si.MAX_SIDE


def test_prepare_image_rejects_truncated_files():
    with pytest.raises(si.ImageError):
        si.prepare_image(png_bytes()[:30])


# --- talking to the local vision model --------------------------------------------------------
def test_ollama_vision_sends_the_image_and_parses_json(monkeypatch):
    seen = {}

    def fake_post(url, payload, timeout):
        seen.update(url=url, payload=payload, timeout=timeout)
        return {"message": {"content": json.dumps(RAW)}}

    monkeypatch.setattr(si, "_post_json", fake_post)
    out = si.ollama_vision(png_bytes(), host="http://h:1", model="vm")
    assert out == RAW
    p = seen["payload"]
    assert seen["url"] == "http://h:1/api/chat" and p["model"] == "vm" and p["stream"] is False
    assert p["options"]["temperature"] == 0 and p["format"]
    assert base64.b64decode(p["messages"][-1]["images"][0]) == png_bytes()
    assert "JSON" in json.dumps(p["messages"])


def test_ollama_vision_tolerates_code_fences(monkeypatch):
    monkeypatch.setattr(si, "_post_json",
                        lambda *a, **k: {"message": {"content": "```json\n" + json.dumps(RAW) + "\n```"}})
    assert si.ollama_vision(png_bytes(), host="h", model="m") == RAW


def test_ollama_vision_bad_output_is_an_extract_error(monkeypatch):
    monkeypatch.setattr(si, "_post_json", lambda *a, **k: {"message": {"content": "I cannot read this."}})
    with pytest.raises(si.ExtractError):
        si.ollama_vision(png_bytes(), host="h", model="m")


def test_ollama_down_is_an_extract_error(monkeypatch):
    def boom(*a, **k):
        raise ConnectionRefusedError("nope")
    monkeypatch.setattr(si, "_post_json", boom)
    with pytest.raises(si.ExtractError) as ei:
        si.ollama_vision(png_bytes(), host="h", model="m")
    assert "ollama" in str(ei.value).lower()


def test_extract_accounts_uses_the_injected_vision_and_normalizes():
    seen = []

    def fake(image):
        seen.append(len(image))
        return RAW

    out = si.extract_accounts(png_bytes(), vision=fake)
    assert out[0]["positions"][1]["symbol"] == "BRK-B" and seen


def test_extract_accounts_with_nothing_readable_raises():
    with pytest.raises(si.ExtractError):
        si.extract_accounts(png_bytes(), vision=lambda image: {"accounts": []})


def test_extract_accounts_rejects_non_images_before_calling_the_model():
    called = []
    with pytest.raises(si.ImageError):
        si.extract_accounts(b"not an image", vision=lambda i: called.append(1))
    assert not called
