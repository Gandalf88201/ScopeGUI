"""Cluster page: connection profile, connection test, upload, run on the cluster, download.

Network work runs in worker threads (plain subprocess calls, no chdir) or, for `scope run`, in a QProcess whose stdin
carries the script. Nothing contacts a host until the user presses a button, and nothing is copied before the user has
seen the list of files.
"""
import os
import time
from collections.abc import Callable
from PySide6.QtCore    import QProcess, QThreadPool, Qt
from PySide6.QtGui     import QBrush, QColor, QGuiApplication
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)
from scope.gui import backend, remote, theme
from scope.gui.theme import set_kind
from scope.gui.tasks import Task

class RemoteTab(QWidget):
    def __init__(self, session):
        super().__init__()
        self.session, self.proc, self.busy, self.checks, self.tasks = session, None, False, [], []
        self.profiles = remote.load_profiles()
        self.chooser  = QComboBox(); self.chooser.setMinimumWidth(180)
        self.new_btn, self.delete_btn, self.save_btn = QPushButton("New"), QPushButton("Delete"), QPushButton("Save profile")
        self.name, self.scope_bin, self.activate, self.root, self.env_file = QLineEdit(), QLineEdit(), QLineEdit(), QLineEdit(), QLineEdit()
        self.host = QComboBox(); self.host.setEditable(True); self.host.addItems(remote.list_ssh_hosts()); self.host.setEditText("")
        self.host.lineEdit().setPlaceholderText("host name or alias from ~/.ssh/config")
        self.scope_bin.setPlaceholderText("~/miniconda3/envs/scope/bin/scope  (or the full /home/you/... path)"); self.activate.setPlaceholderText("optional, only if the path above is empty")
        self.root.setPlaceholderText("~/scope_project  (a folder on the cluster; it need not exist yet)"); self.env_file.setPlaceholderText("/home/you/scope_project/scope_env_cluster.npy")
        form = QFormLayout(); form.setLabelAlignment(Qt.AlignRight)
        for label, w in (("Profile name", self.name), ("SSH host", self.host), ("Path of scope on the cluster", self.scope_bin), ("…or a line that makes it available", self.activate), ("Project folder on the cluster", self.root), ("Cluster environment file", self.env_file)): form.addRow(label, w)
        top = QHBoxLayout(); top.addWidget(QLabel("Profile")); top.addWidget(self.chooser); top.addWidget(self.new_btn); top.addWidget(self.delete_btn); top.addStretch(1)
        self.terminal_btn, self.test_btn = QPushButton("Show terminal command"), QPushButton("Test connection"); self.test_btn.setProperty("primary", True)
        self.save_btn.setProperty("primary", True); row1 = QHBoxLayout(); row1.addWidget(self.save_btn); row1.addWidget(self.terminal_btn); row1.addWidget(self.test_btn); row1.addStretch(1)
        self.table = QTableWidget(0, 3); self.table.setHorizontalHeaderLabels(["", "Check", "Result"]); self.table.setEditTriggers(QAbstractItemView.NoEditTriggers); self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents); self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents); self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch); self.table.verticalHeader().setVisible(False)
        self.table.setWordWrap(True)
        self.system = QComboBox(); self.system.setMinimumWidth(200)
        self.pre_up, self.up, self.run_btn, self.pre_down, self.down, self.stop_btn = (QPushButton(t) for t in ("Preview upload", "Upload", "Run on the cluster", "Preview download", "Download", "Stop"))
        self.run_btn.setProperty("primary", True); self.stop_btn.setEnabled(False)
        row2 = QHBoxLayout(); row2.addWidget(QLabel("System")); row2.addWidget(self.system); [row2.addWidget(b) for b in (self.pre_up, self.up, self.run_btn, self.stop_btn, self.pre_down, self.down)]; row2.addStretch(1)
        self.log, self.status = QPlainTextEdit(), QLabel("Nothing has been sent to the cluster yet."); self.log.setReadOnly(True); self.log.setLineWrapMode(QPlainTextEdit.NoWrap)
        head = QLabel("SCOPE runs on the cluster; this window starts it over SSH and moves files with rsync. Your SSH setup is used as it is and no password is stored. Nothing is sent until you press a button."); head.setWordWrap(True); head.setObjectName("pagesub")
        split = QSplitter(Qt.Vertical); upper = QWidget(); ul = QVBoxLayout(upper); ul.setContentsMargins(0, 0, 0, 0); ul.addWidget(self.table); lower = QWidget(); ll = QVBoxLayout(lower); ll.setContentsMargins(0, 0, 0, 0); ll.addLayout(row2); ll.addWidget(self.log, 1)
        self.table.setMinimumHeight(210); self.log.setMinimumHeight(150); split.addWidget(upper); split.addWidget(lower); split.setStretchFactor(0, 1); split.setStretchFactor(1, 1); split.setSizes([260, 300])
        self.setMinimumHeight(720)
        self.hint = QLabel(); self.hint.setWordWrap(True)
        self.lights = remote.unchecked_lights(); self.checked_at = ""
        self.lights_row = QHBoxLayout(); self.lights_title = QLabel("On the cluster:"); self.lights_row.addWidget(self.lights_title)
        self.light_labels = [QLabel() for _ in range(3)]; [self.lights_row.addWidget(l) for l in self.light_labels]; self.lights_row.addStretch(1); self.when = QLabel(); self.when.setObjectName("pagesub"); self.lights_row.addWidget(self.when)
        lay = QVBoxLayout(self); lay.addWidget(head); lay.addLayout(top); lay.addLayout(form); lay.addWidget(self.hint); lay.addLayout(row1); lay.addWidget(self.status); lay.addLayout(self.lights_row); lay.addWidget(split, 1)
        for edit in (self.name, self.scope_bin, self.activate, self.root, self.env_file): edit.textChanged.connect(self.update_hint)
        self.host.editTextChanged.connect(self.update_hint)
        self.new_btn.clicked.connect(self.new_profile); self.delete_btn.clicked.connect(self.delete_profile); self.save_btn.clicked.connect(self.save_profile); self.chooser.currentTextChanged.connect(self.choose)
        self.terminal_btn.clicked.connect(self.show_terminal_command); self.test_btn.clicked.connect(self.test_connection)
        self.pre_up.clicked.connect(lambda: self.upload(preview=True)); self.up.clicked.connect(lambda: self.upload(preview=False)); self.run_btn.clicked.connect(self.run_remote); self.stop_btn.clicked.connect(self.stop)
        self.pre_down.clicked.connect(lambda: self.download(preview=True)); self.down.clicked.connect(lambda: self.download(preview=False))
        session.systemsChanged.connect(self.refresh_systems); session.envChanged.connect(self.refresh_systems); theme.on_change(self.render_checks); theme.on_change(self.render_lights)
        self.reload_chooser(); self.refresh_systems(); self.update_hint(); self.render_lights()

    ##### profiles #####
    def reload_chooser(self, select: str="") -> None:
        self.chooser.blockSignals(True); self.chooser.clear(); self.chooser.addItems(sorted(self.profiles)); self.chooser.blockSignals(False)
        if select in self.profiles: self.chooser.setCurrentText(select)
        self.choose(self.chooser.currentText())

    def choose(self, name: str) -> None:
        p = self.profiles.get(name, remote.Profile())
        self.lights, self.checked_at = remote.unchecked_lights(), ""; self.render_lights()
        self.name.setText(p.name); self.host.setEditText(p.host); self.scope_bin.setText(p.scope_bin); self.activate.setText(p.activate); self.root.setText(p.remote_root); self.env_file.setText(p.remote_env)

    def new_profile(self) -> None:
        self.chooser.blockSignals(True); self.chooser.setCurrentIndex(-1); self.chooser.blockSignals(False); self.choose("")

    def update_hint(self) -> None:
        """Tells, while the user types, what is still missing or wrong in the profile (the same checks Save and Test use)."""
        p = self.current(); problems = remote.field_problems(p)
        labels = {"name": "Profile name", "host": "SSH host", "scope_bin": "Path of scope", "root": "Project folder", "env": "Environment file"}
        if problems: self.hint.setText("To complete the profile:\n" + "\n".join(f"  • {labels[k]}: {v}" for k, v in problems.items())); set_kind(self.hint, "warn")
        else: self.hint.setText("✓ The profile is complete. Press Save profile, then Test connection."); set_kind(self.hint, "ok")
        root = self.root.text().strip()
        self.env_file.setPlaceholderText((root.rstrip("/") + "/scope_env_<name>.npy") if root else "~/scope_project/scope_env_cluster.npy")

    def current(self) -> "remote.Profile":
        return remote.Profile(self.name.text().strip(), self.host.currentText().strip(), self.scope_bin.text().strip(), self.activate.text().strip(), self.root.text().strip(), self.env_file.text().strip())

    def save_profile(self) -> bool:
        p = self.current(); problems = remote.validate_profile(p)
        if problems: QMessageBox.warning(self, "Profile not saved", "\n".join(problems)); return False
        remote.save_profile(p); self.profiles = remote.load_profiles(); self.reload_chooser(p.name); self.status.setText(f"✓ Profile '{p.name}' saved. Next: Test connection."); set_kind(self.status, "ok"); return True

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
        for b in (self.test_btn, self.pre_up, self.up, self.run_btn, self.pre_down, self.down): b.setEnabled(not busy)
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
            return remote.evaluate_probe(p, result, getattr(scope, "__version__", "")), remote.lights_from_probe(remote.parse_probe(result.stdout))
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
        if self.session.info: self.system.addItems([r.name for r in backend.list_systems(self.session.info) if r.file])
        if current: self.system.setCurrentText(current)

    def need(self) -> "tuple | None":
        p = self.valid_profile()
        if not p: return None
        if not self.session.info or not self.system.currentText(): QMessageBox.information(self, "Choose a system", "Create an environment and import a system first (steps 1 and 2)."); return None
        return p, self.session.info, self.system.currentText()

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

    def download(self, preview: bool) -> None:
        got = self.need()
        if not got: return
        p, info, system = got; items = remote.download_items(p, info, system)
        def done(dry):
            n = self.show_sync(dry, "Would copy"); self.status.setText(f"Preview: {n} change(s). Nothing was copied.")
            if preview or n == 0: return
            replaces = any(f"{system}.npy" in l for kind, _, lines in dry if kind == "system" for l in lines)
            note = f"\n\nThis replaces the local system file {system}.npy with the cluster's. Anything registered only locally since the last upload would be lost." if replaces else ""
            if QMessageBox.question(self, "Download", f"Copy {n} change(s) from {p.host}?{note}") != QMessageBox.Yes: return
            self.background(lambda: remote.sync(items, dry_run=False), lambda r: (self.show_sync(r, "Copied"), self.status.setText("Download finished."), self.session.systemsChanged.emit()), "Downloading…")
        self.background(lambda: remote.sync(items, dry_run=True), done, "Checking what would be copied…")

    ##### run #####
    def run_remote(self) -> None:
        got = self.need()
        if not got: return
        p, info, system = got; valid = [r for r in self.session.reports if r.ok]
        if not valid: QMessageBox.information(self, "No input files", "Create at least one valid input file in step 3."); return
        submit = [r for r in valid if r.want_submit]
        note = (f"\n\n{len(submit)} input file(s) have want_submit = True: jobs WILL be submitted to the scheduler and use computing time." if submit else "\n\nNo input file asks to submit.")
        missing = remote.unavailable_software(self.lights, valid)
        if missing: note += "\n\nWARNING from the last connection test:\n" + "\n".join(missing)
        if QMessageBox.question(self, "Run on the cluster", f"Run `scope run` for '{system}' on {p.host}, with the files uploaded in {p.remote_root}/inputs.{note}") != QMessageBox.Yes: return
        script = remote.run_script_text(p, system, [f"{p.remote_root.rstrip('/')}/inputs/{os.path.basename(r.path)}" for r in valid])
        self.log.appendPlainText(f"\n$ ssh {p.host} 'scope set_path … && scope run -s {system} …'\n")
        self.proc = QProcess(self); self.proc.setProcessChannelMode(QProcess.MergedChannels)
        self.proc.readyReadStandardOutput.connect(lambda: self.log.appendPlainText(bytes(self.proc.readAllStandardOutput()).decode("utf-8", errors="replace").rstrip("\n")))
        self.proc.finished.connect(self.run_finished); self.proc.errorOccurred.connect(lambda e: self.status.setText("Could not start ssh") if e == QProcess.FailedToStart else None)
        argv = remote.ssh_argv(p); self.proc.start(argv[0], argv[1:]); self.proc.write(script.encode()); self.proc.closeWriteChannel()
        self.set_busy(True, f"Running on {p.host}…"); self.stop_btn.setEnabled(True)

    def run_finished(self, code: int, status) -> None:
        self.log.appendPlainText(bytes(self.proc.readAllStandardOutput()).decode("utf-8", errors="replace").rstrip("\n"))
        self.set_busy(False, f"Cluster run finished with exit code {code}." if status == QProcess.NormalExit else "Cluster run stopped."); self.stop_btn.setEnabled(False)
        if status == QProcess.NormalExit and code == 0: self.session.mark("ran")

    def stop(self) -> None:
        if self.proc and self.proc.state() != QProcess.NotRunning: self.proc.terminate()

    def running(self) -> bool:
        return bool(self.proc and self.proc.state() != QProcess.NotRunning)
