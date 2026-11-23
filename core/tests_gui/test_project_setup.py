"""Set up this folder… on the Cluster page: the GUI sends scope_project.py to the cluster (here a stand-in reached through a fake ssh)
and runs it with SCOPE's Python, first as a preview, then for real, so that the Folder layout check passes."""
import os
import sys
import pytest

from scope.gui import backend, remote, scope_project
from scope.read_write import load_binary
from test_remote import isolated                                            # noqa: F401  (fixture: private HOME, fake ssh)

SCOPE_BIN = os.path.join(os.path.dirname(sys.executable), "scope")

@pytest.fixture
def working_env(tmp_path):
    """The environment that works on the cluster (made once with scope config): here a local one with a module set."""
    env, info = backend.create_environment("RUNS", str(tmp_path / "RUNS/Sources"), str(tmp_path / "RUNS/Systems"), str(tmp_path / "RUNS/Computations"), str(tmp_path))
    env.g16_module = "gaussian/16a3"; env.save(info.filepath)
    return info.filepath

def profile(root: str, env: str) -> "remote.Profile":
    return remote.Profile("c", "fakehost", SCOPE_BIN, "", root, env)

def checks_of(p):
    res = remote.run_script(p, remote.probe_script(p)); probe = remote.parse_probe(res.stdout)
    return {c.name: c for c in remote.evaluate_probe(p, res)}, list(remote.evaluate_probe(p, res)), probe

def test_the_command_is_the_package_module():
    top = os.path.join(os.path.dirname(__file__), "..", "..", "scope-project")
    assert os.path.realpath(top) == os.path.realpath(scope_project.__file__) and os.access(scope_project.__file__, os.X_OK)

def test_a_new_folder_is_set_up_from_the_cluster_after_a_preview(working_env, tmp_path):
    job = str(tmp_path / "JOB2"); p = profile(job, working_env)                          # the workspace still points at the old environment
    by, checks, probe = checks_of(p)
    assert by["Folder layout"].status == "fail" and remote.needs_project_setup(checks, probe)
    res = remote.run_script(p, remote.project_setup_script(p, job, "from", working_env), timeout=120); out = remote.parse_project_setup(res.stdout)
    assert out["code"] == 0 and out["dry_run"] and not out["changed"] and out["target"] == job + "/scope_env_JOB2.npy" and out["g16"] == "gaussian/16a3"
    assert not os.path.exists(job)                                                                                         # a preview changes nothing
    res = remote.run_script(p, remote.project_setup_script(p, job, "from", working_env, dry_run=False), timeout=120); out = remote.parse_project_setup(res.stdout)
    assert out["code"] == 0 and out["changed"] and os.path.isfile(out["target"]) and out["after"]["Systems"] == job + "/Systems/"
    by, checks, probe = checks_of(profile(job, out["target"]))
    assert by["Folder layout"].status == "ok" and not remote.needs_project_setup(checks, probe)
    res = remote.run_script(p, remote.project_setup_script(p, job, "from", working_env), timeout=120); out = remote.parse_project_setup(res.stdout)
    assert out["code"] == 1 and out.get("exists") and "already exists" in out["error"]                                     # never replaced without --force

def test_a_repair_stops_on_old_data_and_keeps_a_backup(working_env, tmp_path):
    runs = str(tmp_path / "RUNS")
    e = load_binary(working_env); e.sources_path = e.systems_path = e.computations_path = runs + "/"; e.save(working_env)
    os.makedirs(os.path.join(runs, "OLD_SYSTEM")); p = profile("~/" + os.path.relpath(runs, os.path.expanduser("~")) if runs.startswith(os.path.expanduser("~")) else runs, working_env)
    out = remote.parse_project_setup(remote.run_script(p, remote.project_setup_script(p, p.remote_root, "fix", working_env), timeout=120).stdout)
    assert out["code"] == 1 and out["leftovers"] == [os.path.join(runs, "OLD_SYSTEM")] and "--force" in out["error"]
    out = remote.parse_project_setup(remote.run_script(p, remote.project_setup_script(p, p.remote_root, "fix", working_env, force=True, dry_run=False), timeout=120).stdout)
    assert out["code"] == 0 and out["changed"] and out["backup"].startswith(working_env + ".bak-") and os.path.isdir(os.path.join(runs, "OLD_SYSTEM"))
    assert checks_of(p)[0]["Folder layout"].status == "ok"

def test_a_missing_template_is_reported_not_raised(tmp_path):
    p = profile(str(tmp_path / "J"), str(tmp_path / "nothing.npy"))
    out = remote.parse_project_setup(remote.run_script(p, remote.project_setup_script(p, p.remote_root, "from", p.remote_env), timeout=120).stdout)
    assert out["code"] == 1 and "does not exist" in out["error"]
    with pytest.raises(ValueError): remote.project_setup_script(p, "x", "delete", "y")

# ---- the window
import time                                                                  # noqa: E402

def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])

def wait(app, fn, seconds=60):
    t0 = time.time()
    while time.time() - t0 < seconds:
        app.processEvents()
        if fn(): return True
        time.sleep(0.05)
    return False

def test_the_cluster_page_offers_set_up_and_the_retest_passes(working_env, tmp_path):
    app = qapp(); from scope.gui.window import MainWindow
    from scope.gui.project_setup_view import ProjectSetupDialog
    from scope.gui import workspaces
    win = MainWindow(); tab = win.remote_tab
    tab.name.setText("hpc"); tab.host.setEditText("fakehost"); tab.scope_bin.setText(SCOPE_BIN); assert tab.save_profile()
    job = str(tmp_path / "JOB2"); tab.root.setText(job); tab.env_file.setText(working_env)
    assert not tab.setup_btn.isVisibleTo(tab)
    tab.test_connection(); assert wait(app, lambda: not tab.busy and tab.checks)
    assert tab.setup_btn.isVisibleTo(tab) and tab.setup_note.isVisibleTo(tab) and "Set up this folder" in tab.status.text()
    d = ProjectSetupDialog(tab, tab.valid_profile(), tab.probe)
    assert d.new_radio.isChecked() and d.fix_radio.isEnabled() and d.template.currentText() == working_env and d.name.text() == "JOB2" and not d.apply_btn.isEnabled()
    d.run(dry_run=True); assert wait(app, lambda: d.result)
    assert d.apply_btn.isEnabled() and "Nothing has been changed" in d.status.text() and "gaussian/16a3" in d.output.toPlainText() and not os.path.exists(job)
    d.name.setText("other"); assert not d.apply_btn.isEnabled(); d.name.setText("JOB2"); assert d.apply_btn.isEnabled()       # Apply only for what was previewed
    d.result = {}; d.run(dry_run=False); assert wait(app, lambda: d.result and tab.env_file.text().endswith("scope_env_JOB2.npy"))
    assert os.path.isfile(os.path.join(job, "scope_env_JOB2.npy")) and workspaces.load(win.workspace.name).remote_env == os.path.join(job, "scope_env_JOB2.npy")   # saved with the workspace
    assert wait(app, lambda: not tab.busy and any(c.name == "Folder layout" for c in tab.checks) and tab.env_file.text() in tab.probe.get("env", {}).get("name", "") + tab.env_file.text())
    assert wait(app, lambda: {c.name: c.status for c in tab.checks}.get("Folder layout") == "ok")
    assert not tab.setup_btn.isVisibleTo(tab)

def test_a_new_cluster_without_a_working_environment_says_what_to_do(tmp_path):
    app = qapp(); from scope.gui.window import MainWindow
    from scope.gui.project_setup_view import ProjectSetupDialog
    win = MainWindow(); tab = win.remote_tab
    tab.name.setText("hpc"); tab.host.setEditText("fakehost"); tab.scope_bin.setText(SCOPE_BIN); assert tab.save_profile()
    tab.root.setText(str(tmp_path / "NEW")); tab.env_file.setText(str(tmp_path / "NEW/scope_env_NEW.npy"))
    tab.test_connection(); assert wait(app, lambda: not tab.busy and tab.checks) and tab.setup_btn.isVisibleTo(tab)
    d = ProjectSetupDialog(tab, tab.valid_profile(), tab.probe)
    assert not d.fix_radio.isEnabled() and d.template.currentText() == "" and "scope config" in d.form_note.text() and not d.preview_btn.isEnabled()
    tab.root.setText(str(tmp_path / "OTHER")); assert not tab.setup_btn.isVisibleTo(tab)                                       # the test was about the old folder
