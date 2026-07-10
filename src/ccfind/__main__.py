"""Enable `python -m ccfind`. The fzf browser re-invokes ccfind this way for its
reload/preview binds, so this entry point must stay in lockstep with the console script."""

import sys

from ccfind.cli import main

if __name__ == "__main__":
    sys.exit(main())
