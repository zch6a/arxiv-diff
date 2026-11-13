"""arxiv-diff: what changed between two versions of a paper.

arxiv-diff 1706.03762                 first and latest version on arXiv
arxiv-diff 1706.03762v3               v2 → v3
arxiv-diff 1706.03762v1 1706.03762v5  any two versions
arxiv-diff 1706.03762 --all           every step, v1 → v2 → ... → latest
arxiv-diff old/ new/                  two LaTeX folders (or .tex files)
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from paper_proof.report import use_color

from . import __version__, html, report
from .arxiv import Client, FetchError, Record, parse_id
from .diff import Diff, compare
from .paper import NoSource, Paper, load


@dataclass
class Side:
    """One of the two things compared: a folder, or a version of an arXiv paper."""

    folder: Path | None = None
    arxiv_id: str = ""
    version: int | None = None

    def label(self) -> str:
        if self.folder is not None:
            shown = self.folder.as_posix()
            return shown if len(shown) <= 40 else "/".join(self.folder.parts[-2:])
        return f"v{self.version}"


class UsageError(ValueError):
    """What was asked cannot be done as asked (exit status 2, like argparse's own errors)."""


def _side(arg: str) -> Side:
    p = Path(arg)
    if p.exists():
        return Side(folder=p)
    aid, v = parse_id(arg)
    if not aid:
        raise UsageError(f"{arg!r} is neither a folder, a .tex file nor an arXiv id")
    if v == 0:
        raise UsageError(f"{arg!r}: arXiv's versions start at v1")
    return Side(arxiv_id=aid, version=v)


def _pairs(sides: list[Side], every: bool, client: Client, records: dict[str, Record]) -> list[tuple[Side, Side]]:
    """The pairs of versions to compare."""

    def record(aid: str) -> Record:
        if aid not in records:
            records[aid] = client.record(aid)
        return records[aid]

    def latest(aid: str) -> int:
        versions = record(aid).versions
        if not versions:
            raise FetchError(f"arXiv lists no versions of {aid}")
        return versions[-1].number

    if every and (len(sides) != 1 or not sides[0].arxiv_id):
        raise UsageError("--all compares every version of one arXiv paper: give its id alone")
    if len(sides) == 1 and sides[0].folder is not None:
        raise UsageError("give two folders to compare (or an arXiv id)")
    for s in sides:  # the record names the versions and their dates, for the report
        if s.arxiv_id:
            n = latest(s.arxiv_id)
            if s.version is not None and s.version > n:
                raise FetchError(f"arXiv has v1 to v{n} of {s.arxiv_id}: there is no v{s.version}")
    if len(sides) == 1:
        s = sides[0]
        if s.version is not None and not every:
            if s.version < 2:
                raise UsageError(f"{s.arxiv_id}v1 is the first version; give two versions to compare")
            return [(Side(arxiv_id=s.arxiv_id, version=s.version - 1), s)]
        n = latest(s.arxiv_id)
        if n < 2:
            return []
        numbers = list(range(1, n + 1)) if every else [1, n]
        return [(Side(arxiv_id=s.arxiv_id, version=a), Side(arxiv_id=s.arxiv_id, version=b)) for a, b in zip(numbers, numbers[1:], strict=False)]
    a, b = sides
    for s in (a, b):
        if s.arxiv_id and s.version is None:
            s.version = latest(s.arxiv_id)
    return [(a, b)]


def _about(a: Side, b: Side, records: dict[str, Record]) -> tuple[str, dict[str, Any]]:
    """A line naming what was compared, and the same for the JSON report."""
    if not a.arxiv_id or a.arxiv_id != b.arxiv_id:
        ids = [s.arxiv_id + (f"v{s.version}" if s.version else "") if s.arxiv_id else (s.folder.as_posix() if s.folder else "") for s in (a, b)]
        return "", {"old_source": ids[0], "new_source": ids[1]}
    rec = records.get(a.arxiv_id)
    dates = {v.number: v.date for v in rec.versions} if rec else {}
    line = f"{a.arxiv_id}"
    if rec and rec.title:
        line += f' "{rec.title}"'
    if dates.get(a.version or 0) and dates.get(b.version or 0):
        line += f" ({dates[a.version or 0]} → {dates[b.version or 0]})"
    info: dict[str, Any] = {"arxiv_id": a.arxiv_id, "old_version": a.version, "new_version": b.version}
    if rec:
        info |= {
            "arxiv_title": rec.title,  # "title" is the diff's own (old and new title, when it changed)
            "old_date": dates.get(a.version or 0, ""),
            "new_date": dates.get(b.version or 0, ""),
            "comments": rec.comments,
            "journal_ref": rec.journal_ref,
        }
    return line, info


def _load(side: Side, client: Client, tmp: Path, cache: dict[tuple[str, int], Paper]) -> Paper:
    if side.folder is not None:
        return load(side.folder, side.label())
    assert side.version is not None
    key = (side.arxiv_id, side.version)
    if key not in cache:
        into = tmp / f"{side.arxiv_id.replace('/', '_')}v{side.version}"
        client.source(side.arxiv_id, side.version, into)
        cache[key] = load(into, side.label())
    return cache[key]


def to_json(d: Diff, info: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {"tool": "arxiv-diff", "tool_version": __version__, **info, **asdict(d), "changed": d.changed}
    for t_json, t in zip(out["tables"], d.tables, strict=True):
        for c_json, c in zip(t_json["cells"], t.cells, strict=True):
            c_json["delta"] = c.delta
    return out


def _fails(d: Diff, fail_on: str) -> bool:
    if fail_on == "any":
        return d.changed
    if fail_on == "results":
        return bool(d.summary.table_values_changed or d.summary.text_numbers_changed)
    return False


def _write(output: Path | None, text: str) -> None:
    if output is None:
        sys.stdout.write(text)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")


def main(argv: list[str] | None = None, client: Client | None = None) -> int:
    """The command line. Exit status: 0 compared, 1 when --fail-on says so, 2 when it could not compare (and on any
    unexpected error, which must not read as "results changed")."""
    try:
        return _main(argv, client)
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as e:  # noqa: BLE001 - the last line of defence for the exit status
        print(f"arxiv-diff: {e.__class__.__name__}: {e}", file=sys.stderr)
        return 2


def _main(argv: list[str] | None, client: Client | None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(prog="arxiv-diff", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sources", nargs="+", metavar="SOURCE", help="an arXiv id (with or without a version), a folder or a .tex file; one or two")
    ap.add_argument("--all", action="store_true", help="compare every version with the next (an arXiv id without a version)")
    ap.add_argument("--format", choices=["text", "markdown", "json", "html"], default="text")
    ap.add_argument("-o", "--output", type=Path, help="write the report to this file instead of the terminal")
    ap.add_argument("--full", action="store_true", help="show every changed sentence (the terminal report shows a few per section)")
    ap.add_argument("--fail-on", choices=["never", "results", "any"], default="never", help="exit with 1 when results (numbers) or anything changed")
    ap.add_argument("--color", choices=["auto", "always", "never"], default="auto")
    ap.add_argument("--keep", type=Path, metavar="DIR", help="keep the arXiv sources fetched in DIR (otherwise they are deleted)")
    ap.add_argument("--version", action="version", version=f"arxiv-diff {__version__}")
    args = ap.parse_args(argv)
    if len(args.sources) > 2:
        ap.error("give one arXiv id, or two versions to compare")

    client = client or Client()
    records: dict[str, Record] = {}
    diffs: list[tuple[Diff, str, dict[str, Any]]] = []
    try:
        try:
            sides = [_side(s) for s in args.sources]
            pairs = _pairs(sides, args.all, client, records)
        except UsageError as e:
            ap.error(str(e))
        if not pairs:
            print(f"arxiv-diff: {sides[0].arxiv_id} has only one version on arXiv: nothing to compare", file=sys.stderr)
            if args.format == "json":  # a JSON reader still gets JSON: no comparisons
                _write(args.output, "[]\n")
            return 0
        failed: list[str] = []
        with tempfile.TemporaryDirectory(prefix="arxiv-diff-") as tmp:
            cache: dict[tuple[str, int], Paper] = {}
            for a, b in pairs:
                line, info = _about(a, b, records)
                where = args.keep or Path(tmp)
                try:
                    diffs.append((compare(_load(a, client, where, cache), _load(b, client, where, cache)), line, info))
                except (FetchError, NoSource) as e:
                    if len(pairs) == 1:
                        raise
                    failed.append(f"{a.label()} → {b.label()}: {e}")  # --all: the other steps are still reported
    except (FetchError, NoSource) as e:
        print(f"arxiv-diff: {e}", file=sys.stderr)
        return 2
    for message in failed:
        print(f"arxiv-diff: not compared: {message}", file=sys.stderr)
    if not diffs:
        return 2

    if args.format == "json":
        payload: Any = [to_json(d, info) for d, _, info in diffs]
        out = json.dumps(payload if args.all else payload[0], indent=2, ensure_ascii=False) + "\n"  # --all: always a list
    elif args.format == "html":
        out = html.page([(d, line) for d, line, _ in diffs])
    elif args.format == "markdown":
        out = "\n".join(report.markdown(d, line, limit=10_000 if args.full else 30) for d, line, _ in diffs)
    else:
        color = args.output is None and use_color(sys.stdout, args.color)
        out = "\n".join(report.text(d, color, 0 if args.full else 6, line) for d, line, _ in diffs)
    _write(args.output, out)
    if any(_fails(d, args.fail_on) for d, _, _ in diffs):
        return 1
    return 2 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
