#!/usr/bin/env python3
"""scope-project: set up a SCOPE project folder on a cluster so that the GUI's "Folder layout" check passes.

Run `scope-project --help` (or `python3 scope-project --help`) for the explanation and examples.

This file is self-contained (standard library and SCOPE only) because it runs on the cluster, where the GUI is not installed:
the `scope-project` command next to scope-gui is this file, and the GUI's Set up this folder… sends this file over SSH and runs it
with SCOPE's Python (with --json, so the window reads the outcome from the last line).
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time

WHY = """\
WHY
  The GUI uploads systems to <project>/Systems, input files to <project>/inputs,
  and downloads results from <project>/Computations. SCOPE itself uses the three
  folders stored in the cluster environment file (scope_env_<name>.npy). The
  two must match, which is what the GUI's "Folder layout" check verifies:

      <project>/Sources/    <project>/Systems/    <project>/Computations/

  This script makes them match in one line, without answering the questions of
  `scope config` again: the queues and the Gaussian 16 / Quantum ESPRESSO
  modules are copied from an environment that already works on this cluster.

  scope-project FOLDER --from ENV_FILE    start a new project folder
  scope-project FOLDER --fix ENV_FILE     repair an existing environment file
  scope-project FOLDER --check ENV_FILE   only check, change nothing
"""

EXAMPLES = """\
EXAMPLES
  New job folder, copying queues and modules from the environment you already use:
      scope-project ~/JOB2 --from ~/scope_env_RUNS.npy
    -> creates ~/JOB2/Sources, ~/JOB2/Systems, ~/JOB2/Computations
       and ~/JOB2/scope_env_JOB2.npy, then prints the two values to paste in
       the GUI (step 5 · Cluster, card 2 · Project on the cluster).

  Is an environment right for its folder?
      scope-project ~/RUNS --check ~/scope_env_RUNS.npy

  Repair it (for instance when Sources, Systems and Computations all point to ~/RUNS):
      scope-project ~/RUNS --fix ~/scope_env_RUNS.npy

  Without --from every time: put this line in ~/.bashrc, then just `scope-project ~/JOB3`
      export SCOPE_TEMPLATE_ENV=~/scope_env_RUNS.npy

SAFETY
  - Nothing is ever moved or deleted. FOLDER and its three subfolders are created
    if missing.
  - --fix keeps a dated copy of the old file (scope_env_X.npy.bak-YYYYmmdd_HHMMSS).
  - --fix stops and lists what is in the old folders if they hold data: move
    what you need into the new folders first, or add --force.
  - A new project never replaces an existing environment file unless you add
    --force (and then a backup is kept).

BEFORE RUNNING
  Run it on the cluster, in a shell where SCOPE works, for instance:
      conda activate scopeN
  If the Python that starts this script has no SCOPE, the script restarts itself
  with the Python next to the `scope` command (or the one given with --python).
  Copy the script there once from the SCOPE folder on your computer, for instance:
      scp scope-project <host>:~/bin/
"""

MARKER  = "__SCOPE_PROJECT__"
RESULT  = {}                                                                ## what happened, printed as one JSON line with --json
FOLDERS = (("sources_path", "Sources"), ("systems_path", "Systems"), ("computations_path", "Computations"))

def parse(argv: list) -> argparse.Namespace:
    """The command line. Answers --help (and usage errors) before SCOPE is needed."""
    parser = argparse.ArgumentParser(prog="scope-project", formatter_class=argparse.RawDescriptionHelpFormatter, description="scope-project: set up a SCOPE project folder on a cluster, ready for the GUI.\n\n" + WHY, epilog=EXAMPLES)
    parser.add_argument("folder", help="the project folder (created if missing)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--from",  dest="template", metavar="ENV_FILE", help="new project: copy queues and modules from this working environment file")
    mode.add_argument("--fix",   metavar="ENV_FILE", help="point this environment at FOLDER's Sources/Systems/Computations (a backup is kept)")
    mode.add_argument("--check", metavar="ENV_FILE", help="report only; exit code 0 if the layout is right, 1 if not")
    parser.add_argument("--name",    help="name of the new environment (default: the folder's name)")
    parser.add_argument("--force",   action="store_true", help="replace an existing environment file, or --fix even if the old folders still hold data")
    parser.add_argument("--dry-run", action="store_true", help="show what would be done, change nothing")
    parser.add_argument("--python",  metavar="PATH", default=os.environ.get("SCOPE_PYTHON"), help="the Python that has SCOPE (default: this one, else the one next to `scope` on the PATH)")
    parser.add_argument("--json",    action="store_true", help=argparse.SUPPRESS)                       ## for the GUI: a last line with the outcome
    a = parser.parse_args(argv)
    a.template = a.template or (None if (a.fix or a.check) else os.environ.get("SCOPE_TEMPLATE_ENV"))
    if not (a.template or a.fix or a.check): parser.error("say which environment to start from: --from ENV_FILE (or set SCOPE_TEMPLATE_ENV), or use --fix ENV_FILE / --check ENV_FILE. Run scope-project --help for examples.")
    return a

def has_scope(python: str) -> bool:
    try: return subprocess.run([python, "-c", "import scope.read_write"], capture_output=True, timeout=120).returncode == 0
    except (OSError, subprocess.TimeoutExpired): return False

def ensure_scope(a: argparse.Namespace) -> None:
    """Makes sure this process can import SCOPE: if it cannot, restarts the script with a Python that can (once), or stops with advice."""
    me = globals().get("__file__") or ""
    def restart_with(python: str) -> None:
        if not os.path.isfile(me): stop(f"this Python ({sys.executable}) cannot import SCOPE, and the script was not started from a file, so it cannot restart with {python}.", 2)
        os.environ["SCOPE_PROJECT_RESTARTED"] = "1"; os.execv(python, [python, os.path.abspath(me), *sys.argv[1:]])
    if a.python and os.path.realpath(a.python) != os.path.realpath(sys.executable):
        if not has_scope(a.python): stop(f"{a.python} cannot import SCOPE. Activate the environment that has SCOPE first (for instance: conda activate scopeN), or give another --python. See scope-project --help.", 2)
        if not os.environ.get("SCOPE_PROJECT_RESTARTED"): restart_with(a.python)
    try:
        import scope.read_write                                                     # noqa: F401
        return
    except ImportError: pass
    scope_cmd = shutil.which("scope")
    candidate = os.path.join(os.path.dirname(scope_cmd), "python") if scope_cmd else ""
    if candidate and not os.environ.get("SCOPE_PROJECT_RESTARTED") and os.path.realpath(candidate) != os.path.realpath(sys.executable) and has_scope(candidate): restart_with(candidate)
    stop(f"no Python with SCOPE found ({sys.executable} cannot import scope). Activate the environment that has SCOPE first (for instance: conda activate scopeN), or pass --python /path/to/python. See scope-project --help.", 2)

def stop(message: str, code: int=1) -> None:
    RESULT["error"] = message; print(f"scope-project: {message}", file=sys.stderr); sys.exit(code)

def same(x, y) -> bool:
    return os.path.normpath(str(x)) == os.path.normpath(str(y))

class Project:
    """One project folder and the three folders SCOPE must use inside it."""
    def __init__(self, folder: str, dry_run: bool=False):
        self.root     = os.path.abspath(os.path.expanduser(folder)).rstrip("/")
        self.expected = {key: f"{self.root}/{sub}/" for key, sub in FOLDERS}
        self.dry_run  = dry_run

    def load(self, path: str) -> tuple:
        """(environment, absolute path) of a SCOPE environment file; stops with a message if it is missing or not an environment."""
        from scope.read_write import load_binary
        path = os.path.abspath(os.path.expanduser(path))
        if not os.path.isfile(path): stop(f"{path} does not exist.")
        try: env = load_binary(path)
        except Exception as exc: stop(f"{path} could not be read: {type(exc).__name__}: {exc}")
        if getattr(env, "object_type", None) != "environment": stop(f"{path} is not a SCOPE environment file.")
        return env, path

    def report(self, env) -> bool:
        """Prints each folder of the environment against the expected one. True if all three match."""
        RESULT.setdefault("before", {sub: getattr(env, key, None) for key, sub in FOLDERS}); good = True
        for key, sub in FOLDERS:
            current = getattr(env, key, None); ok = current is not None and same(current, self.expected[key]); good = good and ok
            print(f"  {sub:<13} {current or '(not set)'}" + ("   ok" if ok else f"   -> should be {self.expected[key]}"))
        return good

    def leftovers(self, env) -> list:
        """Entries in the environment's current folders that SCOPE would no longer see after the change (they are never moved)."""
        found = []
        for key, sub in FOLDERS:
            old = getattr(env, key, None)
            if not old or same(old, self.expected[key]) or not os.path.isdir(old): continue
            skip = {"Sources", "Systems", "Computations", "inputs", "logs"} if same(old, self.root) else set()
            found += [os.path.join(old, n) for n in sorted(os.listdir(old)) if n not in skip and not n.startswith((".", "scope_env_"))]
        return sorted(set(found))

    def make_folders(self) -> None:
        if not self.dry_run:
            for path in self.expected.values(): os.makedirs(path, exist_ok=True)

    def apply(self, env, target: str) -> None:
        """Points the environment at the three folders, creates them, keeps a backup of an existing target and saves."""
        for key, _ in FOLDERS: setattr(env, key, self.expected[key])
        backup = os.path.exists(target); RESULT.update(target=target, after={sub: self.expected[key] for key, sub in FOLDERS}, replaces=backup)
        if self.dry_run: print("\n(dry run) would create, if missing:\n" + "".join(f"  {path}\n" for path in self.expected.values()) + f"and save {target}" + (" (after a backup of the existing file)" if backup else "")); return
        self.make_folders()
        if backup:
            copy = f"{target}.bak-{time.strftime('%Y%m%d_%H%M%S')}"; shutil.copy2(target, copy); print(f"\nBackup of the old file: {copy}"); RESULT["backup"] = copy
        env.save(target); RESULT["changed"] = True

    def next_steps(self, target: str) -> None:
        print("\nIn the GUI (step 5 · Cluster), use:")
        print(f"  Project folder on the cluster:  {self.root}")
        print(f"  Cluster environment file:       {target}")
        print("Then press Test connection: Folder layout should be ok.")

def check(p: Project, env_file: str) -> int:
    env, path = p.load(env_file)
    print(f"Environment '{getattr(env, 'name', '?')}' ({path}) against the project folder {p.root}:")
    good = p.report(env); RESULT.update(target=path, layout_ok=good)
    print("\nThe layout is right." if good else f"\nThe layout is not right. Fix it with:\n  scope-project {p.root} --fix {path}")
    return 0 if good else 1

def fix(p: Project, env_file: str, force: bool) -> int:
    env, path = p.load(env_file)
    print(f"Environment '{getattr(env, 'name', '?')}' ({path}), project folder {p.root}:")
    if p.report(env):
        RESULT.update(target=path, layout_ok=True)
        print("\nNothing to change: the layout is already right."); p.make_folders(); p.next_steps(path); return 0
    old = p.leftovers(env); RESULT["leftovers"] = old
    if old:
        print("\nThe current folders hold data that would no longer be seen by SCOPE (nothing is moved or deleted):")
        for item in old[:20]: print(f"  {item}")
        if len(old) > 20: print(f"  ... and {len(old) - 20} more")
        if not force: stop("stopped. Move what you need into the new Sources/Systems/Computations folders, or run again with --force to change the paths anyway.")
    p.apply(env, path)
    if not p.dry_run: print(f"\nSaved {path} with the new folders:"); p.report(env); p.next_steps(path)
    return 0

def create(p: Project, template: str, name: str, force: bool) -> int:
    env, source = p.load(template)
    name = name or os.path.basename(p.root)
    if not name or "/" in name or name.startswith("."): stop(f"'{name}' cannot be an environment name; pass --name.")
    target = os.path.join(p.root, f"scope_env_{name}.npy")
    RESULT.update(template=source, env_name=name, target=target)
    if os.path.exists(target) and not force: RESULT["exists"] = True; stop(f"{target} already exists. Use --check or --fix on it, or --force to replace it (a backup is kept).")
    queues = getattr(env, "selected_queues", []) or getattr(env, "available_queues", [])
    RESULT.update(scheduler=getattr(env, "scheduler", ""), queues=[getattr(q, "name", str(q)) for q in queues], g16=getattr(env, "g16_module", "") or "", qe=getattr(env, "qe_module", "") or "")
    print(f"New project '{name}' in {p.root}, starting from {source}")
    print(f"  scheduler: {getattr(env, 'scheduler', '?')}; queues: {', '.join(getattr(q, 'name', str(q)) for q in queues) or 'none'}")
    print(f"  modules:   Gaussian 16 {getattr(env, 'g16_module', '') or '(none)'}; Quantum ESPRESSO {getattr(env, 'qe_module', '') or '(none)'}")
    env.name = name
    if hasattr(env, "filepath"): del env.filepath                                   # the copy gets its own file
    p.apply(env, target)
    if not p.dry_run: print("\nCreated:\n" + "".join(f"  {path}\n" for path in p.expected.values()) + f"Saved:\n  {target}"); p.next_steps(target)
    return 0

def main(argv: list=None) -> int:
    a = parse(sys.argv[1:] if argv is None else argv)
    p = Project(a.folder, a.dry_run)
    RESULT.update(mode="check" if a.check else ("fix" if a.fix else "from"), root=p.root, dry_run=a.dry_run, changed=False, error="", leftovers=[])
    code = 1
    try:
        ensure_scope(a)
        if a.check:  code = check(p, a.check)
        elif a.fix:  code = fix(p, a.fix, a.force)
        else:        code = create(p, a.template, a.name, a.force)
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1
    except Exception as exc:                                                ## reported, never a traceback in the window
        RESULT["error"] = f"{type(exc).__name__}: {exc}"; print(f"scope-project: {RESULT['error']}", file=sys.stderr); code = 1
    finally:
        if a.json: RESULT["code"] = code; print(MARKER + json.dumps(RESULT), flush=True)
    return code

if __name__ == "__main__":
    sys.exit(main())
