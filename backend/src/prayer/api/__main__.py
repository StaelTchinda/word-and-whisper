"""Serve the API.

    python -m prayer.api            # or: prayer-serve
"""
import os
import sys


def main() -> int:
    import uvicorn
    uvicorn.run("prayer.api.app:app",
                host=os.environ.get("PRAYER_HOST", "127.0.0.1"),
                # PORT is injected by the host platform (Render, Cloud Run,
                # Heroku) and is the port it routes to, so it outranks the
                # image's own default. Unset on a laptop, so nothing changes
                # locally.
                port=int(os.environ.get("PORT") or os.environ.get("PRAYER_PORT", "8000")),
                reload=bool(os.environ.get("PRAYER_RELOAD")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
