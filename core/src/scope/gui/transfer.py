"""Safe download of the results of a cluster project into the local folders of a workspace (no Qt).

What comes back is chosen file by file: the cluster folder of a system is listed first (name, size, date), compared with the local
copy, and the user ticks what to copy. Files that are new or changed on the cluster are proposed; heavy files (wavefunctions, scratch,
checkpoints) and anything larger than a size limit are listed but left unticked, so a GB-sized file is never copied by accident.

Safety rules, all enforced here:
- files land only inside the workspace's own folders: <Computations>/<system>/ and, for the system file, <Systems>/<system>/;
  names from the cluster with '..', an absolute path or a line break are refused, and links on the cluster are not followed;
- nothing local is ever deleted; a local file that is newer than the cluster's is left unticked;
- the copy is rsync with --partial (an interrupted transfer resumes), and rsync replaces each file only once it is complete;
- the free space here is checked before anything is copied;
- the local system file is replaced only from a complete download, and the old one is kept as <system>.npy.bak-<time>.

The same transfer can be run by hand: command_line() gives the rsync command, which reads the chosen names from a list file.
"""
import fnmatch
import json
import os
import shlex
import shutil
import time
from dataclasses import dataclass
from scope.gui import backend, remote

MARKER   = "__SCOPE_GUI_LISTING__"
HEAVY    = ["*.wfc*", "*.chk", "*.rwf", "*.d2e", "*.int", "*.skr", "*.tmp", "*.save/*", "scope.*/*"]        ## kept unticked by default
MAX_LIST = 50000

LISTING_PY = r'''
import json, os, sys
root, system = os.environ["SCOPE_GUI_ROOT"], os.environ["SCOPE_GUI_SYSTEM"]
comp = os.path.join(root, "Computations", system); out = {"exists": os.path.isdir(comp), "files": [], "truncated": False}
for folder, dirs, files in os.walk(comp, followlinks=False):
    dirs[:] = sorted(d for d in dirs if not os.path.islink(os.path.join(folder, d)))
    for name in sorted(files):
        path = os.path.join(folder, name)
        if os.path.islink(path) or not os.path.isfile(path) or "\n" in path: continue
        st = os.stat(path); out["files"].append([os.path.relpath(path, comp), st.st_size, int(st.st_mtime)])
        if len(out["files"]) >= int(os.environ["SCOPE_GUI_MAX"]): out["truncated"] = True; break
    if out["truncated"]: break
npy = os.path.join(root, "Systems", system, system + ".npy")
out["system"] = [os.path.getsize(npy), int(os.path.getmtime(npy))] if os.path.isfile(npy) and not os.path.islink(npy) else None
print("''' + MARKER + r'''" + json.dumps(out))
'''

@dataclass
class RemoteFile:
    """One file of the cluster folder of a system, compared with the local copy.

    Attributes:
        rel (str):          Path inside <Computations>/<system>/.
        size, mtime (int):  On the cluster (bytes, seconds).
        local_size (int):   Here, or -1 if the file does not exist here.
        local_mtime (int):  Here, or 0.
        status (str):       'new' (not here), 'changed' (differs and the cluster's is newer), 'same', or 'newer here' (differs and the local one is newer).
        heavy (bool):       Matches a pattern of large working files (wavefunctions, scratch, checkpoints).
        selected (bool):    Proposed for download.
    """
    rel:         str
    size:        int
    mtime:       int
    local_size:  int  = -1
    local_mtime: int  = 0
    status:      str  = "new"
    heavy:       bool = False
    selected:    bool = False

def safe_rel(rel: str) -> bool:
    """Whether a name from the cluster stays inside the destination folder."""
    parts = rel.replace("\\", "/").split("/")
    return bool(rel) and not rel.startswith(("/", "~")) and ".." not in parts and "\n" not in rel and "\r" not in rel

def listing_script(p: "remote.Profile", system: str) -> str:
    """Bash for the cluster: lists <project>/Computations/<system>/ and the system file (read-only), with the Python of SCOPE."""
    return "\n".join(["set -u", *remote.activation_lines(p), f"export SCOPE_GUI_ROOT={remote.shell_path(p.remote_root.rstrip('/'))} SCOPE_GUI_SYSTEM={shlex.quote(system)} SCOPE_GUI_MAX={MAX_LIST}",
                      f"SCOPE={remote.scope_program(p)}", 'PY="$(dirname "$(command -v "$SCOPE" 2>/dev/null || echo "$SCOPE")")/python"', '[ -x "$PY" ] || PY=python3',
                      "\"$PY\" - <<'SCOPE_GUI_PY'", LISTING_PY.strip(), "SCOPE_GUI_PY"]) + "\n"

def parse_listing(stdout: str) -> dict:
    """The listing printed by the cluster: {'exists', 'files': [[rel, size, mtime]], 'truncated', 'system': [size, mtime] or None}; {} if none."""
    for line in stdout.splitlines():
        if line.startswith(MARKER):
            try: return json.loads(line[len(MARKER):])
            except ValueError: return {}
    return {}

def compare(listing: dict, info: "backend.EnvInfo", system: str, max_mb: float=200) -> list:
    """Compares the cluster listing with the local folder and proposes a selection. Unsafe names are dropped."""
    local_dir, out = os.path.join(info.computations_path, system), []
    for rel, size, mtime in listing.get("files", []):
        if not safe_rel(rel): continue
        f = RemoteFile(rel, int(size), int(mtime)); here = os.path.join(local_dir, rel)
        f.heavy = any(fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(os.path.basename(rel), pat) for pat in HEAVY)
        if os.path.isfile(here):
            st = os.stat(here); f.local_size, f.local_mtime = st.st_size, int(st.st_mtime)
            if f.local_size == f.size and abs(f.local_mtime - f.mtime) <= 2: f.status = "same"
            elif f.local_mtime > f.mtime + 2: f.status = "newer here"
            else: f.status = "changed"
        f.selected = f.status in ("new", "changed") and not f.heavy and f.size <= max_mb * 1e6
        out.append(f)
    return out

def human(size: int) -> str:
    for unit in ("B", "kB", "MB", "GB", "TB"):
        if size < 1000 or unit == "TB": return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1000

def space_problem(info: "backend.EnvInfo", total: int) -> str:
    """'' if the local disk can hold `total` bytes more (with a margin of 10 % and 200 MB), otherwise why not."""
    target = info.computations_path if os.path.isdir(info.computations_path) else os.path.dirname(info.filepath)
    free = shutil.disk_usage(target).free
    need = int(total * 1.1) + 200_000_000
    return "" if free >= need else f"Not enough free space here: {human(total)} selected, {human(free)} free on the disk of {target}."

def list_file(system: str, rels: list) -> str:
    """Writes the chosen names, one per line, to a list file (kept with the GUI settings) and returns its path. rsync reads it with --files-from."""
    from platformdirs import user_config_dir
    folder = os.path.join(user_config_dir("scope"), "gui_downloads"); os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"{remote.pid_name(system)}_{time.strftime('%Y%m%d_%H%M%S')}.txt")
    with open(path, "w") as fh: fh.write("".join(r + "\n" for r in rels if safe_rel(r)))
    return path

def files_argv(p: "remote.Profile", info: "backend.EnvInfo", system: str, list_path: str, dry_run: bool=False) -> list:
    """rsync arguments that copy the names in `list_path` from <project>/Computations/<system>/ into the local <Computations>/<system>/."""
    src = f"{p.host}:{p.remote_root.rstrip('/')}/Computations/{system}/"; dst = os.path.join(info.computations_path, system) + "/"
    return [remote.rsync_exe(), "-a", "-z", "-i", "--partial", *(["-n"] if dry_run else []), f"--files-from={list_path}", "-e", remote.ssh_command_string(), src, dst]

def system_argv(p: "remote.Profile", info: "backend.EnvInfo", system: str) -> list:
    """rsync arguments that copy the cluster's system file next to the local one, as <system>.npy.incoming (it replaces the local file only once complete)."""
    src = f"{p.host}:{p.remote_root.rstrip('/')}/Systems/{system}/{system}.npy"
    return [remote.rsync_exe(), "-a", "-z", "--partial", "-e", remote.ssh_command_string(), src, incoming_path(info, system)]

def incoming_path(info: "backend.EnvInfo", system: str) -> str:
    return os.path.join(info.systems_path, system, f"{system}.npy.incoming")

def command_line(p: "remote.Profile", info: "backend.EnvInfo", system: str, list_path: str) -> str:
    """The same download as a command to paste in a Terminal (for very large transfers, or to run it inside screen/tmux)."""
    os.makedirs(os.path.join(info.computations_path, system), exist_ok=True)
    return " ".join(shlex.quote(a) for a in files_argv(p, info, system, list_path))

def run(argv: list, timeout: int=24 * 3600) -> "remote.Result":
    import subprocess
    try:
        done = subprocess.run(argv, capture_output=True, timeout=timeout)
        return remote.Result(done.returncode, done.stdout.decode("utf-8", errors="replace"), done.stderr.decode("utf-8", errors="replace"), done.stdout)
    except subprocess.TimeoutExpired: return remote.Result(-2, "", "Timed out")
    except OSError as exc: return remote.Result(-1, "", str(exc))

def download(p: "remote.Profile", info: "backend.EnvInfo", system: str, rels: list, with_system: bool=False) -> dict:
    """Copies the chosen files (and, if asked, the system file) into the workspace's folders. Returns {'files': Result or None, 'system': message or ''}.

    The system file is first copied to <system>.npy.incoming; only when that copy is complete is the local file kept as <system>.npy.bak-<time>
    and replaced.
    """
    out = {"files": None, "system": "", "list": ""}
    if rels:
        os.makedirs(os.path.join(info.computations_path, system), exist_ok=True)
        out["list"] = list_file(system, rels); out["files"] = run(files_argv(p, info, system, out["list"]))
    if with_system:
        incoming = incoming_path(info, system); os.makedirs(os.path.dirname(incoming), exist_ok=True)
        res = run(system_argv(p, info, system), timeout=3600)
        if not res.ok or not os.path.isfile(incoming): out["system"] = "The system file was not copied: " + (res.stderr.strip() or f"exit code {res.returncode}"); return out
        target = os.path.join(info.systems_path, system, f"{system}.npy")
        backup = ""
        if os.path.isfile(target): backup = f"{target}.bak-{time.strftime('%Y%m%d_%H%M%S')}"; shutil.copy2(target, backup)
        os.replace(incoming, target)
        out["system"] = f"System file replaced by the cluster's" + (f"; the previous one is kept as {os.path.basename(backup)}." if backup else ".")
    return out
