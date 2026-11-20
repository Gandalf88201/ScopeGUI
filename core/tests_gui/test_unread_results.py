"""Results SCOPE has not read yet. On a cluster `scope run` submits the jobs and ends; the jobs write their outputs later, and SCOPE reads
them only when it runs again. Until then the system file (on the cluster, and any copy downloaded from it) holds no result for them, so
the window must say so instead of offering a download that brings no results."""
import os
import time

from scope.gui import remote, results, transfer
from test_remote import isolated, local, cluster                             # noqa: F401  (fixtures; isolated keeps the real GUI settings safe)
from test_runs_queue import fake_tool, projects_of, write_log
from test_workspaces import qapp

def project_files(root: str, system: str, saved: float, written: float) -> None:
    """The system file saved at `saved`, the job's input (written before SCOPE saved) and its outputs (written at `written`)."""
    sysdir = os.path.join(root, "Systems", system); comp = os.path.join(root, "Computations", system, "demo")
    os.makedirs(sysdir, exist_ok=True); os.makedirs(comp, exist_ok=True)
    npy = os.path.join(sysdir, f"{system}.npy"); open(npy, "w").write("system\n"); os.utime(npy, (saved, saved))
    inp = os.path.join(comp, "opt_r1.com"); open(inp, "w").write("input\n"); os.utime(inp, (saved - 60, saved - 60))
    for name in ("opt_r1.log", "opt_r1.stdout"):
        f = os.path.join(comp, name); open(f, "w").write("Normal termination\n"); os.utime(f, (written, written))

# ---- parsers and rows
def test_parse_runs_reads_unread_counts_by_folder_name():
    d = remote.parse_runs("__SCOPE_GUI_UNREAD__ 3 3-Methylbutyl-ethanoate\n__SCOPE_GUI_UNREAD__ 2 my mol\n__SCOPE_GUI_UNREAD__ x bad\n")
    assert d["unread"] == {"3-Methylbutyl-ethanoate": 3, "my mol": 2}
    assert remote.unread_count(d, "my mol") == 2 and remote.unread_count(d, "my_mol") == 2                  # run logs name systems in the pid_name form
    assert remote.unread_count(d, "water") == 0 and remote.parse_runs("")["unread"] == {}
    assert "Run on the cluster again" in remote.unread_text(3, "w") and "on this computer" in remote.unread_text(3, "w")

def test_a_finished_run_whose_outputs_are_not_read_says_so():
    from scope.gui import runs_page
    p = remote.Profile("hpc", "hpc.example", "", "", "/p", "/p/env.npy"); J = remote.QueuedJob
    found = {"active": [], "scheduler": "slurm", "unread": {"water": 2, "queued": 1, "failed": 4},
             "last": {"water": ("/p/logs/run_water_20261120_101500.log", 0), "queued": ("/p/logs/run_queued_20261120_101500.log", 0),
                      "failed": ("/p/logs/run_failed_20261120_101500.log", 1), "clean": ("/p/logs/run_clean_20261120_101500.log", 0)},
             "jobs": [J("5", "RUNNING", "queued_a", "/p/Computations/queued")]}
    rows = {r.system: r for r in runs_page.cluster_rows_of(p, ["Default"], found)}
    assert (rows["water"].state, rows["water"].unread) == (runs_page.NOT_READ, 2)
    assert rows["queued"].state == runs_page.WAITING                                                       # still jobs in the queue: waiting comes first
    assert rows["failed"].state == "finished (exit 1)" and rows["clean"].state == "finished (exit 0)"
    found["scheduler"] = "error"                                                                           # jobs may still be writing: do not guess
    assert {r.system: r.state for r in runs_page.cluster_rows_of(p, ["Default"], found)}["water"] == "finished (exit 0)"

# ---- through the stand-in cluster
def test_check_the_clusters_counts_outputs_newer_than_the_system_file(cluster, tmp_path, monkeypatch):
    from scope.gui import runs_page
    p = cluster; root = p.remote_root.rstrip("/"); now = time.time()
    write_log(root, "water", "20261120_101500", 0); write_log(root, "benzene", "20261120_101500", 0)
    project_files(root, "water", now - 3600, now - 60)                                                     # the job wrote after SCOPE saved
    project_files(root, "benzene", now - 60, now - 3600)                                                   # SCOPE ran again since: read
    project_files(root, "toluene", now - 3600, now - 60)                                                   # unread, but never run from this window: not looked at
    heavy = os.path.join(root, "Computations", "water", "demo", "w.save"); os.makedirs(heavy); open(os.path.join(heavy, "wfc1.dat"), "w").write("x")   # a heavy folder: not walked
    fake_tool(tmp_path, monkeypatch, "squeue", "true\n")                                                   # an empty queue
    rows, messages = runs_page.check_clusters(projects_of(p))
    got = {r.system: (r.state, r.unread) for r in rows}
    assert got == {"water": (runs_page.NOT_READ, 2), "benzene": ("finished (exit 0)", 0)}
    assert "1 system(s) with results not read yet" in messages[0]

def test_the_cluster_page_does_not_offer_unread_results_for_download(cluster, tmp_path, monkeypatch):
    qapp(); from PySide6.QtWidgets import QApplication
    from scope.gui.window import MainWindow
    from test_runs_outlive_window import until
    p = cluster; root = p.remote_root.rstrip("/"); now = time.time()
    project_files(root, "water", now - 3600, now - 60); fake_tool(tmp_path, monkeypatch, "squeue", "true\n"); write_log(root, "water", "20261120_101500", 0)
    tab = MainWindow().remote_tab
    def status_has(text):
        QApplication.processEvents(); return text in tab.status.text()
    tab.after_run_ended(p, "water")
    assert until(lambda: status_has("not read yet"), 30) and "Press Download results" not in tab.status.text() and "Run on the cluster again" in tab.log.toPlainText()
    os.utime(os.path.join(root, "Systems", "water", "water.npy"))                                         # SCOPE ran again and saved: all read
    tab.after_run_ended(p, "water")
    assert until(lambda: status_has("Press Download results"), 30)

def test_the_download_dialog_warns_that_the_system_file_lacks_those_results(local, cluster):
    from PySide6.QtWidgets import QApplication
    from scope.gui.window import MainWindow
    app = QApplication.instance() or QApplication([])
    env, info = local; root = cluster.remote_root.rstrip("/"); now = time.time()
    project_files(root, "water", now - 3600, now - 60)
    listing = {"files": [["demo/opt_r1.com", 1, now - 3660], ["demo/opt_r1.log", 1, now - 60], ["../x", 1, now]], "system": [7, now - 3600]}
    assert transfer.unread(listing) == ["demo/opt_r1.log"] and transfer.unread({"files": listing["files"]}) == []
    win = MainWindow(); win.session.set_environment(env, info); tab = win.remote_tab
    tab.name.setText("fake"); tab.host.setEditText(cluster.host); tab.scope_bin.setText(cluster.scope_bin); tab.root.setText(cluster.remote_root); tab.env_file.setText(cluster.remote_env)
    assert tab.save_profile(); tab.refresh_systems()
    dialog = tab.open_download(system="water"); t0 = time.time()
    while (dialog.busy or not dialog.listing) and time.time() - t0 < 30: app.processEvents(); time.sleep(0.02)
    assert sorted(dialog.unread) == ["demo/opt_r1.log", "demo/opt_r1.stdout"]
    assert "2 output(s) are not read by SCOPE yet" in dialog.summary.text() and "Run on the cluster again" in dialog.log.toPlainText()
    assert "does not include their results" in dialog.with_system.toolTip()
    dialog.close(); win.close()

# ---- here, on the Results page
def test_outputs_here_but_not_read_are_counted_apart_from_missing_ones():
    row = lambda rel, group, here: results.CompRow("b", "w", "opt", 1, 1, "g16", "opt", "i", "f", "", group, None, None, "/x/" + rel, rel, here, True)
    s = results.Summary([], [row("a.log", "unregistered", True), row("b.log", "waiting", False), row("c.log", "ok", True)])
    assert s.unread_outputs == ["a.log"] and s.missing_outputs == ["b.log"]
