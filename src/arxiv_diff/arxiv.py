"""The versions of a paper on arXiv and their LaTeX sources.

The list of versions (with their dates) comes from arXiv's OAI-PMH service, each version's source from
arxiv.org/e-print/<id>v<n>. arXiv asks for at most one request every three seconds: requests are paced so. Sources
are unpacked into a temporary folder that the caller deletes; only .tex, .bib, .bbl, .sty and .cls files are kept
(paper-proof's safe extraction: no absolute paths, no `..`, a size limit).
"""

from __future__ import annotations

import re
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from pathlib import Path

from paper_proof.arxiv_source import MAX_BYTES, extract

from . import __version__

USER_AGENT = f"arxiv-diff/{__version__} (+https://github.com/zch6a/arxiv-diff)"
ID = re.compile(
    r"^(?:arxiv:|https?://(?:export\.)?arxiv\.org/(?:abs|pdf|e-print)/)?(\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?/\d{7})(?:v(\d+))?(?:\.pdf)?/?$", re.I
)
INTERVAL = 3.0  # seconds between requests to arXiv


class FetchError(RuntimeError):
    """arXiv could not be reached, or did not have what was asked for."""


def parse_id(s: str) -> tuple[str, int | None]:
    """An arXiv id (and version, if given) from what a user may type or paste.

    >>> parse_id("1706.03762"), parse_id("arXiv:1706.03762v5"), parse_id("https://arxiv.org/abs/2106.09685v2")
    (('1706.03762', None), ('1706.03762', 5), ('2106.09685', 2))
    >>> parse_id("hep-th/9901001v1"), parse_id("paper/")
    (('hep-th/9901001', 1), ('', None))
    """
    m = ID.match(s.strip())
    if not m:
        return "", None
    return m.group(1), int(m.group(2)) if m.group(2) else None


@dataclass
class Version:
    number: int
    date: str  # ISO 8601, UTC
    size: str = ""  # as arXiv gives it: "1,234kb"
    source_type: str = ""  # arXiv's own code for the kind of source


@dataclass
class Record:
    arxiv_id: str
    title: str
    versions: list[Version]
    comments: str = ""  # the latest version's comments field ("Accepted at NeurIPS 2017")
    journal_ref: str = ""


Getter = Callable[[str], bytes]


class Client:
    """Requests to arXiv, paced; `get` can be replaced (the tests never reach the network)."""

    def __init__(self, get: Getter | None = None, interval: float = INTERVAL, sleep: Callable[[float], None] = time.sleep):
        self._get = get or self._urlopen
        self.interval = interval
        self.sleep = sleep
        self._last = -1e9

    @staticmethod
    def _urlopen(url: str) -> bytes:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                data: bytes = r.read(MAX_BYTES + 1)
        except urllib.error.HTTPError as e:
            raise FetchError(f"arxiv.org: HTTP {e.code} for {url}") from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise FetchError(f"arxiv.org: {getattr(e, 'reason', e)}") from e
        if len(data) > MAX_BYTES:
            raise FetchError(f"arxiv.org: {url} is larger than {MAX_BYTES // 2**20} MB")
        return data

    def get(self, url: str) -> bytes:
        wait = self._last + self.interval - time.monotonic()
        if wait > 0:
            self.sleep(wait)
        try:
            return self._get(url)
        finally:
            self._last = time.monotonic()

    def record(self, arxiv_id: str) -> Record:
        """The paper's versions, with dates, title and comments."""
        url = f"https://export.arxiv.org/oai2?verb=GetRecord&identifier=oai:arXiv.org:{arxiv_id}&metadataPrefix=arXivRaw"
        return parse_record(self.get(url), arxiv_id)

    def source(self, arxiv_id: str, version: int, into: Path) -> Path:
        """Version `version`'s LaTeX source, unpacked into `into`."""
        data = self.get(f"https://arxiv.org/e-print/{arxiv_id}v{version}")
        if data[:5] == b"%PDF-":
            raise FetchError(f"{arxiv_id}v{version} was submitted as a PDF only: there is no LaTeX source to compare")
        try:
            extract(data, into)
        except ValueError as e:
            raise FetchError(f"{arxiv_id}v{version}: {e}") from e
        return into


NS = {"oai": "http://www.openarchives.org/OAI/2.0/", "raw": "http://arxiv.org/OAI/arXivRaw/"}


def parse_record(xml: bytes, arxiv_id: str) -> Record:
    """A record from arXiv's OAI-PMH answer (metadataPrefix=arXivRaw)."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as e:
        raise FetchError(f"arXiv's answer for {arxiv_id} is not readable XML") from e
    err = root.find("oai:error", NS)
    if err is not None:
        raise FetchError(f"arXiv has no paper {arxiv_id} ({err.get('code', '')}: {(err.text or '').strip()})")
    meta = root.find(".//raw:arXivRaw", NS)
    if meta is None:
        raise FetchError(f"arXiv's answer for {arxiv_id} has no record in it")

    def text(tag: str) -> str:
        e = meta.find(f"raw:{tag}", NS)
        return re.sub(r"\s+", " ", e.text or "").strip() if e is not None else ""

    versions = []
    for v in meta.findall("raw:version", NS):
        n = int((v.get("version") or "v0").lstrip("v") or 0)
        date_el, size_el, type_el = v.find("raw:date", NS), v.find("raw:size", NS), v.find("raw:source_type", NS)
        try:
            date = parsedate_to_datetime((date_el.text or "").strip()).strftime("%Y-%m-%d") if date_el is not None else ""
        except (TypeError, ValueError):
            date = ""
        versions.append(
            Version(n, date, (size_el.text or "").strip() if size_el is not None else "", (type_el.text or "").strip() if type_el is not None else "")
        )
    versions.sort(key=lambda v: v.number)
    return Record(arxiv_id, text("title"), versions, text("comments"), text("journal-ref"))
