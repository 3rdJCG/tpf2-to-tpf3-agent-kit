"""Port Transport Fever 2 vehicle mods to Transport Fever 3.

    python port.py                  list the commands
    python port.py <vehicle> all    port one vehicle

See README.md. Everything lives in the tf3port package; this only makes it
runnable from anywhere without installing it.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tf3port.entry import main  # noqa: E402

if __name__ == "__main__":
    main()
