"""The Connect… button of the Cluster page: the password window, the status badge, Disconnect, and that nothing is kept."""
import os
import pytest
from test_remote import isolated                                               # noqa: F401  (autouse: own HOME and GUI settings, so no test touches the real ones)
from test_connect import FAKE, login, script                                  # noqa: F401  (fixtures)
from scope.gui import remote

pytestmark = pytest.mark.skipif(not remote.can_login_here(), reason="needs a pseudo-terminal")

def make_tab(login):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from scope.gui.window import MainWindow
    app = QApplication.instance() or QApplication([])
    win = MainWindow(); tab = win.remote_tab
    tab.name.setText("fake"); tab.host.setEditText(login.host); tab.user.setText(login.user); tab.port.setText(login.port); tab.scope_bin.setText("/s"); tab.root.setText("~/p"); tab.env_file.setText("~/p/e.npy")
    return app, win, tab

def wait(app, tab, seconds=60):
    import time
    t0 = time.time()
    while tab.busy and time.time() - t0 < seconds: app.processEvents(); time.sleep(0.03)
    app.processEvents()

def test_connect_asks_in_a_window_then_shows_connected_and_disconnect_closes_it(login, monkeypatch):
    app, win, tab = make_tab(login)
    asked = []
    monkeypatch.setattr(tab, "ask_login", lambda context, prompt, kind: (asked.append((prompt, kind)), "s3cret")[1])
    monkeypatch.setattr(tab, "test_connection", lambda: asked.append("tested"))                 # the probe itself is covered elsewhere
    tab.refresh_connection()
    assert not tab.alive and "Not connected" in tab.conn_badge.text() and tab.connect_btn.isEnabled() and not tab.disconnect_btn.isEnabled()
    tab.connect_cluster(); wait(app, tab)
    assert asked == [("me@fake's password:", "secret"), "tested"]                                # the window was asked once, then the cluster was tested by itself
    assert tab.alive and "Connected to fakehost" in tab.conn_badge.text() and not tab.connect_btn.isEnabled() and tab.disconnect_btn.isEnabled()
    assert "s3cret" not in tab.log.toPlainText() and "s3cret" not in tab.status.text()
    tab.disconnect_cluster(); app.processEvents()
    assert not tab.alive and "Not connected" in tab.conn_badge.text() and "closed" in tab.log.toPlainText()

def test_cancelling_the_window_connects_nothing(login, monkeypatch):
    app, win, tab = make_tab(login)
    monkeypatch.setattr(tab, "ask_login", lambda *a: None)
    tab.connect_cluster(); wait(app, tab)
    assert not tab.alive and "cancel" in tab.status.text().lower()

def test_a_wrong_password_says_what_to_do(login, monkeypatch):
    app, win, tab = make_tab(login)
    monkeypatch.setattr(tab, "ask_login", lambda *a: "wrong")
    tab.connect_cluster(); wait(app, tab)
    assert not tab.alive and "Could not connect" in tab.status.text() and "Permission denied" in tab.log.toPlainText() and "wrong" not in tab.log.toPlainText()

def test_connect_checks_the_host_before_asking(login, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    app, win, tab = make_tab(login); tab.host.setEditText("")
    told = []; monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: told.append(a[2])))
    monkeypatch.setattr(tab, "ask_login", lambda *a: pytest.fail("must not ask without a host"))
    tab.connect_cluster()
    assert told and "SSH host" in told[0] and not tab.alive

def test_the_page_is_grouped_in_cards_and_keeps_every_field(login):
    app, win, tab = make_tab(login)
    from PySide6.QtWidgets import QFrame, QLabel
    titles = [l.text() for l in tab.findChildren(QLabel) if l.objectName() == "sectiontitle"]
    assert titles == ["1 · Cluster", "2 · Project on the cluster  (this workspace)", "3 · Transfer and run"]                   # in the order of use
    assert len([f for f in tab.findChildren(QFrame) if f.objectName() == "card"]) == 3
    assert sum(1 for b in (tab.connect_btn, tab.test_btn, tab.save_btn, tab.run_btn) if b.property("primary")) == 2          # Connect… and Run, one main action each
    for w in (tab.name, tab.host, tab.user, tab.port, tab.scope_bin, tab.activate, tab.root, tab.env_file): assert tab.isAncestorOf(w)   # every field is still there

def test_a_complete_profile_is_one_line_until_edit(login):
    app, win, tab = make_tab(login); win.resize(1240, 900); win.show(); win.show_step("cluster"); app.processEvents()
    assert tab.save_profile(); tab.select_profile("fake"); tab.edit_btn.setChecked(False); app.processEvents()
    assert not tab.profile_box.isVisible() and login.host in tab.summary.text() and "/s" in tab.summary.text()
    tab.edit_btn.setChecked(True); app.processEvents(); assert tab.profile_box.isVisible()
    tab.edit_btn.setChecked(False); tab.new_profile(); app.processEvents(); assert tab.profile_box.isVisible()               # a new profile opens its fields by itself
    assert not tab.pre_up.isVisible() and not tab.table.isVisible()                                                          # Upload previews and asks; test details appear after a test

def test_the_advanced_line_is_folded_until_asked_or_needed(login):
    app, win, tab = make_tab(login); win.resize(1240, 900); win.show(); win.show_step("cluster"); app.processEvents()
    assert not tab.adv_box.isVisible()
    tab.adv_btn.setChecked(True); app.processEvents(); assert tab.adv_box.isVisible() and tab.adv_btn.text().startswith("▾")
    tab.adv_btn.setChecked(False); app.processEvents(); assert not tab.adv_box.isVisible()
    tab.activate.setText("module load scope"); tab.scope_bin.setText(""); assert tab.save_profile()                              # a profile that starts scope with a line opens the box by itself
    tab.new_profile(); app.processEvents(); assert not tab.adv_btn.isChecked()
    tab.select_profile("fake"); app.processEvents(); assert tab.adv_btn.isChecked() and tab.adv_box.isVisible() and tab.activate.text() == "module load scope"

def test_the_password_window_itself_and_the_host_key_question(login, monkeypatch):
    app, win, tab = make_tab(login)
    from PySide6.QtWidgets import QDialog, QLineEdit, QMessageBox
    from scope.gui.remote_tab import LoginDialog
    d = LoginDialog(tab, "csuc", "Permission denied, please try again.", "me@csuc's password:")             # the real dialog, built for once
    from PySide6.QtWidgets import QLabel
    assert d.edit.echoMode() == QLineEdit.Password and any("Permission denied" in l.text() for l in d.findChildren(QLabel))
    d.edit.setText("abc"); d.reveal.setChecked(True); assert d.edit.echoMode() == QLineEdit.Normal
    d.reveal.setChecked(False); assert d.edit.echoMode() == QLineEdit.Password and d.answer() == "abc"
    monkeypatch.setattr(LoginDialog, "exec", lambda self: (self.edit.setText("pw"), QDialog.Accepted)[1])
    assert tab.ask_login("ctx", "Password:", "secret") == "pw"
    monkeypatch.setattr(LoginDialog, "exec", lambda self: QDialog.Rejected)
    assert tab.ask_login("ctx", "Password:", "secret") is None
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes))
    assert tab.ask_login("ED25519 key fingerprint is SHA256:abc.", "Are you sure (yes/no/[fingerprint])?", "confirm") == "yes"
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.No))
    assert tab.ask_login("fp", "Are you sure (yes/no)?", "confirm") is None

def test_a_broken_password_window_is_reported_and_is_not_taken_for_a_cancel(login, monkeypatch):
    app, win, tab = make_tab(login)
    def boom(*a): raise RuntimeError("no window")
    monkeypatch.setattr(tab, "ask_login", boom)
    tab.connect_cluster(); wait(app, tab)
    assert not tab.alive and "could not be shown" in tab.log.toPlainText() and "RuntimeError: no window" in tab.log.toPlainText()
