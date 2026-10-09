"""Put the repo root on sys.path so tests can import the pipeline packages
(``fno_history``, ``index_history``) under plain ``pytest`` as CI runs it."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
