"""Run the whole dataset build: three extractors, then the link table.

    python -m prayer.extract          # or: prayer-extract

Each step is deterministic and the whole thing takes about a second, which is
why deployment rebuilds the data rather than shipping a prebuilt artifact.
"""
import sys

from prayer.extract import lockyer, links, parks, watters

STEPS = [("parks", parks), ("lockyer", lockyer), ("watters", watters),
         ("links", links)]


def main() -> int:
    for name, mod in STEPS:
        argv = sys.argv[1:]
        sys.argv = [f"prayer-extract-{name}", *argv]
        rc = mod.main()
        if rc:
            print(f"FAILED at {name}", file=sys.stderr)
            return rc
    return 0


if __name__ == "__main__":
    sys.exit(main())
