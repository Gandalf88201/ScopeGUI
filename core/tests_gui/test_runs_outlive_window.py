"""A run must not depend on the window: crash, Ctrl-C in the Terminal that started the GUI, closing the window, a dropped connection."""
import json
import os
import signal
import stat
import subprocess
import sys
import time
import pytest

from scope.gui import backend, remote
from test_remote import isolated, cluster, local, WATER                    # noqa: F401  (fixtures)

JOB = "&environment\n   requested_procs = 2\n/\n&options\n   want_submit = False\n/\n&job_data\n   branch = 'demo'\n   workflow = '*'\n   job = 'opt'\n   hierarchy = 1\n   requisites = []\n   constrains = ['self']\n/\n&qc_data\n   software = 'g16'\n   comp_type = 'opt'\n/\n"

def until(fn, seconds=90):
    t0 = time.time()
    while time.time() - t0 < seconds:
        value = fn()
        if value: return value
        time.sleep(0.1)
    return None

@pytest.fixture
def ready(local, tmp_path):
    env, info = local
    inp = tmp_path / "opt.scope"; inp.write_text(JOB)
    return env, info, str(inp)

PARENT = """
import json, os, signal, sys, time
from scope.gui import backend
rec = backend.start_detached_local(sys.argv[1], sys.argv[2], [sys.argv[3]])
print(json.dumps(rec), flush=True)
if sys.argv[4] == "kill9": os.kill(os.getpid(), signal.SIGKILL)
time.sleep(60)
"""

def start_parent(info, inp, how, new_session):
    p = subprocess.Popen([sys.executable, "-c", PARENT, info.filepath, "water", inp, how], stdout=subprocess.PIPE, text=True, start_new_session=new_session)
    return p, json.loads(p.stdout.readline())

# ---- local runs
def test_local_run_finishes_by_itself_and_leaves_a_log(ready):
    env, info, inp = ready
    rec = backend.start_detached_local(info.filepath, "water", [inp])
    state = until(lambda: backend.run_state(rec) if backend.run_state(rec)[0] != "running" else None)
    assert state == ("finished", 0)
    text, offset = backend.read_log(rec["log"])
    assert "MANUAL ATTENTION" in text and backend.EXIT_MARKER not in text and offset > 0
    assert os.path.isdir(os.path.join(info.computations_path, "water", "demo"))

def test_run_survives_a_crash_of_the_window(ready):
    env, info, inp = ready
    parent, rec = start_parent(info, inp, "kill9", new_session=False)         # the window is killed right after starting the run
    parent.wait(timeout=20); assert parent.returncode == -signal.SIGKILL
    assert until(lambda: backend.run_state(rec)[0] != "running") and backend.run_state(rec) == ("finished", 0)
    assert "MANUAL ATTENTION" in backend.read_log(rec["log"])[0]

def test_run_survives_ctrl_c_sent_to_the_whole_process_group(ready):
    env, info, inp = ready
    parent, rec = start_parent(info, inp, "wait", new_session=True)           # the parent leads its own group, like a Terminal's foreground job
    os.killpg(parent.pid, signal.SIGINT); parent.wait(timeout=20)
    assert parent.returncode != 0
    assert until(lambda: backend.run_state(rec)[0] != "running") and backend.run_state(rec) == ("finished", 0)

def test_stop_ends_a_run_and_it_is_reported_honestly(ready):
    env, info, inp = ready
    rec = backend.start_detached_local(info.filepath, "water", [inp])
    assert backend.stop_run(rec) or backend.run_state(rec)[0] == "finished"
    state = until(lambda: backend.run_state(rec) if backend.run_state(rec)[0] != "running" else None)
    assert state[0] in ("lost", "finished")                                    # stopped before the end marker, or it was already done

def test_window_finds_a_run_again_after_being_reopened(ready):
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from scope.gui.window import MainWindow
    app = QApplication.instance() or QApplication([])
    env, info, inp = ready
    rec = backend.start_detached_local(info.filepath, "water", [inp])           # started by a window that no longer exists
    win = MainWindow(); win.session.set_environment(env, info); win.run_tab.reattach()
    assert "Found again" in win.run_tab.log.toPlainText()
    t0 = time.time()
    while win.run_tab.running() and time.time() - t0 < 90: app.processEvents(); time.sleep(0.05)
    app.processEvents()
    assert "exit code 0" in win.run_tab.status.text() and "MANUAL ATTENTION" in win.run_tab.log.toPlainText()
    assert backend.load_runs()[-1]["seen"] is True
    again = MainWindow(); again.run_tab.reattach(); assert again.run_tab.record is None             # a run already shown is not shown again

def test_closing_the_window_keeps_the_run_unless_told_to_stop(ready, monkeypatch):
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QCloseEvent
    from scope.gui.window import MainWindow
    app = QApplication.instance() or QApplication([])
    env, info, inp = ready
    win = MainWindow(); win.session.set_environment(env, info); win.run_tab.attach(backend.start_detached_local(info.filepath, "water", [inp]))
    assert win.run_tab.running()
    win.close_choice = lambda: "cancel"; ev = QCloseEvent(); win.closeEvent(ev); assert not ev.isAccepted()
    win.close_choice = lambda: "keep"; ev = QCloseEvent(); win.closeEvent(ev); assert ev.isAccepted()
    assert until(lambda: backend.run_state(win.run_tab.record)[0] != "running") and backend.run_state(win.run_tab.record)[0] == "finished"       # still ran to the end

# ---- runs on the cluster
@pytest.fixture
def slow_cluster(cluster, tmp_path):
    """The stand-in cluster whose `scope` is a script: set_path answers at once, run waits until the test creates the file `go` next to the script (so timing never decides a test), at most 60 s."""
    stub = tmp_path / "slow_scope"
    stub.write_text('#!/bin/bash\nif [ "$1" = set_path ]; then echo "set_path ok"; exit 0; fi\ni=0; while [ ! -f "$(dirname "$0")/go" ] && [ $i -lt 600 ]; do sleep 0.1; i=$((i+1)); done\necho "RUN DONE $*"\necho "MANUAL ATTENTION REQUIRED"\n'); stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    return remote.Profile(**{**cluster.__dict__, "scope_bin": str(stub)})

def test_parsers():
    assert remote.parse_started("x\n__SCOPE_GUI_STARTED__ 123 /p/logs/run_a_1.log\n") == {"state": "started", "pid": "123", "log": "/p/logs/run_a_1.log"}
    assert remote.parse_started("__SCOPE_GUI_BUSY__ 77\n") == {"state": "busy", "pid": "77"} and remote.parse_started("nothing") == {}
    d = remote.parse_poll("__SCOPE_GUI_SIZE__ 40\n__SCOPE_GUI_ALIVE__ 0\n__SCOPE_GUI_BEGIN__\nhello\n__SCOPE_GUI_EXIT__ 0\n")
    assert d == {"alive": False, "text": "hello\n", "bytes": len("hello\n__SCOPE_GUI_EXIT__ 0\n"), "exit": 0}
    assert remote.parse_runs("__SCOPE_GUI_RUN__ water 5 1 /l/a.log\n__SCOPE_GUI_RUN__ old 6 0 /l/b.log\n__SCOPE_GUI_LOG__ /l/a.log\n") == {"active": [("water", "5", "/l/a.log")], "logs": ["/l/a.log"], "last": {}, "scheduler": None, "jobs": [], "root_real": "", "unread": {}}

def test_cluster_run_goes_on_without_the_window_and_blocks_a_second_run(slow_cluster, tmp_path):
    p = slow_cluster
    assert remote.run_script(p, remote.remote_dirs_script(p, "water")).ok
    started = remote.parse_started(remote.run_script(p, remote.detached_run_script(p, "water", [p.remote_root + "/inputs/a.scope"])).stdout)
    go = tmp_path / "go"
    assert started["state"] == "started"                                         # the call returned while the run is still going: nothing holds the connection open
    busy = remote.parse_started(remote.run_script(p, remote.detached_run_script(p, "water", [p.remote_root + "/inputs/a.scope"])).stdout)
    assert busy["state"] == "busy" and busy["pid"] == started["pid"]
    found = remote.parse_runs(remote.run_script(p, remote.list_runs_script(p)).stdout)
    assert [a[0] for a in found["active"]] == ["water"]
    # the window "comes back" later and only reads
    go.write_text("go")
    def finished():
        d = remote.parse_poll(remote.run_script(p, remote.poll_script(p, "water", started["log"], 0)).stdout)
        return d if d["exit"] is not None else None
    d = until(finished, 60)
    assert d and d["exit"] == 0 and "RUN DONE" in d["text"] and "MANUAL ATTENTION" in d["text"] and "set_path ok" in d["text"]
    assert remote.parse_runs(remote.run_script(p, remote.list_runs_script(p)).stdout)["active"] == []        # the pid file is gone
    again = remote.parse_started(remote.run_script(p, remote.detached_run_script(p, "water", [p.remote_root + "/inputs/a.scope"])).stdout)
    assert again["state"] == "started"                                           # and a new run can start

def test_cluster_run_can_be_stopped(slow_cluster):
    p = slow_cluster
    assert remote.run_script(p, remote.remote_dirs_script(p, "water")).ok
    started = remote.parse_started(remote.run_script(p, remote.detached_run_script(p, "water", [p.remote_root + "/inputs/a.scope"])).stdout)
    assert "stopped" in remote.run_script(p, remote.stop_script(p, "water")).stdout
    alive = until(lambda: not remote.parse_poll(remote.run_script(p, remote.poll_script(p, "water", started["log"], 0)).stdout)["alive"], 20)
    assert alive

def test_cluster_page_finds_and_follows_a_run_started_earlier(slow_cluster, local, tmp_path, monkeypatch):
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QMessageBox
    from scope.gui.window import MainWindow
    app = QApplication.instance() or QApplication([])
    p = slow_cluster
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes))
    assert remote.run_script(p, remote.remote_dirs_script(p, "water")).ok
    remote.run_script(p, remote.detached_run_script(p, "water", [p.remote_root + "/inputs/a.scope"]))        # started by a window that is gone
    env, info = local
    win = MainWindow(); win.session.set_environment(env, info); tab = win.remote_tab; tab.poll_ms = 100
    tab.name.setText("fake"); tab.host.setEditText(p.host); tab.scope_bin.setText(p.scope_bin); tab.root.setText(p.remote_root); tab.env_file.setText(p.remote_env); tab.refresh_systems(); tab.system.setCurrentText("water")
    tab.watch_runs()
    t0 = time.time()
    while "Following the active run" not in tab.log.toPlainText() and time.time() - t0 < 60: app.processEvents(); time.sleep(0.03)
    (tmp_path / "go").write_text("go")                                               # now let the run finish
    while (tab.busy or tab.running()) and time.time() - t0 < 90: app.processEvents(); time.sleep(0.03)
    app.processEvents()
    assert "Following the active run of 'water'" in tab.log.toPlainText() and "MANUAL ATTENTION" in tab.log.toPlainText() and "exit code 0" in tab.status.text()
    assert win.step_done("run")
