"""Regression tests for the problems found by the code review of the GUI (one test, or a few, per problem)."""
import os
import subprocess
import sys
import threading
import time
import pytest

from scope.gui import backend, remote
from test_remote import isolated, cluster, local, WATER                    # noqa: F401  (fixtures)
from test_runs_outlive_window import slow_cluster, until, ready, JOB      # noqa: F401  (fixtures)

def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])

# ---- Remove selected removed the wrong input files
def test_removing_several_selected_inputs_removes_exactly_those(tmp_path):
    qapp(); from PySide6.QtWidgets import QAbstractItemView
    from scope.gui.window import PipelineTab, Session
    s = Session(); tab = PipelineTab(s); paths = []
    for job in ("a", "b", "c", "d"):
        f = tmp_path / f"{job}.scope"; f.write_text(JOB.replace("'opt'", f"'{job}'", 1)); paths.append(str(f))
    s.add_inputs(paths); assert tab.table.rowCount() == 4
    tab.table.setSelectionMode(QAbstractItemView.MultiSelection); tab.table.selectRow(0); tab.table.selectRow(1)
    tab.remove()
    assert [os.path.basename(r.path) for r in s.reports] == ["c.scope", "d.scope"]

# ---- a pid reused by another program was taken for the run
def test_a_reused_pid_is_not_taken_for_the_run_and_is_never_signalled(tmp_path):
    other = subprocess.Popen(["sleep", "60"], start_new_session=True)                       # an unrelated program that happens to hold the run's old pid
    try:
        record = {"id": "x", "pid": other.pid, "log": str(tmp_path / "run_water_1.log"), "kind": "local"}
        open(record["log"], "w").write("partial output, no end marker\n")
        assert backend.run_state(record) == ("lost", None)
        assert backend.stop_run(record) is False and other.poll() is None                  # nothing was sent: it is still running
    finally:
        other.kill(); other.wait()

def test_a_real_run_is_still_recognised_and_can_be_stopped(ready):
    env, info, inp = ready
    slow = inp.replace("opt.scope", "slow.py"); open(slow, "w").write("import time; time.sleep(60)\n")
    original = backend.build_run_command
    try:
        backend.build_run_command = lambda *a, **k: (sys.executable, [slow])                  # a run that takes long, started the normal way
        record = backend.start_detached_local(info.filepath, "water", [inp])
    finally:
        backend.build_run_command = original
    assert until(lambda: backend.run_state(record)[0] == "running", 10)
    assert backend.stop_run(record) is True
    assert until(lambda: backend.run_state(record)[0] != "running", 20)

# ---- runs.json was rewritten without a lock
def test_concurrent_updates_of_the_run_list_lose_nothing():
    code = "import sys\nfrom scope.gui import backend\nfor i in range(25): backend.update_runs(lambda r, i=i: r.append({'id': sys.argv[1] + str(i), 'seen': False}))\n"
    procs = [subprocess.Popen([sys.executable, "-c", code, tag], env=dict(os.environ)) for tag in ("a", "b")]
    for p in procs: assert p.wait(60) == 0
    ids = {r["id"] for r in backend.load_runs()}
    assert {f"a{i}" for i in range(25)} | {f"b{i}" for i in range(25)} <= ids                  # 50 records written by two processes at once, all kept

def test_unseen_records_survive_the_trimming():
    backend.save_runs([{"id": "active", "seen": False}] + [{"id": f"old{i}", "seen": True} for i in range(40)])
    ids = [r["id"] for r in backend.load_runs()]
    assert "active" in ids and len(ids) == 31

# ---- multi-byte characters split between two reads
def test_complete_utf8_keeps_an_unfinished_character_for_later():
    text = "é→ok".encode()
    for cut in range(len(text) + 1):
        n = backend.complete_utf8(text[:cut])
        assert text[:n].decode("utf-8") == text[:n].decode("utf-8", errors="strict")       # never ends inside a character
        assert cut - n < 4
    assert backend.complete_utf8(b"abc") == 3 and backend.complete_utf8(b"") == 0

def test_local_log_reader_does_not_split_a_character(tmp_path):
    log = tmp_path / "run.log"; data = "énergie → ok\n".encode()
    log.write_bytes(data[:2])                                                               # 'é' complete, nothing else
    first, offset = backend.read_log(str(log), 0)
    log.write_bytes(data[:4])                                                               # '→' half written
    second, offset = backend.read_log(str(log), offset)
    log.write_bytes(data)
    third, offset = backend.read_log(str(log), offset)
    assert "�" not in first + second + third and first + second + third == data.decode() and offset == len(data)

def test_remote_poll_counts_bytes_and_survives_undecodable_output():
    raw = b"__SCOPE_GUI_ALIVE__ 1\n__SCOPE_GUI_BEGIN__\n" + "énergie ".encode() + b"\xff\xfe" + "→".encode()[:2]
    d = remote.parse_poll(raw)
    assert d["alive"] and d["bytes"] == len("énergie ".encode()) + 2 and "énergie" in d["text"]       # the half '→' waits for the next poll

def test_run_script_never_raises_on_bytes_that_are_not_utf8(cluster):
    res = remote.run_script(cluster, "printf 'ok \\377\\376\\n'\n")
    assert res.ok and res.stdout.startswith("ok ") and res.raw.startswith(b"ok \xff\xfe")

# ---- one pid-file name for start, follow, stop and list; atomic lock; stop reaches the whole run
def test_unusual_system_names_use_one_set_of_run_files(slow_cluster, tmp_path):
    p = slow_cluster; name = "my mol"
    assert remote.pid_name(name) == "my_mol" and remote.pid_name("2-butène") == "2-but_ne" and remote.pid_name("water") == "water"
    assert remote.run_script(p, remote.remote_dirs_script(p, name)).ok
    started = remote.parse_started(remote.run_script(p, remote.detached_run_script(p, name, [p.remote_root + "/inputs/a.scope"])).stdout)
    assert started["state"] == "started" and "/logs/run_my_mol_" in started["log"]
    poll = remote.parse_poll(remote.run_script(p, remote.poll_script(p, name, started["log"], 0)).raw)
    assert poll["alive"]                                                                    # followed, not reported as ended
    assert [a[0] for a in remote.parse_runs(remote.run_script(p, remote.list_runs_script(p)).stdout)["active"]] == ["my_mol"]
    assert "stopped" in remote.run_script(p, remote.stop_script(p, name)).stdout
    assert until(lambda: remote.parse_poll(remote.run_script(p, remote.poll_script(p, name, started["log"], 0)).raw)["exit"] is not None, 20)

def test_two_starts_at_the_same_moment_give_one_run(slow_cluster):
    p = slow_cluster
    assert remote.run_script(p, remote.remote_dirs_script(p, "water")).ok
    script = remote.detached_run_script(p, "water", [p.remote_root + "/inputs/a.scope"]); answers = []
    threads = [threading.Thread(target=lambda: answers.append(remote.parse_started(remote.run_script(p, script).stdout)["state"])) for _ in range(4)]
    for t in threads: t.start()
    for t in threads: t.join()
    assert sorted(answers) == ["busy", "busy", "busy", "started"]
    remote.run_script(p, remote.stop_script(p, "water"))

def test_stop_ends_the_whole_run_frees_the_lock_and_writes_the_marker(slow_cluster, tmp_path):
    p = slow_cluster
    assert remote.run_script(p, remote.remote_dirs_script(p, "water")).ok
    started = remote.parse_started(remote.run_script(p, remote.detached_run_script(p, "water", [p.remote_root + "/inputs/a.scope"])).stdout)
    assert until(lambda: "slow_scope" in subprocess.run(["ps", "-ww", "-axo", "args="], capture_output=True, text=True).stdout and "run_water_" in subprocess.run(["ps", "-ww", "-axo", "args="], capture_output=True, text=True).stdout, 20)
    assert "stopped" in remote.run_script(p, remote.stop_script(p, "water")).stdout
    d = until(lambda: (lambda d: d if d["exit"] is not None else None)(remote.parse_poll(remote.run_script(p, remote.poll_script(p, "water", started["log"], 0)).raw)), 20)
    assert d and d["exit"] == 143 and not d["alive"]
    assert until(lambda: str(tmp_path / "slow_scope") not in subprocess.run(["ps", "-ww", "-axo", "args="], capture_output=True, text=True).stdout, 20)   # `scope run` itself is gone, not only the wrapper
    again = remote.parse_started(remote.run_script(p, remote.detached_run_script(p, "water", [p.remote_root + "/inputs/a.scope"])).stdout)
    assert again["state"] == "started"                                                      # the lock was freed at once
    remote.run_script(p, remote.stop_script(p, "water"))

def test_a_stale_pid_file_holding_another_programs_pid_blocks_nothing_and_is_never_signalled(slow_cluster):
    p = slow_cluster; logs = os.path.join(p.remote_root, "logs"); os.makedirs(logs, exist_ok=True)
    other = subprocess.Popen(["sleep", "60"], start_new_session=True)
    try:
        open(os.path.join(logs, "run_water.pid"), "w").write(str(other.pid))
        os.makedirs(os.path.join(logs, "run_water.lock")); old = time.time() - 600; os.utime(os.path.join(logs, "run_water.lock"), (old, old))      # left by a run that died hard
        assert "no run" in remote.run_script(p, remote.stop_script(p, "water")).stdout and other.poll() is None
        assert remote.parse_runs(remote.run_script(p, remote.list_runs_script(p)).stdout)["active"] == []
        assert remote.run_script(p, remote.remote_dirs_script(p, "water")).ok
        started = remote.parse_started(remote.run_script(p, remote.detached_run_script(p, "water", [p.remote_root + "/inputs/a.scope"])).stdout)
        assert started["state"] == "started" and other.poll() is None
        remote.run_script(p, remote.stop_script(p, "water"))
    finally:
        other.kill(); other.wait()

def test_a_lock_taken_moments_ago_by_another_start_is_respected(slow_cluster):
    p = slow_cluster; logs = os.path.join(p.remote_root, "logs"); os.makedirs(os.path.join(logs, "run_water.lock"))     # another start is between its mkdir and its pid file
    assert remote.parse_started(remote.run_script(p, remote.detached_run_script(p, "water", [p.remote_root + "/inputs/a.scope"])).stdout) == {"state": "busy", "pid": "starting"}

# ---- inputs with the same file name
def test_inputs_with_the_same_file_name_are_refused(local, tmp_path, monkeypatch):
    assert remote.duplicate_names(["/a/opt.scope", "/b/opt.scope", "/b/freq.scope"]) == ["opt.scope"] and remote.duplicate_names(["/a/x.scope"]) == []
    qapp(); from PySide6.QtWidgets import QMessageBox
    from scope.gui.window import MainWindow
    warned = []; monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: warned.append(a[2]) or QMessageBox.Ok))
    sent = []; monkeypatch.setattr(remote, "run_script", lambda *a, **k: sent.append(a) or remote.Result(0))
    env, info = local; win = MainWindow(); win.session.set_environment(env, info); tab = win.remote_tab
    for folder in ("A", "B"):
        d = tmp_path / folder; d.mkdir(); f = d / "opt.scope"; f.write_text(JOB.replace("'demo'", f"'{folder.lower()}'")); win.session.add_inputs([str(f)])
    tab.name.setText("fake"); tab.host.setEditText("h"); tab.scope_bin.setText("/s"); tab.root.setText("~/p"); tab.env_file.setText("~/p/e.npy"); tab.system.setCurrentText("water")
    tab.upload(preview=True); tab.run_remote()
    assert len(warned) == 2 and "opt.scope" in warned[0] and sent == []                        # nothing reached the cluster

# ---- the Systems folder was scanned once per tab
def test_one_scan_of_the_systems_folder_per_change(local, monkeypatch):
    qapp(); from scope.gui.window import MainWindow
    env, info = local; win = MainWindow(); win.session.set_environment(env, info)
    calls = []; real = backend.list_systems; monkeypatch.setattr(backend, "list_systems", lambda i: calls.append(1) or real(i))
    win.session.systemsChanged.emit()
    assert len(calls) == 1 and win.step_done("systems") and len(calls) == 1
    win.session.inputsChanged.emit(); assert len(calls) == 1                                 # editing inputs does not rescan
