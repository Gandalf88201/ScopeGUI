"""Cluster page: connection (profile, Connect…, test), where SCOPE and the project are, upload, run on the cluster, download.

Network work runs in worker threads (plain subprocess calls, no chdir). A run on the cluster is started detached (nohup, its own
log and pid file on the cluster): the window only watches it by reading the log, so closing the window or losing the connection
does not stop it, and a window opened later can find it again. Nothing contacts a host until the user presses a button, and nothing is copied before the user has
seen the list of files.
"""
import os
import queue
import re
import time
from collections.abc import Callable
from PySide6.QtCore    import QObject, QThreadPool, QTimer, Qt, Signal
from PySide6.QtGui     import QBrush, QColor, QGuiApplication
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)
from scope.gui import backend, remote, theme
from scope.gui.theme import set_kind
from scope.gui.tasks import Task

class LoginDialog(QDialog):
    """One question of ssh (a password or a verification code), shown with what ssh said just before it. The answer is read once and not kept."""
    def __init__(self, parent, host: str, context: str, prompt: str):
        super().__init__(parent); self.setWindowTitle(f"Connect to {host}" if host else "Connect"); lay = QVBoxLayout(self); lay.setSpacing(8)
        if context:
            note = QLabel(context); note.setWordWrap(True); note.setObjectName("pagesub"); note.setTextInteractionFlags(Qt.TextSelectableByMouse); lay.addWidget(note)
        lay.addWidget(QLabel(prompt)); self.edit = QLineEdit(); self.edit.setEchoMode(QLineEdit.Password); self.edit.setMinimumWidth(360); lay.addWidget(self.edit)
        self.reveal = QCheckBox("Show what I type"); self.reveal.toggled.connect(lambda on: self.edit.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password)); lay.addWidget(self.reveal)
        privacy = QLabel("It goes to the cluster only. SCOPE does not save it."); privacy.setObjectName("pagesub"); lay.addWidget(privacy)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel); buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject); lay.addWidget(buttons)
        self.edit.setFocus()

    def answer(self) -> str:
        return self.edit.text()

class LoginBridge(QObject):
    """Lets the thread that runs ssh ask the user: a dialog must be shown by the GUI thread, and the worker waits for the answer."""
    requested = Signal(str, str, str)

    def __init__(self, tab):
        super().__init__(tab); self.tab, self.answers = tab, queue.Queue(); self.requested.connect(self.on_requested)

    def ask(self, context: str, prompt: str, kind: str) -> "str | None":
        """Called in the worker thread. Returns what the user typed, or None if they cancelled."""
        self.requested.emit(context, prompt, kind); return self.answers.get()

    def on_requested(self, context: str, prompt: str, kind: str) -> None:
        try: answer = self.tab.ask_login(context, prompt, kind)
        except Exception as exc:                                             ## never leave the worker waiting, and never let a broken window pass for a cancel
            answer = None; self.tab.log.appendPlainText(f"The password window could not be shown ({type(exc).__name__}: {exc}). Use Terminal command… instead and report this.")
        self.answers.put(answer)

class RemoteTab(QWidget):
    """The Cluster page. The connection (a saved profile) is shared by all workspaces; the project on the cluster (folder and environment
    file) belongs to the workspace shown, which the window saves when projectChanged is emitted."""
    projectChanged = Signal()

    def __init__(self, session):
        super().__init__()
        self.session, self.watching, self.busy, self.checks, self.tasks, self.alive = session, None, False, [], [], False
        self.poll_ms = 5000; self.poll_timer = QTimer(self); self.poll_timer.timeout.connect(self.poll)
        self.bridge = LoginBridge(self)
        self.refresh_timer = QTimer(self); self.refresh_timer.setSingleShot(True); self.refresh_timer.setInterval(500); self.refresh_timer.timeout.connect(self.refresh_connection)
        self.profiles = remote.load_profiles()
        self.chooser  = QComboBox(); self.chooser.setMinimumWidth(140)
        self.new_btn, self.delete_btn, self.save_btn = QPushButton("New"), QPushButton("Delete"), QPushButton("Save profile")
        self.name, self.scope_bin, self.activate, self.root, self.env_file = QLineEdit(), QLineEdit(), QLineEdit(), QLineEdit(), QLineEdit()
        self.host = QComboBox(); self.host.setEditable(True); self.host.setMinimumContentsLength(16); self.host.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon); self.host.addItems(remote.list_ssh_hosts()); self.host.setEditText("")
        self.host.lineEdit().setPlaceholderText("login.cluster.org, an alias from ~/.ssh/config, or paste your ssh command (ssh -p 2122 you@login.cluster.org)")
        self.host.setToolTip("The machine you log in to. You can paste the whole command you use in the Terminal: the user name and the port are moved to their own fields.")
        self.user, self.port = QLineEdit(), QLineEdit(); self.port.setMaximumWidth(120)
        self.user.setPlaceholderText("your login name on the cluster  (empty: the one in ~/.ssh/config, or this computer's)")
        self.port.setPlaceholderText("22"); self.port.setToolTip("SSH port. Leave empty for the usual 22 (or the one in ~/.ssh/config); some clusters use another, for instance 2122.")
        self.scope_bin.setPlaceholderText("~/miniconda3/envs/scope/bin/scope  (or the full /home/you/... path)"); self.activate.setPlaceholderText("optional, only if the path above is empty")
        self.root.setPlaceholderText("~/scope_project  (a folder on the cluster; it need not exist yet)"); self.env_file.setPlaceholderText("/home/you/scope_project/scope_env_cluster.npy")
        self.loading_project, self.shared = False, []
        ## connection: the state of the shared SSH connection and the buttons that open and close it
        self.conn_badge = QLabel(); self.connect_btn, self.disconnect_btn = QPushButton("Connect…"), QPushButton("Disconnect")
        self.terminal_btn, self.test_btn = QPushButton("Terminal command…"), QPushButton("Test connection"); self.connect_btn.setProperty("primary", True)
        self.connect_btn.setToolTip("Log in to the cluster. If it asks for a password or a verification code, you answer in a window. The answer goes to the cluster only; it is not stored.\nThe connection then stays open for 4 hours and every button of this page uses it.")
        if not remote.shares_connection():                                   ## Windows: no shared connection and no password window; every command logs in with a key
            self.connect_btn.setText("Set up key login…"); self.terminal_btn.setText("Commands to do it yourself…"); self.disconnect_btn.hide()
            self.connect_btn.setToolTip("On Windows each command logs in on its own, so the cluster must accept a key from this computer. This opens a console window that creates a key if you have none\n"
                                        "and adds it to the cluster (you type the cluster password there, once). Nothing is stored by this window.")
        self.disconnect_btn.setToolTip("Close the shared connection. A run already started on the cluster keeps going."); self.test_btn.setToolTip("Check, without changing anything, that SCOPE, the project and the software are in place on the cluster.")
        self.terminal_btn.setToolTip("The same connection can be opened in the Terminal app. Use it if you prefer to type the password there, or if Connect… does not work on this computer.")
        self.adv_btn = QPushButton("▸  Advanced: start scope with a line instead of a path"); self.adv_btn.setObjectName("linkbtn"); self.adv_btn.setCheckable(True); self.adv_btn.setCursor(Qt.PointingHandCursor)
        ## checks, transfer and run
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
        self.log, self.status = QPlainTextEdit(), QLabel("Nothing has been sent to the cluster yet."); self.log.setReadOnly(True); self.log.setLineWrapMode(QPlainTextEdit.NoWrap); self.status.setWordWrap(True)
        self.hint = QLabel(); self.hint.setWordWrap(True)
        self.lights = remote.unchecked_lights(); self.checked_at = ""
        ## the software on the cluster: three equal tiles (dot and name, then the state), the time of the check on the right
        self.lights_title = QLabel("Software on the cluster"); self.lights_title.setObjectName("cardtitle")
        self.when = QLabel(); self.when.setObjectName("pagesub")
        lights_head = QHBoxLayout(); lights_head.addWidget(self.lights_title); lights_head.addStretch(1); lights_head.addWidget(self.when)
        tiles = QGridLayout(); tiles.setHorizontalSpacing(10); tiles.setContentsMargins(0, 0, 0, 0); self.light_tiles, self.light_labels = [], []
        for i in range(3):
            tile = QFrame(); tile.setObjectName("lighttile"); tl = QVBoxLayout(tile); tl.setContentsMargins(12, 8, 12, 8)
            label = QLabel(); label.setWordWrap(True); label.setTextFormat(Qt.RichText); tl.addWidget(label)
            tiles.addWidget(tile, 0, i); tiles.setColumnStretch(i, 1); self.light_tiles.append(tile); self.light_labels.append(label)
        self.lights_row = QVBoxLayout(); self.lights_row.setSpacing(6); self.lights_row.setContentsMargins(0, 6, 0, 0); self.lights_row.addLayout(lights_head); self.lights_row.addLayout(tiles)

        ##### layout: three cards, in the order of use: the cluster account, this workspace's project, then transfer and run #####
        def field(label: str, widget, left: bool=False) -> QVBoxLayout:
            box = QVBoxLayout(); box.setSpacing(3); caption = QLabel(label); caption.setObjectName("pagesub"); box.addWidget(caption)
            box.addWidget(widget, 0, Qt.AlignLeft) if left else box.addWidget(widget)
            return box
        def card(title: str) -> tuple:
            frame = QFrame(); frame.setObjectName("card"); inner = QVBoxLayout(frame); inner.setContentsMargins(16, 8, 16, 14); inner.setSpacing(8)
            head = QLabel(title); head.setObjectName("sectiontitle"); inner.addWidget(head); return frame, inner
        intro = QLabel("SCOPE runs on the cluster; this window starts it over SSH and copies files. Nothing is sent until you press a button, and no password is stored.")
        intro.setWordWrap(True); intro.setObjectName("pagesub")

        ## 1 · the cluster account: one line when the saved profile is complete; its fields only while editing
        conn, cl = card("1 · Cluster")
        self.edit_btn = QPushButton("Edit…"); self.edit_btn.setCheckable(True); self.edit_btn.setToolTip("Show the fields of this connection (host, user, port, where scope is).")
        top = QHBoxLayout(); top.addWidget(QLabel("Profile")); top.addWidget(self.chooser); top.addWidget(self.edit_btn); top.addWidget(self.new_btn); top.addWidget(self.delete_btn); top.addStretch(1); top.addWidget(self.conn_badge); cl.addLayout(top)
        self.summary = QLabel(); self.summary.setObjectName("pagesub"); self.summary.setWordWrap(True); cl.addWidget(self.summary)
        actions = QHBoxLayout(); [actions.addWidget(b) for b in (self.connect_btn, self.disconnect_btn, self.test_btn)]; actions.addStretch(1); cl.addLayout(actions)
        cl.addLayout(self.lights_row)
        self.details_btn = QPushButton("▸  Details of the last test"); self.details_btn.setObjectName("linkbtn"); self.details_btn.setCheckable(True); self.details_btn.setCursor(Qt.PointingHandCursor)
        self.details_btn.toggled.connect(lambda on: (self.table.setVisible(on), self.details_btn.setText(("▾" if on else "▸") + "  Details of the last test")))
        self.details_btn.hide(); self.table.hide(); cl.addWidget(self.details_btn); cl.addWidget(self.table)
        self.profile_box = QWidget(); pb = QVBoxLayout(self.profile_box); pb.setContentsMargins(0, 4, 0, 0); pb.setSpacing(8)
        grid = QGridLayout(); grid.setHorizontalSpacing(14); grid.setVerticalSpacing(8); grid.setColumnStretch(0, 2); grid.setColumnStretch(1, 3)
        grid.addLayout(field("Profile name", self.name), 0, 0); grid.addLayout(field("SSH host", self.host), 0, 1); grid.addLayout(field("User", self.user), 1, 0); grid.addLayout(field("Port", self.port, left=True), 1, 1); pb.addLayout(grid)
        pb.addLayout(field("Path of scope on the cluster", self.scope_bin)); pb.addWidget(self.adv_btn, 0, Qt.AlignLeft)
        self.adv_box = QWidget(); ab = QVBoxLayout(self.adv_box); ab.setContentsMargins(0, 0, 0, 0); ab.addLayout(field("…or a line that makes it available  (used only when the path is empty)", self.activate)); self.adv_box.setVisible(False); pb.addWidget(self.adv_box)
        save_row = QHBoxLayout(); save_row.addWidget(self.terminal_btn); save_row.addStretch(1); save_row.addWidget(self.save_btn); pb.addLayout(save_row)
        self.profile_box.setVisible(False); cl.addWidget(self.profile_box)
        self.edit_btn.toggled.connect(self.profile_box.setVisible)

        ## 2 · this workspace's project on the cluster
        project, jl = card("2 · Project on the cluster  (this workspace)")
        prow = QHBoxLayout(); prow.setSpacing(12); prow.addLayout(field("Project folder on the cluster", self.root), 1); prow.addLayout(field("Cluster environment file", self.env_file), 1); jl.addLayout(prow); jl.addWidget(self.hint)

        ## 3 · transfer and run
        work, wl = card("3 · Transfer and run")
        self.system.setMinimumWidth(120); self.system.setMinimumContentsLength(10); self.system.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        row2 = QHBoxLayout(); row2.addWidget(QLabel("System")); row2.addWidget(self.system, 1); [row2.addWidget(b) for b in (self.up, self.down)]
        row3 = QHBoxLayout(); [row3.addWidget(b) for b in (self.run_btn, self.watch_btn, self.stopcl_btn)]; row3.addStretch(1)
        self.pre_up.hide(); self.unwatch_btn.hide()                          ## Upload already shows what it would copy and asks; following a run stops by itself
        self.up.setToolTip("Shows what would be copied (system, input files, and calculation files only here), then asks before copying.")
        sync = QLabel("Keep the input and output files in step wherever the system runs: the system file only records what SCOPE read from them, so copying the .npy alone is not enough. "
                      "Branches, or workflows (sources), can run on different clusters; the jobs of one workflow belong in one place.")
        sync.setWordWrap(True); sync.setObjectName("pagesub")
        from scope.gui.review_view import ReviewTable
        self.review = ReviewTable(); self.review.setMinimumHeight(110); self.review_note = QLabel(); self.review_note.setWordWrap(True); self.probe = {}
        wl.addLayout(row2); wl.addLayout(row3); wl.addWidget(QLabel("Review: every input file as it will run on the cluster")); wl.addWidget(self.review); wl.addWidget(self.review_note); wl.addWidget(self.log, 1); wl.addWidget(sync)
        self.log.setMinimumHeight(160); self.table.setMinimumHeight(120)
        self.status.setObjectName("statusline")                                    ## the result of the last button, at the top of the page so it is always in view
        lay = QVBoxLayout(self); lay.setSpacing(12); lay.addWidget(intro); lay.addWidget(self.status); lay.addWidget(conn); lay.addWidget(project); lay.addWidget(work, 1)
        chain = (self.chooser, self.edit_btn, self.new_btn, self.delete_btn, self.connect_btn, self.disconnect_btn, self.test_btn, self.name, self.host, self.user, self.port, self.scope_bin, self.adv_btn, self.activate, self.terminal_btn, self.save_btn, self.root, self.env_file)
        for a, b in zip(chain, chain[1:]): QWidget.setTabOrder(a, b)

        for edit in (self.name, self.user, self.port, self.scope_bin, self.activate, self.root, self.env_file): edit.textChanged.connect(self.update_hint)
        for edit in (self.root, self.env_file): edit.textChanged.connect(self.project_edited)
        for edit in (self.user, self.port): edit.textChanged.connect(lambda _=None: self.refresh_timer.start())              ## another account is another shared connection
        self.host.editTextChanged.connect(self.update_hint); self.host.editTextChanged.connect(lambda _=None: self.refresh_timer.start()); self.host.lineEdit().editingFinished.connect(self.split_host)
        self.new_btn.clicked.connect(self.new_profile); self.delete_btn.clicked.connect(self.delete_profile); self.save_btn.clicked.connect(self.save_profile); self.chooser.currentTextChanged.connect(self.choose)
        self.connect_btn.clicked.connect(self.connect_cluster); self.disconnect_btn.clicked.connect(self.disconnect_cluster); self.adv_btn.toggled.connect(self.show_advanced)
        self.terminal_btn.clicked.connect(self.show_terminal_command); self.test_btn.clicked.connect(self.test_connection)
        self.pre_up.clicked.connect(lambda: self.upload(preview=True)); self.up.clicked.connect(lambda: self.upload(preview=False)); self.run_btn.clicked.connect(self.run_remote)
        self.watch_btn.clicked.connect(self.watch_runs); self.unwatch_btn.clicked.connect(self.stop_watching); self.stopcl_btn.clicked.connect(self.stop_cluster_run)
        self.down.clicked.connect(lambda: self.open_download())
        session.systemsChanged.connect(self.refresh_systems); session.envChanged.connect(self.refresh_systems); session.inputsChanged.connect(self.update_review); theme.on_change(self.render_checks); theme.on_change(self.render_lights)
        self.reload_chooser(); self.refresh_systems(); self.update_hint(); self.render_lights(); self.update_connection_buttons()

    ##### profiles #####
    def reload_chooser(self, select: str="") -> None:
        self.chooser.blockSignals(True); self.chooser.clear(); self.chooser.addItems(sorted(self.profiles)); self.chooser.blockSignals(False)
        if select in self.profiles: self.chooser.setCurrentText(select)
        self.choose(self.chooser.currentText())

    def choose(self, name: str) -> None:
        """Shows the connection of a saved profile. The project fields are not touched: they belong to the workspace."""
        p = self.profiles.get(name, remote.Profile())
        self.lights, self.checked_at = remote.unchecked_lights(), ""; self.render_lights()
        self.name.setText(p.name); self.host.setEditText(p.host); self.user.setText(p.user); self.port.setText(p.port); self.scope_bin.setText(p.scope_bin); self.activate.setText(p.activate)
        self.adv_btn.setChecked(bool(p.activate)); self.refresh_connection()
        if not self.loading_project: self.projectChanged.emit()

    def split_host(self) -> None:
        """When the host field holds more than a host (`you@host`, `host:2122`, or a pasted `ssh -p 2122 you@host`), moves the user name and the
        port to their own fields. A user or port already typed is replaced only by one written in the pasted text."""
        text = self.host.currentText().strip()
        if not text or not (re.search(r"[\s@]", text) or text.startswith("ssh://") or re.search(r":\d+$", text)): return
        found = remote.parse_ssh_target(text)
        if not found: return
        self.host.setEditText(found["host"])
        if found["user"]: self.user.setText(found["user"])
        if found["port"]: self.port.setText(found["port"])
        if not self.name.text().strip(): self.name.setText(re.sub(r"[^A-Za-z0-9_.-]", "_", found["host"].split(".")[0]))

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
        if problems: self.hint.setText("To complete the profile and the project:\n" + "\n".join(f"  • {remote.FIELD_LABELS[k]}: {v}" for k, v in problems.items())); set_kind(self.hint, "warn")
        else: self.hint.setText("✓ The connection and the project are complete. Save the profile, then Test connection."); set_kind(self.hint, "ok")
        if self.shared:
            self.hint.setText(self.hint.text() + f"\n⚠ The same project folder on this cluster is used by workspace(s): {', '.join(self.shared)}. Do not run the same system from both: the cluster refuses a second run of a system that is running, but results registered in one workspace are not seen by the other until you download them.")
            set_kind(self.hint, "warn")
        root = self.root.text().strip()
        self.env_file.setPlaceholderText((root.rstrip("/") + "/scope_env_<name>.npy") if root else "~/scope_project/scope_env_cluster.npy")

    def current(self) -> "remote.Profile":
        return remote.Profile(self.name.text().strip(), self.host.currentText().strip(), self.scope_bin.text().strip(), self.activate.text().strip(), self.root.text().strip(), self.env_file.text().strip(),
                              user=self.user.text().strip(), port=self.port.text().strip())

    def save_profile(self) -> bool:
        """Saves the connection (name, host, user, port, how to start scope). The project fields are saved with the workspace, not in the profile."""
        self.split_host(); p = self.current()
        problems = [f"{remote.FIELD_LABELS[k]}: {v}" for k, v in remote.connection_problems(p).items()]
        if problems: QMessageBox.warning(self, "Profile not saved", "\n".join(problems)); return False
        remote.save_profile(p, connection_only=True); self.profiles = remote.load_profiles()
        self.loading_project = True; self.reload_chooser(p.name); self.loading_project = False; self.projectChanged.emit()
        self.edit_btn.setChecked(False)                                           ## saved and complete: back to one line (Edit… opens it again)
        self.status.setText(f"✓ Profile '{p.name}' saved. Next: Test connection."); set_kind(self.status, "ok"); return True

    def delete_profile(self) -> None:
        name = self.chooser.currentText()
        if name and QMessageBox.question(self, "Delete profile", f"Delete the profile '{name}'? Nothing on the cluster is touched.") == QMessageBox.Yes:
            remote.delete_profile(name); self.profiles = remote.load_profiles(); self.reload_chooser()

    def valid_profile(self) -> "remote.Profile | None":
        self.split_host(); p = self.current(); problems = remote.validate_profile(p)
        if problems: QMessageBox.warning(self, "Check the profile", "\n".join(problems)); return None
        return p

    def show_terminal_command(self) -> None:
        p = self.current()
        if not p.host: QMessageBox.information(self, "No host", "Choose or type the SSH host first."); return
        if not remote.shares_connection():
            QMessageBox.information(self, "Key login by hand", "In PowerShell, run (answer the cluster password once):\n\n" + remote.key_setup_command(p) + "\n\nThen press Test connection."); return
        dialog = QDialog(self); dialog.setWindowTitle("Open a connection in the Terminal"); lay = QVBoxLayout(dialog)
        text = QLabel("Connect… does the same inside this window. If you prefer the Terminal, or Connect… does not work on this computer: run this command once in the Terminal app, answer the password or verification code there, and leave it. The connection stays open and this window reuses it:"); text.setWordWrap(True)
        box = QPlainTextEdit(remote.master_command(p)); box.setReadOnly(True); box.setMaximumHeight(70)
        copy = QPushButton("Copy"); copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(box.toPlainText())); close = QPushButton("Close"); close.clicked.connect(dialog.accept)
        row = QHBoxLayout(); row.addStretch(1); row.addWidget(copy); row.addWidget(close); lay.addWidget(text); lay.addWidget(box); lay.addLayout(row); theme.fit(dialog, 640, 220); dialog.exec()

    ##### the shared connection: Connect…, Disconnect, and what the page shows about it #####
    def show_advanced(self, on: bool) -> None:
        self.adv_box.setVisible(on); self.adv_btn.setText(("▾" if on else "▸") + "  Advanced: start scope with a line instead of a path")

    def refresh_connection(self) -> None:
        """Looks, on this computer only, whether a shared connection to the account in the form is open, and updates the badge and the buttons."""
        p = self.current(); self.alive = remote.connection_alive(p)
        if not remote.shares_connection(): self.conn_badge.setText("key login (each command logs in)"); set_kind(self.conn_badge, "idle")
        elif self.alive: self.conn_badge.setText(f"●  Connected to {p.host}"); set_kind(self.conn_badge, "ok")
        else: self.conn_badge.setText("○  Not connected"); set_kind(self.conn_badge, "idle")
        self.update_connection_buttons(); self.update_summary()

    def update_summary(self) -> None:
        """One line that says which account the profile reaches; the fields open with Edit… (and by themselves while the profile is incomplete)."""
        p = self.current(); incomplete = bool(remote.connection_problems(p))
        who = (f"{p.user}@" if p.user else "") + (p.host or "?") + (f", port {p.port}" if p.port else "")
        self.summary.setText("New connection: fill in the fields below and save." if not p.name and not p.host else f"{who} · scope: {p.scope_bin or p.activate or 'not set'}" + ("  (incomplete: see the fields)" if incomplete else ""))
        if incomplete and not self.edit_btn.isChecked(): self.edit_btn.setChecked(True)

    def update_connection_buttons(self) -> None:
        self.connect_btn.setEnabled(not self.busy and (not self.alive or not remote.shares_connection())); self.disconnect_btn.setEnabled(not self.busy and self.alive)

    def ask_login(self, context: str, prompt: str, kind: str) -> "str | None":
        """Shows one question of ssh and returns the answer (None: cancelled). Runs in the GUI thread. The answer is passed on and not kept."""
        host = self.host.currentText().strip()
        if kind == "confirm":
            text = (context + "\n\n" if context else "") + "Only continue if the fingerprint is the one your cluster support gives for this machine."
            return "yes" if QMessageBox.question(self, f"Trust {host or 'this cluster'}?", text) == QMessageBox.Yes else None
        dialog = LoginDialog(self, host, context, prompt)
        return dialog.answer() if dialog.exec() == QDialog.Accepted else None

    def connect_cluster(self) -> None:
        """Opens the shared connection. If the cluster asks for a password or a verification code, a window asks for it; nothing is stored."""
        self.split_host(); p = self.current()
        problems = {k: v for k, v in remote.connection_problems(p).items() if k in ("host", "user", "port")}
        if problems: QMessageBox.warning(self, "Check the connection", "\n".join(f"{remote.FIELD_LABELS[k]}: {v}" for k, v in problems.items())); return
        if not remote.shares_connection():
            res = remote.open_key_setup(p)
            if res.ok: self.log.appendPlainText(f"A console window opened to set up key login to {p.host}: answer there (the cluster password once). Then press Test connection."); self.status.setText("Finish the key setup in the console window, then press Test connection.")
            else: self.log.appendPlainText("Could not open the console window: " + res.stderr); self.status.setText("Key setup could not start. Use Commands to do it yourself… instead.")
            return
        self.refresh_connection()
        if self.alive: self.status.setText(f"Already connected to {p.host}."); return
        self.log.appendPlainText(f"$ {remote.ssh_display(p)}  (opens the shared connection; the cluster's questions are asked in a window, and nothing is stored)")
        bridge = self.bridge
        self.background(lambda: remote.open_connection(p, bridge.ask), lambda res: self.connected(p, res), f"Connecting to {p.host}…")

    def connected(self, p: "remote.Profile", res: "remote.Result") -> None:
        self.refresh_connection()
        if res.ok:
            self.log.appendPlainText(f"Connected to {p.host}. The connection stays open for 4 hours and every button of this page uses it.")
            self.status.setText(f"✓ Connected to {p.host}. Checking the cluster…"); set_kind(self.status, "ok"); self.test_connection()
        elif res.returncode == 130: self.log.appendPlainText("Connection cancelled."); self.status.setText("Not connected: you cancelled.")
        else:
            why = (res.stderr.strip().splitlines() or [f"exit code {res.returncode}"])[-1]
            self.log.appendPlainText(f"Could not connect: {why}"); self.status.setText("Could not connect. Check the password, the host and the port, then press Connect… again.")

    def disconnect_cluster(self) -> None:
        p = self.current(); closed = remote.close_connection(p); self.refresh_connection()
        self.log.appendPlainText(f"Connection to {p.host} closed." if closed else f"The connection to {p.host} could not be closed.")
        self.status.setText("Disconnected. A run already started on the cluster keeps going." if closed else "Could not close the connection.")

    def reconnect_hint(self, res: "remote.Result") -> str:
        """What to add to a message when a command failed only for want of a login."""
        if not remote.auth_failed(res): return ""
        return " Press Connect… to log in again." if remote.shares_connection() else " The cluster refused this computer's key: press Set up key login…"

    def showEvent(self, event) -> None:
        super().showEvent(event); self.refresh_connection()

    ##### connection test #####
    def set_busy(self, busy: bool, message: str="") -> None:
        self.busy = busy
        for b in (self.test_btn, self.pre_up, self.up, self.down, self.watch_btn): b.setEnabled(not busy)
        self.run_btn.setEnabled(not busy and not self.watching); self.update_connection_buttons()
        if message: self.status.setText(message)

    def background(self, fn: Callable, on_done: Callable, message: str) -> None:
        self.set_busy(True, message); task = Task(fn); self.tasks.append(task)
        task.signals.done.connect(lambda r: (self.set_busy(False), on_done(r))); task.signals.failed.connect(lambda m: (self.set_busy(False, f"Failed: {m}"), self.log.appendPlainText(f"Failed: {m}")))
        QThreadPool.globalInstance().start(task)

    def test_connection(self) -> None:
        p = self.valid_profile()
        if not p: return
        import scope
        self.table.setRowCount(0); self.log.appendPlainText(f"$ {remote.ssh_display(p)}  (connection test, read-only)")
        self.lights = remote.unchecked_lights("Checking…"); self.checked_at = ""; self.render_lights()
        def work():
            result = remote.run_script(p, remote.probe_script(p), timeout=90)
            from scope.gui import updates
            probe = remote.parse_probe(result.stdout)
            return remote.evaluate_probe(p, result, getattr(scope, "__version__", ""), updates.local_commit()), remote.lights_from_probe(probe), probe
        self.background(work, self.show_checks, f"Testing {p.host}…")

    def render_lights(self) -> None:
        """Draws the three lights (SCOPE, Quantum ESPRESSO, Gaussian 16): green available, amber doubtful, red missing, grey not checked or not set."""
        c = theme.colors(); colour = {"green": c["ok"], "amber": c["warn"], "red": c["err"], "grey": c["sub"]}
        for label, light in zip(self.light_labels, self.lights):
            label.setText(f'<span style="color:{colour[light.state]}; font-size:15px">●</span>&nbsp;<b>{light.name}</b><br><span style="color:{c["sub"]}">{light.short}</span>')
            label.setToolTip(light.detail); label.parentWidget().setToolTip(light.detail)
        self.when.setText(f"checked {self.checked_at}" if self.checked_at else "")

    def show_checks(self, outcome) -> None:
        checks, self.lights = outcome[:2]; self.probe = outcome[2] if len(outcome) > 2 else {}; self.checked_at = time.strftime("%H:%M:%S"); self.render_lights(); self.update_review()
        self.checks = checks; self.render_checks(); self.details_btn.setVisible(bool(checks))
        self.details_btn.setChecked(any(c.status != "ok" for c in checks))       ## open when something needs a look
        failed = [c for c in checks if c.status == "fail"]; warned = [c for c in checks if c.status == "warn"]
        self.session.mark("cluster", not failed and bool(checks))
        if not failed and checks: self.announce_runs()
        self.status.setText("Connection test passed." + (f" {len(warned)} warning(s)." if warned else "") if not failed else f"Connection test failed: {len(failed)} problem(s). Fix them and test again.")
        self.refresh_connection()

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
        self.update_review()

    def update_review(self) -> None:
        """The review table with the cluster's scheduler and queues from the last Test connection (not checked before one)."""
        env = (self.probe or {}).get("env") or {}
        reports = self.session.reports
        extra = {r.path: remote.unavailable_software(self.lights, [r]) for r in reports if r.ok}
        self.review.show_rows(backend.review_rows(reports, env.get("scheduler", ""), env.get("queues") if env else None, None, extra))
        note = self.review.summary() + ("" if env else "  Queues and submission are checked after Test connection.")
        self.review_note.setText(note); set_kind(self.review_note, {"ok": "ok", "warn": "warn", "err": "err"}[self.review.level] if self.review.rows else "")

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

    def source_checks(self, info, system: str, reports: list) -> list:
        """Charge and spin of the sources that need a look: on a cluster they go into the Gaussian and QE inputs SCOPE writes."""
        from scope.gui import systems
        return systems.run_checks(os.path.join(info.systems_path, system, f"{system}.npy"), sorted({r.software for r in reports if r.ok}))

    def upload(self, preview: bool) -> None:
        got = self.need()
        if not got: return
        p, info, system = got; inputs = [r.path for r in self.session.reports if r.ok]
        if not self.unique_inputs(inputs): return
        items = remote.upload_items(p, info, system, inputs)
        from scope.gui import transfer
        def work():
            made = remote.run_script(p, remote.remote_dirs_script(p, system))
            if not made.ok: return made, [], None
            listing = transfer.parse_listing(remote.run_script(p, transfer.listing_script(p, system), timeout=120).stdout)
            return made, remote.sync(items, dry_run=True, p=p), (transfer.upload_check(listing, info, system) if listing else None)
        def done(result):
            made, dry, check = result
            if not made.ok: self.log.appendPlainText("Cannot prepare the folders on the cluster: " + (made.stderr.strip() or f"exit code {made.returncode}")); self.status.setText("Upload not possible." + self.reconnect_hint(made)); return
            n = self.show_sync(dry, "Would copy"); warnings = check.messages if check else ["The cluster folder could not be listed, so the synchronisation could not be checked."]
            warnings = warnings + self.source_checks(info, system, self.session.reports)
            for w in warnings: self.log.appendPlainText("Synchronisation: " + w)
            if check and check.only_here: self.log.appendPlainText("    " + "\n    ".join(check.only_here[:40]) + (f"\n    … and {len(check.only_here) - 40} more" if len(check.only_here) > 40 else ""))
            self.status.setText(f"Preview: {n} change(s)" + (f", {len(check.only_here)} calculation file(s) only here" if check and check.only_here else "") + ". Nothing was copied.")
            if preview or (n == 0 and not (check and check.only_here)): return
            text = f"Copy {n} change(s) to {p.host}:{p.remote_root}?\n\nSystem '{system}' and {len(inputs)} input file(s). Existing files with the same name are replaced; nothing is deleted."
            if warnings: text += "\n\nCheck first:\n• " + "\n• ".join(warnings)
            if QMessageBox.question(self, "Upload", text) != QMessageBox.Yes: return
            files = check.only_here if check and check.only_here and QMessageBox.question(self, "Upload the calculation files too?",
                        f"Also copy the {len(check.only_here)} input and output file(s) that are only here (or newer here) into Computations/{system} on the cluster?\n\n"
                        "Recommended: the cluster's SCOPE reads, continues and checks calculations from these files; the system file alone is not enough.") == QMessageBox.Yes else []
            def copy():
                out = remote.sync(items, dry_run=False, p=p)
                if files: out.append(("calculation files", transfer.push_files(p, info, system, files), list(files)))
                return out
            self.background(copy, lambda r: (self.show_sync(r, "Copied"), self.status.setText("Upload finished.")), "Uploading…")
        self.background(work, done, "Checking what would be copied…")

    def open_download(self, system: str=None, wanted: list=None) -> "object | None":
        """Opens the download dialog for the selected system: list, choose, copy into this workspace's folders (or copy the command line).
        `system` selects that system first; `wanted` (paths inside Computations/<system>/) are ticked instead of the usual proposal (Results page)."""
        if system: self.system.setCurrentText(system)
        got = self.need()
        if not got: return None
        from scope.gui.download_dialog import DownloadDialog
        p, info, system = got
        self.download_dialog = DownloadDialog(self, p, info, system, wanted=wanted); self.download_dialog.downloaded.connect(self.session.systemsChanged.emit)
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
        self.update_review()
        if self.review.level != "ok": note += "\n\nReview table: " + self.review.summary() + " Hover over its Check column for the details."
        checks = self.source_checks(info, system, valid)
        if checks: note += "\n\nCharge and spin (of this computer's system file, as uploaded):\n• " + "\n• ".join(checks[:6]) + ("\n• …" if len(checks) > 6 else "")
        if QMessageBox.question(self, "Run on the cluster", f"Start `scope run` for '{system}' on {p.host}, with the files uploaded in {p.remote_root}/inputs.\n\nThe run is detached: it keeps going on the cluster if you close this window or lose the connection.{note}") != QMessageBox.Yes: return
        script = remote.detached_run_script(p, system, [f"{p.remote_root.rstrip('/')}/inputs/{os.path.basename(r.path)}" for r in valid], check_files=True)
        self.log.appendPlainText(f"\n$ {remote.ssh_display(p)}  (start `scope set_path` and `scope run` for {system}, detached)\n")
        self.background(lambda: remote.run_script(p, script, timeout=60), lambda res: self.started(p, system, res), f"Starting the run on {p.host}…")

    def started(self, p: "remote.Profile", system: str, res: "remote.Result") -> None:
        info = remote.parse_started(res.stdout)
        if not info: self.log.appendPlainText("Could not start the run: " + (res.stderr.strip() or res.stdout.strip() or f"exit code {res.returncode}")); self.status.setText("The run did not start." + self.reconnect_hint(res)); return
        if info["state"] == "missing":                                      ## checked on the cluster before starting: nothing was started
            elsewhere = [path for kind, path in info["files"] if kind == "envdir"]
            if elsewhere:                                                   ## the environment of another project folder: uploading again would not help
                root = p.remote_root.rstrip("/")
                self.log.appendPlainText(f"Not started: the cluster environment file {p.remote_env} keeps its systems in {elsewhere[0]}, but this workspace's project folder is {root}, "
                                         f"where Upload puts them ({root}/Systems). `scope set_path` would not find the system.\n"
                                         f"Fix it in card 2: choose the environment file of {root} (if it has none, create one there on the cluster with `scope config -n <name>`), "
                                         f"or set the project folder to the folder of that environment.")
                self.status.setText(f"Not started: the environment file belongs to another project folder ({os.path.dirname(elsewhere[0].rstrip('/'))}). See the log; fix card 2, then Run."); set_kind(self.status, "warn"); return
            system_gone = any(kind == "system" for kind, _ in info["files"]); inputs_gone = [path for kind, path in info["files"] if kind == "input"]
            what = " and ".join(([f"the system file of '{system}'"] if system_gone else []) + ([f"{len(inputs_gone)} input file(s)"] if inputs_gone else []))
            self.log.appendPlainText(f"Not started: {what} not on the cluster yet:\n" + "\n".join(f"  {path}" for _, path in info["files"]) + "\nPress Upload (it copies the system file and the input files), then Run.")
            self.status.setText(f"Not started: {what} not on the cluster yet. Press Upload, then Run."); set_kind(self.status, "warn"); return
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
        if not res.ok:
            if remote.auth_failed(res): self.refresh_connection(); self.status.setText("The login to the cluster has expired. The run goes on there. Press Connect… to log in again; following resumes by itself.")
            else: self.status.setText("Cannot reach the cluster right now. The run goes on there; trying again…")
            return
        d = remote.parse_poll(res.raw or res.stdout)
        if d["text"].strip("\n"): self.log.appendPlainText(d["text"].rstrip("\n")); w["offset"] += d["bytes"]
        if d["exit"] is not None or not d["alive"]:
            self.poll_timer.stop(); self.watching = None; self.unwatch_btn.setEnabled(False); self.stopcl_btn.setEnabled(False); self.run_btn.setEnabled(not self.busy)
            if d["exit"] == 143: self.status.setText("The cluster run was stopped. Run again: SCOPE continues where it stopped.")
            elif d["exit"] is not None:
                self.status.setText(f"Cluster run finished with exit code {d['exit']}.")
                if d["exit"] == 0: self.session.mark("ran"); self.after_run_ended(w["profile"], w["system"])
            else: self.status.setText("The cluster run ended without finishing (stopped or killed). Run again: SCOPE continues where it stopped.")

    def after_run_ended(self, p: "remote.Profile", system: str) -> None:
        """A cluster run ended with exit code 0. `scope run` submits its jobs and ends, so look once (read-only) at the scheduler queue
        before saying the results can be downloaded."""
        def done(found: dict) -> None:
            jobs = remote.queued_jobs(found, p.remote_root, system)
            if jobs:
                note = f"SCOPE has ended, but {len(jobs)} job(s) of '{system}' are still in the scheduler queue ({remote.jobs_summary(jobs)})."
                self.log.appendPlainText(note + " Wait for them, then run again: SCOPE collects their results and goes on. Runs → Refresh shows the queue.")
                self.status.setText(note + " Wait for them, then run again.")
            elif found.get("scheduler") in ("error", "other"): self.status.setText("Cluster run finished with exit code 0, but the scheduler queue could not be read: its jobs may still be waiting.")
            elif remote.unread_count(found, system):
                note = remote.unread_text(remote.unread_count(found, system), system)
                self.log.appendPlainText(note); self.status.setText("Cluster run finished with exit code 0, but some results are not read yet. " + note)
            else: self.status.setText("Cluster run finished with exit code 0. Press Download results… to bring the results back.")
        self.background(lambda: remote.parse_runs(remote.run_script(p, remote.list_runs_script(p), timeout=30).stdout), done, "Cluster run finished with exit code 0. Looking at the scheduler queue…")

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
            else:
                jobs = remote.queued_jobs(found, p.remote_root, remote.pid_name(current)) if current else []
                waiting = f"{len(jobs)} job(s) of '{current}' are still in the scheduler queue ({remote.jobs_summary(jobs)}): wait for them, then run again." if jobs else ""
                unread = remote.unread_count(found, current) if current and not jobs and found.get("scheduler") not in ("error", "other") else 0
                if unread: waiting = remote.unread_text(unread, current)
                if found["logs"]: self.log.appendPlainText(f"No SCOPE run is active on the cluster. The latest log is {found['logs'][0]}" + (f"\n{waiting}" if waiting else ""))
                self.status.setText(f"No active SCOPE run. {waiting}" if waiting else "No active run." if found["logs"] else "No run found on the cluster for this project.")
        self.background(lambda: remote.parse_runs(remote.run_script(p, remote.list_runs_script(p), timeout=30).stdout), done, f"Looking for runs on {p.host}…")

    def running(self) -> bool:
        return bool(self.watching)
