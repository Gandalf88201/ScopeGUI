"""Runs page: every run of every workspace in one table, on this computer and on the clusters.

Runs on this computer come from the run records (refreshed every few seconds while the page is shown). Runs on a cluster are asked for
only when the user presses Check the clusters: the window never contacts a host by itself. A row can be shown (the window switches to
its workspace and follows it), and a run can be stopped from here.
"""
import os
import time
from dataclasses import dataclass
from PySide6.QtCore    import QThreadPool, QTimer, Qt
from PySide6.QtGui     import QBrush, QColor
from PySide6.QtWidgets import QAbstractItemView, QHBoxLayout, QHeaderView, QLabel, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget
from scope.gui import backend, remote, theme, workspaces
from scope.gui.tasks import Task

@dataclass
class RunRow:
    """One line of the Runs page. where is 'this computer' or the SSH host; state is 'running', 'finished', 'stopped' or 'ended without finishing'."""
    workspace: str
    system:    str
    where:     str
    state:     str
    started:   str  = ""
    log:       str  = ""
    record:    dict = None                                                  ## the local run record, for a run on this computer
    profile:   "remote.Profile" = None                                      ## the cluster connection and project, for a run on a cluster
    names:     list = None                                                  ## the workspaces it belongs to (a cluster project can be shared)

def workspace_of(record: dict, spaces: list) -> str:
    """Name of the workspace a local run belongs to (by its environment; runs from before workspaces existed go to the legacy one)."""
    for ws in spaces:
        if backend.record_belongs(record, ws.env_path, ws.legacy): return ws.name
    return "(no workspace)"

def local_rows(spaces: list) -> list:
    rows = []
    for record in reversed(backend.load_runs()):
        if record.get("kind") != "local": continue
        state, code = backend.run_state(record)
        text = "running" if state == "running" else ("stopped" if code == -15 or code == 143 else f"finished (exit {code})") if state == "finished" else "ended without finishing"
        owner = workspace_of(record, spaces)
        rows.append(RunRow(owner, record.get("system", "?"), "this computer", text, time.strftime("%Y-%m-%d %H:%M", time.localtime(record.get("started", 0))), record.get("log", ""), record=record, names=[] if owner == "(no workspace)" else [owner]))
    return rows

def cluster_projects(spaces: list, profiles: dict) -> dict:
    """The distinct cluster projects of the workspaces: (host, project folder) -> (Profile, [workspace names])."""
    out = {}
    for ws in spaces:
        prof = profiles.get(ws.profile)
        if prof is None: continue
        root, env = workspaces.remote_fields(ws, prof)
        if not root: continue
        p = remote.Profile(prof.name, prof.host, prof.scope_bin, prof.activate, root, env, user=prof.user, port=prof.port)
        key = (remote.connection_key(prof), root.rstrip("/"))
        out.setdefault(key, (p, []))[1].append(ws.name)
    return out

def check_clusters(projects: dict) -> tuple:
    """Asks each cluster project which runs are active (read-only). Returns (rows, messages)."""
    rows, messages = [], []
    for (_, root), (p, names) in projects.items():
        host = p.host
        res = remote.run_script(p, remote.list_runs_script(p), timeout=30)
        if not res.ok: messages.append(f"{host}:{root}: not reachable ({(res.stderr.strip().splitlines() or [f'exit code {res.returncode}'])[-1]})"); continue
        found = remote.parse_runs(res.stdout)
        for system, pid, log in found["active"]: rows.append(RunRow(", ".join(names), system, host, "running", "", log, profile=p, names=list(names)))
        messages.append(f"{host}:{root}: {len(found['active'])} active run(s)")
    return rows, messages

class RunsPage(QWidget):
    def __init__(self, window):
        super().__init__()
        self.window_, self.rows, self.cluster_rows, self.tasks, self.checked = window, [], [], [], ""
        self.table = QTableWidget(0, 6); self.table.setHorizontalHeaderLabels(["Workspace", "System", "Where", "State", "Started", "Log"]); self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows); self.table.setSelectionMode(QAbstractItemView.SingleSelection); self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        hh = self.table.horizontalHeader(); [hh.setSectionResizeMode(i, QHeaderView.ResizeToContents) for i in range(5)]; hh.setSectionResizeMode(5, QHeaderView.Stretch)
        self.refresh_btn, self.check_btn, self.show_btn, self.stop_btn = QPushButton("Refresh"), QPushButton("Check the clusters"), QPushButton("Show"), QPushButton("Stop the run")
        self.check_btn.setToolTip("Asks every cluster project of your workspaces which runs are active (read-only, over SSH)."); self.show_btn.setProperty("primary", True)
        self.status = QLabel("Runs on this computer refresh by themselves. Runs on the clusters are checked when you press Check the clusters."); self.status.setWordWrap(True); self.status.setObjectName("pagesub")
        row = QHBoxLayout(); [row.addWidget(b) for b in (self.show_btn, self.stop_btn, self.refresh_btn, self.check_btn)]; row.addStretch(1)
        lay = QVBoxLayout(self); lay.addLayout(row); lay.addWidget(self.table, 1); lay.addWidget(self.status)
        self.refresh_btn.clicked.connect(self.refresh); self.check_btn.clicked.connect(self.check); self.show_btn.clicked.connect(self.show_selected); self.stop_btn.clicked.connect(self.stop_selected)
        self.table.itemDoubleClicked.connect(lambda _: self.show_selected())
        self.timer = QTimer(self); self.timer.timeout.connect(self.refresh)
        theme.on_change(self.render)

    def showEvent(self, event) -> None:
        super().showEvent(event); self.refresh(); self.timer.start(3000)

    def hideEvent(self, event) -> None:
        super().hideEvent(event); self.timer.stop()

    def refresh(self) -> None:
        spaces = [w for w in (workspaces.load(n) for n in workspaces.list_names()) if w]
        self.rows = self.cluster_rows + local_rows(spaces); self.render()

    def render(self) -> None:
        c = theme.colors(); colour = {"running": c["ok"], "stopped": c["warn"], "ended without finishing": c["warn"]}
        current = self.table.currentRow(); self.table.setRowCount(len(self.rows))
        for i, r in enumerate(self.rows):
            for j, text in enumerate((r.workspace, r.system, r.where, r.state, r.started, r.log)):
                item = QTableWidgetItem(text)
                if j == 3: item.setForeground(QBrush(QColor(colour.get(r.state, c["sub"] if r.state.startswith("finished") else c["text"]))))
                self.table.setItem(i, j, item)
        if 0 <= current < len(self.rows): self.table.selectRow(current)
        if not self.rows: self.status.setText("No runs yet. Runs started from any workspace appear here." + (f"  Clusters checked at {self.checked}." if self.checked else ""))

    def check(self) -> None:
        spaces = [w for w in (workspaces.load(n) for n in workspaces.list_names()) if w]
        projects = cluster_projects(spaces, remote.load_profiles())
        if not projects: self.status.setText("No workspace has a cluster project yet (step 5 · Cluster)."); return
        self.check_btn.setEnabled(False); self.status.setText(f"Checking {len(projects)} cluster project(s)…")
        task = Task(lambda: check_clusters(projects)); self.tasks.append(task)
        task.signals.done.connect(self.checked_done); task.signals.failed.connect(lambda m: (self.check_btn.setEnabled(True), self.status.setText(f"Check failed: {m}")))
        QThreadPool.globalInstance().start(task)

    def checked_done(self, result) -> None:
        self.cluster_rows, messages = result; self.checked = time.strftime("%H:%M:%S"); self.check_btn.setEnabled(True)
        self.status.setText(f"Clusters checked at {self.checked}: " + "; ".join(messages)); self.refresh()

    def selected(self) -> "RunRow | None":
        row = self.table.currentRow()
        return self.rows[row] if 0 <= row < len(self.rows) else None

    def show_selected(self) -> None:
        r = self.selected()
        if r: self.window_.show_run(r)

    def stop_selected(self) -> None:
        r = self.selected()
        if not r or r.state != "running": QMessageBox.information(self, "Nothing to stop", "Select a run that is running."); return
        where = "on this computer" if r.record else f"on {r.where}"
        if QMessageBox.question(self, "Stop the run", f"Stop the run of '{r.system}' {where}?\n\nJobs already submitted to a scheduler are not cancelled. SCOPE continues where it stopped the next time you run.") != QMessageBox.Yes: return
        if r.record: backend.stop_run(r.record); self.refresh(); return
        p, system = r.profile, r.system
        task = Task(lambda: remote.run_script(p, remote.stop_script(p, system), timeout=30)); self.tasks.append(task)
        task.signals.done.connect(lambda res: (self.status.setText("Stop requested: " + (res.stdout.strip() or res.stderr.strip())), self.check()))
        QThreadPool.globalInstance().start(task)
