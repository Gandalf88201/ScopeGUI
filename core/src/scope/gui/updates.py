"""Checks whether newer SCOPE code is available, for a SCOPE installed from a git checkout (no Qt).

SCOPE is installed by the launcher as a development install of the folder it was cloned into, so newer code is newer commits on
GitHub. Two operations, kept apart:

- check: `git fetch` of the branches compared against: the main branch of the GitHub repository this copy follows (updates come
  from there, whatever branch is checked out), and the main branch of the main remote when it is another one.
  A fetch only updates git's record of what GitHub holds; the files of SCOPE are not changed. It never asks for a password: a
  remote that needs one makes the check fail with a message instead.
- update: `git merge --ff-only` of that main branch into the current branch, only when nothing here would be lost or mixed: no uncommitted changes to
  tracked files and no local commits that the branch on GitHub lacks. Anything else is left to the user, with an explanation.

The check runs only once the user has allowed it (or when they press Check now); its setting and the time of the last check are
kept in the GUI preferences under 'update_check'.
"""
import os
import subprocess
import time
from dataclasses import dataclass, field

DAY        = 24 * 3600
CONFIG_KEY = "update_check"
MAX_LOG    = 30                                                             ## commits listed in the details

def git(repo: str, *args, timeout: int=30) -> tuple:
    """Runs git in `repo` without any prompt (no password, no editor). Returns (returncode, stdout, stderr); git missing gives (-1, '', message)."""
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_ASKPASS="echo", SSH_ASKPASS="echo", GIT_SSH_COMMAND="ssh -o BatchMode=yes", LC_ALL="C", GIT_EDITOR="true")
    try:
        done = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, timeout=timeout, env=env, stdin=subprocess.DEVNULL)
        return done.returncode, done.stdout.strip(), done.stderr.strip()
    except subprocess.TimeoutExpired: return -2, "", f"git {args[0]} did not answer within {timeout} s"
    except OSError as exc: return -1, "", f"git could not be started ({exc})"

def scope_folder() -> str:
    """Folder of the SCOPE package this window imports."""
    import scope
    return os.path.dirname(os.path.realpath(scope.__file__))

def checkout_of(path: str=None) -> str:
    """Top folder of the git checkout that holds `path` (by default SCOPE's package), or '' when SCOPE was not installed from a checkout."""
    code, out, _ = git(path or scope_folder(), "rev-parse", "--show-toplevel", timeout=10)
    return out if code == 0 and out else ""

def local_commit(path: str=None) -> tuple:
    """(full commit hash, commit date YYYY-MM-DD) of the checkout that holds `path` (by default SCOPE's package), or ('', '')."""
    code, out, _ = git(path or scope_folder(), "log", "-1", "--format=%H %cs", timeout=10)
    parts = out.split() if code == 0 else []
    return (parts[0], parts[1]) if len(parts) == 2 else ("", "")

def remote_main(repo: str, remote: str) -> str:
    """The main branch of `remote` as git knows it: what its HEAD points to (set by a clone), otherwise '<remote>/main'."""
    code, head, _ = git(repo, "symbolic-ref", "--short", f"refs/remotes/{remote}/HEAD", timeout=10)
    return head if code == 0 and head else f"{remote}/main"

def source(repo: str) -> str:
    """The branch updates come from: the main branch of the GitHub repository this copy follows (the remote of the current branch's
    upstream, otherwise 'origin'), whatever branch is checked out here. '' when there is no such remote."""
    _, remotes, _ = git(repo, "remote", timeout=10); remotes = remotes.split()
    code, tracked, _ = git(repo, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}", timeout=10)
    remote = next((r for r in remotes if code == 0 and tracked.startswith(r + "/")), "origin" if "origin" in remotes else "")
    return remote_main(repo, remote) if remote else ""

def targets(repo: str) -> list:
    """The remote branches to compare with: first the one updates come from (see source), then, for information, the main branch of
    the main remote ('upstream' when it exists, as in a fork, otherwise 'origin') when it is another branch."""
    out = [source(repo)] if source(repo) else []
    _, remotes, _ = git(repo, "remote", timeout=10); remotes = remotes.split()
    main = "upstream" if "upstream" in remotes else ("origin" if "origin" in remotes else "")
    if main and remote_main(repo, main) not in out: out.append(remote_main(repo, main))
    return out

@dataclass
class Target:
    """One remote branch compared with this copy.

    Attributes:
        ref (str):      For instance 'origin/main'.
        followed (bool): Whether updates come from it (only then can Update apply it): the main branch of the repository this copy follows.
        exists (bool):  Whether git knows the branch (after a fetch).
        behind (int):   Commits it has that this copy lacks.
        ahead (int):    Commits this copy has that it lacks.
        new (list):     The commits this copy lacks, newest first, as 'hash date subject' (at most MAX_LOG).
    """
    ref:      str
    followed: bool = False
    exists:   bool = False
    behind:   int  = 0
    ahead:    int  = 0
    new:      list = field(default_factory=list)

@dataclass
class UpdateStatus:
    """What the check found.

    Attributes:
        repo (str):     The checkout ('' if SCOPE is not installed from one).
        branch (str):   The current branch ('' when no branch is checked out).
        head (str), date (str): The current commit (short hash) and its date.
        dirty (bool):   Uncommitted changes to files git tracks.
        targets (list): Target rows.
        fetched (bool): Whether this status follows a fetch (otherwise it uses what the last fetch brought).
        error (str):    Why the check could not be completed ('' if it was).
        checked (float): When.
    """
    repo:    str   = ""
    branch:  str   = ""
    head:    str   = ""
    date:    str   = ""
    dirty:   bool  = False
    targets: list  = field(default_factory=list)
    fetched: bool  = False
    error:   str   = ""
    checked: float = 0.0

    def followed(self) -> "Target | None":
        return next((t for t in self.targets if t.followed), None)

    def can_update(self) -> bool:
        t = self.followed()
        return bool(self.branch and t and t.exists and t.behind and not t.ahead and not self.dirty)

    def blocker(self) -> str:
        """Why Update cannot be applied here ('' if it can, or if there is nothing to apply)."""
        t = self.followed()
        if not self.repo:   return "SCOPE was not installed from a git checkout, so this window cannot update it. Update it the way it was installed (for instance pip install -U)."
        if not self.branch: return "No branch is checked out (detached HEAD). Check out a branch, then update."
        if t is None:       return "This copy has no remote repository on GitHub (no 'origin'), so there is nothing to update it from."
        if not t.behind:    return ""
        if t.ahead:         return f"'{self.branch}' has {t.ahead} commit(s) of its own that {t.ref} lacks, so it cannot simply move forward. Bring the new commits in with git (git merge {t.ref}, or git rebase {t.ref})."
        if self.dirty:      return "There are uncommitted changes in the SCOPE folder. Commit or stash them first (git stash), then update."
        return ""

    def summary(self) -> tuple:
        """(kind, short text) for the sidebar: kind is 'new' (updates to apply), 'info' (nothing to do) or 'warn'."""
        if self.error: return "warn", "Update check failed"
        if not self.repo: return "info", "Not a git install"
        t = self.followed() or next((x for x in self.targets if x.exists), None)
        if t is None: return "info", "No remote branch to compare"
        if t.behind: return "new", f"{t.behind} update{'s' if t.behind > 1 else ''} on {t.ref}"
        return "info", f"Up to date with {t.ref}"

def status(repo: str=None, fetch: bool=True) -> UpdateStatus:
    """Compares this copy with the remote branches (see targets). With fetch=True the remote branches are fetched first (network);
    with fetch=False only what the last fetch brought is used (no network). Never raises."""
    st = UpdateStatus(repo=repo if repo is not None else checkout_of(), checked=time.time())
    if not st.repo: return st
    try:
        _, st.branch, _ = git(st.repo, "symbolic-ref", "--short", "-q", "HEAD", timeout=10)
        _, head, _ = git(st.repo, "log", "-1", "--format=%h %cs", timeout=10); st.head, st.date = (head.split() + ["", ""])[:2]
        code, porcelain, _ = git(st.repo, "status", "--porcelain", "--untracked-files=no", timeout=30); st.dirty = code == 0 and bool(porcelain)
        refs = targets(st.repo); src = source(st.repo)
        if fetch:
            errors = []
            for remote in dict.fromkeys(r.split("/")[0] for r in refs):
                code, _, err = git(st.repo, "fetch", "--quiet", "--no-tags", remote, timeout=90)
                if code != 0: errors.append(f"{remote}: " + ((err.splitlines() or [f"exit code {code}"])[-1]))
            st.fetched, st.error = True, "; ".join(errors)
        for ref in refs:
            t = Target(ref, followed=(ref == src))
            t.exists = git(st.repo, "rev-parse", "--verify", "-q", ref, timeout=10)[0] == 0
            if t.exists:
                code, counts, _ = git(st.repo, "rev-list", "--left-right", "--count", f"HEAD...{ref}", timeout=30)
                if code == 0 and len(counts.split()) == 2: t.ahead, t.behind = (int(x) for x in counts.split())
                if t.behind: t.new = git(st.repo, "log", f"--max-count={MAX_LOG}", "--format=%h %cs %s", f"HEAD..{ref}", timeout=30)[1].splitlines()
            st.targets.append(t)
    except Exception as exc:
        st.error = f"{type(exc).__name__}: {exc}"
    return st

def update(repo: str) -> tuple:
    """Moves the current branch forward to the main branch updates come from (fast-forward only), after checking again that nothing would be
    lost. Returns (ok, message, needs_reinstall): needs_reinstall is True when the installation recipe (core/pyproject.toml) changed."""
    st = status(repo, fetch=False)
    if not st.can_update(): return False, st.blocker() or "There is nothing to update.", False
    t = st.followed()
    code, before, _ = git(repo, "rev-parse", "HEAD", timeout=10)
    code, _, err = git(repo, "merge", "--ff-only", "--quiet", t.ref, timeout=120)
    if code != 0: return False, "git could not update: " + ((err.splitlines() or [f"exit code {code}"])[-1]), False
    _, changed, _ = git(repo, "diff", "--name-only", before, "HEAD", timeout=30)
    recipe = any(name.endswith("pyproject.toml") for name in changed.splitlines())
    _, head, _ = git(repo, "log", "-1", "--format=%h %cs", timeout=10)
    return True, f"Updated '{st.branch}' by {t.behind} commit(s) to {head}.", recipe

def setting() -> dict:
    """The 'update_check' preferences: {'enabled': True/False, or missing when the user was not asked yet; 'last': time of the last fetch}."""
    from scope.gui import backend
    value = backend.load_gui_config().get(CONFIG_KEY)
    return value if isinstance(value, dict) else {}

def save_setting(**changes) -> None:
    from scope.gui import backend
    backend.save_gui_config({CONFIG_KEY: dict(setting(), **changes)})

def due(now: float=None) -> bool:
    """Whether the daily check should run now: allowed by the user and not run in the last 24 hours."""
    s = setting(); now = now or time.time()
    return s.get("enabled") is True and now - float(s.get("last", 0)) >= DAY
