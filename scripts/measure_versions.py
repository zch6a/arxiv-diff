"""Measure arxiv-diff on real papers with several arXiv versions: compare v1 with the latest version and audit the
tables independently of the report.

    uv run python scripts/measure_versions.py IDS_FILE OUT_DIR [--max N]

For each paper with two or more versions, the two sources are fetched into OUT_DIR (a folder outside this
repository; delete it afterwards: never commit papers' sources). The audit: in every pair of tables, each number
that left the old version's cells (or arrived in the new one's) must be explained by what the report says (a
changed or emptied cell, a removed or added row or column). What is left unexplained is printed, to be checked by
hand: a pairing the diff got wrong, or a change it missed. Every reported value change is printed too, for checking
that it is real.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

from paper_proof.tables import Table

from arxiv_diff.arxiv import Client, FetchError
from arxiv_diff.diff import TableDiff, cell_numbers, compare, match_tables, rows
from arxiv_diff.paper import NoSource, load


def numbers(t: Table, skip_rows: set[str] = frozenset(), skip_cols: set[int] = frozenset()) -> Counter[str]:  # type: ignore[assignment]
    keys = dict(rows(t))
    out: Counter[str] = Counter()
    for i in range(t.header_rows, len(t.rows)):
        if keys.get(i) in skip_rows:
            continue
        for j, c in enumerate(t.rows[i]):
            if c.value is not None and j not in skip_cols:  # a cell as the numbers it shows (not its formatting)
                out[" ".join(f"{n:g}" for n in cell_numbers(c.text))] += 1
    return out


def audit(ta: Table, tb: Table, td: TableDiff) -> tuple[Counter[str], Counter[str]]:
    """Numbers that left the old table and arrived in the new one, without a reported change to explain them."""
    from arxiv_diff.diff import columns

    gone_cols = {j for j, k in enumerate(columns(ta)) if k in td.columns_removed}  # renamed columns are compared, not here
    new_cols = {j for j, k in enumerate(columns(tb)) if k in td.columns_added}
    old = numbers(ta, set(td.rows_removed), gone_cols)
    new = numbers(tb, set(td.rows_added), new_cols)
    left, arrived = old - new, new - old
    left -= Counter(" ".join(f"{n:g}" for n in cell_numbers(c.old)) for c in td.cells if c.old)
    arrived -= Counter(" ".join(f"{n:g}" for n in cell_numbers(c.new)) for c in td.cells if c.new)
    return left, arrived


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--max", type=int, default=20, help="papers with several versions to measure")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    client = Client()
    ids = [x.strip() for x in args.ids.read_text(encoding="utf-8-sig").split() if x.strip()]
    done = 0
    totals: Counter[str] = Counter()
    for aid in ids:
        if done >= args.max:
            break
        try:
            rec = client.record(aid)
        except FetchError as e:
            print(f"{aid}: {e}")
            continue
        if len(rec.versions) < 2:
            continue
        first, last = rec.versions[0].number, rec.versions[-1].number
        papers = []
        try:
            for n in (first, last):
                into = args.out / f"{aid.replace('/', '_')}v{n}"
                if not into.exists():
                    client.source(aid, n, into)
                papers.append(load(into, f"v{n}"))
        except (FetchError, NoSource) as e:
            print(f"{aid}: {e}")
            continue
        done += 1
        a, b = papers
        d = compare(a, b)
        s = d.summary
        print(f"\n=== {aid} v{first} ({rec.versions[0].date}) -> v{last} ({rec.versions[-1].date})  {rec.title[:70]}")
        sentences = f"+{s.sentences_added} -{s.sentences_removed} ~{s.sentences_changed}"
        print(f"  words {s.words_old} -> {s.words_new}, changed {s.changed_share:.0%}; sentences {sentences}")
        tables = f"values changed {s.table_values_changed}, added {s.tables_added}, removed {s.tables_removed}"
        print(f"  tables {len(a.tables)} -> {len(b.tables)}: {tables}; text numbers {s.text_numbers_changed}")
        if d.authors.changed:
            print(f"  AUTHORS added {d.authors.added} removed {d.authors.removed} reordered {d.authors.reordered}")
        totals["papers"] += 1
        totals["values"] += s.table_values_changed
        totals["text_numbers"] += s.text_numbers_changed
        # the audit, on the tables the diff paired
        ta_all = [t for t in a.tables if len(t.rows) > t.header_rows]
        tb_all = [t for t in b.tables if len(t.rows) > t.header_rows]
        by_new = {(t.new.file, t.new.line): t for t in d.tables if t.new is not None and t.old is not None}
        for i, j in match_tables(ta_all, tb_all):
            ta, tb = ta_all[i], tb_all[j]
            td = by_new.get((tb.file, tb.line))
            if td is None:
                continue
            left, arrived = audit(ta, tb, td)
            totals["audited_tables"] += 1
            totals["unexplained_left"] += sum(left.values())
            totals["unexplained_arrived"] += sum(arrived.values())
            if left or arrived:
                print(f"  AUDIT {td.name} ({tb.file}:{tb.line}): left {dict(left.most_common(8))} arrived {dict(arrived.most_common(8))}")
        for t in d.tables:
            if t.status in ("added", "removed"):
                print(f"  table {t.status}: {t.name} ({len(t.rows_added or t.rows_removed)} rows)")
            for c in t.cells:
                if c.kind == "value":
                    print(f"  VALUE {t.name} | {c.row} | {c.column}: {c.old} -> {c.new} (line {c.line})")
        for sd in [None, *d.sections]:
            changes = d.abstract if sd is None else sd.changes
            for c in changes:
                where = f"{c.new.file}:{c.new.line}" if c.new else ""
                for n in c.numbers:
                    print(f"  TEXT {'Abstract' if sd is None else sd.name[:30]} ({where}): ...{n.before} [{n.old} -> {n.new}] {n.after}...")
    print(f"\nTOTAL {dict(totals)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
