import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "sources"
if str(SOURCES) not in sys.path:
    sys.path.insert(0, str(SOURCES))
