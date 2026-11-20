"""The review table: every input file as it will run (job, type, states, what it waits for, processors, queue, whether it submits) with
what needs a look, shown where Run is pressed (Run here, Cluster) and from the Pipeline page. The rows come from backend.review_rows."""
from PySide6.QtGui     import QBrush, QColor
from PySide6.QtWidgets import QAbstractItemView, QDialog, QHBoxLayout, QHeaderView, QLabel, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout
from scope.gui import theme

COLUMNS = ["File", "Job", "Branch · sources", "Software · type", "Reads → writes", "Waits for", "Procs", "Queue", "Submits?", "Check"]
MARK    = {"ok": "✓", "warn": "!", "err": "✗"}

class ReviewTable(QTableWidget):
    """Read-only table of backend.ReviewRow. summary() says, in one line, how many jobs need a look."""
    def __init__(self):
        super().__init__(0, len(COLUMNS)); self.setHorizontalHeaderLabels(COLUMNS); self.rows = []
        self.setEditTriggers(QAbstractItemView.NoEditTriggers); self.setSelectionBehavior(QAbstractItemView.SelectRows); self.verticalHeader().hide(); self.setWordWrap(False)
        hh = self.horizontalHeader(); [hh.setSectionResizeMode(i, QHeaderView.ResizeToContents) for i in range(len(COLUMNS) - 1)]; hh.setSectionResizeMode(len(COLUMNS) - 1, QHeaderView.Stretch)
        self.setToolTip("Every input file as it will run. Hover over a Check cell for all its messages.")

    def show_rows(self, rows: list) -> None:
        self.rows = list(rows); c = theme.colors(); colour = {"ok": c["ok"], "warn": c["warn"], "err": c["err"]}
        self.setRowCount(len(rows))
        for i, r in enumerate(rows):
            check = f"{MARK[r.level]} " + (r.problems[0] if r.problems else "ready")
            cells = [r.file, r.job, r.where, r.kind, r.states, r.waits_for, r.procs, r.queue, r.submits, check]
            for j, text in enumerate(cells):
                it = QTableWidgetItem(text)
                if j == len(cells) - 1: it.setForeground(QBrush(QColor(colour[r.level]))); it.setToolTip("\n\n".join(r.problems) or "Nothing to report.")
                if j == 8 and text.startswith("YES"): it.setForeground(QBrush(QColor(c["warn"])))
                self.setItem(i, j, it)

    def summary(self) -> str:
        if not self.rows: return "No input files yet."
        bad, look = sum(r.level == "err" for r in self.rows), sum(r.level == "warn" for r in self.rows)
        submit = sum(r.submits.startswith("YES") for r in self.rows)
        parts = [f"{len(self.rows)} job(s)"] + ([f"{bad} will not run as meant"] if bad else []) + ([f"{look} to look at"] if look else []) + ([f"{submit} submit to the scheduler"] if submit else [])
        return ", ".join(parts) + "." + ("" if bad or look else " Ready.")

    @property
    def level(self) -> str:
        return "err" if any(r.level == "err" for r in self.rows) else ("warn" if any(r.level == "warn" for r in self.rows) else "ok")

class ReviewDialog(QDialog):
    """The review table in its own window (Pipeline page: Review…)."""
    def __init__(self, parent, rows: list, where: str):
        super().__init__(parent); self.setWindowTitle("Review before running"); theme.fit(self, 1100, 420)
        self.table = ReviewTable(); self.table.show_rows(rows)
        head = QLabel(f"{where}  {self.table.summary()}"); head.setWordWrap(True)
        close = QPushButton("Close"); close.clicked.connect(self.accept)
        row = QHBoxLayout(); row.addStretch(1); row.addWidget(close)
        lay = QVBoxLayout(self); lay.addWidget(head); lay.addWidget(self.table, 1); lay.addLayout(row)
