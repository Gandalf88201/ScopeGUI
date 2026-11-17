"""The ./scope-gui launcher script (bash). A fake "Python" in the private environment records what the script asks of it, so nothing is downloaded."""
import os, shutil, stat, subprocess, sys
from pathlib import Path
import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scope-gui"
pytestmark = pytest.mark.skipif(sys.platform == "win32" or shutil.which("bash") is None, reason="bash launcher")

FAKE_PYTHON = """#!/bin/bash
case "$*" in
  *version_info*) exit 0 ;;                                  # "is this a Python 3.12?"
  *"import cell2mol"*) exit ${C2M_PRESENT_EXIT:-0} ;;        # "is cell2mol installed?" (default: yes)
  "-m pip install"*"cell2mol @"*) echo "PIP $*" >> "$LOG"; exit ${C2M_EXIT:-0} ;;
  "-m pip"*)      echo "PIP $*" >> "$LOG"; exit ${PIP_EXIT:-0} ;;
  *)              echo "LAUNCH $*" >> "$LOG"; exit 0 ;;
esac
"""

@pytest.fixture
def repo(tmp_path):
    """A copy of the launcher next to a core/pyproject.toml, plus a private environment holding the fake Python."""
    root = tmp_path / "repo"; (root / "core").mkdir(parents=True)
    shutil.copy(SCRIPT, root / "scope-gui"); (root / "core" / "pyproject.toml").write_text("[project]\nname='x'\n")
    home = tmp_path / "home"; py = home / "venv" / "bin" / "python"; py.parent.mkdir(parents=True)
    py.write_text(FAKE_PYTHON); py.chmod(py.stat().st_mode | stat.S_IEXEC)
    return root, home

def run(root, home, *args, log, **env):
    e = {**os.environ, "SCOPE_GUI_HOME": str(home), "LOG": str(log), **env}
    return subprocess.run([str(root / "scope-gui"), *args], capture_output=True, text=True, env=e)

C2M_COMMIT = "55649ba"                                                                         # first 7 characters of the commit pinned in SCOPE's README

def stamp(root) -> str:
    return subprocess.run("cksum < core/pyproject.toml | awk '{print $1 \"-\" $2}'", shell=True, cwd=root, capture_output=True, text=True).stdout.strip() + "-c2m" + C2M_COMMIT

def test_an_up_to_date_environment_is_reused_and_arguments_are_passed_on(repo, tmp_path):
    root, home = repo; log = tmp_path / "log"
    (home / "installed.stamp").write_text(stamp(root) + "\n")
    done = run(root, home, "-n", "/x/env.npy", "--check", log=log)
    assert done.returncode == 0, done.stderr
    lines = log.read_text().splitlines()
    assert len(lines) == 1 and lines[0].startswith("LAUNCH") and "gui -n /x/env.npy --check" in lines[0]        # no pip call: nothing is reinstalled

def test_a_changed_pyproject_triggers_a_reinstall_before_the_launch(repo, tmp_path):
    root, home = repo; log = tmp_path / "log"
    (home / "installed.stamp").write_text("0-0\n")                                              # what a previous pyproject looked like
    done = run(root, home, log=log)
    assert done.returncode == 0 and "changed" in done.stdout
    lines = log.read_text().splitlines()
    assert lines[0].startswith("PIP -m pip install") and "-e" in lines[0] and str(root / "core") + "[gui]" in lines[0] and lines[1].startswith("LAUNCH")
    assert (home / "installed.stamp").read_text().strip() == stamp(root)

def test_reinstall_flag_and_failed_install(repo, tmp_path):
    root, home = repo; log = tmp_path / "log"
    (home / "installed.stamp").write_text(stamp(root) + "\n")
    assert run(root, home, "--reinstall", log=log).returncode == 0 and log.read_text().startswith("PIP")
    log.unlink()
    failed = run(root, home, "--reinstall", log=log, PIP_EXIT="1")
    assert failed.returncode == 1 and "installation failed" in failed.stderr
    assert not (home / "installed.stamp").exists() and "LAUNCH" not in log.read_text()          # not marked as installed, and the GUI is not started half-installed

def test_where_prints_the_environment_and_exits(repo, tmp_path):
    root, home = repo
    done = run(root, home, "--where", log=tmp_path / "log")
    assert done.stdout.strip() == str(home / "venv") and not (tmp_path / "log").exists()

def test_no_python_312_gives_instructions_and_creates_nothing(repo, tmp_path):
    root, _ = repo; fresh = tmp_path / "fresh"
    done = run(root, fresh, "--check", log=tmp_path / "log", SCOPE_GUI_PYTHON=sys.executable if sys.version_info[:2] != (3, 12) else "/usr/bin/false")
    assert done.returncode == 1 and "not a Python 3.12" in done.stderr and not fresh.exists()

def test_works_through_a_symlink_from_another_folder(repo, tmp_path):
    root, home = repo; log = tmp_path / "log"
    (home / "installed.stamp").write_text(stamp(root) + "\n")
    link = tmp_path / "bin" / "scope-gui"; link.parent.mkdir(); link.symlink_to(root / "scope-gui")
    done = subprocess.run([str(link), "--check"], capture_output=True, text=True, cwd="/", env={**os.environ, "SCOPE_GUI_HOME": str(home), "LOG": str(log)})
    assert done.returncode == 0, done.stderr
    assert "gui --check" in log.read_text()

def test_missing_core_folder_is_reported(tmp_path):
    lonely = tmp_path / "scope-gui"; shutil.copy(SCRIPT, lonely)
    done = subprocess.run([str(lonely)], capture_output=True, text=True)
    assert done.returncode == 1 and "core/pyproject.toml" in done.stderr

def test_cell2mol_is_installed_from_the_pinned_commit_when_missing(repo, tmp_path):
    root, home = repo; log = tmp_path / "log"
    (home / "installed.stamp").write_text("0-0\n")
    done = run(root, home, log=log, C2M_PRESENT_EXIT="1")
    assert done.returncode == 0, done.stderr
    pips = [l for l in log.read_text().splitlines() if l.startswith("PIP")]
    assert len(pips) == 2 and "[gui]" in pips[0] and "cell2mol @ git+https://github.com/lcmd-epfl/cell2mol.git@55649ba5f444895846a5d049adcb056c01bb0421" in pips[1]
    assert log.read_text().splitlines()[-1].startswith("LAUNCH")

def test_cell2mol_already_present_is_not_reinstalled(repo, tmp_path):
    root, home = repo; log = tmp_path / "log"
    (home / "installed.stamp").write_text("0-0\n")
    run(root, home, log=log)                                                                   # default: the fake says cell2mol is there
    assert len([l for l in log.read_text().splitlines() if l.startswith("PIP")]) == 1

def test_a_failed_cell2mol_install_warns_but_still_opens_the_gui(repo, tmp_path):
    root, home = repo; log = tmp_path / "log"
    (home / "installed.stamp").write_text("0-0\n")
    done = run(root, home, log=log, C2M_PRESENT_EXIT="1", C2M_EXIT="1")
    assert done.returncode == 0 and "WARNING: cell2mol could not be installed" in done.stderr and "--reinstall" in done.stderr
    assert log.read_text().splitlines()[-1].startswith("LAUNCH") and (home / "installed.stamp").read_text().strip() == stamp(root)

def test_an_environment_made_before_cell2mol_was_added_gets_it_on_the_next_start(repo, tmp_path):
    root, home = repo; log = tmp_path / "log"
    old = stamp(root).rsplit("-c2m", 1)[0]                                                     # the stamp the first launcher version wrote: no cell2mol part
    (home / "installed.stamp").write_text(old + "\n")
    done = run(root, home, log=log, C2M_PRESENT_EXIT="1")
    assert "recipe changed" in done.stdout and any("cell2mol @" in l for l in log.read_text().splitlines())
