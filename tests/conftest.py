import os
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="session", autouse=True)
def _isolated_workspace(tmp_path_factory):
    ws = tmp_path_factory.mktemp("ws")
    os.environ["Q2E_WORKSPACE"] = str(ws)
    os.environ.setdefault("Q2E_LLM_PROVIDER", "offline")
    from q2e import config
    config.settings.workspace = ws
    from q2e import store as st
    st.store.root = ws / "projects"
    st.store.root.mkdir(parents=True, exist_ok=True)
    yield


HAS_R = shutil.which("Rscript") is not None
requires_r = pytest.mark.skipif(not HAS_R, reason="Rscript not available")
