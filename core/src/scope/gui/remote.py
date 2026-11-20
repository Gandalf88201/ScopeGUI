"""Remote cluster support of the SCOPE GUI, without Qt.

SCOPE has to run where the scheduler is, so the GUI drives a SCOPE installed on the cluster over SSH and moves
files with rsync. It uses the system `ssh` and `rsync` as they are: keys, ~/.ssh/config, jump hosts and 2FA stay
the user's business, and no password is ever stored. Every command runs with BatchMode (no prompt that could hang);
for password or 2FA clusters the user presses Connect…: `open_connection` runs one ssh that may ask questions, relays
them to a dialog, and leaves a ControlMaster socket that every other command reuses. (The same connection can be opened
in a terminal with `master_command`.) The password is passed to ssh and forgotten; it is never stored or logged.

Nothing here contacts a host by itself: each function is called by an explicit user action.
"""
import json
import os
import re
import shlex
import subprocess
import sys
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
        user (str):         Optional login name on the cluster (ssh -l). Empty: the one from ~/.ssh/config, else the local user name.
        port (str):         Optional SSH port (ssh -p), digits only. Empty: the one from ~/.ssh/config, else 22.
    """
    name:        str = ""
    host:        str = ""
    scope_bin:   str = ""
    activate:    str = ""
    remote_root: str = ""
    remote_env:  str = ""
    user:        str = ""
    port:        str = ""

SAFE_USER = re.compile(r"^[A-Za-z0-9_.][A-Za-z0-9_.-]*$")
## ssh options that take a value, so that the value is not taken for the host when an ssh command is pasted
SSH_VALUE_OPTIONS = set("BbcDEeFIiJLlmOoPpQRSWw")

def parse_ssh_target(text: str) -> "dict | None":
    """Splits what a user may paste in the host field into host, user and port. Accepts a plain host, `user@host`, `user@host:port`,
    `ssh://user@host:port`, or a whole command such as `ssh -p 2122 user@host` or `ssh -l user host -p 2122`. Returns
    {"host", "user", "port"} (user and port may be empty), or None when no host is found. Contacts nothing."""
    try: words = shlex.split(text.strip())
    except ValueError: return None
    if words and os.path.basename(words[0]) == "ssh": words = words[1:]
    user = port = target = ""; i = 0
    while i < len(words):
        w = words[i]
        if w.startswith("-") and len(w) > 1:
            flag, rest = w[1], w[2:]
            value = rest if rest else (words[i + 1] if flag in SSH_VALUE_OPTIONS and i + 1 < len(words) else "")
            if flag == "p": port = value
            elif flag == "l": user = value
            elif flag == "o" and "=" in value:
                key, val = value.split("=", 1)
                if key.lower() == "port": port = val
                elif key.lower() == "user": user = val
            i += 1 if rest or flag not in SSH_VALUE_OPTIONS else 2; continue
        if not target: target = w
        i += 1
    if target.startswith("ssh://"): target = target[len("ssh://"):].rstrip("/")
    if "@" in target: found, target = target.rsplit("@", 1); user = user or found
    m = re.match(r"^(.+):(\d+)$", target)
    if m: target, port = m.group(1), port or m.group(2)
    if not target: return None
    return {"host": target, "user": user, "port": port}

def connection_key(p: Profile) -> tuple:
    """What identifies one cluster account: two profiles with the same key reach the same files."""
    return (p.host, p.user, p.port)

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
    elif p.host.startswith("-") or re.search(r"\s", p.host): out["host"] = "A host name has no spaces and does not start with '-'. To paste a whole ssh command, leave the field and it is split."
    elif "@" in p.host or re.search(r":\d+$", p.host): out["host"] = "Put the user name and the port in their own fields (leave the field and it is split)."
    if p.user and not SAFE_USER.match(p.user): out["user"] = "A user name has letters, digits, '_', '-' or '.', no spaces, and does not start with '-'."
    if p.port and not (p.port.isdigit() and 1 <= int(p.port) <= 65535): out["port"] = "The port is a number between 1 and 65535 (22 if the cluster says nothing)."
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
    return [f"{FIELD_LABELS[k]}: {v}" for k, v in field_problems(p).items()]

FIELD_LABELS = {"name": "Profile name", "host": "SSH host", "user": "User", "port": "Port", "scope_bin": "Path of scope", "root": "Project folder", "env": "Environment file"}

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

def shares_connection() -> bool:
    """Whether ssh can keep one shared connection open (ControlMaster) that every command reuses. macOS and Linux can; the OpenSSH that
    comes with Windows cannot (it has no Unix sockets for it), so on Windows every command logs in on its own: a key is needed."""
    return os.name == "posix"

def control_path() -> str:
    """Socket of the shared SSH connection. Kept short: macOS refuses socket paths longer than 104 characters."""
    base = os.path.expanduser("~/.ssh")
    uid = os.getuid() if hasattr(os, "getuid") else os.getpid()            ## os.getuid does not exist on Windows (never used there: no shared connection)
    return os.path.join(base, "cm-%C") if os.path.isdir(base) else f"/tmp/scope-gui-{uid}-%C"

def control_options() -> list:
    """The options that reuse (or open) the shared connection; none where ssh cannot share one (Windows)."""
    return ["-o", "ControlMaster=auto", "-o", f"ControlPath={control_path()}", "-o", "ControlPersist=10m"] if shares_connection() else []

def account_options(p: "Profile | None") -> list:
    """-p PORT and -l USER when the profile sets them (otherwise ~/.ssh/config or ssh's defaults apply)."""
    if p is None: return []
    return (["-p", p.port] if p.port else []) + (["-l", p.user] if p.user else [])

def ssh_options(p: "Profile | None"=None) -> list:
    """Options for every command the GUI runs: never ask anything, give up quickly, reuse a shared connection if one is open; then the profile's port and user."""
    return ["-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "-o", "ServerAliveInterval=30", *control_options(), *account_options(p)]

def ssh_command_string(p: "Profile | None"=None) -> str:
    """The ssh command with its options as one string, for rsync's -e."""
    return " ".join([shlex.quote(ssh_exe()), *[shlex.quote(o) for o in ssh_options(p)]])

def ssh_display(p: Profile) -> str:
    """The plain ssh command a user would type for this profile, for logs (`ssh -p 2122 -l me host`)."""
    return " ".join(["ssh", *[shlex.quote(o) for o in account_options(p)], shlex.quote(p.host)])

def master_command(p: Profile) -> str:
    """The command to type once in a terminal when the cluster needs a password or a second factor: it opens a connection the GUI then reuses.
    It carries the same port and user as the GUI's commands, so both name the same socket (%C hashes host, port and user)."""
    return " ".join(["ssh -M -N -f", f"-o ControlPath={control_path()}", "-o ControlPersist=4h", *[shlex.quote(o) for o in account_options(p)], shlex.quote(p.host)])

def master_options(p: Profile) -> list:
    """Options of the connection the GUI opens itself (Connect…): a master that stays in the background for 4 hours and that every other command reuses.
    The socket name is the one of ssh_options and master_command, so all of them share it. No BatchMode: this is the one command that may ask questions."""
    return ["-M", "-N", "-f", "-o", "BatchMode=no", "-o", "ConnectTimeout=20", "-o", "ServerAliveInterval=30", "-o", f"ControlPath={control_path()}", "-o", "ControlPersist=4h", *account_options(p)]

def control_argv(p: Profile, operation: str) -> list:
    """`ssh -O check|exit` for the shared connection of this account. It talks to the local socket only: nothing is sent to the cluster."""
    return [ssh_exe(), "-O", operation, "-o", f"ControlPath={control_path()}", *account_options(p), p.host]

def connection_alive(p: Profile, timeout: int=5) -> bool:
    """True when a shared connection to this account is open (from Connect…, or from the terminal command). Contacts no host.
    Always False where ssh cannot share a connection (Windows): there each command logs in with a key."""
    if not p.host or not shares_connection(): return False
    try: return subprocess.run(control_argv(p, "check"), capture_output=True, stdin=subprocess.DEVNULL, timeout=timeout).returncode == 0
    except (OSError, subprocess.TimeoutExpired): return False

def close_connection(p: Profile, timeout: int=10) -> bool:
    """Closes the shared connection (the cluster sees a normal logout). True when it is closed afterwards."""
    if not shares_connection(): return True
    try: subprocess.run(control_argv(p, "exit"), capture_output=True, stdin=subprocess.DEVNULL, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired): pass
    return not connection_alive(p)

def can_login_here() -> bool:
    """Connect… needs a pseudo-terminal, which ssh insists on for passwords: macOS and Linux have one, Windows does not."""
    return os.name == "posix"

## Key login, for computers where the window cannot relay a password (Windows): a small program that runs in its own console window, so
## ssh-keygen and ssh ask their questions there (passphrase, cluster password, host key) and the GUI never sees the answers. It creates
## ~/.ssh/id_ed25519 if there is no key yet, adds the public key to ~/.ssh/authorized_keys on the cluster (once, never twice), and checks
## that a command now logs in without a password (BatchMode, as every command of the GUI).
KEY_HELPER = r'''
import json, os, subprocess, sys
ssh, target = json.loads(sys.argv[1]), json.loads(sys.argv[2])
key = os.path.join(os.path.expanduser("~"), ".ssh", "id_ed25519")
def pause(code):
    try: input("\nPress Enter to close this window.")
    except EOFError: pass
    sys.exit(code)
print("SCOPE GUI: set up key login to " + target[-1] + "\n")
existing = [k for k in ("id_ed25519", "id_ecdsa", "id_rsa") if os.path.isfile(os.path.join(os.path.dirname(key), k + ".pub"))]
if existing: key = os.path.join(os.path.dirname(key), existing[0]); print("Using your existing key " + key + ".pub")
else:
    os.makedirs(os.path.dirname(key), exist_ok=True)
    print("Creating a key (" + key + "). When asked for a passphrase, press Enter twice for none:")
    print("the window needs a key it can use without asking. (With a passphrase, start the 'OpenSSH Authentication Agent' service and run ssh-add.)\n")
    if subprocess.run(["ssh-keygen", "-t", "ed25519", "-f", key]).returncode != 0: print("ssh-keygen failed."); pause(1)
pub = open(key + ".pub", encoding="utf-8").read().strip()
remote = 'umask 077; mkdir -p ~/.ssh; touch ~/.ssh/authorized_keys; K=$(cat); grep -qxF "$K" ~/.ssh/authorized_keys || echo "$K" >> ~/.ssh/authorized_keys; echo SCOPE_GUI_KEY_OK'
print("\nCopying the public key to the cluster. Answer the cluster's questions here (its password, or a code); nothing is stored.\n")
done = subprocess.run(ssh + target + [remote], input=pub + "\n", text=True, stdout=subprocess.PIPE)
if done.returncode != 0 or "SCOPE_GUI_KEY_OK" not in done.stdout: print("\nThe key could not be added (exit code " + str(done.returncode) + ")."); pause(1)
check = subprocess.run(ssh + ["-o", "BatchMode=yes"] + target + ["echo SCOPE_GUI_LOGIN_OK"], text=True, stdout=subprocess.PIPE, stdin=subprocess.DEVNULL)
if "SCOPE_GUI_LOGIN_OK" in check.stdout: print("\nDone: the cluster now accepts this computer's key. Go back to the window and press Test connection."); pause(0)
print("\nThe key was added, but a login without password still fails. The cluster may not accept keys, or the key has a passphrase and no agent holds it."); pause(1)
'''

def key_setup_argv(p: Profile) -> list:
    """The command that opens the key-login helper (see KEY_HELPER) for this account. It is started in its own console window."""
    target = [*account_options(p), p.host]
    return [sys.executable, "-I", "-c", KEY_HELPER, json.dumps([ssh_exe(), "-o", "ConnectTimeout=20"]), json.dumps(target)]

def open_key_setup(p: Profile) -> "Result":
    """Starts the key-login helper in a console window of its own (Windows) and returns at once. Result(-1) when it cannot be started."""
    kw = {"creationflags": getattr(subprocess, "CREATE_NEW_CONSOLE", 0)} if os.name == "nt" else {}
    try: subprocess.Popen(key_setup_argv(p), **kw); return Result(0)
    except OSError as exc: return Result(-1, "", str(exc))

def key_setup_command(p: Profile) -> str:
    """The same as the helper, as commands to type in PowerShell (shown in the window for those who prefer to do it themselves)."""
    target = " ".join([*[shlex.quote(o) for o in account_options(p)], p.host])
    return ("ssh-keygen -t ed25519    # only if you have no key yet; press Enter twice for no passphrase\n"
            f"Get-Content $HOME\\.ssh\\id_ed25519.pub | ssh {target} \"umask 077; mkdir -p ~/.ssh; cat >> ~/.ssh/authorized_keys\"")

def auth_failed(res: "Result") -> bool:
    """True when a command failed only because the cluster wants a login (no key, no open shared connection)."""
    return res.returncode == 255 and "permission denied" in res.stderr.lower()

## Runs ssh on a pseudo-terminal and relays its questions. It is a separate small program (and not a fork inside the GUI) so that no thread
## of the GUI is copied. Questions go to the GUI as JSON lines on stdout, answers come back on stdin: a password is never put in an argument,
## an environment variable or a file, and the helper blanks every answer from the text it reports.
LOGIN_HELPER = r'''
import json, os, pty, re, select, signal, sys, time
argv, patience = json.loads(sys.argv[1]), float(sys.argv[2])
def say(obj): sys.stdout.write(json.dumps(obj) + "\n"); sys.stdout.flush()
pid, fd = pty.fork()
if pid == 0:
    try: os.execvp(argv[0], argv)
    except OSError as exc: os.write(2, str(exc).encode())
    os._exit(127)
given, shown, buf, last = [], [], "", time.time()
def scrub(text):
    for a in given:
        if len(a) >= 3: text = text.replace(a, "***")
    return text
def finish(code, extra=""):
    say({"type": "done", "code": code, "text": scrub("\n".join(shown + [buf, extra])).strip()[-1500:]}); sys.exit(0)
def reap(block=False):
    try: done, st = os.waitpid(pid, 0 if block else os.WNOHANG)
    except ChildProcessError: return True, 0
    return (done != 0), (os.waitstatus_to_exitcode(st) if done else None)
while True:
    ready = select.select([fd], [], [], 0.3)[0]
    if ready:
        try: chunk = os.read(fd, 4096)
        except OSError: chunk = b""
        if chunk: buf += chunk.decode("utf-8", "replace").replace("\r", ""); last = time.time()
        else: time.sleep(0.05)
    over, code = reap()
    if over:
        try:
            while select.select([fd], [], [], 0.1)[0]:
                chunk = os.read(fd, 4096)
                if not chunk: break
                buf += chunk.decode("utf-8", "replace").replace("\r", "")
        except OSError: pass
        finish(code)
    tail = buf.rsplit("\n", 1)[-1]
    if not ready and tail.strip() and re.search(r"[:?]\s*$", tail) and time.time() - last > 0.25:
        context = "\n".join(l for l in buf.rsplit("\n", 1)[0].split("\n") if l.strip())[-1500:]
        prompt = tail.strip(); kind = "confirm" if "(yes/no" in prompt else "secret"
        say({"type": "prompt", "context": scrub(context), "prompt": prompt, "kind": kind})
        line = sys.stdin.readline(); msg = json.loads(line) if line.strip() else {"cancel": True}
        if msg.get("cancel"):
            try: os.kill(pid, signal.SIGTERM)
            except OSError: pass
            reap(block=True); finish(130, "Cancelled.")
        answer = str(msg.get("answer", "")); given.append(answer); shown.append(context)
        os.write(fd, (answer + "\n").encode("utf-8")); buf = ""; last = time.time()
    elif not ready and time.time() - last > patience:
        try: os.kill(pid, signal.SIGTERM)
        except OSError: pass
        reap(block=True); finish(124, "Timed out waiting for the cluster.")
'''

def open_connection(p: Profile, ask: "Callable[[str, str, str], str | None]", patience: int=120) -> "Result":
    """Opens the shared connection, answering what ssh asks (host key, password, verification code) through `ask(context, prompt, kind)`.

    kind is 'secret' (a password or code: mask it) or 'confirm' (the first-time host key question: answer yes or no). `ask` returns the answer, or None to cancel.
    It is called from the thread that runs this function, and may block as long as the user needs. Nothing is stored: the answer goes to ssh on a
    pseudo-terminal and is forgotten. `patience` is how long ssh may stay silent after an answer. Returns Result(0) when the connection is open."""
    if not can_login_here(): return Result(-1, "", "Entering a password in this window needs macOS or Linux. Use the terminal command instead.")
    argv = [ssh_exe(), *master_options(p), p.host]
    try: proc = subprocess.Popen([sys.executable, "-I", "-c", LOGIN_HELPER, json.dumps(argv), str(patience)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)
    except OSError as exc: return Result(-1, "", str(exc))
    code, text = -1, ""
    try:
        for line in proc.stdout:
            try: msg = json.loads(line)
            except ValueError: continue
            if msg.get("type") == "prompt":
                answer = ask(msg.get("context", ""), msg.get("prompt", ""), msg.get("kind", "secret"))
                proc.stdin.write(json.dumps({"cancel": True} if answer is None else {"answer": answer}) + "\n"); proc.stdin.flush()
            elif msg.get("type") == "done": code, text = int(msg.get("code", -1)), msg.get("text", "")
    except (BrokenPipeError, OSError): pass
    finally:
        try: proc.stdin.close()
        except OSError: pass
        try: proc.wait(timeout=10)
        except subprocess.TimeoutExpired: proc.kill()
    if code == 0 and not connection_alive(p): return Result(1, "", text or "ssh finished but no shared connection is open.")
    return Result(code, "", text)

def ssh_argv(p: Profile, remote_command: str="bash -l -s") -> list:
    """Arguments to start a remote login shell that reads its script from standard input."""
    return [ssh_exe(), *ssh_options(p), p.host, remote_command]

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
    try:
        done = subprocess.run(["git", "-C", os.path.dirname(os.path.realpath(scope.__file__)), "log", "-1", "--format=%H %cs"], capture_output=True, text=True, timeout=15, stdin=subprocess.DEVNULL)
        if done.returncode == 0 and len(done.stdout.split()) == 2: out["scope_commit"], out["scope_commit_date"] = done.stdout.split()
    except Exception: pass
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

def evaluate_probe(p: Profile, result: Result, local_version: str="", local_commit: tuple=("", "")) -> list:
    """Turns the output of the probe into the list of checks shown to the user. Explains, and does not guess.

    When SCOPE comes from a git checkout both here and on the cluster, the commits are compared (local_commit is (hash, date), see
    updates.local_commit); otherwise only the version numbers, which a development install does not change."""
    checks = []
    info = parse_probe(result.stdout)
    if not info:
        why = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else f"exit code {result.returncode}"
        hint = " If the cluster needs a password or a second factor, press Connect… (or run the terminal command shown) and test again." if result.returncode == 255 else ""
        return [Check("SSH connection", "fail", f"Could not run a command on {p.host}: {why}.{hint}")]
    checks.append(Check("SSH connection and login shell", "ok", f"{info.get('user', '?')}@{info.get('host', '?')}"))
    major, minor = (int(x) for x in info.get("python", "0.0").split(".")[:2])
    checks.append(Check("Python on the cluster", "ok" if (major, minor) == (3, 12) else "warn", f"Python {info.get('python')} (SCOPE needs 3.12)"))
    if "scope_error" in info: checks.append(Check("SCOPE on the cluster", "fail", f"{info['scope_error']}. Check the path of `scope` and that its Python can import it."))
    elif local_commit[0] and info.get("scope_commit"):
        here, there = local_commit[0], info["scope_commit"]
        if here == there: checks.append(Check("SCOPE on the cluster", "ok", f"the same code as here: commit {here[:7]} of {local_commit[1]} ({info.get('scope_file')})."))
        else: checks.append(Check("SCOPE on the cluster", "warn", f"different code: commit {there[:7]} of {info.get('scope_commit_date')} on the cluster, {here[:7]} of {local_commit[1]} here ({info.get('scope_file')}). Results and system files may differ; update the older copy (git pull in its SCOPE folder)."))
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
            checks.append(Check("Folder layout", ("fail" if "systems" in off else "warn") if off else "ok", ("The environment's " + ", ".join(off) + " folder is not <project folder>/" + "/".join(v.capitalize() for v in off) + ". `scope set_path` would use a different layout from the environment.") if off else "Sources, Systems and Computations are inside the project folder"))
            gone = [k for k, ok in info.get("folders", {}).items() if not ok]
            if gone: checks.append(Check("Environment folders exist", "fail", "missing: " + ", ".join(gone)))
            for light in lights_from_probe(info)[1:]: checks.append(Check(light.name, {"green": "ok", "amber": "warn", "red": "fail", "grey": "warn"}[light.state], light.detail))
    checks.append(Check("TMPDIR", "ok" if info.get("tmpdir") else "warn", info.get("tmpdir") or "TMPDIR is empty on the login node. SCOPE's job script needs it on the compute node (it uses ${TMPDIR:?}); ask the cluster support if jobs fail at once."))
    return checks

############
### Sync ###
############
def rsync_argv(src: str, dst: str, dry_run: bool=False, excludes: list=None, p: "Profile | None"=None) -> list:
    """rsync arguments: archive, compress, itemize changes, never delete. Uses only flags that old (openrsync) versions also know. The profile gives the port and user."""
    argv = [rsync_exe(), "-a", "-z", "-i"] + (["-n"] if dry_run else [])
    argv += [f"--exclude={e}" for e in (DEFAULT_EXCLUDES if excludes is None else excludes)]
    return argv + ["-e", ssh_command_string(p), src, dst]

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

##### without rsync (Windows): tar through ssh #####
## Windows 10 and 11 come with ssh and tar but not rsync. Files then travel as a tar stream over one ssh command per batch: whole files,
## no resume of an interrupted copy, nothing deleted. Dates are kept, so the next comparison sees the copies as up to date.
TAR_BATCH = 200                                                             ## files per ssh command (keeps the command line short on Windows)

def have_rsync() -> bool:
    import shutil
    return bool(shutil.which(rsync_exe()))

def tar_exe() -> str:
    import shutil
    return os.environ.get("SCOPE_GUI_TAR") or shutil.which("tar") or "tar"

def _batches(rels: list) -> list:
    return [rels[i:i + TAR_BATCH] for i in range(0, len(rels), TAR_BATCH)] or [[]]

def tar_push(p: Profile, local_dir: str, rels: list, remote_dir: str, timeout: int=24 * 3600) -> Result:
    """Copies rels (paths under local_dir, '/'-separated) into remote_dir on the cluster, creating folders. Never deletes."""
    if not rels: return Result(0)
    lines = []
    for batch in _batches(rels):
        try:
            pack = subprocess.Popen([tar_exe(), "-cf", "-", "-C", local_dir, *batch], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            done = subprocess.run(ssh_argv(p, f"mkdir -p {shell_path(remote_dir)} && tar -xf - -C {shell_path(remote_dir)}"), stdin=pack.stdout, capture_output=True, timeout=timeout)
            pack.stdout.close(); err = pack.stderr.read().decode("utf-8", "replace"); pack.wait(timeout=60)
        except subprocess.TimeoutExpired: return Result(-2, "", "Timed out")
        except OSError as exc: return Result(-1, "", str(exc))
        if done.returncode != 0 or pack.returncode != 0:
            return Result(done.returncode or pack.returncode, "\n".join(lines), (err + done.stderr.decode("utf-8", "replace")).strip())
        lines += [f">f {r}" for r in batch]
    return Result(0, "\n".join(lines))

def tar_pull(p: Profile, remote_dir: str, rels: list, local_dir: str, timeout: int=24 * 3600) -> Result:
    """Copies rels (paths under remote_dir on the cluster) into local_dir, creating folders. Never deletes."""
    if not rels: return Result(0)
    os.makedirs(local_dir, exist_ok=True); lines = []
    for batch in _batches(rels):
        cmd = f"tar -cf - -C {shell_path(remote_dir)} -- " + " ".join(shlex.quote(r) for r in batch)
        try:
            fetch = subprocess.Popen(ssh_argv(p, cmd), stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL)
            done = subprocess.run([tar_exe(), "-xf", "-", "-C", local_dir], stdin=fetch.stdout, capture_output=True, timeout=timeout)
            fetch.stdout.close(); err = fetch.stderr.read().decode("utf-8", "replace"); fetch.wait(timeout=60)
        except subprocess.TimeoutExpired: return Result(-2, "", "Timed out")
        except OSError as exc: return Result(-1, "", str(exc))
        if done.returncode != 0 or fetch.returncode != 0:
            return Result(fetch.returncode or done.returncode, "\n".join(lines), (err + done.stderr.decode("utf-8", "replace")).strip())
        lines += [f">f {r}" for r in batch]
    return Result(0, "\n".join(lines))

def _remote_path(p: Profile, dst: str) -> str:
    return dst[len(p.host) + 1:] if dst.startswith(p.host + ":") else dst

def _local_rels(folder: str, excludes: list) -> list:
    import fnmatch
    out = []
    for root, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if not any(fnmatch.fnmatch(d + "/", e) or fnmatch.fnmatch(d, e.rstrip("/")) for e in excludes)]
        for f in files:
            if any(fnmatch.fnmatch(f, e) for e in excludes): continue
            out.append(os.path.relpath(os.path.join(root, f), folder).replace(os.sep, "/"))
    return sorted(out)

def tar_sync_item(p: Profile, src: str, dst: str, dry_run: bool) -> tuple:
    """One upload item without rsync: a folder (src ends with '/') or one file. Returns (Result, lines)."""
    remote = _remote_path(p, dst)
    if src.endswith("/") or src.endswith(os.sep): local_dir, rels, remote_dir = src, _local_rels(src, DEFAULT_EXCLUDES), remote
    else: local_dir, rels, remote_dir = os.path.dirname(src), [os.path.basename(src)], (remote if remote.endswith("/") else remote.rsplit("/", 1)[0] + "/")
    if dry_run: return Result(0, "\n".join(f">f {r}" for r in rels)), [f">f {r}  (no rsync here: whole files are copied)" for r in rels]
    res = tar_push(p, local_dir, rels, remote_dir)
    return res, [l for l in res.stdout.splitlines() if l.strip()]

def sync(items: list, dry_run: bool, p: "Profile | None"=None) -> list:
    """Runs rsync for each item, through the profile's port and user. Returns a list of (kind, Result, lines) where lines are the itemized changes.
    Without rsync (Windows) the items are copied as tar streams over ssh (tar_sync_item)."""
    if p is not None and not have_rsync():
        return [(kind, *tar_sync_item(p, src, dst, dry_run)) for src, dst, kind in items]
    out = []
    for src, dst, kind in items:
        try:
            done = subprocess.run(rsync_argv(src, dst, dry_run, p=p), capture_output=True, text=True, timeout=600)
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
MISSING = "__SCOPE_GUI_MISSING__"
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

def detached_run_script(p: Profile, system: str, remote_inputs: list, quiet: bool=False, verbose: bool=False, errors: bool=False, set_path: bool=True, stamp: str="", check_files: bool=False) -> str:
    """Starts `scope run` on the cluster so that it does not depend on this window or on the SSH connection.

    One run per system at a time: the lock is a folder (`mkdir` is atomic, so two starts at the same moment cannot both get it). The run is
    started with nohup in its own process group (setsid, or job control where setsid is missing), reads no input, and writes to
    <project>/logs/run_<system>_<time>.log; its pid is kept in <project>/logs/run_<system>.pid. When it ends, or is stopped, it appends
    `__SCOPE_GUI_EXIT__ <code>` to the log and removes the pid file and the lock. If the connection drops, the run goes on.
    Prints `__SCOPE_GUI_STARTED__ <pid> <log>`, or `__SCOPE_GUI_BUSY__ <pid>` if a run of that system is active (`starting` when another start holds the lock).
    check_files (the Run button): first checks, in the same connection, what `scope set_path` and `scope run` will need, and starts nothing
    when one is missing, printing `__SCOPE_GUI_MISSING__ <kind> <path>` for each:
      envdir  the environment file keeps its systems in <path>, not in <project>/Systems where Upload puts them (an environment of
              another project folder: SCOPE would never find the uploaded system);
      system  the system file is not where SCOPE reads it (<environment's Systems>/<system>/<system>.npy): not uploaded yet;
      input   an input file is not uploaded.
    The environment is read with SCOPE's own Python, as the connection test does; if that fails, <project>/Systems is assumed.
    """
    import time
    from scope.gui.backend import unique_stamp
    stamp = stamp or unique_stamp()                                         ## date_time_id: two starts in one second never share a log
    inner = run_script_text(p, system, remote_inputs, quiet, verbose, errors, set_path)
    wrapper = 'trap true TERM; bash "$1" > "$2" 2>&1 < /dev/null; echo "' + EXIT_MARKER_REMOTE + ' $?" >> "$2"; rm -rf "$3" "$4"'      ## TERM: let the run end, then still write the marker and free the lock
    check = []
    if check_files:
        q = shlex.quote(system); act = "".join(f"{{ {a}; }} >/dev/null 2>&1; " for a in activation_lines(p))
        read_env = ("from scope.read_write import load_binary; import sys, io, contextlib\n"
                    "with contextlib.redirect_stdout(io.StringIO()): e = load_binary(sys.argv[1])\nprint(e.systems_path)")
        check = ["MISSING=0",
                 f'SYS="$({act}SCOPE={scope_program(p)}; PY="$(dirname "$(command -v "$SCOPE" 2>/dev/null || echo "$SCOPE")")/python"; [ -x "$PY" ] || PY=python3; '
                 f'"$PY" -c {shlex.quote(read_env)} {shell_path(p.remote_env)} 2>/dev/null | tail -n 1)" || SYS=""',
                 '[ -n "$SYS" ] || SYS="$ROOT"/Systems', 'SYS="${SYS%/}"',
                 'A="$(cd "$SYS" 2>/dev/null && pwd -P || echo "$SYS")"; B="$(cd "$ROOT"/Systems 2>/dev/null && pwd -P || echo "$ROOT"/Systems)"',
                 f'[ "$A" = "$B" ] || {{ echo "{MISSING} envdir $SYS"; MISSING=1; }}',
                 f'[ -f "$SYS"/{q}/{q}.npy ] || {{ echo "{MISSING} system $SYS/"{q}/{q}.npy; MISSING=1; }}',
                 *[f'[ -f {shell_path(i)} ] || {{ echo "{MISSING} input "{shell_path(i)}; MISSING=1; }}' for i in remote_inputs],
                 '[ "$MISSING" = 0 ] || exit 0']                            ## before the lock: nothing to clean up
    lines = ["set -e", *_common(p, system), *check, 'mkdir -p "$ROOT"/logs',
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
    """{'state': 'started', 'pid': ..., 'log': ...}, {'state': 'busy', 'pid': ...}, {'state': 'missing', 'files': [(kind, path), ...]}
    (files not uploaded: nothing started) or {} when the script printed none of these."""
    missing = [tuple(line.split(None, 2)[1:]) for line in stdout.splitlines() if line.startswith(MISSING + " ") and len(line.split(None, 2)) == 3]
    if missing: return {"state": "missing", "files": missing}
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

LASTLINE, QUEUELINE, JOBLINE, REALROOT, UNREADLINE = "__SCOPE_GUI_LAST__", "__SCOPE_GUI_QUEUE__", "__SCOPE_GUI_JOB__", "__SCOPE_GUI_REALROOT__", "__SCOPE_GUI_UNREAD__"
MAX_UNREAD = 1000                                                           ## counted at most, so a huge folder never slows the check

## Outputs SCOPE has not read yet. SCOPE reads (registers) the output of a calculation only when it runs again, and saves the system file
## at the end of each run; on a cluster the jobs write their outputs after `scope run` has ended. So a file in Computations/<system>/ that
## is newer than Systems/<system>/<system>.npy was written after SCOPE last saved: SCOPE has not read it, and the results it holds are not
## in the system file yet. One `UNREADLINE <count> <system>` line per system that has such files.
## Kept cheap, as it runs at every check (30 s for all of it): only systems with a run log of this window are looked at (the only ones the
## Runs page shows; the log name is the pid_name() form, made here with tr, so a name with non-ASCII letters is skipped), heavy working
## folders (*.save, scope.*) are not walked, and the scan of each system stops after 10 s where `timeout` exists.
_UNREAD_LINES = ['T=""; command -v timeout >/dev/null 2>&1 && T="timeout 10"',
                 'for d in "$ROOT"/Systems/*/; do s=$(basename "$d"); y="$d$s.npy"; { [ -f "$y" ] && [ -d "$ROOT/Computations/$s" ]; } || continue',
                 "  N=$(printf '%s' \"$s\" | LC_ALL=C tr -c 'A-Za-z0-9._-' '_'); ls \"$ROOT\"/logs/run_\"$N\"_*.log >/dev/null 2>&1 || continue",
                 "  n=$(( $($T find \"$ROOT/Computations/$s\" \\( -name '*.save' -o -name 'scope.*' \\) -prune -o -type f -newer \"$y\" -print 2>/dev/null | head -n " + str(MAX_UNREAD) + " | wc -l) ))",
                 f'  if [ "$n" -gt 0 ]; then echo "{UNREADLINE} $n $s"; fi; done']

## The jobs of the user in the scheduler queue, one `JOBLINE id|state|name|working folder|its physical path` line each (empty folders when
## the scheduler does not tell them), after a `QUEUELINE slurm|sge|other|none|error` line. `scope run` submits its jobs and ends, so the queue is where a cluster run
## goes on. `qstat` alone is not taken for SGE: PBS/Torque have one too, with another output, which would read as an empty queue. SGE is
## recognised as SCOPE recognises it (qconf), or by $SGE_ROOT; any other `qstat` is 'other' (a scheduler this window cannot read).
## SGE: `qstat -r` gives the full job names, `qstat -j <ids>` the folder of each job (`cwd:`, as SCOPE submits with `#$ -cwd`, else
## `sge_o_workdir:`, the folder it was submitted from), so SGE jobs are matched by folder like Slurm ones. A job whose folder cannot be
## read is still listed, and is then matched by its name.
_SGE_LINES = r"""  if Q=$(qstat -r -u "$U" 2>/dev/null); then echo "__Q__ sge"
    J=$(printf "%s\n" "$Q" | awk '$1 ~ /^[0-9]+$/ {id=$1; st=$5} /Full jobname:/ {sub(/.*Full jobname:[ \t]*/, ""); print id "|" st "|" $0}')
    IDS=$(printf "%s\n" "$J" | cut -d"|" -f1 | grep . | paste -sd, -)
    D=""; [ -n "$IDS" ] && D=$(qstat -j "$IDS" 2>/dev/null | awk '/^job_number:/ {id=$2} /^cwd:/ {v=$0; sub(/^cwd:[ \t]*/, "", v); c[id]=v} /^sge_o_workdir:/ {v=$0; sub(/^sge_o_workdir:[ \t]*/, "", v); w[id]=v} END {for (i in w) if (!(i in c)) c[i]=w[i]; for (i in c) print i "|" c[i]}')
    printf "%s\n" "$J" | while IFS= read -r l; do [ -n "$l" ] || continue; wd=$(printf "%s\n" "$D" | awk -F"|" -v i="${l%%|*}" '$1==i {sub(/^[^|]*\|/, ""); print; exit}'); rd=""; [ -n "$wd" ] && rd=$(cd "$wd" 2>/dev/null && pwd -P); echo "__J__ $l|$wd|$rd"; done
  else echo "__Q__ error"; fi""".replace("__Q__", QUEUELINE).replace("__J__", JOBLINE).split("\n")

_QUEUE_LINES = ['U=${USER:-$(id -un)}',
                f'echo "{REALROOT} $(cd "$ROOT" 2>/dev/null && pwd -P)"',
                'if command -v squeue >/dev/null 2>&1; then',
                '  if Q=$(squeue -h -u "$U" -o "%i|%T|%j|%Z" 2>/dev/null); then echo "' + QUEUELINE + ' slurm"',
                '    printf "%s\\n" "$Q" | while IFS= read -r l; do [ -n "$l" ] || continue; wd=${l##*|}; rd=$(cd "$wd" 2>/dev/null && pwd -P); echo "' + JOBLINE + ' $l|$rd"; done',
                '  else echo "' + QUEUELINE + ' error"; fi',
                'elif command -v qstat >/dev/null 2>&1 && { [ -n "${SGE_ROOT:-}" ] || command -v qconf >/dev/null 2>&1; }; then',
                *_SGE_LINES,
                'elif command -v qstat >/dev/null 2>&1; then echo "' + QUEUELINE + ' other"',
                'else echo "' + QUEUELINE + ' none"; fi']

def list_runs_script(p: Profile) -> str:
    """Lists the runs of this project that are active, the newest logs with how each run ended, the outputs SCOPE has not read yet, and
    the user's jobs in the scheduler queue, so a window opened later can find them. Read-only. The system names of runs are the pid_name()
    form; those of unread outputs are the folder names."""
    return "\n".join([*_common(p), 'for f in "$ROOT"/logs/run_*.pid; do [ -f "$f" ] || continue; PID=$(cat "$f"); n=$(basename "$f" .pid); n=${n#run_}',
                      'if alive "$PID" "$n"; then A=1; else A=0; fi; L=$(ls -t "$ROOT"/logs/run_"$n"_*.log 2>/dev/null | head -1)',
                      f'echo "{RUNLINE} $n $PID $A $L"; done', f'for f in $(ls -t "$ROOT"/logs/run_*_*.log 2>/dev/null | head -5); do echo "__SCOPE_GUI_LOG__ $f"; done',
                      'ls -t "$ROOT"/logs/run_*_*.log 2>/dev/null | head -50 | while IFS= read -r f; do',
                      f'  C=$(tail -n 3 "$f" 2>/dev/null | grep "^{EXIT_MARKER_REMOTE} " | tail -n 1 | cut -d" " -f2); echo "{LASTLINE} ${{C:--}} $f"; done',
                      *_QUEUE_LINES, *_UNREAD_LINES]) + "\n"

@dataclass
class QueuedJob:
    """A job of the user in the scheduler queue. workdir is the folder it runs in as the scheduler gives it ('' when it could not be
    read), realdir the same folder with every link resolved ('' when unknown)."""
    id:      str
    state:   str
    name:    str
    workdir: str = ""
    realdir: str = ""

    @property
    def phase(self) -> str:
        """'pending', 'running', or the scheduler's own state in lower case (held, suspended, error…)."""
        s = self.state.strip()
        if s.upper() in ("PENDING", "REQUEUED", "REQUEUE_HOLD", "REQUEUE_FED", "RESV_DEL_HOLD") or s in ("qw", "hqw", "Rq"): return "pending"
        if s.upper() in ("RUNNING", "CONFIGURING", "COMPLETING", "STAGE_OUT", "SIGNALING", "RESIZING") or s in ("r", "t", "Rr", "Rt"): return "running"
        return s.lower() or "unknown"

LOG_NAME = re.compile(r"^run_(.+?)_(\d{8})_(\d{6})(?:_([0-9a-f]{6}))?\.log$")            ## the id after the time is new (older logs have none)

def log_system(path: str) -> str:
    """The system (pid_name form) of a cluster run log <project>/logs/run_<system>_<YYYYmmdd>_<HHMMSS>[_<id>].log, or ''."""
    m = LOG_NAME.match(os.path.basename(path.rstrip("/")))
    return m.group(1) if m else ""

def parse_runs(stdout: str) -> dict:
    """{'active': [(system, pid, log)], 'logs': [paths, newest first], 'last': {system: (newest log, exit code or None)},
        'scheduler': 'slurm', 'sge', 'other' (one this window cannot read), 'none', 'error' or None (not asked),
        'jobs': [QueuedJob], 'root_real': the project folder with every link resolved ('' if unknown),
        'unread': {system folder name: number of files SCOPE has not read yet (at most MAX_UNREAD)}}"""
    active, logs, last, scheduler, jobs, root_real, unread = [], [], {}, None, [], "", {}
    for line in stdout.splitlines():
        if line.startswith(RUNLINE):
            parts = line.split()
            if len(parts) >= 5 and parts[3] == "1": active.append((parts[1], parts[2], parts[4]))
        elif line.startswith("__SCOPE_GUI_LOG__"): logs.append(line.split(None, 1)[1].strip())
        elif line.startswith(LASTLINE + " "):
            parts = line.split(None, 2)
            if len(parts) < 3: continue
            system = log_system(parts[2].strip())
            if not system or system in last: continue                        ## newest first: the first log of a system is its last run
            try: code = int(parts[1])
            except ValueError: code = None
            last[system] = (parts[2].strip(), code)
        elif line.startswith(QUEUELINE + " "): scheduler = line.split()[1]
        elif line.startswith(REALROOT): root_real = line[len(REALROOT):].strip()
        elif line.startswith(UNREADLINE + " "):
            parts = line.split(None, 2)
            if len(parts) == 3 and parts[1].isdigit(): unread[parts[2].strip()] = int(parts[1])
        elif line.startswith(JOBLINE + " "):
            fields = line[len(JOBLINE) + 1:].split("|", 3)
            if len(fields) < 3 or not fields[0].strip(): continue
            rest = fields[3] if len(fields) > 3 else ""
            workdir, _, realdir = rest.rpartition("|") if "|" in rest else (rest, "", "")
            jobs.append(QueuedJob(fields[0].strip(), fields[1].strip(), fields[2].strip(), workdir.strip(), realdir.strip()))
    return {"active": active, "logs": logs, "last": last, "scheduler": scheduler, "jobs": jobs, "root_real": root_real, "unread": unread}

def unread_count(found: dict, system: str) -> int:
    """Files of `system` (its name or its pid_name() form) that SCOPE has not read yet, from what list_runs_script found."""
    return sum(n for name, n in found.get("unread", {}).items() if name == system or pid_name(name) == pid_name(system))

def unread_text(n: int, system: str) -> str:
    """What to do about outputs SCOPE has not read yet, in one sentence block (shared by the Cluster page and the Runs page)."""
    many = f"{n}{'+' if n >= MAX_UNREAD else ''} file(s)"
    return (f"{many} of '{system}' on the cluster were written after SCOPE last saved the system, so their results are not in it yet. "
            "SCOPE reads outputs when it runs again: press Run on the cluster again, then Download results… with the system file; "
            "or download the outputs and run the system on this computer.")

def jobs_by_system(jobs: list, root: str, systems: "Iterable[str]"=(), root_real: str="") -> dict:
    """{system: [QueuedJob]} for the jobs that belong to the project in `root`.

    A job that runs in <root>/Computations/<system>/… belongs to that system. A job elsewhere in the project, or one whose folder could not
    be read, is matched by its name, which SCOPE starts with the system name (`<system>_<workflow>_<job>_r<n>`), against `systems`.
    A job whose folder is outside the project belongs to another project and is left out. The folders are compared as written and with
    their links resolved (`root_real`, the job's realdir), so a project reached through a link (/home → /gpfs/home) still finds its jobs."""
    roots = [r for r in dict.fromkeys(x.rstrip("/") for x in (root, root_real)) if r]; out = {}
    names = sorted(set(systems), key=len, reverse=True)                     ## the longest name first: 'water_2' before 'water'
    for job in jobs:
        dirs = [d.rstrip("/") for d in (job.workdir, job.realdir) if d]
        system, inside = "", False
        for d in dirs:
            for r in roots:
                if d == r or d.startswith(r + "/"): inside = True
                comp = r + "/Computations/"
                if not system and d.startswith(comp): system = d[len(comp):].split("/")[0]
        if system: out.setdefault(system, []).append(job); continue
        if dirs and not inside: continue
        for s in names:
            if job.name == s or job.name.startswith(s + "_"): out.setdefault(s, []).append(job); break
    return out

def queued_jobs(found: dict, root: str, system: str) -> list:
    """The jobs of one system in the queue, from what list_runs_script found."""
    return jobs_by_system(found.get("jobs", []), root, [system], found.get("root_real", "")).get(system, [])

def jobs_summary(jobs: list) -> str:
    """'2 running, 1 pending' (running first, then pending, then any other state), or '' for no job."""
    counts = {}
    for job in jobs: counts[job.phase] = counts.get(job.phase, 0) + 1
    order = ["running", "pending"] + sorted(k for k in counts if k not in ("running", "pending"))
    return ", ".join(f"{counts[k]} {k}" for k in order if counts.get(k))
