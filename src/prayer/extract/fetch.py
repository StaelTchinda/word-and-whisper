#!/usr/bin/env python3
"""Download and unpack the source markdown archive into data/input/.

    python -m prayer.extract.fetch [URL] [--dest DIR]

The source books are copyrighted and are not in the repository, so every
environment that builds the datasets — your laptop, CI, and the Docker image —
starts by fetching them. Reads `PRAYER_DATA_URL` from the environment when the
URL is not given as an argument.

The URL must need no authentication: a plain or pre-signed direct-download
link. Anyone holding it can download the books, so prefer a host where the
object behind the link can be swapped without changing anything here.
"""
import argparse
import io
import os
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path


def _top_levels(names: list[str]) -> list[str]:
    # `tar -czf - -C dir .` names entries "./parks2021/x.md", and macOS adds
    # AppleDouble "._" siblings; neither belongs in the summary line.
    tops = set()
    for name in names:
        head = name.removeprefix("./").split("/")[0]
        if head and head != "." and not head.startswith("._"):
            tops.add(head)
    return sorted(tops)


def _guard(dest: Path, names: list[str]) -> None:
    """Refuse any entry that would write outside `dest`.

    An archive is free to name `../../etc/passwd` — the zip form of this even
    has a name, "zip slip". Checked identically for both formats.
    """
    root = dest.resolve()
    for name in names:
        if not (dest / name).resolve().is_relative_to(root):
            raise ValueError(f"archive entry escapes {dest}: {name!r}")


def extract(payload: bytes, dest: Path) -> list[str]:
    """Unpack a .zip or .tar.gz into `dest`. Returns the top-level names.

    The format is sniffed from the magic bytes rather than the URL, because a
    download link often carries no usable extension — Google Drive serves
    `uc?export=download&id=…`, for one.
    """
    dest.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO(payload)

    if payload[:4] in (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"):
        with zipfile.ZipFile(buf) as zf:
            names = zf.namelist()
            _guard(dest, names)
            zf.extractall(dest)
        return _top_levels(names)

    if payload[:2] == b"\x1f\x8b" or payload[257:262] == b"ustar":
        with tarfile.open(fileobj=buf) as tar:
            names = [m.name for m in tar.getmembers()]
            _guard(dest, names)
            tar.extractall(dest)
        return _top_levels(names)

    raise ValueError("downloaded data is neither a .zip nor a .tar.gz "
                     f"(starts with {payload[:8]!r}) — check the URL serves the "
                     "file itself rather than an HTML download page")


def fetch(url: str, dest: Path, timeout: int = 120) -> list[str]:
    """Fetch a .zip or .tar.gz archive and extract it into `dest`."""
    req = urllib.request.Request(url, headers={"User-Agent": "word-and-whisper/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = resp.read()
    return extract(payload, dest)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("url", nargs="?", default=os.environ.get("PRAYER_DATA_URL", ""))
    ap.add_argument("--dest", type=Path, default=None)
    args = ap.parse_args(argv)

    if not args.url:
        print("PRAYER_DATA_URL is not set.\n"
              "The source books are copyrighted and are not in this repository.\n"
              "Point it at a direct-download link to a .zip or .tar.gz of "
              "data/input/.", file=sys.stderr)
        return 1

    dest = args.dest
    if dest is None:
        from prayer import paths
        dest = paths.INPUT

    try:
        names = fetch(args.url, dest)
    except Exception as exc:                       # noqa: BLE001 - reported, not swallowed
        print(f"fetch failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(f"input: {' '.join(names)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
