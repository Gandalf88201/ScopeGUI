"""The scope-project script (Python, next to scope-gui): a new project folder from a working environment, and the repair of an existing one,
so that the GUI's Folder layout check passes. It runs here with this Python; on a cluster it runs with SCOPE's Python."""
import os
import subprocess
import sys
import pytest

from scope.gui import backend, remote
from scope.read_write import load_binary
from test_remote import isolated                                            # noqa: F401  (fixture: private HOME, fake ssh)

SCRIPT = os.path.join(os.path.dirname(__file__), "..", "..", "scope-project")

def run(*args, env=None):
    done = subprocess.run([sys.executable, SCRIPT, *args, "--python", sys.executable], capture_output=True, text=True, env=env or os.environ.copy(), timeout=120)
    return done.returncode, done.stdout + done.stderr

@pytest.fixture
def template(tmp_path):
    """A working environment, as made once with `scope config` (here a local one with a queue name and modules set)."""
    env, info = backend.create_environment("RUNS", str(tmp_path / "RUNS/Sources"), str(tmp_path / "RUNS/Systems"), str(tmp_path / "RUNS/Computations"), str(tmp_path))
    env.g16_module = "gaussian/16a3"; env.save(info.filepath)
    return info.filepath

def paths(path):
    e = load_binary(path); return e.name, e.sources_path, e.systems_path, e.computations_path

def test_a_new_project_folder_gets_its_own_environment(template, tmp_path):
    job = str(tmp_path / "JOB2")
    code, out = run(job, "--from", template)
    target = os.path.join(job, "scope_env_JOB2.npy")
    assert code == 0, out
    assert paths(target) == ("JOB2", job + "/Sources/", job + "/Systems/", job + "/Computations/") and load_binary(target).g16_module == "gaussian/16a3"
    assert all(os.path.isdir(os.path.join(job, d)) for d in ("Sources", "Systems", "Computations"))
    assert f"Project folder on the cluster:  {job}" in out and f"Cluster environment file:       {target}" in out
    assert paths(template)[0] == "RUNS" and paths(template)[2] == str(tmp_path / "RUNS/Systems") + "/"                # the template is untouched
    assert run(job, "--check", target)[0] == 0
    code, out = run(job, "--from", template); assert code == 1 and "already exists" in out                            # never replaced by accident
    code, out = run(job, "--from", template, "--force"); assert code == 0 and ".bak-" in out
    assert any(n.startswith("scope_env_JOB2.npy.bak-") for n in os.listdir(job))

def test_the_gui_check_passes_for_a_new_project(template, tmp_path):
    job = str(tmp_path / "JOB3"); assert run(job, "--from", template, "--name", "third")[0] == 0
    p = remote.Profile("c", "fakehost", os.path.join(os.path.dirname(sys.executable), "scope"), "", job, os.path.join(job, "scope_env_third.npy"))
    by = {c.name: c for c in remote.evaluate_probe(p, remote.run_script(p, remote.probe_script(p)))}
    assert by["Folder layout"].status == "ok" and by["Cluster environment file"].status == "ok" and "'third'" in by["Cluster environment file"].detail

def test_an_environment_with_all_folders_in_one_is_repaired_safely(template, tmp_path):
    runs = str(tmp_path / "RUNS")
    e = load_binary(template); e.sources_path = e.systems_path = e.computations_path = runs + "/"; e.save(template)      # the layout the cluster had
    p = remote.Profile("c", "fakehost", os.path.join(os.path.dirname(sys.executable), "scope"), "", runs, template)
    by = {c.name: c for c in remote.evaluate_probe(p, remote.run_script(p, remote.probe_script(p)))}
    assert by["Folder layout"].status == "fail" and f"scope-project {runs} --fix {template}" in by["Folder layout"].detail
    code, out = run(runs, "--check", template); assert code == 1 and "should be" in out and "--fix" in out
    os.makedirs(os.path.join(runs, "OLD_SYSTEM"))                                                                        # data under the old layout
    before = open(template, "rb").read()
    code, out = run(runs, "--fix", template); assert code == 1 and "OLD_SYSTEM" in out and "--force" in out and open(template, "rb").read() == before
    code, out = run(runs, "--fix", template, "--dry-run", "--force"); assert code == 0 and "dry run" in out and open(template, "rb").read() == before
    code, out = run(runs, "--fix", template, "--force"); assert code == 0, out
    assert paths(template)[1:] == (runs + "/Sources/", runs + "/Systems/", runs + "/Computations/") and os.path.isdir(os.path.join(runs, "OLD_SYSTEM"))
    assert any(n.startswith("scope_env_RUNS.npy.bak-") for n in os.listdir(str(tmp_path)))
    by = {c.name: c for c in remote.evaluate_probe(p, remote.run_script(p, remote.probe_script(p)))}
    assert by["Folder layout"].status == "ok"
    code, out = run(runs, "--fix", template); assert code == 0 and "already right" in out

def test_helpful_errors(template, tmp_path):
    code, out = run(str(tmp_path / "X")); assert code == 2 and "--from" in out                                         # no mode, no SCOPE_TEMPLATE_ENV
    code, out = run(str(tmp_path / "X"), env=dict(os.environ, SCOPE_TEMPLATE_ENV=template)); assert code == 0 and os.path.isfile(str(tmp_path / "X/scope_env_X.npy"))
    code, out = run(str(tmp_path / "Y"), "--from", str(tmp_path / "missing.npy")); assert code == 1 and "does not exist" in out
    done = subprocess.run([sys.executable, SCRIPT, str(tmp_path / "Z"), "--from", template, "--python", "/usr/bin/false"], capture_output=True, text=True)
    assert done.returncode == 2 and "conda activate" in done.stderr

def test_help_explains_with_examples_even_without_scope():
    for flag in ("--help", "-h"):
        done = subprocess.run(["python3", SCRIPT, flag], capture_output=True, text=True)                                      # a Python without SCOPE can show the help       # no SCOPE needed to read the help
        assert done.returncode == 0 and done.stderr == ""
        for words in ("WHY", "EXAMPLES", "scope-project ~/JOB2 --from ~/scope_env_RUNS.npy", "--fix", "--check", "SCOPE_TEMPLATE_ENV", "SAFETY", ".bak-", "conda activate"): assert words in done.stdout, words
    code, out = run("/tmp/anything"); assert code == 2 and "scope-project --help" in out                                     # mistakes point to the help

def test_a_python_without_scope_restarts_with_the_one_next_to_scope(template, tmp_path):
    """Started by a plain python3 (no SCOPE), the script finds the Python of the `scope` command on the PATH and restarts with it."""
    plain = "/usr/bin/python3"
    if subprocess.run([plain, "-c", "import scope"], capture_output=True).returncode == 0: pytest.skip("this python3 already has SCOPE")
    env = dict(os.environ, PATH=os.path.dirname(sys.executable) + os.pathsep + os.environ["PATH"])
    done = subprocess.run([plain, SCRIPT, str(tmp_path / "W"), "--from", template], capture_output=True, text=True, env=env, timeout=120)
    assert done.returncode == 0, done.stderr and os.path.isfile(str(tmp_path / "W/scope_env_W.npy"))
    done = subprocess.run([plain, SCRIPT, str(tmp_path / "V"), "--from", template], capture_output=True, text=True, env=dict(os.environ, PATH="/usr/bin:/bin"), timeout=120)
    assert done.returncode == 2 and "conda activate" in done.stderr
