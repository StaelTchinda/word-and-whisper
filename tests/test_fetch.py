"""Tests for the source-archive fetch.

This runs in one place that matters and is hard to debug there: inside a
container build on a deploy platform.
"""
import io
import tarfile
import urllib.error
import urllib.request
import zipfile

import pytest

from prayer.extract.fetch import check, extract, fetch, main

NAMES = ("parks2021/a.md", "lockyer1959/b.md")


def _targz(names=NAMES) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name in names:
            data = b"# hello\n"
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _zip(names=NAMES) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name in names:
            zf.writestr(name, "# hello\n")
    return buf.getvalue()


# Both formats must behave identically; the URL often has no usable extension,
# so the format is sniffed from the bytes.
ARCHIVES = pytest.mark.parametrize("build", [_targz, _zip], ids=["tar.gz", "zip"])


@ARCHIVES
def test_extract_handles_both_formats(tmp_path, build):
    names = extract(build(), tmp_path)
    assert names == ["lockyer1959", "parks2021"]
    assert (tmp_path / "parks2021/a.md").read_text() == "# hello\n"


@ARCHIVES
def test_extract_refuses_an_entry_that_escapes(tmp_path, build):
    with pytest.raises(ValueError, match="escapes"):
        extract(build(("../escape.md",)), tmp_path)
    assert not (tmp_path.parent / "escape.md").exists()


def test_extract_rejects_something_that_is_neither(tmp_path):
    with pytest.raises(ValueError, match="neither a .zip nor a .tar.gz"):
        extract(b"<!doctype html><title>Download</title>", tmp_path)


class _Resp(io.BytesIO):
    """Enough of an http.client.HTTPResponse for download() to work with."""

    headers = {"Content-Type": "application/octet-stream"}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def geturl(self):
        return "https://example.invalid/final"


def _serve(monkeypatch, payload: bytes):
    monkeypatch.setattr(urllib.request.OpenerDirector, "open",
                        lambda self, req, data=None, timeout=None: _Resp(payload))


@pytest.fixture
def served(monkeypatch):
    """Capture the request urllib would send, and reply with an archive."""
    seen = {}

    def fake_open(self, req, data=None, timeout=None):
        seen["url"] = req.full_url
        seen["headers"] = {k.lower(): v for k, v in req.headers.items()}
        return _Resp(_targz())

    monkeypatch.setattr(urllib.request.OpenerDirector, "open", fake_open)
    return seen


def test_extracts_into_dest(tmp_path, served):
    names = fetch("https://example.invalid/input.tar.gz", tmp_path)
    assert sorted(names) == ["lockyer1959", "parks2021"]
    assert (tmp_path / "parks2021/a.md").read_text() == "# hello\n"


def test_sends_no_authorization_header(tmp_path, served):
    """The URL must be one that needs no credentials."""
    fetch("https://example.invalid/input.zip", tmp_path)
    assert "authorization" not in served["headers"]


def test_main_without_a_url_explains_itself(capsys, monkeypatch):
    monkeypatch.delenv("PRAYER_DATA_URL", raising=False)
    assert main([]) == 1
    err = capsys.readouterr().err
    assert "PRAYER_DATA_URL is not set" in err
    assert "copyrighted" in err


def test_main_reports_a_refusal(capsys, monkeypatch, tmp_path):
    def boom(self, req, data=None, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)

    monkeypatch.setattr(urllib.request.OpenerDirector, "open", boom)
    assert main(["https://example.invalid/x.zip", "--dest", str(tmp_path)]) == 1
    assert "fetch failed" in capsys.readouterr().err


def test_main_names_the_wrong_link_mistake(capsys, monkeypatch, tmp_path):
    """A share URL that serves its HTML download page is the likeliest mistake
    (Dropbox ?dl=0, a Drive interstitial)."""
    _serve(monkeypatch, b"<!doctype html>")
    assert main(["https://example.invalid/x.zip", "--dest", str(tmp_path)]) == 1
    err = capsys.readouterr().err
    assert "neither a .zip nor a .tar.gz" in err


def test_check_accepts_a_real_archive(capsys, monkeypatch):
    _serve(monkeypatch, _zip(("parks2021/a.md", "lockyer1959/b.md",
                              "watters1883/c.md")))
    assert check("https://example.invalid/x.zip") == 0
    assert "usable" in capsys.readouterr().out


def test_check_rejects_a_share_page_and_says_how_to_fix_it(capsys, monkeypatch):
    _serve(monkeypatch, b"<!DOCTYPE html><title>Sign in</title>")
    assert check("https://example.invalid/share") == 1
    err = capsys.readouterr().err
    assert "not the file" in err
    assert "?dl=1" in err


def test_check_rejects_an_archive_missing_a_source(capsys, monkeypatch):
    _serve(monkeypatch, _zip(("parks2021/a.md",)))
    assert check("https://example.invalid/x.zip") == 1
    assert "missing lockyer1959, watters1883" in capsys.readouterr().err
