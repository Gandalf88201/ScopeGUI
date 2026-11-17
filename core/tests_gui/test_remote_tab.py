"""The Cluster page, driven offscreen against the fake ssh of test_remote."""
import os
import time
import pytest
from test_remote import isolated, cluster, local, WATER                       # noqa: F401  (fixtures)
from scope.gui import backend, remote

JOB = "&environment\n   requested_procs = 2\n/\n&options\n   want_submit = False\n/\n&job_data\n   branch = 'demo'\n   workflow = '*'\n   job = 'opt'\n   hierarchy = 1\n   requisites = []\n   constrains = ['self']\n/\n&qc_data\n   software = 'g16'\n   comp_type = 'opt'\n/\n"

def wait(app, tab, seconds=120):
    t0 = time.time()
    while (tab.busy or tab.running()) and time.time() - t0 < seconds: app.processEvents(); time.sleep(0.03)
    app.processEvents()

def test_cluster_page_end_to_end(cluster, local, tmp_path, monkeypatch):
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QMessageBox
    from scope.gui.window import MainWindow
    app = QApplication.instance() or QApplication([])
    asked = []
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: (asked.append(a[2]), QMessageBox.Yes)[1]))
    for name in ("warning", "information"): monkeypatch.setattr(QMessageBox, name, staticmethod(lambda *a, **k: pytest.fail(f"unexpected dialog: {a[1:3]}")))
    env, info = local
    win = MainWindow(); win.session.set_environment(env, info); tab = win.remote_tab
    inp = tmp_path / "opt.scope"; inp.write_text(JOB); win.session.add_inputs([str(inp)])
    assert not win.step_done("cluster")
    # profile form -> save
    tab.name.setText("fake"); tab.host.setEditText(cluster.host); tab.scope_bin.setText(cluster.scope_bin); tab.root.setText(cluster.remote_root); tab.env_file.setText(cluster.remote_env)
    assert tab.save_profile() and "fake" in remote.load_profiles()
    # connection test
    tab.test_connection(); wait(app, tab)
    assert tab.table.rowCount() >= 6 and not any(c.status == "fail" for c in tab.checks) and win.step_done("cluster")
    assert [l.name for l in tab.lights] == ["SCOPE", "Quantum ESPRESSO", "Gaussian 16"] and tab.lights[0].state == "green" and tab.checked_at       # the lights fill in by themselves
    assert "SCOPE" in tab.light_labels[0].text() and "●" in tab.light_labels[0].text() and tab.light_labels[0].toolTip()
    # upload: preview copies nothing, upload asks first
    tab.refresh_systems(); tab.system.setCurrentText("water")
    tab.upload(preview=True); wait(app, tab)
    assert not os.path.exists(os.path.join(cluster.remote_root, "Systems", "water", "water.npy")) and not asked
    tab.upload(preview=False); wait(app, tab)
    assert asked and os.path.isfile(os.path.join(cluster.remote_root, "Systems", "water", "water.npy")) and os.path.isfile(os.path.join(cluster.remote_root, "inputs", "opt.scope"))
    # run on the cluster
    tab.poll_ms = 100; tab.run_remote(); wait(app, tab)
    assert "MANUAL ATTENTION" in tab.log.toPlainText() and "exit code 0" in tab.status.text() and win.step_done("run")
    assert os.path.isdir(os.path.join(cluster.remote_root, "Computations", "water", "demo"))
    # download warns that the system file is replaced
    asked.clear(); tab.download(preview=False); wait(app, tab)
    assert asked and "replaces the local system file" in asked[-1]

def test_invalid_profile_is_not_used(monkeypatch):
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QMessageBox
    from scope.gui.window import MainWindow
    app = QApplication.instance() or QApplication([])
    shown = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: shown.append(a[2])))
    win = MainWindow(); tab = win.remote_tab
    tab.name.setText("x"); tab.host.setEditText("-oProxyCommand=evil")
    tab.test_connection(); assert shown and not tab.busy and "does not start with '-'" in shown[0]


def test_hint_follows_typing_and_save_gives_visible_feedback(cluster):
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from PySide6.QtTest import QTest
    from scope.gui.window import MainWindow
    app = QApplication.instance() or QApplication([])
    win = MainWindow(); win.resize(1240, 800); win.show(); win.show_step("cluster"); app.processEvents(); tab = win.remote_tab
    assert "To complete the profile" in tab.hint.text() and "Profile name" in tab.hint.text()
    tab.name.setFocus(); QTest.keyClicks(tab.name, "mine"); tab.host.lineEdit().setFocus(); QTest.keyClicks(tab.host.lineEdit(), "login1")
    tab.scope_bin.setFocus(); QTest.keyClicks(tab.scope_bin, "~/miniconda3/envs/scope/bin/scope")
    tab.root.setFocus(); QTest.keyClicks(tab.root, "~/scope_project")
    assert "Environment file" in tab.hint.text() and "Project folder" not in tab.hint.text()
    assert tab.env_file.placeholderText().startswith("~/scope_project/scope_env")
    tab.env_file.setFocus(); QTest.keyClicks(tab.env_file, "~/scope_project/scope_env_c.npy")
    assert tab.hint.text().startswith("✓") and tab.save_profile() and "saved" in tab.status.text()
    # the line that tells the result is inside the visible window, not below it
    assert tab.status.mapTo(win, tab.status.rect().bottomLeft()).y() < win.height()


def test_run_warns_when_the_software_is_missing(cluster, local, tmp_path, monkeypatch):
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QMessageBox
    from scope.gui.window import MainWindow
    app = QApplication.instance() or QApplication([])
    asked = []
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: (asked.append(a[2]), QMessageBox.No)[1]))
    env, info = local
    win = MainWindow(); win.session.set_environment(env, info); tab = win.remote_tab
    inp = tmp_path / "opt.scope"; inp.write_text(JOB); win.session.add_inputs([str(inp)])
    tab.name.setText("fake"); tab.host.setEditText(cluster.host); tab.scope_bin.setText(cluster.scope_bin); tab.root.setText(cluster.remote_root); tab.env_file.setText(cluster.remote_env); tab.refresh_systems(); tab.system.setCurrentText("water")
    tab.test_connection(); wait(app, tab)                     # the stand-in cluster names no Gaussian module: that light is grey
    assert tab.lights[2].state == "grey"
    tab.run_remote()
    assert asked and "WARNING from the last connection test" in asked[-1] and "opt.scope needs Gaussian 16" in asked[-1]
