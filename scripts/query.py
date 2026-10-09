#!/usr/bin/env python3
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
VENV_PYTHON = REPO_ROOT / ".venv" / "bin" / "python3"
RUNNING_IN_A_VENV = sys.prefix != sys.base_prefix

if VENV_PYTHON.exists() and not RUNNING_IN_A_VENV:
    os.execv(str(VENV_PYTHON), [str(VENV_PYTHON), str(Path(__file__).resolve())] + sys.argv[1:])

sys.path.insert(0, str(REPO_ROOT / "src"))

from chatplayground_skill.cli_query import main

if __name__ == "__main__":
    sys.exit(main())
