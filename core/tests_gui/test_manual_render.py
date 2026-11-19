"""The manual renderer (markdown to styled HTML) and the grouped, navigable manual page."""
import os, re
import pytest
from scope.gui import manual_render as mr, theme

C = theme.LIGHT

def test_inline_forms_and_escaping():
    out = mr.inline("**bold** and *italic* and `a < b` and [site](https://example.org) <script>alert(1)</script>", C)
    assert "<b>bold</b>" in out and "<i>italic</i>" in out and "&nbsp;a &lt; b&nbsp;" in out and 'href="https://example.org"' in out
    assert "<script>" not in out and "&lt;script&gt;" in out                                    # nothing typed in the manual can inject markup
    assert mr.inline("5 * 2 and 3 * 4", C).count("<i>") == 0                                    # a lone asterisk between spaces is not emphasis
    assert "<b>" not in mr.inline("`**not bold**`", C)                                          # code is never interpreted

def test_blocks_lists_tables_code_and_callouts():
    md = "Lead paragraph\nsecond line.\n\n### Part\n\n- one\n- two\n\n3. third\n4. fourth\n\n| A | B |\n|---|---|\n| `x` | y |\n\n```\npip install <thing>\n```\n\n> **Warning.** careful\n"
    kinds = [b[0] for b in mr.parse_blocks(md)]
    assert kinds == ["p", "h3", "ul", "ol", "table", "code", "quote"]
    assert mr.parse_blocks(md)[0][1] == "Lead paragraph second line."
    assert mr.parse_blocks(md)[3][1] == 3                                                       # a numbered list that continues after a code block keeps its number
    html = mr.render_section("Title", md, C)
    assert '<ol start="3"' in html and "pip install &lt;thing&gt;" in html and "Warning" in html and C["warn"] in html
    assert "<h1" in html and html.index("Title") < html.index("Lead paragraph")

def test_each_callout_kind_has_its_colour_and_unlabelled_quotes_are_notes():
    for word, key in (("Note", "accent"), ("Tip", "ok"), ("Warning", "warn"), ("Important", "err")):
        assert C[key] in mr.callout(f"**{word}.** text", C) and word in mr.callout(f"**{word}.** text", C)
    assert "Note" in mr.callout("plain quote", C) and "plain quote" in mr.callout("plain quote", C)

def test_tables_pad_short_rows_and_size_columns_by_content():
    html = mr.table(["Field", "Meaning"], [["a", "a much longer explanation of the field goes here"], ["b"]], C)
    shares = [int(s) for s in re.findall(r'<td width="(\d+)%"', html)]
    assert len(shares) == 2 and shares[1] > shares[0] and abs(sum(shares) - 100) <= 2          # the wide column gets more room
    assert html.count("<tr") == 3                                                               # header plus two rows, the short row padded

def test_on_this_page_only_for_sections_with_three_or_more_subheadings():
    few  = mr.render_section("T", "Lead.\n\n### One\n\ntext\n\n### Two\n\ntext\n", C)
    many = mr.render_section("T", "Lead.\n\n### One\n\ntext\n\n### Two\n\ntext\n\n### Three\n\ntext\n", C)
    assert "ON THIS PAGE" not in few and "ON THIS PAGE" in many
    assert '<a name="one">' in many and 'href="#three"' in many

def test_dark_theme_colours_are_used():
    assert theme.DARK["text"] in mr.render_section("T", "Lead.", theme.DARK) and theme.LIGHT["text"] not in mr.render_section("T", "Lead.", theme.DARK)

def test_manual_text_renders_without_leftover_markdown():
    from scope.gui import manual
    for group, title, body in manual.load_structure():
        html = mr.render_section(title, body, C)
        text = re.sub(r"<[^>]+>", "", html)
        assert "**" not in text and "```" not in text and not re.search(r"^\s*\|---", text, re.M), title     # no markup left showing
        assert "<script" not in html

def test_structure_groups_and_titles():
    from scope.gui import manual
    groups = [g for g, _, _ in manual.load_structure()]
    assert groups[0] == "Getting started" and "The six steps" in groups and groups[-1] == "Reference"
    assert [t for t, _ in manual.load_sections()][:2] == ["Welcome", "Install and start"]

def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])

def test_page_groups_captions_previous_next_and_search():
    qapp(); from scope.gui import manual
    page = manual.ManualPage()
    captions = [page.list.item(r).text() for r in page.heads]
    assert captions == ["GETTING STARTED", "THE SIX STEPS", "REFERENCE"]
    assert not page.list.item(next(iter(page.heads))).flags() & page.list.item(1).flags().__class__.ItemIsSelectable            # captions cannot be selected
    assert page.show_section("Welcome") and not page.prev_btn.isVisibleTo(page) and "Install and start" in page.next_btn.text()
    page.next_btn.click(); assert "Install and start" in page.view.toPlainText()[:30] and "Welcome" in page.prev_btn.text()
    assert page.show_section("6 ·") and "Local vs cluster" in page.next_btn.text() and "5 · Cluster" in page.prev_btn.text()
    page.search.setText("TMPDIR")
    shown = [page.sections[i][0] for i in page.visible_sections()]
    assert shown and all("TMPDIR" in (t + dict(page.sections)[t]) for t in shown)
    assert page.list.item(0).isHidden() and page.list.item(next(iter(page.heads))).isHidden()      # a group with no match disappears
    page.search.setText(""); assert len(page.visible_sections()) == len(page.sections)

def test_links_inside_a_section_scroll_and_web_links_open_the_browser(monkeypatch):
    qapp(); from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices
    from scope.gui import manual
    page = manual.ManualPage(); page.show_section("5 ·"); page.resize(1000, 500); page.show()
    opened = []; monkeypatch.setattr(QDesktopServices, "openUrl", staticmethod(lambda url: opened.append(url.toString()) or True))
    page.follow(QUrl("https://example.org/x")); assert opened == ["https://example.org/x"]
    page.follow(QUrl("#the-three-lights")); assert page.view.verticalScrollBar().value() > 0      # jumped down to the heading
