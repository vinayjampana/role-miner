import os
from pathlib import Path

ROOT = Path(__file__).parent

# Load .env if present (never commit .env)
_env_file = ROOT / ".env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())
OUTPUT_DIR = ROOT / "output"
DB_PATH = ROOT / "roleminer" / "registry" / "roleminer.db"
SEARCH_PROFILE = ROOT / "search_profile.yaml"
RESUME_PDF = ROOT / "resume.pdf"

LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "")  # e.g. https://opencode.ai/zen/v1
SCORING_MODEL = os.getenv("SCORING_MODEL", "gemini-3-flash")
PROXY_URL = os.getenv("PROXY_URL", "")
