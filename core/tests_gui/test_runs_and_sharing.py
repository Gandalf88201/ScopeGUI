"""Phase 2 (the Runs page across workspaces) and phase 3 (a cluster folder shared by two workspaces, export and import of a workspace)."""
import json
import os
import pytest

from scope.gui import backend, remote, workspaces
from test_remote import isolated, cluster, local, WATER                    # noqa: F401  (fixtures)
from test_runs_outlive_window import ready, until, JOB, slow_cluster      # noqa: F401  (fixtures)
from test_workspaces import slow_run, second_env, qapp

def window_with_two_workspaces(env, info, inp, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QInputDialog
    from scope.gui.window import MainWindow
    win = MainWindow(); win.session.set_environment(env, info); win.session.add_inputs([inp])
    env_b, info_b = second_env(tmp_path)
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("Project B", True)))
    win.new_workspace(); win.session.set_environment(env_b, info_b)
    return win, info_b

# ---- phase 2: the Runs page
def test_the_runs_page_lists_local_runs_of_every_workspace_and_shows_or_stops_them(ready, tmp_path, monkeypatch):
    qapp(); from PySide6.QtWidgets import QMessageBox
    env, info, inp = ready
    win, info_b = window_with_two_workspaces(env, info, inp, tmp_path, monkeypatch)
    run_a = slow_run(info, inp)                                                                                   # a run of the Default workspace, while B is shown
    run_b = backend.start_detached_local(info_b.filepath, "other_water", [inp])                                   # a short run of B
    assert until(lambda: backend.run_state(run_b)[0] == "finished", 60)
    win.go(len(win.step_buttons) + 1); page = win.runs_page; page.refresh()
    rows = {(r.workspace, r.system): r for r in page.rows}
    assert rows[("Default", "water")].state == "running" and rows[("Project B", "other_water")].state.startswith("finished")
    assert page.table.rowCount() == len(page.rows) and page.table.item(0, 0).text()
    page.table.selectRow(page.rows.index(rows[("Default", "water")])); page.show_selected()
    assert win.workspace.name == "Default" and win.tabs.currentIndex() == 3 and win.run_tab.record["id"] == run_a["id"]      # switched, and the Run page follows it
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes))
    page.refresh(); page.table.selectRow([r.record and r.record["id"] for r in page.rows].index(run_a["id"])); page.stop_selected()
    assert until(lambda: backend.run_state(run_a)[0] != "running", 20)

def test_check_the_clusters_finds_runs_of_shared_projects_and_show_follows_them(slow_cluster, ready, tmp_path, monkeypatch):
    qapp(); from scope.gui import runs_page
    env, info, inp = ready; p = slow_cluster
    remote.save_profile(remote.Profile("hpc", p.host, p.scope_bin, "", "", ""), connection_only=True)
    win, info_b = window_with_two_workspaces(env, info, inp, tmp_path, monkeypatch)
    for name in ("Default", "Project B"):                                                                         # both workspaces use the same cluster project
        ws = workspaces.load(name); ws.profile, ws.remote_root, ws.remote_env = "hpc", p.remote_root, p.remote_env; workspaces.save(ws)
    assert remote.run_script(p, remote.remote_dirs_script(p, "water")).ok
    started = remote.parse_started(remote.run_script(p, remote.detached_run_script(p, "water", [p.remote_root + "/inputs/a.scope"])).stdout)
    spaces = [workspaces.load(n) for n in workspaces.list_names()]
    projects = runs_page.cluster_projects(spaces, remote.load_profiles())
    assert len(projects) == 1 and sorted(next(iter(projects.values()))[1]) == ["Default", "Project B"]          # one project, asked once
    rows, messages = runs_page.check_clusters(projects)
    assert [(r.system, r.state, r.where) for r in rows] == [("water", "running", p.host)] and "1 active run" in messages[0]
    win.runs_page.cluster_rows = rows; win.show_run(rows[0])
    assert win.tabs.currentIndex() == 4 and win.remote_tab.watching and win.remote_tab.watching["log"] == started["log"]
    remote.run_script(p, remote.stop_script(p, "water")); win.remote_tab.stop_watching()

# ---- phase 3: a cluster folder used by two workspaces
def test_two_workspaces_on_the_same_cluster_folder_are_warned(cluster, ready, tmp_path, monkeypatch):
    qapp(); env, info, inp = ready; p = cluster
    win, info_b = window_with_two_workspaces(env, info, inp, tmp_path, monkeypatch)
    tab = win.remote_tab
    tab.name.setText("hpc"); tab.host.setEditText(p.host); tab.scope_bin.setText(p.scope_bin); assert tab.save_profile()
    tab.root.setText(p.remote_root); tab.env_file.setText(p.remote_env)
    assert workspaces.sharing("Project B", p.host, p.remote_root, tab.profiles) == []
    win.ws_combo.setCurrentText("Default"); tab.select_profile("hpc"); tab.root.setText(p.remote_root + "/"); tab.env_file.setText(p.remote_env)
    assert tab.shared == ["Project B"] and "Project B" in tab.hint.text() and "⚠" in tab.hint.text()          # a trailing slash is the same folder
    tab.root.setText(p.remote_root + "_other"); assert tab.shared == [] and "⚠" not in tab.hint.text()

# ---- phase 3: export and import
def test_export_and_import_keep_everything_and_never_replace_a_connection(local, tmp_path):
    env, info = local; workspaces.ensure()
    remote.save_profile(remote.Profile("hpc", "login1", "/s/scope", "", "", ""), connection_only=True)
    ws = workspaces.create("Water study", profile="hpc"); ws.env_path, ws.inputs, ws.remote_root, ws.remote_env = info.filepath, ["/gone/opt.scope"], "~/w", "~/w/e.npy"; workspaces.save(ws)
    data = workspaces.export_data(ws, remote.load_profiles()["hpc"])
    assert data["profile"] == {"name": "hpc", "host": "login1", "scope_bin": "/s/scope", "activate": ""} and json.dumps(data)
    same, notes = workspaces.import_data(data, remote.load_profiles())
    assert same.name == "Water study (2)" and same.profile == "hpc" and same.remote_root == "~/w" and same.env_path == info.filepath
    assert any("Water study (2)" in n for n in notes) and any("do not exist on this computer" in n for n in notes)
    other = dict(data, profile={"name": "hpc", "host": "another-cluster", "scope_bin": "/x/scope", "activate": ""})
    imported, notes = workspaces.import_data(other, remote.load_profiles())
    assert imported.profile == "hpc_2" and remote.load_profiles()["hpc"].host == "login1" and remote.load_profiles()["hpc_2"].host == "another-cluster"
    with pytest.raises(ValueError, match="not an exported"): workspaces.import_data({"format": "something else"}, {})

def test_export_and_import_from_the_window(ready, tmp_path, monkeypatch):
    qapp(); from PySide6.QtWidgets import QFileDialog, QMessageBox
    from scope.gui.window import MainWindow
    env, info, inp = ready
    win = MainWindow(); win.session.set_environment(env, info); win.session.add_inputs([inp]); win.remote_tab.root.setText("~/project_a")
    target = str(tmp_path / "default.scopews.json")
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (target, "")))
    win.export_workspace()
    assert json.load(open(target))["workspace"]["inputs"] == [os.path.abspath(inp)]
    told = []; monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: told.append(a[2]) or QMessageBox.Ok))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (target, "")))
    win.import_workspace()
    assert win.workspace.name == "Default (2)" and win.session.info.filepath == info.filepath and [r.path for r in win.session.reports] == [os.path.abspath(inp)]
    assert win.remote_tab.root.text() == "~/project_a" and told and "Default (2)" in told[0]
    assert sorted(win.ws_combo.itemText(i) for i in range(win.ws_combo.count())) == ["Default", "Default (2)"]
