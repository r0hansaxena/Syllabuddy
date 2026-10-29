import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("STUDY_DATA_DIR", ROOT / "data"))
UPLOAD_DIR = DATA_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

EMBED_MODEL = "BAAI/bge-small-en-v1.5"
CHUNK_WORDS = 200
# Optional fixed AI connection (e.g. on a server). Without it, Atlas auto-detects or uses what Settings saved.
AI_BASE_URL = os.environ.get("STUDY_AI_BASE_URL", "")
AI_MODEL = os.environ.get("STUDY_AI_MODEL", "")
AI_KEY = os.environ.get("STUDY_AI_KEY", "")
OFFLINE = os.environ.get("STUDY_OFFLINE") == "1"  # force offline mode (for testing)
