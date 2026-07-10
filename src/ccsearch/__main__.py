"""Enable `python -m ccsearch`. The fzf browser re-invokes ccsearch this way for its
reload/preview binds, so this entry point must stay in lockstep with the console script."""

import sys

from ccsearch.cli import main

if __name__ == "__main__":
    sys.exit(main())
