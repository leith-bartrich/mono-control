"""Enable `python -m mono_control`."""

import sys

from mono_control.cli import main

if __name__ == "__main__":
    sys.exit(main())
