"""Tests for the source-archive fetch.

This runs in exactly one place that matters and is hard to debug there: inside
a container build on a deploy platform. The redirect case in particular fails
only when pointed at a private repo, which is the case it exists to serve.
"""
import io
import tarfile
import urllib.error
import urllib.request
import zipfile

import pytest

from prayer.extract.fetch import (_StripAuthOnCrossHostRedirect, extract, fetch,
                                  main)

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


@pytest.fixture
def served(monkeypatch):
    """Capture the request urllib would send, and reply with an archive."""
    seen = {}

    class _Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_open(self, req, timeout=None):
        seen["url"] = req.full_url
        seen["headers"] = {k.lower(): v for k, v in req.headers.items()}
        return _Resp(_targz())

    monkeypatch.setattr(urllib.request.OpenerDirector, "open", fake_open)
    return seen


def test_extracts_into_dest(tmp_path, served):
    names = fetch("https://example.invalid/input.tar.gz", tmp_path)
    assert sorted(names) == ["lockyer1959", "parks2021"]
    assert (tmp_path / "parks2021/a.md").read_text() == "# hello\n"


def test_token_becomes_a_bearer_header(tmp_path, served):
    fetch("https://example.invalid/input.tar.gz", tmp_path, token="ghp_x")
    assert served["headers"]["authorization"] == "Bearer ghp_x"
    # Without this a GitHub release-asset URL returns JSON metadata, not bytes.
    assert served["headers"]["accept"] == "application/octet-stream"


def test_no_token_sends_no_auth(tmp_path, served):
    fetch("https://example.invalid/input.tar.gz", tmp_path)
    assert "authorization" not in served["headers"]


def test_auth_is_stripped_when_a_redirect_crosses_hosts():
    """A GitHub asset 302s to S3, which rejects a request carrying two auth
    mechanisms. Replaying the bearer there is the bug this guards."""
    handler = _StripAuthOnCrossHostRedirect()
    req = urllib.request.Request(
        "https://api.github.com/repos/o/r/releases/assets/1",
        headers={"Authorization": "Bearer secret", "Accept": "application/octet-stream"},
    )
    new = handler.redirect_request(
        req, io.BytesIO(), 302, "Found", {}, "https://objects.githubusercontent.com/x")
    assert new is not None
    assert not any(k.lower() == "authorization" for k in new.headers)
    assert not any(k.lower() == "authorization" for k in new.unredirected_hdrs)


def test_auth_survives_a_same_host_redirect():
    handler = _StripAuthOnCrossHostRedirect()
    req = urllib.request.Request("https://api.github.com/a",
                                 headers={"Authorization": "Bearer secret"})
    new = handler.redirect_request(req, io.BytesIO(), 302, "Found", {},
                                   "https://api.github.com/b")
    assert any(k.lower() == "authorization" for k in new.headers)


def test_main_without_a_url_explains_itself(capsys, monkeypatch):
    monkeypatch.delenv("PRAYER_DATA_URL", raising=False)
    assert main([]) == 1
    err = capsys.readouterr().err
    assert "PRAYER_DATA_URL is not set" in err
    assert "copyrighted" in err


def test_main_hints_at_the_token_when_the_server_refuses(capsys, monkeypatch, tmp_path):
    def boom(self, req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)

    monkeypatch.setattr(urllib.request.OpenerDirector, "open", boom)
    assert main(["https://example.invalid/x.zip", "--dest", str(tmp_path)]) == 1
    err = capsys.readouterr().err
    assert "fetch failed" in err
    assert "PRAYER_DATA_TOKEN" in err


def test_main_does_not_blame_the_token_for_a_wrong_link(capsys, monkeypatch, tmp_path):
    """A share URL that serves its HTML download page is the likeliest mistake
    (Dropbox ?dl=0, a Drive interstitial). Pointing at auth would misdirect."""
    class _Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(urllib.request.OpenerDirector, "open",
                        lambda self, req, timeout=None: _Resp(b"<!doctype html>"))
    assert main(["https://example.invalid/x.zip", "--dest", str(tmp_path)]) == 1
    err = capsys.readouterr().err
    assert "neither a .zip nor a .tar.gz" in err
    assert "PRAYER_DATA_TOKEN" not in err
