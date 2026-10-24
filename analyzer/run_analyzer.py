"""Entry point: `python run_analyzer.py [log.TXT|file.csv]`."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from parallax_bb.ui import main  # noqa: E402

if __name__ == "__main__":
    main()
