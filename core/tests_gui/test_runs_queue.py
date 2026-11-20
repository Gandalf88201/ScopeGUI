"""The Runs page reads the scheduler queue: on a cluster `scope run` submits jobs and ends, so a run whose jobs still wait in the queue
must not look finished."""
import os
import shutil
import stat
import pytest

from scope.gui import remote
from test_remote import isolated, cluster                                   # noqa: F401  (fixtures; isolated keeps the real GUI settings safe)
from test_workspaces import qapp

def write_log(root: str, system: str, stamp: str, code: "int | None") -> str:
    os.makedirs(os.path.join(root, "logs"), exist_ok=True)
    path = os.path.join(root, "logs", f"run_{system}_{stamp}.log")
    with open(path, "w") as f: f.write("some output\n" + (f"{remote.EXIT_MARKER_REMOTE} {code}\n" if code is not None else ""))
    return path

def fake_tool(tmp_path, monkeypatch, name: str, body: str) -> None:
    """Puts a fake `name` program first on the PATH that the stand-in cluster's shell inherits."""
    d = tmp_path / "fakebin"; d.mkdir(exist_ok=True)
    f = d / name; f.write_text("#!/bin/bash\n" + body); f.chmod(f.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{d}{os.pathsep}{os.environ['PATH']}")

def projects_of(p) -> dict:
    return {(remote.connection_key(p), p.remote_root): (p, ["Default"])}

# ---- parsers
def test_parse_runs_reads_last_runs_and_the_queue():
    out = ("__SCOPE_GUI_LAST__ - /p/logs/run_water_20261120_101500.log\n"
           "__SCOPE_GUI_LAST__ 0 /p/logs/run_water_20261119_090000.log\n"            # older log of the same system: ignored
           "__SCOPE_GUI_LAST__ 143 /p/logs/run_my_mol_20261118_080000.log\n"
           "__SCOPE_GUI_QUEUE__ slurm\n"
           "__SCOPE_GUI_JOB__ 11|PENDING|water_wf_run1_r1|/p/Computations/water/demo\n"
           "__SCOPE_GUI_JOB__ 12|RUNNING|x|/p/Computations/my_mol\n")
    d = remote.parse_runs(out)
    assert d["last"] == {"water": ("/p/logs/run_water_20261120_101500.log", None), "my_mol": ("/p/logs/run_my_mol_20261118_080000.log", 143)}
    assert d["scheduler"] == "slurm" and [(j.id, j.phase, j.workdir) for j in d["jobs"]] == [("11", "pending", "/p/Computations/water/demo"), ("12", "running", "/p/Computations/my_mol")]
    assert remote.parse_runs("")["scheduler"] is None

def test_jobs_belong_to_a_system_by_folder_then_by_name():
    J = remote.QueuedJob
    jobs = [J("1", "PENDING", "anything", "/p/Computations/water/demo"),              # by folder, whatever its name
            J("2", "RUNNING", "water_2_wf_r1", "/p"),                                  # in the project but not in a system folder: by name, longest first
            J("3", "qw", "water_wf_r1", ""),                                           # no folder (SGE): by name
            J("4", "PENDING", "water_wf_r1", "/other/Computations/water"),            # another project
            J("5", "PENDING", "waterfall", "")]                                        # a name that only starts like a system
    got = remote.jobs_by_system(jobs, "/p/", ["water", "water_2"])
    assert {s: [j.id for j in js] for s, js in got.items()} == {"water": ["1", "3"], "water_2": ["2"]}
    assert remote.jobs_summary([J("1", "PENDING", ""), J("2", "RUNNING", ""), J("3", "qw", ""), J("4", "Eqw", "")]) == "1 running, 2 pending, 1 eqw"
    assert remote.jobs_summary([]) == ""

def test_cluster_rows_say_waiting_while_jobs_are_queued():
    from scope.gui import runs_page
    p = remote.Profile("hpc", "hpc.example", "", "", "/p", "/p/env.npy"); J = remote.QueuedJob
    found = {"active": [("busy", "7", "/p/logs/run_busy_20261120_120000.log")],
             "last": {"water": ("/p/logs/run_water_20261120_101500.log", 0), "done": ("/p/logs/run_done_20261119_090000.log", 0), "killed": ("/p/logs/run_killed_20261119_090000.log", 143)},
             "scheduler": "slurm", "jobs": [J("1", "PENDING", "water_a", "/p/Computations/water"), J("2", "RUNNING", "orphan_a", "/p/Computations/orphan")]}
    rows = {r.system: r for r in runs_page.cluster_rows_of(p, ["Default"], found)}
    assert (rows["busy"].state, rows["busy"].jobs) == ("running", "none in queue")
    assert (rows["water"].state, rows["water"].jobs, rows["water"].started) == ("waiting for jobs", "1 pending", "2026-11-20 10:15")
    assert (rows["done"].state, rows["done"].jobs) == ("finished (exit 0)", "none in queue")
    assert rows["killed"].state == "stopped"
    assert (rows["orphan"].state, rows["orphan"].log, rows["orphan"].jobs) == ("waiting for jobs", "", "1 running")    # jobs submitted outside the window
    assert [r.system for r in runs_page.cluster_rows_of(p, ["Default"], found)][:3] == ["busy", "orphan", "water"]       # active, then queued, then the rest
    assert runs_page.queue_text("error", []) == "queue not readable" and runs_page.queue_text("none", []) == runs_page.queue_text(None, []) == "no scheduler"

# ---- through the stand-in cluster (fake ssh), with a fake scheduler
def test_check_the_clusters_reads_the_slurm_queue(cluster, tmp_path, monkeypatch):
    from scope.gui import runs_page
    p = cluster; root = p.remote_root.rstrip("/")
    write_log(root, "water", "20261120_101500", 0); write_log(root, "benzene", "20261119_090000", 0)
    fake_tool(tmp_path, monkeypatch, "squeue", 'printf "%s\\n" '
              f'"31|PENDING|water_wf_run1_r1|{root}/Computations/water/demo" "32|RUNNING|water_wf_run2_r1|{root}/Computations/water/demo" '
              '"33|PENDING|water_wf_run1_r1|/elsewhere/Computations/water"\n')
    rows, messages = runs_page.check_clusters(projects_of(p))
    got = {r.system: (r.state, r.jobs) for r in rows}
    assert got == {"water": ("waiting for jobs", "1 running, 1 pending"), "benzene": ("finished (exit 0)", "none in queue")}
    assert "0 active run(s), 2 job(s) in the queue" in messages[0]

def test_check_the_clusters_says_when_the_queue_cannot_be_read_or_there_is_none(cluster, tmp_path, monkeypatch):
    from scope.gui import runs_page
    p = cluster; root = p.remote_root.rstrip("/"); write_log(root, "water", "20261120_101500", 0)
    if not (shutil.which("squeue") or shutil.which("qstat")):                  # this computer has no scheduler: the stand-in cluster has none either
        rows, messages = runs_page.check_clusters(projects_of(p))
        assert [(r.state, r.jobs) for r in rows] == [("finished (exit 0)", "no scheduler")] and messages[0].endswith("0 active run(s)")
    fake_tool(tmp_path, monkeypatch, "squeue", 'echo "slurm_load_jobs error: Unable to contact slurm controller" >&2; exit 1\n')
    rows, messages = runs_page.check_clusters(projects_of(p))
    assert [(r.state, r.jobs) for r in rows] == [("finished (exit 0)", "queue not readable")] and "queue not readable" in messages[0]

SGE_LIST = """job-ID  prior   name       user         state submit/start at     queue                          slots ja-task-ID
-----------------------------------------------------------------------------------------------------------------
   1234 0.55500 water_wf_r user         r     11/20/2026 10:00:00 all.q@node1                        1
       Full jobname:     water_wf_run1_r1
   1235 0.00000 water_wf_r user         qw    11/20/2026 10:01:00                                    1
       Full jobname:     water_wf_run2_r1
   1236 0.00000 water_wf_r user         qw    11/20/2026 10:01:00                                    1
       Full jobname:     water_wf_run1_r1
   1237 0.00000 water_wf_r user         qw    11/20/2026 10:02:00                                    1
       Full jobname:     water_wf_run3_r1
   1238 0.00000 benzene_wf user         qw    11/20/2026 10:01:00                                    1
       Full jobname:     benzene_wf_run1_r1
"""

SGE_JOBS = """==============================================================
job_number:                 1234
sge_o_workdir:              ROOT/Computations/water/demo
cwd:                        ROOT/Computations/water/demo
==============================================================
job_number:                 1235
sge_o_workdir:              ROOT/Computations/water/demo
==============================================================
job_number:                 1236
sge_o_workdir:              /elsewhere/proj/Computations/water
cwd:                        /elsewhere/proj/Computations/water
"""

def test_check_the_clusters_reads_the_sge_queue_and_each_job_folder(cluster, tmp_path, monkeypatch):
    from scope.gui import runs_page
    if shutil.which("squeue"): pytest.skip("a real squeue is on the PATH and would be asked first")
    p = cluster; root = p.remote_root.rstrip("/"); write_log(root, "water", "20261120_101500", 0)
    asked = tmp_path / "qstat_j"
    fake_tool(tmp_path, monkeypatch, "qconf", "exit 0\n")                     # how SGE is recognised (as SCOPE does)
    fake_tool(tmp_path, monkeypatch, "qstat", f'if [ "$1" = "-j" ]; then echo "$2" > "{asked}"; cat <<\'EOF\'\n' + SGE_JOBS.replace("ROOT", root) + "EOF\nexit 0; fi\n"
              "cat <<'EOF'\n" + SGE_LIST + "EOF\n")
    rows, messages = runs_page.check_clusters(projects_of(p))
    # 1234 by cwd, 1235 by the folder it was submitted from, 1237 by name (qstat -j said nothing about it);
    # 1236 has the same name but runs in another project, and benzene has no run in this project
    assert [(r.system, r.state, r.jobs) for r in rows] == [("water", "waiting for jobs", "1 running, 2 pending")]
    assert asked.read_text().strip() == "1234,1235,1236,1237,1238" and "3 job(s) in the queue" in messages[0]
    tip = {j.id for j in rows[0].queued}; assert tip == {"1234", "1235", "1237"}

def test_a_qstat_that_is_not_sge_is_not_read_as_an_empty_queue(cluster, tmp_path, monkeypatch):
    from scope.gui import runs_page
    if shutil.which("squeue") or shutil.which("qconf"): pytest.skip("a real scheduler is on the PATH")
    monkeypatch.delenv("SGE_ROOT", raising=False)
    p = cluster; root = p.remote_root.rstrip("/"); write_log(root, "water", "20261120_101500", 0)
    fake_tool(tmp_path, monkeypatch, "qstat", "cat <<'EOF'\n"                  # PBS/Torque output: no 'Full jobname' lines
              "Job ID          Username Queue    Jobname    SessID NDS TSK Memory Time  S Time\n"
              "--------------- -------- -------- ---------- ------ --- --- ------ ----- - -----\n"
              "5501.pbs        user     batch    water_wf_r    --    1   1    --  01:00 Q   --\n"
              "EOF\n")
    rows, messages = runs_page.check_clusters(projects_of(p))
    assert [(r.state, r.jobs) for r in rows] == [("finished (exit 0)", "scheduler not recognised")] and "scheduler not recognised" in messages[0]

def test_a_project_reached_through_a_link_still_finds_its_jobs(cluster, tmp_path, monkeypatch):
    from scope.gui import runs_page
    p = cluster; real = os.path.realpath(p.remote_root.rstrip("/"))
    write_log(real, "water", "20261120_101500", 0); write_log(real, "benzene", "20261120_101500", 0)
    os.makedirs(f"{real}/Computations/water/demo", exist_ok=True); os.makedirs(f"{real}/Computations/benzene", exist_ok=True)
    link = str(tmp_path / "home_link"); os.symlink(real, link)
    linked = remote.Profile(**{**p.__dict__, "remote_root": link})                      # the profile names the project through the link
    fake_tool(tmp_path, monkeypatch, "squeue", 'printf "%s\\n" '
              f'"51|PENDING|water_wf_run1_r1|{real}/Computations/water/demo" '        # Slurm reports the physical folder
              f'"52|RUNNING|benzene_wf_run1_r1|{link}/Computations/benzene"\n')         # or the folder through the link
    rows, _ = runs_page.check_clusters(projects_of(linked))
    assert {r.system: r.jobs for r in rows} == {"water": "1 pending", "benzene": "1 running"}
    rows, _ = runs_page.check_clusters(projects_of(remote.Profile(**{**p.__dict__, "remote_root": real})))     # and the other way round
    assert {r.system: r.jobs for r in rows} == {"water": "1 pending", "benzene": "1 running"}

def test_jobs_are_matched_through_resolved_folders():
    J = remote.QueuedJob
    jobs = [J("1", "PENDING", "x", "/home/u/proj/Computations/water", "/gpfs/home/u/proj/Computations/water"),
            J("2", "PENDING", "water_a", "/gpfs/other/Computations/water", "/gpfs/other/Computations/water")]
    assert {s: [j.id for j in js] for s, js in remote.jobs_by_system(jobs, "/gpfs/home/u/proj", ["water"]).items()} == {"water": ["1"]}
    assert {s: [j.id for j in js] for s, js in remote.jobs_by_system(jobs[:1], "/link/proj", ["water"], root_real="/gpfs/home/u/proj").items()} == {"water": ["1"]}
    d = remote.parse_runs("__SCOPE_GUI_REALROOT__ /gpfs/p\n__SCOPE_GUI_JOB__ 7|PENDING|w_a|/home/p/Computations/w|/gpfs/p/Computations/w\n__SCOPE_GUI_JOB__ 8|qw|w_b||\n")
    assert d["root_real"] == "/gpfs/p" and [(j.workdir, j.realdir) for j in d["jobs"]] == [("/home/p/Computations/w", "/gpfs/p/Computations/w"), ("", "")]

# ---- the Cluster page, when the run it follows ends
def test_the_cluster_page_does_not_offer_the_results_while_jobs_are_queued(cluster, tmp_path, monkeypatch):
    qapp(); from PySide6.QtWidgets import QApplication
    from scope.gui.window import MainWindow
    from test_runs_outlive_window import until
    p = cluster; root = p.remote_root.rstrip("/")
    fake_tool(tmp_path, monkeypatch, "squeue", f'[ -f "{tmp_path}/empty" ] || echo "41|PENDING|water_wf_run1_r1|{root}/Computations/water/demo"\n')
    tab = MainWindow().remote_tab
    def status_has(text):
        QApplication.processEvents(); return text in tab.status.text()
    tab.after_run_ended(p, "water")
    assert until(lambda: status_has("still in the scheduler queue"), 30) and "1 pending" in tab.status.text() and "Download" not in tab.status.text()
    assert "run again" in tab.log.toPlainText()
    (tmp_path / "empty").write_text("")                                         # the jobs are done
    tab.after_run_ended(p, "water")
    assert until(lambda: status_has("Press Download results"), 30)

# ---- the page
def test_the_page_shows_the_jobs_column_and_does_not_offer_to_stop_a_waiting_run(monkeypatch):
    qapp(); from PySide6.QtWidgets import QMessageBox
    from scope.gui import runs_page
    p = remote.Profile("hpc", "hpc.example", "", "", "/p", "/p/env.npy")
    found = {"active": [], "last": {"water": ("/p/logs/run_water_20261120_101500.log", 0)}, "scheduler": "slurm",
             "jobs": [remote.QueuedJob("31", "PENDING", "water_a", "/p/Computations/water"), remote.QueuedJob("32", "PENDING", "x", "/p/Computations/ghost")]}
    page = runs_page.RunsPage(None); page.cluster_rows = runs_page.cluster_rows_of(p, ["Default"], found)
    monkeypatch.setattr(runs_page, "local_rows", lambda spaces: []); page.refresh()
    header = [page.table.horizontalHeaderItem(i).text() for i in range(page.table.columnCount())]
    assert header == ["Workspace", "System", "Where", "State", "Jobs", "Started", "Log"]
    row = [r.system for r in page.rows].index("water")
    assert page.table.item(row, 3).text() == "waiting for jobs" and page.table.item(row, 4).text() == "1 pending" and "31" in page.table.item(row, 4).toolTip()
    said = []; monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda parent, title, text: said.append(text)))
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: pytest.fail("must not offer to stop")))
    page.table.selectRow(row); page.stop_selected()
    assert "already ended" in said[-1] and "scancel" in said[-1]
    page.table.selectRow([r.system for r in page.rows].index("ghost")); page.show_selected()                       # jobs with no log of ours: nothing to follow
    assert "no log to follow" in said[-1]
