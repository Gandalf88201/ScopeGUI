"""Form to create or edit a Scope input file, with a live preview and validation by SCOPE's own functions."""
import os
from PySide6.QtGui     import QFont
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QScrollArea, QSpinBox, QTabWidget, QVBoxLayout, QWidget, QWidget)
from scope.gui import backend, theme
from scope.gui.theme import set_kind

DEFAULTS = {"branch": "demo", "workflow": "*", "job": "opt", "requisites": "", "constrains": "self", "software": "g16", "comp_type": "opt", "functional": "b3lyp", "basis": "6-31g*", "procs": 4, "want_submit": False, "queue": "",
            "istate": "", "fstate": ""}

class LinkDialog(QDialog):
    """Shows what linking job A before job B changes in B's input file (backend.link_jobs), line by line, before anything is written."""
    def __init__(self, parent: QWidget, a: str, b: str, change: "backend.Link"):
        super().__init__(parent); self.setWindowTitle(f"'{b}' waits for '{a}'"); theme.fit(self, 760, 460)
        head = QLabel("\n".join(change.notes)); head.setWordWrap(True)
        where = QLabel(f"Settings that change in {change.path}  (~ changed, + added, − removed):"); where.setObjectName("pagesub"); where.setWordWrap(True)
        mono = QFont("Menlo"); mono.setStyleHint(QFont.Monospace)
        self.diff = QPlainTextEdit("\n".join(change.diff) or "(no change)"); self.diff.setReadOnly(True); self.diff.setFont(mono)
        check = QLabel("Nothing has been written yet. Check the change, then save; nothing runs until you press Run."); check.setObjectName("pagesub"); check.setWordWrap(True)
        save, cancel = QPushButton("Save the change"), QPushButton("Cancel"); save.setProperty("primary", True); save.clicked.connect(self.accept); cancel.clicked.connect(self.reject)
        row = QHBoxLayout(); row.addStretch(1); row.addWidget(cancel); row.addWidget(save)
        lay = QVBoxLayout(self); lay.addWidget(head); lay.addWidget(where); lay.addWidget(self.diff, 1); lay.addWidget(check); lay.addLayout(row)

class ChainDialog(QDialog):
    """Links several jobs in a sequence (each waits for the one before it and starts from its result). The order can be changed by
    dragging in the list; the preview shows every file that changes, and nothing is written until Save."""
    def __init__(self, parent: QWidget, chain: list, reports: list, sources: "list | None"=None):
        from PySide6.QtWidgets import QAbstractItemView, QListWidget, QListWidgetItem
        from PySide6.QtCore import Qt
        super().__init__(parent); self.setWindowTitle("Chain jobs"); theme.fit(self, 860, 620)
        self.reports, self.sources, self.links = reports, sources, []
        self.order = QListWidget(); self.order.setDragDropMode(QAbstractItemView.InternalMove); self.order.setMaximumHeight(150)
        for r in chain:
            it = QListWidgetItem(f"{r.job}   ·  branch {r.branch} · sources {r.workflow_label} · {r.software} {r.comp_type} · writes '{r.fstate}'"); it.setData(Qt.UserRole, r); self.order.addItem(it)
        self.order.model().rowsMoved.connect(self.refresh)
        intro = QLabel("Each job waits for the one above it and starts from its result. Drag the jobs to change the order."); intro.setWordWrap(True)
        mono = QFont("Menlo"); mono.setStyleHint(QFont.Monospace)
        self.preview = QPlainTextEdit(); self.preview.setReadOnly(True); self.preview.setFont(mono)
        self.status = QLabel(); self.status.setWordWrap(True)
        self.save_btn, cancel = QPushButton("Save the changes"), QPushButton("Cancel"); self.save_btn.setProperty("primary", True)
        self.save_btn.clicked.connect(self.accept); cancel.clicked.connect(self.reject)
        row = QHBoxLayout(); row.addWidget(self.status, 1); row.addWidget(cancel); row.addWidget(self.save_btn)
        lay = QVBoxLayout(self); lay.addWidget(intro); lay.addWidget(self.order); lay.addWidget(QLabel("Settings that change (~ changed, + added, − removed). Nothing is written before Save; nothing runs before Run:")); lay.addWidget(self.preview, 1); lay.addLayout(row)
        self.refresh()

    def chain(self) -> list:
        from PySide6.QtCore import Qt
        return [self.order.item(i).data(Qt.UserRole) for i in range(self.order.count())]

    def refresh(self, *args) -> None:
        try: self.links = backend.link_chain(self.chain(), self.reports, self.sources)
        except ValueError as exc:
            self.links = []; self.preview.setPlainText(""); self.status.setText(f"Cannot chain in this order: {exc}"); set_kind(self.status, "err"); self.save_btn.setEnabled(False); return
        blocks = [f"## {os.path.basename(l.path)}\n" + "\n".join(l.notes) + "\n" + "\n".join(l.diff) for l in self.links]
        self.preview.setPlainText("\n\n".join(blocks) or "Already chained in this order: nothing to change.")
        self.status.setText(f"{len(self.links)} file(s) will change." if self.links else "Nothing to change."); set_kind(self.status, "ok" if self.links else "")
        self.save_btn.setEnabled(bool(self.links))

class InputEditor(QDialog):
    """Dialog with one field per common setting, a box for any other setting, and the resulting file as text.

    The Initial and Final state fields follow the requisites (istate = the fstate of the job waited for, found among `reports`) until the
    user types in them; from then on they keep what was typed.

    Attributes:
        saved_path (str):    Path of the file written, or '' if the dialog was cancelled.
    """
    def __init__(self, parent: QWidget=None, start_dir: str="", form: dict=None, extras: dict=None, filename: str="", reports: list=None, after: str=""):
        super().__init__(parent)
        self.setWindowTitle("Scope input file"); theme.fit(self, 1000, 680)
        self.start_dir, self.saved_path, self.text = start_dir or os.path.expanduser("~"), "", ""
        self.reports = list(reports or [])
        values = {**DEFAULTS, **(form or {})}
        self.branch,    self.workflow,   self.job        = QLineEdit(values["branch"]), QLineEdit(values["workflow"]), QLineEdit(values["job"])
        self.requisites, self.constrains                 = QLineEdit(values["requisites"]), QLineEdit(values["constrains"])
        existing = bool(filename)                                         ## an existing file: show what SCOPE will do with it, change nothing by itself
        if after: self.setWindowTitle(f"New job after '{after}'")
        self.istate = QLineEdit(values["istate"] or ("initial" if existing else ""))
        self.fstate = QLineEdit(values["fstate"] or (values["job"] if existing else ""))
        self.auto = {"istate": not existing, "fstate": not existing}
        self.use_result = QPushButton("Start from the requisite's result"); self.use_result.clicked.connect(self.apply_suggestion); self.use_result.hide()
        self.istate.setToolTip("The State this job starts from (its geometry). 'initial' is the imported structure. To start from the result of an earlier job, give the state that job writes (its fstate), for instance 'opt'.")
        self.fstate.setToolTip("The State this job writes its results into. A geometry job (opt, ts) usually writes a new state named after the job. A freq, scf or td job usually writes into the state it read, so its frequencies and energy sit on that geometry.")
        self.states_note = QLabel(); self.states_note.setWordWrap(True); self.states_note.setObjectName("pagesub")
        self.software, self.comp_type                    = QComboBox(), QComboBox()
        self.functional, self.basis, self.queue          = QLineEdit(values["functional"]), QLineEdit(values["basis"]), QLineEdit(values["queue"])
        self.procs, self.submit                          = QSpinBox(), QCheckBox("Submit jobs to the scheduler (want_submit)")
        self.procs.setRange(1, 4096); self.procs.setValue(int(values["procs"])); self.submit.setChecked(bool(values["want_submit"]))
        self.software.addItems(list(backend.SOFTWARE_TYPES)); self.software.setCurrentText(values["software"])
        self.fill_types(values["comp_type"])
        self.branch.setToolTip("Folder name inside the system's Computations folder. Jobs of one pipeline share a branch.")
        self.workflow.setToolTip("Which sources of the system to run: '*' for all, a name, a pattern such as 'water*', or several separated by commas.")
        self.requisites.setToolTip("Jobs that must be finished and good BEFORE this one starts (names, separated by commas). Leave empty for the first job of a pipeline; a 'freq' job after an optimization needs 'opt'. Never this job's own name.\n"
                                   "Requisites only decide WHEN the job starts. Which geometry it uses is the Initial state.")
        self.requisites.setPlaceholderText("empty = starts right away; e.g. opt")
        self.constrains.setToolTip("Jobs that block this one once they are finished. 'self' prevents running the same job twice.")
        self.queue.setToolTip("Optional. On a cluster it must match a queue of the environment exactly.")
        self.submit.setToolTip("Unchecked is written as want_submit = False. SCOPE assumes True when the line is missing.")
        form = QFormLayout()
        for label, widget in (("Branch", self.branch), ("Workflow (sources)", self.workflow), ("Job name", self.job), ("Requisites (when)", self.requisites), ("Initial state (istate)", self.istate), ("Final state (fstate)", self.fstate)): form.addRow(label, widget)
        form.addRow("", self.states_note); form.addRow("", self.use_result)
        for label, widget in (("Constrains", self.constrains), ("Software", self.software), ("Computation type", self.comp_type), ("Functional", self.functional)): form.addRow(label, widget)
        form.addRow("Basis set (Gaussian)", self.basis); form.addRow("Processors", self.procs); form.addRow("Queue (optional)", self.queue); form.addRow("", self.submit)
        self.extras = {name: QPlainTextEdit() for name in backend.SECTIONS}
        tabs = QTabWidget()
        for name in ("qc_data", "job_data", "options", "environment"):
            self.extras[name].setPlainText((extras or {}).get(name, "")); self.extras[name].setPlaceholderText("key = value, one per line"); self.extras[name].setMaximumHeight(110)
            tabs.addTab(self.extras[name], f"&&{name}")           ## '&&' is a literal ampersand in a Qt label ('&' alone makes the next letter a shortcut)
        mono = QFont("Menlo"); mono.setStyleHint(QFont.Monospace)
        self.preview = QPlainTextEdit(); self.preview.setReadOnly(True); self.preview.setFont(mono)
        self.status  = QLabel(); self.status.setWordWrap(True)
        self.save_btn, cancel = QPushButton("Save…"), QPushButton("Cancel")
        self.save_btn.clicked.connect(self.save); cancel.clicked.connect(self.reject)
        note = QLabel("Other settings go in the tabs (for instance pseudo, mix_beta or save_wf). Comments of an existing file are not kept.")
        note.setWordWrap(True)
        left, right, buttons = QVBoxLayout(), QVBoxLayout(), QHBoxLayout()
        left.addLayout(form); left.addWidget(QLabel("Other settings")); left.addWidget(tabs); left.addWidget(note); left.addStretch(1)
        right.addWidget(QLabel("File that will be written")); right.addWidget(self.preview, 1); right.addWidget(self.status)
        buttons.addStretch(1); buttons.addWidget(cancel); buttons.addWidget(self.save_btn)
        form_box = QWidget(); form_box.setLayout(left)                    ## the form scrolls on a short screen; preview and Save stay in view
        form_area = QScrollArea(); form_area.setWidgetResizable(True); form_area.setFrameShape(QFrame.NoFrame); form_area.setWidget(form_box)
        body = QHBoxLayout(); body.addWidget(form_area, 1); body.addLayout(right, 1)
        lay = QVBoxLayout(self); lay.addLayout(body, 1); lay.addLayout(buttons)
        self.filename = filename
        for w in (self.branch, self.workflow, self.job, self.requisites, self.constrains, self.functional, self.basis, self.queue): w.textChanged.connect(self.refresh)
        for key, w in (("istate", self.istate), ("fstate", self.fstate)):          ## typed by the user: stop following the suggestion BEFORE refreshing
            w.textEdited.connect(lambda _=None, key=key: (self.auto.__setitem__(key, False), self.refresh()))
        for w in self.extras.values(): w.textChanged.connect(self.refresh)
        self.procs.valueChanged.connect(self.refresh); self.submit.toggled.connect(self.refresh); self.comp_type.currentTextChanged.connect(self.refresh)
        self.software.currentTextChanged.connect(self.on_software)
        self.on_software()

    def fill_types(self, current: str="") -> None:
        self.comp_type.blockSignals(True); self.comp_type.clear(); self.comp_type.addItems(backend.SOFTWARE_TYPES[self.software.currentText()])
        if current in backend.SOFTWARE_TYPES[self.software.currentText()]: self.comp_type.setCurrentText(current)
        self.comp_type.blockSignals(False)

    def on_software(self) -> None:
        self.fill_types(self.comp_type.currentText())
        self.basis.setEnabled(self.software.currentText() == "g16")
        self.refresh()

    def values(self) -> dict:
        return {"branch": self.branch.text(), "workflow": self.workflow.text(), "job": self.job.text(), "requisites": self.requisites.text(), "constrains": self.constrains.text(), "software": self.software.currentText(), "comp_type": self.comp_type.currentText(),
                "functional": self.functional.text(), "basis": self.basis.text(), "procs": self.procs.value(), "want_submit": self.submit.isChecked(), "queue": self.queue.text(), "extras": {n: w.toPlainText() for n, w in self.extras.items()},
                "istate": self.istate.text(), "fstate": self.fstate.text()}

    def suggest_states(self) -> None:
        """Fills the state fields the user has not typed in, from the requisites and the loaded input files."""
        job = self.job.text().strip()
        if not self.auto["fstate"] and job and self.fstate.text().strip() == getattr(self, "last_job", None) and job != self.last_job:
            self.fstate.blockSignals(True); self.fstate.setText(job); self.fstate.blockSignals(False)       ## still SCOPE's default (the job name): follow the rename
        self.last_job = job
        istate, fstate = backend.suggest_states(self.job.text(), self.comp_type.currentText(), self.requisites.text(), self.reports, self.branch.text(), self.workflow.text())
        for key, widget, value in (("istate", self.istate, istate), ("fstate", self.fstate, fstate)):
            if self.auto[key] and widget.text() != value: widget.blockSignals(True); widget.setText(value); widget.blockSignals(False)
        req = backend.split_names(self.requisites.text()); reads = self.istate.text().strip() or "initial"
        self.use_result.setVisible(bool(req) and reads != istate and istate != "initial")
        if req and reads == "initial": self.states_note.setText(f"This job waits for {', '.join(req)} but starts from the imported geometry ('initial'). If it should use the result of {req[0]}, set the initial state to the state {req[0]} writes.")
        elif req: self.states_note.setText(f"Waits for {', '.join(req)} (when); starts from state '{reads}' (which geometry); writes into '{self.fstate.text().strip() or self.job.text().strip()}'.")
        else: self.states_note.setText(f"Starts from state '{reads}' and writes into '{self.fstate.text().strip() or self.job.text().strip()}'.")

    def apply_suggestion(self) -> None:
        """Sets both state fields to the suggestion (the requisite's fstate) and lets them follow the form again."""
        self.auto = {"istate": True, "fstate": True}; self.refresh()

    def refresh(self) -> None:
        self.suggest_states()
        self.text, report, problems = backend.validate_form(**self.values())
        self.preview.setPlainText(self.text)
        ok = report.ok and not problems
        messages = problems + ([] if report.ok else [report.error])
        self.status.setText("Valid: SCOPE accepts this file." if ok else "\n".join(messages))
        set_kind(self.status, "ok" if ok else "err")
        self.save_btn.setEnabled(ok)

    def save(self) -> None:
        name = self.filename or f"{self.job.text().strip() or 'job'}.scope"
        path, _ = QFileDialog.getSaveFileName(self, "Save input file", os.path.join(self.start_dir, name), "Scope input (*.scope);;All files (*)")
        if not path: return
        if not os.path.splitext(path)[1]: path += ".scope"
        try:
            with open(path, "w") as f: f.write(self.text)
        except OSError as exc:
            self.status.setText(f"Cannot write {path}: {exc}"); return
        self.saved_path = path; self.accept()
