"""The manual that ships inside the GUI: one markdown file, shown section by section with a search box.

The text is scope/gui/manual/en.md, read with importlib.resources so that a missing package file fails loudly in
a test instead of only on another computer. Sections start at `## ` headings.
"""
import re
from importlib import resources
from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QListWidget, QListWidgetItem, QTextBrowser, QVBoxLayout, QWidget
from scope.gui import theme

def load_text() -> str:
    """Returns the manual as markdown text."""
    return (resources.files("scope.gui") / "manual" / "en.md").read_text(encoding="utf-8")

def load_sections() -> list:
    """Splits the manual into (title, markdown) pairs, one per `## ` heading, in order. Text before the first heading is dropped."""
    sections, title, body = [], None, []
    for line in load_text().splitlines():
        if line.startswith("## "):
            if title is not None: sections.append((title, "\n".join(body).strip()))
            title, body = line[3:].strip(), []
        elif title is not None: body.append(line)
    if title is not None: sections.append((title, "\n".join(body).strip()))
    return sections

def search(sections: list, query: str) -> list:
    """Returns the indices of the sections whose title or text contains every word of the query (case-insensitive)."""
    words = [w for w in re.split(r"\s+", query.lower().strip()) if w]
    return [i for i, (title, body) in enumerate(sections) if all(w in (title + " " + body).lower() for w in words)]

class ManualPage(QWidget):
    """Section list with a search box on the left and the selected section on the right."""
    def __init__(self):
        super().__init__()
        self.sections = load_sections()
        self.search   = QLineEdit(); self.search.setPlaceholderText("Search the manual…"); self.search.setClearButtonEnabled(True)
        self.list     = QListWidget(); self.list.setMaximumWidth(250)
        self.view     = QTextBrowser(); self.view.setOpenExternalLinks(True); f = self.view.font(); f.setPointSize(f.pointSize() + 1); self.view.setFont(f)
        for title, _ in self.sections: self.list.addItem(QListWidgetItem(title))
        left = QVBoxLayout(); left.addWidget(self.search); left.addWidget(self.list, 1)
        lay  = QHBoxLayout(self); lay.addLayout(left); lay.addWidget(self.view, 1)
        self.search.textChanged.connect(self.filter); self.list.currentRowChanged.connect(self.show_row)
        theme.on_change(self.restyle)
        self.list.setCurrentRow(0)

    def filter(self, query: str) -> None:
        keep = set(search(self.sections, query)) if query.strip() else set(range(len(self.sections)))
        for i in range(self.list.count()): self.list.item(i).setHidden(i not in keep)
        current = self.list.currentRow()
        if current not in keep and keep: self.list.setCurrentRow(min(keep))

    def show_row(self, row: int) -> None:
        if row < 0 or row >= len(self.sections): return
        c = theme.colors()
        self.view.document().setDefaultStyleSheet(f"p, li {{ margin-top: 5px; margin-bottom: 5px; }} h2 {{ color: {c['text']}; margin-bottom: 8px; }} th {{ background: {c['alt']}; }} td, th {{ padding: 5px 9px; }} code {{ background: {c['alt']}; }} a {{ color: {c['accent']}; }}")
        title, body = self.sections[row]
        self.view.setMarkdown(f"## {title}\n\n{body}")

    def restyle(self) -> None:
        self.show_row(self.list.currentRow())

    def show_section(self, prefix: str) -> bool:
        """Selects the first section whose title starts with the prefix (for instance '3 ·'). Returns whether one was found."""
        for i, (title, _) in enumerate(self.sections):
            if title.startswith(prefix): self.search.clear(); self.list.setCurrentRow(i); return True
        return False
