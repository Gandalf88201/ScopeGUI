"""User name and port of a cluster profile: parsing what users paste, validation, and that every ssh and rsync call carries them."""
import os
import pytest
from test_remote import isolated, cluster, local, WATER                       # noqa: F401  (fixtures)
from scope.gui import remote, workspaces

@pytest.mark.parametrize("text, expected", [
    ("pirineus3.csuc.cat",                                   ("pirineus3.csuc.cat", "", "")),
    ("tfrancese@pirineus3.csuc.cat",                         ("pirineus3.csuc.cat", "tfrancese", "")),
    ("ssh -p 2122 tfrancese@pirineus3.csuc.cat",             ("pirineus3.csuc.cat", "tfrancese", "2122")),
    ("ssh tfrancese@pirineus3.csuc.cat -p 2122",             ("pirineus3.csuc.cat", "tfrancese", "2122")),
    ("ssh -p2122 -l tfrancese pirineus3.csuc.cat",           ("pirineus3.csuc.cat", "tfrancese", "2122")),
    ("/usr/bin/ssh -X -i ~/.ssh/id_ed25519 -p 22 me@h.org",  ("h.org", "me", "22")),
    ("ssh -o Port=2200 -o User=jo login.hpc.eu",             ("login.hpc.eu", "jo", "2200")),
    ("tfrancese@pirineus3.csuc.cat:2122",                    ("pirineus3.csuc.cat", "tfrancese", "2122")),
    ("ssh://tfrancese@pirineus3.csuc.cat:2122",              ("pirineus3.csuc.cat", "tfrancese", "2122")),
    ("ssh -J jump.org user@inner.org",                       ("inner.org", "user", "")),        # the jump host is an option value, not the target
])
def test_parse_what_users_paste(text, expected):
    got = remote.parse_ssh_target(text)
    assert (got["host"], got["user"], got["port"]) == expected

def test_parse_gives_up_on_nothing():
    assert remote.parse_ssh_target("") is None and remote.parse_ssh_target("ssh -p 22") is None and remote.parse_ssh_target("ssh 'unclosed") is None

def test_user_and_port_are_validated():
    ok = remote.Profile("c", "h", "/s", "", "/p", "/e", user="tfrancese", port="2122")
    assert remote.validate_profile(ok) == []
    assert "port" in remote.connection_problems(remote.Profile("c", "h", "/s", user="u", port="22a"))
    assert "port" in remote.connection_problems(remote.Profile("c", "h", "/s", port="70000"))
    assert "user" in remote.connection_problems(remote.Profile("c", "h", "/s", user="-oProxyCommand=x"))      # option injection through the user
    assert "user" in remote.connection_problems(remote.Profile("c", "h", "/s", user="my name"))
    assert "host" in remote.connection_problems(remote.Profile("c", "u@h", "/s"))                             # user written in the host field
    assert "host" in remote.connection_problems(remote.Profile("c", "h:2122", "/s"))

def test_every_command_carries_port_and_user():
    p = remote.Profile("c", "pirineus3.csuc.cat", "/s", "", "/p", "/e", user="tfrancese", port="2122")
    argv = remote.ssh_argv(p)
    assert argv[argv.index("-p") + 1] == "2122" and argv[argv.index("-l") + 1] == "tfrancese" and argv.index("-l") < argv.index("pirineus3.csuc.cat")
    rs = remote.rsync_argv("a/", "pirineus3.csuc.cat:/p/", p=p); e = rs[rs.index("-e") + 1]
    assert "-p 2122" in e and "-l tfrancese" in e
    m = remote.master_command(p)
    assert "-p 2122" in m and "-l tfrancese" in m and m.endswith("pirineus3.csuc.cat")                         # same socket name as the GUI's commands
    assert remote.ssh_display(p) == "ssh -p 2122 -l tfrancese pirineus3.csuc.cat"
    plain = remote.Profile("c", "alias", "/s")                                                                 # empty fields: ~/.ssh/config decides
    assert "-p" not in remote.ssh_argv(plain) and "-l" not in remote.ssh_argv(plain) and remote.master_command(plain).endswith("alias")

def test_profiles_keep_user_and_port_and_old_ones_still_load():
    remote.save_profile(remote.Profile("csuc", "pirineus3.csuc.cat", "/s", user="tfrancese", port="2122"), connection_only=True)
    got = remote.load_profiles()["csuc"]
    assert (got.user, got.port) == ("tfrancese", "2122")
    from scope.gui import backend
    backend.save_gui_config({"profiles": {"old": {"name": "old", "host": "h", "scope_bin": "/s", "activate": "", "remote_root": "", "remote_env": ""}}})
    old = remote.load_profiles()["old"]
    assert (old.user, old.port) == ("", "")

def test_fake_cluster_works_through_a_port_and_a_user(cluster, local, tmp_path, monkeypatch):
    """Probe, upload (rsync) and a run, with port and user set: the fake ssh records that both arrive on every call."""
    log = tmp_path / "ssh.log"; monkeypatch.setenv("FAKE_SSH_LOG", str(log))
    p = remote.Profile(**{**cluster.__dict__, "user": "tfrancese", "port": "2122"})
    env, info = local
    assert remote.run_script(p, remote.remote_dirs_script(p, "water")).ok
    inp = tmp_path / "opt.scope"; inp.write_text("&environment\n/\n")
    done = remote.sync(remote.upload_items(p, info, "water", [str(inp)]), dry_run=False, p=p)
    assert all(r.ok for _, r, _ in done), [r.stderr for _, r, _ in done]
    assert os.path.isfile(os.path.join(p.remote_root, "Systems", "water", "water.npy"))
    calls = log.read_text().splitlines()
    assert len(calls) >= 4 and all("-p 2122 -l tfrancese" in c for c in calls)

def test_export_import_carry_user_and_port(tmp_path):
    remote.save_profile(remote.Profile("hpc", "login1", "/s/scope", user="me", port="2122"), connection_only=True)
    ws = workspaces.Workspace(name="W"); ws.profile = "hpc"
    data = workspaces.export_data(ws, remote.load_profiles()["hpc"])
    assert data["profile"]["user"] == "me" and data["profile"]["port"] == "2122"
    _, notes = workspaces.import_data(data, remote.load_profiles())
    assert not any("different profile" in n for n in notes)                         # same account: not duplicated
    other = {**data, "profile": {**data["profile"], "port": "22"}}
    imported, notes = workspaces.import_data(other, remote.load_profiles())
    assert imported.profile == "hpc_2" and remote.load_profiles()["hpc_2"].port == "22"   # another port is another connection

def test_cluster_page_splits_a_pasted_ssh_command(monkeypatch):
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from scope.gui.window import MainWindow
    app = QApplication.instance() or QApplication([])
    tab = MainWindow().remote_tab; tab.new_profile()
    tab.host.setEditText("ssh -p 2122 tfrancese@pirineus3.csuc.cat"); tab.split_host()
    assert (tab.host.currentText(), tab.user.text(), tab.port.text(), tab.name.text()) == ("pirineus3.csuc.cat", "tfrancese", "2122", "pirineus3")
    tab.scope_bin.setText("~/miniconda3/envs/scope/bin/scope")
    assert tab.save_profile()
    saved = remote.load_profiles()["pirineus3"]
    assert (saved.host, saved.user, saved.port) == ("pirineus3.csuc.cat", "tfrancese", "2122")
    tab.port.setText("abc"); app.processEvents()
    assert "Port:" in tab.hint.text()
