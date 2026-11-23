"""A GUI run that submits nothing must not look like a success (SCOPE_GUI_fix_report, 2026-11-22). Three defects together:
A: queue 'std' also selected res_std, whose alias had become 'std', and res_std is not in the user's Slurm associations;
B: no #SBATCH --time when the partition has MaxTime=UNLIMITED and no DefaultTime (the cluster then refuses the job);
C: the sbatch failure was ignored, `scope run` exited 0 and the Cluster page said 'done'.
The cluster is the fake ssh of test_remote; `scope` and `squeue` are scripts."""
import argparse
import os
import stat
import subprocess
from types import SimpleNamespace

import pytest

from scope.classes_environment import Environment, match_queue
from scope.classes_queue import Queue
from scope.classes_workflow import Computation, SubmissionError
from scope.gui import remote
from test_remote import isolated, cluster                                   # noqa: F401  (fixtures)
from test_runs_outlive_window import until

############################
### A: exact queue names ###
############################
def slurm_env() -> Environment:
    env = Environment("t"); env.scheduler = "slurm"; return env

def stale_queues(env):
    """The queues as `scope config` had saved them: std kept sinfo's '*' as alias, res_std got the alias 'std' from the fuzzy prompt."""
    std, res_std, fat = Queue("std*", env, time_limit="infinite"), Queue("res_std", env), Queue("fat", env)
    std.alter_name, res_std.alter_name = "std*", "std"
    return std, res_std, fat

def test_a_queue_name_selects_only_that_queue_even_when_another_has_it_as_alias():
    env = slurm_env(); std, res_std, fat = stale_queues(env)
    env.available_queues = [res_std, std, fat]                              # res_std first: the alias must not win over the name
    env.read_user_queue_list("std")
    assert env.selected_queues == [std]
    env.mqueues = [res_std, std, fat]
    assert env.find_queue("std") == (True, std) and env.find_queue("fat") == (True, fat) and env.find_queue("gpu") == (False, None)

def test_an_alias_is_still_found_when_no_queue_has_that_name():
    env = slurm_env(); std, res_std, fat = stale_queues(env); fat.alter_name = "big"
    assert match_queue([std, res_std, fat], "big") is fat and match_queue([std, fat], "") is None

def test_new_queues_drop_the_default_partition_marker_from_their_alias():
    q = Queue("std*", slurm_env())
    assert (q.name, q.alter_name) == ("std", "std")

def test_a_similar_name_is_selected_without_renaming_it(monkeypatch):
    env = slurm_env(); fat = Queue("fat", env); env.available_queues = [fat]
    monkeypatch.setattr("scope.classes_environment.interactive", lambda: True)
    monkeypatch.setattr("scope.classes_environment.read_user_input", lambda **k: "y")
    env.read_user_queue_list("fa")
    assert env.selected_queues == [fat] and fat.alter_name == "fat"         # 'fa' would otherwise match fat from now on

def test_a_similar_name_in_a_run_without_terminal_selects_nothing_and_does_not_ask(monkeypatch, capsys):
    env = slurm_env(); fat = Queue("fat", env); env.available_queues = [fat]
    monkeypatch.setattr("scope.classes_environment.interactive", lambda: False)
    monkeypatch.setattr("scope.classes_environment.read_user_input", lambda **k: pytest.fail("asked without a terminal"))
    env.read_user_queue_list("fa")
    assert env.selected_queues == [] and "similar one is 'fat'" in capsys.readouterr().out

def test_slurm_partitions_of_the_account(monkeypatch):
    from scope import classes_environment as ce
    def fake(out, code=0): return lambda *a, **k: subprocess.CompletedProcess(a, code, out, "")
    monkeypatch.setattr(ce.subprocess, "run", fake("express\nfat\ngpu\nstd\n"))
    assert ce.slurm_user_partitions(SimpleNamespace(user="u")) == {"express", "fat", "gpu", "std"}
    monkeypatch.setattr(ce.subprocess, "run", fake("\nstd\n"))           # an association without partition allows every partition
    assert ce.slurm_user_partitions(SimpleNamespace(user="u")) is None
    monkeypatch.setattr(ce.subprocess, "run", fake("", 1))
    assert ce.slurm_user_partitions(SimpleNamespace(user="u")) is None

######################
### B: a wall time ###
######################
def write_g16_subfile(tmp_path, env, queue) -> str:
    from scope.software.gaussian.g16_input import gen_g16_subfile
    comp = SimpleNamespace(name="water_opt", path=str(tmp_path), sub_path=str(tmp_path / "water_opt.sub"), inp_name="water_opt.com", out_name="water_opt.log")
    gen_g16_subfile(comp, queue=queue, module="g16")
    return (tmp_path / "water_opt.sub").read_text()

def unlimited(env) -> Queue:
    return Queue("std", env, time_limit="infinite")                                                 # MaxTime=UNLIMITED, DefaultTime=NONE

def test_an_unlimited_partition_without_default_gets_the_fallback_wall_time(tmp_path):
    env = slurm_env(); env.time_limit = None; env.fallback_time_limit = 1440
    assert "#SBATCH --time=1-00:00:00" in write_g16_subfile(tmp_path, env, unlimited(env))

def test_wall_time_order_input_then_queue_default_then_fallback_then_30_days(tmp_path):
    from scope.classes_queue import get_submission_time_limit
    env = slurm_env(); env.time_limit = None; q = unlimited(env)
    assert get_submission_time_limit(q) == 30 * 24 * 60                                             # nothing set: SCOPE's own default
    env.fallback_time_limit = 1440; assert get_submission_time_limit(q) == 1440
    q.default_time_limit = 60;      assert get_submission_time_limit(q) == 60
    env.time_limit = 120;           assert "#SBATCH --time=02:00:00" in write_g16_subfile(tmp_path, env, q)
    finite = Queue("short", env, time_limit="4320"); finite.time_limit = 4320; env.time_limit = None
    assert get_submission_time_limit(finite) == 4320                                                # a finite maximum wins over the fallback

def test_the_quantum_espresso_job_file_uses_the_same_fallback(tmp_path, monkeypatch):
    from scope.software.quantum_espresso import qe_input
    monkeypatch.setattr(qe_input, "gen_qe_wf_blocks", lambda comp, debug=0: ("", ""))     ## wave-function storage needs a full computation
    env = slurm_env(); env.time_limit = None; env.fallback_time_limit = 1440
    comp = SimpleNamespace(name="w", path=str(tmp_path), sub_path=str(tmp_path / "w.sub"), inp_name="w.in", out_name="w.out")
    qe_input.gen_qe_subfile(comp, queue=unlimited(env), module="qe")
    assert "#SBATCH --time=1-00:00:00" in (tmp_path / "w.sub").read_text()

##################################
### C: a refused job is loud ###
##################################
def bare_computation(tmp_path) -> Computation:
    comp = Computation.__new__(Computation); comp.path = str(tmp_path); comp.sub_name = "water_opt.sub"; return comp

def test_a_refused_submission_raises_with_the_scheduler_message_and_keeps_the_folder(tmp_path):
    env = SimpleNamespace(commands={"submit": "echo 'sbatch: error: Batch job submission failed: Invalid account or account/partition combination specified' >&2; exit 1; :"})
    before = os.getcwd(); (tmp_path / "water_opt.sub").write_text("#SBATCH -p res_std\n")
    with pytest.raises(SubmissionError) as err: bare_computation(tmp_path).submit(env)
    assert "Invalid account or account/partition combination" in err.value.reason and os.getcwd() == before
    assert not (tmp_path / "water_opt.sub").exists() and (tmp_path / "water_opt.sub.refused").exists()   # the next run writes a new job file

def test_an_accepted_submission_prints_the_scheduler_answer(tmp_path, capsys):
    comp = bare_computation(tmp_path)
    comp.submit(SimpleNamespace(commands={"submit": "echo Submitted batch job 42; :"}))
    assert "Submitted batch job 42" in capsys.readouterr().out and comp.submit_failed is False

def test_run_task_reports_a_refused_job_and_the_states_it_would_have_written():
    import importlib
    rt = importlib.import_module("scope.utils.run_task")                    ## the module: scope.utils exports the function under that name
    class Refused:
        out_path, qc_data = "/p/Computations/water/demo/water_opt.log", SimpleNamespace(fstate="opt")
        def run(self, *a, **k): raise SubmissionError("COMPUTATION.SUBMIT: failed", "sbatch: error: Batch job submission failed:\nTime limit specification required")
    failures, states = [], set()
    line = rt._submit(Refused(), None, None, failures, states)
    assert line.startswith("Submission failed for /p/Computations/water/demo/water_opt.log: sbatch: error") and "; Time limit" in line
    assert states == {"opt"} and len(failures) == 1
    assert isinstance(rt.RunReport("x", failures), str) and rt.RunReport("x", failures).submission_failures == failures

def test_scope_run_exits_non_zero_when_a_job_was_refused(monkeypatch, capsys):
    from scope.cli import run as cli_run, main as cli_main
    from scope.utils.run_task import RunReport
    monkeypatch.setattr(cli_run, "clear_screen", lambda: None)
    monkeypatch.setattr(cli_run, "load_binary", lambda path: SimpleNamespace(systems_path="/p/Systems/"))
    args = SimpleNamespace(quiet=True, verbose=False, errors=False, inp_path=["a.scope"], env_path="e.npy", sys_name="water")
    monkeypatch.setattr(cli_run, "run_task", lambda *a, **k: RunReport("Submission failed for x.log: refused\n", [("x.log", "refused")]))
    assert cli_run.run(args) == cli_run.EXIT_SUBMISSION_FAILED == 4
    assert "Submission failed for x.log" in capsys.readouterr().out
    monkeypatch.setattr(cli_run, "run_task", lambda *a, **k: RunReport(""))
    assert cli_run.run(args) == 0
    monkeypatch.setattr(argparse.ArgumentParser, "parse_args", lambda self: argparse.Namespace(func=lambda a: 4))
    assert cli_main.main() == 4                                             ## the console script does sys.exit(main())
    monkeypatch.setattr(argparse.ArgumentParser, "parse_args", lambda self: argparse.Namespace(func=lambda a: None))
    assert cli_main.main() == 0

#############################
### C: the run script ###
#############################
SCOPE = """#!/bin/bash
# Fake scope. Files in its folder choose what `run` does: 'refuse' prints sbatch's refusal (exit 0, as SCOPE before the fix),
# 'exit4' exits 4 (SCOPE with the fix), 'submit' prints sbatch's acceptance.
D=$(dirname "$0"); echo "$*" >> "$D/calls"
[ "$1" = set_path ] && { echo "set_path ok"; exit 0; }
if [ -f "$D/refuse" ]; then echo "sbatch: error: Batch job submission failed: Invalid account or account/partition combination specified"; fi
echo "### MANUAL ATTENTION REQUIRED ###"
echo "#################################"
if [ -f "$D/refuse" ] || [ -f "$D/exit4" ]; then echo "Submission failed for /p/water_opt.log: sbatch: error: Batch job submission failed"
else echo "Retry pending for /p/water_freq_r1.log: initial state 'opt' is missing or lacks geometry."; fi
echo "#################################"
[ -f "$D/submit" ] && echo "Submitted batch job 77"
[ -f "$D/exit4" ] && exit 4
exit 0
"""
SQUEUE = """#!/bin/bash
exit 0
"""

@pytest.fixture
def fake(cluster, tmp_path, monkeypatch):
    d = tmp_path / "fake"; d.mkdir()
    for name, text in (("scope", SCOPE), ("squeue", SQUEUE)):
        f = d / name; f.write_text(text); f.chmod(f.stat().st_mode | stat.S_IEXEC)
    os.makedirs(os.path.join(cluster.remote_root, "Computations", "water"), exist_ok=True)
    monkeypatch.setenv("PATH", f"{d}:{os.environ['PATH']}")
    return remote.Profile(**{**cluster.__dict__, "scope_bin": str(d / "scope")}), d

def run_to_end(p, keep_going: bool) -> str:
    assert remote.run_script(p, remote.remote_dirs_script(p, "water")).ok
    got = remote.parse_started(remote.run_script(p, remote.detached_run_script(p, "water", [p.remote_root + "/inputs/a.scope"], keep_going=keep_going, poll=1)).stdout)
    assert got["state"] == "started"
    text = until(lambda: (lambda t: t if remote.EXIT_MARKER_REMOTE in t else None)(open(got["log"]).read() if os.path.exists(got["log"]) else ""), 60)
    assert text, "the run did not end"; return text

def calls(d) -> list:
    return [l.split()[0] for l in (d / "calls").read_text().splitlines()]

@pytest.mark.parametrize("keep_going", [True, False])
def test_a_refusal_printed_by_an_older_scope_ends_the_run_with_exit_4(fake, keep_going):
    p, d = fake; (d / "refuse").write_text("")
    text = run_to_end(p, keep_going)
    assert f"{remote.EXIT_MARKER_REMOTE} {remote.EXIT_REFUSED}" in text and "done after" not in text
    assert f"{remote.RUN_NOTE} the scheduler refused job(s)" in text and calls(d) == ["set_path", "run"]
    assert remote.refused_lines(text)[0].startswith("sbatch: error: Batch job submission failed: Invalid account")

def test_scope_runs_own_exit_code_ends_the_keep_going_loop(fake):
    p, d = fake; (d / "exit4").write_text("")
    text = run_to_end(p, True)
    assert f"{remote.EXIT_MARKER_REMOTE} 4" in text and "scope run ended with exit code 4" in text and "done after" not in text

def test_keep_going_says_when_no_job_was_submitted_at_all(fake):
    p, d = fake
    text = run_to_end(p, True)
    assert "no job was submitted: done after 1 run(s)" in text and "MANUAL ATTENTION block above" in text and f"{remote.EXIT_MARKER_REMOTE} 0" in text

def test_keep_going_done_as_before_when_jobs_were_submitted(fake):
    p, d = fake; (d / "submit").write_text("")
    text = run_to_end(p, True)
    assert "no job of this system is left in the queue: done after 1 run(s)." in text

def test_manual_attention_block_is_read_from_the_log():
    log = "x\n### MANUAL ATTENTION REQUIRED ###\n#####\nRetry pending for a.log: initial state 'opt' is missing.\nSubmission failed for b.log: refused\n#####\nafter\n"
    assert remote.manual_attention(log) == "Retry pending for a.log: initial state 'opt' is missing.\nSubmission failed for b.log: refused"
    assert remote.manual_attention("### MANUAL ATTENTION REQUIRED ###\n###\nNo manual action required\n###\n") == ""
    assert remote.manual_attention("no block") == ""

def test_the_cluster_page_says_the_jobs_were_refused_and_shows_the_attention_block(cluster):
    from PySide6.QtWidgets import QApplication
    from scope.gui.window import MainWindow
    QApplication.instance() or QApplication([])
    win = MainWindow(); tab = win.remote_tab
    log = ("### MANUAL ATTENTION REQUIRED ###\n####\nSubmission failed for /p/water_opt.log: sbatch: error: Batch job submission failed: Invalid account\n"
           "Blocked: /p/water_freq_r1.log starts from state 'opt', whose job could not be submitted (see 'Submission failed' above).\n####\n")
    body = f"{log}{remote.EXIT_MARKER_REMOTE} {remote.EXIT_REFUSED}\n"
    raw = (f"{remote.SIZE} {len(body)}\n{remote.ALIVE} 0\n{remote.BEGIN}\n" + body).encode()
    w = {"profile": cluster, "system": "water", "log": "/p/logs/run_water.log", "offset": 0, "polling": True, "text": ""}
    tab.watching = w; tab.polled(w, remote.Result(0, raw.decode(), "", raw))
    status, shown = tab.status.text(), tab.log.toPlainText()
    assert "refused" in status and "Invalid account" in status and tab.status.property("kind") == "err"
    assert "SCOPE needs your attention" in shown and "Blocked: /p/water_freq_r1.log" in shown
    win.close()

def test_the_runs_page_names_the_refusal():
    from scope.gui import runs_page
    assert runs_page.ended_text(remote.EXIT_REFUSED) == "jobs refused by the scheduler (exit 4)" and runs_page.ended_text(0) == "finished (exit 0)"
