#!/usr/bin/env python3
"""Download and unpack the source markdown archive into data/input/.

    python -m prayer.extract.fetch [URL] [--dest DIR]

The source books are copyrighted and are not in the repository, so every
environment that builds the datasets — your laptop, CI, and the Docker image —
starts by fetching them from somewhere private. Reads `PRAYER_DATA_URL` and the
optional `PRAYER_DATA_TOKEN` from the environment when not given as arguments.

One implementation shared by all three callers, because the redirect handling
below is easy to get wrong and painful to debug in a container build.
"""
import argparse
import io
import os
import sys
import tarfile
import urllib.parse
import urllib.request
from pathlib import Path


class _StripAuthOnCrossHostRedirect(urllib.request.HTTPRedirectHandler):
    """Drop the Authorization header when a redirect crosses to another host.

    A GitHub release asset 302s to an S3 URL that carries its own signature.
    urllib replays every original header on the redirect, and S3 rejects a
    request bearing two auth mechanisms with an opaque 400 — so the naive
    version of this fetch fails exactly when pointed at a private repo, which
    is the case it exists to serve. curl has stripped cross-host auth by
    default since 7.58 for the same reason.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is None:
            return None
        if urllib.parse.urlparse(req.full_url).netloc != urllib.parse.urlparse(newurl).netloc:
            new.headers = {k: v for k, v in new.headers.items()
                           if k.lower() != "authorization"}
            new.unredirected_hdrs.pop("Authorization", None)
        return new


def fetch(url: str, dest: Path, token: str = "", timeout: int = 120) -> list[str]:
    """Fetch a tar.gz and extract it into `dest`. Returns the top-level names."""
    headers = {"User-Agent": "word-and-whisper/0.1"}
    if token:
        # Both are needed for a GitHub release asset: the bearer authorises the
        # request, the Accept makes the API return the bytes rather than JSON.
        headers["Authorization"] = f"Bearer {token}"
        headers["Accept"] = "application/octet-stream"

    opener = urllib.request.build_opener(_StripAuthOnCrossHostRedirect)
    req = urllib.request.Request(url, headers=headers)
    with opener.open(req, timeout=timeout) as resp:
        payload = resp.read()

    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(payload)) as tar:
        members = tar.getmembers()
        for m in members:
            # A tar entry is free to name ../../etc/passwd; refuse anything that
            # would land outside dest.
            target = (dest / m.name).resolve()
            if not target.is_relative_to(dest.resolve()):
                raise ValueError(f"archive entry escapes {dest}: {m.name!r}")
        tar.extractall(dest)
    # `tar -czf - -C dir .` names entries "./parks2021/x.md", and macOS adds
    # AppleDouble "._" siblings; neither belongs in the summary line.
    tops = set()
    for m in members:
        head = m.name.removeprefix("./").split("/")[0]
        if head and head != "." and not head.startswith("._"):
            tops.add(head)
    return sorted(tops)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("url", nargs="?", default=os.environ.get("PRAYER_DATA_URL", ""))
    ap.add_argument("--dest", type=Path, default=None)
    ap.add_argument("--token", default=os.environ.get("PRAYER_DATA_TOKEN", ""))
    args = ap.parse_args(argv)

    if not args.url:
        print("PRAYER_DATA_URL is not set.\n"
              "The source books are copyrighted and are not in this repository.\n"
              "Point it at a tar.gz of data/input/, and set PRAYER_DATA_TOKEN\n"
              "as well when that URL needs authentication.", file=sys.stderr)
        return 1

    dest = args.dest
    if dest is None:
        from prayer import paths
        dest = paths.INPUT

    try:
        names = fetch(args.url, dest, args.token)
    except Exception as exc:                       # noqa: BLE001 - reported, not swallowed
        print(f"fetch failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        if not args.token:
            print("hint: no token was supplied; a private URL needs "
                  "PRAYER_DATA_TOKEN", file=sys.stderr)
        return 1
    print(f"input: {' '.join(names)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
