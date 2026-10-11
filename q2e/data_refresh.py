"""Keep downloaded NHANES files in step with CDC.

BEDSIDE downloads each CDC file the first time a study needs it and reuses that copy afterwards. CDC sometimes
re-releases a file with corrections; `python -m q2e refresh-data` downloads every cached file again, compares checksums
and replaces the ones CDC changed (`--check` only reports). Earlier results stay traceable: every run records the MD5
of each file it used.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import tempfile
import urllib.request
from pathlib import Path

from .config import settings
from .knowledge import get_knowledge

URL = "https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/{folder}/DataFiles/{name}.xpt"


def _cycle_of(name: str) -> str | None:
    if name.startswith("P_"):
        return "P"
    m = re.search(r"_([B-Z])$", name)
    return m.group(1) if m else "A"


def _md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def _fetch(url: str, dest: Path) -> bool:
    with urllib.request.urlopen(url, timeout=300) as r, open(dest, "wb") as fh:
        fh.write(r.read())
    return dest.stat().st_size >= 1000 and dest.read_bytes()[:20] == b"HEADER RECORD*******"


def refresh(check_only: bool = False, fetch=_fetch, log=print) -> dict:
    k = get_knowledge()
    cache = Path(settings.cache_dir) if hasattr(settings, "cache_dir") else settings.root / "data" / "cache"
    files = sorted(cache.glob("*.xpt")) + sorted(cache.glob("*.XPT"))
    out = {"checked": 0, "unchanged": [], "updated": [], "failed": [], "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
    if not files:
        log(f"No downloaded CDC files in {cache} yet - they download automatically the first time a study needs them.")
        return out
    for f in files:
        name = f.stem
        cyc = _cycle_of(name)
        folder = (k.cycles.get(cyc) or {}).get("url_folder")
        if not folder:
            out["failed"].append(f"{name}: unknown survey cycle")
            continue
        url = URL.format(folder=folder, name=name)
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / f.name
            try:
                ok = fetch(url, tmp)
            except Exception as e:  # noqa: BLE001 - report and continue with the next file
                out["failed"].append(f"{name}: {str(e)[:120]}")
                continue
            out["checked"] += 1
            if not ok:
                out["failed"].append(f"{name}: CDC did not return a data file")
                continue
            if _md5(tmp) == _md5(f):
                out["unchanged"].append(name)
                continue
            out["updated"].append(name)
            if not check_only:
                f.write_bytes(tmp.read_bytes())
        log(f"  {name}: " + ("CHANGED at CDC" + (" (not replaced: --check)" if check_only else " - replaced") if name in out["updated"] else "unchanged"))
    (cache / "refresh_log.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    log(f"Checked {out['checked']} file(s): {len(out['updated'])} changed, {len(out['unchanged'])} unchanged, {len(out['failed'])} failed."
        + (" Re-run affected studies to use the new data." if out["updated"] and not check_only else ""))
    return out
