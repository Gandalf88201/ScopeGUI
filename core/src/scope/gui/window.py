"""Qt window of the SCOPE GUI: a left bar of five steps (Environment, Systems, Pipeline, Run, Cluster) plus a manual.

Requires PySide6. Heavy work is never done in the window thread. `scope run` is started detached (its own session, no pipe to the
window, output in a log file), so closing or crashing the window does not stop it; the window follows the log and finds a run again when reopened.
"""
import os
import sys
import time
from PySide6.QtCore    import Qt, QObject, QThreadPool, QTimer, Signal
from PySide6.QtGui     import QBrush, QColor, QGuiApplication, QPainter, QPalette, QPen, QPolygonF
from PySide6.QtCore    import QPointF
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QDialog, QFrame, QInputDialog, QMenu, QScrollArea, QStackedWidget, QComboBox, QFileDialog, QFormLayout, QGraphicsScene, QGraphicsView, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox,
                               QPlainTextEdit, QPushButton, QSplitter, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget, QHeaderView, QAbstractItemView)
from scope.gui import backend, theme, updates, workspaces
from scope.gui.tasks import Task

#################
### Session   ###
#################
class Session(QObject):
    """State shared by the tabs: current environment, input reports. Signals tell the tabs to refresh."""
    envChanged      = Signal()
    systemsChanged  = Signal()
    inputsChanged   = Signal()
    message         = Signal(str)
    progressChanged = Signal()

    def __init__(self):
        super().__init__()
        self.env      = None
        self.info     = None
        self.reports  = []
        self.progress = {"ran": False, "cluster": False}
        self._systems = None
        self.envChanged.connect(self.forget_systems); self.systemsChanged.connect(self.forget_systems)      ## connected first, so it runs before the tabs refresh

    def mark(self, key: str, value: bool=True) -> None:
        """Records that a step was completed (a run finished, a cluster test passed) so the left bar can show it."""
        if self.progress.get(key) != value: self.progress[key] = value; self.progressChanged.emit()

    def clear(self) -> None:
        """Forgets the environment, the inputs and the step dots (an empty workspace, or before another workspace is loaded)."""
        self.env, self.info, self.reports, self.progress = None, None, [], {"ran": False, "cluster": False}
        self.envChanged.emit(); self.systemsChanged.emit(); self.inputsChanged.emit(); self.progressChanged.emit()

    def set_environment(self, env: object, info: object) -> None:
        self.env, self.info = env, info
        backend.save_gui_config({"last_env": info.filepath})
        self.envChanged.emit(); self.systemsChanged.emit()

    def add_inputs(self, paths: list) -> None:
        known = {r.path for r in self.reports}
        for p in paths:
            p = os.path.abspath(p)
            if p in known: self.reports = [r for r in self.reports if r.path != p]
            self.reports.append(backend.read_input(p))
        self.inputsChanged.emit()

    def remove_input(self, path: str) -> None:
        self.remove_inputs([path])

    def remove_inputs(self, paths: list) -> None:
        drop = set(paths); self.reports = [r for r in self.reports if r.path not in drop]
        self.inputsChanged.emit()

    def systems(self) -> list:
        """The systems of the current environment (backend.list_systems), scanned once after each change instead of once per tab."""
        if self._systems is None: self._systems = backend.list_systems(self.info) if self.info else []
        return self._systems

    def forget_systems(self) -> None:
        self._systems = None

set_kind = theme.set_kind

def folder_row(edit: QLineEdit, parent: QWidget) -> QWidget:
    """A line edit with a Browse button that opens a folder picker."""
    box = QWidget(); lay = QHBoxLayout(box); lay.setContentsMargins(0, 0, 0, 0)
    button = QPushButton("Browse…")
    def pick():
        start = edit.text() or os.path.expanduser("~")
        folder = QFileDialog.getExistingDirectory(parent, "Select folder", start)
        if folder: edit.setText(folder)
    button.clicked.connect(pick)
    lay.addWidget(edit, 1); lay.addWidget(button)
    return box

#######################
### Environment tab ###
#######################
class EnvironmentTab(QWidget):
    def __init__(self, session: Session):
        super().__init__()
        self.session = session
        self.name    = QLineEdit("demo")
        self.root    = QLineEdit(); self.root.setPlaceholderText("Project folder: Sources, Systems and Computations are created inside")
        self.sources = QLineEdit(); self.systems = QLineEdit(); self.comps = QLineEdit(); self.savedir = QLineEdit()
        self.root.textChanged.connect(self.fill_from_root)            ## textChanged, not editingFinished: the Browse button sets the text without finishing an edit
        form = QFormLayout()
        form.addRow("Name", self.name)
        form.addRow("Project folder", folder_row(self.root, self))
        form.addRow("Sources", folder_row(self.sources, self)); form.addRow("Systems", folder_row(self.systems, self)); form.addRow("Computations", folder_row(self.comps, self))
        form.addRow("Save environment file in", folder_row(self.savedir, self))
        create = QPushButton("Create local environment"); create.setProperty("primary", True); create.clicked.connect(self.create)
        opens  = QPushButton("Open existing environment…"); opens.clicked.connect(self.open_existing)
        row = QHBoxLayout(); row.addWidget(create); row.addWidget(opens); row.addStretch(1)
        self.summary = QPlainTextEdit(); self.summary.setReadOnly(True)
        note = QLabel("Cluster settings (scheduler, queues, modules) are created on the cluster with `scope config`. This tab only creates local environments.")
        note.setWordWrap(True)
        lay = QVBoxLayout(self); lay.addLayout(form); lay.addLayout(row); lay.addWidget(note); lay.addWidget(self.summary, 1)
        session.envChanged.connect(self.show_summary)

    def fill_from_root(self) -> None:
        root = self.root.text().strip()
        if not root: return
        for edit, sub in ((self.sources, "Sources"), (self.systems, "Systems"), (self.comps, "Computations")): edit.setText(os.path.join(root, sub))
        self.savedir.setText(root)

    def create(self) -> None:
        if self.root.text().strip() and not (self.sources.text().strip() and self.systems.text().strip() and self.comps.text().strip() and self.savedir.text().strip()): self.fill_from_root()
        try:
            env, info = backend.create_environment(self.name.text(), self.sources.text(), self.systems.text(), self.comps.text(), self.savedir.text())
        except Exception as exc:
            QMessageBox.warning(self, "Cannot create environment", str(exc)); return
        self.session.set_environment(env, info)

    def open_existing(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open environment (a pickle file: open only files you trust)", self.savedir.text() or os.path.expanduser("~"), "SCOPE environment (*.npy)")
        if path: self.load(path)

    def load(self, path: str) -> bool:
        try: env, info = backend.load_environment(path)
        except Exception as exc:
            QMessageBox.warning(self, "Cannot open environment", f"{type(exc).__name__}: {exc}"); return False
        self.session.set_environment(env, info); return True

    def show_summary(self) -> None:
        i = self.session.info
        if i is None:                                                                 ## an empty workspace: nothing to show, and no folders of another project left in the form
            self.root.blockSignals(True); [e.setText("") for e in (self.root, self.sources, self.systems, self.comps, self.savedir)]; self.root.blockSignals(False)
            self.summary.setPlainText("No environment in this workspace yet. Choose a project folder and press Create local environment, or open an existing environment."); return
        self.name.setText(i.name); self.root.blockSignals(True)                      ## show the loaded environment in the form (the root box is only a helper)
        self.sources.setText(i.sources_path); self.systems.setText(i.systems_path); self.comps.setText(i.computations_path); self.savedir.setText(os.path.dirname(i.filepath))
        common = os.path.commonpath([i.sources_path, i.systems_path, i.computations_path]) if i.sources_path and i.systems_path and i.computations_path else ""
        self.root.setText(common if common and os.path.dirname(i.sources_path.rstrip("/")) == common else ""); self.root.blockSignals(False)
        lines = [f"Environment:   {i.name}", f"File:          {i.filepath}", f"Scheduler:     {i.scheduler}", f"Sources:       {i.sources_path}", f"Systems:       {i.systems_path}", f"Computations:  {i.computations_path}"]
        if i.missing: lines.append(f"\nWARNING: folder(s) not found on this machine: {', '.join(i.missing)}. The environment was probably created on another computer.")
        if i.scheduler == "local": lines.append("\nLocal environment: SCOPE builds workflows and registers existing outputs, but does not write inputs or submit jobs.")
        if i.queues: lines.append("Queues:        " + ", ".join(i.queues))
        if any(i.modules.values()): lines.append(f"Modules:       {i.modules}")
        self.summary.setPlainText("\n".join(lines))

###################
### Systems tab ###
###################
class SystemsTab(QWidget):
    def __init__(self, session: Session):
        super().__init__()
        self.session = session
        self.rows    = []
        self.table   = QTableWidget(0, 4); self.table.setHorizontalHeaderLabels(["System", "Binary", "Finished branches", "Terminated branches"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows); self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.itemSelectionChanged.connect(self.show_details)
        from scope.gui.structure_view import StructurePanel
        self.structure = StructurePanel()                                        ## the structure SCOPE will compute: 3D view, formula, states, 2D drawing
        refresh = QPushButton("Refresh"); refresh.clicked.connect(session.systemsChanged.emit)          ## through the session, so the cached list is scanned again
        imp     = QPushButton("Import .xyz…"); imp.setProperty("primary", True); imp.clicked.connect(self.import_xyz)
        row = QHBoxLayout(); row.addWidget(imp); row.addWidget(refresh); row.addStretch(1)
        split = QSplitter(Qt.Vertical); split.addWidget(self.table); split.addWidget(self.structure); split.setStretchFactor(0, 1); split.setStretchFactor(1, 3)
        lay = QVBoxLayout(self); lay.addLayout(row); lay.addWidget(split, 1)
        session.systemsChanged.connect(self.refresh)

    def refresh(self) -> None:
        self.rows = self.session.systems()
        self.table.setRowCount(len(self.rows))
        for i, r in enumerate(self.rows):
            for j, text in enumerate([r.name, "yes" if r.file else "missing", ", ".join(r.finished), ", ".join(r.terminated)]): self.table.setItem(i, j, QTableWidgetItem(text))
        self.structure.clear("Import a system to see its structure here." if not self.rows else "")
        if self.rows: self.table.selectRow(0)                                     ## show a structure straight away

    def import_xyz(self) -> None:
        if not self.session.env: QMessageBox.information(self, "No environment", "Create or open an environment first."); return
        paths, _ = QFileDialog.getOpenFileNames(self, "Import .xyz files", self.session.info.sources_path, "XYZ files (*.xyz)")
        for p in paths:
            try: backend.import_xyz(self.session.env, p)
            except Exception as exc: QMessageBox.warning(self, "Import failed", f"{os.path.basename(p)}: {exc}")
        self.session.systemsChanged.emit()

    def show_details(self) -> None:
        """Shows the selected system: its structures (sources and states) in the structure panel, and SCOPE's own description under 'SCOPE details…'."""
        from scope.gui import structure
        sel = self.table.selectionModel().selectedRows()
        if not sel: return
        r = self.rows[sel[0].row()]
        try: details = backend.system_details(r.file) if r.file else "No system binary in this folder."
        except Exception as exc: details = f"Cannot read {r.file}\n{type(exc).__name__}: {exc}"
        found = structure.structures_for(r, self.session.info.sources_path if self.session.info else "")
        if found: self.structure.set_structures(found, details, r.name)
        else: self.structure.clear("No structure could be read for this system.", details)

####################
### Pipeline tab ###
####################
class GraphView(QGraphicsView):
    """Draws the pipeline left to right: one box per job, an arrow A -> B when B must wait for A to finish.

    Dashed red arrows mean A blocks B (constrains). A box with a dashed orange border is a job that no loaded file
    defines. A red badge marks a job that lists itself as a requisite (it would never start).
    """
    def __init__(self):
        self._scene = QGraphicsScene()                    ## kept in an attribute: PySide6 deletes a scene that only the view references
        super().__init__(self._scene)
        self.setRenderHint(QPainter.Antialiasing)
        self.setMinimumHeight(220)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event); self.fit()

    def fit(self) -> None:
        rect = self._scene.itemsBoundingRect()
        if rect.isEmpty(): return
        self.fitInView(rect.adjusted(-30, -30, 30, 30), Qt.KeepAspectRatio)
        if self.transform().m11() > 1.3: self.resetTransform(); self.scale(1.3, 1.3); self.centerOn(rect.center())

    def draw(self, reports: list) -> None:
        scene = self._scene; scene.clear()
        nodes, edges, cycles = backend.build_graph(reports)
        place  = backend.layout_graph(nodes, edges)
        c      = theme.colors()
        ink, arrow, red = QColor(c["text"]), QColor(c["edge"]), QColor(c["constrain"])
        W, H, GX, GY = 200, 62, 90, 36
        pos    = {n: QPointF(c * (W + GX), r * (H + GY)) for n, (c, r) in place.items()}
        for a, b, kind in edges:
            p1, p2 = pos[a] + QPointF(W, H / 2), pos[b] + QPointF(0, H / 2)
            pen = QPen(red if kind == "constrain" else arrow, 2.4, Qt.DashLine if kind == "constrain" else Qt.SolidLine)
            scene.addLine(p1.x(), p1.y(), p2.x(), p2.y(), pen)
            d = p2 - p1; n = (d.x() ** 2 + d.y() ** 2) ** 0.5 or 1; ux, uy = d.x() / n, d.y() / n
            l = QPointF(-ux * 14 - uy * 6, -uy * 14 + ux * 6); r = QPointF(-ux * 14 + uy * 6, -uy * 14 - ux * 6)
            scene.addPolygon(QPolygonF([p2, p2 + l, p2 + r]), QPen(pen.color()), QBrush(pen.color()))
        selfish = {r.node for r in reports if r.ok and r.job in r.requisites}
        for n, kind in nodes.items():
            fill = QColor(c["node"]) if kind == "job" else QColor(c["node_missing"])
            pen  = QPen(QColor(c["warn"]), 2, Qt.DashLine) if kind == "missing" else QPen(QColor(c["edge"]), 1.5)
            scene.addRect(pos[n].x(), pos[n].y(), W, H, pen, QBrush(fill))
            report = next((r for r in reports if r.ok and r.node == n), None)
            title  = scene.addText(n); f = title.font(); f.setBold(True); f.setPointSize(13); title.setFont(f); title.setDefaultTextColor(QColor(c["node_text"])); title.setPos(pos[n].x() + 6, pos[n].y() + 4)
            sub    = scene.addText(f"{report.software}  {report.comp_type}  ({report.procs} proc)" if report else "not defined in a loaded file"); sub.setDefaultTextColor(QColor(c["node_text"])); sub.setPos(pos[n].x() + 6, pos[n].y() + 30)
            if n in selfish:
                badge = scene.addText("requires itself: never starts"); badge.setDefaultTextColor(red); bf = badge.font(); bf.setBold(True); badge.setFont(bf); badge.setPos(pos[n].x(), pos[n].y() + H + 2)
        if not nodes: scene.addText("No valid input files yet. Use 'New input…' or 'Add input files…'.").setDefaultTextColor(ink)
        scene.setSceneRect(scene.itemsBoundingRect().adjusted(-30, -30, 30, 30)); self.fit()

class PipelineTab(QWidget):
    def __init__(self, session: Session):
        super().__init__()
        self.session = session
        self.table   = QTableWidget(0, 6); self.table.setHorizontalHeaderLabels(["File", "Branch/Job", "Software", "Type", "Submit?", "Status"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows); self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.graph   = GraphView()
        new    = QPushButton("New input…"); new.setProperty("primary", True); new.clicked.connect(self.new_input)
        edit   = QPushButton("Edit selected…"); edit.clicked.connect(self.edit_selected)
        add    = QPushButton("Add input files…"); add.clicked.connect(self.add)
        remove = QPushButton("Remove selected"); remove.clicked.connect(self.remove)
        row = QHBoxLayout(); [row.addWidget(w) for w in (new, edit, add, remove)]; row.addStretch(1)
        legend = QLabel("Read left to right: an arrow A → B means B starts only after A has finished (B's requisites). Dashed red = A blocks B (constrains). Orange dashed box = job not defined in a loaded file."); legend.setWordWrap(True)
        self.issues = QLabel(); self.issues.setWordWrap(True); set_kind(self.issues, "warn")
        graph_box = QWidget(); gl = QVBoxLayout(graph_box); gl.setContentsMargins(0, 0, 0, 0); gl.addWidget(legend); gl.addWidget(self.graph, 1); gl.addWidget(self.issues)
        split = QSplitter(Qt.Vertical); split.addWidget(self.table); split.addWidget(graph_box); split.setStretchFactor(0, 1); split.setStretchFactor(1, 2)
        lay = QVBoxLayout(self); lay.addLayout(row); lay.addWidget(split, 1)
        session.inputsChanged.connect(self.refresh)

    def start_dir(self) -> str:
        return os.path.dirname(self.session.info.filepath) if self.session.info else os.path.expanduser("~")

    def new_input(self) -> None:
        from scope.gui.editor import InputEditor
        dialog = InputEditor(self, self.start_dir())
        if dialog.exec() and dialog.saved_path: self.session.add_inputs([dialog.saved_path])

    def edit_selected(self) -> None:
        from scope.gui.editor import InputEditor
        rows = self.table.selectionModel().selectedRows()
        if not rows: QMessageBox.information(self, "Nothing selected", "Select an input file in the table first."); return
        path = self.session.reports[rows[0].row()].path
        try:
            with open(path) as f: form, extras = backend.sections_to_form(backend.parse_sections(f.read()))
        except OSError as exc: QMessageBox.warning(self, "Cannot read file", str(exc)); return
        dialog = InputEditor(self, os.path.dirname(path), form, extras, os.path.basename(path))
        if dialog.exec() and dialog.saved_path: self.session.add_inputs([dialog.saved_path])

    def add(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Scope input files", os.path.expanduser("~"), "Scope input (*.scope *.inp *.txt);;All files (*)")
        if paths: self.session.add_inputs(paths)

    def remove(self) -> None:
        paths = [self.session.reports[idx.row()].path for idx in self.table.selectionModel().selectedRows()]       ## read all rows first: each removal rebuilds the table
        if paths: self.session.remove_inputs(paths)

    def refresh(self) -> None:
        reports = self.session.reports
        issues  = backend.pipeline_issues(reports)
        by_file = {}
        for path, message in issues: by_file.setdefault(path, []).append(message)
        self.table.setRowCount(len(reports))
        for i, r in enumerate(reports):
            status = "ok" if r.ok and r.path not in by_file else ("warning: " + by_file[r.path][0] if r.ok else r.error)
            cells = [os.path.basename(r.path), r.node if r.ok else "", r.software, r.comp_type, ("YES" if r.want_submit else "no") if r.ok else "", status]
            for j, text in enumerate(cells): self.table.setItem(i, j, QTableWidgetItem(text))
            c = theme.colors()
            if not r.ok: self.table.item(i, 5).setForeground(QBrush(QColor(c["err"]))); self.table.item(i, 5).setToolTip(r.error)
            elif r.path in by_file: self.table.item(i, 5).setForeground(QBrush(QColor(c["warn"]))); self.table.item(i, 5).setToolTip("\n".join(by_file[r.path]))
        self.issues.setText("\n".join(m for _, m in issues))
        self.graph.draw(reports)

###############
### Run tab ###
###############
class RunTab(QWidget):
    def __init__(self, session: Session):
        super().__init__()
        self.session = session
        self.record, self.offset, self.accept_legacy = None, 0, False       ## accept_legacy: show runs recorded before workspaces existed (the Default workspace)
        self.timer   = QTimer(self); self.timer.timeout.connect(self.tick)
        self.system  = QComboBox()
        self.quiet, self.verbose, self.errors = QCheckBox("quiet (-q)"), QCheckBox("verbose (-v)"), QCheckBox("handle errors (-e)")
        self.warning = QLabel(); self.warning.setWordWrap(True); set_kind(self.warning, "err")
        self.run_btn  = QPushButton("Run"); self.run_btn.setProperty("primary", True); self.run_btn.clicked.connect(self.start)
        self.stop_btn = QPushButton("Stop"); self.stop_btn.clicked.connect(self.stop); self.stop_btn.setEnabled(False)
        self.log      = QPlainTextEdit(); self.log.setReadOnly(True); self.log.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.status   = QLabel("Idle")
        top = QHBoxLayout(); top.addWidget(QLabel("System")); top.addWidget(self.system, 1); [top.addWidget(w) for w in (self.quiet, self.verbose, self.errors, self.run_btn, self.stop_btn)]
        lay = QVBoxLayout(self); lay.addLayout(top); lay.addWidget(self.warning); lay.addWidget(self.log, 1); lay.addWidget(self.status)
        session.systemsChanged.connect(self.refresh); session.inputsChanged.connect(self.refresh); session.envChanged.connect(self.refresh)

    def refresh(self) -> None:
        current = self.system.currentText()
        self.system.clear()
        self.system.addItems([r.name for r in self.session.systems() if r.file])
        if current: self.system.setCurrentText(current)
        self.warning.setText("\n".join(w for w in [backend.submission_warning(self.session.info, self.session.reports), *backend.queue_problems(self.session.info, self.session.reports)] if w))

    def start(self) -> None:
        s = self.session
        valid = [r for r in s.reports if r.ok]
        if not s.info or not self.system.currentText() or not valid:
            QMessageBox.information(self, "Nothing to run", "Choose an environment, a system and at least one valid input file."); return
        if self.running(): QMessageBox.information(self, "A run is in progress", "Wait for the current run to end, or stop it first: two runs on one system can overwrite each other's results."); return
        other = backend.active_local_run(s.info.filepath, self.system.currentText())
        if other: QMessageBox.information(self, "This system is already running", f"'{other['system']}' is already being run from this environment (started {time.strftime('%H:%M', time.localtime(other['started']))}, perhaps from another workspace or window). Two runs on one system overwrite each other's results: wait for it to end."); return
        warning = backend.submission_warning(s.info, valid)
        if warning and QMessageBox.question(self, "Jobs will be submitted", warning + "\n\nContinue?") != QMessageBox.Yes: return
        record = backend.start_detached_local(s.info.filepath, self.system.currentText(), [r.path for r in valid], self.quiet.isChecked(), self.verbose.isChecked(), self.errors.isChecked())
        self.attach(record)

    ##### following a run: the run itself lives outside this window #####
    def attach(self, record: dict, note: str="") -> None:
        """Starts following a run (new, or found again when the window was reopened) by reading its log file."""
        self.record, self.offset = record, 0
        import time as _t
        self.log.clear(); self.log.appendPlainText(f"$ {record['command']}   (started {_t.strftime('%H:%M:%S', _t.localtime(record['started']))})\n" + (note + "\n" if note else "") + "This run keeps going if you close this window.\n")
        self.run_btn.setEnabled(False); self.stop_btn.setEnabled(True); self.status.setText("Running…")
        self.timer.start(400); self.tick()

    def tick(self) -> None:
        if not self.record: return
        text, self.offset = backend.read_log(self.record["log"], self.offset)
        if text.strip("\n"): self.log.appendPlainText(text.rstrip("\n"))
        state, code = backend.run_state(self.record)
        if state != "running": self.finish(state, code)

    def finish(self, state: str, code: "int | None") -> None:
        self.timer.stop(); text, self.offset = backend.read_log(self.record["log"], self.offset, final=True)
        if text.strip("\n"): self.log.appendPlainText(text.rstrip("\n"))
        self.run_btn.setEnabled(True); self.stop_btn.setEnabled(False)
        backend.mark_seen(self.record["id"])
        if state == "finished": self.status.setText(f"Finished with exit code {code}")
        else: self.status.setText("The run ended without finishing (it was stopped or killed, or the computer restarted). Press Run again: SCOPE continues where it stopped.")
        if state == "finished" and code == 0: self.session.mark("ran")
        self.session.systemsChanged.emit()

    def reattach(self) -> None:
        """Follows again the latest run of this workspace's environment that is still running, or shows the end of one that finished while it was not shown."""
        env = self.session.info.filepath if self.session.info else ""
        for record in reversed(backend.load_runs()):
            if record.get("kind") != "local" or record.get("seen") or not backend.record_belongs(record, env, self.accept_legacy): continue
            state, code = backend.run_state(record)
            self.attach(record, note="Found again: this run was started earlier." + ("" if state == "running" else " It ended while it was not shown."))
            return

    def detach(self) -> None:
        """Stops following the run (when another workspace is shown). The run goes on and is not marked as seen, so it is found again later."""
        self.timer.stop(); self.record, self.offset = None, 0
        self.log.clear(); self.run_btn.setEnabled(True); self.stop_btn.setEnabled(False); self.status.setText("Idle")

    def stop(self) -> None:
        if self.record and backend.stop_run(self.record): self.status.setText("Stopping…")

    def running(self) -> bool:
        return bool(self.record and self.timer.isActive())

###################
### Main window ###
###################
STEPS = [("environment", "Environment", "Say where your files live", "1 ·"), ("systems", "Systems", "Bring in the molecules to compute", "2 ·"), ("pipeline", "Pipeline", "Describe what to compute, and in what order", "3 ·"),
         ("run", "Run", "Let SCOPE act on the pipeline", "4 ·"), ("cluster", "Cluster", "Run on a remote cluster instead of this computer", "5 ·")]

class Page(QWidget):
    """One step: title, one-line purpose, a link to its manual section, the content, and Back / Next buttons."""
    def __init__(self, number: int, key: str, title: str, subtitle: str, body: QWidget, window: "MainWindow"):
        super().__init__()
        self.key = key
        head  = QLabel(f"Step {number} of {len(STEPS)}"); head.setObjectName("pagesub")
        name  = QLabel(title); name.setObjectName("pagetitle")
        sub   = QLabel(subtitle); sub.setObjectName("pagesub")
        help_ = QPushButton("Manual: what does this step do?"); help_.clicked.connect(lambda: window.open_manual(STEPS[number - 1][3]))
        top   = QHBoxLayout(); col = QVBoxLayout(); col.setSpacing(2); [col.addWidget(x) for x in (head, name, sub)]; top.addLayout(col, 1); top.addWidget(help_, 0, Qt.AlignTop)
        foot  = QHBoxLayout(); foot.addStretch(1)
        if number > 1:
            back = QPushButton(f"←  {STEPS[number - 2][1]}"); back.clicked.connect(lambda: window.go(number - 2)); foot.addWidget(back)
        if number < len(STEPS):
            nxt = QPushButton(f"Next: {STEPS[number][1]}  →"); nxt.setProperty("primary", True); nxt.clicked.connect(lambda: window.go(number)); foot.addWidget(nxt)
        lay = QVBoxLayout(self); lay.setContentsMargins(26, 20, 26, 16); lay.setSpacing(12); lay.addLayout(top); lay.addWidget(body, 1); lay.addLayout(foot)

def status_row(glyph: str, colour: str, main: str, sub: str="") -> str:
    """One line of the sidebar status card: a coloured sign, the state, and a quieter note on the right (rich text, never wrapped)."""
    c = theme.colors(); sub = sub if len(sub) <= 18 else sub[:17] + "…"
    return (f'<table width="100%" cellspacing="0" cellpadding="0"><tr><td width="18" style="color:{colour}; font-size:13px">{glyph}</td>'
            f'<td style="color:{c["sidebar_text"]}; white-space:nowrap">{main}</td><td align="right" style="color:{c["sidebar_sub"]}; font-size:11px; white-space:nowrap">{sub}</td></tr></table>')

class ClickLabel(QLabel):
    """A label that can be clicked."""
    clicked = Signal()
    def mousePressEvent(self, event) -> None:
        self.clicked.emit(); super().mousePressEvent(event)

class LocalScopeDialog(QDialog):
    """Details of the SCOPE installation on this computer, with a copyable text and a button to check again."""
    def __init__(self, parent: QWidget, window: "MainWindow"):
        super().__init__(parent); self.window_ = window
        self.setWindowTitle("SCOPE on this computer"); self.resize(760, 470)
        self.text = QPlainTextEdit(); self.text.setReadOnly(True); mono = self.text.font(); mono.setFamily("Menlo"); self.text.setFont(mono); self.text.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        again, copy, close = QPushButton("Check again"), QPushButton("Copy"), QPushButton("Close")
        again.clicked.connect(window.check_local); copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.text.toPlainText())); close.clicked.connect(self.accept)
        row = QHBoxLayout(); row.addWidget(again); row.addWidget(copy); row.addStretch(1); row.addWidget(close)
        lay = QVBoxLayout(self); lay.addWidget(self.text, 1); lay.addLayout(row)
        window.localChecked.connect(self.refresh); self.refresh()

    def refresh(self) -> None:
        info = self.window_.local; glyph = {"ok": "✓", "warn": "!", "fail": "✗"}
        lines = [f"{glyph[s]}  {name:<24} {detail}" for s, name, detail in info.report()]
        if info.state != "green": lines += ["", backend.INSTALL_HINT]
        self.text.setPlainText("\n".join(lines))

class MainWindow(QMainWindow):
    """Left bar with the five steps, a manual and a theme switch; the selected step fills the rest of the window."""
    localChecked   = Signal()
    updatesChecked = Signal()

    def __init__(self, env_path: str=None):
        super().__init__()
        self.local, self.local_checked_at, self.local_task = backend.LocalScope(), 0.0, None
        self.update_status, self.update_task, self.update_repo, self.updated, self.update_message = None, None, None, False, ""     ## update_repo None: the checkout SCOPE is imported from
        self.setWindowTitle("SCOPE"); self.resize(1240, 800)
        self.session = Session()
        theme.apply(QApplication.instance(), backend.load_gui_config().get("theme", "auto"))
        self.env_tab, self.sys_tab, self.pipe_tab, self.run_tab = EnvironmentTab(self.session), SystemsTab(self.session), PipelineTab(self.session), RunTab(self.session)
        from scope.gui.remote_tab import RemoteTab
        from scope.gui.manual import ManualPage
        self.remote_tab, self.manual = RemoteTab(self.session), ManualPage()
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.NoFrame); scroll.setWidget(self.remote_tab)       ## the Cluster page is tall: scroll instead of squeezing
        bodies  = [self.env_tab, self.sys_tab, self.pipe_tab, self.run_tab, scroll]
        self.tabs = QStackedWidget()                                  ## kept under this name: it used to be a QTabWidget
        self.pages = [Page(i + 1, key, title, sub, body, self) for i, ((key, title, sub, _), body) in enumerate(zip(STEPS, bodies))]
        for page in self.pages: self.tabs.addWidget(page)
        manual_page = QWidget(); ml = QVBoxLayout(manual_page); ml.setContentsMargins(26, 20, 26, 16); title = QLabel("Manual"); title.setObjectName("pagetitle"); ml.addWidget(title); ml.addWidget(self.manual, 1)
        self.tabs.addWidget(manual_page)
        from scope.gui.runs_page import RunsPage
        self.runs_page = RunsPage(self); runs_wrap = QWidget(); rl_ = QVBoxLayout(runs_wrap); rl_.setContentsMargins(26, 20, 26, 16); runs_title = QLabel("Runs"); runs_title.setObjectName("pagetitle")
        runs_sub = QLabel("Every run of every workspace, on this computer and on the clusters. Double-click a run to show it in its workspace."); runs_sub.setObjectName("pagesub"); runs_sub.setWordWrap(True)
        rl_.addWidget(runs_title); rl_.addWidget(runs_sub); rl_.addWidget(self.runs_page, 1); self.tabs.addWidget(runs_wrap)                 ## index len(STEPS) + 1 (the manual stays at len(STEPS))

        side = QFrame(); side.setObjectName("sidebar"); side.setFixedWidth(240); sl = QVBoxLayout(side); sl.setContentsMargins(0, 22, 0, 16); sl.setSpacing(2)
        brand = QLabel("SCOPE"); brand.setObjectName("brand"); brandsub = QLabel("workflow assistant"); brandsub.setObjectName("brandsub")
        bl = QVBoxLayout(); bl.setContentsMargins(18, 0, 18, 0); bl.setSpacing(0); bl.addWidget(brand); bl.addWidget(brandsub); sl.addLayout(bl); sl.addSpacing(14)
        self.local_label = ClickLabel(); self.local_label.setCursor(Qt.PointingHandCursor); self.local_label.setObjectName("statusrow"); self.local_label.setTextFormat(Qt.RichText); self.local_label.clicked.connect(self.show_local)
        self.update_label = ClickLabel(); self.update_label.setCursor(Qt.PointingHandCursor); self.update_label.setObjectName("statusrow"); self.update_label.setTextFormat(Qt.RichText); self.update_label.clicked.connect(self.show_updates); self.update_label.hide()
        card = QFrame(); card.setObjectName("statuscard"); cl = QVBoxLayout(card); cl.setContentsMargins(6, 6, 6, 6); cl.setSpacing(0); cl.addWidget(self.local_label); cl.addWidget(self.update_label)
        cw = QHBoxLayout(); cw.setContentsMargins(14, 0, 14, 0); cw.addWidget(card); sl.addLayout(cw); sl.addSpacing(20)
        ws_label = QLabel("WORKSPACE"); ws_label.setObjectName("wslabel")
        self.ws_combo = QComboBox(); self.ws_combo.setObjectName("wscombo"); self.ws_combo.setToolTip("The project shown: its environment, input files and project on the cluster. Runs keep going whichever workspace is shown.")
        self.ws_combo.setMinimumContentsLength(8); self.ws_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.ws_new_btn = QPushButton("+"); self.ws_new_btn.setObjectName("wsbtn"); self.ws_new_btn.setFixedWidth(28); self.ws_new_btn.setToolTip("New workspace"); self.ws_new_btn.clicked.connect(self.new_workspace)
        self.ws_menu_btn = QPushButton("⋯"); self.ws_menu_btn.setObjectName("wsbtn"); self.ws_menu_btn.setFixedWidth(28); self.ws_menu_btn.setToolTip("Rename or delete this workspace")
        ws_menu = QMenu(self); ws_menu.addAction("Rename this workspace…", self.rename_workspace); ws_menu.addAction("Delete this workspace…", self.delete_workspace); ws_menu.addSeparator()
        ws_menu.addAction("Export this workspace…", self.export_workspace); ws_menu.addAction("Import a workspace…", self.import_workspace); self.ws_menu_btn.setMenu(ws_menu)
        wl = QVBoxLayout(); wl.setContentsMargins(14, 0, 14, 14); wl.setSpacing(6); wl.addWidget(ws_label); wr = QHBoxLayout(); wr.setSpacing(4); wr.addWidget(self.ws_combo, 1); wr.addWidget(self.ws_new_btn); wr.addWidget(self.ws_menu_btn); wl.addLayout(wr); sl.addLayout(wl)
        def separator() -> QFrame:
            line = QFrame(); line.setObjectName("sidesep"); line.setFixedHeight(1); return line
        sl.addWidget(separator()); sl.addSpacing(8)
        self.group, self.step_buttons = QButtonGroup(self), []
        for i, (key, title, _, _) in enumerate(STEPS):
            b = QPushButton(); b.setObjectName("step"); b.setCheckable(True); b.setCursor(Qt.PointingHandCursor); b.clicked.connect(lambda _=False, i=i: self.go(i)); self.group.addButton(b, i); self.step_buttons.append(b); sl.addWidget(b)
        sl.addSpacing(8); sl.addWidget(separator()); sl.addSpacing(8)
        self.runs_btn = QPushButton("▶   Runs"); self.runs_btn.setObjectName("step"); self.runs_btn.setCheckable(True); self.runs_btn.setCursor(Qt.PointingHandCursor); self.runs_btn.setToolTip("Every run of every workspace, here and on the clusters")
        self.runs_btn.clicked.connect(lambda: self.go(len(STEPS) + 1)); self.group.addButton(self.runs_btn, len(STEPS) + 1); sl.addWidget(self.runs_btn)
        self.manual_btn = QPushButton("?   Manual"); self.manual_btn.setObjectName("step"); self.manual_btn.setCheckable(True); self.manual_btn.setCursor(Qt.PointingHandCursor); self.manual_btn.clicked.connect(lambda: self.open_manual()); self.group.addButton(self.manual_btn, len(STEPS)); sl.addWidget(self.manual_btn)
        sl.addStretch(1)
        self.badge = QLabel(); self.badge.setObjectName("badge"); self.badge.setWordWrap(True); bw = QHBoxLayout(); bw.setContentsMargins(14, 0, 14, 0); bw.addWidget(self.badge); sl.addLayout(bw)
        self.theme_btn = QPushButton(); self.theme_btn.setObjectName("themebtn"); self.theme_btn.setCursor(Qt.PointingHandCursor); self.theme_btn.clicked.connect(self.cycle_theme)
        tw = QHBoxLayout(); tw.setContentsMargins(14, 8, 14, 0); tw.addWidget(self.theme_btn); tw.addStretch(1); sl.addLayout(tw)

        root = QWidget(); rl = QHBoxLayout(root); rl.setContentsMargins(0, 0, 0, 0); rl.setSpacing(0); rl.addWidget(side); rl.addWidget(self.tabs, 1); self.setCentralWidget(root)
        self.statusBar().showMessage("Local mode: no scheduler is used unless the environment says so.")
        for signal in (self.session.envChanged, self.session.systemsChanged, self.session.inputsChanged, self.session.progressChanged): signal.connect(self.update_steps)
        theme.on_change(self.on_theme); theme.on_change(self.render_local); theme.on_change(self.render_updates); self.on_theme(); self.render_local()
        QGuiApplication.instance().applicationStateChanged.connect(self.on_app_state)
        self.check_local(); self.check_updates(fetch=updates.due())            ## GitHub is asked only once the user allowed the daily check
        self.go(0); self.update_steps()
        self.loading, self.workspace = False, None
        for signal in (self.session.envChanged, self.session.inputsChanged, self.remote_tab.projectChanged): signal.connect(self.save_workspace)
        self.ws_combo.currentTextChanged.connect(self.switch_workspace)
        self.load_workspace(workspaces.ensure(), env_override=env_path)

    def check_local(self) -> None:
        """Asks, in a worker thread, whether SCOPE can run from this computer (the same question every run depends on). The version shown is read from the installation each time."""
        if self.local_task is not None: return
        self.local_label.setText(status_row("●", theme.colors()["sidebar_sub"], "SCOPE", "checking…"))
        task = Task(backend.detect_local_scope); self.local_task = task
        task.signals.done.connect(self.local_done); task.signals.failed.connect(lambda m: self.local_done(backend.LocalScope(probe_error=m)))
        QThreadPool.globalInstance().start(task)

    def local_done(self, info) -> None:
        self.local, self.local_checked_at, self.local_task = info, time.time(), None
        self.render_local(); self.localChecked.emit()

    def render_local(self) -> None:
        """Draws the light and the installed version under the SCOPE title: green active, amber active but worth a look, red not usable."""
        c = theme.colors(); info = self.local; colour = {"green": c["ok"], "amber": c["warn"], "red": c["err"]}[info.state] if (info.runs_ok or info.probe_error or info.python) else c["sidebar_sub"]
        if not (info.python or info.probe_error): return                                   # still checking
        word = "active" if info.runs_ok else ("not installed" if not info.probe_error else "check failed")
        self.local_label.setText(status_row("●", colour, f"SCOPE v{info.scope_version}" if info.scope_version else "SCOPE", word))
        self.local_label.setToolTip("Click for details.\n" + "\n".join(f"{name}: {detail}" for s, name, detail in info.report()[:3]))

    def show_local(self) -> None:
        LocalScopeDialog(self, self).exec()

    def on_app_state(self, state) -> None:
        """Checks again when the window comes back to the front after a while, so an upgrade of SCOPE shows without restarting."""
        if state == Qt.ApplicationActive and time.time() - self.local_checked_at > 120: self.check_local()
        if state == Qt.ApplicationActive and updates.due(): self.check_updates(fetch=True)

    ##### updates of SCOPE #####
    def check_updates(self, fetch: bool=False) -> None:
        """Compares this copy of SCOPE with GitHub in a worker thread: with fetch=True GitHub is asked (network), otherwise only what the last check brought is used."""
        if self.update_task is not None: return
        if fetch: self.update_label.setText(status_row("↻", theme.colors()["sidebar_sub"], "Updates", "checking…")); self.update_label.show()
        repo = self.update_repo
        task = Task(lambda: updates.status(repo, fetch=fetch)); self.update_task = task
        task.signals.done.connect(self.updates_done); task.signals.failed.connect(lambda m: self.updates_done(updates.UpdateStatus(repo=repo or "", error=m)))
        QThreadPool.globalInstance().start(task); self.updatesChecked.emit()

    def updates_done(self, st) -> None:
        self.update_status, self.update_task = st, None
        if st.fetched: updates.save_setting(last=st.checked)                 ## also after a failure: the daily check does not retry at every start
        self.render_updates(); self.updatesChecked.emit()

    def render_updates(self) -> None:
        """The line under the SCOPE light: updates found (accent), up to date (quiet), check failed (amber), or the question whether to check at all."""
        st, c = self.update_status, theme.colors()
        if self.update_task is not None and st is None: return
        if st is None or not st.repo: self.update_label.hide(); return
        kind, text = st.summary(); enabled = updates.setting().get("enabled")
        t = st.followed() or next((x for x in st.targets if x.exists), None); ref = t.ref if t else ""
        if self.updated:                          kind, main, sub = "new", "Restart to update", ""
        elif enabled is None and kind != "new":   kind, main, sub = "ask", "Check for updates?", ""
        elif kind == "new":                       main, sub = f"{t.behind} update{'s' if t.behind > 1 else ''}", ref
        elif kind == "warn":                      main, sub = "Update check failed", ""
        elif text.startswith("Up to date"):       main, sub = "Up to date", ref
        else:                                     main, sub = text, ""
        colour = {"new": c["accent"], "ask": c["accent"], "warn": c["warn"]}.get(kind, c["sidebar_sub"]); glyph = {"new": "↑", "warn": "!"}.get(kind, "↻")
        self.update_label.setText(status_row(glyph, colour, main, sub)); self.update_label.show()
        tip = {None: "The window does not contact GitHub until you allow it.", False: "The daily check is off: click to check now or turn it on.", True: "Checked once a day."}[enabled]
        self.update_label.setToolTip(f"{text}. {tip}\nClick for details: what is new on GitHub, the daily check, and Update.")

    def show_updates(self) -> None:
        from scope.gui.update_view import UpdatesDialog
        UpdatesDialog(self, self).exec()

    def apply_update(self) -> None:
        """Moves this copy forward (fast-forward only) in a worker thread; updates.update checks again that nothing local is affected."""
        if self.update_task is not None or not self.update_status: return
        repo = self.update_status.repo; task = Task(lambda: updates.update(repo)); self.update_task = task
        task.signals.done.connect(self.update_applied); task.signals.failed.connect(lambda m: self.update_applied((False, f"Update failed: {m}", False)))
        QThreadPool.globalInstance().start(task); self.updatesChecked.emit()

    def update_applied(self, result) -> None:
        ok, message, recipe = result; self.update_task = None; self.updated = self.updated or ok
        if ok and recipe: message += ' The installation recipe changed: start the window with ./scope-gui, which reinstalls by itself (or run pip install -e "core[gui]").'
        if ok: message += " Restart the window to use the new code; runs keep going."
        self.update_message = message; self.check_updates(fetch=False)

    def restart(self) -> None:
        """Closes the window (asking first if a run is shown, as usual) and opens a new one with the code now on disk."""
        from PySide6.QtCore import QProcess
        if self.close(): QProcess.startDetached(sys.executable, ["-c", "from scope.cli.main import main; main()", "gui"])

    def go(self, index: int) -> None:
        """Shows step `index` (0-based; len(STEPS) is the manual)."""
        self.tabs.setCurrentIndex(index)
        button = self.group.button(index)
        if button: button.setChecked(True)

    def show_step(self, key: str) -> None:
        self.go([s[0] for s in STEPS].index(key))

    def open_manual(self, section: str=None) -> None:
        if section: self.manual.show_section(section)
        self.go(len(STEPS))

    def step_done(self, key: str) -> bool:
        s = self.session
        if key == "environment": return s.info is not None and not s.info.missing
        if key == "systems":     return any(r.file for r in s.systems())
        if key == "pipeline":    return any(r.ok for r in s.reports)
        if key == "run":         return s.progress["ran"]
        if key == "cluster":     return s.progress["cluster"]
        return False

    def update_steps(self) -> None:
        for (key, title, _, _), button in zip(STEPS, self.step_buttons):
            done = self.step_done(key)
            button.setText(f"{'✓' if done else '○'}   {title}")
        i = self.session.info
        self.badge.setText(f"{i.name}\n{i.scheduler} environment" if i else "No environment yet")

    def cycle_theme(self) -> None:
        order = ["auto", "light", "dark"]
        new = order[(order.index(theme.preference()) + 1) % 3]
        backend.save_gui_config({"theme": new})
        theme.apply(QApplication.instance(), new)

    def on_theme(self) -> None:
        glyph = {"auto": "◐", "light": "☀", "dark": "☾"}[theme.preference()]
        self.theme_btn.setText(f"{glyph}  Theme: {theme.preference().capitalize()}")
        self.pipe_tab.refresh()                                           ## the graph and the status colours are drawn by hand

    ##### workspaces #####
    def refresh_workspaces(self) -> None:
        self.ws_combo.blockSignals(True); self.ws_combo.clear(); self.ws_combo.addItems(workspaces.list_names())
        if self.workspace: self.ws_combo.setCurrentText(self.workspace.name)
        self.ws_combo.blockSignals(False)

    def load_workspace(self, ws: "workspaces.Workspace", env_override: str=None) -> None:
        """Shows a workspace: its environment, input files, cluster connection and project on the cluster, and its run if one is active.
        Runs of the workspace shown before keep going; they are found again when it is shown again."""
        self.loading = True
        try:
            self.run_tab.detach(); self.remote_tab.stop_watching(); self.session.clear()
            path = env_override or ws.env_path
            if path and os.path.isfile(path): self.env_tab.load(path) if env_override else self.try_last(path)
            elif ws.env_path: self.statusBar().showMessage(f"The environment of workspace '{ws.name}' was not found: {ws.env_path}", 15000)
            if self.session.info is None: self.env_tab.name.setText(workspaces.file_name(ws.name)[:-5])             ## a proposed environment name for an empty workspace
            if ws.inputs: self.session.add_inputs(ws.inputs)                                    ## a file that no longer exists shows as an error row, it is not dropped
            self.remote_tab.loading_project = True; self.remote_tab.select_profile(ws.profile); self.remote_tab.loading_project = False
            root, env = workspaces.remote_fields(ws, self.remote_tab.profiles.get(ws.profile))
            self.remote_tab.set_project(root, env, workspaces.suggested_remote_root(ws))
            self.workspace = ws; workspaces.set_active(ws.name); self.refresh_workspaces()
            self.run_tab.accept_legacy = ws.legacy; self.run_tab.reattach(); self.update_shared()
            self.setWindowTitle(f"SCOPE — {ws.name}"); self.ws_combo.setToolTip(f"Workspace '{ws.name}': its environment, input files and project on the cluster. Runs keep going whichever workspace is shown.")
        finally:
            self.loading = False
        if env_override: self.save_workspace()
        self.update_steps()

    def save_workspace(self) -> None:
        """Writes what the window shows into the active workspace (called when the environment, the inputs or the cluster project change)."""
        if self.loading or self.workspace is None: return
        ws = self.workspace
        ws.env_path = self.session.info.filepath if self.session.info else ""
        ws.inputs   = [r.path for r in self.session.reports]
        ws.profile  = self.remote_tab.chooser.currentText() if self.remote_tab.chooser.currentIndex() >= 0 else ""
        ws.remote_root, ws.remote_env = self.remote_tab.project()
        try: workspaces.save(ws)
        except OSError as exc: self.statusBar().showMessage(f"Could not save workspace '{ws.name}': {exc}", 15000)
        self.update_shared()

    def update_shared(self) -> None:
        """Warns on the Cluster page when another workspace uses the same project folder on the same cluster."""
        if self.workspace is None: return
        prof = self.remote_tab.profiles.get(self.remote_tab.chooser.currentText()) if self.remote_tab.chooser.currentIndex() >= 0 else None
        root, _ = self.remote_tab.project()
        self.remote_tab.set_shared(workspaces.sharing(self.workspace.name, prof.host if prof else "", root, self.remote_tab.profiles))

    def show_run(self, row) -> None:
        """Shows a run listed on the Runs page in its workspace: a run on this computer on the Run page, a cluster run on the Cluster page (followed)."""
        if row.names and (self.workspace is None or self.workspace.name not in row.names) and row.names[0] in workspaces.list_names(): self.switch_workspace(row.names[0])
        if row.record is not None:
            if self.run_tab.record is None or self.run_tab.record.get("id") != row.record["id"]: self.run_tab.attach(row.record, note="Shown from the Runs page.")
            self.show_step("run")
        else:
            self.show_step("cluster"); self.remote_tab.stop_watching(); self.remote_tab.begin_watch(row.profile, row.system, row.log, f"Following the run of '{row.system}' on {row.where}.")

    def export_workspace(self) -> None:
        import json
        self.save_workspace(); ws = self.workspace
        path, _ = QFileDialog.getSaveFileName(self, "Export workspace", os.path.join(os.path.expanduser("~"), workspaces.file_name(ws.name)[:-5] + ".scopews.json"), "SCOPE workspace (*.json)")
        if not path: return
        data = workspaces.export_data(ws, self.remote_tab.profiles.get(ws.profile))
        try:
            with open(path, "w") as fh: json.dump(data, fh, indent=2)
        except OSError as exc: QMessageBox.warning(self, "Not exported", str(exc)); return
        self.statusBar().showMessage(f"Workspace '{ws.name}' exported to {path} (paths, input list and cluster connection; no project file is copied).", 15000)

    def import_workspace(self) -> None:
        import json
        from scope.gui import remote
        path, _ = QFileDialog.getOpenFileName(self, "Import workspace", os.path.expanduser("~"), "SCOPE workspace (*.json)")
        if not path: return
        try:
            with open(path) as fh: ws, notes = workspaces.import_data(json.load(fh), remote.load_profiles())
        except (OSError, ValueError) as exc: QMessageBox.warning(self, "Not imported", str(exc)); return
        self.remote_tab.profiles = remote.load_profiles(); self.remote_tab.loading_project = True; self.remote_tab.reload_chooser(); self.remote_tab.loading_project = False
        self.save_workspace(); self.load_workspace(ws)
        if notes: QMessageBox.information(self, "Workspace imported", "\n\n".join(notes))

    def switch_workspace(self, name: str) -> None:
        if self.loading or not name or (self.workspace and name == self.workspace.name): return
        ws = workspaces.load(name)
        if ws is None: QMessageBox.warning(self, "Workspace not found", f"The workspace '{name}' could not be read."); self.refresh_workspaces(); return
        following = self.run_tab.record["system"] if self.run_tab.running() else ""
        self.save_workspace(); old = self.workspace.name if self.workspace else ""
        self.load_workspace(ws)
        if following: self.statusBar().showMessage(f"The run of '{following}' keeps going. It is shown again when you come back to '{old}'.", 10000)

    def new_workspace(self) -> None:
        name, ok = QInputDialog.getText(self, "New workspace", "Name of the new workspace (for instance the molecule or the project):")
        if not ok or not name.strip(): return
        try: ws = workspaces.create(name, profile=self.workspace.profile if self.workspace else "")
        except ValueError as exc: QMessageBox.warning(self, "Workspace not created", str(exc)); return
        self.save_workspace(); self.load_workspace(ws); self.go(0)

    def rename_workspace(self) -> None:
        old = self.workspace.name
        name, ok = QInputDialog.getText(self, "Rename workspace", "New name:", text=old)
        if not ok or not name.strip() or name.strip() == old: return
        self.save_workspace()
        try: self.workspace = workspaces.rename(old, name)
        except ValueError as exc: QMessageBox.warning(self, "Workspace not renamed", str(exc)); return
        self.refresh_workspaces(); self.setWindowTitle(f"SCOPE — {self.workspace.name}")

    def delete_workspace(self) -> None:
        names = workspaces.list_names(); current = self.workspace.name
        if len(names) <= 1: QMessageBox.information(self, "Last workspace", "This is the only workspace, so it cannot be deleted."); return
        if QMessageBox.question(self, "Delete workspace", f"Delete the workspace '{current}'?\n\nOnly the workspace is removed from this window. Its environment, systems, input files, runs and everything on the cluster stay as they are.") != QMessageBox.Yes: return
        self.save_workspace(); self.load_workspace(workspaces.load(next(n for n in names if n != current)))
        workspaces.delete(current); self.refresh_workspaces()

    def try_last(self, path: str) -> None:
        try: env, info = backend.load_environment(path)
        except Exception: return
        self.session.set_environment(env, info)

    def close_choice(self) -> str:
        """Asks what to do with an active run when the window is closed: 'keep' (default), 'stop' or 'cancel'."""
        box = QMessageBox(self); box.setWindowTitle("A run is in progress"); box.setIcon(QMessageBox.Question)
        box.setText("A scope run is still active.\n\nIt keeps running on its own if you close this window. When you open the window again it finds the run and shows its log.")
        keep = box.addButton("Close, keep it running", QMessageBox.AcceptRole); stop = box.addButton("Stop it and close", QMessageBox.DestructiveRole); box.addButton(QMessageBox.Cancel)
        box.exec(); chosen = box.clickedButton()
        return "keep" if chosen is keep else ("stop" if chosen is stop else "cancel")

    def closeEvent(self, event) -> None:
        """Closing the window never stops a run by itself: runs live outside it. If one is active the user chooses to leave it running (default) or to stop it."""
        if self.run_tab.running():
            choice = self.close_choice()
            if choice == "stop": self.run_tab.stop()
            elif choice != "keep": event.ignore(); return
        self.save_workspace(); self.run_tab.timer.stop(); self.remote_tab.stop_watching()
        event.accept()

def main(env_path: str=None, check: bool=False) -> int:
    """Starts the GUI and returns the exit code of the Qt event loop. With check=True the window is built, one line is printed and the function returns 0 (no event loop)."""
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("SCOPE")
    win = MainWindow(env_path)
    if check:
        import PySide6
        print(f"SCOPE GUI OK  python={sys.executable}  PySide6={PySide6.__version__}", flush=True); return 0
    win.show()
    win.raise_(); win.activateWindow()                                ## a GUI started from a terminal on macOS otherwise opens behind the other applications
    print("SCOPE GUI started. If you do not see the window, look for 'Python' in the Dock or press Cmd+Tab.", flush=True)
    return app.exec()
