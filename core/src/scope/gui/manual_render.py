"""Turns the manual's markdown into styled HTML for a Qt text browser (no Qt imports, so it is easy to test).

Qt's rich text understands only a small part of HTML and CSS, so the page is built from what it does draw reliably: tables with
background colours (for the callouts, the code blocks and the data tables), spans with a background (inline code), and plain
headings, paragraphs and lists. Supported markdown: `###` and `####` headings, paragraphs, bullet and numbered lists, pipe tables,
fenced code, `>` callouts (**Note.** / **Tip.** / **Warning.** / **Important.**), and the inline forms `code`, **bold**, *italic*
and [links](url).
"""
import html, re

MONO = "Menlo, Consolas, 'DejaVu Sans Mono', monospace"
CALLOUTS = {"note": ("Note", "accent"), "tip": ("Tip", "ok"), "warning": ("Warning", "warn"), "important": ("Important", "err")}

def mix(first: str, second: str, share: float) -> str:
    """Returns the colour `share` of the way from `first` to `second` (hex strings such as '#2f6fed')."""
    a, b = [int(first.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)], [int(second.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
    return "#" + "".join(f"{round(x + (y - x) * share):02x}" for x, y in zip(a, b))

def anchor(text: str) -> str:
    """Anchor name of a heading: lower case letters and digits joined by dashes."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")

def inline(text: str, colors: dict) -> str:
    """Converts the inline markdown of one piece of text to HTML. Everything else is escaped. Code spans are set aside first, so bold or italic text may contain code."""
    code_bg, code_fg = mix(colors["alt"], colors["text"], 0.06), mix(colors["accent"], colors["text"], 0.35)
    spans = []
    def keep(match) -> str:
        spans.append(f'<span style="font-family:{MONO}; font-size:12px; background-color:{code_bg}; color:{code_fg};">&nbsp;{html.escape(match.group(1))}&nbsp;</span>')
        return f"\x00{len(spans) - 1}\x00"
    text = html.escape(re.sub(r"`([^`]+)`", keep, text), quote=False)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<![*\w])\*(?!\s)(.+?)(?<!\s)\*(?![*\w])", r"<i>\1</i>", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", lambda m: f'<a href="{m.group(2)}" style="color:{colors["accent"]};">{m.group(1)}</a>', text)
    return re.sub(r"\x00(\d+)\x00", lambda m: spans[int(m.group(1))], text)

def parse_blocks(markdown: str) -> list:
    """Splits markdown into blocks: ('h3'|'h4', text), ('p', text), ('ul'|'ol', start, [items]), ('table', header, rows), ('code', text), ('quote', text)."""
    lines, blocks, para, i = markdown.splitlines(), [], [], 0
    def flush():
        if para: blocks.append(("p", " ".join(s.strip() for s in para))); para.clear()
    while i < len(lines):
        line = lines[i]; stripped = line.strip()
        if stripped.startswith("```"):                                                    ## fenced code
            flush(); i += 1; code = []
            while i < len(lines) and not lines[i].strip().startswith("```"): code.append(lines[i]); i += 1
            blocks.append(("code", "\n".join(code))); i += 1; continue
        if not stripped: flush(); i += 1; continue
        m = re.match(r"^(#{3,4})\s+(.*)$", stripped)
        if m: flush(); blocks.append(("h" + str(len(m.group(1))), m.group(2).strip())); i += 1; continue
        if stripped.startswith("|") and i + 1 < len(lines) and re.match(r"^\|[\s:|-]+\|?\s*$", lines[i + 1].strip()):
            flush(); cells = lambda s: [c.strip() for c in s.strip().strip("|").split("|")]
            header, rows = cells(stripped), []; i += 2
            while i < len(lines) and lines[i].strip().startswith("|"): rows.append(cells(lines[i])); i += 1
            blocks.append(("table", header, rows)); continue
        if stripped.startswith(">"):
            flush(); quote = []
            while i < len(lines) and lines[i].strip().startswith(">"): quote.append(lines[i].strip()[1:].strip()); i += 1
            blocks.append(("quote", " ".join(q for q in quote if q))); continue
        m = re.match(r"^(\s*)([-*]|\d+\.)\s+(.*)$", line)
        if m:
            flush(); ordered = m.group(2)[0].isdigit(); start = int(m.group(2)[:-1]) if ordered else 1; items = []
            while i < len(lines):
                n = re.match(r"^(\s*)([-*]|\d+\.)\s+(.*)$", lines[i])
                if n and n.group(2)[0].isdigit() == ordered: items.append(n.group(3).strip()); i += 1
                elif lines[i].startswith("  ") and lines[i].strip() and items: items[-1] += " " + lines[i].strip(); i += 1      ## a wrapped line of the item
                else: break
            blocks.append(("ol" if ordered else "ul", start, items)); continue
        para.append(line); i += 1
    flush()
    return blocks

def callout(text: str, colors: dict) -> str:
    """A coloured box with a bar on the left. The kind comes from the first bold word ('**Note.**', '**Warning.**', ...); no tag means a note."""
    m = re.match(r"^\*\*(\w+)\.?\*\*\s*(.*)$", text); kind, body = "note", text
    if m and m.group(1).lower() in CALLOUTS: kind, body = m.group(1).lower(), m.group(2)
    label, key = CALLOUTS[kind]; bar = colors[key]; background = mix(colors["base"], bar, 0.10)
    return (f'<table width="100%" cellspacing="0" cellpadding="0" style="margin-top:12px; margin-bottom:12px;"><tr>'
            f'<td width="4" bgcolor="{bar}"></td>'
            f'<td bgcolor="{background}" style="padding:10px 14px;"><span style="color:{bar}; font-weight:700;">{label}</span>&nbsp;&nbsp;{inline(body, colors)}</td></tr></table>')

def table(header: list, rows: list, colors: dict) -> str:
    """A data table: shaded header, light stripes, generous cell padding."""
    head_bg, stripe = mix(colors["alt"], colors["text"], 0.05), mix(colors["base"], colors["alt"], 0.55)
    weights = [min(max([len(re.sub(r"[`*]", "", h))] + [len(re.sub(r"[`*]", "", r[i])) for r in rows if i < len(r)]), 55) + 6 for i, h in enumerate(header)]
    shares  = [round(100 * w / sum(weights)) for w in weights]                              ## column widths follow the length of their content
    out = ['<table width="100%" cellspacing="0" cellpadding="8" style="margin-top:10px; margin-bottom:14px;">', f'<tr bgcolor="{head_bg}">']
    out += [f'<td width="{shares[i]}%"><b style="color:{colors["sub"]}; font-size:12px;">{inline(h.upper(), colors)}</b></td>' for i, h in enumerate(header)]
    out.append("</tr>")
    for n, row in enumerate(rows):
        out.append(f'<tr bgcolor="{stripe if n % 2 else colors["base"]}">' + "".join(f"<td>{inline(c, colors)}</td>" for c in row + [""] * (len(header) - len(row))) + "</tr>")
    out.append("</table>")
    return "".join(out)

def code_block(text: str, colors: dict) -> str:
    background = mix(colors["alt"], colors["text"], 0.04)
    return (f'<table width="100%" cellspacing="0" cellpadding="0" style="margin-top:10px; margin-bottom:14px;"><tr><td bgcolor="{background}" style="padding:10px 14px;">'
            f'<pre style="margin:0; white-space:pre-wrap; font-family:{MONO}; font-size:12px; color:{colors["text"]};">{html.escape(text)}</pre></td></tr></table>')

def render_section(title: str, markdown: str, colors: dict) -> str:
    """Returns the HTML of one manual section: a title with an accent rule, a larger lead paragraph, an 'On this page' list when the
    section has three or more `###` headings, then the body."""
    blocks, text, sub, accent = parse_blocks(markdown), colors["text"], colors["sub"], colors["accent"]
    out = [f'<h1 style="font-size:27px; font-weight:700; color:{text}; margin-top:2px; margin-bottom:6px;">{html.escape(title)}</h1>',
           f'<table cellspacing="0" cellpadding="0" style="margin-bottom:16px;"><tr><td width="64" height="3" bgcolor="{accent}" style="font-size:1px; line-height:1px;">&nbsp;</td></tr></table>']
    toc = [(anchor(b[1]), b[1]) for b in blocks if b[0] == "h3"]
    lead_done, toc_done = False, len(toc) < 3
    for b in blocks:
        kind = b[0]
        if kind == "p":
            size, color = ("16px", sub) if not lead_done else ("14px", text); lead_done = True
            out.append(f'<p style="font-size:{size}; color:{color}; line-height:150%; margin-top:8px; margin-bottom:10px;">{inline(b[1], colors)}</p>')
            if not toc_done:
                links = "".join(f'<tr><td style="padding:2px 0;"><a href="#{a}" style="color:{accent}; text-decoration:none;">{html.escape(t)}</a></td></tr>' for a, t in toc)
                out.append(f'<table cellspacing="0" cellpadding="0" style="margin-top:14px; margin-bottom:14px;"><tr><td style="padding-bottom:6px;"><b style="color:{sub}; font-size:12px;">ON THIS PAGE</b></td></tr>{links}</table>'); toc_done = True
        elif kind == "h3":
            out.append(f'<a name="{anchor(b[1])}"></a><h3 style="font-size:19px; font-weight:600; color:{text}; margin-top:26px; margin-bottom:6px;">{inline(b[1], colors)}</h3>')
        elif kind == "h4":
            out.append(f'<h4 style="font-size:15px; font-weight:700; color:{text}; margin-top:16px; margin-bottom:4px;">{inline(b[1], colors)}</h4>')
        elif kind in ("ul", "ol"):
            tag = f'<{kind} start="{b[1]}"' if kind == "ol" and b[1] != 1 else f"<{kind}"
            out.append(f'{tag} style="font-size:14px; color:{text}; margin-top:4px; margin-bottom:12px;">' + "".join(f'<li style="margin-top:4px; margin-bottom:4px; line-height:145%;">{inline(i, colors)}</li>' for i in b[2]) + f"</{kind}>")
        elif kind == "table": out.append(table(b[1], b[2], colors))
        elif kind == "code": out.append(code_block(b[1], colors))
        elif kind == "quote": out.append(callout(b[1], colors))
    return "".join(out)
