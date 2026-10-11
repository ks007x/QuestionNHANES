"""refresh-data: re-download cached CDC files, replace only the ones CDC changed."""
from pathlib import Path

from q2e import data_refresh

XPT = b"HEADER RECORD*******" + b"x" * 2000


def test_refresh_replaces_only_changed(tmp_path, monkeypatch):
    monkeypatch.setattr(data_refresh.settings, "cache_dir", tmp_path)
    (tmp_path / "DEMO_L.xpt").write_bytes(XPT)
    (tmp_path / "P_GHB.xpt").write_bytes(XPT)
    seen = []

    def fake_fetch(url, dest):
        seen.append(url)
        dest.write_bytes(XPT + (b"new" if "GHB" in url else b""))
        return True

    out = data_refresh.refresh(check_only=True, fetch=fake_fetch, log=lambda *_: None)
    assert out["updated"] == ["P_GHB"] and out["unchanged"] == ["DEMO_L"]
    assert (tmp_path / "P_GHB.xpt").read_bytes() == XPT                          # --check leaves files alone
    assert "Public/2021/DataFiles/DEMO_L.xpt" in seen[0] and "Public/2017/DataFiles/P_GHB.xpt" in seen[1]
    data_refresh.refresh(fetch=fake_fetch, log=lambda *_: None)
    assert (tmp_path / "P_GHB.xpt").read_bytes().endswith(b"new")             # replaced
    assert (tmp_path / "refresh_log.json").exists()


def test_cycle_from_file_name():
    assert [data_refresh._cycle_of(n) for n in ("DEMO", "DEMO_B", "P_DEMO", "SSTOCA_G")] == ["A", "B", "P", "G"]
