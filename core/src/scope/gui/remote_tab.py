"""Cluster page: connection profile, connection test, upload, run on the cluster, download.

Network work runs in worker threads (plain subprocess calls, no chdir). A run on the cluster is started detached (nohup, its own
log and pid file on the cluster): the window only watches it by reading the log, so closing the window or losing the connection
does not stop it, and a window opened later can find it again. Nothing contacts a host until the user presses a button, and nothing is copied before the user has
seen the list of files.
"""
import os
import time
from collections.abc import Callable
from PySide6.QtCore    import QThreadPool, QTimer, Qt, Signal
from PySide6.QtGui     import QBrush, QColor, QGuiApplication
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)
from scope.gui import backend, remote, theme
from scope.gui.theme import set_kind
from scope.gui.tasks import Task

class RemoteTab(QWidget):
    """The Cluster page. The connection (a saved profile) is shared by all workspaces; the project on the cluster (folder and environment
    file) belongs to the workspace shown, which the window saves when projectChanged is emitted."""
    projectChanged = Signal()

    def __init__(self, session):
        super().__init__()
        self.session, self.watching, self.busy, self.checks, self.tasks = session, None, False, [], []
        self.poll_ms = 5000; self.poll_timer = QTimer(self); self.poll_timer.timeout.connect(self.poll)
        self.profiles = remote.load_profiles()
        self.chooser  = QComboBox(); self.chooser.setMinimumWidth(180)
        self.new_btn, self.delete_btn, self.save_btn = QPushButton("New"), QPushButton("Delete"), QPushButton("Save profile")
        self.name, self.scope_bin, self.activate, self.root, self.env_file = QLineEdit(), QLineEdit(), QLineEdit(), QLineEdit(), QLineEdit()
        self.host = QComboBox(); self.host.setEditable(True); self.host.addItems(remote.list_ssh_hosts()); self.host.setEditText("")
        self.host.lineEdit().setPlaceholderText("host name or alias from ~/.ssh/config")
        self.scope_bin.setPlaceholderText("~/miniconda3/envs/scope/bin/scope  (or the full /home/you/... path)"); self.activate.setPlaceholderText("optional, only if the path above is empty")
        self.root.setPlaceholderText("~/scope_project  (a folder on the cluster; it need not exist yet)"); self.env_file.setPlaceholderText("/home/you/scope_project/scope_env_cluster.npy")
        form = QFormLayout(); form.setLabelAlignment(Qt.AlignRight)
        for label, w in (("Profile name", self.name), ("SSH host", self.host), ("Path of scope on the cluster", self.scope_bin), ("…or a line that makes it available", self.activate)): form.addRow(label, w)
        project_title = QLabel("Project on the cluster  (this workspace)"); project_title.setObjectName("sectiontitle")
        form.addRow(project_title)
        for label, w in (("Project folder on the cluster", self.root), ("Cluster environment file", self.env_file)): form.addRow(label, w)
        self.loading_project, self.shared = False, []
        top = QHBoxLayout(); top.addWidget(QLabel("Profile")); top.addWidget(self.chooser); top.addWidget(self.new_btn); top.addWidget(self.delete_btn); top.addStretch(1)
        self.terminal_btn, self.test_btn = QPushButton("Show terminal command"), QPushButton("Test connection"); self.test_btn.setProperty("primary", True)
        self.save_btn.setProperty("primary", True); row1 = QHBoxLayout(); row1.addWidget(self.save_btn); row1.addWidget(self.terminal_btn); row1.addWidget(self.test_btn); row1.addStretch(1)
        self.table = QTableWidget(0, 3); self.table.setHorizontalHeaderLabels(["", "Check", "Result"]); self.table.setEditTriggers(QAbstractItemView.NoEditTriggers); self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents); self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents); self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch); self.table.verticalHeader().setVisible(False)
        self.table.setWordWrap(True)
        self.system = QComboBox(); self.system.setMinimumWidth(200)
        self.pre_up, self.up, self.run_btn, self.down = (QPushButton(t) for t in ("Preview upload", "Upload", "Run on the cluster", "Download results…"))
        self.down.setToolTip("List the results of the selected system on the cluster and choose which files to bring back into this workspace's folders."); self.download_dialog = None
        self.watch_btn, self.unwatch_btn, self.stopcl_btn = QPushButton("Watch runs"), QPushButton("Stop watching"), QPushButton("Stop the run")
        self.watch_btn.setToolTip("Find a run that is active on the cluster (started from this window earlier, or before it was closed) and follow its log.")
        self.unwatch_btn.setToolTip("Stop following the log. The run itself keeps going on the cluster."); self.stopcl_btn.setToolTip("Ask the cluster to end the run (SCOPE continues where it stopped the next time you run).")
        self.run_btn.setProperty("primary", True); self.unwatch_btn.setEnabled(False); self.stopcl_btn.setEnabled(False)
        row2 = QHBoxLayout(); row2.addWidget(QLabel("System")); row2.addWidget(self.system); [row2.addWidget(b) for b in (self.pre_up, self.up, self.down)]; row2.addStretch(1)
        row3 = QHBoxLayout(); [row3.addWidget(b) for b in (self.run_btn, self.watch_btn, self.unwatch_btn, self.stopcl_btn)]; row3.addStretch(1)
        self.log, self.status = QPlainTextEdit(), QLabel("Nothing has been sent to the cluster yet."); self.log.setReadOnly(True); self.log.setLineWrapMode(QPlainTextEdit.NoWrap)
        head = QLabel("SCOPE runs on the cluster; this window starts it over SSH and moves files with rsync. Your SSH setup is used as it is and no password is stored. Nothing is sent until you press a button."); head.setWordWrap(True); head.setObjectName("pagesub")
        split = QSplitter(Qt.Vertical); upper = QWidget(); ul = QVBoxLayout(upper); ul.setContentsMargins(0, 0, 0, 0); ul.addWidget(self.table); lower = QWidget(); ll = QVBoxLayout(lower); ll.setContentsMargins(0, 0, 0, 0); ll.addLayout(row2); ll.addLayout(row3); ll.addWidget(self.log, 1)
        self.table.setMinimumHeight(210); self.log.setMinimumHeight(150); split.addWidget(upper); split.addWidget(lower); split.setStretchFactor(0, 1); split.setStretchFactor(1, 1); split.setSizes([260, 300])
        self.setMinimumHeight(720)
        self.hint = QLabel(); self.hint.setWordWrap(True)
        self.lights = remote.unchecked_lights(); self.checked_at = ""
        self.lights_row = QHBoxLayout(); self.lights_title = QLabel("On the cluster:"); self.lights_row.addWidget(self.lights_title)
        self.light_labels = [QLabel() for _ in range(3)]; [self.lights_row.addWidget(l) for l in self.light_labels]; self.lights_row.addStretch(1); self.when = QLabel(); self.when.setObjectName("pagesub"); self.lights_row.addWidget(self.when)
        lay = QVBoxLayout(self); lay.addWidget(head); lay.addLayout(top); lay.addLayout(form); lay.addWidget(self.hint); lay.addLayout(row1); lay.addWidget(self.status); lay.addLayout(self.lights_row); lay.addWidget(split, 1)
        for edit in (self.name, self.scope_bin, self.activate, self.root, self.env_file): edit.textChanged.connect(self.update_hint)
        for edit in (self.root, self.env_file): edit.textChanged.connect(self.project_edited)
        self.host.editTextChanged.connect(self.update_hint)
        self.new_btn.clicked.connect(self.new_profile); self.delete_btn.clicked.connect(self.delete_profile); self.save_btn.clicked.connect(self.save_profile); self.chooser.currentTextChanged.connect(self.choose)
        self.terminal_btn.clicked.connect(self.show_terminal_command); self.test_btn.clicked.connect(self.test_connection)
        self.pre_up.clicked.connect(lambda: self.upload(preview=True)); self.up.clicked.connect(lambda: self.upload(preview=False)); self.run_btn.clicked.connect(self.run_remote)
        self.watch_btn.clicked.connect(self.watch_runs); self.unwatch_btn.clicked.connect(self.stop_watching); self.stopcl_btn.clicked.connect(self.stop_cluster_run)
        self.down.clicked.connect(self.open_download)
        session.systemsChanged.connect(self.refresh_systems); session.envChanged.connect(self.refresh_systems); theme.on_change(self.render_checks); theme.on_change(self.render_lights)
        self.reload_chooser(); self.refresh_systems(); self.update_hint(); self.render_lights()

    ##### profiles #####
    def reload_chooser(self, select: str="") -> None:
        self.chooser.blockSignals(True); self.chooser.clear(); self.chooser.addItems(sorted(self.profiles)); self.chooser.blockSignals(False)
        if select in self.profiles: self.chooser.setCurrentText(select)
        self.choose(self.chooser.currentText())

    def choose(self, name: str) -> None:
        """Shows the connection of a saved profile. The project fields are not touched: they belong to the workspace."""
        p = self.profiles.get(name, remote.Profile())
        self.lights, self.checked_at = remote.unchecked_lights(), ""; self.render_lights()
        self.name.setText(p.name); self.host.setEditText(p.host); self.scope_bin.setText(p.scope_bin); self.activate.setText(p.activate)
        if not self.loading_project: self.projectChanged.emit()

    def select_profile(self, name: str) -> None:
        """Selects a saved connection by name (or none)."""
        self.chooser.blockSignals(True)
        if name in self.profiles: self.chooser.setCurrentText(name)
        else: self.chooser.setCurrentIndex(-1)
        self.chooser.blockSignals(False); self.choose(name if name in self.profiles else "")

    def set_project(self, root: str, env: str, suggestion: str="") -> None:
        """Shows the project on the cluster of the workspace (without saving anything back)."""
        self.loading_project = True
        self.root.setText(root); self.env_file.setText(env)
        self.root.setPlaceholderText(f"{suggestion}  (a folder on the cluster; it need not exist yet)" if suggestion else "~/scope_project  (a folder on the cluster; it need not exist yet)")
        self.loading_project = False; self.update_hint()

    def set_shared(self, names: list) -> None:
        """Other workspaces that use the same project folder on the same cluster (shown as a warning)."""
        self.shared = list(names); self.update_hint()

    def project(self) -> tuple:
        return self.root.text().strip(), self.env_file.text().strip()

    def project_edited(self) -> None:
        if not self.loading_project: self.projectChanged.emit()

    def new_profile(self) -> None:
        self.chooser.blockSignals(True); self.chooser.setCurrentIndex(-1); self.chooser.blockSignals(False); self.choose("")

    def update_hint(self) -> None:
        """Tells, while the user types, what is still missing or wrong in the profile (the same checks Save and Test use)."""
        p = self.current(); problems = remote.field_problems(p)
        labels = {"name": "Profile name", "host": "SSH host", "scope_bin": "Path of scope", "root": "Project folder", "env": "Environment file"}
        if problems: self.hint.setText("To complete the profile and the project:\n" + "\n".join(f"  • {labels[k]}: {v}" for k, v in problems.items())); set_kind(self.hint, "warn")
        else: self.hint.setText("✓ The connection and the project are complete. Save the profile, then Test connection."); set_kind(self.hint, "ok")
        if self.shared:
            self.hint.setText(self.hint.text() + f"\n⚠ The same project folder on this cluster is used by workspace(s): {', '.join(self.shared)}. Do not run the same system from both: the cluster refuses a second run of a system that is running, but results registered in one workspace are not seen by the other until you download them.")
            set_kind(self.hint, "warn")
        root = self.root.text().strip()
        self.env_file.setPlaceholderText((root.rstrip("/") + "/scope_env_<name>.npy") if root else "~/scope_project/scope_env_cluster.npy")

    def current(self) -> "remote.Profile":
        return remote.Profile(self.name.text().strip(), self.host.currentText().strip(), self.scope_bin.text().strip(), self.activate.text().strip(), self.root.text().strip(), self.env_file.text().strip())

    def save_profile(self) -> bool:
        """Saves the connection (name, host, how to start scope). The project fields are saved with the workspace, not in the profile."""
        p = self.current(); labels = {"name": "Profile name", "host": "SSH host", "scope_bin": "Path of scope"}
        problems = [f"{labels[k]}: {v}" for k, v in remote.connection_problems(p).items()]
        if problems: QMessageBox.warning(self, "Profile not saved", "\n".join(problems)); return False
        remote.save_profile(p, connection_only=True); self.profiles = remote.load_profiles()
        self.loading_project = True; self.reload_chooser(p.name); self.loading_project = False; self.projectChanged.emit()
        self.status.setText(f"✓ Profile '{p.name}' saved. Next: Test connection."); set_kind(self.status, "ok"); return True

    def delete_profile(self) -> None:
        name = self.chooser.currentText()
        if name and QMessageBox.question(self, "Delete profile", f"Delete the profile '{name}'? Nothing on the cluster is touched.") == QMessageBox.Yes:
            remote.delete_profile(name); self.profiles = remote.load_profiles(); self.reload_chooser()

    def valid_profile(self) -> "remote.Profile | None":
        p = self.current(); problems = remote.validate_profile(p)
        if problems: QMessageBox.warning(self, "Check the profile", "\n".join(problems)); return None
        return p

    def show_terminal_command(self) -> None:
        p = self.current()
        if not p.host: QMessageBox.information(self, "No host", "Choose or type the SSH host first."); return
        dialog = QDialog(self); dialog.setWindowTitle("Open a connection in the Terminal"); lay = QVBoxLayout(dialog)
        text = QLabel("If the cluster asks for a password or a second factor, this window cannot answer. Run this command once in the Terminal app, log in, and leave it. The connection stays open and this window reuses it:"); text.setWordWrap(True)
        box = QPlainTextEdit(remote.master_command(p)); box.setReadOnly(True); box.setMaximumHeight(70)
        copy = QPushButton("Copy"); copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(box.toPlainText())); close = QPushButton("Close"); close.clicked.connect(dialog.accept)
        row = QHBoxLayout(); row.addStretch(1); row.addWidget(copy); row.addWidget(close); lay.addWidget(text); lay.addWidget(box); lay.addLayout(row); dialog.resize(640, 220); dialog.exec()

    ##### connection test #####
    def set_busy(self, busy: bool, message: str="") -> None:
        self.busy = busy
        for b in (self.test_btn, self.pre_up, self.up, self.down, self.watch_btn): b.setEnabled(not busy)
        self.run_btn.setEnabled(not busy and not self.watching)
        if message: self.status.setText(message)

    def background(self, fn: Callable, on_done: Callable, message: str) -> None:
        self.set_busy(True, message); task = Task(fn); self.tasks.append(task)
        task.signals.done.connect(lambda r: (self.set_busy(False), on_done(r))); task.signals.failed.connect(lambda m: (self.set_busy(False, f"Failed: {m}"), self.log.appendPlainText(f"Failed: {m}")))
        QThreadPool.globalInstance().start(task)

    def test_connection(self) -> None:
        p = self.valid_profile()
        if not p: return
        import scope
        self.table.setRowCount(0); self.log.appendPlainText(f"$ ssh {p.host}  (connection test, read-only)")
        self.lights = remote.unchecked_lights("Checking…"); self.checked_at = ""; self.render_lights()
        def work():
            result = remote.run_script(p, remote.probe_script(p), timeout=90)
            from scope.gui import updates
            return remote.evaluate_probe(p, result, getattr(scope, "__version__", ""), updates.local_commit()), remote.lights_from_probe(remote.parse_probe(result.stdout))
        self.background(work, self.show_checks, f"Testing {p.host}…")

    def render_lights(self) -> None:
        """Draws the three lights (SCOPE, Quantum ESPRESSO, Gaussian 16): green available, amber doubtful, red missing, grey not checked or not set."""
        c = theme.colors(); colour = {"green": c["ok"], "amber": c["warn"], "red": c["err"], "grey": c["sub"]}
        for label, light in zip(self.light_labels, self.lights):
            label.setText(f'<span style="color:{colour[light.state]}; font-size:17px">●</span>&nbsp;<b>{light.name}</b>&nbsp;<span style="color:{c["sub"]}">{light.short}</span>&nbsp;&nbsp;')
            label.setToolTip(light.detail); label.setTextFormat(Qt.RichText)
        self.when.setText(f"checked {self.checked_at}" if self.checked_at else "")

    def show_checks(self, outcome) -> None:
        checks, self.lights = outcome; self.checked_at = time.strftime("%H:%M:%S"); self.render_lights()
        self.checks = checks; self.render_checks()
        failed = [c for c in checks if c.status == "fail"]; warned = [c for c in checks if c.status == "warn"]
        self.session.mark("cluster", not failed and bool(checks))
        if not failed and checks: self.announce_runs()
        self.status.setText("Connection test passed." + (f" {len(warned)} warning(s)." if warned else "") if not failed else f"Connection test failed: {len(failed)} problem(s). Fix them and test again.")

    def render_checks(self) -> None:
        c = theme.colors(); glyph = {"ok": ("✓", c["ok"]), "warn": ("!", c["warn"]), "fail": ("✗", c["err"])}
        self.table.setRowCount(len(self.checks))
        for i, chk in enumerate(self.checks):
            g, colour = glyph[chk.status]
            for j, text in enumerate((g, chk.name, chk.detail)):
                item = QTableWidgetItem(text); item.setForeground(QBrush(QColor(colour if j == 0 else c["text"]))); self.table.setItem(i, j, item)
        self.table.resizeRowsToContents()

    ##### files #####
    def refresh_systems(self) -> None:
        current = self.system.currentText(); self.system.clear()
        self.system.addItems([r.name for r in self.session.systems() if r.file])
        if current: self.system.setCurrentText(current)

    def need(self) -> "tuple | None":
        p = self.valid_profile()
        if not p: return None
        if not self.session.info or not self.system.currentText(): QMessageBox.information(self, "Choose a system", "Create an environment and import a system first (steps 1 and 2)."); return None
        return p, self.session.info, self.system.currentText()

    def unique_inputs(self, paths: list) -> bool:
        """Refuses input files that share a file name: on the cluster they all go into one inputs folder and would replace each other."""
        same = remote.duplicate_names(paths)
        if same: QMessageBox.warning(self, "Input files with the same name", "These file names are used by more than one input file: " + ", ".join(same) + ".\n\nOn the cluster all inputs go into one folder, so they would replace each other. Rename them in step 3.")
        return not same

    def show_sync(self, results: list, verb: str) -> int:
        total = 0
        for kind, res, lines in results:
            self.log.appendPlainText(f"{verb} {kind}: " + ("error: " + (res.stderr.strip() or f"exit code {res.returncode}") if not res.ok else f"{len(lines)} change(s)"))
            for line in lines[:60]: self.log.appendPlainText("    " + line)
            if len(lines) > 60: self.log.appendPlainText(f"    … and {len(lines) - 60} more")
            total += len(lines) if res.ok else 0
        return total

    def upload(self, preview: bool) -> None:
        got = self.need()
        if not got: return
        p, info, system = got; inputs = [r.path for r in self.session.reports if r.ok]
        if not self.unique_inputs(inputs): return
        items = remote.upload_items(p, info, system, inputs)
        def work():
            made = remote.run_script(p, remote.remote_dirs_script(p, system))
            return (made, remote.sync(items, dry_run=True)) if made.ok else (made, [])
        def done(result):
            made, dry = result
            if not made.ok: self.log.appendPlainText("Cannot prepare the folders on the cluster: " + (made.stderr.strip() or f"exit code {made.returncode}")); self.status.setText("Upload not possible."); return
            n = self.show_sync(dry, "Would copy"); self.status.setText(f"Preview: {n} change(s). Nothing was copied.")
            if preview or n == 0: return
            if QMessageBox.question(self, "Upload", f"Copy {n} change(s) to {p.host}:{p.remote_root}?\n\nSystem '{system}' and {len(inputs)} input file(s). Existing files with the same name are replaced; nothing is deleted.") != QMessageBox.Yes: return
            self.background(lambda: remote.sync(items, dry_run=False), lambda r: (self.show_sync(r, "Copied"), self.status.setText("Upload finished.")), "Uploading…")
        self.background(work, done, "Checking what would be copied…")

    def open_download(self) -> "object | None":
        """Opens the download dialog for the selected system: list, choose, copy into this workspace's folders (or copy the command line)."""
        got = self.need()
        if not got: return None
        from scope.gui.download_dialog import DownloadDialog
        p, info, system = got
        self.download_dialog = DownloadDialog(self, p, info, system); self.download_dialog.downloaded.connect(self.session.systemsChanged.emit)
        self.download_dialog.setWindowModality(Qt.WindowModal); self.download_dialog.show()
        return self.download_dialog

    ##### run: started detached, followed by reading its log #####
    def run_remote(self) -> None:
        got = self.need()
        if not got: return
        p, info, system = got; valid = [r for r in self.session.reports if r.ok]
        if not valid: QMessageBox.information(self, "No input files", "Create at least one valid input file in step 3."); return
        if not self.unique_inputs([r.path for r in valid]): return
        submit = [r for r in valid if r.want_submit]
        note = (f"\n\n{len(submit)} input file(s) have want_submit = True: jobs WILL be submitted to the scheduler and use computing time." if submit else "\n\nNo input file asks to submit.")
        if self.shared: note += f"\n\nThis project folder is also used by workspace(s): {', '.join(self.shared)}."
        missing = remote.unavailable_software(self.lights, valid)
        if missing: note += "\n\nWARNING from the last connection test:\n" + "\n".join(missing)
        if QMessageBox.question(self, "Run on the cluster", f"Start `scope run` for '{system}' on {p.host}, with the files uploaded in {p.remote_root}/inputs.\n\nThe run is detached: it keeps going on the cluster if you close this window or lose the connection.{note}") != QMessageBox.Yes: return
        script = remote.detached_run_script(p, system, [f"{p.remote_root.rstrip('/')}/inputs/{os.path.basename(r.path)}" for r in valid])
        self.log.appendPlainText(f"\n$ ssh {p.host}  (start `scope set_path` and `scope run` for {system}, detached)\n")
        self.background(lambda: remote.run_script(p, script, timeout=60), lambda res: self.started(p, system, res), f"Starting the run on {p.host}…")

    def started(self, p: "remote.Profile", system: str, res: "remote.Result") -> None:
        info = remote.parse_started(res.stdout)
        if not info: self.log.appendPlainText("Could not start the run: " + (res.stderr.strip() or res.stdout.strip() or f"exit code {res.returncode}")); self.status.setText("The run did not start."); return
        if info["state"] == "busy":
            self.log.appendPlainText(f"A run of '{system}' is already active on the cluster (process {info['pid']}). Two runs on one system can overwrite each other's results, so none was started. Following the active one…"); self.watch_runs(); return
        self.begin_watch(p, system, info["log"], f"Run started on the cluster (process {info['pid']}). It keeps going if you close this window or lose the connection.")

    def begin_watch(self, p: "remote.Profile", system: str, log: str, note: str="") -> None:
        self.watching = {"profile": p, "system": system, "log": log, "offset": 0, "polling": False}
        if note: self.log.appendPlainText(note + f"\nLog on the cluster: {log}\n")
        self.run_btn.setEnabled(False); self.unwatch_btn.setEnabled(True); self.stopcl_btn.setEnabled(True); self.status.setText(f"Watching the run on {p.host}…")
        self.poll_timer.start(self.poll_ms); self.poll()

    def poll(self) -> None:
        w = self.watching
        if not w or w["polling"]: return
        w["polling"] = True; p = w["profile"]; task = Task(lambda: remote.run_script(p, remote.poll_script(p, w["system"], w["log"], w["offset"]), timeout=45)); self.tasks.append(task)
        task.signals.done.connect(lambda res, w=w: self.polled(w, res)); task.signals.failed.connect(lambda m, w=w: self.polled(w, remote.Result(-1, "", m)))
        QThreadPool.globalInstance().start(task)

    def polled(self, w: dict, res: "remote.Result") -> None:
        if self.watching is not w: return                                   # stopped watching meanwhile
        w["polling"] = False
        if not res.ok: self.status.setText("Cannot reach the cluster right now. The run goes on there; trying again…"); return
        d = remote.parse_poll(res.raw or res.stdout)
        if d["text"].strip("\n"): self.log.appendPlainText(d["text"].rstrip("\n")); w["offset"] += d["bytes"]
        if d["exit"] is not None or not d["alive"]:
            self.poll_timer.stop(); self.watching = None; self.unwatch_btn.setEnabled(False); self.stopcl_btn.setEnabled(False); self.run_btn.setEnabled(not self.busy)
            if d["exit"] == 143: self.status.setText("The cluster run was stopped. Run again: SCOPE continues where it stopped.")
            elif d["exit"] is not None:
                self.status.setText(f"Cluster run finished with exit code {d['exit']}.")
                if d["exit"] == 0: self.session.mark("ran"); self.status.setText(f"Cluster run finished with exit code 0. Press Download results… to bring the results back.")
            else: self.status.setText("The cluster run ended without finishing (stopped or killed). Run again: SCOPE continues where it stopped.")

    def stop_watching(self) -> None:
        """Stops following the log; the run itself is not touched."""
        self.poll_timer.stop()
        if self.watching:
            self.watching = None; self.unwatch_btn.setEnabled(False); self.stopcl_btn.setEnabled(False); self.run_btn.setEnabled(not self.busy)
            self.status.setText("Not watching. The run continues on the cluster; press Watch runs to follow it again.")

    def stop_cluster_run(self) -> None:
        w = self.watching
        if not w: return
        if QMessageBox.question(self, "Stop the run", f"Ask {w['profile'].host} to end the run of '{w['system']}'?\n\nJobs already submitted to the scheduler are not cancelled. SCOPE continues where it stopped the next time you run.") != QMessageBox.Yes: return
        p, system = w["profile"], w["system"]
        self.background(lambda: remote.run_script(p, remote.stop_script(p, system), timeout=30), lambda res: self.log.appendPlainText("Stop requested: " + (res.stdout.strip() or res.stderr.strip())), "Stopping…")

    def announce_runs(self) -> None:
        """After a passed connection test: tell, read-only, whether a run of this project is still active on the cluster."""
        p = self.current()
        self.background(lambda: remote.parse_runs(remote.run_script(p, remote.list_runs_script(p), timeout=30).stdout),
                        lambda found: (self.log.appendPlainText("Active on the cluster: " + ", ".join(f"run of '{s}' (process {pid})" for s, pid, _ in found["active"]) + ". Press Watch runs to follow it.") if found["active"] else None), "Looking for active runs…")

    def watch_runs(self) -> None:
        """Finds a run that is active on the cluster (for instance one started before this window was closed) and follows its log."""
        p = self.valid_profile()
        if not p: return
        def done(found):
            current = self.system.currentText()
            if found["active"]:
                system, pid, log = next((a for a in found["active"] if a[0] == remote.pid_name(current)), found["active"][0])
                self.begin_watch(p, system, log, f"Following the active run of '{system}' (process {pid}).")
            elif found["logs"]: self.log.appendPlainText(f"No run is active on the cluster. The latest log is {found['logs'][0]}"); self.status.setText("No active run.")
            else: self.status.setText("No run found on the cluster for this project.")
        self.background(lambda: remote.parse_runs(remote.run_script(p, remote.list_runs_script(p), timeout=30).stdout), done, f"Looking for runs on {p.host}…")

    def running(self) -> bool:
        return bool(self.watching)
