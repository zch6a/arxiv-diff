"""The reports: for the terminal, and as Markdown (a pull request comment, a job summary). JSON is built in cli.py,
the side-by-side page in html.py."""

from __future__ import annotations

import re

from paper_proof.report import _code, _md, visible

from .diff import CellChange, Change, Diff, SectionDiff, word_diff
from .latex import Sentence

CONCLUSION = re.compile(r"conclu|summary|discussion|limitation|future work|outlook", re.I)
RED, GREEN, YELLOW, DIM, BOLD, RESET = "\x1b[31m", "\x1b[32m", "\x1b[33m", "\x1b[2m", "\x1b[1m", "\x1b[0m"


def is_conclusion(sd: SectionDiff) -> bool:
    return sd.level <= 1 and not sd.appendix and bool(CONCLUSION.search(sd.name))


def _decimals(s: str) -> int:
    m = re.search(r"\.(\d+)", s)
    return len(m.group(1)) if m else 0


def delta(c: CellChange) -> str:
    """The change of a table value, with as many decimals as the table shows.

    >>> from arxiv_diff.diff import CellChange
    >>> delta(CellChange("r", "c", "28.4", "28.95", 28.4, 28.95, "value"))
    '+0.55'
    """
    if c.delta is None:
        return ""
    return f"{c.delta:+.{max(_decimals(c.old), _decimals(c.new))}f}"


def verdict(c: CellChange) -> str:
    return "" if c.better is None else "better" if c.better else "worse"


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _grouped(cells: list[CellChange]) -> tuple[dict[tuple[str, str], list[str]], dict[tuple[str, str], list[str]]]:
    """Cells emptied, and cells filled in, by column and value: (column, value) -> rows."""
    emptied: dict[tuple[str, str], list[str]] = {}
    filled: dict[tuple[str, str], list[str]] = {}
    for c in cells:
        if c.kind == "text" and c.old and not c.new:
            emptied.setdefault((c.column, c.old), []).append(c.row)
        elif c.kind == "text" and c.new and not c.old:
            filled.setdefault((c.column, c.new), []).append(c.row)
    return emptied, filled


def _some(items: list[str], n: int = 12) -> str:
    """The first n items, and how many there are when that is not all."""
    return "; ".join(visible(k) for k in items[:n]) + (f"; ... ({len(items)} in all)" if len(items) > n else "")


def _rows(rows: list[str], n: int = 6) -> str:
    return "; ".join(visible(r) for r in rows[:n]) + (f"; ... ({len(rows)})" if len(rows) > n else "")


def headline(d: Diff) -> list[str]:
    """The summary in a few phrases."""
    s = d.summary
    out = [f"prose {s.words_old:,} → {s.words_new:,} words, {s.changed_share:.0%} of the old text rewritten or removed"]
    sent = [f"+{s.sentences_added}", f"-{s.sentences_removed}", f"~{s.sentences_changed} changed"]
    if s.sentences_moved:
        sent.append(f"{s.sentences_moved} moved")
    out.append("sentences " + " ".join(sent))
    parts = []
    if s.table_values_changed:
        parts.append(f"{_plural(s.table_values_changed, 'result')} changed in tables")
    if s.text_numbers_changed:
        parts.append(f"{_plural(s.text_numbers_changed, 'number')} changed in the text")
    for n, what in (
        (s.table_rows_added, "table row added"),
        (s.table_rows_removed, "table row removed"),
        (s.sections_added, "section added"),
        (s.sections_removed, "section removed"),
        (s.sections_renamed, "section renamed"),
        (s.tables_added, "table added"),
        (s.tables_removed, "table removed"),
        (s.figures_added, "figure added"),
        (s.figures_removed, "figure removed"),
        (s.figures_changed, "figure changed"),
        (s.references_added, "reference added"),
        (s.references_removed, "reference removed"),
        (s.references_updated, "reference updated"),
        (s.authors_added, "author added"),
        (s.authors_removed, "author removed"),
    ):
        if n:
            *noun, verb = what.split(" ")  # "table row added" -> "2 table rows added"
            parts.append(f"{n} {' '.join([*noun[:-1], noun[-1] + ('' if n == 1 else 's')])} {verb}")
    moved = sum(sd.moved for sd in d.sections)
    if moved:
        parts.append(f"{_plural(moved, 'section')} moved")
    if d.authors.reordered:
        parts.append("author order changed")
    if d.title:
        parts.append("title changed")
    if parts:
        out.append(", ".join(parts))
    return out


# ---------------------------------------------------------------- terminal


def _words(c: Change, color: bool) -> str:
    out = []
    prev = "="
    for op, t in c.words:
        t = visible(t)
        if op == "=":
            out.append(t)
        else:
            lead, core = t[: len(t) - len(t.lstrip())], t.lstrip()
            if op == "+" and prev == "-":
                lead = " " if lead else ""  # one space between what was removed and what replaced it
            if color:
                out.append(lead + (f"{RED}\x1b[9m{core}{RESET}" if op == "-" else f"{GREEN}{core}{RESET}"))
            else:
                out.append(lead + (f"[-{core}-]" if op == "-" else f"{{+{core}+}}"))
        prev = op
    return "".join(out)


def _at(s: Sentence) -> str:
    """file:line, with any control characters in the file name made visible."""
    return visible(f"{s.file}:{s.line}")


def _change_line(c: Change, color: bool) -> str:
    paint = (lambda code, s: f"{code}{s}{RESET}") if color else (lambda code, s: s)
    if c.kind == "changed" and c.new is not None:
        mark = "#" if c.numbers_only else "~"
        return f"{paint(YELLOW, mark)} {paint(DIM, _at(c.new))}  {_words(c, color)}"
    if c.kind == "added" and c.new is not None:
        return f"{paint(GREEN, '+')} {paint(DIM, _at(c.new))}  {paint(GREEN, visible(c.new.text))}"
    if c.kind == "removed" and c.old is not None:
        return f"{paint(RED, '-')} {paint(DIM, _at(c.old))}  {paint(RED, visible(c.old.text))}"
    s = c.new or c.old
    assert s is not None
    where = "from" if c.new is not None else "to"
    moved = f"(moved {where} {visible(c.other)})"
    return f"{paint(DIM, '>')} {paint(DIM, _at(s))}  {paint(DIM, visible(s.text[:80]))} {paint(DIM, moved)}"


def text(d: Diff, color: bool = False, limit: int = 6, about: str = "") -> str:
    """The report for a terminal: what changed in the results first, then the abstract, the conclusion, the sections
    (at most `limit` changes each; 0 for all), figures and references."""
    paint = (lambda code, s: f"{code}{s}{RESET}") if color else (lambda code, s: s)
    out = [paint(BOLD, f"arxiv-diff: {visible(d.old)} → {visible(d.new)}") + (f"  {visible(about)}" if about else "")]
    out += [f"  {line}" for line in headline(d)]
    if not d.changed:
        out.append("  no changes")
        return "\n".join(out) + "\n"

    changed_tables = [t for t in d.tables if t.status != "same"]
    if changed_tables:
        out += ["", paint(BOLD, "Tables")]
        for t in changed_tables:
            w = t.new or t.old
            where = visible(f"{w.file}:{w.line}") if w else ""
            out.append(f"  {t.status:8} {visible(t.name)}  {paint(DIM, where)}")
            emptied, filled = _grouped(t.cells)
            for c in t.cells:
                label = f"{visible(c.row)} · {visible(c.column)}"
                if c.kind == "text" and (not c.old or not c.new):
                    continue  # grouped below
                if c.kind == "value":
                    v = verdict(c)
                    tone = GREEN if v == "better" else RED if v == "worse" else YELLOW
                    out.append(f"      {label}: {visible(c.old)} → {paint(tone, visible(c.new))}  ({delta(c)}{', ' + v if v else ''})")
                elif c.kind == "bold":
                    out.append(f"      {label}: {visible(c.new)} {'now in bold' if c.new_bold else 'no longer in bold'}")
                else:
                    out.append(f'      {label}: "{visible(c.old)}" → "{visible(c.new)}"')
            for (column, value), rows_ in emptied.items():
                out.append(f"      {visible(column)}: {_plural(len(rows_), 'cell')} emptied (was {visible(value)}): {_rows(rows_)}")
            for (column, value), rows_ in filled.items():
                out.append(f"      {visible(column)}: {_plural(len(rows_), 'cell')} filled in ({visible(value)}): {_rows(rows_)}")
            if t.columns_moved:
                moved_ = "; ".join(f"{o} → {n}" for o, n in t.columns_moved)
                out.append(f"      numbers now under another header: {visible(moved_)} (headers corrected? the changes above may be relabelling)")
            if t.columns_renamed and t.status == "changed":
                out.append("      columns renamed: " + _some([f"{o} → {n}" for o, n in t.columns_renamed]))
            if t.rows_renamed and t.status == "changed":
                out.append("      rows renamed: " + _some([f"{o} → {n}" for o, n in t.rows_renamed]))
            for what, keys in (
                ("rows added", t.rows_added),
                ("rows removed", t.rows_removed),
                ("columns added", t.columns_added),
                ("columns removed", t.columns_removed),
            ):
                if keys and t.status == "changed":
                    out.append(f"      {what}: " + _some(keys))
            if t.caption:
                out.append("      caption: " + _words(Change("changed", words=word_diff(*t.caption)), color))

    numbers = [("Abstract", ch) for ch in d.abstract if ch.numbers] + [(sd.name, ch) for sd in d.sections for ch in sd.changes if ch.numbers]
    if numbers:
        out += ["", paint(BOLD, "Numbers in the text")]
        for place, ch in numbers:
            assert ch.new is not None
            where = paint(DIM, _at(ch.new))
            for n in ch.numbers:
                out.append(
                    f"  {visible(place)}  {where}  ...{visible(n.before)} {visible(n.old)} → {paint(YELLOW, visible(n.new))} {visible(n.after)}..."
                )

    if d.title or d.authors.changed or d.authors.unread:
        out += ["", paint(BOLD, "Title and authors")]
        if d.title:
            out.append(f'  title: "{visible(d.title[0])}" → "{visible(d.title[1])}"')
        if d.authors.added:
            out.append("  added: " + ", ".join(visible(n) for n in d.authors.added))
        if d.authors.removed:
            out.append("  removed: " + ", ".join(visible(n) for n in d.authors.removed))
        if d.authors.reordered:
            out.append("  order: " + ", ".join(visible(n) for n in d.authors.new))
        if d.authors.unread:
            version = visible(d.new if d.authors.unread == "new" else d.old)
            out.append(f"  authors: none found in {version} (written without \\author?), so not compared")

    if d.abstract:
        out += ["", paint(BOLD, "Abstract")]
        out += [f"  {_change_line(c, color)}" for c in d.abstract]

    concl = [sd for sd in d.sections if is_conclusion(sd) and sd.status != "same"]
    for sd in concl:
        out += ["", paint(BOLD, visible(sd.name))]
        out += [f"  {_change_line(c, color)}" for c in sd.changes]

    if any(sd.status != "same" or sd.moved for sd in d.sections):
        out += ["", paint(BOLD, "Sections")]
    for sd in d.sections:
        if sd.status == "same" and not sd.moved:
            continue
        mark = {"added": "+", "removed": "-", "changed": "~", "same": "="}[sd.status]
        tone = {"added": GREEN, "removed": RED}.get(sd.status, YELLOW)
        counts = _counts(sd)
        was = f" (was {visible(sd.old.name)})" if sd.renamed and sd.old else ""
        moved = " (moved)" if sd.moved else ""
        indent = "  " * max(0, sd.level - 1)
        out.append(f"  {indent}{paint(tone, mark)} {visible(sd.name)}{was}{moved}  {paint(DIM, counts)}")
        if is_conclusion(sd) or (sd.status in ("added", "removed") and limit > 0):
            continue  # shown above; or all of it is new or gone (--full shows it)
        shown = sd.changes if limit <= 0 else sd.changes[:limit]
        out += [f"  {indent}    {_change_line(c, color)}" for c in shown]
        if len(sd.changes) > len(shown):
            out.append(f"  {indent}    {paint(DIM, f'... {len(sd.changes) - len(shown)} more (--full shows all)')}")

    changed_figs = [f for f in d.figures if f.status != "same"]
    if changed_figs:
        out += ["", paint(BOLD, "Figures")]
        for f in changed_figs:
            line = f"  {f.status:8} {visible(f.name)}"
            if f.graphics:
                line += f"  graphics {visible(', '.join(f.graphics[0]) or '-')} → {visible(', '.join(f.graphics[1]) or '-')}"
            if f.caption:
                line += "  caption: " + _words(Change("changed", words=f.caption), color)
            out.append(line)

    r = d.references
    if r.added or r.removed or r.updated:
        out += ["", paint(BOLD, "References")]
        out += [f"  {paint(GREEN, '+')} {visible(x.key)}  {visible(x.title[:90])}" for x in r.added]
        out += [f"  {paint(RED, '-')} {visible(x.key)}  {visible(x.title[:90])}" for x in r.removed]
        out += [f"  {paint(YELLOW, '~')} {visible(x.key)}  {visible(x.what)}" for x in r.updated]
    return "\n".join(out) + "\n"


def _counts(sd: SectionDiff) -> str:
    kinds = [c.kind for c in sd.changes]
    if sd.status in ("added", "removed"):
        return _plural(len(kinds), "sentence")
    parts = [f"+{kinds.count('added')}", f"-{kinds.count('removed')}", f"~{kinds.count('changed')}"]
    if kinds.count("moved"):
        parts.append(f"{kinds.count('moved')} moved")
    return " ".join(parts)


# ---------------------------------------------------------------- Markdown


def _html(s: str) -> str:
    r"""Text inside an HTML element of a Markdown report (<summary>), where Markdown escapes would show as written:
    HTML escaped, and links and mentions broken as _md breaks them.

    >>> _html("A_b <i>x</i> ~1 @me")
    'A_b &lt;i&gt;x&lt;/i&gt; ~1 @\u200bme'
    """
    s = visible(s).replace("\n", " ").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return s.replace("://", ":\u200b//").replace("www.", "www\u200b.").replace("@", "@\u200b")


def _md_words(c: Change) -> str:
    out = []
    prev = "="
    for op, t in c.words:
        if op == "=":
            out.append(_md(t))
            prev = op
            continue
        lead, core = t[: len(t) - len(t.lstrip())], t.strip()
        trail = t[len(t.rstrip()) :] if core else ""
        if op == "+" and prev == "-" and lead:
            lead = " "
        prev = op
        if core:
            out.append(lead + (f"~~{_md(core)}~~" if op == "-" else f"**{_md(core)}**") + trail)
        else:
            out.append(t)
    return "".join(out)


def _md_change(c: Change) -> str:
    if c.kind == "changed" and c.new is not None:
        mark = "**\\#**" if c.numbers_only else "\\~"  # "- # ..." would be a heading
        return f"- {mark} {_md_words(c)} <sub>{_code(f'{c.new.file}:{c.new.line}')}</sub>"
    if c.kind == "added" and c.new is not None:
        return f"- **+** {_md(c.new.text)} <sub>{_code(f'{c.new.file}:{c.new.line}')}</sub>"
    if c.kind == "removed" and c.old is not None:
        return f"- **−** ~~{_md(c.old.text)}~~ <sub>{_code(f'{c.old.file}:{c.old.line}')}</sub>"
    s = c.new or c.old
    assert s is not None
    return f"- moved {'from' if c.new is not None else 'to'} {_md(c.other)}: {_md(s.text[:80])}"


def markdown(d: Diff, about: str = "", limit: int = 30, budget: int = 60_000) -> str:
    """The report as GitHub Markdown; nothing from the paper renders (no links, mentions or HTML from its text).
    Sections' details are folded, and the report stops before `budget` characters (a comment holds 65,536)."""
    out = [f"### arxiv-diff: {_code(d.old)} → {_code(d.new)}" + (f" — {_md(about)}" if about else ""), ""]
    out += [f"- {_md(line)}" for line in headline(d)]
    if not d.changed:
        return "\n".join([*out, "", "No changes."]) + "\n"

    value_changes = [(t, c) for t in d.tables for c in t.cells]
    structure = [
        t
        for t in d.tables
        if t.status in ("added", "removed")
        or t.rows_added
        or t.rows_removed
        or t.columns_added
        or t.columns_removed
        or t.rows_renamed
        or t.columns_renamed
        or t.caption
        or t.columns_moved
    ]
    if value_changes or structure:
        out += ["", "#### Tables", ""]
    if value_changes:
        out += ["| table | row | column | old | new | change |", "|---|---|---|---:|---:|---|"]
        for t, c in value_changes[:200]:
            change = (
                f"{delta(c)} {verdict(c)}".strip()
                if c.kind == "value"
                else ("now bold" if c.new_bold else "no longer bold")
                if c.kind == "bold"
                else "text"
            )
            out.append(f"| {_md(t.name)} | {_md(c.row)} | {_md(c.column)} | {_md(c.old)} | {_md(c.new)} | {_md(change)} |")
        if len(value_changes) > 200:
            out.append(f"\n… and {len(value_changes) - 200} more cells (the JSON report has all).")
        out.append("")  # a list right under a table would be read as more rows
    for t in structure:
        if t.status != "changed":
            out.append(f"- table {_md(t.name)}: {t.status}")
            continue
        bits = (
            [f"rows added: {', '.join(t.rows_added[:10])}" + (f" … ({len(t.rows_added)})" if len(t.rows_added) > 10 else "")] if t.rows_added else []
        )
        bits += (
            [f"rows removed: {', '.join(t.rows_removed[:10])}" + (f" … ({len(t.rows_removed)})" if len(t.rows_removed) > 10 else "")]
            if t.rows_removed
            else []
        )
        bits += [f"{len(t.rows_renamed)} rows renamed"] if t.rows_renamed else []
        bits += [f"columns added: {', '.join(t.columns_added)}"] if t.columns_added else []
        bits += [f"columns removed: {', '.join(t.columns_removed)}"] if t.columns_removed else []
        bits += ["columns renamed: " + ", ".join(f"{o} → {n}" for o, n in t.columns_renamed)] if t.columns_renamed else []
        bits += ["caption changed"] if t.caption else []
        bits += (
            ["numbers now under another header: " + ", ".join(f"{o} → {n}" for o, n in t.columns_moved) + " (headers corrected?)"]
            if t.columns_moved
            else []
        )
        out.append(f"- table {_md(t.name)}: {_md('; '.join(bits))}")

    numbers = [("Abstract", ch) for ch in d.abstract if ch.numbers] + [(sd.name, ch) for sd in d.sections for ch in sd.changes if ch.numbers]
    if numbers:
        out += ["", "#### Numbers in the text", ""]
        for place, ch in numbers:
            for n in ch.numbers:
                out.append(f"- {_md(place)}: …{_md(n.before)} ~~{_md(n.old)}~~ **{_md(n.new)}** {_md(n.after)}…")

    if d.title or d.authors.changed:
        out += ["", "#### Title and authors", ""]
        if d.title:
            out.append(f"- title: ~~{_md(d.title[0])}~~ → **{_md(d.title[1])}**")
        if d.authors.added:
            out.append(f"- added: {_md(', '.join(d.authors.added))}")
        if d.authors.removed:
            out.append(f"- removed: {_md(', '.join(d.authors.removed))}")
        if d.authors.reordered:
            out.append(f"- new order: {_md(', '.join(d.authors.new))}")
    if d.abstract:
        out += ["", "#### Abstract", "", *[_md_change(c) for c in d.abstract]]
    for sd in d.sections:
        if is_conclusion(sd) and sd.status != "same":
            out += ["", f"#### {_md(sd.name)}", "", *[_md_change(c) for c in sd.changes[:limit]]]
            if len(sd.changes) > limit:
                out.append(f"- … {len(sd.changes) - limit} more")

    rest = [sd for sd in d.sections if (sd.status != "same" or sd.moved) and not is_conclusion(sd)]
    if rest:
        out += ["", "#### Sections", ""]
        for sd in rest:
            was = f" (was {_md(sd.old.name)})" if sd.renamed and sd.old else ""
            was_ = f" (was {sd.old.name})" if sd.renamed and sd.old else ""
            status = "moved" if sd.status == "same" else sd.status + (", moved" if sd.moved else "")
            summary = _html(f"{status}: {sd.name}{was_} — {_counts(sd)}")  # Markdown is not read inside <summary>
            title = f"{status}: {_md(sd.name)}{was} — {_md(_counts(sd))}"
            if sd.status in ("added", "removed") or not sd.changes:
                out.append(f"- {title}")
                continue
            body = [_md_change(c) for c in sd.changes[:limit]]
            if len(sd.changes) > limit:
                body.append(f"- … {len(sd.changes) - limit} more")
            out += ["<details>", f"<summary>{summary}</summary>", "", *body, "", "</details>"]

    figs = [f for f in d.figures if f.status != "same"]
    if figs:
        out += ["", "#### Figures", ""]
        for f in figs:
            line = f"- {f.status}: {_md(f.name)}"
            if f.graphics:
                line += f" — graphics {_md(', '.join(f.graphics[0]) or '-')} → {_md(', '.join(f.graphics[1]) or '-')}"
            if f.caption:
                line += " — caption: " + _md_words(Change("changed", words=f.caption))
            out.append(line)
    r = d.references
    if r.added or r.removed or r.updated:
        out += ["", "#### References", ""]
        out += [f"- added {_code(x.key)} {_md(x.title)}" for x in r.added]
        out += [f"- removed {_code(x.key)} {_md(x.title)}" for x in r.removed]
        out += [f"- updated {_code(x.key)}: {_md(x.what)}" for x in r.updated]
    report = "\n".join(out) + "\n"
    if len(report) > budget:
        cut = report.rfind("\n", 0, budget - 200)
        report = report[:cut] + "\n\n… (cut here: the full report is in the JSON or HTML output)\n"
        if report.count("<details>") > report.count("</details>"):
            report += "\n</details>\n"
    return report
