"""Runs page: every run of every workspace in one table, on this computer and on the clusters.

Runs on this computer come from the run records (refreshed every few seconds while the page is shown). Runs on a cluster are asked for
only when the user presses Check the clusters: the window never contacts a host by itself. A row can be shown (the window switches to
its workspace and follows it), and a run can be stopped from here.

On a cluster, `scope run` submits its jobs to the scheduler and ends: the run is then over but its jobs may wait in the queue for hours.
So Check the clusters also reads the scheduler queue, the State column says 'waiting for jobs' while jobs of a system are queued, and the
Jobs column says how many are running or pending.
"""
import os
import time
from dataclasses import dataclass
from PySide6.QtCore    import QThreadPool, QTimer, Qt
from PySide6.QtGui     import QBrush, QColor
from PySide6.QtWidgets import QAbstractItemView, QHBoxLayout, QHeaderView, QLabel, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget
from scope.gui import backend, remote, theme, workspaces
from scope.gui.tasks import Task

WAITING  = "waiting for jobs"
NOT_READ = "done, results not read yet"                                    ## the jobs ended after SCOPE last saved: their results are not in the system file yet
NO_QUEUE = "—"                                                              ## Jobs column of a run with no scheduler queue to look at
COLUMNS  = ["Workspace", "System", "Where", "State", "Jobs", "Started", "Log"]

@dataclass
class RunRow:
    """One line of the Runs page. where is 'this computer' or the SSH host.

    state is about the SCOPE run (`scope run`): 'running', 'finished (exit N)', 'stopped', 'ended without finishing', or, on a cluster,
    'waiting for jobs' when the run has ended but jobs it submitted are still in the scheduler queue, and 'done, results not read yet'
    when no job is left but files were written after SCOPE last saved the system (unread, see remote.unread_count). jobs describes that queue
    ('1 running, 2 pending', 'none in queue', …); NO_QUEUE for a run on this computer."""
    workspace: str
    system:    str
    where:     str
    state:     str
    started:   str  = ""
    log:       str  = ""
    record:    dict = None                                                  ## the local run record, for a run on this computer
    profile:   "remote.Profile" = None                                      ## the cluster connection and project, for a run on a cluster
    names:     list = None                                                  ## the workspaces it belongs to (a cluster project can be shared)
    jobs:      str  = NO_QUEUE
    queued:    list = None                                                  ## the remote.QueuedJob of this system in the scheduler queue
    unread:    int  = 0                                                     ## files on the cluster that SCOPE has not read yet

def ended_text(code: "int | None") -> str:
    """State text of a run that is no longer running, from the exit code its wrapper wrote (None: it wrote none)."""
    if code is None: return "ended without finishing"
    return "stopped" if code in (-15, 143) else f"finished (exit {code})"

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
        text = "running" if state == "running" else ended_text(code) if state == "finished" else ended_text(None)
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

def log_started(log: str) -> str:
    """'YYYY-mm-dd HH:MM' from the time stamp in the name of a cluster run log, or ''."""
    m = remote.LOG_NAME.match(os.path.basename(log or ""))
    if not m: return ""
    d, t = m.group(2), m.group(3)
    return f"{d[:4]}-{d[4:6]}-{d[6:]} {t[:2]}:{t[2:4]}"

def queue_text(scheduler: "str | None", jobs: list) -> str:
    """Jobs column of a cluster row."""
    if scheduler == "error": return "queue not readable"
    if scheduler == "other": return "scheduler not recognised"
    if scheduler in (None, "none"): return "no scheduler"
    return remote.jobs_summary(jobs) or "none in queue"

def cluster_rows_of(p: "remote.Profile", names: list, found: dict) -> list:
    """The rows of one cluster project from what list_runs_script found: one per system with an active run, a last run, or jobs in the
    queue. Active runs come first, then systems with queued jobs, then the others."""
    root = p.remote_root.rstrip("/")
    active = {system: log for system, _, log in found["active"]}
    last = found.get("last", {}); scheduler = found.get("scheduler")
    queued = remote.jobs_by_system(found.get("jobs", []), root, set(active) | set(last), found.get("root_real", ""))
    rows = []
    for system in sorted(set(active) | set(last) | set(queued), key=lambda s: (s not in active, s not in queued, s)):
        jobs = queued.get(system, []); unread = remote.unread_count(found, system)
        if system in active: state, log = "running", active[system]
        elif jobs:           state, log = WAITING, last.get(system, ("", None))[0]
        else:
            log, code = last[system]; state = ended_text(code)
            if code == 0 and unread and scheduler not in ("error", "other"): state = NOT_READ     ## an unreadable queue could still hold jobs that write
        rows.append(RunRow(", ".join(names), system, p.host, state, log_started(log), log, profile=p, names=list(names), jobs=queue_text(scheduler, jobs), queued=jobs, unread=unread))
    return rows

def check_clusters(projects: dict) -> tuple:
    """Asks each cluster project which runs are active, how the others ended, and which of its jobs are in the scheduler queue (read-only).
    Returns (rows, messages)."""
    rows, messages = [], []
    for (_, root), (p, names) in projects.items():
        host = p.host
        res = remote.run_script(p, remote.list_runs_script(p), timeout=30)
        if not res.ok: messages.append(f"{host}:{root}: not reachable ({(res.stderr.strip().splitlines() or [f'exit code {res.returncode}'])[-1]})"); continue
        found = remote.parse_runs(res.stdout); mine = cluster_rows_of(p, names, found)
        rows += mine; queued = sum(len(r.queued or []) for r in mine); unread = sum(1 for r in mine if r.state == NOT_READ)
        queue = {"error": ", queue not readable", "other": ", scheduler not recognised (only Slurm and SGE queues are read)", "none": "", None: ""}.get(found.get("scheduler"), f", {queued} job(s) in the queue")
        messages.append(f"{host}:{root}: {len(found['active'])} active run(s){queue}" + (f", {unread} system(s) with results not read yet" if unread else ""))
    return rows, messages

class RunsPage(QWidget):
    def __init__(self, window):
        super().__init__()
        self.window_, self.rows, self.cluster_rows, self.tasks, self.checked = window, [], [], [], ""
        self.table = QTableWidget(0, len(COLUMNS)); self.table.setHorizontalHeaderLabels(COLUMNS); self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeaderItem(3).setToolTip("The SCOPE run itself. On a cluster it submits jobs and ends: 'waiting for jobs' means it has ended but jobs it submitted are still in the queue; "
                                                     "'done, results not read yet' means the jobs have ended but SCOPE has not read their outputs: run again on the cluster to read them.")
        self.table.horizontalHeaderItem(4).setToolTip("Jobs of this system in the scheduler queue of the cluster, as found by the last Check the clusters. Runs on this computer use no queue.")
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows); self.table.setSelectionMode(QAbstractItemView.SingleSelection); self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        hh = self.table.horizontalHeader(); last = len(COLUMNS) - 1
        [hh.setSectionResizeMode(i, QHeaderView.ResizeToContents) for i in range(last)]; hh.setSectionResizeMode(last, QHeaderView.Stretch)
        self.refresh_btn, self.check_btn, self.show_btn, self.stop_btn = QPushButton("Refresh"), QPushButton("Check the clusters"), QPushButton("Show"), QPushButton("Stop the run")
        self.check_btn.setToolTip("Asks every cluster project of your workspaces which runs are active and which of their jobs are in the scheduler queue (read-only, over SSH)."); self.show_btn.setProperty("primary", True)
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
        c = theme.colors(); colour = {"running": c["ok"], WAITING: c["ok"], NOT_READ: c["warn"], "stopped": c["warn"], "ended without finishing": c["warn"]}
        current = self.table.currentRow(); self.table.setRowCount(len(self.rows))
        for i, r in enumerate(self.rows):
            for j, text in enumerate((r.workspace, r.system, r.where, r.state, r.jobs, r.started, r.log)):
                item = QTableWidgetItem(text)
                if j == 3:
                    item.setForeground(QBrush(QColor(colour.get(r.state, c["sub"] if r.state.startswith("finished") else c["text"]))))
                    if r.state == NOT_READ: item.setToolTip(remote.unread_text(r.unread, r.system))
                if j == 4:
                    item.setForeground(QBrush(QColor(c["ok"] if r.queued else c["sub"])))
                    if r.queued: item.setToolTip("\n".join(f"{q.id}  {q.state}  {q.name}" for q in r.queued))
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
        if not r: return
        if r.record is None and not r.log:
            QMessageBox.information(self, "No log", f"The jobs of '{r.system}' on {r.where} were not submitted by a run started from this window, so there is no log to follow.\n\nJobs: {r.jobs}"); return
        self.window_.show_run(r)

    def stop_selected(self) -> None:
        r = self.selected()
        if r and r.state == WAITING:
            QMessageBox.information(self, "Nothing to stop", f"The SCOPE run of '{r.system}' has already ended. It left {len(r.queued or [])} job(s) in the queue of {r.where} ({r.jobs}).\n\n"
                                    "Those jobs belong to the scheduler: cancel them on the cluster (scancel or qdel) if you do not want them."); return
        if not r or r.state != "running": QMessageBox.information(self, "Nothing to stop", "Select a run that is running."); return
        where = "on this computer" if r.record else f"on {r.where}"
        queued = f"\n\n{len(r.queued)} job(s) of this system are in the queue now ({r.jobs})." if r.queued else ""
        if QMessageBox.question(self, "Stop the run", f"Stop the run of '{r.system}' {where}?\n\nJobs already submitted to a scheduler are not cancelled. SCOPE continues where it stopped the next time you run.{queued}") != QMessageBox.Yes: return
        if r.record: backend.stop_run(r.record); self.refresh(); return
        p, system = r.profile, r.system
        task = Task(lambda: remote.run_script(p, remote.stop_script(p, system), timeout=30)); self.tasks.append(task)
        task.signals.done.connect(lambda res: (self.status.setText("Stop requested: " + (res.stdout.strip() or res.stderr.strip())), self.check()))
        QThreadPool.globalInstance().start(task)
