import os
from pathlib import Path

ROOT = Path(__file__).parent
OUTPUT_DIR = ROOT / "output"
DB_PATH = ROOT / "roleminer" / "registry" / "roleminer.db"
SEARCH_PROFILE = ROOT / "search_profile.yaml"
RESUME_PDF = ROOT / "resume.pdf"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
SCORING_MODEL = os.getenv("SCORING_MODEL", "gpt-4o-mini")
PROXY_URL = os.getenv("PROXY_URL", "")
