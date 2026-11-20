"""The Cluster page on Windows, simulated on macOS/Linux: no os.getuid, no shared SSH connection (ControlMaster), no password window,
no rsync. The fake ssh of test_remote runs the 'cluster' commands locally, so the tar transfers are exercised end to end."""
import os
import time
import pytest

from scope.gui import remote, transfer
from test_remote import isolated, local, cluster, WATER                      # noqa: F401  (fixtures: temp HOME, fake ssh)

@pytest.fixture
def windows(monkeypatch):
    """What differs on Windows: os has no getuid, ssh cannot share a connection, rsync is not installed."""
    monkeypatch.delattr(os, "getuid", raising=False)
    monkeypatch.setattr(remote, "shares_connection", lambda: False)
    monkeypatch.setattr(remote, "have_rsync", lambda: False)

def test_no_getuid_no_crash_and_no_shared_connection(windows):
    p = remote.Profile("t", "csuc", user="me", port="2122")
    assert remote.control_path()                                                       # the reported crash: AttributeError on os.getuid
    assert not any("Control" in o for o in remote.ssh_options(p))                     # Windows' OpenSSH cannot share a connection
    assert "BatchMode=yes" in remote.ssh_options(p)
    assert remote.connection_alive(p) is False and remote.close_connection(p) is True

def test_key_helper_is_valid_and_targets_the_account():
    compile(remote.KEY_HELPER, "key_helper", "exec")
    argv = remote.key_setup_argv(remote.Profile("t", "csuc", user="me", port="2122"))
    assert argv[1:3] == ["-I", "-c"] and '"-p", "2122", "-l", "me", "csuc"' in argv[-1]
    assert "authorized_keys" in remote.key_setup_command(remote.Profile("t", "csuc", user="me", port="2122"))

def test_upload_without_rsync_copies_with_tar(windows, local, cluster, tmp_path):
    env, info = local; p = cluster
    items = remote.upload_items(p, info, "water", [])
    dry = remote.sync(items, dry_run=True, p=p)
    assert all(res.ok for _, res, _ in dry) and any("water.npy" in l for _, _, lines in dry for l in lines)
    assert not os.path.exists(os.path.join(p.remote_root, "Systems", "water", "water.npy"))           # a preview copies nothing
    done = remote.sync(items, dry_run=False, p=p)
    assert all(res.ok for _, res, _ in done), [res.stderr for _, res, _ in done]
    assert os.path.isfile(os.path.join(p.remote_root, "Systems", "water", "water.npy")) and os.path.isfile(os.path.join(p.remote_root, "Sources", "water", "water.xyz"))

def test_download_and_push_without_rsync(windows, local, cluster):
    env, info = local; p = cluster
    comp = os.path.join(p.remote_root, "Computations", "water", "demo"); os.makedirs(comp)
    with open(os.path.join(comp, "w_opt.log"), "w") as fh: fh.write("Normal termination\n")
    old = time.time() - 3600; os.utime(os.path.join(comp, "w_opt.log"), (old, old))
    os.makedirs(os.path.join(p.remote_root, "Systems", "water")); open(os.path.join(p.remote_root, "Systems", "water", "water.npy"), "wb").write(b"cluster npy")
    out = transfer.download(p, info, "water", ["demo/w_opt.log"], with_system=True)
    here = os.path.join(info.computations_path, "water", "demo", "w_opt.log")
    assert out["files"].ok and open(here).read() == "Normal termination\n" and abs(os.path.getmtime(here) - old) < 2       # dates kept
    assert "replaced" in out["system"] and open(os.path.join(info.systems_path, "water", "water.npy"), "rb").read() == b"cluster npy"
    with open(os.path.join(info.computations_path, "water", "demo", "w_freq.com"), "w") as fh: fh.write("#p freq\n")
    assert transfer.push_files(p, info, "water", ["demo/w_freq.com"]).ok and os.path.isfile(os.path.join(comp, "w_freq.com"))

def test_cluster_page_in_windows_mode(windows, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen"); pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from scope.gui.window import MainWindow
    app = QApplication.instance() or QApplication([])
    opened = []; monkeypatch.setattr(remote, "open_key_setup", lambda p: opened.append(p.host) or remote.Result(0))
    win = MainWindow(); tab = win.remote_tab
    tab.name.setText("csuc"); tab.host.setEditText("login.csuc.cat"); tab.user.setText("me"); tab.port.setText("2122"); tab.scope_bin.setText("/s")
    tab.refresh_connection()                                                           # used to raise AttributeError: os.getuid
    assert tab.connect_btn.text() == "Set up key login…" and tab.connect_btn.isEnabled() and tab.disconnect_btn.isHidden() and "key login" in tab.conn_badge.text()
    tab.connect_cluster()
    assert opened == ["login.csuc.cat"] and "console window" in tab.log.toPlainText()
    assert "Set up key login" in tab.reconnect_hint(remote.Result(255, "", "me@login: Permission denied (publickey)."))
