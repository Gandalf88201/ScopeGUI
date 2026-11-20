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

def unread(listing: dict) -> list:
    """Files of the cluster listing written after the cluster's system file was last saved: SCOPE has not read them yet (it reads outputs
    when it runs again), so the results they hold are not in that system file. [] when the listing has no system file."""
    npy = listing.get("system")
    if not npy: return []
    return [rel for rel, size, mtime in listing.get("files", []) if int(mtime) > int(npy[1]) and safe_rel(rel)]

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
    path = os.path.join(folder, f"{remote.pid_name(system)}_{backend.unique_stamp()}.txt")
    with open(path, "w") as fh: fh.write("".join(r + "\n" for r in rels if safe_rel(r)))
    return path

def files_argv(p: "remote.Profile", info: "backend.EnvInfo", system: str, list_path: str, dry_run: bool=False) -> list:
    """rsync arguments that copy the names in `list_path` from <project>/Computations/<system>/ into the local <Computations>/<system>/."""
    src = f"{p.host}:{p.remote_root.rstrip('/')}/Computations/{system}/"; dst = os.path.join(info.computations_path, system) + "/"
    return [remote.rsync_exe(), "-a", "-z", "-i", "--partial", *(["-n"] if dry_run else []), f"--files-from={list_path}", "-e", remote.ssh_command_string(p), src, dst]

def system_argv(p: "remote.Profile", info: "backend.EnvInfo", system: str) -> list:
    """rsync arguments that copy the cluster's system file next to the local one, as <system>.npy.incoming (it replaces the local file only once complete)."""
    src = f"{p.host}:{p.remote_root.rstrip('/')}/Systems/{system}/{system}.npy"
    return [remote.rsync_exe(), "-a", "-z", "--partial", "-e", remote.ssh_command_string(p), src, incoming_path(info, system)]

#########################
### Synchronisation   ###
#########################
## The input and output files in Computations/<system>/ are the source of truth: a system file only records what SCOPE extracted from
## them, and running SCOPE on the same files (same SCOPE version, same inputs) registers the same results again. So a system file copied
## without the calculation files it registered is not a synchronisation: the other side cannot re-read, continue or check those calculations.
CALC_FILES = ["*.inp", "*.com", "*.gjf", "*.in", "*.log", "*.out", "*.xyz"]     ## inputs and outputs. Job scripts are left out: SCOPE writes them for each machine

def is_calc_file(rel: str) -> bool:
    """An input or output of a calculation (not a heavy working file, not a machine-specific job script)."""
    name = os.path.basename(rel)
    heavy = any(fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(name, pat) for pat in HEAVY)
    return not heavy and any(fnmatch.fnmatch(name, pat) for pat in CALC_FILES)

def left_behind(files: list, with_system: bool) -> list:
    """Download: calculation files the cluster has newer (or only there) but that are not ticked, while its system file is taken. The
    system file would then refer to calculations whose files are not here. [] when the system file is not taken."""
    if not with_system: return []
    return [f.rel for f in files if not f.selected and f.status in ("new", "changed") and is_calc_file(f.rel)]

def local_files(info: "backend.EnvInfo", system: str) -> dict:
    """{rel: (size, mtime)} of the calculation files in this computer's <Computations>/<system>/ (links not followed)."""
    root, out = os.path.join(info.computations_path, system), {}
    for folder, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(folder, d)) and not any(fnmatch.fnmatch(d, pat.split("/")[0]) for pat in HEAVY if "/" in pat)]
        for n in names:
            path = os.path.join(folder, n); rel = os.path.relpath(path, root)
            if os.path.isfile(path) and not os.path.islink(path) and is_calc_file(rel) and safe_rel(rel):
                st = os.stat(path); out[rel] = (st.st_size, int(st.st_mtime))
    return out

@dataclass
class UploadCheck:
    """What an upload of a system would get wrong, from the cluster listing and this computer's folders.

    Attributes:
        cluster_newer (str):  Non-empty when the cluster's system file is newer than this computer's (an upload replaces it).
        only_here (list):     Calculation files here that the cluster lacks or has older: without them the cluster cannot re-read,
                              continue or check what this computer's system file registered.
    """
    cluster_newer: str
    only_here:     list

    @property
    def messages(self) -> list:
        out = [self.cluster_newer] if self.cluster_newer else []
        if self.only_here: out.append(f"{len(self.only_here)} calculation file(s) (inputs and outputs) are here but not on the cluster, or newer here. The system file alone is not a synchronisation: "
                                      "SCOPE on the cluster needs these files to read, continue or check the calculations this system file records.")
        return out

def upload_check(listing: dict, info: "backend.EnvInfo", system: str) -> UploadCheck:
    remote_files = {rel: (int(size), int(mtime)) for rel, size, mtime in listing.get("files", [])}
    here = local_files(info, system)
    only_here = sorted(rel for rel, (size, mtime) in here.items() if rel not in remote_files or mtime > remote_files[rel][1] + 2)
    npy, local_npy, newer = listing.get("system"), os.path.join(info.systems_path, system, f"{system}.npy"), ""
    if npy and os.path.isfile(local_npy) and int(npy[1]) > os.path.getmtime(local_npy) + 2:
        newer = (f"The cluster's system file ({time.strftime('%d %b %H:%M', time.localtime(int(npy[1])))}) is newer than this computer's ({time.strftime('%d %b %H:%M', time.localtime(os.path.getmtime(local_npy)))}). "
                 "Uploading replaces it: what SCOPE registered there since then leaves the system file (the output files stay on the cluster and are read again at the next run there, "
                 "but changes made only in that file, such as charges and spins set there, are lost). Download it first if the cluster has the newer work.")
    return UploadCheck(newer, only_here)

def upload_files_argv(p: "remote.Profile", info: "backend.EnvInfo", system: str, list_path: str, dry_run: bool=False) -> list:
    """rsync arguments that copy the names in `list_path` from the local <Computations>/<system>/ to <project>/Computations/<system>/ (never deletes)."""
    src = os.path.join(info.computations_path, system) + "/"; dst = f"{p.host}:{p.remote_root.rstrip('/')}/Computations/{system}/"
    return [remote.rsync_exe(), "-a", "-z", "-i", "--partial", *(["-n"] if dry_run else []), f"--files-from={list_path}", "-e", remote.ssh_command_string(p), src, dst]

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

def pull_files(p: "remote.Profile", info: "backend.EnvInfo", system: str, rels: list) -> "remote.Result":
    """Copies rels from <project>/Computations/<system>/ into the local folder: rsync where it exists, a tar stream over ssh otherwise (Windows)."""
    local = os.path.join(info.computations_path, system); os.makedirs(local, exist_ok=True)
    if remote.have_rsync(): return run(files_argv(p, info, system, list_file(system, rels)))
    return remote.tar_pull(p, f"{p.remote_root.rstrip('/')}/Computations/{system}", [r for r in rels if safe_rel(r)], local)

def push_files(p: "remote.Profile", info: "backend.EnvInfo", system: str, rels: list) -> "remote.Result":
    """Copies rels from the local <Computations>/<system>/ to the cluster's: rsync where it exists, a tar stream over ssh otherwise (Windows)."""
    if remote.have_rsync(): return run(upload_files_argv(p, info, system, list_file(system, rels)))
    return remote.tar_push(p, os.path.join(info.computations_path, system), [r for r in rels if safe_rel(r)], f"{p.remote_root.rstrip('/')}/Computations/{system}")

def pull_system(p: "remote.Profile", info: "backend.EnvInfo", system: str) -> "remote.Result":
    """Copies the cluster's system file to <system>.npy.incoming next to the local one."""
    incoming = incoming_path(info, system); os.makedirs(os.path.dirname(incoming), exist_ok=True)
    if remote.have_rsync(): return run(system_argv(p, info, system), timeout=3600)
    folder = incoming + ".d"; shutil.rmtree(folder, ignore_errors=True)
    res = remote.tar_pull(p, f"{p.remote_root.rstrip('/')}/Systems/{system}", [f"{system}.npy"], folder, timeout=3600)
    if res.ok and os.path.isfile(os.path.join(folder, f"{system}.npy")): os.replace(os.path.join(folder, f"{system}.npy"), incoming)
    shutil.rmtree(folder, ignore_errors=True)
    return res

def download(p: "remote.Profile", info: "backend.EnvInfo", system: str, rels: list, with_system: bool=False) -> dict:
    """Copies the chosen files (and, if asked, the system file) into the workspace's folders. Returns {'files': Result or None, 'system': message or ''}.

    The system file is first copied to <system>.npy.incoming; only when that copy is complete is the local file kept as <system>.npy.bak-<time>
    and replaced.
    """
    out = {"files": None, "system": "", "list": ""}
    if rels:
        out["files"] = pull_files(p, info, system, rels)
    if with_system:
        incoming = incoming_path(info, system)
        res = pull_system(p, info, system)
        if not res.ok or not os.path.isfile(incoming): out["system"] = "The system file was not copied: " + (res.stderr.strip() or f"exit code {res.returncode}"); return out
        target = os.path.join(info.systems_path, system, f"{system}.npy")
        backup = ""
        if os.path.isfile(target): backup = f"{target}.bak-{backend.unique_stamp()}"; shutil.copy2(target, backup)
        os.replace(incoming, target)
        out["system"] = f"System file replaced by the cluster's" + (f"; the previous one is kept as {os.path.basename(backup)}." if backup else ".")
    return out
