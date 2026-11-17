"""Private virtual environment for the graphical interface (no Qt, standard library only).

`scope gui` needs PySide6, which is large and optional. When it is missing, instead of asking the user to build a
virtual environment, the launcher builds one by itself, once, in the user data folder of SCOPE, installs PySide6
there and starts the GUI from it. The environment sees SCOPE and its dependencies through a .pth file that adds
the site-packages of the interpreter SCOPE is installed in (so SCOPE is not installed twice, and a development
install keeps working). The environment is rebuilt only when the interpreter it was made from changes or disappears.
"""
import json, os, shutil, site, subprocess, sys, sysconfig
from importlib.util import find_spec

REQUIREMENT = "PySide6-Essentials>=6.6"
MARKER      = "scope_gui_env.json"            ## written last: its absence means the build did not finish (and that the folder is not ours to delete)
LOOP_GUARD  = "SCOPE_GUI_IN_PRIVATE_ENV"      ## set when the GUI is started from the private environment, so a failure cannot start another build

def env_dir() -> str:
    """Folder of the private environment. SCOPE_GUI_ENV_DIR overrides it (used by the tests)."""
    if os.environ.get("SCOPE_GUI_ENV_DIR"): return os.path.abspath(os.environ["SCOPE_GUI_ENV_DIR"])
    from platformdirs import user_data_dir
    return os.path.join(user_data_dir("scope"), "gui-env")

def venv_python(path: str) -> str:
    """Python executable inside a virtual environment folder."""
    return os.path.join(path, "Scripts", "python.exe") if os.name == "nt" else os.path.join(path, "bin", "python")

def pyside_available() -> bool:
    """Tells whether the running Python can import PySide6 (without importing it)."""
    try: return find_spec("PySide6") is not None
    except (ImportError, ValueError): return False

def source_paths() -> list:
    """Site-packages folders of the running interpreter, which the private environment must also see."""
    paths = list(site.getsitepackages())
    if site.ENABLE_USER_SITE and site.getusersitepackages() and os.path.isdir(site.getusersitepackages()): paths.append(site.getusersitepackages())
    pure = sysconfig.get_paths().get("purelib")
    if pure and pure not in paths: paths.append(pure)
    return [p for p in paths if os.path.isdir(p)]

def fingerprint() -> dict:
    """What the private environment was built from: if any of it changes, the environment is rebuilt."""
    return {"python": os.path.realpath(sys.executable), "version": "%d.%d" % sys.version_info[:2], "prefix": os.path.realpath(sys.prefix), "paths": source_paths()}

def is_ready(path: str=None) -> bool:
    """Tells whether the private environment exists, was finished, and was built from this interpreter."""
    path = path or env_dir()
    try:
        with open(os.path.join(path, MARKER)) as fh: data = json.load(fh)
    except (OSError, ValueError): return False
    return data.get("fingerprint") == fingerprint() and os.path.isfile(venv_python(path))

def remove(path: str) -> None:
    """Deletes a private environment, but only a folder that carries our marker or is a half-built virtual environment (pyvenv.cfg plus the usual venv folders only). Never anything else."""
    if not os.path.isdir(path): return
    venv_only = os.path.isfile(os.path.join(path, "pyvenv.cfg")) and set(os.listdir(path)) <= {"bin", "lib", "lib64", "include", "share", "Scripts", "Lib", "Include", "pyvenv.cfg", ".gitignore"}
    if not (os.path.isfile(os.path.join(path, MARKER)) or venv_only):
        raise RuntimeError(f"{path} exists but is not a SCOPE GUI environment; it was left untouched. Remove it by hand or set SCOPE_GUI_ENV_DIR.")
    shutil.rmtree(path)

def build(path: str=None, requirement: str=REQUIREMENT, log=print) -> str:
    """Creates the private environment (replacing an out-of-date one) and returns its Python. Raises RuntimeError with a clear message on failure."""
    path = path or env_dir()
    if is_ready(path): return venv_python(path)
    remove(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    log(f"SCOPE: setting up the private environment of the graphical interface in {path} (first run only, it needs an internet connection)…")
    done = subprocess.run([sys.executable, "-m", "venv", path])
    if done.returncode != 0: raise RuntimeError("Could not create a virtual environment (python -m venv failed). On Debian/Ubuntu install the package python3-venv.")
    py = venv_python(path)
    purelib = subprocess.run([py, "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"], capture_output=True, text=True).stdout.strip()
    if not purelib or not os.path.isdir(purelib): raise RuntimeError("The new environment has no site-packages folder.")
    with open(os.path.join(purelib, "scope_gui_env.pth"), "w") as fh:                       ## addsitedir also reads the .pth files of those folders: development (editable) installs keep working
        for p in source_paths(): fh.write(f"import site; site.addsitedir({p!r})\n")
    log(f"SCOPE: installing {requirement} …")
    done = subprocess.run([py, "-m", "pip", "install", "--disable-pip-version-check", requirement])
    if done.returncode != 0:
        shutil.rmtree(path, ignore_errors=True)
        raise RuntimeError(f"Could not install {requirement}. Check the internet connection, or install it yourself in this Python:  pip install 'scope-qc[gui]'")
    with open(os.path.join(path, MARKER), "w") as fh: json.dump({"fingerprint": fingerprint(), "requirement": requirement}, fh, indent=1)
    log("SCOPE: private environment ready. It is reused from now on.")
    return py

def relaunch(py: str, argv: list) -> int:
    """Starts `scope gui` again from the private environment. On POSIX the current process is replaced; on Windows it waits and returns the exit code."""
    command = [py, "-c", "from scope.cli.main import main; main()", *argv]
    os.environ[LOOP_GUARD] = "1"
    if os.name != "nt": os.execv(py, command)
    return subprocess.call(command)

def ensure_gui_python(argv: list, log=print) -> int:
    """Called by `scope gui` when PySide6 cannot be imported. Builds the private environment if needed and restarts there.

    Returns an exit code when it cannot continue (the caller exits with it); on POSIX a successful restart never returns.
    """
    if os.environ.get(LOOP_GUARD): log("SCOPE: the private GUI environment is installed but PySide6 still cannot be imported. Remove it (scope gui --reset-env) and try again."); return 1
    if os.environ.get("SCOPE_GUI_NO_ENV"): log("SCOPE: PySide6 is missing and SCOPE_GUI_NO_ENV is set. Install it with:  pip install 'scope-qc[gui]'"); return 1
    try: py = build(log=log)
    except RuntimeError as exc: log(f"SCOPE: {exc}"); return 1
    return relaunch(py, argv)
