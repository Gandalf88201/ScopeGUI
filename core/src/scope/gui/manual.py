"""The manual that ships inside the GUI: one markdown file, shown section by section with a search box.

The text is scope/gui/manual/en.md, read with importlib.resources so that a missing package file fails loudly in a test instead of
only on another computer. Sections start at `## ` headings and are gathered under `# ` group headings (shown as captions in the
list). Rendering is done by scope.gui.manual_render.
"""
import re
from importlib import resources
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QTextBrowser, QVBoxLayout, QWidget
from scope.gui import theme
from scope.gui.manual_render import render_section

def load_text() -> str:
    """Returns the manual as markdown text."""
    return (resources.files("scope.gui") / "manual" / "en.md").read_text(encoding="utf-8")

def load_structure() -> list:
    """Splits the manual into (group, title, markdown) triples, one per `## ` heading, in order. `# ` lines name the group of the sections after them."""
    sections, group, title, body = [], "", None, []
    def close():
        if title is not None: sections.append((group, title, "\n".join(body).strip()))
    for line in load_text().splitlines():
        if line.startswith("## "): close(); title, body = line[3:].strip(), []
        elif line.startswith("# "): close(); title, body = None, []; group = line[2:].strip()
        elif title is not None: body.append(line)
    close()
    return sections

def load_sections() -> list:
    """Splits the manual into (title, markdown) pairs, one per `## ` heading, in order."""
    return [(title, body) for _, title, body in load_structure()]

def search(sections: list, query: str) -> list:
    """Returns the indices of the sections whose title or text contains every word of the query (case-insensitive)."""
    words = [w for w in re.split(r"\s+", query.lower().strip()) if w]
    return [i for i, (title, body) in enumerate(sections) if all(w in (title + " " + body).lower() for w in words)]

class ManualPage(QWidget):
    """Section list (with group captions and a search box) on the left; the selected section and Previous / Next buttons on the right."""
    def __init__(self):
        super().__init__()
        self.structure = load_structure()
        self.sections  = [(title, body) for _, title, body in self.structure]
        self.search    = QLineEdit(); self.search.setPlaceholderText("Search the manual…"); self.search.setClearButtonEnabled(True)
        self.list      = QListWidget(); self.list.setObjectName("manualtoc"); self.list.setFixedWidth(250); self.list.setFocusPolicy(Qt.NoFocus); self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff); self.list.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.view      = QTextBrowser(); self.view.setObjectName("manualview"); self.view.setOpenLinks(False); self.view.setFrameShape(QTextBrowser.NoFrame)
        self.view.document().setDocumentMargin(22); f = self.view.font(); f.setPointSize(f.pointSize() + 1); self.view.setFont(f)
        self.rows, self.heads, last = {}, {}, None                                  ## list row -> section index; group caption rows
        for i, (group, title, _) in enumerate(self.structure):
            if group != last:
                caption = QListWidgetItem(group.upper()); caption.setFlags(Qt.NoItemFlags); font = caption.font(); font.setPointSize(max(font.pointSize() - 2, 8)); font.setWeight(QFont.DemiBold); caption.setFont(font)
                self.list.addItem(caption); self.heads[self.list.count() - 1] = group; last = group
            self.list.addItem(QListWidgetItem(title)); self.rows[self.list.count() - 1] = i
        self.prev_btn, self.next_btn = QPushButton(), QPushButton()
        for button in (self.prev_btn, self.next_btn): button.setCursor(Qt.PointingHandCursor)
        self.prev_btn.clicked.connect(lambda: self.step(-1)); self.next_btn.clicked.connect(lambda: self.step(1))
        nav = QHBoxLayout(); nav.setContentsMargins(0, 0, 0, 0); nav.addWidget(self.prev_btn); nav.addStretch(1); nav.addWidget(self.next_btn)
        right = QVBoxLayout(); right.setContentsMargins(0, 0, 0, 0); right.addWidget(self.view, 1); right.addLayout(nav)
        left = QVBoxLayout(); left.setContentsMargins(0, 0, 0, 0); left.addWidget(self.search); left.addWidget(self.list, 1)
        lay = QHBoxLayout(self); lay.setSpacing(14); lay.addLayout(left); lay.addLayout(right, 1)
        self.search.textChanged.connect(self.filter); self.list.currentRowChanged.connect(self.show_row); self.view.anchorClicked.connect(self.follow)
        theme.on_change(self.restyle)
        self.list.setCurrentRow(next(iter(self.rows)))

    def visible_sections(self) -> list:
        """Indices of the sections that are shown in the list now (all of them unless a search is active)."""
        return [self.rows[r] for r in sorted(self.rows) if not self.list.item(r).isHidden()]

    def filter(self, query: str) -> None:
        keep = set(search(self.sections, query)) if query.strip() else set(range(len(self.sections)))
        for row, index in self.rows.items(): self.list.item(row).setHidden(index not in keep)
        for row, group in self.heads.items(): self.list.item(row).setHidden(not any(g == group and i in keep for i, (g, _, _) in enumerate(self.structure)))
        current = self.rows.get(self.list.currentRow())
        if current not in keep and keep: self.list.setCurrentRow(next(r for r, i in sorted(self.rows.items()) if i == min(keep)))
        self.update_nav()

    def show_row(self, row: int) -> None:
        if row not in self.rows: return
        title, body = self.sections[self.rows[row]]
        self.view.setHtml(render_section(title, body, theme.colors()))
        self.view.verticalScrollBar().setValue(0); self.update_nav()

    def update_nav(self) -> None:
        shown, here = self.visible_sections(), self.rows.get(self.list.currentRow())
        position = shown.index(here) if here in shown else -1
        for button, target in ((self.prev_btn, position - 1), (self.next_btn, position + 1)):
            ok = position >= 0 and 0 <= target < len(shown)
            button.setVisible(ok)
            if ok: button.setText(("←  " if button is self.prev_btn else "") + self.sections[shown[target]][0] + ("  →" if button is self.next_btn else ""))

    def step(self, direction: int) -> None:
        shown, here = self.visible_sections(), self.rows.get(self.list.currentRow())
        if here in shown and 0 <= shown.index(here) + direction < len(shown):
            target = shown[shown.index(here) + direction]; self.list.setCurrentRow(next(r for r, i in self.rows.items() if i == target))

    def follow(self, url: QUrl) -> None:
        """Links inside the page scroll to their heading; web links open in the browser."""
        if url.scheme() in ("http", "https"): QDesktopServices.openUrl(url)
        elif url.hasFragment() or url.toString().startswith("#"): self.view.scrollToAnchor(url.fragment() or url.toString().lstrip("#"))

    def restyle(self) -> None:
        self.show_row(self.list.currentRow())

    def show_section(self, prefix: str) -> bool:
        """Selects the first section whose title starts with the prefix (for instance '3 ·'). Returns whether one was found."""
        for row, index in self.rows.items():
            if self.sections[index][0].startswith(prefix): self.search.clear(); self.list.setCurrentRow(row); return True
        return False
