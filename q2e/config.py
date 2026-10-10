"""Runtime configuration (environment variables, paths)."""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _load_dotenv() -> None:
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv()

R_DOWNLOAD_URL = "https://cran.r-project.org/bin/windows/base/" if os.name == "nt" else "https://cran.r-project.org/"


def find_rscript(override: str = "") -> str | None:
    """Find the Rscript program: the Q2E_RSCRIPT setting, the PATH, then the usual Windows install folders
    (the R installer does not add itself to PATH, so a freshly installed R is otherwise invisible)."""
    if override:
        return override if Path(override).is_file() else shutil.which(override)
    found = shutil.which("Rscript")
    if found:
        return found
    if os.name == "nt":
        roots = [os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", ""),
                 os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs")]
        hits = [p for r in roots if r for p in Path(r).glob("R/R-*/bin/Rscript.exe")]
        if hits:
            return str(max(hits, key=lambda p: [int(x) if x.isdigit() else 0 for x in p.parent.parent.name[2:].split(".")]))
    return None


@dataclass
class Settings:
    root: Path = ROOT
    knowledge_dir: Path = ROOT / "knowledge"
    engine_script: Path = ROOT / "r" / "engine" / "run_pipeline.R"
    synth_script: Path = ROOT / "r" / "synth" / "make_synthetic_nhanes.R"
    workspace: Path = field(default_factory=lambda: Path(_env("Q2E_WORKSPACE", str(ROOT / "workspace"))))
    nhanes_dir: str = field(default_factory=lambda: _env("Q2E_NHANES_DIR", str(ROOT / "data" / "nhanes")))
    synthetic_dir: Path = ROOT / "data" / "synthetic"
    cache_dir: Path = field(default_factory=lambda: Path(_env("Q2E_CACHE_DIR", str(ROOT / "data" / "cache"))))
    allow_download: bool = field(default_factory=lambda: _env("Q2E_ALLOW_DOWNLOAD", "true").lower() == "true")
    rscript_override: str = field(default_factory=lambda: _env("Q2E_RSCRIPT"))
    run_timeout: int = field(default_factory=lambda: int(_env("Q2E_RUN_TIMEOUT", "900")))
    # LLM / governance
    llm_provider: str = field(default_factory=lambda: _env("Q2E_LLM_PROVIDER", "offline"))
    data_policy: str = field(default_factory=lambda: _env("Q2E_DATA_POLICY", "public"))  # public | restricted
    approved_providers: list[str] = field(default_factory=lambda: [p.strip() for p in _env(
        "Q2E_APPROVED_PROVIDERS", "offline,ollama,azure_openai,bedrock").split(",") if p.strip()])
    send_aggregates_to_llm: bool = field(default_factory=lambda: _env("Q2E_SEND_AGGREGATES", "true").lower() == "true")
    # Voice
    elevenlabs_key: str = field(default_factory=lambda: _env("ELEVENLABS_API_KEY"))
    elevenlabs_voice: str = field(default_factory=lambda: _env("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM"))
    elevenlabs_tts_model: str = field(default_factory=lambda: _env("ELEVENLABS_TTS_MODEL", "eleven_multilingual_v2"))
    elevenlabs_stt_model: str = field(default_factory=lambda: _env("ELEVENLABS_STT_MODEL", "scribe_v1"))
    ncbi_email: str = field(default_factory=lambda: _env("NCBI_EMAIL"))
    ncbi_api_key: str = field(default_factory=lambda: _env("NCBI_API_KEY"))
    public_url: str = field(default_factory=lambda: _env("Q2E_PUBLIC_URL", "http://127.0.0.1:8000"))
    tool_key: str = field(default_factory=lambda: _env("Q2E_TOOL_KEY"))

    @property
    def rscript(self) -> str:
        """Path to Rscript. Looked up on every call, so installing R while the server runs just works."""
        return find_rscript(self.rscript_override) or self.rscript_override or "Rscript"

    @rscript.setter
    def rscript(self, value: str) -> None:
        self.rscript_override = value

    def ensure_dirs(self) -> None:
        for p in (self.workspace, self.workspace / "projects", self.workspace / "datasets", self.cache_dir):
            Path(p).mkdir(parents=True, exist_ok=True)


settings = Settings()
