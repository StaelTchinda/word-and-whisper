"""Serve the API.

    python -m prayer.api            # or: prayer-serve
"""
import os
import sys


def main() -> int:
    import uvicorn
    uvicorn.run("prayer.api.app:app",
                host=os.environ.get("PRAYER_HOST", "127.0.0.1"),
                port=int(os.environ.get("PRAYER_PORT", "8000")),
                reload=bool(os.environ.get("PRAYER_RELOAD")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
