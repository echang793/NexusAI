"""datastore_backup.py: nightly rotating copy of the data files (never .env)."""

import datetime
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import datastore_backup as bk  # noqa: E402


def make(root, **files):
    for name, content in files.items():
        (root / name).write_text(content)


def test_copies_existing_data_files_and_skips_missing_ones(tmp_path):
    make(tmp_path, **{"accounts.json": "A", "nw_history.json": "NW"})
    r = bk.backup_daily(str(tmp_path), datetime.date(2026, 11, 14))
    day = tmp_path / "backups" / "daily" / "2026-11-14"
    assert (day / "accounts.json").read_text() == "A" and (day / "nw_history.json").read_text() == "NW"
    assert sorted(r["copied"]) == ["accounts.json", "nw_history.json"] and r["dir"] == str(day)
    assert not (day / "profile.json").exists()


def test_secrets_are_never_copied(tmp_path):
    make(tmp_path, **{".env": "PLAID_SECRET=x", "accounts.json": "A"})
    bk.backup_daily(str(tmp_path), datetime.date(2026, 11, 14))
    day = tmp_path / "backups" / "daily" / "2026-11-14"
    assert not (day / ".env").exists() and ".env" not in bk.DATA_FILES


def test_rerun_same_day_overwrites_instead_of_duplicating(tmp_path):
    make(tmp_path, **{"accounts.json": "old"})
    bk.backup_daily(str(tmp_path), datetime.date(2026, 11, 14))
    make(tmp_path, **{"accounts.json": "new"})
    bk.backup_daily(str(tmp_path), datetime.date(2026, 11, 14))
    assert (tmp_path / "backups" / "daily" / "2026-11-14" / "accounts.json").read_text() == "new"
    assert len(os.listdir(tmp_path / "backups" / "daily")) == 1


def test_only_the_newest_n_days_are_kept(tmp_path):
    make(tmp_path, **{"accounts.json": "A"})
    for i in range(1, 8):
        bk.backup_daily(str(tmp_path), datetime.date(2026, 11, i), keep=3)
    assert sorted(os.listdir(tmp_path / "backups" / "daily")) == ["2026-11-05", "2026-11-06", "2026-11-07"]


def test_nothing_to_back_up_is_reported_not_an_error(tmp_path):
    r = bk.backup_daily(str(tmp_path), datetime.date(2026, 11, 14))
    assert r["copied"] == []


def test_a_copy_that_does_not_match_the_source_fails_loudly(tmp_path, monkeypatch):
    make(tmp_path, **{"accounts.json": "AAAA"})
    real = bk.shutil.copy2
    def bad_copy(src, dst, *a, **k):
        real(src, dst, *a, **k)
        open(dst, "w").write("A")          # truncated copy
    monkeypatch.setattr(bk.shutil, "copy2", bad_copy)
    with pytest.raises(bk.BackupError):
        bk.backup_daily(str(tmp_path), datetime.date(2026, 11, 14))


def test_backup_dir_is_private(tmp_path):
    make(tmp_path, **{"accounts.json": "A"})
    bk.backup_daily(str(tmp_path), datetime.date(2026, 11, 14))
    mode = os.stat(tmp_path / "backups" / "daily" / "2026-11-14").st_mode & 0o777
    assert mode == 0o700


def test_webull_backup_pruning_does_not_touch_the_daily_folder(tmp_path):
    import webull_import as wi
    (tmp_path / "backups" / "daily" / "2026-11-14").mkdir(parents=True)
    for i in range(1, 16):
        (tmp_path / "backups" / f"2026-10-{i:02d}_120000").mkdir(parents=True)
    f = tmp_path / "x.csv"; f.write_text("t")
    wi._backup(str(tmp_path), [str(f)])
    names = os.listdir(tmp_path / "backups")
    assert "daily" in names
    assert len([n for n in names if n != "daily"]) == wi.KEEP_BACKUPS


def test_backed_up_files_are_owner_only(tmp_path):
    f = tmp_path / "daily_history.json"
    f.write_text("x")
    os.chmod(f, 0o644)                                   # source is world-readable
    bk.backup_daily(str(tmp_path), datetime.date(2026, 11, 14))
    mode = os.stat(tmp_path / "backups" / "daily" / "2026-11-14" / "daily_history.json").st_mode & 0o777
    assert mode == 0o600


def test_new_data_stores_write_owner_only_files(tmp_path, monkeypatch):
    import daily_history, transactions, investment_flows
    monkeypatch.setattr(daily_history, "HISTORY_FILE", str(tmp_path / "d.json"))
    monkeypatch.setattr(transactions, "TX_FILE", str(tmp_path / "t.json"))
    monkeypatch.setattr(investment_flows, "FLOWS_FILE", str(tmp_path / "f.json"))
    daily_history.record_day("2026-11-14", 1, {}, [], True)
    transactions.apply_sync("k", [], [], [], "c")
    investment_flows.save({"months": {}, "synced_at": None})
    for name in ("d.json", "t.json", "f.json"):
        assert os.stat(tmp_path / name).st_mode & 0o777 == 0o600, name


def test_net_worth_history_file_is_owner_only(tmp_path, monkeypatch):
    import nw_snapshots
    monkeypatch.setattr(nw_snapshots, "SNAPSHOT_FILE", str(tmp_path / "nw.json"))
    nw_snapshots.record_snapshot(1000, 500, 500, 0)
    assert os.stat(tmp_path / "nw.json").st_mode & 0o777 == 0o600
