r"""arxiv-diff watch: which of the arXiv papers you cite (or follow) have posted a new version, and what changed.

    arxiv-diff watch refs.bib                 the arXiv papers in a .bib (or a LaTeX folder, or a list of ids)
    arxiv-diff watch refs.bib --diff          and, for each new version, what changed in its results
    arxiv-diff watch 1706.03762 2106.09685    ids given directly

The first run remembers each paper's latest version in a small JSON file next to the input (`refs.arxiv-watch.json`,
or `--state`); later runs report the versions posted since, and papers that now have a journal reference. A .bib
entry that names a version (`2106.09685v2`) is compared with that version from the first run on. Versions are looked
up in batches of 100 with arXiv's API, one request every three seconds; only the ids are sent.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import tempfile
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import __version__
from .arxiv import Client, FetchError

BATCH = 100
RETRY_WAITS = (15.0, 60.0, 180.0)  # seconds before asking arXiv's API again after a 429 or 503
ATOM = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
NEW_ID = r"\d{4}\.\d{4,5}"
OLD_ID = r"[a-z-]+(?:\.[A-Z]{2})?/\d{7}"
# Where a .bib names an arXiv paper: eprint fields, arxiv.org links, arXiv:ID in any field, arXiv's DOIs.
BIB_ID = re.compile(
    rf"(?:arxiv\.org/(?:abs|pdf)/|arXiv\s*:\s*|10\.48550/arXiv\.)({NEW_ID}|{OLD_ID})(v\d+)?"
    rf"|\beprint\s*=\s*[{{\"]\s*(?:arXiv\s*:\s*)?({NEW_ID}|{OLD_ID})(v\d+)?\s*[}}\"]",
    re.I,
)
ENTRY_KEY = re.compile(r"@\w+\s*\{\s*([^,\s]+)\s*,")


@dataclass
class Cited:
    arxiv_id: str
    version: int | None = None  # the version the .bib names, if it names one
    keys: list[str] = field(default_factory=list)  # the .bib entries that cite it


@dataclass
class Latest:
    arxiv_id: str
    version: int
    title: str
    updated: str  # date of the latest version (YYYY-MM-DD)
    published: str  # date of v1
    comment: str = ""
    journal_ref: str = ""
    doi: str = ""


@dataclass
class News:
    arxiv_id: str
    title: str
    old_version: int | None
    new_version: int
    date: str
    comment: str = ""
    journal_ref: str = ""
    newly_published: bool = False
    keys: list[str] = field(default_factory=list)
    summary: list[str] = field(default_factory=list)  # with --diff: what changed (results first)
    by_date: bool = False  # found by --since: old_version is a guess until the version dates are read

    @property
    def new(self) -> bool:
        return self.old_version is not None and self.new_version > self.old_version


def ids_in_bib(text: str) -> dict[str, Cited]:
    r"""The arXiv papers a .bib names, with the version and the entries.

    >>> c = ids_in_bib("@article{hu2021lora, eprint={2106.09685v2}, archivePrefix={arXiv}}\n@misc{v, note={arXiv:1706.03762}}")
    >>> [(x.arxiv_id, x.version, x.keys) for x in c.values()]
    [('2106.09685', 2, ['hu2021lora']), ('1706.03762', None, ['v'])]
    """
    out: dict[str, Cited] = {}
    starts = [(m.start(), m.group(1)) for m in ENTRY_KEY.finditer(text)]
    for m in BIB_ID.finditer(text):
        aid = m.group(1) or m.group(3)
        v = m.group(2) or m.group(4)
        key = next((k for pos, k in reversed(starts) if pos <= m.start()), "")
        c = out.setdefault(aid, Cited(aid))
        if v and (c.version is None or int(v[1:]) < c.version):
            c.version = int(v[1:])  # the oldest version named, if several are
        if key and key not in c.keys:
            c.keys.append(key)
    return out


def read_inputs(inputs: list[str]) -> dict[str, Cited]:
    """arXiv ids from .bib files, LaTeX folders (their .bib files), text files of ids, or ids."""
    from .arxiv import parse_id

    out: dict[str, Cited] = {}

    def merge(found: dict[str, Cited]) -> None:
        for aid, c in found.items():
            have = out.setdefault(aid, Cited(aid))
            if c.version and (have.version is None or c.version < have.version):
                have.version = c.version
            have.keys += [k for k in c.keys if k not in have.keys]

    for arg in inputs:
        p = Path(arg)
        if p.is_dir():
            for bib in sorted(p.rglob("*.bib"))[:100]:
                merge(ids_in_bib(bib.read_text(encoding="utf-8", errors="replace")))
        elif p.is_file():
            text = p.read_text(encoding="utf-8", errors="replace")
            if p.suffix.lower() == ".bib" or "@" in text[:2000]:
                merge(ids_in_bib(text))
            else:
                for line in text.splitlines():
                    aid, v = parse_id(line.split("#")[0].strip())
                    if aid:
                        merge({aid: Cited(aid, v)})
        else:
            aid, v = parse_id(arg)
            if not aid:
                raise ValueError(f"{arg!r} is neither a file, a folder nor an arXiv id")
            merge({aid: Cited(aid, v)})
    return out


def parse_feed(xml: bytes) -> dict[str, Latest]:
    """The latest version of each paper in an answer of arXiv's API (export.arxiv.org/api/query)."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as err:
        raise FetchError("arXiv's API answer is not readable XML") from err
    out: dict[str, Latest] = {}
    for e in root.findall("a:entry", ATOM):

        def text(tag: str, entry: ET.Element = e) -> str:
            el = entry.find(tag, ATOM)
            return re.sub(r"\s+", " ", el.text or "").strip() if el is not None else ""

        m = re.search(rf"arxiv\.org/abs/({NEW_ID}|{OLD_ID})v(\d+)", text("a:id"))
        if not m:
            continue  # an error entry ("incorrect id format"), or a paper that does not exist
        doi = text("arxiv:doi")
        out[m.group(1)] = Latest(
            m.group(1), int(m.group(2)), text("a:title"), text("a:updated")[:10], text("a:published")[:10],
            text("arxiv:comment"), text("arxiv:journal_ref"), doi,
        )  # fmt: skip
    return out


def latest_versions(client: Client, ids: list[str]) -> dict[str, Latest]:
    out: dict[str, Latest] = {}
    for i in range(0, len(ids), BATCH):
        batch = ids[i : i + BATCH]
        query = urllib.parse.urlencode({"id_list": ",".join(batch), "max_results": len(batch)})
        url = f"https://export.arxiv.org/api/query?{query}"
        for wait in (*RETRY_WAITS, None):
            try:
                out |= parse_feed(client.get(url))
                break
            except FetchError as e:
                # arXiv answers 429 or 503 when it is busy: wait and ask again, a few times
                if wait is None or not re.search(r"HTTP (?:429|503)\b", str(e)):
                    raise
                client.sleep(wait)
    return out


def load_state(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        raise ValueError(f"{path}: not a watch state file ({e.__class__.__name__}); move it away or pass --state") from e
    if not isinstance(data, dict) or not isinstance(data.get("papers"), dict):
        raise ValueError(f'{path}: not a watch state file (no "papers"); move it away or pass --state')
    return data


def news(cited: dict[str, Cited], latest: dict[str, Latest], state: dict[str, Any], since: str = "") -> list[News]:
    """What is new since the state (or since the version a .bib names, or since a date)."""
    seen = state.get("papers", {})
    out = []
    for aid, c in cited.items():
        lat = latest.get(aid)
        if lat is None:
            continue
        before = seen.get(aid, {})
        old = before.get("version") or c.version
        by_date = False
        if since and lat.updated > since and lat.version > 1 and (old is None or old >= lat.version):
            old, by_date = lat.version - 1, True  # --since: refined with the versions' dates (since_version)
        newly_published = bool(lat.journal_ref) and bool(before) and not before.get("journal_ref")
        n = News(aid, lat.title, old, lat.version, lat.updated, lat.comment, lat.journal_ref, newly_published, c.keys, by_date=by_date)
        if n.new or n.newly_published:
            out.append(n)
    return sorted(out, key=lambda n: n.date, reverse=True)


def since_version(client: Client, n: News, since: str) -> None:
    """The version that was the latest on the --since date (from arXiv's list of versions and their dates)."""
    try:
        versions = client.record(n.arxiv_id).versions
    except FetchError:
        return  # keep the version before the latest
    before = [v.number for v in versions if v.date and v.date <= since]
    n.old_version = max(before) if before else 1


def new_state(cited: dict[str, Cited], latest: dict[str, Latest], state: dict[str, Any]) -> dict[str, Any]:
    papers = dict(state.get("papers", {}))
    for aid in cited:
        if aid in latest:
            lat = latest[aid]
            papers[aid] = {"version": lat.version, "date": lat.updated, "title": lat.title, "journal_ref": lat.journal_ref}
    return {"tool": "arxiv-diff watch", "checked": dt.date.today().isoformat(), "papers": dict(sorted(papers.items()))}


def summarize(client: Client, n: News) -> list[str]:
    """What changed between the old and the new version, as arxiv-diff's headline (results first)."""
    from .diff import compare
    from .paper import NoSource, load
    from .report import headline

    assert n.old_version is not None
    try:
        with tempfile.TemporaryDirectory(prefix="arxiv-watch-") as tmp:
            a = load(client.source(n.arxiv_id, n.old_version, Path(tmp) / "a"), f"v{n.old_version}")
            b = load(client.source(n.arxiv_id, n.new_version, Path(tmp) / "b"), f"v{n.new_version}")
            return headline(compare(a, b))
    except (FetchError, NoSource) as e:
        return [f"not compared: {e}"]


def _versions(n: News) -> str:
    return f"v{n.old_version} → v{n.new_version}" if n.new else f"v{n.new_version}"


def text(items: list[News], watched: int, missing: list[str], first: bool) -> str:
    out = []
    if first and not items:
        out.append(f"Now watching {watched} arXiv paper{'s' if watched != 1 else ''}; the next run reports the versions posted after today.")
    elif not items:
        out.append(f"No new versions among {watched} arXiv paper{'s' if watched != 1 else ''}.")
    else:
        out.append(f"{len([n for n in items if n.new])} new version(s) among {watched} arXiv papers:")
    for n in items:
        out += ["", f"{n.arxiv_id}  {_versions(n)}  ({n.date})  {n.title[:100]}"]
        if n.keys:
            out.append(f"    cited as: {', '.join(n.keys[:5])}")
        if n.comment:
            out.append(f"    comments: {n.comment[:160]}")
        if n.journal_ref:
            out.append(f"    {'now published' if n.newly_published else 'journal ref'}: {n.journal_ref[:160]}")
        out += [f"    {line}" for line in n.summary]
        out.append(f"    https://arxiv.org/abs/{n.arxiv_id}v{n.new_version}")
    if missing:
        out += ["", f"Not found on arXiv: {', '.join(missing[:10])}" + (f" and {len(missing) - 10} more" if len(missing) > 10 else "")]
    return "\n".join(out) + "\n"


def markdown(items: list[News], watched: int) -> str:
    if not items:
        return f"No new versions among {watched} arXiv papers.\n"
    out = [f"### New versions of papers you cite ({len(items)})", "", "| Paper | Versions | Date | Cited as | Notes |", "|---|---|---|---|---|"]
    for n in items:
        title = n.title.replace("|", "\\|")[:90]
        published = ("now published: " if n.newly_published else "") + n.journal_ref if n.journal_ref else ""
        notes = "; ".join(x for x in [n.comment, published, *n.summary] if x)
        keys = ", ".join(f"`{k}`" for k in n.keys[:3])
        notes = notes.replace("|", "\\|")[:300]
        out.append(f"| [{title}](https://arxiv.org/abs/{n.arxiv_id}v{n.new_version}) | {_versions(n)} | {n.date} | {keys} | {notes} |")
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None, client: Client | None = None) -> int:
    ap = argparse.ArgumentParser(prog="arxiv-diff watch", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+", metavar="INPUT", help="a .bib, a LaTeX folder, a text file of arXiv ids, or ids")
    ap.add_argument("--state", type=Path, help="where to remember the versions seen (default: next to the first input)")
    ap.add_argument("--since", metavar="YYYY-MM-DD", help="also report papers whose latest version came after this date")
    ap.add_argument("--diff", action="store_true", help="for each new version, what changed in it (fetches both sources)")
    ap.add_argument("--format", choices=["text", "markdown", "json"], default="text", help="text (default), markdown (an issue), json")
    ap.add_argument("--dry-run", action="store_true", help="report, but do not update the state file")
    ap.add_argument("--fail-on-new", action="store_true", help="exit with 1 when there is a new version (to open an issue in CI)")
    args = ap.parse_args(argv)
    if args.since and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", args.since):
        ap.error("--since takes a date: YYYY-MM-DD")
    try:
        cited = read_inputs(args.inputs)
    except (OSError, ValueError) as e:
        ap.error(str(e))
    if not cited:
        print("arxiv-diff watch: no arXiv papers found in the input", file=sys.stderr)
        return 2
    first_input = Path(args.inputs[0])
    state_path = args.state or (
        first_input.with_suffix(".arxiv-watch.json")
        if first_input.is_file()
        else (first_input / "arxiv-watch.json" if first_input.is_dir() else Path("arxiv-watch.json"))
    )
    try:
        state = load_state(state_path)
    except ValueError as e:
        print(f"arxiv-diff watch: {e}", file=sys.stderr)
        return 2
    client = client or Client()
    try:
        latest = latest_versions(client, sorted(cited))
    except FetchError as e:
        print(f"arxiv-diff watch: {e}", file=sys.stderr)
        return 2
    items = news(cited, latest, state, args.since or "")
    for n in items:
        if n.by_date:
            since_version(client, n, args.since)
    if args.diff:
        for n in items:
            if n.new:
                n.summary = summarize(client, n)
    missing = sorted(set(cited) - set(latest))
    if args.format == "json":
        payload = {
            "tool": "arxiv-diff watch",
            "tool_version": __version__,
            "watched": len(cited),
            "new": [asdict(n) for n in items],
            "not_found": missing,
            "state": str(state_path),
        }
        sys.stdout.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    elif args.format == "markdown":
        sys.stdout.write(markdown(items, len(cited)))
    else:
        sys.stdout.write(text(items, len(cited), missing, first=not state))
    if not args.dry_run:
        state_path.write_text(json.dumps(new_state(cited, latest, state), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 1 if args.fail_on_new and any(n.new for n in items) else 0
