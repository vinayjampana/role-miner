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
RESUME_DIR = ROOT / "data" / "resumes"
# Legacy single-file path (migrated to RESUME_DIR / "<user_id>.pdf" per user)
RESUME_PDF = ROOT / "resume.pdf"

LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "")  # e.g. https://opencode.ai/zen/v1
SCORING_MODEL = os.getenv("SCORING_MODEL", "gemini-3-flash")
PROXY_URL = os.getenv("PROXY_URL", "")
SCRAPER_FRESHNESS_HOURS = int(os.getenv("SCRAPER_FRESHNESS_HOURS", "24"))
SCRAPER_DELAY_MIN = float(os.getenv("SCRAPER_DELAY_MIN", "5"))
SCRAPER_DELAY_MAX = float(os.getenv("SCRAPER_DELAY_MAX", "15"))
SCRAPER_PAGINATION_DELAY_MIN = float(os.getenv("SCRAPER_PAGINATION_DELAY_MIN", "2"))
SCRAPER_PAGINATION_DELAY_MAX = float(os.getenv("SCRAPER_PAGINATION_DELAY_MAX", "6"))

BRAVE_SEARCH_API_KEY = os.getenv("BRAVE_SEARCH_API_KEY", "")
DISCOVER_MODEL = os.getenv("DISCOVER_MODEL", "tencent/hy3-preview:free")


def _resolve_embed_api_key() -> str:
    """
    Key for OpenRouter (or other) embeddings.

    If EMBED_API_KEY is unset or blank (including `EMBED_API_KEY=` in .env),
    fall back to LLM_API_KEY so embeddings still authenticate.
    """
    for key in (os.getenv("EMBED_API_KEY"), os.getenv("LLM_API_KEY")):
        if key and str(key).strip():
            return str(key).strip()
    return ""


EMBED_API_KEY = _resolve_embed_api_key()
EMBED_BASE_URL = os.getenv("EMBED_BASE_URL", "https://openrouter.ai/api/v1")
EMBED_MODEL = os.getenv("EMBED_MODEL", "nvidia/llama-nemotron-embed-vl-1b-v2:free")


def sync_from_environ() -> None:
    """
    Refresh module-level settings from os.environ.
    Call after updating the process environment (e.g. merged .env from the API)
    so the running server and pipeline see new keys without a restart.
    """
    import sys

    m = sys.modules[__name__]
    m.LLM_API_KEY = os.getenv("LLM_API_KEY", "")
    m.LLM_BASE_URL = os.getenv("LLM_BASE_URL", "")
    m.SCORING_MODEL = os.getenv("SCORING_MODEL", "gemini-3-flash")
    m.PROXY_URL = os.getenv("PROXY_URL", "")
    m.SCRAPER_FRESHNESS_HOURS = int(os.getenv("SCRAPER_FRESHNESS_HOURS", "24"))
    m.SCRAPER_DELAY_MIN = float(os.getenv("SCRAPER_DELAY_MIN", "5"))
    m.SCRAPER_DELAY_MAX = float(os.getenv("SCRAPER_DELAY_MAX", "15"))
    m.SCRAPER_PAGINATION_DELAY_MIN = float(os.getenv("SCRAPER_PAGINATION_DELAY_MIN", "2"))
    m.SCRAPER_PAGINATION_DELAY_MAX = float(os.getenv("SCRAPER_PAGINATION_DELAY_MAX", "6"))
    m.BRAVE_SEARCH_API_KEY = os.getenv("BRAVE_SEARCH_API_KEY", "")
    m.DISCOVER_MODEL = os.getenv("DISCOVER_MODEL", "tencent/hy3-preview:free")
    m.EMBED_API_KEY = _resolve_embed_api_key()
    m.EMBED_BASE_URL = os.getenv("EMBED_BASE_URL", "https://openrouter.ai/api/v1")
    m.EMBED_MODEL = os.getenv("EMBED_MODEL", "nvidia/llama-nemotron-embed-vl-1b-v2:free")
