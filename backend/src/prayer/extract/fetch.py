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
import tempfile
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


def download(url: str, timeout: int = 120) -> tuple[bytes, str, str]:
    """Return (payload, final_url, content_type). Follows redirects."""
    req = urllib.request.Request(url, headers={"User-Agent": "word-and-whisper/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read(), resp.geturl(), resp.headers.get("Content-Type", "")


def fetch(url: str, dest: Path, timeout: int = 120) -> list[str]:
    """Fetch a .zip or .tar.gz archive and extract it into `dest`."""
    payload, _, _ = download(url, timeout)
    return extract(payload, dest)


def check(url: str, timeout: int = 120) -> int:
    """Report what a URL actually serves, without extracting anything.

    Worth its own command because the failure it diagnoses — a share link that
    serves its HTML viewer page rather than the file — otherwise only shows up
    inside a CI run or a container build, minutes away from the person who can
    fix it.
    """
    try:
        payload, final_url, content_type = download(url, timeout)
    except Exception as exc:                       # noqa: BLE001 - reported
        print(f"FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print(f"  status       200, {len(payload):,} bytes")
    print(f"  content-type {content_type or '(none)'}")
    if final_url != url:
        print(f"  redirected   {final_url[:100]}")
    print(f"  first bytes  {payload[:8]!r}")

    try:
        with tempfile.TemporaryDirectory() as tmp:
            names = extract(payload, Path(tmp))
    except ValueError as exc:
        print(f"\nNOT USABLE: {exc}", file=sys.stderr)
        if payload[:1] == b"<":
            print("\nThis is a web page, not the file. Share links usually need "
                  "converting:\n"
                  "  Google Drive  https://drive.google.com/uc?export=download&id=FILE_ID\n"
                  "  Dropbox       end the link with ?dl=1 instead of ?dl=0\n"
                  "  OneDrive      use the 'Embed'/direct link, not the share link",
                  file=sys.stderr)
        return 1

    missing = {"parks2021", "lockyer1959", "watters1883"} - set(names)
    print(f"  archive      OK, top level: {', '.join(names)}")
    if missing:
        print(f"\nNOT USABLE: archive is missing {', '.join(sorted(missing))}",
              file=sys.stderr)
        return 1
    print("\nusable — make fetch will work with this URL")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("url", nargs="?", default=os.environ.get("PRAYER_DATA_URL", ""))
    ap.add_argument("--dest", type=Path, default=None)
    ap.add_argument("--check", action="store_true",
                    help="report what the URL serves; extract nothing")
    args = ap.parse_args(argv)

    if not args.url:
        print("PRAYER_DATA_URL is not set.\n"
              "The source books are copyrighted and are not in this repository.\n"
              "Point it at a direct-download link to a .zip or .tar.gz of "
              "data/input/.", file=sys.stderr)
        return 1

    if args.check:
        print(f"checking {args.url[:80]}{'…' if len(args.url) > 80 else ''}")
        return check(args.url)

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
