"""The private virtual environment that `scope gui` builds by itself when PySide6 is missing (offline: a tiny local wheel stands in for PySide6)."""
import os, subprocess, sys, zipfile
import pytest
from scope.cli import gui_env

def fake_wheel(folder) -> str:
    """Builds fakegui-1.0-py3-none-any.whl by hand (a wheel is a zip), so no network or build tool is needed."""
    path = os.path.join(str(folder), "fakegui-1.0-py3-none-any.whl")
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("fakegui/__init__.py", "VALUE = 42\n")
        z.writestr("fakegui-1.0.dist-info/METADATA", "Metadata-Version: 2.1\nName: fakegui\nVersion: 1.0\n")
        z.writestr("fakegui-1.0.dist-info/WHEEL", "Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: py3-none-any\n")
        z.writestr("fakegui-1.0.dist-info/RECORD", "fakegui/__init__.py,,\nfakegui-1.0.dist-info/METADATA,,\nfakegui-1.0.dist-info/WHEEL,,\nfakegui-1.0.dist-info/RECORD,,\n")
    return path

@pytest.fixture
def private(tmp_path, monkeypatch):
    target = tmp_path / "data" / "gui-env"
    monkeypatch.setenv("SCOPE_GUI_ENV_DIR", str(target))
    monkeypatch.delenv(gui_env.LOOP_GUARD, raising=False); monkeypatch.delenv("SCOPE_GUI_NO_ENV", raising=False)
    return target

def test_build_makes_an_environment_that_sees_scope_and_the_new_package(private, tmp_path):
    messages = []
    py = gui_env.build(requirement=fake_wheel(tmp_path), log=messages.append)
    assert py == gui_env.venv_python(str(private)) and os.path.isfile(py) and gui_env.is_ready()
    done = subprocess.run([py, "-c", "import fakegui, scope, sys; print(fakegui.VALUE, sys.prefix)"], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert done.stdout.split()[0] == "42" and os.path.realpath(done.stdout.split()[1]) == os.path.realpath(str(private))      # running in the private environment, SCOPE found through the .pth
    assert any("ready" in m for m in messages)
    assert subprocess.run([sys.executable, "-c", "import fakegui"], capture_output=True).returncode != 0                      # nothing leaked into the user's own environment

def test_an_existing_environment_is_reused_and_a_changed_interpreter_rebuilds_it(private, tmp_path, monkeypatch):
    wheel = fake_wheel(tmp_path)
    gui_env.build(requirement=wheel, log=lambda m: None)
    marker = private / gui_env.MARKER; first = marker.stat().st_mtime_ns
    gui_env.build(requirement=wheel, log=lambda m: None)
    assert marker.stat().st_mtime_ns == first                                                # second start: nothing is built
    real = gui_env.fingerprint()
    monkeypatch.setattr(gui_env, "fingerprint", lambda: {**real, "prefix": "/somewhere/else"})
    assert not gui_env.is_ready()                                                            # SCOPE moved to another interpreter
    gui_env.build(requirement=wheel, log=lambda m: None)
    assert gui_env.is_ready() and marker.stat().st_mtime_ns != first

def test_a_failed_install_leaves_nothing_behind(private, tmp_path):
    with pytest.raises(RuntimeError, match="Could not install"):
        gui_env.build(requirement=str(tmp_path / "missing-1.0-py3-none-any.whl"), log=lambda m: None)
    assert not private.exists() and not gui_env.is_ready()

def test_a_folder_that_is_not_ours_is_never_deleted(private):
    private.mkdir(parents=True); (private / "thesis.txt").write_text("keep me")
    with pytest.raises(RuntimeError, match="not a SCOPE GUI environment"):
        gui_env.remove(str(private))
    with pytest.raises(RuntimeError): gui_env.build(requirement="x", log=lambda m: None)
    assert (private / "thesis.txt").read_text() == "keep me"

def test_a_half_built_environment_is_replaced(private, tmp_path):
    subprocess.run([sys.executable, "-m", "venv", str(private)], check=True)                  # a build that died before the marker
    assert not gui_env.is_ready()
    py = gui_env.build(requirement=fake_wheel(tmp_path), log=lambda m: None)
    assert gui_env.is_ready() and os.path.isfile(py)

def test_the_gui_can_start_a_run_from_the_private_environment(private, tmp_path):
    from scope.gui import backend
    py = gui_env.build(requirement=fake_wheel(tmp_path), log=lambda m: None)
    info = backend.detect_local_scope(python=py)
    assert info.runs_ok and info.python_ok and info.scope_version                              # a `scope run` child of the private Python imports SCOPE

def test_loop_guard_and_opt_out_stop_the_bootstrap(private, monkeypatch):
    messages = []
    monkeypatch.setenv(gui_env.LOOP_GUARD, "1")
    assert gui_env.ensure_gui_python(["gui"], log=messages.append) == 1 and "still cannot" in messages[-1]
    monkeypatch.delenv(gui_env.LOOP_GUARD); monkeypatch.setenv("SCOPE_GUI_NO_ENV", "1")
    assert gui_env.ensure_gui_python(["gui"], log=messages.append) == 1 and "SCOPE_GUI_NO_ENV" in messages[-1] and not private.exists()

def test_scope_gui_without_pyside6_builds_then_restarts_inside_the_environment(private, tmp_path, monkeypatch):
    from scope.cli.gui import gui
    import argparse
    seen = {}
    monkeypatch.setattr(gui_env, "pyside_available", lambda: False)
    monkeypatch.setattr(gui_env, "build", lambda log=print: "/fake/private/python")
    monkeypatch.setattr(gui_env, "relaunch", lambda py, argv: seen.update(py=py, argv=argv) or 0)
    with pytest.raises(SystemExit) as stop:
        gui(argparse.Namespace(env_path="/x/env.npy", reset_env=False, check=True))
    assert stop.value.code == 0 and seen == {"py": "/fake/private/python", "argv": ["gui", "-n", "/x/env.npy", "--check"]}

def test_reset_env_removes_our_environment_and_refuses_a_foreign_folder(private, tmp_path, monkeypatch):
    from scope.cli.gui import gui
    import argparse
    monkeypatch.setattr(gui_env, "pyside_available", lambda: False)
    monkeypatch.setattr(gui_env, "ensure_gui_python", lambda argv, log=print: 0)             # only the reset is under test
    gui_env.build(requirement=fake_wheel(tmp_path), log=lambda m: None)
    with pytest.raises(SystemExit): gui(argparse.Namespace(env_path=None, reset_env=True, check=False))
    assert not private.exists()
    private.mkdir(parents=True); (private / "mine.txt").write_text("keep")
    with pytest.raises(SystemExit) as stop: gui(argparse.Namespace(env_path=None, reset_env=True, check=False))
    assert stop.value.code == 1 and (private / "mine.txt").exists()
