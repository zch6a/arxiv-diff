from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path

import pytest
from helpers import write

from arxiv_diff.arxiv import Client, FetchError, parse_record
from arxiv_diff.cli import main

OAI = """<?xml version="1.0" encoding="UTF-8"?>
<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/"><GetRecord><record><metadata>
<arXivRaw xmlns="http://arxiv.org/OAI/arXivRaw/">
<id>2501.00001</id><title>Attention Is All
  You Need</title><comments>15 pages, 5 figures</comments><journal-ref>NeurIPS 2017</journal-ref>
<version version="v1"><date>Mon, 12 Jun 2017 17:57:34 GMT</date><size>1,234kb</size><source_type>D</source_type></version>
<version version="v2"><date>Mon, 19 Jun 2017 16:49:45 GMT</date><size>1,240kb</size><source_type>D</source_type></version>
<version version="v3"><date>Wed, 6 Dec 2017 03:30:32 GMT</date><size>1,300kb</size><source_type>D</source_type></version>
</arXivRaw></metadata></record></GetRecord></OAI-PMH>"""


def _tar(folder: Path) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for p in sorted(folder.rglob("*")):
            if p.is_file():
                tf.add(p, arcname=p.relative_to(folder).as_posix())
    return buf.getvalue()


class FakeArxiv:
    """arXiv as the tests need it: a record with three versions and their sources, and every request logged."""

    def __init__(self, tmp: Path) -> None:
        self.urls: list[str] = []
        self.waits: list[float] = []
        self.sources = {
            1: _tar(write(tmp / "s1")),
            2: _tar(write(tmp / "s2", BIG="28.9")),
            3: _tar(write(tmp / "s3", BIG="28.9", METHOD="Model Architecture", AUTHOR2="Charles Babbage \\And Grace Hopper")),
        }

    def get(self, url: str) -> bytes:
        self.urls.append(url)
        if "oai2" in url:
            return OAI.encode()
        n = int(url.rsplit("v", 1)[1])
        return self.sources[n]

    def client(self) -> Client:
        return Client(self.get, interval=3.0, sleep=self.waits.append)


def test_record_has_versions_and_dates() -> None:
    r = parse_record(OAI.encode(), "2501.00001")
    assert r.title == "Attention Is All You Need" and r.journal_ref == "NeurIPS 2017"
    assert [(v.number, v.date) for v in r.versions] == [(1, "2017-06-12"), (2, "2017-06-19"), (3, "2017-12-06")]


def test_record_errors() -> None:
    err = b'<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/"><error code="idDoesNotExist">No matching identifier</error></OAI-PMH>'
    with pytest.raises(FetchError, match="no paper"):
        parse_record(err, "9999.99999")
    with pytest.raises(FetchError, match="not readable"):
        parse_record(b"<html>", "9999.99999")


def test_first_and_latest_version(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    fake = FakeArxiv(tmp_path)
    assert main(["2501.00001", "--color", "never"], client=fake.client()) == 0
    out = capsys.readouterr().out
    assert 'arxiv-diff: v1 → v3  2501.00001 "Attention Is All You Need" (2017-06-12 → 2017-12-06)' in out
    assert "Transformer (big) · EN-DE: 28.4 → 28.9  (+0.5, better)" in out
    assert "added: Grace Hopper" in out and "2 Model Architecture (was 2 Model)" in out
    assert [u.rsplit("/", 1)[1] for u in fake.urls if "e-print" in u] == ["2501.00001v1", "2501.00001v3"]
    # paced: every request after the first waited for arXiv's three seconds
    assert len(fake.waits) == len(fake.urls) - 1 and all(2.5 < w <= 3.0 for w in fake.waits)


def test_every_version(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    fake = FakeArxiv(tmp_path)
    assert main(["2501.00001", "--all", "--format", "json"], client=fake.client()) == 0
    steps = json.loads(capsys.readouterr().out)
    assert [(s["old_version"], s["new_version"]) for s in steps] == [(1, 2), (2, 3)]
    assert steps[0]["summary"]["table_values_changed"] == 1 and steps[1]["summary"]["table_values_changed"] == 0
    assert steps[0]["tables"][0]["cells"][0]["delta"] == 0.5
    assert sum("e-print" in u for u in fake.urls) == 3  # each version fetched once


def test_one_version_compares_with_the_one_before(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    fake = FakeArxiv(tmp_path)
    assert main(["arXiv:2501.00001v2", "--format", "markdown", "--fail-on", "results"], client=fake.client()) == 1
    out = capsys.readouterr().out
    assert out.startswith("### arxiv-diff: `v1` → `v2`")
    assert "| tab:main | Transformer (big) | EN-DE | 28.4 | 28.9 | +0.5 better |" in out
    assert sum("oai2" in u for u in fake.urls) == 1 and "(2017-06-12 → 2017-06-19)" in out


def test_two_folders(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    a, b = write(tmp_path / "old"), write(tmp_path / "new", ABSTRACT="We propose a new architecture. It reaches 28.4 BLEU.")
    assert main([str(a), str(b), "--fail-on", "any", "--color", "never"]) == 1
    out = capsys.readouterr().out
    assert "Abstract" in out and "{+" not in out.split("Abstract")[0]
    assert main([str(a), str(write(tmp_path / "same")), "--fail-on", "any"]) == 0
    assert "no changes" in capsys.readouterr().out


def test_pdf_only_version_is_an_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    fake = FakeArxiv(tmp_path)
    fake.sources[3] = b"%PDF-1.5 ..."
    assert main(["2501.00001"], client=fake.client()) == 2
    assert "submitted as a PDF only" in capsys.readouterr().err


def test_not_a_source(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="neither a folder"):
        main(["no-such-thing"])
    (tmp_path / "empty").mkdir()
    assert main([str(tmp_path / "empty"), str(tmp_path / "empty")]) == 2
