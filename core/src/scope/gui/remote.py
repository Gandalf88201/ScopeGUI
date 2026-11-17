"""Remote cluster support of the SCOPE GUI, without Qt.

SCOPE has to run where the scheduler is, so the GUI drives a SCOPE installed on the cluster over SSH and moves
files with rsync. It uses the system `ssh` and `rsync` as they are: keys, ~/.ssh/config, jump hosts and 2FA stay
the user's business, and no password is ever stored. Every command runs with BatchMode (no prompt that could hang);
for password or 2FA clusters the user opens one connection in a terminal (`master_command`) and the GUI reuses it
through a ControlMaster socket.

Nothing here contacts a host by itself: each function is called by an explicit user action.
"""
import json
import os
import re
import shlex
import subprocess
from dataclasses import asdict, dataclass, field
from scope.gui import backend

MARKER = "__SCOPE_GUI_PROBE__"
DEFAULT_EXCLUDES = ["*.wfc*", "*.save/", "*.chk", "*.rwf", "*.d2e", "*.int", "*.skr", "scope.*/", "*.tmp", "._*", ".DS_Store"]

###############
### Profile ###
###############
@dataclass
class Profile:
    """One cluster.

    Attributes:
        name (str):         Label of the profile (letters, digits, '_', '-', '.').
        host (str):         SSH host or alias from ~/.ssh/config.
        scope_bin (str):    Absolute path of the `scope` program on the cluster. Preferred over `activate`.
        activate (str):     Optional shell line that makes `scope` available (for instance `module load scope` or
                            `source /path/activate scope`). Used when scope_bin is empty; `conda activate` often does not
                            work in a non-interactive shell.
        remote_root (str):  Absolute project folder on the cluster. Its Sources, Systems and Computations subfolders must
                            be the folders of the cluster environment.
        remote_env (str):   Absolute path of the cluster environment file (scope_env_<name>.npy).
    """
    name:        str = ""
    host:        str = ""
    scope_bin:   str = ""
    activate:    str = ""
    remote_root: str = ""
    remote_env:  str = ""

def is_remote_path(path: str) -> bool:
    """True for an absolute path (/home/u/x) or one under the cluster home (~/x). Spaces are not accepted, and neither are variables such as $HOME."""
    return (path.startswith("/") or path == "~" or path.startswith("~/")) and not re.search(r"[\s$`]", path)

def shell_path(path: str) -> str:
    """Quotes a cluster path for a shell script, keeping `~/` working (a quoted ~ is not expanded, so it becomes "$HOME")."""
    if path == "~": return '"$HOME"'
    if path.startswith("~/"): return '"$HOME"/' + shlex.quote(path[2:])
    return shlex.quote(path)

def expand_home(path: str, home: str) -> str:
    """Replaces a leading ~ by the cluster home folder reported by the probe."""
    if home and (path == "~" or path.startswith("~/")): return home.rstrip("/") + path[1:]
    return path

def connection_problems(p: Profile) -> dict:
    """Problems of the connection part of a profile (name, host, how to start scope), per field. This is what a saved profile holds."""
    out = {}
    if not backend.SAFE_NAME.match(p.name or ""): out["name"] = "Letters, digits, '_', '-' or '.', no spaces."
    if not p.host: out["host"] = "The SSH host or alias is empty."
    elif p.host.startswith("-") or re.search(r"\s", p.host): out["host"] = "A host name has no spaces and does not start with '-'."
    if not p.scope_bin and not p.activate: out["scope_bin"] = "Give the full path of `scope` on the cluster (or a line in the next box)."
    elif p.scope_bin and not is_remote_path(p.scope_bin): out["scope_bin"] = "Write the full path starting with / or ~/ , with no spaces and no $VARIABLES."
    return out

def project_problems(p: Profile) -> dict:
    """Problems of the project part (project folder and environment file on the cluster), per field. A workspace holds these."""
    out = {}
    if not p.remote_root: out["root"] = "Give the project folder on the cluster, for example ~/scope_project."
    elif not is_remote_path(p.remote_root): out["root"] = "Write the path starting with / or ~/ , with no spaces and no $VARIABLES."
    if not p.remote_env: out["env"] = "Give the cluster environment file, for example ~/scope_project/scope_env_cluster.npy."
    elif not is_remote_path(p.remote_env): out["env"] = "Write the path starting with / or ~/ , with no spaces and no $VARIABLES."
    return out

def field_problems(p: Profile) -> dict:
    """Problems per field (field name -> message) of the connection and the project together, for hints shown while the user types. Empty fields are reported too."""
    return {**connection_problems(p), **project_problems(p)}

def validate_profile(p: Profile) -> list:
    """Returns a list of problems with the profile (empty if it can be used)."""
    labels = {"name": "Profile name", "host": "SSH host", "scope_bin": "Path of scope", "root": "Project folder", "env": "Environment file"}
    return [f"{labels[k]}: {v}" for k, v in field_problems(p).items()]

def load_profiles() -> dict:
    """Reads the saved profiles (name -> Profile) from the GUI preferences."""
    raw = backend.load_gui_config().get("profiles", {})
    out = {}
    for name, data in raw.items():
        try: out[name] = Profile(**{k: v for k, v in data.items() if k in Profile.__dataclass_fields__})
        except TypeError: continue
    return out

def save_profile(p: Profile, connection_only: bool=False) -> None:
    """Saves a profile. With connection_only, the project fields already stored under that name are kept as they are (the project now
    belongs to each workspace; a profile saved by an older version keeps its own values, which its legacy workspace may still use)."""
    profiles = backend.load_gui_config().get("profiles", {}); data = asdict(p)
    if connection_only:
        old = profiles.get(p.name, {}); data["remote_root"], data["remote_env"] = old.get("remote_root", ""), old.get("remote_env", "")
    profiles[p.name] = data
    backend.save_gui_config({"profiles": profiles})

def delete_profile(name: str) -> None:
    profiles = backend.load_gui_config().get("profiles", {}); profiles.pop(name, None)
    backend.save_gui_config({"profiles": profiles})

def list_ssh_hosts(config_path: str=None) -> list:
    """Lists the host aliases written in ~/.ssh/config (names only; wildcard patterns are skipped). Reads no keys."""
    path = config_path or os.path.expanduser("~/.ssh/config")
    hosts = set()
    try:
        with open(path) as f:
            for line in f:
                m = re.match(r"^\s*Host\s+(.+)$", line, re.IGNORECASE)
                if m: hosts.update(h for h in m.group(1).split() if not re.search(r"[*?!]", h))
    except OSError: pass
    return sorted(hosts)

###########
### SSH ###
###########
def ssh_exe() -> str:
    return os.environ.get("SCOPE_GUI_SSH", "ssh")

def rsync_exe() -> str:
    return os.environ.get("SCOPE_GUI_RSYNC", "rsync")

def control_path() -> str:
    """Socket of the shared SSH connection. Kept short: macOS refuses socket paths longer than 104 characters."""
    base = os.path.expanduser("~/.ssh")
    return os.path.join(base, "cm-%C") if os.path.isdir(base) else f"/tmp/scope-gui-{os.getuid()}-%C"

def ssh_options() -> list:
    """Options for every command the GUI runs: never ask anything, give up quickly, reuse a shared connection if one is open."""
    return ["-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "-o", "ServerAliveInterval=30", "-o", "ControlMaster=auto", "-o", f"ControlPath={control_path()}", "-o", "ControlPersist=10m"]

def ssh_command_string() -> str:
    """The ssh command with its options as one string, for rsync's -e."""
    return " ".join([shlex.quote(ssh_exe()), *[shlex.quote(o) for o in ssh_options()]])

def master_command(p: Profile) -> str:
    """The command to type once in a terminal when the cluster needs a password or a second factor: it opens a connection the GUI then reuses."""
    return f"ssh -M -N -f -o ControlPath={control_path()} -o ControlPersist=4h {shlex.quote(p.host)}"

def ssh_argv(p: Profile, remote_command: str="bash -l -s") -> list:
    """Arguments to start a remote login shell that reads its script from standard input."""
    return [ssh_exe(), *ssh_options(), p.host, remote_command]

@dataclass
class Result:
    """What a command on the cluster returned. stdout and stderr are decoded as UTF-8 (undecodable bytes replaced); raw is stdout as bytes."""
    returncode: int
    stdout:     str   = ""
    stderr:     str   = ""
    raw:        bytes = b""

    @property
    def ok(self) -> bool:
        return self.returncode == 0

def run_script(p: Profile, script: str, timeout: int=60) -> Result:
    """Runs a bash script on the cluster (login shell, script on stdin) and returns its output. Never raises."""
    try:
        done = subprocess.run(ssh_argv(p), input=script.encode("utf-8"), capture_output=True, timeout=timeout)          ## bytes, not the local locale: log offsets are byte counts
        return Result(done.returncode, done.stdout.decode("utf-8", errors="replace"), done.stderr.decode("utf-8", errors="replace"), done.stdout)
    except subprocess.TimeoutExpired: return Result(-2, "", f"Timed out after {timeout} s")
    except OSError as exc: return Result(-1, "", str(exc))

def activation_lines(p: Profile) -> list:
    return [p.activate.strip()] if p.activate.strip() and not p.scope_bin else []

def scope_program(p: Profile) -> str:
    return shell_path(p.scope_bin) if p.scope_bin else "scope"

#############
### Probe ###
#############
PROBE_PY = r'''
import json, os, shutil, subprocess, sys
out = {"python": sys.version.split()[0], "host": os.uname().nodename, "user": os.environ.get("USER", ""), "tmpdir": os.environ.get("TMPDIR", ""), "home": os.path.expanduser("~")}
try:
    import scope
    out["scope_version"], out["scope_file"] = scope.__version__, scope.__file__
except Exception as exc:
    out["scope_error"] = f"{type(exc).__name__}: {exc}"
root, envfile = os.environ["SCOPE_GUI_ROOT"], os.environ["SCOPE_GUI_ENV"]
out["root_exists"] = os.path.isdir(root)
if out["root_exists"]: out["free_gb"] = round(shutil.disk_usage(root).free / 1e9, 1)
out["tools"] = {t: bool(shutil.which(t)) for t in ("sbatch", "squeue", "sinfo", "scontrol", "qsub", "qstat", "module")}
out["module_type"] = subprocess.run(["bash", "-lc", "type -t module"], capture_output=True, text=True).stdout.strip()
out["env_exists"] = os.path.isfile(envfile)
if out["env_exists"] and "scope_error" not in out:
    try:
        from scope.read_write import load_binary
        env = load_binary(envfile)
        out["env"] = {"object_type": getattr(env, "object_type", None), "name": getattr(env, "name", ""), "scheduler": getattr(env, "scheduler", ""), "sources": getattr(env, "sources_path", ""), "systems": getattr(env, "systems_path", ""), "computations": getattr(env, "computations_path", ""),
                      "queues": [q.name for q in getattr(env, "available_queues", [])], "g16": getattr(env, "g16_module", ""), "qe": getattr(env, "qe_module", "")}
        out["folders"] = {k: os.path.isdir(out["env"][k]) for k in ("sources", "systems", "computations")}
        out["software"] = {}
        def summarize(rep):
            ex, mod = rep["checks"].get("executable"), rep["checks"].get("module")
            return {"status": rep["status"], "module": rep["module"], "module_ok": bool(mod is not None and mod.ok), "executable": ex.stdout.splitlines()[0] if ex is not None and ex.ok and ex.stdout else "",
                    "launcher": rep.get("launcher"), "mpi_family": rep.get("mpi_family"), "candidates": rep.get("launcher_candidates", []), "warnings": rep.get("warnings", [])}
        for key, attr in (("qe", "qe_module"), ("g16", "g16_module")):
            module = (getattr(env, attr, "") or "").strip()
            if not module: out["software"][key] = {"status": "not_configured"}; continue
            try:
                if key == "qe":
                    from scope.software.quantum_espresso.qe_input import check_qe_launcher
                    out["software"][key] = summarize(check_qe_launcher(module, scheduler=getattr(env, "scheduler", "local")))
                else:
                    from scope.software.gaussian.g16_input import check_g16_launcher
                    out["software"][key] = summarize(check_g16_launcher(module))
            except Exception as exc:
                out["software"][key] = {"status": "error", "module": module, "error": f"{type(exc).__name__}: {exc}"}
    except Exception as exc:
        out["env_error"] = f"{type(exc).__name__}: {exc}"
print("''' + MARKER + r'''" + json.dumps(out))
'''

def probe_script(p: Profile) -> str:
    """The bash script of the connection test. It only reads: it loads the environment file, lists folders and tries `module load`."""
    lines = ["set -u", *activation_lines(p), f"export SCOPE_GUI_ROOT={shell_path(p.remote_root)} SCOPE_GUI_ENV={shell_path(p.remote_env)}",
             f"SCOPE={scope_program(p)}", 'PY="$(dirname "$(command -v "$SCOPE" 2>/dev/null || echo "$SCOPE")")/python"', '[ -x "$PY" ] || PY=python3', "\"$PY\" - <<'SCOPE_GUI_PY'", PROBE_PY.strip(), "SCOPE_GUI_PY"]
    return "\n".join(lines) + "\n"

@dataclass
class Check:
    """One line of the connection test. status is 'ok', 'warn' or 'fail'."""
    name:   str
    status: str
    detail: str = ""

def parse_probe(stdout: str) -> dict:
    """Extracts the JSON the probe printed (empty dict if there is none)."""
    for line in stdout.splitlines():
        if line.startswith(MARKER):
            try: return json.loads(line[len(MARKER):])
            except ValueError: return {}
    return {}

@dataclass
class Light:
    """One traffic light of the Cluster page. state is 'green' (available), 'amber' (found but incomplete or doubtful), 'red' (not available) or 'grey' (not checked, or not set in the cluster environment)."""
    name:   str
    state:  str
    short:  str = ""
    detail: str = ""

SOFTWARE_NAMES = {"qe": "Quantum ESPRESSO", "g16": "Gaussian 16"}

def unchecked_lights(why: str="Not checked yet. Press Test connection.") -> list:
    """The three lights before anything was checked (or after the connection failed)."""
    return [Light("SCOPE", "grey", "not checked", why), Light("Quantum ESPRESSO", "grey", "not checked", why), Light("Gaussian 16", "grey", "not checked", why)]

def lights_from_probe(info: dict) -> list:
    """The three lights, in order of priority: SCOPE, Quantum ESPRESSO, Gaussian 16.

    SCOPE decides what is available: Quantum ESPRESSO and Gaussian 16 are looked for the way SCOPE looks for them, through the
    module names stored in the cluster environment (`module load <name>`, then `command -v pw.x` or `command -v g16`; for QE also
    an MPI launcher). Software that is installed on the cluster but not named in the cluster environment is grey, because SCOPE would not use it.
    """
    if not info: return unchecked_lights("Not checked: the connection test did not get an answer.")
    if "scope_error" in info: scope = Light("SCOPE", "red", "not found", f"{info['scope_error']}. Check the path of `scope` and that its Python can import it.")
    elif "env_error" in info or (info.get("env_exists") and info.get("env", {}).get("object_type") not in ("environment", None)): scope = Light("SCOPE", "amber", f"version {info.get('scope_version')}", "SCOPE runs, but the cluster environment file could not be read: " + info.get("env_error", "it is not a SCOPE environment."))
    elif not info.get("env_exists"): scope = Light("SCOPE", "amber", f"version {info.get('scope_version')}", "SCOPE runs, but the cluster environment file does not exist yet. Create it on the cluster with `scope config`.")
    else: scope = Light("SCOPE", "green", f"version {info.get('scope_version')}", f"SCOPE {info.get('scope_version')} imports and the cluster environment '{info.get('env', {}).get('name', '')}' loads.")
    lights = [scope]
    software = info.get("software", {})
    for key in ("qe", "g16"):
        name, rep = SOFTWARE_NAMES[key], software.get(key)
        if scope.state == "red" or rep is None: lights.append(Light(name, "grey", "not checked", "SCOPE could not read the cluster environment, so the software modules are unknown.")); continue
        status = rep.get("status")
        if status == "not_configured": lights.append(Light(name, "grey", "not set", f"No {name} module is set in the cluster environment. SCOPE only uses software named there: run `scope config` (or `env.set_software()`) on the cluster and give the module name."))
        elif status == "error": lights.append(Light(name, "red", "check failed", rep.get("error", "")))
        elif not rep.get("module_ok"): lights.append(Light(name, "red", "module fails", f"`module load {rep.get('module')}` failed on the cluster. Check the module name with `module avail`."))
        elif status == "unavailable": lights.append(Light(name, "red", "not found", f"Module {rep.get('module')} loads, but {'pw.x' if key == 'qe' else 'g16'} is not in the path afterwards."))
        elif status == "available":
            launcher = rep.get("launcher")
            where = f"module {rep.get('module')}; {'pw.x' if key == 'qe' else 'g16'} at {rep.get('executable')}"
            if key == "qe":
                mpi = f" ({rep.get('mpi_family')})" if rep.get("mpi_family") else ""
                if launcher: lights.append(Light(name, "green", "available", f"{where}; MPI launcher: {launcher}{mpi}." + (" Notes: " + "; ".join(rep["warnings"]) if rep.get("warnings") else "")))
                else: lights.append(Light(name, "amber", "no MPI launcher", f"{where}, but no MPI launcher (mpirun, mpiexec, srun) was found. " + "; ".join(rep.get("warnings", []))))
            else: lights.append(Light(name, "green", "available", where + ("." if not rep.get("warnings") else ". Notes: " + "; ".join(rep["warnings"]))))
        else: lights.append(Light(name, "amber", "inconclusive", f"Module {rep.get('module')}: the check could not finish. " + "; ".join(rep.get("warnings", []))))
    return lights

def unavailable_software(lights: list, reports: list) -> list:
    """Messages for input files that need software the last connection test found missing (red) or not set up (grey). Empty if all is fine or nothing was tested."""
    by = {l.name: l for l in lights}; need = {"qe": "Quantum ESPRESSO", "g16": "Gaussian 16"}; out = []
    if all(l.state == "grey" and l.short == "not checked" for l in lights): return out
    for r in reports:
        if not r.ok: continue
        light = by.get(need.get(r.software, ""))
        if light and light.state in ("red", "grey"): out.append(f"{os.path.basename(r.path)} needs {light.name}, which is {light.short} on the cluster.")
    return out

def evaluate_probe(p: Profile, result: Result, local_version: str="") -> list:
    """Turns the output of the probe into the list of checks shown to the user. Explains, and does not guess."""
    checks = []
    info = parse_probe(result.stdout)
    if not info:
        why = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else f"exit code {result.returncode}"
        hint = " If the cluster needs a password or a second factor, run the terminal command shown and test again." if result.returncode == 255 else ""
        return [Check("SSH connection", "fail", f"Could not run a command on {p.host}: {why}.{hint}")]
    checks.append(Check("SSH connection and login shell", "ok", f"{info.get('user', '?')}@{info.get('host', '?')}"))
    major, minor = (int(x) for x in info.get("python", "0.0").split(".")[:2])
    checks.append(Check("Python on the cluster", "ok" if (major, minor) == (3, 12) else "warn", f"Python {info.get('python')} (SCOPE needs 3.12)"))
    if "scope_error" in info: checks.append(Check("SCOPE on the cluster", "fail", f"{info['scope_error']}. Check the path of `scope` and that its Python can import it."))
    else:
        same = bool(local_version) and local_version == info.get("scope_version")
        note = "Version numbers match. A development install reports the same number for different code, so this cannot prove the code is identical." if same else f"Version here is {local_version or '?'}; SCOPE files may not load across versions."
        checks.append(Check("SCOPE on the cluster", "ok" if same else "warn", f"version {info.get('scope_version')} ({info.get('scope_file')}). {note}"))
    checks.append(Check("Project folder", "ok" if info.get("root_exists") else "fail", expand_home(p.remote_root, info.get("home", "")) + (f" ({info.get('free_gb')} GB free)" if info.get("root_exists") else " does not exist")))
    if not info.get("env_exists"): checks.append(Check("Cluster environment file", "fail", f"{p.remote_env} not found. Create it on the cluster with `scope config`."))
    elif "env_error" in info: checks.append(Check("Cluster environment file", "fail", info["env_error"]))
    elif "env" in info:
        env = info["env"]
        if env.get("object_type") != "environment": checks.append(Check("Cluster environment file", "fail", "The file is not a SCOPE environment."))
        else:
            checks.append(Check("Cluster environment file", "ok", f"'{env['name']}', scheduler {env['scheduler']}, queues: {', '.join(env['queues']) or 'none'}"))
            if env["scheduler"] == "local": checks.append(Check("Scheduler", "warn", "The cluster environment says 'local': SCOPE will not submit or write inputs. It was probably configured where no scheduler was found."))
            else:
                needed = ["sbatch", "squeue", "sinfo"] if env["scheduler"] == "slurm" else ["qsub", "qstat"]
                missing = [t for t in needed if not info["tools"].get(t)]
                checks.append(Check("Scheduler commands", "fail" if missing else "ok", ("missing: " + ", ".join(missing)) if missing else ", ".join(needed) + " found"))
            expected = {k: os.path.join(expand_home(p.remote_root, info.get("home", "")).rstrip("/"), v) + "/" for k, v in (("sources", "Sources"), ("systems", "Systems"), ("computations", "Computations"))}
            off = [k for k in expected if os.path.normpath(env[k]) != os.path.normpath(expected[k])]
            checks.append(Check("Folder layout", "warn" if off else "ok", ("The environment's " + ", ".join(off) + " folder is not <project folder>/" + "/".join(v.capitalize() for v in off) + ". `scope set_path` would use a different layout from the environment.") if off else "Sources, Systems and Computations are inside the project folder"))
            gone = [k for k, ok in info.get("folders", {}).items() if not ok]
            if gone: checks.append(Check("Environment folders exist", "fail", "missing: " + ", ".join(gone)))
            for light in lights_from_probe(info)[1:]: checks.append(Check(light.name, {"green": "ok", "amber": "warn", "red": "fail", "grey": "warn"}[light.state], light.detail))
    checks.append(Check("TMPDIR", "ok" if info.get("tmpdir") else "warn", info.get("tmpdir") or "TMPDIR is empty on the login node. SCOPE's job script needs it on the compute node (it uses ${TMPDIR:?}); ask the cluster support if jobs fail at once."))
    return checks

############
### Sync ###
############
def rsync_argv(src: str, dst: str, dry_run: bool=False, excludes: list=None) -> list:
    """rsync arguments: archive, compress, itemize changes, never delete. Uses only flags that old (openrsync) versions also know."""
    argv = [rsync_exe(), "-a", "-z", "-i"] + (["-n"] if dry_run else [])
    argv += [f"--exclude={e}" for e in (DEFAULT_EXCLUDES if excludes is None else excludes)]
    return argv + ["-e", ssh_command_string(), src, dst]

def upload_items(p: Profile, info: "backend.EnvInfo", system: str, inputs: list) -> list:
    """What an upload copies, as (local, remote, kind) triples. Generated calculation files are never part of it: SCOPE writes them on the cluster."""
    root = p.remote_root.rstrip("/")
    items = [(os.path.join(info.sources_path, system) + "/", f"{p.host}:{root}/Sources/{system}/", "sources"), (os.path.join(info.systems_path, system, f"{system}.npy"), f"{p.host}:{root}/Systems/{system}/{system}.npy", "system")]
    items += [(i, f"{p.host}:{root}/inputs/", "input") for i in inputs]
    return items

def download_items(p: Profile, info: "backend.EnvInfo", system: str) -> list:
    """What a download copies: the calculations folder and the system file of the cluster."""
    root = p.remote_root.rstrip("/")
    return [(f"{p.host}:{root}/Computations/{system}/", os.path.join(info.computations_path, system) + "/", "computations"), (f"{p.host}:{root}/Systems/{system}/{system}.npy", os.path.join(info.systems_path, system) + "/", "system")]

def duplicate_names(paths: list) -> list:
    """File names that occur more than once in `paths`. Inputs are uploaded side by side into <project>/inputs, so two files with one name would replace each other."""
    names = [os.path.basename(x) for x in paths]
    return sorted({n for n in names if names.count(n) > 1})

def remote_dirs_script(p: Profile, system: str) -> str:
    root = shell_path(p.remote_root.rstrip("/")); s = shlex.quote(system)
    return f"mkdir -p {root}/Sources/{s} {root}/Systems/{s} {root}/Computations/{s} {root}/inputs\n"

def sync(items: list, dry_run: bool) -> list:
    """Runs rsync for each item. Returns a list of (kind, Result, lines) where lines are the itemized changes."""
    out = []
    for src, dst, kind in items:
        try:
            done = subprocess.run(rsync_argv(src, dst, dry_run), capture_output=True, text=True, timeout=600)
            res = Result(done.returncode, done.stdout, done.stderr)
        except subprocess.TimeoutExpired: res = Result(-2, "", "Timed out")
        except OSError as exc: res = Result(-1, "", str(exc))
        out.append((kind, res, [l for l in res.stdout.splitlines() if l.strip() and not l.startswith(("sending", "receiving", "total", "sent", "building"))]))
    return out

##############
### Remote run ###
##############
def run_script_text(p: Profile, system: str, remote_inputs: list, quiet: bool=False, verbose: bool=False, errors: bool=False, set_path: bool=True) -> str:
    """The script for `scope run` on the cluster. It first runs `scope set_path` from the project folder, so the paths inside the uploaded system point to the cluster folders."""
    scope = scope_program(p); root = shell_path(p.remote_root.rstrip("/")); env = shell_path(p.remote_env); s = shlex.quote(system)
    flags = " ".join(f for f, on in (("-q", quiet), ("-v", verbose), ("-e", errors)) if on)
    lines = ["set -e", "export TERM=dumb PYTHONUNBUFFERED=1", *activation_lines(p), f"cd {root}"]
    if set_path: lines.append(f"{scope} set_path -n {env} -s {s}")
    lines.append(f"{scope} run -n {env} -s {s} -i " + " ".join(shell_path(i) for i in remote_inputs) + (f" {flags}" if flags else ""))
    return "\n".join(lines) + "\n"


############################################
### Runs on the cluster that outlive us ###
############################################
STARTED, BUSY, SIZE, ALIVE, BEGIN, RUNLINE = "__SCOPE_GUI_STARTED__", "__SCOPE_GUI_BUSY__", "__SCOPE_GUI_SIZE__", "__SCOPE_GUI_ALIVE__", "__SCOPE_GUI_BEGIN__", "__SCOPE_GUI_RUN__"
EXIT_MARKER_REMOTE = backend.EXIT_MARKER

def pid_name(system: str) -> str:
    """The name used for a system in the run files on the cluster (pid file, lock, logs): every character other than a letter, digit, '.', '_' or '-' becomes '_'.
    Computed here once, so that starting, following, stopping and listing a run all use the same files."""
    return "".join(ch if (ch.isascii() and (ch.isalnum() or ch in "._-")) else "_" for ch in system)

## Shell lines shared by the run scripts. `alive PID NAME` is true when PID runs and is the wrapper of a run of NAME (its command line holds
## the log path): a pid left in a file by a run that died hard can be reused by another program, which must not be taken for the run.
def _common(p: Profile, system: str="") -> list:
    lines = [f"ROOT={shell_path(p.remote_root.rstrip('/'))}",
             'alive() { kill -0 "$1" 2>/dev/null || return 1; command -v ps >/dev/null 2>&1 || return 0; ps -ww -p "$1" -o args= 2>/dev/null | grep -qF -- "/logs/run_$2_"; }']
    if system: lines += [f"N={pid_name(system)}", 'PIDF="$ROOT"/logs/run_"$N".pid', 'LOCK="$ROOT"/logs/run_"$N".lock']
    return lines

def detached_run_script(p: Profile, system: str, remote_inputs: list, quiet: bool=False, verbose: bool=False, errors: bool=False, set_path: bool=True, stamp: str="") -> str:
    """Starts `scope run` on the cluster so that it does not depend on this window or on the SSH connection.

    One run per system at a time: the lock is a folder (`mkdir` is atomic, so two starts at the same moment cannot both get it). The run is
    started with nohup in its own process group (setsid, or job control where setsid is missing), reads no input, and writes to
    <project>/logs/run_<system>_<time>.log; its pid is kept in <project>/logs/run_<system>.pid. When it ends, or is stopped, it appends
    `__SCOPE_GUI_EXIT__ <code>` to the log and removes the pid file and the lock. If the connection drops, the run goes on.
    Prints `__SCOPE_GUI_STARTED__ <pid> <log>`, or `__SCOPE_GUI_BUSY__ <pid>` if a run of that system is active (`starting` when another start holds the lock).
    """
    import time
    stamp = stamp or time.strftime("%Y%m%d_%H%M%S")
    inner = run_script_text(p, system, remote_inputs, quiet, verbose, errors, set_path)
    wrapper = 'trap true TERM; bash "$1" > "$2" 2>&1 < /dev/null; echo "' + EXIT_MARKER_REMOTE + ' $?" >> "$2"; rm -rf "$3" "$4"'      ## TERM: let the run end, then still write the marker and free the lock
    lines = ["set -e", *_common(p, system), 'mkdir -p "$ROOT"/logs',
             'if ! mkdir "$LOCK" 2>/dev/null; then',
             '  if [ -f "$PIDF" ] && alive "$(cat "$PIDF")" "$N"; then echo "' + BUSY + ' $(cat "$PIDF")"; exit 0; fi',
             '  if [ -z "$(find "$LOCK" -maxdepth 0 -mmin +1 2>/dev/null)" ]; then echo "' + BUSY + ' starting"; exit 0; fi',      ## a start in progress (no pid yet); older than a minute means a start that died
             '  rm -rf "$LOCK"; mkdir "$LOCK" 2>/dev/null || { echo "' + BUSY + ' starting"; exit 0; }',
             'fi',
             f'LOG="$ROOT"/logs/run_"$N"_{stamp}.log',
             'cat > "$LOG".sh <<\'SCOPE_GUI_RUN_BODY\'', inner.rstrip("\n"), "SCOPE_GUI_RUN_BODY",
             "WRAP=" + shlex.quote(wrapper),
             'if command -v setsid >/dev/null 2>&1; then nohup setsid bash -c "$WRAP" _ "$LOG".sh "$LOG" "$PIDF" "$LOCK" > /dev/null 2>&1 < /dev/null &',
             'else set -m; nohup bash -c "$WRAP" _ "$LOG".sh "$LOG" "$PIDF" "$LOCK" > /dev/null 2>&1 < /dev/null & set +m; fi',
             'echo $! > "$PIDF"', 'echo "' + STARTED + ' $! $LOG"']
    return "\n".join(lines) + "\n"

def parse_started(stdout: str) -> dict:
    """{'state': 'started', 'pid': ..., 'log': ...}, {'state': 'busy', 'pid': ...} or {} when the script printed neither."""
    for line in stdout.splitlines():
        if line.startswith(STARTED):
            parts = line.split(None, 2)
            if len(parts) == 3: return {"state": "started", "pid": parts[1], "log": parts[2].strip()}
        if line.startswith(BUSY): return {"state": "busy", "pid": line.split()[-1]}
    return {}

def poll_script(p: Profile, system: str, log: str, offset: int) -> str:
    """Reads what a cluster run appended to its log after `offset` bytes, and whether it is still alive. Read-only."""
    return "\n".join([*_common(p, system), f'LOG={shell_path(log)}',
                      f'echo "{SIZE} $(wc -c < "$LOG" 2>/dev/null || echo 0)"',
                      f'if [ -f "$PIDF" ] && alive "$(cat "$PIDF")" "$N"; then echo "{ALIVE} 1"; else echo "{ALIVE} 0"; fi',
                      f'echo "{BEGIN}"', f'tail -c +{int(offset) + 1} "$LOG" 2>/dev/null || true']) + "\n"

def parse_poll(stdout: "str | bytes") -> dict:
    """Splits the answer of poll_script into {'alive': bool, 'text': new log text without the end marker, 'bytes': how many bytes of log were read, 'exit': code or None}.

    Give it the raw bytes (Result.raw): the byte count is then exact, and a character still being written is left for the next poll.
    """
    raw = stdout if isinstance(stdout, bytes) else stdout.encode("utf-8")
    head, _, body = raw.partition(BEGIN.encode() + b"\n")
    body = body[:backend.complete_utf8(body)]
    alive = (ALIVE + " 1").encode() in head; code = None; keep = []
    for line in body.decode("utf-8", errors="replace").split("\n"):
        if line.startswith(backend.EXIT_MARKER):
            try: code = int(line.split()[1])
            except (IndexError, ValueError): code = -1
        else: keep.append(line)
    return {"alive": alive, "text": "\n".join(keep), "bytes": len(body), "exit": code}

def stop_script(p: Profile, system: str) -> str:
    """Asks the cluster run of a system to end: its whole process group, only if the pid is still that run."""
    return "\n".join([*_common(p, system), 'if [ -f "$PIDF" ] && alive "$(cat "$PIDF")" "$N"; then PID=$(cat "$PIDF"); kill -TERM -- -"$PID" 2>/dev/null || kill -TERM "$PID" 2>/dev/null; echo stopped; else echo "no run"; fi']) + "\n"

def list_runs_script(p: Profile) -> str:
    """Lists the runs of this project that are active, and the most recent logs, so a window opened later can find them. Read-only.
    The system names it reports are the pid_name() form."""
    return "\n".join([*_common(p), 'for f in "$ROOT"/logs/run_*.pid; do [ -f "$f" ] || continue; PID=$(cat "$f"); n=$(basename "$f" .pid); n=${n#run_}',
                      'if alive "$PID" "$n"; then A=1; else A=0; fi; L=$(ls -t "$ROOT"/logs/run_"$n"_*.log 2>/dev/null | head -1)',
                      f'echo "{RUNLINE} $n $PID $A $L"; done', f'for f in $(ls -t "$ROOT"/logs/run_*_*.log 2>/dev/null | head -5); do echo "__SCOPE_GUI_LOG__ $f"; done']) + "\n"

def parse_runs(stdout: str) -> dict:
    """{'active': [(system, pid, log)], 'logs': [paths, newest first]}"""
    active, logs = [], []
    for line in stdout.splitlines():
        if line.startswith(RUNLINE):
            parts = line.split()
            if len(parts) >= 5 and parts[3] == "1": active.append((parts[1], parts[2], parts[4]))
        elif line.startswith("__SCOPE_GUI_LOG__"): logs.append(line.split(None, 1)[1].strip())
    return {"active": active, "logs": logs}
