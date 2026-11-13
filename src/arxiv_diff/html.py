"""The side-by-side page: one HTML file with everything in it (no fonts, scripts or images from anywhere), to open in
a browser or share. Every piece of the paper's text is escaped, and the page's Content-Security-Policy forbids
loading anything, so a paper cannot make the page do more than show its words."""

from __future__ import annotations

import base64
import hashlib
from html import escape

from . import __version__
from .diff import Change, Diff, SectionDiff, word_diff
from .latex import Sentence
from .report import _grouped, _plural, delta, headline, is_conclusion, verdict

CSS = """
:root { --bg: #fbfbfa; --fg: #1d1d1f; --muted: #6b6b70; --line: #e3e3e0; --card: #ffffff;
  --del: #fbe4e4; --del-fg: #9b1c1c; --ins: #e1f4e5; --ins-fg: #14632d; --num: #fff1c2; --accent: #2f5bd3; }
@media (prefers-color-scheme: dark) { :root { --bg: #141416; --fg: #e8e8ea; --muted: #9a9aa2; --line: #2c2c31;
  --card: #1c1c20; --del: #4a1f22; --del-fg: #ffb4b4; --ins: #17391f; --ins-fg: #a6e8b5; --num: #4a3f12; --accent: #8fb0ff; } }
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--fg); font: 15px/1.55 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width: 1180px; margin: 0 auto; padding: 24px 16px 64px; }
h1 { font-size: 22px; margin: 0 0 4px; } h2 { font-size: 18px; margin: 32px 0 10px; } h3 { font-size: 15px; margin: 0; }
.sub { color: var(--muted); margin: 0 0 12px; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; margin: 10px 0; padding: 0; list-style: none; }
.chips li { background: var(--card); border: 1px solid var(--line); border-radius: 999px; padding: 2px 10px; font-size: 13px; }
nav { position: sticky; top: 0; background: var(--bg); border-bottom: 1px solid var(--line); padding: 8px 0; z-index: 2;
  display: flex; flex-wrap: wrap; gap: 14px; align-items: center; font-size: 14px; }
nav a { color: var(--accent); text-decoration: none; } nav label { color: var(--muted); }
table.cells { border-collapse: collapse; width: 100%; background: var(--card); font-size: 14px; }
table.cells th, table.cells td { border: 1px solid var(--line); padding: 4px 8px; text-align: left; vertical-align: top; }
table.cells td.n { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
.better { color: var(--ins-fg); } .worse { color: var(--del-fg); }
details.sec { background: var(--card); border: 1px solid var(--line); border-radius: 8px; margin: 8px 0; }
details.sec > summary { cursor: pointer; padding: 8px 12px; display: flex; gap: 10px; align-items: baseline; flex-wrap: wrap; }
.tag { font-size: 12px; border-radius: 4px; padding: 0 6px; background: var(--line); color: var(--fg); }
.tag.added { background: var(--ins); color: var(--ins-fg); } .tag.removed { background: var(--del); color: var(--del-fg); }
.count { color: var(--muted); font-size: 13px; }
.pair { display: grid; grid-template-columns: 1fr 1fr; border-top: 1px solid var(--line); }
.pair > div { padding: 8px 12px; min-width: 0; overflow-wrap: anywhere; }
.pair > div + div { border-left: 1px solid var(--line); }
.pair.numbers { background: linear-gradient(90deg, var(--num) 0 4px, transparent 4px); }
.where { display: block; color: var(--muted); font-size: 12px; font-family: ui-monospace, Consolas, monospace; }
.eq { font-family: ui-monospace, Consolas, monospace; font-size: 13px; }
del { background: var(--del); color: var(--del-fg); text-decoration: line-through; border-radius: 3px; padding: 0 1px; }
ins { background: var(--ins); color: var(--ins-fg); text-decoration: none; border-radius: 3px; padding: 0 1px; }
.gone { color: var(--del-fg); } .new { color: var(--ins-fg); } .moved { color: var(--muted); font-style: italic; }
.gap { color: var(--muted); font-size: 13px; padding: 4px 12px; border-top: 1px dashed var(--line); }
ul.plain { padding-left: 18px; } footer { color: var(--muted); font-size: 12px; margin-top: 48px; }
body.numbers-only .pair:not(.numbers):not(.caption), body.numbers-only .gap, body.numbers-only details.no-numbers { display: none; }
body.hide-moved .pair.is-moved { display: none; }
@media (max-width: 720px) { .pair { grid-template-columns: 1fr; } .pair > div + div { border-left: 0; border-top: 1px dashed var(--line); } }
"""

SCRIPT = """
for (const box of document.querySelectorAll('input[data-class]')) {
  box.addEventListener('change', () => document.body.classList.toggle(box.dataset.class, box.checked));
}
const link = document.getElementById('open-all');
const sections = () => [...document.querySelectorAll('details.sec')];
const label = () => { link.textContent = sections().every((d) => d.open) ? 'fold all' : 'unfold all'; };
link.addEventListener('click', (e) => {
  e.preventDefault(); const open = !sections().every((d) => d.open);
  for (const d of sections()) d.open = open;
  label();
});
for (const d of sections()) d.addEventListener('toggle', label);
label();
"""


SCRIPT_HASH = "sha256-" + base64.b64encode(hashlib.sha256(SCRIPT.encode()).digest()).decode()


def _e(s: str) -> str:
    return escape(s, quote=True)


def _words(words: list[tuple[str, str]]) -> tuple[str, str]:
    """A word diff as the old side (deletions marked) and the new side (insertions marked)."""
    old, new = [], []
    for op, t in words:
        if op == "=":
            old.append(_e(t))
            new.append(_e(t))
        else:
            lead, core = t[: len(t) - len(t.lstrip())], t.lstrip()
            (old if op == "-" else new).append(_e(lead) + (f"<del>{_e(core)}</del>" if op == "-" else f"<ins>{_e(core)}</ins>"))
    return "".join(old), "".join(new)


def _where(s: Sentence | None) -> str:
    return f'<span class="where">{_e(f"{s.file}:{s.line}")}</span>' if s is not None else ""


def _text(c: Change, side: str) -> str:
    s = c.old if side == "old" else c.new
    if s is None:
        return ""
    cls = ' class="eq"' if s.kind == "equation" else ""
    return f"<span{cls}>{_e(s.text)}</span>"


def _pair(c: Change) -> str:
    if c.kind == "changed":
        old, new = _words(c.words)
        cls = "pair numbers" if c.numbers else "pair"
        eq = c.new is not None and c.new.kind == "equation"
        if eq:
            old, new = f'<span class="eq">{old}</span>', f'<span class="eq">{new}</span>'
        return f'<div class="{cls}"><div>{_where(c.old)}{old}</div><div>{_where(c.new)}{new}</div></div>'
    if c.kind == "added":
        return f'<div class="pair"><div></div><div class="new">{_where(c.new)}{_text(c, "new")}</div></div>'
    if c.kind == "removed":
        return f'<div class="pair"><div class="gone">{_where(c.old)}{_text(c, "old")}</div><div></div></div>'
    if c.new is not None:  # moved here
        left = f'<div class="moved">moved here from {_e(c.other)}</div>'
        return f'<div class="pair is-moved">{left}<div class="moved">{_where(c.new)}{_text(c, "new")}</div></div>'
    return (
        f'<div class="pair is-moved"><div class="moved">{_where(c.old)}{_text(c, "old")}</div><div class="moved">moved to {_e(c.other)}</div></div>'
    )


def _section(sd: SectionDiff, open_: bool, name: str = "") -> str:
    kinds = [c.kind for c in sd.changes]
    if sd.status in ("added", "removed"):
        count = _plural(len(kinds), "sentence")
    else:
        count = f"+{kinds.count('added')} −{kinds.count('removed')} ~{kinds.count('changed')}"
        if sd.unchanged:
            count += f" · {sd.unchanged} unchanged"
    was = f' <span class="count">was {_e(sd.old.name)}</span>' if sd.renamed and sd.old else ""
    moved = ' <span class="count">moved</span>' if sd.moved else ""
    status = "moved" if sd.status == "same" and sd.moved else sd.status
    tag = f'<span class="tag {sd.status}">{status}</span>'
    classes = "sec" if any(c.numbers for c in sd.changes) else "sec no-numbers"
    body = "".join(_pair(c) for c in sd.changes)
    if sd.unchanged and sd.status == "changed":
        body += f'<div class="gap">{_plural(sd.unchanged, "sentence")} unchanged</div>'
    return (
        f'<details class="{classes}"{" open" if open_ else ""}><summary>{tag}<h3>{_e(name or sd.name)}</h3>{was}{moved}'
        f'<span class="count">{count}</span></summary>{body}</details>'
    )


def _tables(d: Diff) -> str:
    out = []
    for t in d.tables:
        if t.status == "same":
            continue
        w = t.new or t.old
        where = f'<span class="where">{_e(f"{w.file}:{w.line}")}</span>' if w else ""
        out.append(f'<h3>{_e(t.name)} <span class="tag {t.status}">{t.status}</span></h3>{where}')
        rows = []
        for c in t.cells:
            if c.kind == "text" and (not c.old or not c.new):
                continue
            if c.kind == "value":
                v = verdict(c)
                change = f'<span class="{v}">{_e(delta(c))}{" " + v if v else ""}</span>'
            elif c.kind == "bold":
                change = "now bold" if c.new_bold else "no longer bold"
            else:
                change = "text"
            rows.append(
                f'<tr><td>{_e(c.row)}</td><td>{_e(c.column)}</td><td class="n">{_e(c.old)}</td><td class="n">{_e(c.new)}</td><td>{change}</td></tr>'
            )
        if rows:
            out.append(
                '<table class="cells"><tr><th>row</th><th>column</th><th>old</th><th>new</th><th>change</th></tr>' + "".join(rows) + "</table>"
            )
        notes = []
        emptied, filled = _grouped(t.cells)
        notes += [f"{_e(col)}: {len(r)} cells emptied (were {_e(v)}): {_e('; '.join(r))}" for (col, v), r in emptied.items()]
        notes += [f"{_e(col)}: {len(r)} cells filled in ({_e(v)}): {_e('; '.join(r))}" for (col, v), r in filled.items()]
        if t.columns_moved:
            moved_ = "; ".join(f"{o} → {n}" for o, n in t.columns_moved)
            notes.append(f"numbers now under another header: {_e(moved_)} (headers corrected? the changes above may be relabelling)")
        if t.status == "changed" and t.columns_renamed:
            notes.append("columns renamed: " + _e("; ".join(f"{o} → {n}" for o, n in t.columns_renamed)))
        if t.status == "changed" and t.rows_renamed:
            notes.append("rows renamed: " + _e("; ".join(f"{o} → {n}" for o, n in t.rows_renamed)))
        if t.status == "changed":
            for what, keys in (
                ("rows added", t.rows_added),
                ("rows removed", t.rows_removed),
                ("columns added", t.columns_added),
                ("columns removed", t.columns_removed),
            ):
                if keys:
                    notes.append(f"{what}: {_e('; '.join(keys))}")
        if t.caption:
            old, new = _words(word_diff(*t.caption))
            notes.append(f"caption:<div class='pair caption'><div>{old}</div><div>{new}</div></div>")
        if notes:
            out.append('<ul class="plain">' + "".join(f"<li>{n}</li>" for n in notes) + "</ul>")
    return "".join(out)


def _one(d: Diff, about: str, anchor: str) -> str:
    out = [f'<section id="{anchor}">', f"<h1>{_e(d.old)} → {_e(d.new)}</h1>"]
    if about:
        out.append(f'<p class="sub">{_e(about)}</p>')
    out.append('<ul class="chips">' + "".join(f"<li>{_e(line)}</li>" for line in headline(d)) + "</ul>")
    if not d.changed:
        out.append("<p>No changes.</p></section>")
        return "".join(out)
    tables = _tables(d)
    if tables:
        out.append(f'<h2 id="{anchor}-tables">Tables</h2>{tables}')
    numbers = [("Abstract", ch) for ch in d.abstract if ch.numbers] + [(sd.name, ch) for sd in d.sections for ch in sd.changes if ch.numbers]
    if numbers:
        out.append(f'<h2 id="{anchor}-numbers">Numbers in the text</h2><ul class="plain">')
        for place, ch in numbers:
            for n in ch.numbers:
                out.append(f"<li>{_e(place)} {_where(ch.new)}…{_e(n.before)} <del>{_e(n.old)}</del> <ins>{_e(n.new)}</ins> {_e(n.after)}…</li>")
        out.append("</ul>")
    if d.title or d.authors.changed:
        out.append(f'<h2 id="{anchor}-front">Title and authors</h2><ul class="plain">')
        if d.title:
            out.append(f"<li>title: <del>{_e(d.title[0])}</del> → <ins>{_e(d.title[1])}</ins></li>")
        if d.authors.added:
            out.append(f"<li>added: <ins>{_e(', '.join(d.authors.added))}</ins></li>")
        if d.authors.removed:
            out.append(f"<li>removed: <del>{_e(', '.join(d.authors.removed))}</del></li>")
        if d.authors.reordered:
            out.append(f"<li>new order: {_e(', '.join(d.authors.new))}</li>")
        out.append("</ul>")
    if d.abstract:
        abstract = SectionDiff("changed", None, None, 1, d.abstract)
        out.append(f'<h2 id="{anchor}-abstract">Abstract</h2>' + _section(abstract, True, "Abstract"))
    changed = [sd for sd in d.sections if sd.status != "same" or sd.moved]
    if changed:
        out.append(f'<h2 id="{anchor}-sections">Sections</h2>')
        out += [_section(sd, is_conclusion(sd) or len(changed) <= 6) for sd in changed]
    figs = [f for f in d.figures if f.status != "same"]
    if figs:
        out.append(f'<h2 id="{anchor}-figures">Figures</h2><ul class="plain">')
        for f in figs:
            line = f'<span class="tag {f.status}">{f.status}</span> {_e(f.name)}'
            if f.graphics:
                line += f" — graphics <del>{_e(', '.join(f.graphics[0]) or '-')}</del> → <ins>{_e(', '.join(f.graphics[1]) or '-')}</ins>"
            if f.caption:
                old, new = _words(f.caption)
                line += f"<div class='pair caption'><div>{old}</div><div>{new}</div></div>"
            out.append(f"<li>{line}</li>")
        out.append("</ul>")
    r = d.references
    if r.added or r.removed or r.updated:
        out.append(f'<h2 id="{anchor}-references">References</h2><ul class="plain">')
        out += [f"<li><ins>+ {_e(x.key)}</ins> {_e(x.title)}</li>" for x in r.added]
        out += [f"<li><del>− {_e(x.key)}</del> {_e(x.title)}</li>" for x in r.removed]
        out += [f"<li>~ {_e(x.key)}: {_e(x.what)}</li>" for x in r.updated]
        out.append("</ul>")
    out.append("</section>")
    return "".join(out)


SECTIONS = (("tables", "tables"), ("numbers", "numbers"), ("front", "title and authors"), ("abstract", "abstract"),
            ("sections", "sections"), ("figures", "figures"), ("references", "references"))  # fmt: skip


def page(diffs: list[tuple[Diff, str]], title: str = "") -> str:
    """The page for one comparison, or for several (each step of a paper's versions) one after another."""
    if not title and len(diffs) > 1:
        first, last = diffs[0][0], diffs[-1][0]
        title = f"arxiv-diff: {first.old} → {last.new}, {len(diffs)} steps"
    title = title or (diffs[0][1] if diffs and diffs[0][1] else "arxiv-diff")
    parts = [_one(d, about, f"d{k}") for k, (d, about) in enumerate(diffs)]
    links = []
    if len(diffs) > 1:
        links = [f'<a href="#d{k}">{_e(d.old)} → {_e(d.new)}</a>' for k, (d, _) in enumerate(diffs)]
    else:
        links = [f'<a href="#d0-{s}">{label}</a>' for s, label in SECTIONS if f'id="d0-{s}"' in parts[0]] if parts else []
    nav = (
        "<nav>" + "".join(links) + '<label><input type="checkbox" data-class="numbers-only"> only sentences whose numbers changed</label>'
        '<label><input type="checkbox" data-class="hide-moved"> hide moved sentences</label><a href="#" id="open-all">fold or unfold all</a></nav>'
    )
    return (
        '<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; style-src 'unsafe-inline'; script-src '{SCRIPT_HASH}'\">"
        '<meta name="referrer" content="no-referrer">'
        f"<title>{_e(title)}</title><style>{CSS}</style></head><body><main>{nav}{''.join(parts)}"
        f"<footer>Made by arxiv-diff {__version__}. Left: the old version; right: the new one. "
        "Sentences are compared as plain text (formatting dropped, citations as [keys], references as ‹labels›).</footer>"
        f"</main><script>{SCRIPT}</script></body></html>\n"
    )
