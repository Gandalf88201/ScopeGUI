"""The check for newer SCOPE code and the update (scope.gui.updates), on throwaway git repositories: a 'GitHub' (a bare repository),
the user's copy cloned from it, and a colleague's copy that pushes new commits."""
import os
import subprocess
import time
import pytest

from scope.gui import updates
from test_remote import isolated                                            # noqa: F401  (fixture: private HOME and settings)

def run(cwd, *args):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.com", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.com")
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True, env=env).stdout.strip()

def commit(repo, name, text, message):
    path = os.path.join(repo, name); os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh: fh.write(text)
    run(repo, "add", name); run(repo, "commit", "-q", "-m", message)

@pytest.fixture
def repos(tmp_path):
    """(github, mine, colleague): mine follows github's main; colleague pushes to it."""
    github, seed, mine, colleague = (str(tmp_path / n) for n in ("github.git", "seed", "mine", "colleague"))
    run(str(tmp_path), "init", "-q", "--bare", "-b", "main", github)
    run(str(tmp_path), "init", "-q", "-b", "main", seed); commit(seed, "core/pyproject.toml", "[project]\nname='scope-qc'\n", "first"); run(seed, "remote", "add", "origin", github); run(seed, "push", "-q", "origin", "main")
    for path in (mine, colleague): run(str(tmp_path), "clone", "-q", github, path)
    return github, mine, colleague

def push_new(colleague, n=1, name="core/src/a.py"):
    for i in range(n): commit(colleague, name, f"x = {i}\n{time.time()}\n", f"new code {i}")
    run(colleague, "push", "-q", "origin", "HEAD:main")

def test_nothing_new_then_new_commits_are_found_and_applied(repos):
    github, mine, colleague = repos
    st = updates.status(mine)
    assert st.repo == mine and st.branch == "main" and not st.error and st.fetched and [t.ref for t in st.targets] == ["origin/main"]
    assert st.summary() == ("info", "Up to date with origin/main") and not st.can_update() and st.blocker() == ""
    push_new(colleague, 2)
    assert updates.status(mine, fetch=False).followed().behind == 0                                       # without a fetch nothing is known
    before = open(os.path.join(mine, "core/pyproject.toml")).read()
    st = updates.status(mine)
    t = st.followed()
    assert t.behind == 2 and t.ahead == 0 and len(t.new) == 2 and "new code 1" in t.new[0] and st.summary() == ("new", "2 updates on origin/main") and st.can_update()
    assert not os.path.exists(os.path.join(mine, "core/src/a.py")) and open(os.path.join(mine, "core/pyproject.toml")).read() == before   # the check changed no file
    ok, message, recipe = updates.update(mine)
    assert ok and "by 2 commit(s)" in message and not recipe and os.path.exists(os.path.join(mine, "core/src/a.py"))
    assert updates.status(mine, fetch=False).summary() == ("info", "Up to date with origin/main")

def test_a_changed_installation_recipe_is_reported(repos):
    github, mine, colleague = repos
    commit(colleague, "core/pyproject.toml", "[project]\nname='scope-qc'\ndependencies=['numpy']\n", "new dependency"); run(colleague, "push", "-q", "origin", "HEAD:main")
    updates.status(mine); ok, message, recipe = updates.update(mine)
    assert ok and recipe

def test_local_changes_and_local_commits_are_never_overwritten(repos):
    github, mine, colleague = repos
    push_new(colleague)
    with open(os.path.join(mine, "core/pyproject.toml"), "a") as fh: fh.write("# my edit\n")
    st = updates.status(mine)
    assert st.dirty and not st.can_update() and "uncommitted changes" in st.blocker()
    ok, message, _ = updates.update(mine); assert not ok and "uncommitted" in message and "# my edit" in open(os.path.join(mine, "core/pyproject.toml")).read()
    run(mine, "commit", "-q", "-am", "my own change")
    st = updates.status(mine); t = st.followed()
    assert t.ahead == 1 and t.behind == 1 and not st.can_update() and "1 commit(s) of its own" in st.blocker()
    assert not updates.update(mine)[0] and run(mine, "log", "-1", "--format=%s") == "my own change"
    open(os.path.join(mine, "untracked.txt"), "w").write("x")                                          # an untracked file alone does not block
    run(mine, "reset", "-q", "--hard", "origin/main~1"); assert updates.status(mine).can_update()

def test_a_branch_of_its_own_is_compared_with_main_and_a_fork_with_upstream(repos, tmp_path):
    github, mine, colleague = repos
    run(mine, "checkout", "-q", "-b", "gui-demo"); commit(mine, "core/src/gui.py", "gui\n", "gui work")
    push_new(colleague)
    st = updates.status(mine)
    assert st.followed() is None and [t.ref for t in st.targets] == ["origin/main"] and st.targets[0].behind == 1 and st.targets[0].ahead == 1
    assert not st.can_update() and "does not follow a branch" in st.blocker() and "git merge origin/main" in st.blocker()
    fork = str(tmp_path / "fork.git"); run(str(tmp_path), "clone", "-q", "--bare", github, fork)
    run(mine, "remote", "rename", "origin", "upstream"); run(mine, "remote", "add", "origin", fork); run(mine, "push", "-q", "-u", "origin", "gui-demo")
    st = updates.status(mine)
    assert [t.ref for t in st.targets] == ["origin/gui-demo", "upstream/main"] and st.followed().ref == "origin/gui-demo" and st.targets[1].behind == 1
    assert st.summary() == ("info", "Up to date with origin/gui-demo")

def test_no_network_no_git_checkout_and_no_prompt(repos, tmp_path):
    github, mine, colleague = repos
    run(mine, "remote", "set-url", "origin", "https://127.0.0.1:9/nothing.git")                       # nothing listens there
    st = updates.status(mine)
    assert st.error.startswith("origin:") and st.summary() == ("warn", "Update check failed")
    plain = tmp_path / "plain"; plain.mkdir()
    st = updates.status(updates.checkout_of(str(plain)))
    assert st.repo == "" and "not installed from a git checkout" in st.blocker() and st.summary() == ("info", "Not a git install")
    assert updates.local_commit(mine)[0] == run(mine, "rev-parse", "HEAD") and updates.local_commit(str(plain)) == ("", "")

def test_the_daily_check_waits_for_consent(isolated):
    assert updates.setting() == {} and not updates.due()                                                # never asked: no network
    updates.save_setting(enabled=True); assert updates.due()
    updates.save_setting(last=time.time()); assert not updates.due() and updates.due(time.time() + updates.DAY + 1)
    updates.save_setting(enabled=False); assert not updates.due(time.time() + 10 * updates.DAY)

# ---- SCOPE on the cluster: the same commit?
from test_remote import cluster                                             # noqa: F401,E402  (fixture: a fake cluster reached through a fake ssh)
from scope.gui import remote                                                # noqa: E402

def test_the_connection_test_compares_the_commit_on_the_cluster(cluster):
    here = updates.local_commit()
    if not here[0]: pytest.skip("this SCOPE is not a git checkout")
    res = remote.run_script(cluster, remote.probe_script(cluster)); info = remote.parse_probe(res.stdout)
    assert info["scope_commit"] == here[0]                                                                # the fake cluster runs this very copy
    by = {c.name: c for c in remote.evaluate_probe(cluster, res, "any", here)}
    assert by["SCOPE on the cluster"].status == "ok" and "the same code as here" in by["SCOPE on the cluster"].detail
    by = {c.name: c for c in remote.evaluate_probe(cluster, res, "any", ("f" * 40, "2020-01-01"))}
    assert by["SCOPE on the cluster"].status == "warn" and "different code" in by["SCOPE on the cluster"].detail and here[0][:7] in by["SCOPE on the cluster"].detail

# ---- the window
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])

def wait(app, fn, seconds=30):
    t0 = time.time()
    while time.time() - t0 < seconds:
        app.processEvents()
        if fn(): return True
        time.sleep(0.05)
    return False

def test_the_window_asks_first_then_checks_updates_and_restarts(repos, monkeypatch):
    app = qapp(); from PySide6.QtCore import QProcess
    from PySide6.QtWidgets import QMessageBox
    from scope.gui.window import MainWindow
    from scope.gui.update_view import UpdatesDialog
    github, mine, colleague = repos
    fetches, real = [], updates.status
    monkeypatch.setattr(updates, "status", lambda repo=None, fetch=True: (fetches.append(fetch), real(repo, fetch))[1])
    win = MainWindow(); assert wait(app, lambda: win.update_task is None)
    assert fetches == [False]                                                                            # GitHub is not asked before the user allows it
    win.update_repo = mine; win.check_updates(); assert wait(app, lambda: win.update_task is None)
    assert "Check for updates?" in win.update_label.text() and not win.update_label.isHidden() and "until you allow it" in win.update_label.toolTip()
    d = UpdatesDialog(win, win); assert not d.auto.isChecked() and "This copy" in d.head.text(); d.accept()
    assert updates.setting()["enabled"] is False and "Up to date" in win.update_label.text() and "daily check is off" in win.update_label.toolTip()       # closing without ticking answers "no"
    push_new(colleague, 2)
    d = UpdatesDialog(win, win); d.auto.setChecked(True)                                                 # allowed: the daily check is due at once
    assert wait(app, lambda: win.update_task is None and win.update_status.fetched)
    assert fetches[-1] is True and "2 updates" in win.update_label.text() and "origin/main" in win.update_label.text() and updates.setting()["last"] > 0
    assert d.update_btn.isEnabled() and "new code 1" in d.log.toPlainText()
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes))
    d.apply(); assert wait(app, lambda: win.updated and win.update_task is None)
    assert os.path.exists(os.path.join(mine, "core/src/a.py")) and d.restart_btn.isVisibleTo(d) and not d.update_btn.isEnabled() and "by 2 commit(s)" in d.message.text()
    assert "Restart to update" in win.update_label.text()
    started = []; monkeypatch.setattr(QProcess, "startDetached", staticmethod(lambda *a: started.append(a) or True))
    d.reject(); win.show(); win.restart()
    assert started and started[0][1][-1] == "gui" and not win.isVisible()
