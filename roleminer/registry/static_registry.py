"""Static company registry — single source of truth for V1."""
import json
from pathlib import Path

_REGISTRY_FILE = Path(__file__).parent / "data" / "companies.json"


def load_companies() -> list[dict]:
    """Load companies from static JSON registry."""
    return json.loads(_REGISTRY_FILE.read_text(encoding="utf-8"))
