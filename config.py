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
CHROMA_PATH = ROOT / "roleminer" / "registry" / "chroma"
SEARCH_PROFILE = ROOT / "search_profile.yaml"
RESUME_PDF = ROOT / "resume.pdf"

LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "")  # e.g. https://opencode.ai/zen/v1
SCORING_MODEL = os.getenv("SCORING_MODEL", "gemini-3-flash")
PROXY_URL = os.getenv("PROXY_URL", "")
SCRAPER_FRESHNESS_HOURS = int(os.getenv("SCRAPER_FRESHNESS_HOURS", "24"))

BRAVE_SEARCH_API_KEY = os.getenv("BRAVE_SEARCH_API_KEY", "")
DISCOVER_MODEL = os.getenv("DISCOVER_MODEL", "tencent/hy3-preview:free")

EMBED_API_KEY = os.getenv("EMBED_API_KEY", os.getenv("LLM_API_KEY", ""))
EMBED_BASE_URL = os.getenv("EMBED_BASE_URL", "https://openrouter.ai/api/v1")
EMBED_MODEL = os.getenv("EMBED_MODEL", "nvidia/llama-nemotron-embed-vl-1b-v2:free")
