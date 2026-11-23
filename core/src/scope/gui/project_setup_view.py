"""Set up this folder… (Cluster page): makes the workspace's project folder on the cluster ready for SCOPE, from the window.

It runs scope_project.py on the cluster (see remote.project_setup_script), always first as a preview that changes nothing; Apply
does what the preview showed. Either a new environment file is made for the folder (queues and modules copied from an environment
that already works there), or the current file is changed in place (a backup is kept). Nothing is moved or deleted.
"""
import os
from PySide6.QtCore    import QThreadPool, Qt
from PySide6.QtGui     import QFontDatabase
from PySide6.QtWidgets import QCheckBox, QComboBox, QDialog, QFormLayout, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QRadioButton, QSizePolicy, QVBoxLayout
from scope.gui import remote, workspaces
from scope.gui.tasks import Task
from scope.gui.theme import set_kind

def known_environments(host: str, profiles: dict, skip: tuple=()) -> list:
    """(workspace, project folder, environment file) of the workspaces that use a project on this host, except `skip` (root, env)."""
    out = []
    for name in workspaces.list_names():
        ws = workspaces.load(name); prof = profiles.get(ws.profile) if ws else None
        if prof is None or prof.host != host: continue
        root, env = workspaces.remote_fields(ws, prof)
        if env and (root, env) != tuple(skip): out.append((ws.name, root, env))
    return out

class ProjectSetupDialog(QDialog):
    """Preview, then Apply. `probe` is what the last connection test found (whether the environment file exists)."""
    def __init__(self, tab, p: "remote.Profile", probe: dict):
        super().__init__(tab); self.tab, self.p, self.probe, self.tasks, self.previewed, self.result = tab, p, probe or {}, [], None, {}
        self.setWindowTitle("Set up the project folder"); self.resize(840, 820); self.setMinimumSize(720, 700)
        root, env = p.remote_root, p.remote_env
        self.env_exists = bool(self.probe.get("env_exists")) and "env_error" not in self.probe
        mono = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        def card(title: str) -> tuple:
            frame = QFrame(); frame.setObjectName("card"); inner = QVBoxLayout(frame); inner.setContentsMargins(16, 10, 16, 14); inner.setSpacing(6)
            head = QLabel(title); head.setObjectName("cardtitle"); inner.addWidget(head); return frame, inner
        def note(text: str="", indent: int=0) -> QLabel:
            label = QLabel(text); label.setObjectName("pagesub"); label.setWordWrap(True); label.setTextInteractionFlags(Qt.TextSelectableByMouse); label.setContentsMargins(indent, 0, 0, 0); return label
        def path(text: str) -> QLabel:
            label = QLabel(text or "(not set)"); label.setFont(mono); label.setWordWrap(True); label.setTextInteractionFlags(Qt.TextSelectableByMouse); return label
        title = QLabel("Set up the project folder"); title.setObjectName("pagetitle")
        sub = note("SCOPE must use the folder's Sources, Systems and Computations, through an environment file made for it. The cluster first shows what it would do; nothing changes before Apply.")
        ## where
        where, wl = card("Where")
        grid = QGridLayout(); grid.setHorizontalSpacing(14); grid.setVerticalSpacing(4); grid.setColumnStretch(1, 1)
        state = "found" if self.env_exists else ("not a SCOPE environment" if "env_error" in self.probe else "not found")
        for i, (label, value) in enumerate((("Cluster", p.host), ("Project folder", root), ("Environment file", f"{env}   ({state})"))):
            key = note(label); grid.addWidget(key, i, 0, Qt.AlignTop); grid.addWidget(path(value), i, 1)
        wl.addLayout(grid)
        ## what to do
        what, dl = card("What to do")
        self.new_radio = QRadioButton("Make a new environment file for this folder  (recommended)")
        self.fix_radio = QRadioButton("Change the current environment file so that it uses this folder")
        others = known_environments(p.host, tab.profiles, (root, env))
        self.sharing = [w for w, r, e in others if e == env]
        self.template = QComboBox(); self.template.setEditable(True); self.template.setMinimumContentsLength(30); self.template.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        choices = ([env] if self.env_exists else []) + [e for w, r, e in others if e != env]
        self.template.addItems(list(dict.fromkeys(choices)))
        self.template.setToolTip("An environment file that already works on this cluster (made once with scope config). Its scheduler, queues and software modules are copied; its folders are not.")
        self.template.lineEdit().setPlaceholderText("~/scope_env_RUNS.npy  (an environment that works on this cluster)")
        self.name = QLineEdit(os.path.basename(root.rstrip("/")) or "project"); self.name.setToolTip("The new file is <project folder>/scope_env_<name>.npy")
        form = QFormLayout(); form.setContentsMargins(26, 2, 0, 4); form.setHorizontalSpacing(12); form.addRow("Copy queues and modules from", self.template); form.addRow("Name of the new environment", self.name)
        self.form_note = note(indent=26)
        self.fix_note  = note("The file is changed in place and a dated backup is kept next to it." + (f"  ⚠ Workspace(s) {', '.join(self.sharing)} use the same file: their project will point here too." if self.sharing else ""), indent=26)
        if self.sharing: set_kind(self.fix_note, "warn")
        self.force = QCheckBox()
        dl.addWidget(self.new_radio); dl.addLayout(form); dl.addWidget(self.form_note); dl.addSpacing(6); dl.addWidget(self.fix_radio); dl.addWidget(self.fix_note); dl.addSpacing(6); dl.addWidget(self.force)
        ## preview
        prev, pl = card("Preview")
        self.output = QPlainTextEdit(); self.output.setReadOnly(True); self.output.setLineWrapMode(QPlainTextEdit.WidgetWidth); self.output.setFont(mono); self.output.setMinimumHeight(140)
        self.output.setPlaceholderText("Press Preview: the cluster says what it would create or change. Nothing changes before Apply.")
        self.status = QLabel(); self.status.setWordWrap(True)
        pl.addWidget(self.output, 1); pl.addWidget(self.status)
        self.preview_btn, self.apply_btn, close = QPushButton("Preview"), QPushButton("Apply"), QPushButton("Close")
        self.apply_btn.setProperty("primary", True); self.apply_btn.setEnabled(False); self.apply_btn.setToolTip("Does what the preview showed. Enabled after a successful preview with the same choices.")
        row = QHBoxLayout(); row.addWidget(self.preview_btn); row.addStretch(1); row.addWidget(close); row.addWidget(self.apply_btn)
        lay = QVBoxLayout(self); lay.setContentsMargins(22, 18, 22, 16); lay.setSpacing(12)
        for frame in (where, what): frame.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)          ## the fields keep their height; the preview takes the rest
        lay.addWidget(title); lay.addWidget(sub); lay.addWidget(where); lay.addWidget(what); lay.addWidget(prev, 1); lay.addLayout(row)
        self.fix_radio.setEnabled(self.env_exists); self.fix_note.setEnabled(self.env_exists)
        if not self.env_exists: self.fix_radio.setToolTip("The environment file does not exist on the cluster (or is not a SCOPE environment), so there is nothing to change.")
        self.new_radio.setChecked(True)
        for w in (self.new_radio, self.fix_radio, self.force): w.toggled.connect(self.update_form)
        self.template.editTextChanged.connect(self.update_form); self.name.textChanged.connect(self.update_form)
        self.preview_btn.clicked.connect(lambda: self.run(dry_run=True)); self.apply_btn.clicked.connect(lambda: self.run(dry_run=False)); close.clicked.connect(self.reject)
        self.update_form()

    ##### the choices #####
    def mode(self) -> str:
        return "fix" if self.fix_radio.isChecked() else "from"

    def choices(self) -> tuple:
        """What a preview was made for: Apply is offered only while it is unchanged."""
        return (self.mode(), self.template.currentText().strip(), self.name.text().strip(), self.force.isChecked())

    def update_form(self) -> None:
        new = self.mode() == "from"; template = self.template.currentText().strip()
        self.template.setEnabled(new); self.name.setEnabled(new)
        self.force.setText("Replace the new file if it already exists  (a backup is kept)" if new else "Change the paths even if the old folders still hold systems  (nothing is moved or deleted)")
        if not template:
            self.form_note.setText("No environment that works on this cluster is known to this window yet. Make one once on the cluster with scope config "
                                   f"(ssh {self.p.host}, then: scope config -n cluster) and write its path above. Every new project folder after that is one click.")
        else: self.form_note.setText(f"Creates Sources, Systems and Computations in the project folder and the file scope_env_{self.name.text().strip() or '<name>'}.npy there, and makes it this workspace's environment file. The file you copy from is not changed.")
        set_kind(self.form_note, "warn" if new and not template else "")
        self.preview_btn.setEnabled(not new or bool(template))
        self.apply_btn.setEnabled(bool(self.previewed) and self.previewed == self.choices() and self.result.get("code") == 0)

    ##### preview and apply #####
    def run(self, dry_run: bool) -> None:
        mode, template, name, force = self.choices(); p = self.p
        env_file = template if mode == "from" else p.remote_env
        script = remote.project_setup_script(p, p.remote_root, mode, env_file, name=name, force=force, dry_run=dry_run)
        self.preview_btn.setEnabled(False); self.apply_btn.setEnabled(False)
        self.status.setText("Asking the cluster what would be done…" if dry_run else "Setting up the folder on the cluster…"); set_kind(self.status, "")
        task = Task(lambda: remote.run_script(p, script, timeout=180)); self.tasks.append(task)
        task.signals.done.connect(lambda res: self.finished(res, dry_run, (mode, template, name, force)))
        task.signals.failed.connect(lambda m: (self.status.setText(f"Failed: {m}"), set_kind(self.status, "err"), self.update_form()))
        QThreadPool.globalInstance().start(task)

    def finished(self, res: "remote.Result", dry_run: bool, choices: tuple) -> None:
        out = remote.parse_project_setup(res.stdout); self.result = out
        text = "\n".join(l for l in res.stdout.splitlines() if not l.startswith("__SCOPE_PROJECT__"))
        self.output.setPlainText((text + ("\n" + res.stderr.strip() if res.stderr.strip() else "")).strip())
        if not out:
            why = (res.stderr.strip().splitlines() or [f"exit code {res.returncode}"])[-1]
            self.previewed = None; self.status.setText(f"The cluster did not answer as expected: {why}"); set_kind(self.status, "err"); self.update_form(); return
        if out.get("code") != 0:
            hint = " Tick the box above to replace it." if out.get("exists") else (" Move what you need into the new folders first, or tick the box above." if out.get("leftovers") else "")
            self.previewed = None; self.status.setText(f"{'Preview' if dry_run else 'Set-up'} stopped: {out.get('error', 'unknown reason')}{hint}"); set_kind(self.status, "warn"); self.update_form(); return
        if dry_run:
            self.previewed = choices
            nothing = self.mode() == "fix" and out.get("layout_ok")
            self.status.setText("Nothing to change: the layout is already right. Test connection again." if nothing else "This is what Apply will do. Nothing has been changed yet."); set_kind(self.status, "ok")
            self.update_form(); return
        target = out.get("target") or self.p.remote_env
        self.tab.log.appendPlainText(f"$ set up {self.p.remote_root} on {self.p.host}\n{text}")
        self.tab.env_file.setText(target)                                       ## saved with the workspace (projectChanged)
        self.status.setText(f"Done: {target}" + (f" (backup: {out['backup']})" if out.get("backup") else "")); set_kind(self.status, "ok")
        self.accept(); self.tab.status.setText(f"Project folder set up: environment file {target}. Testing the connection again…"); self.tab.test_connection()
