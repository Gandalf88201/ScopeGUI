"""Results page (step 6): what SCOPE registered for each system of the workspace, read-only (see scope.gui.results).

The page loads a system file in a worker thread, shows where it came from (file, date, SCOPE version, the environment whose folders
were used), a table of states (energies, minima, runs), a tree of calculations (status, times, whether the output is here), and one state
in detail (structure, frequencies, IR / VDOS / absorption spectra), thermochemistry (G(T), ΔG(T) between two states and where it
changes sign), and a comparison of states across the systems of the workspace. It reloads
by itself when the system file changes (a run or a download ended), and offers to download the outputs that are not on this computer.
An older copy of the system file (kept by a download) can be opened beside the current one. Exports carry where their numbers come from.
Nothing here saves a system or creates a folder in the project, except the notebooks the user asks for, in <project>/Notebooks/.
"""
import os
import time
from PySide6.QtCore    import QThreadPool, QTimer, QUrl, Qt
from PySide6.QtGui     import QBrush, QColor, QDesktopServices, QFont, QGuiApplication, QTextCursor
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QFrame, QMenu, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSplitter, QTableWidget, QTableWidgetItem, QTabWidget, QToolButton, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)
from scope.gui import backend, notebooks, results, theme
from scope.gui.tasks import Task

GROUP_WORD = {"ok": "✓", "warn": "!", "err": "✗", "unknown": "?", "waiting": "…", "unregistered": "◌", "none": "—"}

def group_colour(group: str) -> str:
    c = theme.colors()
    return {"ok": c["ok"], "warn": c["warn"], "err": c["err"]}.get(group, c["sub"])

def item(text: str, tip: str="", colour: str="", align_right: bool=False) -> QTableWidgetItem:
    it = QTableWidgetItem(text)
    if tip: it.setToolTip(tip)
    if colour: it.setForeground(QBrush(QColor(colour)))
    if align_right: it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
    return it

def seconds(value: "float | None") -> str:
    if value is None: return ""
    if value <= 0: return "—"                                                         ## not recorded by the parser (Quantum ESPRESSO CPU time, for instance)
    return f"{value:.1f} s" if value < 120 else (f"{value / 60:.1f} min" if value < 7200 else f"{value / 3600:.1f} h")

class LogViewer(QDialog):
    """A read-only view of an output file, with a search box and a list of lines worth jumping to (terminations, energies, errors)."""
    def __init__(self, parent: QWidget, path: str, title: str):
        super().__init__(parent); self.setWindowTitle(title); self.resize(1000, 700)
        self.text = QPlainTextEdit(); self.text.setReadOnly(True); self.text.setLineWrapMode(QPlainTextEdit.NoWrap)
        mono = QFont("Menlo"); mono.setStyleHint(QFont.Monospace); self.text.setFont(mono)
        self.marks = QListWidget(); self.marks.setMinimumWidth(320); self.marks.setMaximumWidth(460); self.marks.itemClicked.connect(self.jump)
        self.find = QLineEdit(); self.find.setPlaceholderText("Find… (Enter for the next match)"); self.find.returnPressed.connect(self.find_next)
        head = QLabel(path); head.setTextInteractionFlags(Qt.TextSelectableByMouse); head.setWordWrap(True)
        self.note = QLabel(); self.note.setWordWrap(True)
        split = QSplitter(); split.addWidget(self.marks); split.addWidget(self.text); split.setStretchFactor(1, 1)
        close = QPushButton("Close"); close.clicked.connect(self.accept)
        reveal = QPushButton("Show in folder"); reveal.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(path))))
        row = QHBoxLayout(); row.addWidget(self.find, 1); row.addWidget(reveal); row.addWidget(close)
        lay = QVBoxLayout(self); lay.addWidget(head); lay.addWidget(self.note); lay.addWidget(split, 1); lay.addLayout(row)
        try: text, note = results.read_log(path)
        except OSError as exc: text, note = "", f"Cannot read the file: {exc}"
        self.text.setPlainText(text); self.note.setText(note); self.note.setVisible(bool(note))
        for line, kind, content in results.log_marks(text):
            it = QListWidgetItem(f"{line + 1:>7}  {content[:80]}"); it.setData(Qt.UserRole, line)
            it.setForeground(QBrush(QColor(group_colour({"ok": "ok", "err": "err", "warn": "warn"}.get(kind, "info"))))); self.marks.addItem(it)
        if self.marks.count(): self.jump(self.marks.item(self.marks.count() - 1))                 ## the end of a log tells how it finished

    def jump(self, it: QListWidgetItem) -> None:
        block = self.text.document().findBlockByLineNumber(int(it.data(Qt.UserRole)))
        cursor = QTextCursor(block); self.text.setTextCursor(cursor); self.text.centerCursor()

    def find_next(self) -> None:
        if self.find.text() and not self.text.find(self.find.text()):
            self.text.moveCursor(QTextCursor.Start); self.text.find(self.find.text())

def caption(text: str) -> QLabel:
    label = QLabel(text); label.setObjectName("pagesub"); return label

def hrow(*parts, stretch: bool=True, spacing: int=8) -> QHBoxLayout:
    """A row of widgets; a str becomes a grey caption, None a wider gap."""
    row = QHBoxLayout(); row.setSpacing(spacing); row.setContentsMargins(0, 0, 0, 0)
    for part in parts:
        if part is None: row.addSpacing(16)
        elif isinstance(part, str): row.addWidget(caption(part))
        elif isinstance(part, QWidget): row.addWidget(part)
        else: row.addLayout(part)
    if stretch: row.addStretch(1)
    return row

def card(*rows, title: str="") -> QFrame:
    """A rounded panel (the Cluster page's cards) holding rows (layouts or widgets)."""
    frame = QFrame(); frame.setObjectName("card"); lay = QVBoxLayout(frame); lay.setContentsMargins(14, 10, 14, 12); lay.setSpacing(8)
    if title: head = QLabel(title); head.setObjectName("cardtitle"); lay.addWidget(head)
    for r in rows: lay.addWidget(r) if isinstance(r, QWidget) else lay.addLayout(r)
    return frame

def scrolled(widget: QWidget) -> QScrollArea:
    """`widget` in a frameless scroll area: its minimum size no longer forces the window to grow; a small window scrolls instead."""
    area = QScrollArea(); area.setWidgetResizable(True); area.setFrameShape(QFrame.NoFrame); area.setWidget(widget)
    return area

SPECTRA = {"ir": "IR", "vdos": "Vibrational density of states", "abs": "Absorption (UV-vis)"}
DEFAULT_WIDTH = {"ir": (10.0, " cm⁻¹", 0.5, 500.0, 1.0), "vdos": (10.0, " cm⁻¹", 0.5, 500.0, 1.0), "abs": (0.2, " eV", 0.01, 2.0, 0.05)}     ## value, unit, min, max, step

class StatePanel(QWidget):
    """The State tab: one state in detail. Its structure (as SCOPE holds it), its frequencies, and its spectra computed by SCOPE's own functions.
    Everything is read from the system in memory; the only files written are the ones the user saves (geometry, plot)."""
    def __init__(self, page: "ResultsTab"):
        super().__init__()
        from scope.gui.plots import PlotCanvas, PlotPanel
        from scope.gui.structure_view import StructurePanel
        self.page, self.detail, self.keys = page, None, []
        self.chooser = QComboBox(); self.chooser.setMinimumWidth(220); self.chooser.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon); self.chooser.setMinimumContentsLength(22); self.chooser.currentIndexChanged.connect(self.show_index)
        self.summary = QLabel(); self.summary.setWordWrap(True); self.summary.setTextFormat(Qt.RichText); self.summary.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.save_xyz_btn = QPushButton("Save geometry (.xyz)…"); self.save_xyz_btn.clicked.connect(self.save_xyz)
        self.summary.setMinimumWidth(10)                                                    ## wraps instead of widening the window
        self.structure = StructurePanel()
        ## spectrum controls
        self.kind = QComboBox(); self.kernel = QComboBox(); self.kernel.addItems(results.KERNELS)
        self.kind.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon); self.kind.setMinimumContentsLength(14)
        self.width = QDoubleSpinBox(); self.width.setDecimals(2); self.width.setToolTip("Broadening width")
        self.auto = QCheckBox("Auto range"); self.auto.setChecked(True)
        self.lo, self.hi = QDoubleSpinBox(), QDoubleSpinBox()
        for b in (self.lo, self.hi): b.setRange(-1000, 100000); b.setDecimals(0); b.setVisible(False); b.setMinimumWidth(80)
        self.dash = QLabel("–"); self.dash.setVisible(False)
        self.per_z = QCheckBox("Per formula unit"); self.per_z.setChecked(True); self.per_z.setToolTip("Divide by the number of formula units in the cell (Z)")
        self.save_plot_btn = QPushButton("Save plot…"); self.save_plot_btn.clicked.connect(self.save_plot)
        self.width.setMinimumWidth(110)
        ctl = hrow("Spectrum", self.kind, None, "Kernel", self.kernel, None, "Width", self.width, None, self.auto, self.lo, self.dash, self.hi, None, self.per_z)
        self.canvas = PlotCanvas(); self.plot_panel = PlotPanel(self.canvas, [self.save_plot_btn])
        self.kind.currentIndexChanged.connect(self.kind_changed)
        for sig in (self.kernel.currentIndexChanged, self.width.valueChanged, self.lo.valueChanged, self.hi.valueChanged, self.per_z.toggled): sig.connect(self.plot)
        self.auto.toggled.connect(lambda on: ([b.setVisible(not on) for b in (self.lo, self.dash, self.hi)], [b.setEnabled(not on) for b in (self.lo, self.hi)], self.plot()))
        ## frequencies
        self.modes = QTableWidget(0, 5); self.modes.setHorizontalHeaderLabels(["Mode", "Frequency (cm⁻¹)", "IR (km/mol)", "Red. mass (amu)", "Sym."])
        self.modes.setEditTriggers(QAbstractItemView.NoEditTriggers); self.modes.verticalHeader().setVisible(False)
        [self.modes.horizontalHeader().setSectionResizeMode(i, QHeaderView.ResizeToContents) for i in range(5)]
        self.modes_note = QLabel(); self.modes_note.setObjectName("pagesub"); self.modes_note.setWordWrap(True)
        copy_modes = QPushButton("Copy frequencies (CSV)"); copy_modes.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.modes_text()) if self.detail else None)
        mrow = QHBoxLayout(); mrow.addWidget(self.modes_note, 1); mrow.addWidget(copy_modes)
        freq_box = QWidget(); fl = QVBoxLayout(freq_box); fl.setContentsMargins(10, 10, 10, 10); fl.setSpacing(8); fl.addLayout(mrow); fl.addWidget(self.modes, 1)
        spec_box = QWidget(); sl = QVBoxLayout(spec_box); sl.setContentsMargins(10, 10, 10, 10); sl.setSpacing(10); sl.addLayout(ctl); sl.addWidget(self.plot_panel, 1)
        self.lower = QTabWidget(); self.lower.addTab(spec_box, "Spectrum"); self.lower.addTab(freq_box, "Frequencies"); self.lower.addTab(scrolled(self.structure), "Structure")     ## each gets the whole area
        head = card(self.state_row(), self.summary)
        lay = QVBoxLayout(self); lay.setContentsMargins(0, 10, 0, 0); lay.setSpacing(10); lay.addWidget(head); lay.addWidget(self.lower, 1)
        theme.on_change(self.fill_modes)

    def state_row(self) -> QHBoxLayout:
        row = hrow("State", self.chooser); row.addWidget(self.save_xyz_btn); return row

    def set_loaded(self, loaded: "results.Loaded | None") -> None:
        """New system (or the same one reloaded): keeps the state shown if it still exists, otherwise picks the first state with frequencies."""
        keep = self.keys[self.chooser.currentIndex()] if 0 <= self.chooser.currentIndex() < len(self.keys) else None
        rows = loaded.summary.states if loaded else []
        self.keys = [(r.source, r.state) for r in rows]
        self.chooser.blockSignals(True); self.chooser.clear()
        self.chooser.addItems([f"{r.source} · {r.state}" + ("" if r.energy is not None else "  (no result)") for r in rows]); self.chooser.blockSignals(False)
        if not rows: self.detail = None; self.structure.clear("No system shown."); self.canvas.show_message(""); self.modes.setRowCount(0); self.summary.setText(""); return
        index = self.keys.index(keep) if keep in self.keys else next((i for i, r in enumerate(rows) if r.n_freqs), next((i for i, r in enumerate(rows) if r.energy is not None), 0))
        self.chooser.setCurrentIndex(index); self.show_index(index)

    def show_state(self, source: str, state: str) -> None:
        if (source, state) in self.keys: self.chooser.setCurrentIndex(self.keys.index((source, state)))

    def show_index(self, index: int) -> None:
        loaded = self.page.loaded
        if not loaded or not 0 <= index < len(self.keys): return
        source, state = self.keys[index]; row = loaded.summary.states[index]
        try: self.detail = results.state_detail(loaded.system, source, state)
        except Exception as exc: self.detail = None; self.summary.setText(f"Cannot read this state: {type(exc).__name__}: {exc}"); return
        d = self.detail; c = theme.colors(); units = self.page.units.currentText()
        energy = "no energy registered" if row.energy is None else f"<span style='font-size:15px; font-weight:600'>{row.energy:.8f} Eh</span>"
        bits = [energy, row.method or "", f"{len(d.modes)} frequencies" if d.modes else "no frequencies",
                ("<span style='color:%s'>%d imaginary</span>" % (c["err"], sum(m.freq < 0 for m in d.modes))) if any(m.freq < 0 for m in d.modes) else ("minimum" if d.modes else ""),
                f"{d.n_excited} excited states" if d.n_excited else "", "from " + ", ".join(row.runs) if row.runs else ""]
        sub = f"<span style='color:{c['sub']}'>"; self.summary.setText(bits[0] + " &nbsp; " + sub + " &nbsp;·&nbsp; ".join(b for b in bits[1:] if b) + "</span>")
        if d.structure: self.structure.set_structures([d.structure], "", f"{source} · {state}")
        else: self.structure.clear("This state has no geometry of its own.")
        self.save_xyz_btn.setEnabled(d.structure is not None)
        kinds = [k for k, ok in (("ir", bool(d.modes)), ("vdos", bool(d.modes)), ("abs", d.n_excited > 0)) if ok]
        current = self.kind.currentData()
        self.kind.blockSignals(True); self.kind.clear(); [self.kind.addItem(SPECTRA[k], k) for k in kinds]; self.kind.blockSignals(False)
        if current in kinds: self.kind.setCurrentIndex(kinds.index(current))
        self.per_z.setVisible(bool(d.z) and d.z != 1)
        if not kinds and self.lower.currentIndex() != 2: self.lower.setCurrentIndex(2)                   ## nothing to plot: show the structure
        self.kind_changed(); self.fill_modes()

    def kind_changed(self) -> None:
        kind = self.kind.currentData()
        if kind:
            value, unit, lo, hi, step = DEFAULT_WIDTH[kind]
            for w in (self.width, self.lo, self.hi): w.blockSignals(True)
            if self.width.suffix() != unit: self.width.setRange(lo, hi); self.width.setSingleStep(step); self.width.setSuffix(unit); self.width.setValue(value)
            if kind == "abs": self.lo.setValue(200); self.hi.setValue(1000)
            elif self.detail and self.detail.modes: self.lo.setValue(min(0, min(m.freq for m in self.detail.modes) - 100)); self.hi.setValue(max(m.freq for m in self.detail.modes) + 100)
            for w in (self.width, self.lo, self.hi): w.blockSignals(False)
        for w in (self.kernel, self.width, self.auto, self.lo, self.hi, self.save_plot_btn): w.setEnabled(bool(kind) if w not in (self.lo, self.hi) else bool(kind) and not self.auto.isChecked())
        self.plot()

    def plot(self) -> None:
        d, kind = self.detail, self.kind.currentData()
        if d is None or not kind:
            self.canvas.show_message("No frequencies or excited states were computed for this state." if d else ""); return
        lo, hi = (None, None) if self.auto.isChecked() else (self.lo.value(), self.hi.value())
        if kind == "abs" and self.auto.isChecked(): lo, hi = 200, 1000
        try: sp = results.spectrum(self.page.loaded.system, d.source, d.state, kind, self.kernel.currentText(), self.width.value(), lo, hi, self.per_z.isChecked())
        except Exception as exc: self.canvas.show_message(f"Cannot build this spectrum: {exc}"); return
        if kind == "ir" and not d.has_ir: sp.title += "  (no IR intensities stored)"
        self.canvas.plot_spectrum(sp)

    def fill_modes(self) -> None:
        d = self.detail; c = theme.colors()
        modes = d.modes if d else []
        self.modes.setRowCount(len(modes))
        for i, m in enumerate(modes):
            red = c["err"] if m.freq < 0 else ""
            cells = [item(str(m.index), "", "", True), item(f"{m.freq:.2f}", "Imaginary (negative): not a minimum along this mode" if m.freq < 0 else "", red, True),
                     item("" if m.ir is None else f"{m.ir:.2f}", "", "", True), item("" if m.red_mass is None else f"{m.red_mass:.3f}", "", "", True), item(m.sym)]
            for j, cell in enumerate(cells): self.modes.setItem(i, j, cell)
        imag = sum(m.freq < 0 for m in modes); self.lower.setTabText(1, f"Frequencies ({len(modes)})" if modes else "Frequencies")
        self.modes_note.setText("" if not d else ("No frequencies were computed for this state (a frequency job writes them)." if not modes else
                                f"{len(modes)} modes" + (f", {imag} imaginary (a transition state has exactly one)" if imag else ", none imaginary: a minimum") + ". As stored by SCOPE; eigenvectors are not shown."))

    def suggested(self, ext: str) -> str:
        p = self.page.loaded.provenance if self.page.loaded else None
        name = "_".join(x for x in ((p.system if p else ""), self.detail.source if self.detail else "", self.detail.state if self.detail else "", (self.kind.currentData() or "") if ext != "xyz" else "") if x)
        return os.path.join(os.path.expanduser("~"), f"{name}.{ext}")

    def save_xyz(self) -> None:
        if not self.detail or not self.detail.structure: return
        path, _ = QFileDialog.getSaveFileName(self, "Save the geometry of this state", self.suggested("xyz"), "XYZ files (*.xyz)")
        if not path: return
        p = self.page.loaded.provenance
        with open(path, "w") as fh: fh.write(results.xyz_text(self.detail.structure, f"{p.system} {self.detail.source} {self.detail.state} (from {p.file}, SCOPE {p.saved_version})"))

    def settings(self) -> dict:
        """What the spectrum shown was computed with, for the provenance of an export."""
        d = self.detail; kind = self.kind.currentData()
        out = {"state": f"{d.source} · {d.state}" if d else ""}
        if kind: out |= {"spectrum": SPECTRA[kind], "kernel": self.kernel.currentText(), "width": f"{self.width.value():g}{self.width.suffix()}",
                         "range": "auto" if self.auto.isChecked() else f"{self.lo.value():g} to {self.hi.value():g}", "per formula unit": self.per_z.isChecked() if self.per_z.isVisible() else "n/a"}
        return out

    def export(self) -> tuple:
        """(file name, CSV) of what the State tab shows: the spectrum curve on the Spectrum sub-tab, the modes on Frequencies; nothing for Structure."""
        d, p = self.detail, self.page.loaded.provenance if self.page.loaded else None
        if not d: return "", ""
        base = f"{p.system if p else ''}_{d.source}_{d.state}"
        if self.lower.currentIndex() == 0 and isinstance(self.canvas.last, results.Spectrum): return f"{base}_{self.kind.currentData()}.csv", results.spectrum_csv(self.canvas.last, p, self.settings())
        if self.lower.currentIndex() == 1 and d.modes: return f"{base}_frequencies.csv", self.modes_text()
        return "", ""

    def modes_text(self) -> str:
        return results.modes_csv(self.detail.modes, self.page.loaded.provenance if self.page.loaded else None, {"state": f"{self.detail.source} · {self.detail.state}"})

    def save_plot(self) -> None:
        if self.canvas.last is None: return
        path, _ = QFileDialog.getSaveFileName(self, "Save the plot", self.suggested("png"), PLOT_FILTER)
        if path: self.canvas.save(path, results.plot_metadata(self.page.loaded.provenance if self.page.loaded else None, self.settings(), getattr(self.canvas.last, "title", "")))

PLOT_FILTER = "PNG image (*.png);;SVG drawing (*.svg);;PDF (*.pdf)"

def combo(items: list, tip: str="") -> QComboBox:
    box = QComboBox(); box.addItems(items)
    if tip: box.setToolTip(tip)
    return box

def spin(lo: float, hi: float, value: float, step: float=1.0, decimals: int=2, suffix: str="") -> QDoubleSpinBox:
    box = QDoubleSpinBox(); box.setRange(lo, hi); box.setDecimals(decimals); box.setSingleStep(step); box.setValue(value)
    if suffix: box.setSuffix(suffix)
    return box

IMAG_TIP = "Imaginary frequencies, as SCOPE treats them: ignore (left out, usual for a transition state), absolute (taken as real, a diagnostic), raise (stop: the state should be a minimum)"

class ThermoPanel(QWidget):
    """The Thermochemistry tab: G(T) of one state, or ΔG(T), ΔH and −TΔS between two states, from SCOPE's get_thermal_data (run on a copy of
    the state, in a worker thread). Where ΔG changes sign is shown (T½ for the HS and LS states of a spin-crossover compound)."""
    def __init__(self, page: "ResultsTab"):
        super().__init__()
        from scope.gui.plots import PlotCanvas, PlotPanel
        self.page, self.task, self.generation, self.result, self.keys = page, None, 0, None, []
        self.a, self.b = QComboBox(), QComboBox()
        for box in (self.a, self.b): box.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon); box.setMinimumContentsLength(20)
        self.t_from, self.t_to, self.t_step = spin(1, 5000, 10, 10, 1, " K"), spin(1, 5000, 500, 10, 1, " K"), spin(0.1, 500, 5, 1, 1, " K")
        self.at = spin(1, 5000, 298.15, 10, 2, " K"); self.at.setToolTip("Temperature at which the values are reported below the plot")
        self.model = combo(results.MODELS, "Vibrational entropy: harmonic oscillator, or Grimme's quasi-rigid-rotor model (QRRHO) for low frequencies")
        self.imag = combo(results.IMAGINARY, IMAG_TIP); self.cutoff = spin(1, 1000, 100, 10, 0, " cm⁻¹"); self.cutoff.setToolTip("QRRHO frequency cutoff")
        self.units = combo(list(results.UNITS)[1:])
        self.summary = QLabel(); self.summary.setWordWrap(True); self.summary.setTextFormat(Qt.RichText); self.summary.setTextInteractionFlags(Qt.TextSelectableByMouse); self.summary.setMinimumWidth(10)
        self.canvas = PlotCanvas()
        save, copy = QPushButton("Save plot…"), QPushButton("Copy data (CSV)"); save.clicked.connect(self.save_plot); copy.clicked.connect(self.copy_csv)
        self.plot_panel = PlotPanel(self.canvas, [copy, save])
        grid = QGridLayout(); grid.setHorizontalSpacing(12); grid.setVerticalSpacing(8); grid.setColumnStretch(1, 1)
        for r, (name, row) in enumerate((("States", hrow(self.a, "minus", self.b)),
                                         ("Temperature", hrow("from", self.t_from, "to", self.t_to, "step", self.t_step, None, "report at", self.at)),
                                         ("Model", hrow(self.model, self.cutoff, None, "Imaginary", self.imag, None, "Units", self.units)))):
            grid.addWidget(caption(name), r, 0, Qt.AlignRight | Qt.AlignVCenter); grid.addLayout(row, r, 1)
        self.summary.setContentsMargins(2, 0, 2, 0)
        lay = QVBoxLayout(self); lay.setContentsMargins(0, 10, 0, 0); lay.setSpacing(10)
        lay.addWidget(card(grid)); lay.addWidget(self.summary); lay.addWidget(self.plot_panel, 1)
        self.timer = QTimer(self); self.timer.setSingleShot(True); self.timer.setInterval(250); self.timer.timeout.connect(self.compute)
        for sig in (self.a.currentIndexChanged, self.b.currentIndexChanged, self.t_from.valueChanged, self.t_to.valueChanged, self.t_step.valueChanged, self.at.valueChanged,
                    self.model.currentIndexChanged, self.imag.currentIndexChanged, self.cutoff.valueChanged): sig.connect(self.timer.start)
        self.units.currentIndexChanged.connect(self.draw); self.model.currentTextChanged.connect(lambda m: self.cutoff.setVisible(m == "QRRHO")); self.cutoff.hide()

    def set_loaded(self, loaded: "results.Loaded | None") -> None:
        keep_a, keep_b = self.a.currentData(), self.b.currentData()
        self.keys = [(r.source, r.state) for r in (loaded.summary.states if loaded else []) if r.n_freqs and r.energy is not None]
        for box in (self.a, self.b): box.blockSignals(True); box.clear()
        self.b.addItem("— nothing (one state) —", None)
        for k in self.keys: self.a.addItem(f"{k[0]} · {k[1]}", k); self.b.addItem(f"{k[0]} · {k[1]}", k)
        if keep_a in self.keys: self.a.setCurrentIndex(self.keys.index(keep_a))
        if keep_b in self.keys: self.b.setCurrentIndex(self.keys.index(keep_b) + 1)
        for box in (self.a, self.b): box.blockSignals(False)
        self.result = None
        if not loaded: self.canvas.show_message(""); self.summary.setText(""); return
        if not self.keys: self.canvas.show_message("No state of this system has frequencies. Thermochemistry needs a frequency job (and its energy)."); self.summary.setText(""); return
        self.compute()

    def temperatures(self) -> list:
        lo, hi, step = self.t_from.value(), self.t_to.value(), self.t_step.value()
        if hi < lo: lo, hi = hi, lo
        n = min(int((hi - lo) / step) + 1, 5000)
        return sorted({round(lo + i * step, 6) for i in range(n)} | {round(hi, 6), round(self.at.value(), 6)})

    def compute(self) -> None:
        loaded, a, b = self.page.loaded, self.a.currentData(), self.b.currentData()
        if not loaded or not a: return
        self.generation += 1; generation = self.generation
        temps, model, imag, cutoff = self.temperatures(), self.model.currentText(), self.imag.currentText(), self.cutoff.value()
        obj = loaded.system
        def work():
            ta = results.thermo(obj, a[0], a[1], temps, model, imag, cutoff)
            tb = results.thermo(obj, b[0], b[1], temps, model, imag, cutoff) if b and b != a else None
            return generation, ta, tb
        self.summary.setText("Computing…"); theme.set_kind(self.summary, "")
        task = Task(work); self.task = task
        task.signals.done.connect(self.computed); task.signals.failed.connect(lambda m, g=generation: self.failed(g, m))
        QThreadPool.globalInstance().start(task)

    def computed(self, out) -> None:
        generation, ta, tb = out
        if generation != self.generation: return                                   ## settings changed meanwhile: a newer result is coming
        self.result = (ta, tb, results.difference(ta, tb) if tb else None); self.draw()

    def failed(self, generation: int, message: str) -> None:
        if generation != self.generation: return
        self.result = None; self.canvas.show_message("Cannot compute the thermochemistry."); theme.set_kind(self.summary, "err")
        self.summary.setText(message.replace("ValueError: ", "") + (" (the 'raise' policy stops at an imaginary frequency; choose 'ignore' for a transition state)" if "raise" in self.imag.currentText() else ""))

    def row(self, key) -> "results.StateRow | None":
        return next((r for r in self.page.loaded.summary.states if (r.source, r.state) == key), None) if self.page.loaded else None

    def draw(self) -> None:
        from scope.gui.plots import Lines
        if not self.result: return
        ta, tb, d = self.result; units = self.units.currentText(); f = results.UNITS[units]; c = theme.colors(); T = ta.T
        notes = []
        for th in (ta, tb):
            if th and th.n_imag: notes.append(f"{th.source} · {th.state} has {th.n_imag} imaginary frequenc{'y' if th.n_imag == 1 else 'ies'} ({th.settings['imaginary']}).")
        per = f"per formula unit (Z = {ta.z:g})" if ta.z != 1 else "per molecule"
        if d is None:
            i = ta.at(self.at.value()); t = ta.T[i]
            self.canvas.plot(Lines(f"Thermal terms · {ta.source} · {ta.state}", "Temperature (K)", f"Energy ({units}), {per}",
                                   [("G − H_elec", T, [(g - ta.Helec) * f for g in ta.G]), ("H_vib", T, [h * f for h in ta.Hvib]), ("−T·S (elec + vib)", T, [-x * (ta.Selec + s) * f for x, s in zip(T, ta.Svib)])], zero=True))
            text = (f"At {t:g} K: <b>G = {ta.G[i]:.8f} Eh</b> &nbsp;·&nbsp; G − H<sub>elec</sub> = {(ta.G[i] - ta.Helec) * f:.2f} {units} &nbsp;·&nbsp; "
                    f"H<sub>vib</sub> = {ta.Hvib[i] * f:.2f} &nbsp;·&nbsp; −T·S = {-t * (ta.Selec + ta.Svib[i]) * f:.2f} {units} &nbsp;·&nbsp; {ta.settings['model']}. "
                    f"Translational and rotational terms are not included (as in SCOPE).")
        else:
            i = d.T.index(min(d.T, key=lambda x: abs(x - self.at.value()))); t = d.T[i]
            marks = [(x, f"ΔG = 0 at {x:.1f} K") for x in d.crossing]
            self.canvas.plot(Lines(f"{d.a}  minus  {d.b}", "Temperature (K)", f"Δ ({units}), {per}",
                                   [("ΔG", d.T, [x * f for x in d.dG]), ("ΔH", d.T, [x * f for x in d.dH]), ("−TΔS", d.T, [x * f for x in d.mTdS])], zero=True, marks=marks))
            if d.crossing: cross = f"<b>ΔG = 0 at {', '.join(f'{x:.1f} K' for x in d.crossing)}</b> (T½ when the two states are the high- and low-spin states of a spin-crossover compound)."
            else: cross = f"ΔG keeps its sign from {d.T[0]:g} to {d.T[-1]:g} K: <b>{d.a if d.dG[0] < 0 else d.b}</b> is the more stable throughout (no crossing in this range)."
            text = f"At {t:g} K: <b>ΔG = {d.dG[i] * f:.2f} {units}</b> &nbsp;·&nbsp; ΔH = {d.dH[i] * f:.2f} &nbsp;·&nbsp; −TΔS = {d.mTdS[i] * f:.2f} {units}. {cross}"
            ra, rb = self.row((ta.source, ta.state)), self.row((tb.source, tb.state))
            if ra and rb and (ra.formula != rb.formula or ra.method != rb.method): notes.append(f"The two states differ in formula or method ({ra.formula} {ra.method} vs {rb.formula} {rb.method}): their ΔG is not a meaningful comparison.")
        self.summary.setText(text + "".join(f"<br><span style='color:{c['warn']}'>{n}</span>" for n in notes)); theme.set_kind(self.summary, "")

    def settings(self) -> dict:
        ta, tb, d = self.result if self.result else (None, None, None)
        out = {"A": f"{ta.source} · {ta.state}" if ta else "", "B": f"{tb.source} · {tb.state}" if tb else "none"}
        if ta: out |= {"model": ta.settings.get("model"), "imaginary": ta.settings.get("imaginary")} | ({"QRRHO cutoff": f"{ta.settings['FR_cutoff']:g} cm-1"} if "FR_cutoff" in ta.settings else {})
        return out | {"temperatures": f"{self.t_from.value():g} to {self.t_to.value():g} K, step {self.t_step.value():g} K", "units": self.units.currentText()}

    def csv_text(self) -> str:
        if not self.result: return ""
        ta, tb, d = self.result; prov = self.page.loaded.provenance if self.page.loaded else None
        return results.difference_csv(d, self.units.currentText(), prov, self.settings()) if d else results.thermo_csv(ta, self.units.currentText(), prov)

    def copy_csv(self) -> None:
        if self.result: QGuiApplication.clipboard().setText(self.csv_text())

    def save_plot(self) -> None:
        if self.canvas.last is None: return
        name = (self.page.loaded.provenance.system if self.page.loaded else "") + "_thermo"
        path, _ = QFileDialog.getSaveFileName(self, "Save the plot", os.path.join(os.path.expanduser("~"), f"{name}.png"), PLOT_FILTER)
        if path: self.canvas.save(path, results.plot_metadata(self.page.loaded.provenance if self.page.loaded else None, self.settings(), getattr(self.canvas.last, "title", "")))

class ComparePanel(QWidget):
    """The Compare tab: states of several systems of the workspace side by side, by electronic energy or by G(T). Δ is taken only within the
    same formula and method, across systems. Other systems are loaded read-only in a worker thread and kept until their file changes."""
    def __init__(self, page: "ResultsTab"):
        super().__init__()
        from scope.gui.plots import PlotCanvas, PlotPanel
        self.page, self.cache, self.rows, self.task, self.order, self.done_quantity, self.done_temp, self.provs, self.done_settings = page, {}, [], None, [], "energy", 298.15, [], {}
        self.list = QListWidget(); self.list.setFixedWidth(140); self.list.setToolTip("Systems to compare (tick them)")
        all_btn, this_btn = QPushButton("All"), QPushButton("Only this"); all_btn.clicked.connect(lambda: self.tick(True)); this_btn.clicked.connect(lambda: self.tick(False))
        self.list.setObjectName("navlist"); lb = QHBoxLayout(); lb.setSpacing(6); lb.addWidget(all_btn); lb.addWidget(this_btn)
        left = card(self.list, lb, title="Systems"); left.setFixedWidth(150); self.list.setMinimumWidth(10); self.list.setFixedWidth(122)
        self.quantity = combo(["Electronic energy", "Gibbs energy G(T)"]); self.temp = spin(1, 5000, 298.15, 10, 2, " K")
        self.model, self.imag, self.units = combo(results.MODELS), combo(results.IMAGINARY, IMAG_TIP), combo(list(results.UNITS)[1:])
        self.go = QPushButton("Compare"); self.go.setProperty("primary", True); self.go.clicked.connect(self.run)
        copy, save = QPushButton("Copy table (CSV)"), QPushButton("Save plot…"); copy.clicked.connect(self.copy_csv); save.clicked.connect(self.save_plot)
        row = hrow("Compare", self.quantity, self.temp, self.model, self.imag, None, "Units", self.units); row.addWidget(self.go)
        self.status = QLabel("Tick systems and press Compare. Δ is measured from the lowest value among states with the same formula and method."); self.status.setWordWrap(True); self.status.setObjectName("pagesub"); self.status.setMinimumWidth(10)
        self.table = QTableWidget(0, 8); self.table.setHorizontalHeaderLabels(["System", "Source", "State", "Formula", "Method", "Value (Eh)", "Δ", "Note"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers); self.table.setSelectionBehavior(QAbstractItemView.SelectRows); self.table.verticalHeader().setVisible(False)
        hh = self.table.horizontalHeader(); [hh.setSectionResizeMode(i, QHeaderView.ResizeToContents) for i in range(8)]; hh.setSectionResizeMode(7, QHeaderView.Stretch)
        self.table.itemSelectionChanged.connect(self.draw)
        self.canvas = PlotCanvas(); self.plot_panel = PlotPanel(self.canvas, [copy, save])
        split = QSplitter(Qt.Vertical); split.setHandleWidth(8); split.addWidget(self.table); split.addWidget(self.plot_panel); split.setStretchFactor(0, 1); split.setStretchFactor(1, 1)
        right = QVBoxLayout(); right.setSpacing(10); right.addWidget(card(row, self.status)); right.addWidget(split, 1)
        lay = QHBoxLayout(self); lay.setContentsMargins(0, 10, 0, 0); lay.setSpacing(10); lay.addWidget(left); lay.addLayout(right, 1)
        self.quantity.currentIndexChanged.connect(self.options_shown); self.units.currentIndexChanged.connect(self.fill); self.options_shown()

    def options_shown(self) -> None:
        g = self.quantity.currentIndex() == 1
        for w in (self.temp, self.model, self.imag): w.setVisible(g)

    def set_systems(self, names: list, current: str) -> None:
        ticked = {self.list.item(i).text() for i in range(self.list.count()) if self.list.item(i).checkState() == Qt.Checked}
        self.list.clear()
        for n in names:
            it = QListWidgetItem(n); it.setFlags(it.flags() | Qt.ItemIsUserCheckable); it.setCheckState(Qt.Checked if n in ticked or n == current else Qt.Unchecked); self.list.addItem(it)
        self.cache = {k: v for k, v in self.cache.items() if k in names}

    def tick(self, everything: bool) -> None:
        current = self.page.current()
        for i in range(self.list.count()): self.list.item(i).setCheckState(Qt.Checked if everything or self.list.item(i).text() == current else Qt.Unchecked)

    def chosen(self) -> list:
        return [self.list.item(i).text() for i in range(self.list.count()) if self.list.item(i).checkState() == Qt.Checked]

    def run(self) -> None:
        names, info = self.chosen(), self.page.session.info
        if not names or not info or self.task is not None: return
        env_path, current = info.filepath, self.page.loaded
        cache = dict(self.cache)
        quantity, temp, model, imag = ("energy" if self.quantity.currentIndex() == 0 else "gibbs"), self.temp.value(), self.model.currentText(), self.imag.currentText()
        def work():
            loadeds, errors = [], []
            for n in names:
                if current is not None and current.provenance.system == n: L = current
                else:
                    path = os.path.join(info.systems_path, n, f"{n}.npy"); fp = results.fingerprint(path)
                    hit = cache.get(n)
                    if hit and hit[0] == fp: L = hit[1]
                    else:
                        try: L = results.load(env_path, n); cache[n] = (fp, L)
                        except Exception as exc: errors.append(f"{n}: {str(exc).replace('ResultsError: ', '')}"); continue
                loadeds.append(L)
            return results.compare_rows(loadeds, quantity, temp, model, imag), errors, cache, quantity, temp, [L.provenance for L in loadeds], {"model": model, "imaginary": imag} if quantity == "gibbs" else {}
        self.go.setEnabled(False); self.status.setText(f"Comparing {len(names)} system(s)…")
        task = Task(work); self.task = task
        task.signals.done.connect(self.done); task.signals.failed.connect(lambda m: (setattr(self, "task", None), self.go.setEnabled(True), self.status.setText(f"Failed: {m}")))
        QThreadPool.globalInstance().start(task)

    def done(self, out) -> None:
        self.task = None; self.go.setEnabled(True)
        self.rows, errors, self.cache, self.done_quantity, self.done_temp, self.provs, self.done_settings = out
        rel = results.compare_relative(self.rows); groups = len({(r.formula, r.method) for r in self.rows if (r.system, r.source, r.state) in rel})
        what = "electronic energies" if self.done_quantity == "energy" else f"G at {self.done_temp:g} K (per formula unit)"
        self.status.setText(f"{len(self.rows)} state(s) with {what}; {groups} group(s) of comparable states (same formula and method). Select a row to plot its group."
                            + (" Not loaded: " + "; ".join(errors) if errors else ""))
        theme.set_kind(self.status, "warn" if errors else ""); self.fill()

    def fill(self) -> None:
        units = self.units.currentText(); f = results.UNITS[units]; rel = results.compare_relative(self.rows); sub = theme.colors()["sub"]
        order = sorted(range(len(self.rows)), key=lambda i: ((self.rows[i].system, self.rows[i].source, self.rows[i].state) not in rel, self.rows[i].formula, self.rows[i].method,
                                                                rel.get((self.rows[i].system, self.rows[i].source, self.rows[i].state), 0)))
        self.order = order
        self.table.blockSignals(True); self.table.setRowCount(len(order))
        for k, i in enumerate(order):
            r = self.rows[i]; d = rel.get((r.system, r.source, r.state))
            note = r.note or ("" if d is not None or r.value is None else "nothing with the same formula and method")
            cells = [item(r.system), item(r.source), item(r.state), item(r.formula), item(r.method, "", sub), item("—" if r.value is None else f"{r.value:.8f}", "", "" if r.value is not None else sub, True),
                     item("" if d is None else f"{d * f:.2f}", f"in {units}", "", True), item(note, note, sub)]
            for j, cell in enumerate(cells): self.table.setItem(k, j, cell)
        self.table.horizontalHeaderItem(6).setText(f"Δ ({units})"); self.table.blockSignals(False)
        first = next((k for k, i in enumerate(order) if (self.rows[i].system, self.rows[i].source, self.rows[i].state) in rel), -1)
        if first >= 0: self.table.selectRow(first)
        else: self.canvas.show_message("Nothing to compare: no two states share formula and method." if self.rows else "")
        self.draw()

    def draw(self) -> None:
        from scope.gui.plots import Bars
        sel = self.table.selectionModel().selectedRows()
        if not sel or not self.rows: return
        r = self.rows[self.order[sel[0].row()]]; rel = results.compare_relative(self.rows)
        group = [x for x in self.rows if x.formula == r.formula and x.method == r.method and (x.system, x.source, x.state) in rel]
        if not group: self.canvas.show_message("This state has nothing comparable (same formula and method) among the systems ticked."); return
        group.sort(key=lambda x: rel[(x.system, x.source, x.state)]); units = self.units.currentText(); f = results.UNITS[units]
        multi = len({x.system for x in group}) > 1
        labels = [(f"{x.system} · " if multi else "") + f"{x.source} · {x.state}" for x in group]
        what = "E" if self.done_quantity == "energy" else f"G({self.done_temp:g} K)"
        self.canvas.plot(Bars(f"Δ{what} · {r.formula} · {r.method}", f"Δ{what} ({units})", labels, [rel[(x.system, x.source, x.state)] * f for x in group], group.index(r)))

    def csv_text(self) -> str:
        return results.compare_csv(self.rows, self.units.currentText(), self.done_quantity, self.done_temp, self.provs, self.done_settings) if self.rows else ""

    def copy_csv(self) -> None:
        if self.rows: QGuiApplication.clipboard().setText(self.csv_text())

    def save_plot(self) -> None:
        if self.canvas.last is None: return
        path, _ = QFileDialog.getSaveFileName(self, "Save the plot", os.path.join(os.path.expanduser("~"), "compare.png"), PLOT_FILTER)
        what = {"quantity": "electronic energy" if self.done_quantity == "energy" else f"G at {self.done_temp:g} K"} | self.done_settings | {"units": self.units.currentText()}
        if path: self.canvas.save(path, results.plot_metadata(self.provs, what, getattr(self.canvas.last, "title", "")))

CHANGE_TEXT = {"": "", "new": "new state", "gone": "not in the current file", "computed": "computed since", "energy": "energy changed", "status": "status changed", "runs": "more runs"}

class VersionDialog(QDialog):
    """An older copy of a system file (<system>.npy.bak-<time>, kept by a download) beside the current file, read-only: one row per state
    with its energy, status and runs in each. The copy is read like the current file (paths pointed at this computer) and never reloaded."""
    def __init__(self, page: "ResultsTab", path: str):
        super().__init__(page); self.page, self.path, self.old, self.task = page, path, None, None
        current = page.loaded; self.setWindowTitle(f"{current.provenance.system}: older copy {os.path.basename(path)}"); self.resize(1100, 600)
        self.head = QLabel(f"Reading <code>{path}</code>…"); self.head.setWordWrap(True); self.head.setTextFormat(Qt.RichText); self.head.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.table = QTableWidget(0, 9); self.table.setHorizontalHeaderLabels(["Source", "State", "Energy then (Eh)", "Energy now (Eh)", "Δ (kcal/mol)", "Status then", "Status now", "Runs then → now", "Change"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers); self.table.verticalHeader().setVisible(False)
        hh = self.table.horizontalHeader(); [hh.setSectionResizeMode(i, QHeaderView.ResizeToContents) for i in range(9)]; hh.setSectionResizeMode(7, QHeaderView.Stretch)
        self.only = QCheckBox("Only states that changed"); self.only.toggled.connect(self.fill)
        nb = QPushButton("Open this copy in a notebook"); nb.clicked.connect(lambda: self.page.open_notebook(file=self.path) if self.old else None)
        close = QPushButton("Close"); close.clicked.connect(self.accept)
        row = QHBoxLayout(); row.addWidget(self.only); row.addStretch(1); row.addWidget(nb); row.addWidget(close)
        lay = QVBoxLayout(self); lay.addWidget(self.head); lay.addWidget(self.table, 1); lay.addLayout(row)
        env_path, name = page.session.info.filepath, current.provenance.system
        self.task = Task(lambda: results.load(env_path, name, path)); self.task.signals.done.connect(self.loaded); self.task.signals.failed.connect(self.failed)
        QThreadPool.globalInstance().start(self.task)

    def loaded(self, old: "results.Loaded") -> None:
        self.task, self.old = None, old; o, n = old.provenance, self.page.loaded.provenance
        when = lambda p: time.strftime("%d %b %Y %H:%M", time.localtime(p.mtime))
        self.head.setText(f"<b>Then</b>: <code>{os.path.basename(o.file)}</code> ({when(o)}, saved by SCOPE {o.saved_version or '?'}, {o.size / 1e6:.2f} MB) &nbsp;·&nbsp; "
                          f"<b>Now</b>: <code>{os.path.basename(n.file)}</code> ({when(n)}, saved by SCOPE {n.saved_version or '?'}, {n.size / 1e6:.2f} MB). Both read-only.")
        self.rows = results.version_diff(old.summary, self.page.loaded.summary); self.fill()

    def failed(self, message: str) -> None:
        self.task = None; self.head.setText(f"Cannot read the copy: {message.replace('ResultsError: ', '')}"); theme.set_kind(self.head, "err")

    def fill(self) -> None:
        if self.old is None: return
        rows = [r for r in self.rows if r.change or not self.only.isChecked()]; f = results.UNITS["kcal/mol"]; c = theme.colors()
        e = lambda v: "—" if v is None else f"{v:.8f}"
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            de = "" if r.old_energy is None or r.new_energy is None else f"{(r.new_energy - r.old_energy) * f:.3f}"
            runs = f"{len(r.old_runs) if r.old_runs is not None else '—'} → {len(r.new_runs) if r.new_runs is not None else '—'}"
            cells = [item(r.source), item(r.state), item(e(r.old_energy), "", "", True), item(e(r.new_energy), "", "", True), item(de, "", "", True),
                     item(r.old_group or "—", "", group_colour(r.old_group or "none")), item(r.new_group or "—", "", group_colour(r.new_group or "none")),
                     item(runs, f"then: {', '.join(r.old_runs or [])}\nnow: {', '.join(r.new_runs or [])}"), item(CHANGE_TEXT.get(r.change, r.change), "", c["warn"] if r.change else "")]
            for j, cell in enumerate(cells): self.table.setItem(i, j, cell)

class ResultsTab(QWidget):
    """Step 6. Attributes: loaded (results.Loaded or None), shown_print (fingerprint of the file shown), task (the load in progress)."""
    def __init__(self, session, window=None):
        super().__init__()
        self.session, self.window_, self.loaded, self.shown_print, self.task, self.pending, self.viewers = session, window, None, (), None, None, []
        from scope.gui.plots import ElidedLabel
        self.systems = QListWidget(); self.systems.setObjectName("navlist"); self.systems.currentTextChanged.connect(self.select)
        self.title   = QLabel(); self.title.setObjectName("restitle")
        self.prov    = QLabel(); self.prov.setWordWrap(True); self.prov.setTextFormat(Qt.RichText); self.prov.setTextInteractionFlags(Qt.TextSelectableByMouse); self.prov.setObjectName("pagesub"); self.prov.setMinimumWidth(10)
        self.message = ElidedLabel()                                                                   ## one line for what an action just did (coloured by kind)
        self.banner  = QLabel(); self.banner.setWordWrap(True); self.banner.hide()
        self.issues  = QLabel(); self.issues.setWordWrap(True); self.issues.setTextFormat(Qt.RichText); self.issues.hide()
        self.notes, self.notes_open, self.notes_warn = [], False, False
        self.issues.linkActivated.connect(lambda _: (setattr(self, "notes_open", not self.notes_open), self.render_notes()))
        ## Overview
        self.units = QComboBox(); self.units.addItems(list(results.UNITS)[1:]); self.units.currentTextChanged.connect(self.fill_overview)
        self.table = QTableWidget(0, 9); self.table.setHorizontalHeaderLabels(["Source", "State", "Method", "Energy (Eh)", "ΔE", "Min.", "Imag.", "Runs", "Status"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers); self.table.setSelectionBehavior(QAbstractItemView.SelectRows); self.table.verticalHeader().setVisible(False)
        self.table.setTextElideMode(Qt.ElideRight); self.table.setWordWrap(False)
        hh = self.table.horizontalHeader(); [hh.setSectionResizeMode(i, QHeaderView.ResizeToContents) for i in range(9)]; hh.setSectionResizeMode(7, QHeaderView.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.Interactive); hh.resizeSection(2, 130); hh.setMinimumSectionSize(40)                      ## the method elides; Runs takes what is left
        de_note = ElidedLabel("ΔE is measured within the same formula and method (other energies are not comparable)  ·  double-click a state to open it"); de_note.setObjectName("pagesub")
        urow = hrow("ΔE in", self.units, stretch=False); urow.addSpacing(12); urow.addWidget(de_note, 1)
        over = QWidget(); ol = QVBoxLayout(over); ol.setContentsMargins(10, 10, 10, 10); ol.setSpacing(8); ol.addLayout(urow); ol.addWidget(self.table, 1)
        ## Computations
        self.tree = QTreeWidget(); self.tree.setColumnCount(7); self.tree.setHeaderLabels(["Calculation", "Status", "Reads → writes", "Wall time", "CPU time", "Output", "Method"])
        self.tree.itemDoubleClicked.connect(self.open_item); self.tree.header().setSectionResizeMode(QHeaderView.ResizeToContents)
        open_log = QPushButton("Open output"); open_log.clicked.connect(lambda: self.open_item(self.tree.currentItem()))
        tip = ElidedLabel("Double-click a calculation to read its output  ·  r2, r3… continue a run that stopped or failed  ·  s2, s3… are steps of a repeated job"); tip.setObjectName("pagesub")
        crow = QHBoxLayout(); crow.addWidget(tip, 1); crow.addWidget(open_log)
        comps = QWidget(); cl = QVBoxLayout(comps); cl.setContentsMargins(10, 10, 10, 10); cl.setSpacing(8); cl.addLayout(crow); cl.addWidget(self.tree, 1)
        self.state = StatePanel(self)
        self.thermo, self.compare = ThermoPanel(self), ComparePanel(self)
        self.tabs = QTabWidget(); self.tabs.addTab(over, "Overview"); self.tabs.addTab(comps, "Calculations"); self.tabs.addTab(scrolled(self.state), "State")
        self.tabs.addTab(scrolled(self.thermo), "Thermochemistry"); self.tabs.addTab(scrolled(self.compare), "Compare")
        self.table.cellDoubleClicked.connect(self.open_state); self.table.setToolTip("Double-click a state to see it in detail (State tab)")
        ## Actions
        self.reload_btn, self.folder_btn, self.missing_btn = QPushButton("Reload"), QPushButton("Show folder"), QPushButton("Download missing outputs…")
        self.reload_btn.clicked.connect(lambda: self.load(force=True)); self.folder_btn.clicked.connect(self.show_folder); self.missing_btn.clicked.connect(self.download_missing)
        self.missing_btn.setToolTip("Opens the download of the Cluster page with the outputs that SCOPE registered but that are not on this computer already ticked.")
        def menu_button(text: str, tip: str, entries: list, main=None) -> QToolButton:
            """A button with a menu; with `main`, a click on the button does it and the arrow opens the menu."""
            b = QToolButton(); b.setText(text); b.setToolTip(tip); m = QMenu(b); [m.addAction(t, f) for t, f in entries]; b.setMenu(m)
            b.setPopupMode(QToolButton.MenuButtonPopup if main else QToolButton.InstantPopup)
            if main: b.clicked.connect(main)
            return b
        self.export_btn = menu_button("Export", "The table of the current tab as CSV, with where its numbers come from in the first lines",
                                      [("Copy table (CSV)", self.copy_csv), ("Save table as CSV…", self.export_table)])
        self.notebook_btn = menu_button("Open in notebook", "Writes a new Jupyter notebook for this system in <project>/Notebooks/ and opens it in Jupyter Lab, with the Python of this window.\n"
                                        "The arrow: copy the code that opens this system as this page does (for VS Code or any other editor).",
                                        [("Copy code (the notebook's first cell)", self.copy_code)], lambda: self.open_notebook())
        self.older_btn = QToolButton(); self.older_btn.setText("Older copies"); self.older_btn.setPopupMode(QToolButton.InstantPopup); self.older_menu = QMenu(self.older_btn); self.older_btn.setMenu(self.older_menu)
        self.older_btn.setToolTip("Copies of this system file kept by downloads (<system>.npy.bak-<time>): open one beside the current file")
        actions = QHBoxLayout(); actions.setSpacing(8); [actions.addWidget(b) for b in (self.reload_btn, self.folder_btn, self.export_btn, self.older_btn)]
        actions.addStretch(1); [actions.addWidget(b) for b in (self.notebook_btn, self.missing_btn)]
        self.message.hide()
        self.jupyter, self.jupyter_root, self.jupyter_pending, self.dialogs = None, "", [], []           ## the Jupyter Lab this window started, the folder it serves, notebooks to open once it is up
        self.jupyter_timer = QTimer(self); self.jupyter_timer.setInterval(1000); self.jupyter_timer.timeout.connect(self.poll_jupyter); self.jupyter_waited = 0
        head = QVBoxLayout(); head.setSpacing(2); head.setContentsMargins(2, 0, 2, 0); head.addWidget(self.title); head.addWidget(self.prov); head.addWidget(self.issues)
        right = QWidget(); rl = QVBoxLayout(right); rl.setContentsMargins(0, 0, 0, 0); rl.setSpacing(10)
        rl.addLayout(head); rl.addWidget(self.banner); rl.addWidget(self.tabs, 1); rl.addLayout(actions); rl.addWidget(self.message)
        side = card(self.systems, title="Systems"); side.setFixedWidth(140)
        lay = QHBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(14); lay.addWidget(side); lay.addWidget(right, 1)
        self.timer = QTimer(self); self.timer.setInterval(2500); self.timer.timeout.connect(self.watch)
        session.systemsChanged.connect(self.refresh_systems); session.envChanged.connect(self.refresh_systems)
        theme.on_change(self.redraw)
        self.refresh_systems()

    ##### systems #####
    def refresh_systems(self) -> None:
        current = self.systems.currentItem().text() if self.systems.currentItem() else ""
        names = [r.name for r in self.session.systems()] if self.session.info else []
        self.systems.blockSignals(True); self.systems.clear(); self.systems.addItems(names); self.systems.blockSignals(False)
        self.compare.set_systems(names, names[0] if names and current not in names else current)
        if not names: self.clear("No system in this workspace yet. Import one on the Systems page." if self.session.info else "Open or create an environment first (step 1)."); return
        keep = current if current in names else names[0]
        self.systems.blockSignals(True); self.systems.setCurrentRow(names.index(keep)); self.systems.blockSignals(False)
        self.load(force=True)                                                           ## after a download or a run: read the file again

    def select(self, name: str) -> None:
        if name: self.load(force=True)

    def current(self) -> str:
        return self.systems.currentItem().text() if self.systems.currentItem() else ""

    def clear(self, message: str) -> None:
        self.loaded, self.shown_print = None, ()
        self.title.setText(self.current() or "Results"); self.prov.setText(message); self.banner.hide(); self.issues.hide(); self.table.setRowCount(0); self.tree.clear(); self.state.set_loaded(None); self.thermo.set_loaded(None)
        for b in (self.reload_btn, self.folder_btn, self.missing_btn, self.notebook_btn, self.export_btn, self.older_btn): b.setEnabled(False)

    ##### loading (worker thread) #####
    def load(self, force: bool=False) -> None:
        name = self.current()
        if not name or not self.session.info: return
        if self.task is not None: self.pending = name; return                          ## one load at a time; the latest wish wins
        if not force and self.loaded and self.loaded.provenance.system == name and results.fingerprint(self.loaded.provenance.file) == self.shown_print: return
        env_path = self.session.info.filepath
        self.title.setText(name); self.prov.setText("Reading the system file…"); self.task = Task(lambda: results.load(env_path, name))
        self.task.signals.done.connect(self.loaded_ok); self.task.signals.failed.connect(lambda m, n=name: self.loaded_failed(n, m))
        QThreadPool.globalInstance().start(self.task)

    def finish_task(self) -> bool:
        """Ends the current load; starts the one asked for meanwhile, if any. True if the result just received is still wanted."""
        self.task = None; wanted = self.pending is None
        if self.pending is not None: self.pending = None; self.load(force=True)
        return wanted

    def loaded_ok(self, loaded: "results.Loaded") -> None:
        if not self.finish_task() or loaded.provenance.system != self.current(): return
        self.loaded, self.shown_print = loaded, results.fingerprint(loaded.provenance.file)
        self.show_provenance(); self.fill_overview(); self.fill_tree(); self.state.set_loaded(loaded); self.thermo.set_loaded(loaded); self.watch(); self.timer.start()
        for b in (self.reload_btn, self.folder_btn, self.notebook_btn, self.export_btn): b.setEnabled(True)
        self.missing_btn.setEnabled(bool(loaded.summary.missing_outputs)); self.fill_older()
        if self.window_ is not None and hasattr(self.window_, "update_steps"): self.window_.update_steps()          ## the step dot: results shown

    def loaded_failed(self, name: str, message: str) -> None:
        if not self.finish_task(): return
        self.clear(f"<b>{name}</b>: the results cannot be shown.")
        self.issues.setText(message.replace("ResultsError: ", "")); theme.set_kind(self.issues, "err"); self.issues.show()
        self.reload_btn.setEnabled(True)

    ##### provenance and checks #####
    def show_provenance(self) -> None:
        p, s = self.loaded.provenance, self.loaded.summary; c = theme.colors()
        when = time.strftime("%d %b %Y %H:%M", time.localtime(p.mtime))
        done, total = s.counts()
        self.title.setText(p.label)
        version = f"SCOPE {p.saved_version or '?'}" + (f" → {p.local_version}" if p.version_differs else "")
        facts = [f"<span style='color:{c['text']}'>{done} of {total} sources with results</span>", self.short_path(p.file), when, f"{p.size / 1e6:.1f} MB", version]
        self.prov.setText(" &nbsp;·&nbsp; ".join(facts)); self.prov.setToolTip(f"System file: {p.file}\nEnvironment: {p.env_file}\nSaved by SCOPE {p.saved_version or '?'}, read with SCOPE {p.local_version or '?'}")
        notes, copies = [], f"{len(p.backups)} older cop{'y' if len(p.backups) == 1 else 'ies'}"                ## (short label, full text)
        if p.moved: notes.append(("from another computer", f"The file was written where SCOPE ran (<code>{p.stored_root}</code>); its paths are pointed at this computer's folders for reading. Nothing is changed on disk."))
        if p.version_differs: notes.append((f"saved by SCOPE {p.saved_version}", f"Saved by SCOPE {p.saved_version}, read by {p.local_version}: values are read as stored, but objects from very different versions may miss newer fields."))
        if s.missing_outputs: notes.append((f"{len(s.missing_outputs)} outputs not here", f"{len(s.missing_outputs)} output file(s) are not on this computer (still running, not downloaded, or not started). Energies and frequencies are in the system file; reading an output needs it here. Use <i>Download missing outputs…</i>."))
        if p.rdkit_note: notes.append(("newer RDKit", p.rdkit_note + " Usually harmless: energies and frequencies are SCOPE's own numbers."))
        if p.backups: notes.append((copies, f"{copies} of this system file kept by downloads (newest: {os.path.basename(p.backups[0])})."))
        self.notes, self.notes_warn = notes, bool(s.missing_outputs or p.version_differs); theme.set_kind(self.issues, ""); self.render_notes()

    def short_path(self, path: str) -> str:
        """`path` relative to the project folder when it is inside it (Systems/water/water.npy), otherwise as it is."""
        try:
            root = notebooks.project_folder(self.session.info); rel = os.path.relpath(path, root)
            return path if rel.startswith("..") else rel
        except Exception: return path

    def render_notes(self) -> None:
        """The notes about the file shown, folded to one line by default (they matter, but should not push the results off the screen)."""
        n = len(self.notes); self.issues.setVisible(bool(n))
        if not n: return
        colour = theme.colors()["warn" if self.notes_warn else "sub"]
        if self.notes_open: self.issues.setText(f"<span style='color:{colour}'>" + "<br>".join("• " + full for _, full in self.notes) + "</span> &nbsp;<a href='fold'>hide</a>")
        else: self.issues.setText(f"<span style='color:{colour}'>⚑ " + " · ".join(short for short, _ in self.notes) + "</span> &nbsp;<a href='open'>details</a>")

    def watch(self) -> None:
        """Runs every few seconds while the page has a system: reloads when the file changed, and says when a run of it is going on."""
        if not self.loaded or not self.session.info: return
        p = self.loaded.provenance
        try: active = backend.active_local_run(self.session.info.filepath, p.system)
        except Exception: active = None
        if active: self.banner.setText(f"A run of '{p.system}' is going on (started {time.strftime('%H:%M', time.localtime(active.get('started', time.time())))}). The results are reloaded when it saves the system file."); theme.set_kind(self.banner, "warn")
        self.banner.setVisible(bool(active))
        if not self.isVisible(): return
        now = results.fingerprint(p.file)
        if now != self.shown_print and self.task is None:
            if not now: self.clear(f"The system file of <b>{p.system}</b> is gone: {p.file}"); return
            self.load(force=True)

    def showEvent(self, event) -> None:
        super().showEvent(event); self.watch()

    ##### tables #####
    def fill_overview(self) -> None:
        if not self.loaded: return
        rows = self.loaded.summary.states; units = self.units.currentText(); factor = results.UNITS[units]; rel = results.relative_energies(rows)
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            de = rel.get((r.source, r.state)); colour = group_colour(r.group); sub = theme.colors()["sub"]
            energy = item(f"{r.energy:.8f}" if r.energy is not None else "—", r.energy_note or "Energy as registered by SCOPE, in Hartree", "" if r.energy is not None else sub, True)
            minimum = "" if r.minimum is None else ("yes" if r.minimum else "no")
            status = {"none": "no calculation", "waiting": "waiting / not here"}.get(r.group, r.group) + (" (after a retry)" if r.retried else "")
            cells = [item(r.source, f"{r.source_type} {r.formula}"), item(r.state), item(r.method, "As asked for in SCOPE's input", sub), energy,
                     item("" if de is None else f"{de * factor:.2f}", f"ΔE in {units}", "", True),
                     item(minimum, "From the frequencies: no imaginary frequency" if r.minimum else ("Has imaginary frequencies" if r.minimum is False else "No frequencies computed"), theme.colors()["err"] if r.minimum is False else ""),
                     item(str(r.n_imag) if r.n_freqs else "", f"{r.n_freqs} frequencies", theme.colors()["err"] if r.n_imag else "", True),
                     item(", ".join(r.runs), (", ".join(r.runs) + "\n" if r.runs else "") + "Calculations that wrote this state, in order. The values come from the last one."), item(f"{GROUP_WORD.get(r.group, '?')} {status}", "", colour)]
            for j, cell in enumerate(cells): self.table.setItem(i, j, cell)
        self.table.horizontalHeaderItem(4).setText(f"ΔE ({units})")

    def fill_tree(self) -> None:
        self.tree.clear()
        if not self.loaded: return
        parents = {}
        for c in self.loaded.summary.comps:
            key = (c.branch, c.workflow)
            if key not in parents:
                if c.branch not in parents: parents[c.branch] = QTreeWidgetItem(self.tree, [f"branch {c.branch}"]); parents[c.branch].setExpanded(True)
                parents[key] = QTreeWidgetItem(parents[c.branch], [c.workflow]); parents[key].setExpanded(True)
            out = "here" if c.out_exists else "not here"
            it = QTreeWidgetItem(parents[key], [c.label, f"{GROUP_WORD.get(c.group, '?')} {c.status_text}", f"{c.istate} → {c.fstate}", seconds(c.elapsed), seconds(c.cpu), out, f"{c.software} {c.comp_type}"])
            it.setForeground(1, QBrush(QColor(group_colour(c.group)))); it.setForeground(5, QBrush(QColor(theme.colors()["sub" if c.out_exists else "warn"])))
            it.setToolTip(5, c.out_path); it.setData(0, Qt.UserRole, c.out_path)
        for i in range(self.tree.columnCount()): self.tree.resizeColumnToContents(i)

    def redraw(self) -> None:
        if self.loaded: self.show_provenance(); self.fill_overview(); self.fill_tree()

    ##### actions #####
    def open_item(self, it: "QTreeWidgetItem | None", _column: int=0) -> None:
        path = it.data(0, Qt.UserRole) if it is not None else None
        if not path: return
        if not os.path.isfile(path): self.say(f"The output is not on this computer: {path}. Use Download missing outputs…", "warn"); return
        viewer = LogViewer(self, path, f"{it.text(0)} · {os.path.basename(path)}"); self.viewers = [v for v in self.viewers if v.isVisible()] + [viewer]; viewer.show()

    def open_state(self, row: int, _column: int=0) -> None:
        if self.loaded and 0 <= row < len(self.loaded.summary.states):
            r = self.loaded.summary.states[row]; self.state.show_state(r.source, r.state); self.tabs.setCurrentIndex(2)

    def show_folder(self) -> None:
        if self.loaded: QDesktopServices.openUrl(QUrl.fromLocalFile(self.loaded.provenance.local_root))

    def copy_csv(self) -> None:
        """The table of the current tab on the clipboard, as CSV with its provenance."""
        name, text = self.current_export()
        if text: QGuiApplication.clipboard().setText(text)
        else: self.say("Nothing to copy in this tab yet.", "warn")

    def download_missing(self) -> None:
        if not self.loaded or self.window_ is None: return
        self.window_.remote_tab.open_download(system=self.loaded.provenance.system, wanted=self.loaded.summary.missing_outputs)

    ##### older copies #####
    def fill_older(self) -> None:
        self.older_menu.clear(); backups = self.loaded.provenance.backups if self.loaded else []
        for path in backups:
            when = time.strftime("%d %b %Y %H:%M:%S", time.localtime(os.path.getmtime(path))) if os.path.exists(path) else "?"
            self.older_menu.addAction(f"{os.path.basename(path)}  ({when})", lambda p=path: self.open_copy(p))
        self.older_btn.setEnabled(bool(backups)); self.older_btn.setText(f"Older copies ({len(backups)})" if backups else "Older copies")

    def open_copy(self, path: str) -> "VersionDialog | None":
        if not self.loaded or not self.session.info: return None
        dialog = VersionDialog(self, path); self.dialogs = [d for d in self.dialogs if d.isVisible()] + [dialog]; dialog.show()
        return dialog

    ##### exports #####
    def current_export(self) -> tuple:
        """(suggested file name, CSV text) of the table of the current tab; ('', '') when it shows nothing."""
        if not self.loaded: return "", ""
        p = self.loaded.provenance; i = self.tabs.currentIndex()
        if i == 0: return f"{p.system}_overview.csv", results.overview_csv(self.loaded.summary.states, self.units.currentText(), p)
        if i == 1: return f"{p.system}_calculations.csv", results.comps_csv(self.loaded.summary.comps, p)
        if i == 2: return self.state.export()
        if i == 3: return (f"{p.system}_thermo.csv", self.thermo.csv_text()) if self.thermo.result else ("", "")
        if i == 4: return ("compare.csv", self.compare.csv_text()) if self.compare.rows else ("", "")
        return "", ""

    def export_table(self) -> None:
        name, text = self.current_export()
        if not text: self.say("Nothing to export in this tab yet.", "warn"); return
        path, _ = QFileDialog.getSaveFileName(self, "Export the table", os.path.join(os.path.expanduser("~"), name), "CSV files (*.csv)")
        if not path: return
        with open(path, "w", encoding="utf-8", newline="") as fh: fh.write(text)
        self.say(f"Saved {path}.", "")

    def say(self, html: str, kind: str) -> None:
        """What an action just did, on one line of the action bar (cut to the room it has; the whole text is its tooltip)."""
        import re
        text = re.sub(r"<[^>]+>", "", html).replace("&nbsp;", " ")
        self.message.set_full(text); theme.set_kind(self.message, kind); self.message.setVisible(bool(text))

    ##### notebooks #####
    def copy_code(self) -> None:
        if self.loaded and self.session.info: QGuiApplication.clipboard().setText(notebooks.setup_code(self.session.info.filepath, self.loaded.provenance.system))

    def open_notebook(self, file: str="") -> "str | None":
        """Writes a new notebook for the system shown (or for an older copy of its file) and opens it in Jupyter Lab. Returns its path."""
        if not self.loaded or not self.session.info: return None
        info, system = self.session.info, self.loaded.provenance.system
        state = self.state.keys[self.state.chooser.currentIndex()] if 0 <= self.state.chooser.currentIndex() < len(self.state.keys) else None
        pair = (self.thermo.a.currentData(), self.thermo.b.currentData()) if self.thermo.a.currentData() and self.thermo.b.currentData() else None
        folder = notebooks.notebooks_dir(info)
        kernel = notebooks.ensure_kernel()                                             ## 'SCOPE GUI' kernel: this window's Python, for any Jupyter
        try: path = notebooks.write_new(folder, notebooks.build(info.filepath, system, state, pair, file, kernel), system)
        except Exception as exc: self.say(f"Cannot write the notebook in {folder}: {type(exc).__name__}: {exc}", "err"); return None
        missing = notebooks.jupyter_missing()
        if missing: self.say(f"Notebook written: <code>{path}</code>. Jupyter Lab is not installed in this window's Python; install it with <code>{missing}</code>, or open the file in VS Code.", "warn"); return path
        self.launch(path, folder)
        return path

    def launch(self, path: str, root: str) -> None:
        """Opens `path` in a running Jupyter Lab that serves `root` (this window's, or one kept from before). While this window's server is
        still starting, the notebook waits for it; a server of another project is stopped first (one per window); otherwise one is started."""
        server = notebooks.running_server(root)
        if server:
            QDesktopServices.openUrl(QUrl(notebooks.notebook_url(server, root, path)))
            self.say(f"Notebook written and opened in the running Jupyter Lab: <code>{path}</code>", ""); return
        if self.jupyter_running() and self.jupyter_root == root:
            self.jupyter_pending.append(path); self.jupyter_timer.start()
            self.say(f"Notebook written: <code>{path}</code>. Jupyter Lab is still starting; the notebook opens as soon as it is up.", ""); return
        if self.jupyter_running(): self.stop_jupyter()
        program, args = notebooks.jupyter_command(path, root)
        log = os.path.join(root, ".jupyter-scope-gui.log")
        try: self.jupyter = notebooks.spawn(program, args, notebooks.jupyter_environment(os.environ), log)
        except OSError as exc: self.say(f"Cannot start Jupyter Lab: {exc}. The notebook is <code>{path}</code>.", "err"); return
        self.jupyter_root, self.jupyter_pending, self.jupyter_waited = root, [], 0; self.jupyter_timer.start()       ## Jupyter opens `path` itself once it is up
        self.say(f"Notebook written: <code>{path}</code>. Jupyter Lab is starting and opens it in your browser (its messages: <code>{log}</code>).", "")

    def poll_jupyter(self) -> None:
        """Every second while this window's Jupyter Lab starts: opens the notebooks written meanwhile once it is up, or says it failed."""
        self.jupyter_waited += 1
        if not self.jupyter_running():
            self.jupyter_timer.stop(); self.say(f"Jupyter Lab stopped. Its messages are in <code>{os.path.join(self.jupyter_root, '.jupyter-scope-gui.log')}</code>.", "err"); return
        server = notebooks.running_server(self.jupyter_root)
        if server:
            self.jupyter_timer.stop()
            for path in self.jupyter_pending: QDesktopServices.openUrl(QUrl(notebooks.notebook_url(server, self.jupyter_root, path)))
            self.jupyter_pending = []
        elif self.jupyter_waited > 120: self.jupyter_timer.stop(); self.say(f"Jupyter Lab has not started after 2 minutes. Its messages are in <code>{os.path.join(self.jupyter_root, '.jupyter-scope-gui.log')}</code>.", "warn")

    def jupyter_running(self) -> bool:
        """The Jupyter Lab this window started still runs (starting, or up)."""
        try: return self.jupyter is not None and self.jupyter.poll() is None
        except OSError: return False

    def stop_jupyter(self) -> None:
        if self.jupyter is not None: notebooks.stop(self.jupyter)
        self.jupyter, self.jupyter_pending = None, []; self.jupyter_timer.stop()

    def close_jupyter(self) -> bool:
        """At window close: asks whether to stop the Jupyter Lab this window started. False if the user cancels the close."""
        if not self.jupyter_running(): self.jupyter = None; return True
        box = QMessageBox(self.window_ or self); box.setWindowTitle("Jupyter Lab is running"); box.setIcon(QMessageBox.Question)
        box.setText("Jupyter Lab, started from this window, is still running.\n\nSave your notebooks in the browser before stopping it.")
        stop = box.addButton("Stop it and close", QMessageBox.AcceptRole); keep = box.addButton("Keep it running", QMessageBox.DestructiveRole); box.addButton(QMessageBox.Cancel)
        box.setDefaultButton(stop); box.exec(); chosen = box.clickedButton()
        if chosen is stop: self.stop_jupyter(); return True
        if chosen is keep: self.jupyter = None; self.jupyter_timer.stop(); return True
        return False
