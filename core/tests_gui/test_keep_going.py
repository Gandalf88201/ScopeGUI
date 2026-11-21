"""Keep going until every job is done (requested after a freq job that waited for its opt was never submitted: one `scope run` submits only
the jobs that are ready and ends). The cluster is the fake ssh of test_remote; `scope` and Slurm's `squeue` are scripts."""
import os
import stat
import pytest

from scope.gui import remote
from test_remote import isolated, cluster, local                            # noqa: F401  (fixtures)
from test_runs_outlive_window import until

SCOPE = """#!/bin/bash
# Fake scope: records each call. The first `run` submits a job of 'water' (the queue shows it for COUNT looks); with EVERY, every run does.
D=$(dirname "$0"); echo "$*" >> "$D/calls"
[ "$1" = set_path ] && { echo "set_path ok"; exit 0; }
n=$(grep -c "^run" "$D/calls")
if [ "$n" = 1 ] || [ -f "$D/every" ]; then cat "$D/count" > "$D/countdown"; fi
echo "RUN $n"
"""
SQUEUE = """#!/bin/bash
# Fake Slurm queue (squeue -h -u USER -o "%i|%T|%j|%Z"): jobs of other systems and projects always; one of 'water' while the countdown lasts.
D=__D__
[ -f "$D/queue_error" ] && exit 1
echo "456|PENDING|benzene_demo_opt_r1|__ROOT__/Computations/benzene/demo"
echo "999|RUNNING|water_demo_opt_r1|/elsewhere/other_project/Computations/water/demo"
c=$(cat "$D/countdown" 2>/dev/null || echo 0)
if [ "$c" -gt 0 ]; then echo $((c-1)) > "$D/countdown"; echo "123|RUNNING|water_demo_opt_r1|__ROOT__/Computations/water/demo"; fi
"""

@pytest.fixture
def kg(cluster, tmp_path, monkeypatch):
    """(profile, folder of the fake programs). The water job stays in the queue for 2 looks after the first run."""
    d = tmp_path / "kg"; d.mkdir(); (d / "count").write_text("2\n")
    for name, text in (("scope", SCOPE), ("squeue", SQUEUE.replace("__D__", str(d)).replace("__ROOT__", cluster.remote_root))):
        f = d / name; f.write_text(text); f.chmod(f.stat().st_mode | stat.S_IEXEC)
    for sub in ("water/demo", "benzene/demo"): os.makedirs(os.path.join(cluster.remote_root, "Computations", sub), exist_ok=True)
    monkeypatch.setenv("PATH", f"{d}:{os.environ['PATH']}")
    return remote.Profile(**{**cluster.__dict__, "scope_bin": str(d / "scope")}), d

def start(p, **k) -> str:
    assert remote.run_script(p, remote.remote_dirs_script(p, "water")).ok
    got = remote.parse_started(remote.run_script(p, remote.detached_run_script(p, "water", [p.remote_root + "/inputs/a.scope"], keep_going=True, poll=1, **k)).stdout)
    assert got["state"] == "started"; return got["log"]

def ended(log: str) -> str:
    text = until(lambda: (lambda t: t if remote.EXIT_MARKER_REMOTE in t else None)(read(log)), 60)
    assert text, "the run did not end"; return text

def read(log: str) -> str:
    return open(log).read() if os.path.exists(log) else ""                    ## the detached run creates its log a moment after starting

def calls(d) -> list:
    return [l.split()[0] for l in (d / "calls").read_text().splitlines()]

def test_keep_going_runs_again_when_the_jobs_leave_the_queue_then_stops(kg):
    p, d = kg
    text = ended(start(p, rounds=5))
    assert calls(d) == ["set_path", "run", "run"]                               # set_path once; run 2 reads the job and submits nothing
    assert "Keep going: 1 job(s) of this system in the queue" in text           # benzene and the other project's water job are not counted
    assert "done after 2 run(s)" in text and f"{remote.EXIT_MARKER_REMOTE} 0" in text

def test_keep_going_stops_when_the_queue_cannot_be_read(kg):
    p, d = kg; (d / "queue_error").write_text("")
    text = ended(start(p))
    assert calls(d) == ["set_path", "run"] and "cannot be read" in text and f"{remote.EXIT_MARKER_REMOTE} 0" in text

def test_keep_going_stops_after_the_round_limit(kg):
    p, d = kg; (d / "every").write_text(""); (d / "count").write_text("1\n")    # every run submits a new job
    text = ended(start(p, rounds=2))
    assert calls(d) == ["set_path", "run", "run"] and "2 runs reached" in text

def test_keep_going_without_a_scheduler_is_one_run(kg, monkeypatch):
    p, d = kg; (d / "squeue").unlink()                                          # no squeue, no qstat: SCOPE runs locally, nothing to wait for
    text = ended(start(p))
    assert calls(d) == ["set_path", "run"] and "done after 1 run(s)" in text

def test_stop_ends_the_wait(kg):
    p, d = kg; (d / "count").write_text("100000\n")                             # the job never leaves the queue
    log = start(p)
    assert until(lambda: "looking again" in read(log), 30)
    assert "stopped" in remote.run_script(p, remote.stop_script(p, "water")).stdout
    assert until(lambda: remote.EXIT_MARKER_REMOTE in read(log), 30) and calls(d) == ["set_path", "run"]

def test_without_keep_going_the_script_is_unchanged(cluster):
    plain = remote.run_script_text(cluster, "water", ["/p/inputs/a.scope"])
    assert "scope_gui_queued" not in plain and plain.count(" run -n ") == 1
    assert "scope_gui_queued" in remote.run_script_text(cluster, "water", ["/p/inputs/a.scope"], keep_going=True)

def test_the_cluster_page_offers_it_and_says_so(cluster, local, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication, QMessageBox
    from scope.gui.window import MainWindow
    from test_remote_tab import JOB
    QApplication.instance() or QApplication([])
    asked = []; monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: (asked.append(a[2]), QMessageBox.No)[1]))
    env, info = local
    win = MainWindow(); win.session.set_environment(env, info); tab = win.remote_tab
    inp = tmp_path / "opt.scope"; inp.write_text(JOB); win.session.add_inputs([str(inp)])
    tab.name.setText("fake"); tab.host.setEditText(cluster.host); tab.scope_bin.setText(cluster.scope_bin); tab.root.setText(cluster.remote_root); tab.env_file.setText(cluster.remote_env)
    assert tab.save_profile(); tab.refresh_systems(); tab.system.setCurrentText("water")
    assert not tab.keep_going.isChecked()                                       # off by default: one run, as before
    tab.run_remote(); assert asked and "Keep going" not in asked[-1]
    tab.keep_going.setChecked(True); tab.run_remote(); assert "Keep going until every job is done" in asked[-1]
    win.close()
