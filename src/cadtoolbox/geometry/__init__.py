"""Load backend with caches scoped to this project, never a source project."""
import os
from pathlib import Path
_cache = Path(__file__).resolve().parents[3] / '.cache'
os.environ.setdefault('XDG_CACHE_HOME',str(_cache))
os.environ.setdefault('MPLCONFIGDIR',str(_cache/'matplotlib'))
