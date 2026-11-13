r"""From a LaTeX project to what a reader of the paper sees: the document in reading order (\input followed), its
sections, title, authors and abstract, its figures, and its prose as plain sentences with their place in the source.
"""

from __future__ import annotations

import bisect
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field

from paper_proof.bib import _matching
from paper_proof.latex import CITE, INPUT, MULTICITE, Project, _resolve


@dataclass
class Source:
    r"""The document with \input followed, and where each of its characters came from."""

    text: str
    starts: list[int] = field(default_factory=list)  # where each piece starts in `text`
    origins: list[tuple[str, int]] = field(default_factory=list)  # (file, offset in that file) of each piece
    files: dict[str, str] = field(default_factory=dict)
    newlines: dict[str, list[int]] = field(default_factory=dict, repr=False, compare=False)  # per file, built when asked
    macros: dict[str, tuple[int, str]] = field(default_factory=dict)  # the document's own commands: name -> (arguments, body)

    def where(self, pos: int) -> tuple[str, int]:
        r"""The file and line of a position in `text`.

        >>> s = Source("ab\ncd", [0, 3], [("main.tex", 0), ("intro.tex", 0)], {"main.tex": "ab\n", "intro.tex": "cd"})
        >>> s.where(1), s.where(4)
        (('main.tex', 1), ('intro.tex', 1))
        """
        if not self.starts:
            return "", 0
        k = max(0, bisect.bisect_right(self.starts, pos) - 1)
        file, off = self.origins[k]
        local = off + pos - self.starts[k]
        if file not in self.newlines:  # one pass per file, then a binary search per position
            self.newlines[file] = [i for i, c in enumerate(self.files.get(file, "")) if c == "\n"]
        return file, bisect.bisect_left(self.newlines[file], local) + 1


MAX_USES = 8  # times one file may be \input
MAX_DOCUMENT = 50_000_000  # characters, all files together


def expand(project: Project) -> Source:
    r"""The project's text in reading order: each \input, \include and \import replaced by the file it names (as
    paper-proof read it: comments and \iffalse blocks removed)."""
    root = project.main.parent
    pieces: list[tuple[str, int, str]] = []
    uses: Counter[str] = Counter()
    size = [0]

    def visit(rel: str, stack: frozenset[str]) -> None:
        text = project.texts.get(rel, "")
        i = 0
        for m in INPUT.finditer(text):
            name = m.group(1) or (m.group(2) or "") + "/" + m.group(3)
            p = _resolve(root, (root / rel).parent, name, ".tex")
            sub = p.relative_to(root).as_posix() if p is not None else ""
            if not sub or sub not in project.texts or sub in stack or len(stack) > 20:
                continue
            # a file \input many times (each including the next many times) would grow the document exponentially
            if uses[sub] >= MAX_USES or size[0] + len(project.texts[sub]) > MAX_DOCUMENT:
                continue
            uses[sub] += 1
            size[0] += len(project.texts[sub])
            pieces.append((rel, i, text[i : m.start()]))
            visit(sub, stack | {sub})
            i = m.end()
        pieces.append((rel, i, text[i:]))

    main = project.main.relative_to(root).as_posix()
    visit(main, frozenset({main}))
    src = Source("", files=dict(project.texts))
    out, n = [], 0
    for file, off, text in pieces:
        src.starts.append(n)
        src.origins.append((file, off))
        out.append(text)
        n += len(text)
    src.text = "".join(out)
    src.macros = macros(src.text)
    return src


# ---------------------------------------------------------------- LaTeX to plain text

INLINE_MATH = re.compile(r"(?<!\\)\$(?:\\.|[^$\\]){1,4000}\$|\\\((?:.|\n){0,4000}?\\\)")
COMMAND = re.compile(r"\\([A-Za-z@]+)\*?|\\(.)", re.S)
KEEP_ARG = {
    "textbf", "textit", "textsl", "emph", "underline", "texttt", "textsc", "textrm", "textsf", "textmd", "textup", "mbox",
    "hbox", "text", "textnormal", "uline", "ul", "hl", "sout", "xout", "textsuperscript", "textsubscript", "makebox",
    "fbox", "framebox", "url", "nolinkurl", "path", "mathrm", "mathbf", "mathit", "boldsymbol", "bm", "ensuremath",
    "title", "paragraph", "subparagraph", "textls", "uppercase", "lowercase", "MakeUppercase", "MakeLowercase",
    "smash", "acrshort", "acrlong", "acrfull", "acs", "acl", "acf", "ac", "gls", "glspl", "Gls", "Glspl",
}  # fmt: skip
SECOND_ARG = {"textcolor", "colorbox", "href", "hyperref", "hyperlink", "texorpdfstring", "foreignlanguage"}
DROP = {
    "label", "vspace", "hspace", "vskip", "hskip", "includegraphics", "bibliographystyle", "bibliography",
    "addbibresource", "newpage", "clearpage", "cleardoublepage", "pagebreak", "linebreak", "nolinebreak", "noindent",
    "centering", "raggedright", "raggedleft", "maketitle", "tableofcontents", "printbibliography", "phantom",
    "hphantom", "vphantom", "protect", "relax", "footnotemark", "index", "glossary", "nocite", "setlength",
    "addtolength", "setcounter", "addtocounter", "small", "footnotesize", "scriptsize", "tiny", "large", "Large",
    "LARGE", "huge", "Huge", "normalsize", "bfseries", "itshape", "ttfamily", "rmfamily", "sffamily", "scshape",
    "normalfont", "bf", "it", "em", "tt", "rm", "sf", "sc", "sl", "color", "medskip", "smallskip", "bigskip",
    "quad", "qquad", "par", "item", "appendix", "frontmatter", "mainmatter", "backmatter", "allowbreak", "looseness",
    "thispagestyle", "pagestyle", "captionsetup", "hfill", "vfill", "null", "strut", "leavevmode",
}  # fmt: skip
NO_ARGS = {
    "quad", "qquad", "par", "item", "appendix", "frontmatter", "mainmatter", "backmatter", "allowbreak", "hfill",
    "vfill", "null", "strut", "leavevmode", "noindent", "centering", "raggedright", "raggedleft", "maketitle",
    "newpage", "clearpage", "cleardoublepage", "protect", "relax", "medskip", "smallskip", "bigskip", "small",
    "footnotesize", "scriptsize", "tiny", "large", "Large", "LARGE", "huge", "Huge", "normalsize", "bfseries",
    "itshape", "ttfamily", "rmfamily", "sffamily", "scshape", "normalfont", "bf", "it", "em", "tt", "rm", "sf", "sc",
    "sl", "tableofcontents", "printbibliography", "footnotemark",
}  # fmt: skip
WORDS = {
    "LaTeX": "LaTeX", "TeX": "TeX", "ie": "i.e.", "eg": "e.g.", "etal": "et al.", "etc": "etc.", "vs": "vs.",
    "dots": "...", "ldots": "...", "cdots": "...", "textellipsis": "...", "S": "§", "P": "¶", "textendash": "–",
    "textemdash": "—", "textquoteright": "'", "textquoteleft": "'", "textasciitilde": "~", "times": "×", "pm": "±",
    "textbackslash": "\\", "ss": "ß", "o": "ø", "O": "Ø", "aa": "å", "AA": "Å", "ae": "æ", "AE": "Æ", "oe": "œ",
    "l": "ł", "L": "Ł", "i": "ı", "copyright": "©", "textregistered": "®", "texttrademark": "™", "degree": "°",
}  # fmt: skip
REF = {"ref", "eqref", "autoref", "Autoref", "cref", "Cref", "vref", "Vref", "pageref", "nameref", "subref", "cpageref", "labelcref"}
CITE_NAME = re.compile(
    r"(?:[Cc]ite(?:p|t|alp|alt|author|year|yearpar|num|title|url|date)?|[Pp]arencite|[Tt]extcite|[Aa]utocite|[Ff]ootcite"
    r"|[Ss]martcite|supercite|fullcite|footfullcite|citeauthor|citeyear)$"
)


def _arg(s: str, j: int) -> tuple[str | None, int]:
    """The argument in braces at s[j] (after spaces and any [optional] arguments), and where it ends."""
    k = j
    while True:
        m = re.match(r"\s*\[[^\]]*\]", s[k:])
        if not m:
            break
        k += m.end()
    m = re.match(r"\s*\{", s[k:])
    if not m:
        return None, j
    start = k + m.end()
    end = _matching(s, start, "{", "}")
    if end < 0:
        return s[start:], len(s)
    return s[start:end], end + 1


ACCENTS = {"'": "\u0301", "`": "\u0300", "^": "\u0302", '"': "\u0308", "~": "\u0303", "=": "\u0304", ".": "\u0307",
           "c": "\u0327", "v": "\u030c", "u": "\u0306", "H": "\u030b", "r": "\u030a", "k": "\u0328"}  # fmt: skip
ACCENT = re.compile(r"\\(['`^\"~=.])\s*(?:\{\s*(\\?[A-Za-z])\s*\}|(\\?[A-Za-z]))|\\([cvuHrk])\s*(?:\{\s*(\\?[A-Za-z])\s*\}|\s([A-Za-z]))")


def _accents(s: str) -> str:
    r"""Accented letters written with LaTeX accents, as letters.

    >>> _accents(r"M\"uller, Garc\'{\i}a, \v{S}koda, Fran\c{c}ois")
    'Müller, García, Škoda, François'
    """

    def letter(m: re.Match[str]) -> str:
        accent = m.group(1) or m.group(4)
        base = next(g for g in (m.group(2), m.group(3), m.group(5), m.group(6)) if g)
        base = {"\\i": "i", "\\j": "j"}.get(base, base.lstrip("\\"))
        return unicodedata.normalize("NFC", base + ACCENTS[accent])

    return ACCENT.sub(letter, s)


ENV_ARGS = {"minipage": 1, "multicols": 1, "wrapfigure": 2, "subfigure": 1, "adjustbox": 1, "spacing": 1, "tabular": 1}
MACRO_DEF = re.compile(
    r"\\(?:(?:re)?newcommand|providecommand)\*?\s*\{?\s*\\([A-Za-z@]+)\s*\}?\s*(?:\[(\d)\])?\s*\{"
    r"|\\[gex]?def\s*\\([A-Za-z@]+)\s*\{"
    r"|\\DeclareMathOperator\*?\s*\{?\s*\\([A-Za-z@]+)\s*\}?\s*\{"
)
PROTECTED = KEEP_ARG | SECOND_ARG | DROP | REF | {"footnote", "thanks", "begin", "end", "section", "subsection", "item", "cite", "label"}


def macros(text: str) -> dict[str, tuple[int, str]]:
    r"""The document's own commands (\newcommand{\method}{FooNet}, \def\dff{d_{ff}}, \newcommand{\cell}[2]{#1$\pm$#2}),
    as name -> (number of arguments, body), so that the text and the tables read as the paper prints them. Commands with
    an optional argument, and \def with parameters, are left alone.

    >>> macros(r"\newcommand{\ours}{\textsc{FooNet}\xspace} \def\dff{d_{\text{ff}}} \newcommand{\cell}[2]{#1$_{\pm #2}$}")
    {'ours': (0, '\\textsc{FooNet}\\xspace'), 'dff': (0, 'd_{\\text{ff}}'), 'cell': (2, '#1$_{\\pm #2}$')}
    """
    out: dict[str, tuple[int, str]] = {}
    for m in MACRO_DEF.finditer(text):
        end = _matching(text, m.end(), "{", "}")
        name = m.group(1) or m.group(3) or m.group(4)
        if end < 0 or name in PROTECTED or CITE_NAME.match(name):
            continue
        n = int(m.group(2) or 0)
        body = text[m.end() : end].replace("\n", " ")
        if re.search(r"#(?![1-9])", body) or any(int(k) > n for k in re.findall(r"#([1-9])", body)) or len(body) > 300:
            continue
        if re.search(r"\\" + re.escape(name) + r"(?![A-Za-z@])", body):  # \def\x{\x\x}: TeX itself would loop
            continue
        out[name] = (n, "\\mathrm{" + body + "}" if m.group(4) else body)
    return out


COMMAND_NAME = re.compile(r"\\([A-Za-z@]+)(?![A-Za-z@])")


def expand_macros(s: str, defs: dict[str, tuple[int, str]] | None) -> str:
    r"""The document's own commands replaced by what they stand for, their arguments put in.

    >>> expand_macros(r"\ours{} gets \cell{6.5}{0.4}.", {"ours": (0, "FooNet"), "cell": (2, "#1$_{\\pm #2}$")})
    'FooNet{} gets 6.5$_{\\pm 0.4}$.'
    """
    if not defs:
        return s
    limit = 4 * len(s) + 100_000  # commands that call each other must not grow the text without end
    for _ in range(4):  # commands that use commands; never forever
        out, i, changed = [], 0, False
        for m in COMMAND_NAME.finditer(s):
            if m.start() < i or m.group(1) not in defs:
                continue
            n, body = defs[m.group(1)]
            j, args = m.end(), []
            for _k in range(n):
                a = re.match(r"\s*\{", s[j:])
                end = _matching(s, j + a.end(), "{", "}") if a else -1
                if a is None or end < 0:
                    break
                args.append(s[j + a.end() : end])
                j = end + 1
            if len(args) < n:
                continue
            for k, arg in enumerate(args, 1):
                body = body.replace(f"#{k}", arg)
            out += [s[i : m.start()], body]
            i, changed = j, True
        if not changed:
            break
        t = "".join(out) + s[i:]
        if len(t) > limit:
            break
        s = t
    return s


def _text(s: str) -> str:
    """LaTeX as text (inline math kept as written)."""
    s = _accents(s)
    out: list[str] = []
    i = 0
    while i < len(s):
        c = s[i]
        if c == "$" or s.startswith("\\(", i):
            m = INLINE_MATH.match(s, i)
            if m is not None:
                out.append(re.sub(r"\s+", " ", m.group(0)))
                i = m.end()
                continue
        if c == "\\":
            m = COMMAND.match(s, i)
            if m is None:
                i += 1
                continue
            if m.group(2) is not None:  # \% \& \_ \\ \, ...
                ch = m.group(2)
                out.append(ch if ch in "%&_#${}" else '"' if ch == '"' else " ")
                i = m.end()
                continue
            name, j = m.group(1), m.end()
            if CITE_NAME.match(name) or name in REF:
                arg, j = _arg(s, j)
                keys = ", ".join(k.strip() for k in (arg or "").split(",") if k.strip())
                out.append(f"[{keys}]" if CITE_NAME.match(name) else f"‹{keys}›")
            elif name in ("footnote", "thanks", "marginpar"):
                arg, j = _arg(s, j)
                out.append(f" (footnote: {_text(arg or '')})" if name == "footnote" else "")
            elif name in KEEP_ARG:
                arg, j = _arg(s, j)
                out.append(_text(arg or ""))
            elif name in SECOND_ARG:
                _, j = _arg(s, j)
                arg, j = _arg(s, j)
                out.append(_text(arg or ""))
            elif name in ("multirow", "multicolumn"):  # {rows}{width}{text}, {columns}{spec}{text}: the text
                _, j = _arg(s, j)
                _, j = _arg(s, j)
                arg, j = _arg(s, j)
                out.append(_text(arg or ""))
            elif name in ("begin", "end"):
                env, j = _arg(s, j)
                for _ in range(ENV_ARGS.get((env or "").rstrip("*"), 0) if name == "begin" else 0):
                    _, j = _arg(s, j)
                out.append(" ")
            elif name in WORDS:
                out.append(WORDS[name])
                if s.startswith("{}", j):
                    j += 2
            elif name in ("input", "include", "subfile", "includeonly"):
                _, j = _arg(s, j)
            elif name in ("import", "subimport"):
                _, j = _arg(s, j)
                _, j = _arg(s, j)
            elif name in ("rule", "setlength", "addtolength", "setcounter", "addtocounter"):
                lhs = re.match(r"\s*\\[A-Za-z@]+", s[j:])  # \setlength\tabcolsep{1pt}: a length without braces
                if lhs and name != "rule":
                    j += lhs.end()
                else:
                    _, j = _arg(s, j)
                _, j = _arg(s, j)
            elif name in DROP and name not in NO_ARGS or name in ("cellcolor", "rowcolor", "columncolor"):
                _, j = _arg(s, j)
            # any other command: dropped, its arguments kept as text (braces fall away below)
            i = j
            continue
        if c in "{}":
            i += 1
            continue
        out.append(" " if c == "~" or c == "\n" else c)
        i += 1
    return "".join(out)


def detex(s: str, defs: dict[str, tuple[int, str]] | None = None) -> str:
    r"""Prose as a reader sees it: the document's own macros expanded, formatting dropped, citations as [keys],
    references as ‹labels›, math kept as written (so a changed formula shows), spaces normalised.

    >>> detex(r"We train \textbf{BERT}~\cite{devlin, liu} (see Table~\ref{tab:main}); it reaches $F_1 = 91.2$\%.")
    'We train BERT [devlin, liu] (see Table ‹tab:main›); it reaches $F_1 = 91.2$%.'
    >>> detex(r"A \emph{new} {\bf idea}\footnote{Joint work, $n=2$.} --- here, ``quoted''.")
    'A new idea (footnote: Joint work, $n=2$.) — here, "quoted".'
    >>> detex(r"\rule{0pt}{2ex}\multirow{4}{*}{(A)} \begin{center}\ours\end{center}", {"ours": (0, r"\textsc{FooNet}")})
    '(A) FooNet'
    """
    s = expand_macros(s, defs)
    s = re.sub(r"\\[hv]skip\s*-?[\d.]+\s*\w+(?:\s+plus\s+-?[\d.]+\s*\w+)?(?:\s+minus\s+-?[\d.]+\s*\w+)?", " ", s)  # glue
    t = _text(s).replace("---", "—").replace("--", "–").replace("``", '"').replace("''", '"')
    t = re.sub(r"\s+", " ", t).strip()
    return re.sub(r"\s+([,.;:!?)])", r"\1", re.sub(r"\(\s+", "(", t))


# ---------------------------------------------------------------- sentences

DISPLAY = re.compile(
    r"\\begin\{(equation|align|gather|multline|eqnarray|flalign|alignat|displaymath|math|dmath|IEEEeqnarray)(\*?)\}|\\\[|(?<!\\)\$\$"
)
# floats and the like: compared on their own (tables, figures) or not prose at all
BLANKED = re.compile(
    r"\\begin\{(figure|table|wrapfigure|wraptable|SCfigure|algorithm|algorithmic|lstlisting|verbatim|minted|tikzpicture"
    r"|thebibliography|tabular|tabularx|tabular\*|longtable|filecontents|comment)(\*?)\}"
)


def _spans(text: str, opening: re.Pattern[str]) -> list[tuple[int, int]]:
    r"""Where each environment `opening` finds begins and ends (\begin{x} ... \end{x}, \[ ... \], $$ ... $$),
    outermost first, in order; one without an end is skipped. The end is looked for with str.find, and once it is
    known to be missing it is not looked for again: an unclosed environment repeated costs nothing more.

    >>> _spans(r"a \begin{figure}x\begin{tabular}y\end{tabular}\end{figure} b \begin{table} c", BLANKED)
    [(2, 58)]
    """
    out: list[tuple[int, int]] = []
    missing: dict[str, int] = {}  # closing text -> a position after which it does not occur
    for m in opening.finditer(text):
        if out and m.start() < out[-1][1]:
            continue  # inside the one before
        tok = m.group(0)
        close = "\\]" if tok == "\\[" else "$$" if tok == "$$" else "\\end{" + tok[len("\\begin{") :]
        if close in missing and m.end() >= missing[close]:
            continue
        end = text.find(close, m.end())
        if end < 0:
            missing[close] = 0
            continue
        out.append((m.start(), end + len(close)))
    return out


ABBREV = re.compile(
    r"(?:\b(?:e\.g|i\.e|et al|al|cf|vs|Fig|Figs|fig|figs|Eq|Eqs|eq|eqs|Sec|Secs|sec|Tab|Tabs|Table|Ref|Refs|resp|approx"
    r"|Dr|Prof|Mr|Ms|Mrs|No|no|St|Inc|Ltd|Co|Corp|vol|Vol|pp|ch|Ch|Thm|Def|Prop|Lem|Alg|App|Apx|w\.r\.t|a\.k\.a|viz|ca)"
    r"|\b[A-Z])\.$"
)
BOUNDARY = re.compile(r"[.!?](?:['\")\]]|'')*\s+(?=[A-Z0-9(\[`\"“]|\\[A-Za-z])")


def blank(s: str) -> str:
    """Everything but line breaks replaced by spaces: positions stay where they were."""
    return re.sub(r"[^\n]", " ", s)


@dataclass
class Sentence:
    text: str  # as plain text
    file: str
    line: int
    kind: str = "text"  # "text" or "equation"


def sentences(src: Source, start: int, end: int) -> list[Sentence]:
    """The prose between two positions of the document, sentence by sentence, with each displayed equation a unit of
    its own; floats (figures, tables, algorithms, code) are left out."""
    raw = src.text[start:end]
    for a, b in _spans(raw, BLANKED):
        raw = raw[:a] + blank(raw[a:b]) + raw[b:]
    units: list[tuple[int, str, str]] = []  # (offset, kind, latex)
    last = 0
    for a, b in _spans(raw, DISPLAY):
        units.append((last, "text", raw[last:a]))
        units.append((a, "equation", raw[a:b]))
        last = b
    units.append((last, "text", raw[last:]))
    out: list[Sentence] = []
    for off, kind, text in units:
        if kind == "equation":
            body = re.sub(r"\\label\{[^}]*\}|\\nonumber|\\notag", "", text)
            body = re.sub(r"^\\begin\{[^}]*\}|\\end\{[^}]*\}$|^\\\[|\\\]$|^\$\$|\$\$$", "", body.strip())
            body = re.sub(r"\s+", " ", expand_macros(body, src.macros)).strip()
            if body:
                out.append(Sentence(body, *src.where(start + off), kind="equation"))
            continue
        for p_off, para in _paragraphs(text):
            for s_off, sent in _split_sentences(para):
                plain = detex(sent, src.macros)
                if len(re.findall(r"\w", plain)) >= 2:
                    pos = start + off + p_off + s_off + (len(sent) - len(sent.lstrip()))
                    out.append(Sentence(plain, *src.where(pos)))
    return out


def _paragraphs(text: str) -> list[tuple[int, str]]:
    out, last = [], 0
    for m in re.finditer(r"\n[ \t]*\n\s*|\\par\b|\\item\b(?:\s*\[[^\]]*\])?", text):
        out.append((last, text[last : m.start()]))
        last = m.end()
    out.append((last, text[last:]))
    return [(o, p) for o, p in out if p.strip()]


def _split_sentences(para: str) -> list[tuple[int, str]]:
    r"""A paragraph cut at sentence ends: not after abbreviations (e.g., et al., Fig.) or initials, never inside braces
    or inline math.

    >>> [s for _, s in _split_sentences("We use BERT, e.g. for tagging. It works well! See Fig. 2 for J. Smith's plot.")]
    ['We use BERT, e.g. for tagging. ', 'It works well! ', "See Fig. 2 for J. Smith's plot."]
    """
    protected = [(m.start(), m.end()) for m in INLINE_MATH.finditer(para)]
    out, last = [], 0
    k, depth, counted = 0, 0, 0  # the next math span; brace depth up to `counted`
    for m in BOUNDARY.finditer(para):
        cut = m.end()
        depth += para.count("{", counted, m.start()) - para.count("}", counted, m.start())
        counted = m.start()
        while k < len(protected) and protected[k][1] <= m.start():
            k += 1
        if depth != 0 or (k < len(protected) and protected[k][0] < m.start()):
            continue
        before = para[max(last, m.start() - 40) : m.start() + 1]
        if before.endswith(".") and ABBREV.search(before):
            continue
        out.append((last, para[last:cut]))
        last = cut
    out.append((last, para[last:]))
    return [(o, s) for o, s in out if s.strip()]


# ---------------------------------------------------------------- the parts of a paper

HEADING = re.compile(r"\\(part|chapter|section|subsection|subsubsection)(\*?)\s*(?:\[[^\]]*\])?\s*\{")
LEVEL = {"part": 0, "chapter": 0, "section": 1, "subsection": 2, "subsubsection": 3}


@dataclass
class Section:
    level: int
    number: str  # "3.2", "A.1", "" when unnumbered
    title: str
    start: int  # the heading's position in the document
    body: int  # where its text begins
    end: int
    file: str
    line: int
    appendix: bool = False
    sentences: list[Sentence] = field(default_factory=list)

    @property
    def name(self) -> str:
        return f"{self.number} {self.title}".strip() if self.number else self.title


def document_span(src: Source) -> tuple[int, int]:
    m = re.search(r"\\begin\{document\}", src.text)
    start = m.end() if m else 0
    e = src.text.find("\\end{document}", start)
    return start, e if e >= 0 else len(src.text)


def sections(src: Source, front_skip: list[tuple[int, int]] | None = None) -> list[Section]:
    """The document's sections in order, numbered as the PDF numbers them; the text before the first heading (after
    the title and abstract) is a section of its own, untitled."""
    start, end = document_span(src)
    text = src.text
    appendix_at = min((m.start() for m in re.finditer(r"\\appendix\b|\\begin\{appendices\}", text[start:end])), default=-1)
    appendix_at = start + appendix_at if appendix_at >= 0 else end + 1
    heads = []
    for m in HEADING.finditer(text, start, end):
        close = _matching(text, m.end(), "{", "}")
        if close < 0:
            continue
        heads.append((m.start(), close + 1, LEVEL[m.group(1)], bool(m.group(2)), detex(text[m.end() : close], src.macros)))
    out: list[Section] = []
    first = heads[0][0] if heads else end
    out.append(Section(0, "", "", start, start, first, *src.where(start)))
    counters = [0, 0, 0, 0]
    for k, (pos, body, level, starred, title) in enumerate(heads):
        appendix = pos > appendix_at
        if starred:
            number = ""
        else:
            if appendix and not any(s.appendix and s.number and s.level <= level for s in out):
                counters = [0, 0, 0, 0]
            counters[level] += 1
            for deeper in range(level + 1, 4):
                counters[deeper] = 0
            top = max(1, min(level, 1))
            parts = [counters[d] for d in range(top, level + 1)]
            if appendix and parts and parts[0] > 0:
                number = ".".join([chr(ord("A") + (parts[0] - 1) % 26)] + [str(p) for p in parts[1:]])
            elif appendix:
                number = ""
            else:
                number = ".".join(str(p) for p in parts) if level else ""
        stop = heads[k + 1][0] if k + 1 < len(heads) else end
        out.append(Section(level, number, title, pos, body, stop, *src.where(pos), appendix=appendix))
    for s in out:
        last = s.body
        for a, b in sorted(front_skip or []) if s is out[0] else []:
            if last <= a < s.end:
                s.sentences += sentences(src, last, a)
                last = max(last, b)
        s.sentences += sentences(src, last, s.end)
    return out


def title(src: Source) -> str:
    m = re.search(r"\\(?:title|icmltitle|twocolumn\[\s*\\icmltitle)\s*(?:\[[^\]]*\])?\s*\{", src.text)
    if not m:
        return ""
    end = _matching(src.text, m.end(), "{", "}")
    return detex(src.text[m.end() : end], src.macros) if end > 0 else ""


def abstract(src: Source) -> tuple[int, int]:
    r"""Where the abstract's text is (\begin{abstract} or \abstract{...}); (0, 0) when the paper has none."""
    m = re.search(r"\\begin\{abstract\*?\}(.*?)\\end\{abstract\*?\}", src.text, re.S)
    if m:
        return m.start(1), m.end(1)
    m = re.search(r"\\abstract\s*\{", src.text)
    if m:
        end = _matching(src.text, m.end(), "{", "}")
        if end > 0:
            return m.end(), end
    return 0, 0


AUTHOR = re.compile(r"\\(?:author|icmlauthor|IEEEauthorblockN|authorname)\s*(?:\[[^\]]*\])?\s*\{")
NOT_A_NAME = re.compile(
    r"\b(?:universit\w*|institut\w*|college|school|department|dept|laborator\w*|lab|labs|research|inc|ltd|llc|corp"
    r"|corporation|company|centre|center|academy|faculty|google|deepmind|microsoft|meta|facebook|openai|amazon|nvidia"
    r"|apple|ibm|intel|baidu|alibaba|tencent|huawei|bytedance|anonymous|authors?|equal|contribution|correspond\w*"
    r"|email|e-mail|address|street|road|usa|china|germany|france|canada|japan|korea|uk|city|state|province"
    r"|engineering|sciences?|informatics|computing|technology|polytechnic|hospital|foundation|ai2"
    r"|mit|cmu|stanford|berkeley|harvard|princeton|oxford|cambridge|eth|epfl|inria|mila|tsinghua|peking|kaist|ucla|ucl"
    r"|nyu|toronto|montreal|zurich|zürich|tübingen|tuebingen|edinburgh|imperial|cornell|columbia|yale|caltech|ntu|nus)\b",
    re.I,
)


OUT_OF_NAMES = re.compile(
    r"\\(?:thanks|Thanks|footnote|texttt|tt|email|url|href|affiliation|institute|inst|affil|orcid|orcidID|IEEEauthorrefmark"
    r"|corref|cormark|fnref|fnmark|tnoteref|ead|orcidlink|IEEEmembership|corauth|authornote|textsuperscript)"
    r"\s*(?:\[[^\]]*\])?\s*\{(?:[^{}]|\{[^{}]*\})*\}|\\footnotemark(?:\[[^\]]*\])?|\\(?:small|footnotesize|scriptsize)\b"
)
# what separates one author from the next (or a name from what follows it)
NAME_SEPARATOR = re.compile(
    r"\\(?:quad|qquad|enspace|hfill|newline|And|AND|and)\b|\\hspace\*?\{[^}]*\}|\\hskip\s*[\d.]+\w*|\\\\(?:\[[^\]]*\])?|~{2,}|&|,|;"
    r"|(?:\\\s+){2,}"
    r"|\band\b|\n\s*\n"
)


def _name(piece: str) -> str:
    r"""A piece of an author block as a person's name, or "" when it is not one.

    >>> _name("Noam Shazeer[1]"), _name("Ed H. Chi"), _name("Engineering"), _name("Runway ML"), _name("Google Brain")
    ('Noam Shazeer', 'Ed H. Chi', '', '', '')
    """
    name = re.sub(r"\[[^\]]*\]|[*†‡§¶∗⋆♠♣♢♡\d]+", "", piece).strip(" .:()")
    words = name.split()
    if not 2 <= len(words) <= 6 or not re.search(r"[^\W\d_]", name) or "@" in name or NOT_A_NAME.search(name):
        return ""
    if any(len(w) >= 2 and w.isupper() and w.isalpha() for w in words):  # IWR, ML: a place or a company
        return ""
    return name if any(w[:1].isupper() for w in words) else ""


def authors(src: Source) -> list[str]:
    """The authors' names, in order, from \\author (any template's way of listing them), \\icmlauthor and IEEE
    blocks: in each group of authors, the names until the first affiliation or e-mail address; footnotes and marks
    left out."""
    names: list[str] = []
    for m in AUTHOR.finditer(src.text):
        end = _matching(src.text, m.end(), "{", "}")
        if end < 0:
            continue
        block = expand_macros(src.text[m.end() : end], src.macros)  # \authorskip and such
        # \texttt{...} holds addresses, or (some templates) the names themselves
        block = re.sub(r"\\(?:texttt|tt)\s*\{([^{}]*)\}", lambda m: " " if "@" in m.group(1) else m.group(1), block)
        block = OUT_OF_NAMES.sub(" ", block)
        block = re.sub(r"\$[^$]*\$|\\textsuperscript\{[^}]*\}|\^\{?[^}\s]*\}?|\\vspace\*?\{[^}]*\}", " ", block)
        for group in re.split(r"\\(?:and|And|AND)\b", block):
            for piece in NAME_SEPARATOR.split(group):
                plain = detex(piece, src.macros)
                if not plain.strip():
                    continue
                if NOT_A_NAME.search(plain) or "@" in plain:
                    break  # the group's affiliations begin
                name = _name(plain)
                if name and name not in names:
                    names.append(name)
    return names


@dataclass
class Figure:
    label: str
    caption: str
    graphics: list[str]  # file names, without folders and extensions
    file: str
    line: int

    @property
    def name(self) -> str:
        return self.label or (self.graphics[0] if self.graphics else f'"{self.caption[:50]}"')


GRAPHICS = re.compile(
    r"\\includegraphics\s*(?:\[[^\]]*\])?\s*\{([^}]+)\}|\\includesvg\s*(?:\[[^\]]*\])?\s*\{([^}]+)\}|\\input\{([^}]+\.(?:pgf|tikz))\}"
)


def _graphic_name(path: str) -> str:
    name = path.strip().replace("\\", "/").rsplit("/", 1)[-1]
    return re.sub(r"\.(?:pdf|png|jpe?g|eps|svg|pgf|tikz|gif|bmp|tiff?)$", "", name, flags=re.I)


def figures(src: Source) -> list[Figure]:
    """The paper's figures: each figure environment (subfigures inside belong to it), its caption, label and the
    graphics it shows."""
    out = []
    for m in re.finditer(r"\\begin\{(figure|wrapfigure|SCfigure)(\*?)\}", src.text):
        close = src.text.find(f"\\end{{{m.group(1)}{m.group(2)}}}", m.end())
        if close < 0:
            continue
        body = src.text[m.end() : close]
        caption = ""
        caps = list(re.finditer(r"\\caption\s*(?:\[[^\]]*\])?\s*\{", body))
        if caps:  # the figure's own caption is the last one (subfigures' come first)
            c = caps[-1]
            end = _matching(body, c.end(), "{", "}")
            caption = detex(body[c.end() : end], src.macros) if end > 0 else ""
        labels = re.findall(r"\\label\{([^}]+)\}", body)
        graphics = [_graphic_name(next(g for g in gm.groups() if g)) for gm in GRAPHICS.finditer(body)]
        out.append(Figure(labels[-1] if labels else "", caption, graphics, *src.where(m.start())))
    return out


def citations(text: str) -> list[str]:
    """The keys cited in a text, in order, each once."""
    keys: list[str] = []
    for m in CITE.finditer(text):
        keys += [k.strip() for k in m.group(2).split(",")]
    for m in MULTICITE.finditer(text):
        for g in re.findall(r"\{([^}]*)\}", m.group(1)):
            keys += [k.strip() for k in g.split(",")]
    return list(dict.fromkeys(k for k in keys if k and k != "*"))
