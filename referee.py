"""入口：python referee.py <test|crap|mutation|check> ..."""

import sys

from referee.cli import main

if __name__ == "__main__":
    sys.exit(main())
