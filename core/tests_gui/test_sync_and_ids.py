"""Point 4: synchronisation warnings (the system file alone is not a sync). Point 8: run logs and records never share a name."""
import os
import time
import pytest

from scope.gui import backend, remote, transfer
from test_remote import isolated, local, WATER                              # noqa: F401  (fixtures: temp HOME, fake ssh)

# ---- point 8
def test_unique_stamps_differ_within_one_second():
    stamps = {backend.unique_stamp() for _ in range(50)}
    assert len(stamps) == 50 and all(s[:8].isdigit() and s[8] == "_" for s in stamps)

def test_two_projects_same_system_same_second_get_different_logs_and_ids(tmp_path, monkeypatch):
    started = []
    class P:
        pid = 4242
    monkeypatch.setattr("subprocess.Popen", lambda *a, **k: started.append(a) or P())
    a = backend.start_detached_local(str(tmp_path / "a" / "scope_env_a.npy"), "water", [str(tmp_path / "x.scope")])
    b = backend.start_detached_local(str(tmp_path / "b" / "scope_env_b.npy"), "water", [str(tmp_path / "x.scope")])
    assert a["id"] != b["id"] and a["log"] != b["log"] and os.path.isfile(a["log"]) and os.path.isfile(b["log"])
    assert len({r["id"] for r in backend.load_runs()}) == 2

def test_cluster_log_names_old_and_new_are_both_understood():
    old, new = "/p/logs/run_my_mol_20261120_101500.log", "/p/logs/run_my_mol_20261120_101500_a1b2c3.log"
    assert remote.log_system(old) == "my_mol" and remote.log_system(new) == "my_mol"
    from scope.gui.runs_page import log_started
    assert log_started(old) == log_started(new) == "2026-11-20 10:15"
    script = remote.detached_run_script(remote.Profile(name="t", host="h", remote_root="/p", remote_env="/p/e.npy"), "my_mol", ["/p/inputs/a.scope"])
    line = next(l for l in script.splitlines() if l.startswith('LOG='))
    assert line.startswith('LOG="$ROOT"/logs/run_"$N"_') and len(line.rsplit("_", 1)[-1]) == len("a1b2c3.log")    # still matched by run_"$N"_*.log

# ---- point 4
def calc(info, system, rel, text="x", age=0):
    path = os.path.join(info.computations_path, system, rel); os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh: fh.write(text)
    if age: os.utime(path, (time.time() - age, time.time() - age))
    return path

def test_upload_check_finds_files_only_here_and_a_newer_cluster_system(local):
    env, info = local
    calc(info, "water", "demo/water_opt_r1.com"); calc(info, "water", "demo/water_opt_r1.log"); calc(info, "water", "demo/water_opt_r1.chk")        # .chk is heavy: never proposed
    calc(info, "water", "demo/water_opt_r1.sub")                                                                # a job script is machine-specific: never proposed
    npy = os.path.join(info.systems_path, "water", "water.npy"); os.utime(npy, (time.time() - 3600, time.time() - 3600))
    listing = {"exists": True, "files": [["demo/water_opt_r1.com", 1, int(time.time())]], "system": [10, int(time.time())]}
    check = transfer.upload_check(listing, info, "water")
    assert check.only_here == ["demo/water_opt_r1.log"] and "newer than this computer" in check.cluster_newer
    assert any("not a synchronisation" in m for m in check.messages)
    in_step = {"exists": True, "files": [["demo/water_opt_r1.com", 1, int(time.time()) + 10], ["demo/water_opt_r1.log", 1, int(time.time()) + 10]], "system": [10, int(time.time()) - 7200]}
    assert transfer.upload_check(in_step, info, "water").messages == []

def test_download_warns_when_the_system_file_comes_without_its_files(local):
    env, info = local
    listing = {"exists": True, "files": [["demo/a.log", 5, int(time.time())], ["demo/a.chk", 5, int(time.time())]], "system": [10, int(time.time())]}
    files = transfer.compare(listing, info, "water")
    for f in files: f.selected = False
    assert transfer.left_behind(files, with_system=True) == ["demo/a.log"] and transfer.left_behind(files, with_system=False) == []
    files[0].selected = True; assert transfer.left_behind(files, with_system=True) == []

def test_upload_files_argv_goes_to_the_cluster_computations(local, tmp_path):
    env, info = local
    p = remote.Profile(name="t", host="h", remote_root="/p", remote_env="/p/e.npy")
    argv = transfer.upload_files_argv(p, info, "water", str(tmp_path / "list.txt"))
    assert argv[-2] == os.path.join(info.computations_path, "water") + "/" and argv[-1] == "h:/p/Computations/water/" and "--delete" not in argv

# ---- Run on the cluster before Upload (reported: "System binary file not found in the expected path …/Systems/<s>/<s>.npy")
from test_remote import cluster                                             # noqa: F401,E402  (fixture: a project folder behind the fake ssh)

def test_run_checks_the_uploaded_files_before_starting(cluster):
    p = cluster; root = p.remote_root; inp = root + "/inputs/opt.scope"
    script = remote.detached_run_script(p, "water", [inp], check_files=True)
    got = remote.parse_started(remote.run_script(p, script).stdout)
    assert got == {"state": "missing", "files": [("system", f"{root}/Systems/water/water.npy"), ("input", inp)]}
    assert not os.path.exists(os.path.join(root, "logs"))                   # nothing started: no lock, no log, no pid file
    os.makedirs(os.path.join(root, "Systems", "water")); open(os.path.join(root, "Systems", "water", "water.npy"), "w").close()
    assert remote.parse_started(remote.run_script(p, script).stdout) == {"state": "missing", "files": [("input", inp)]}
    assert remote.parse_started("__SCOPE_GUI_MISSING__ system /p/Systems/my mol/my mol.npy\n") == {"state": "missing", "files": [("system", "/p/Systems/my mol/my mol.npy")]}

def test_run_before_upload_says_upload_first(cluster, local, tmp_path, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QMessageBox
    from scope.gui.window import MainWindow
    from test_remote_tab import JOB, wait
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes))
    env, info = local
    win = MainWindow(); win.session.set_environment(env, info); tab = win.remote_tab
    inp = tmp_path / "opt.scope"; inp.write_text(JOB); win.session.add_inputs([str(inp)])
    tab.name.setText("fake"); tab.host.setEditText(cluster.host); tab.scope_bin.setText(cluster.scope_bin); tab.root.setText(cluster.remote_root); tab.env_file.setText(cluster.remote_env)
    assert tab.save_profile(); tab.refresh_systems(); tab.system.setCurrentText("water")
    tab.run_remote(); wait(app, tab)                                         # nothing uploaded yet
    assert "Not started" in tab.status.text() and "Press Upload" in tab.status.text() and "system file of 'water'" in tab.status.text()
    assert "Systems/water/water.npy" in tab.log.toPlainText() and not tab.watching and not os.path.exists(os.path.join(cluster.remote_root, "logs"))
    win.close()

def test_run_refuses_an_environment_of_another_project_folder(cluster, tmp_path):
    """Reported: two workspaces, two project folders on the cluster, one environment file (of the first folder). Upload put the system
    in the second folder; `scope set_path` looked in the first and stopped. Now nothing starts and the reason is the environment."""
    other = tmp_path / "other_proj"; (other / "Systems" / "water").mkdir(parents=True); (other / "inputs").mkdir()
    (other / "Systems" / "water" / "water.npy").write_text("x"); (other / "inputs" / "opt.scope").write_text("x")      # what Upload put there
    p = remote.Profile("fake", cluster.host, cluster.scope_bin, "", str(other), cluster.remote_env)                     # the environment of cluster_proj
    got = remote.parse_started(remote.run_script(p, remote.detached_run_script(p, "water", [str(other / "inputs" / "opt.scope")], check_files=True)).stdout)
    systems = os.path.join(cluster.remote_root, "Systems")
    assert got == {"state": "missing", "files": [("envdir", systems), ("system", f"{systems}/water/water.npy")]}
    assert not (other / "logs").exists()
