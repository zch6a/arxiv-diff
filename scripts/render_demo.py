"""docs/demo.png: arxiv-diff's real, coloured terminal output on the example paper's two versions, drawn as a terminal window.
The output is captured as text (FORCE_COLOR), turned into HTML and rendered with headless Chrome: nothing on the
screen is captured.

    uv run python scripts/render_demo.py [path-to-chrome]

Nothing is sent anywhere.
"""

import html
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHROME = sys.argv[1] if len(sys.argv) > 1 else r"C:\Program Files\Google\Chrome\Application\chrome.exe"
COLORS = {
    "1": "#e6edf3;font-weight:700",
    "31": "#ff7b72",
    "9": "#ff7b72;text-decoration:line-through",
    "33": "#e3b341",
    "32": "#7ee787",
    "2": "#8b949e",
}

env = dict(os.environ, PYTHONIOENCODING="utf-8")
out = subprocess.run(
    ["uv", "run", "arxiv-diff", "examples/v1", "examples/v2", "--color", "always"],
    cwd=ROOT,
    env=env,
    capture_output=True,
    text=True,
    encoding="utf-8",
).stdout
out = out.rstrip()


def to_html(s: str) -> str:
    parts, pos, style = [], 0, None
    for m in re.finditer(r"\x1b\[([\d;]*)m", s):
        text = html.escape(s[pos : m.start()])
        parts.append(f'<span style="color:{style}">{text}</span>' if style else text)
        style = COLORS.get(m.group(1)) if m.group(1) not in ("0", "") else None
        pos = m.end()
    parts.append(html.escape(s[pos:]))
    return "".join(parts)


lines = out.count("\n") + 2
height = 140 + lines * 21
page = f"""<!doctype html><html><head><meta charset="utf-8"><style>
html,body{{margin:0;background:#0b0d11}}
.t{{margin:24px;background:#0d1117;border:1px solid #30363d;border-radius:12px;overflow:hidden;box-shadow:0 20px 60px rgba(0,0,0,.5)}}
.b{{display:flex;gap:7px;padding:11px 14px;background:#161b22;border-bottom:1px solid #30363d;align-items:center}}
.b i{{width:12px;height:12px;border-radius:50%;display:inline-block}} .b span{{margin-left:10px;color:#8b949e;font:600 13px 'Segoe UI',sans-serif}}
pre{{margin:0;padding:16px 18px;font:13.5px/1.55 Consolas,'Cascadia Mono',monospace;color:#c9d1d9;white-space:pre}}
</style></head><body><div class="t"><div class="b"><i style="background:#ff5f57"></i><i style="background:#febc2e"></i>
<i style="background:#28c840"></i><span>arxiv-diff examples/v1 examples/v2</span></div>
<pre><span style="color:#7ee787">$</span> arxiv-diff examples/v1 examples/v2
{to_html(out)}</pre></div></body></html>"""
with tempfile.TemporaryDirectory() as tmp:
    page_path = Path(tmp) / "demo.html"
    page_path.write_text(page, encoding="utf-8")
    target = ROOT / "docs" / "demo.png"
    subprocess.run(
        [
            CHROME,
            "--headless=new",
            "--disable-gpu",
            "--no-proxy-server",
            "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1",
            "--hide-scrollbars",
            f"--window-size=1500,{height}",
            f"--screenshot={target}",
            page_path.as_uri(),
        ],
        check=True,
        capture_output=True,
    )
print(f"wrote {target}")
