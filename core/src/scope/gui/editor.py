"""Form to create or edit a Scope input file, with a live preview and validation by SCOPE's own functions."""
import os
from PySide6.QtGui     import QFont
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QSpinBox, QTabWidget, QVBoxLayout, QWidget)
from scope.gui import backend
from scope.gui.theme import set_kind

DEFAULTS = {"branch": "demo", "workflow": "*", "job": "opt", "requisites": "", "constrains": "self", "software": "g16", "comp_type": "opt", "functional": "b3lyp", "basis": "6-31g*", "procs": 4, "want_submit": False, "queue": ""}

class InputEditor(QDialog):
    """Dialog with one field per common setting, a box for any other setting, and the resulting file as text.

    Attributes:
        saved_path (str):    Path of the file written, or '' if the dialog was cancelled.
    """
    def __init__(self, parent: QWidget=None, start_dir: str="", form: dict=None, extras: dict=None, filename: str=""):
        super().__init__(parent)
        self.setWindowTitle("Scope input file"); self.resize(1000, 640)
        self.start_dir, self.saved_path, self.text = start_dir or os.path.expanduser("~"), "", ""
        values = {**DEFAULTS, **(form or {})}
        self.branch,    self.workflow,   self.job        = QLineEdit(values["branch"]), QLineEdit(values["workflow"]), QLineEdit(values["job"])
        self.requisites, self.constrains                 = QLineEdit(values["requisites"]), QLineEdit(values["constrains"])
        self.software, self.comp_type                    = QComboBox(), QComboBox()
        self.functional, self.basis, self.queue          = QLineEdit(values["functional"]), QLineEdit(values["basis"]), QLineEdit(values["queue"])
        self.procs, self.submit                          = QSpinBox(), QCheckBox("Submit jobs to the scheduler (want_submit)")
        self.procs.setRange(1, 4096); self.procs.setValue(int(values["procs"])); self.submit.setChecked(bool(values["want_submit"]))
        self.software.addItems(list(backend.SOFTWARE_TYPES)); self.software.setCurrentText(values["software"])
        self.fill_types(values["comp_type"])
        self.branch.setToolTip("Folder name inside the system's Computations folder. Jobs of one pipeline share a branch.")
        self.workflow.setToolTip("Which sources of the system to run: '*' for all, a name, a pattern such as 'water*', or several separated by commas.")
        self.requisites.setToolTip("Jobs that must be finished and good BEFORE this one starts (names, separated by commas). Leave empty for the first job of a pipeline; a 'freq' job after an optimization needs 'opt'. Never this job's own name.")
        self.requisites.setPlaceholderText("empty = starts right away; e.g. opt")
        self.constrains.setToolTip("Jobs that block this one once they are finished. 'self' prevents running the same job twice.")
        self.queue.setToolTip("Optional. On a cluster it must match a queue of the environment exactly.")
        self.submit.setToolTip("Unchecked is written as want_submit = False. SCOPE assumes True when the line is missing.")
        form = QFormLayout()
        for label, widget in (("Branch", self.branch), ("Workflow (sources)", self.workflow), ("Job name", self.job), ("Requisites", self.requisites), ("Constrains", self.constrains), ("Software", self.software), ("Computation type", self.comp_type), ("Functional", self.functional)): form.addRow(label, widget)
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
        body = QHBoxLayout(); body.addLayout(left, 1); body.addLayout(right, 1)
        lay = QVBoxLayout(self); lay.addLayout(body, 1); lay.addLayout(buttons)
        self.filename = filename
        for w in (self.branch, self.workflow, self.job, self.requisites, self.constrains, self.functional, self.basis, self.queue): w.textChanged.connect(self.refresh)
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
                "functional": self.functional.text(), "basis": self.basis.text(), "procs": self.procs.value(), "want_submit": self.submit.isChecked(), "queue": self.queue.text(), "extras": {n: w.toPlainText() for n, w in self.extras.items()}}

    def refresh(self) -> None:
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
