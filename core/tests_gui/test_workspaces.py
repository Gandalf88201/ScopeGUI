"""Workspaces: several projects in one window, one shown at a time, each with its environment, inputs and project on the cluster."""
import json
import os
import subprocess
import sys
import pytest

from scope.gui import backend, remote, workspaces
from test_remote import isolated, cluster, local, WATER                    # noqa: F401  (fixtures)
from test_runs_outlive_window import ready, until, JOB                    # noqa: F401  (fixtures)

def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])

def second_env(tmp_path, name="other"):
    root = tmp_path / name
    env, info = backend.create_environment(name, str(root / "Sources"), str(root / "Systems"), str(root / "Computations"), str(root))
    x = tmp_path / f"{name}_water.xyz"; x.write_text(WATER); backend.import_xyz(env, str(x))
    return env, info

def an_input(folder, job="opt", branch="demo"):
    os.makedirs(folder, exist_ok=True); f = os.path.join(folder, f"{job}.scope")
    open(f, "w").write(JOB.replace("'opt'", f"'{job}'", 1).replace("'demo'", f"'{branch}'")); return f

# ---- the module, without the window
def test_first_start_makes_a_default_workspace_from_the_old_settings(local):
    env, info = local
    profile = remote.Profile("hpc", "login1", "/s/scope", "", "~/old_project", "~/old_project/scope_env_c.npy"); remote.save_profile(profile)
    backend.save_gui_config({"last_env": info.filepath})
    ws = workspaces.ensure()
    assert (ws.name, ws.env_path, ws.profile, ws.remote_root, ws.remote_env, ws.legacy) == ("Default", info.filepath, "hpc", "~/old_project", "~/old_project/scope_env_c.npy", True)
    assert backend.load_gui_config()["workspaces_migrated"] and remote.load_profiles()["hpc"] == profile          # the stored profile is untouched
    assert workspaces.ensure() == ws and workspaces.list_names() == ["Default"]                                   # done once

def test_with_several_old_profiles_the_default_workspace_falls_back_to_the_chosen_profile(local):
    for n in ("a", "b"): remote.save_profile(remote.Profile(n, "h", "/s", "", f"~/{n}", f"~/{n}/e.npy"))
    ws = workspaces.ensure()
    assert ws.profile == "" and ws.remote_root == "" and ws.legacy
    assert workspaces.remote_fields(ws, remote.load_profiles()["b"]) == ("~/b", "~/b/e.npy")                      # nothing of the old profiles is lost
    other = workspaces.create("New one")
    assert workspaces.remote_fields(other, remote.load_profiles()["b"]) == ("", "")                               # a new workspace never borrows another project's folder

def test_removing_every_workspace_by_hand_starts_again_empty():
    workspaces.ensure()
    for f in os.listdir(workspaces.folder()): os.remove(os.path.join(workspaces.folder(), f))
    ws = workspaces.ensure()
    assert ws.name == "Default" and not ws.legacy and ws.env_path == ""

def test_names_create_rename_delete():
    workspaces.ensure()
    assert workspaces.name_problem("", []) and workspaces.name_problem("-x", []) and workspaces.name_problem("a/b", [])
    assert workspaces.name_problem("Water project", ["water-project"]) == "" and workspaces.name_problem("water project", ["Water project"])     # same name but for case
    a = workspaces.create("Water project", profile="hpc")
    with pytest.raises(ValueError): workspaces.create("water project")
    workspaces.set_active(a.name)
    b = workspaces.rename("Water project", "Water (B3LYP)")
    assert workspaces.active_name() == "Water (B3LYP)" and workspaces.load("Water (B3LYP)").profile == "hpc" and workspaces.load("Water project") is None
    workspaces.delete("Water (B3LYP)")
    assert workspaces.list_names() == ["Default"] and workspaces.active_name() == "Default"
    with pytest.raises(ValueError, match="last workspace"): workspaces.delete("Default")

def test_two_processes_saving_workspaces_and_preferences_at_once_lose_nothing():
    workspaces.ensure()
    code = ("import sys\nfrom scope.gui import backend, workspaces\ntag = sys.argv[1]\n"
            "for i in range(15):\n    workspaces.save(workspaces.Workspace(f'{tag}{i}', inputs=[str(i)]))\n    backend.save_gui_config({f'key_{tag}_{i}': i})\n")
    procs = [subprocess.Popen([sys.executable, "-c", code, t], env=dict(os.environ)) for t in ("a", "b")]
    for p in procs: assert p.wait(60) == 0
    names, config = set(workspaces.list_names()), backend.load_gui_config()
    assert {f"a{i}" for i in range(15)} | {f"b{i}" for i in range(15)} <= names
    assert all(f"key_{t}_{i}" in config for t in "ab" for i in range(15))                                          # every key written by either process is kept

def test_run_records_belong_to_their_environment_and_old_ones_to_the_legacy_workspace(tmp_path):
    rec = {"env": os.path.abspath(tmp_path / "e.npy")}
    assert backend.record_belongs(rec, str(tmp_path / "e.npy")) and not backend.record_belongs(rec, str(tmp_path / "f.npy")) and not backend.record_belongs(rec, "")
    assert backend.record_belongs({}, "", legacy=True) and not backend.record_belongs({}, str(tmp_path / "e.npy"))

# ---- the window
def slow_run(info, inp, seconds=60):
    """Starts a run the normal way, but of a program that takes long (so it is still running while the test switches workspaces)."""
    slow = os.path.join(os.path.dirname(inp), "slow.py"); open(slow, "w").write(f"import time; time.sleep({seconds})\n")
    original = backend.build_run_command
    try:
        backend.build_run_command = lambda *a, **k: (sys.executable, [slow])
        return backend.start_detached_local(info.filepath, "water", [inp])
    finally:
        backend.build_run_command = original

def test_each_workspace_keeps_its_environment_inputs_and_cluster_project(ready, tmp_path, monkeypatch):
    qapp(); from PySide6.QtWidgets import QInputDialog
    from scope.gui.window import MainWindow
    env, info, inp = ready; env_b, info_b = second_env(tmp_path)
    win = MainWindow(); win.session.set_environment(env, info); win.session.add_inputs([inp])
    win.remote_tab.root.setText("~/project_a"); win.remote_tab.env_file.setText("~/project_a/scope_env_c.npy")
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("Project B", True)))
    win.new_workspace()
    assert win.workspace.name == "Project B" and win.session.info is None and win.session.reports == []
    assert "No environment in this workspace yet" in win.env_tab.summary.toPlainText() and win.env_tab.sources.text() == ""      # nothing of A is left in the form
    assert win.remote_tab.root.text() == "" and "~/scope_projects/Project_B" in win.remote_tab.root.placeholderText()
    assert not win.step_done("environment") and not win.step_done("pipeline")
    input_b = an_input(str(tmp_path / "b_inputs"), "freq", "other")
    win.session.set_environment(env_b, info_b); win.session.add_inputs([input_b]); win.remote_tab.root.setText("~/project_b")
    win.ws_combo.setCurrentText("Default")
    assert win.session.info.filepath == info.filepath and [r.path for r in win.session.reports] == [os.path.abspath(inp)] and win.remote_tab.root.text() == "~/project_a"
    win.ws_combo.setCurrentText("Project B")
    assert win.session.info.filepath == info_b.filepath and [r.path for r in win.session.reports] == [os.path.abspath(input_b)] and win.remote_tab.root.text() == "~/project_b"
    win.close()
    again = MainWindow()                                                                                               # the window opens on the workspace shown last
    assert again.workspace.name == "Project B" and again.session.info.filepath == info_b.filepath and again.ws_combo.currentText() == "Project B"
    assert sorted(again.ws_combo.itemText(i) for i in range(again.ws_combo.count())) == ["Default", "Project B"]

def test_an_input_file_that_disappeared_shows_as_an_error_row(ready, tmp_path):
    qapp(); from scope.gui.window import MainWindow
    env, info, inp = ready; gone = an_input(str(tmp_path / "gone"), "scf")
    win = MainWindow(); win.session.set_environment(env, info); win.session.add_inputs([inp, gone]); os.remove(gone)
    win.load_workspace(workspaces.load(win.workspace.name))
    rows = {os.path.basename(r.path): r for r in win.session.reports}
    assert rows["opt.scope"].ok and not rows["scf.scope"].ok and rows["scf.scope"].error                               # kept, and shown as a problem

def test_a_run_keeps_going_while_another_workspace_is_shown_and_comes_back(ready, tmp_path, monkeypatch):
    qapp(); from PySide6.QtWidgets import QInputDialog
    from scope.gui.window import MainWindow
    env, info, inp = ready
    win = MainWindow(); win.session.set_environment(env, info); win.session.add_inputs([inp])
    record = slow_run(info, inp); win.run_tab.attach(record); assert win.run_tab.running()
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("Other", True)))
    win.new_workspace()
    assert win.run_tab.record is None and not win.run_tab.running()                                                   # B does not show A's run
    assert backend.run_state(record)[0] == "running" and not [r for r in backend.load_runs() if r["id"] == record["id"]][0]["seen"]   # still going, not marked seen
    win.ws_combo.setCurrentText("Default")
    assert win.run_tab.record and win.run_tab.record["id"] == record["id"] and win.run_tab.running()                  # found again
    backend.stop_run(record); assert until(lambda: backend.run_state(record)[0] != "running", 20)

def test_the_same_system_cannot_be_started_twice_from_two_workspaces(ready, tmp_path, monkeypatch):
    qapp(); from PySide6.QtWidgets import QInputDialog, QMessageBox
    from scope.gui.window import MainWindow
    env, info, inp = ready
    win = MainWindow(); win.session.set_environment(env, info); win.session.add_inputs([inp])
    record = slow_run(info, inp)
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("Second look", True)))
    win.new_workspace(); win.session.set_environment(env, info); win.session.add_inputs([inp]); win.run_tab.refresh(); win.run_tab.system.setCurrentText("water")
    told = []; monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: told.append(a[1]) or QMessageBox.Ok))
    before = len(backend.load_runs()); win.run_tab.start()
    assert told == ["This system is already running"] and len(backend.load_runs()) == before
    backend.stop_run(record); assert until(lambda: backend.run_state(record)[0] != "running", 20)

def test_runs_recorded_before_workspaces_existed_show_in_the_default_workspace_only(ready, tmp_path, monkeypatch):
    qapp(); from PySide6.QtWidgets import QInputDialog
    from scope.gui.window import MainWindow
    env, info, inp = ready
    old = slow_run(info, inp); old.pop("env")
    backend.update_runs(lambda records: [r.pop("env", None) for r in records])                                        # as an older version wrote it
    backend.save_gui_config({"last_env": info.filepath})
    win = MainWindow()                                                                                                 # first start with workspaces: Default is made, and it is legacy
    assert win.workspace.legacy and win.run_tab.record and win.run_tab.record["id"] == old["id"]
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("Fresh", True)))
    win.new_workspace(); win.session.set_environment(env, info); win.run_tab.reattach()
    assert win.run_tab.record is None                                                                                  # same environment, but not the legacy workspace
    backend.stop_run(old); assert until(lambda: backend.run_state(old)[0] != "running", 20)

def test_saving_a_profile_saves_the_connection_and_the_project_stays_with_the_workspace(cluster, local, monkeypatch):
    qapp(); from PySide6.QtWidgets import QInputDialog, QMessageBox
    from scope.gui.window import MainWindow
    warned = []; monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: warned.append(a[2]) or QMessageBox.Ok))
    env, info = local; p = cluster
    win = MainWindow(); win.session.set_environment(env, info); tab = win.remote_tab
    tab.name.setText("hpc"); tab.host.setEditText(p.host); tab.scope_bin.setText(p.scope_bin); tab.root.setText(p.remote_root); tab.env_file.setText(p.remote_env)
    assert tab.save_profile()
    stored = backend.load_gui_config()["profiles"]["hpc"]
    assert stored["host"] == p.host and stored["remote_root"] == "" and stored["remote_env"] == ""                    # the profile is the connection only
    assert workspaces.load("Default").remote_root == p.remote_root and workspaces.load("Default").profile == "hpc"   # the project is the workspace's
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("Second", True)))
    win.new_workspace()
    assert tab.chooser.currentText() == "hpc" and tab.host.currentText() == p.host and tab.root.text() == ""           # same cluster, its own project folder
    tab.name.setText(""); assert not tab.save_profile() and "Profile name" in warned[-1]                              # a profile still needs its connection fields
    assert "Project folder" in tab.hint.text()

def test_rename_and_delete_from_the_window(ready, monkeypatch):
    qapp(); from PySide6.QtWidgets import QInputDialog, QMessageBox
    from scope.gui.window import MainWindow
    env, info, inp = ready
    win = MainWindow(); win.session.set_environment(env, info)
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("Water study", True)))
    win.rename_workspace()
    assert win.workspace.name == "Water study" and win.ws_combo.currentText() == "Water study" and workspaces.active_name() == "Water study"
    told = []; monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: told.append(a[1]) or QMessageBox.Ok))
    win.delete_workspace(); assert told == ["Last workspace"]
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("Scratch", True)))
    win.new_workspace(); assert win.workspace.name == "Scratch"
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes))
    win.delete_workspace()
    assert win.workspace.name == "Water study" and workspaces.list_names() == ["Water study"] and win.session.info.filepath == info.filepath
    assert os.path.isfile(info.filepath)                                                                               # deleting a workspace touches no project file
