"""
Sentinel Launcher - Root Workspace Entry Point
Forwards execution to sentinel-laptop-core/run_sentinel.py
"""

import sys
import subprocess
from pathlib import Path

core_dir = Path(__file__).resolve().parent / "sentinel-laptop-core"
script = core_dir / "run_sentinel.py"

if __name__ == "__main__":
    cmd = [sys.executable, str(script)] + sys.argv[1:]
    sys.exit(subprocess.call(cmd, cwd=str(core_dir)))
