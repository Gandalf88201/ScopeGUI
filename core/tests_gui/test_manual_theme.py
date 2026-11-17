"""The manual, the theme switch and the step bar."""
import os
import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication
from scope.gui import backend, manual, theme

@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    home = tmp_path / "home"; home.mkdir()
    monkeypatch.setenv("HOME", str(home)); monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))

def app():
    return QApplication.instance() or QApplication([])

def test_manual_is_packaged_and_complete():
    pyproject = open(os.path.join(os.path.dirname(__file__), "..", "pyproject.toml")).read()
    assert '"scope.gui" = ["manual/*.md"]' in pyproject                       # an editable install hides a missing package-data entry
    titles = [t for t, _ in manual.load_sections()]
    assert len(titles) >= 10 and "Troubleshooting" in titles
    from scope.gui.window import STEPS
    for _, _, _, prefix in STEPS: assert any(t.startswith(prefix) for t in titles), prefix

def test_manual_search_and_navigation():
    app(); page = manual.ManualPage()
    hits = manual.search(page.sections, "TMPDIR")
    assert hits and all("TMPDIR" in (page.sections[i][0] + page.sections[i][1]) for i in hits)
    assert manual.search(page.sections, "zzzzqqqq") == []
    assert page.show_section("3 ·") and "Pipeline" in page.view.toPlainText()[:40]
    page.search.setText("TMPDIR"); assert any(not page.list.item(i).isHidden() for i in range(page.list.count())) and page.list.item(0).isHidden()

def test_theme_switch_changes_colours_and_redraws():
    qapp = app()
    from scope.gui.window import MainWindow
    win = MainWindow()
    theme.apply(qapp, "light"); light = qapp.palette().window().color().name()
    theme.apply(qapp, "dark");  dark  = qapp.palette().window().color().name()
    assert light != dark and theme.mode() == "dark" and "Dark" in win.theme_btn.text()
    for role in (theme.QPalette.Button, theme.QPalette.ButtonText, theme.QPalette.PlaceholderText, theme.QPalette.Highlight):
        assert qapp.palette().color(theme.QPalette.Disabled, role).isValid()        # the Disabled group is set too
    win.cycle_theme(); win.cycle_theme(); win.cycle_theme()
    assert backend.load_gui_config()["theme"] == theme.preference()

def test_theme_preference_is_remembered():
    qapp = app()
    backend.save_gui_config({"theme": "dark"})
    from scope.gui.window import MainWindow
    MainWindow(); assert theme.preference() == "dark" and theme.mode() == "dark"
    backend.save_gui_config({"theme": "light"}); MainWindow(); assert theme.mode() == "light"

def test_step_bar_follows_progress(tmp_path):
    app()
    from scope.gui.window import MainWindow
    win = MainWindow()
    assert all(b.text().startswith("○") for b in win.step_buttons)
    env, info = backend.create_environment("t", str(tmp_path / "S"), str(tmp_path / "Y"), str(tmp_path / "C"), str(tmp_path))
    win.session.set_environment(env, info)
    assert win.step_buttons[0].text().startswith("✓") and win.step_buttons[1].text().startswith("○")
    win.session.mark("ran"); assert win.step_buttons[3].text().startswith("✓")
    win.go(2); assert win.tabs.currentIndex() == 2 and win.step_buttons[2].isChecked()
    win.open_manual("5 ·"); assert win.tabs.currentIndex() == len(win.step_buttons)


# ---- SCOPE on this computer
import sys
from scope.gui import backend as be

def test_detect_local_scope_in_this_environment():
    import scope
    info = be.detect_local_scope()
    assert info.runs_ok and info.scope_version == scope.__version__ and info.python_ok and info.cell2mol and info.rdkit and info.pyside6
    assert info.state == "green" and info.short == f"SCOPE {scope.__version__}"
    assert info.editable == ("site-packages" not in info.scope_file)
    assert all(s in ("ok", "warn", "fail") for s, _, _ in info.report()) and not any(s == "fail" for s, _, _ in info.report())

def test_detect_local_scope_when_scope_is_missing_or_python_is_wrong(tmp_path):
    other = "/usr/local/bin/python3"                                              # a Python without SCOPE
    if os.path.exists(other) and be.detect_local_scope(other).probe_error == "":
        info = be.detect_local_scope(other)
        assert not info.runs_ok and info.state == "red" and info.import_error and "SCOPE" in [n for _, n, _ in info.report()]
        assert not info.python_ok or "3.12" not in info.python_version
    gone = be.detect_local_scope(str(tmp_path / "no_such_python"))
    assert gone.state == "red" and gone.probe_error and gone.report()[-1][0] == "fail"

def test_cli_belongs_to_this_environment(monkeypatch):
    bin_dir = os.path.dirname(sys.executable)
    monkeypatch.setenv("PATH", bin_dir + os.pathsep + os.environ.get("PATH", ""))
    info = be.detect_local_scope()
    assert info.cli_path.startswith(bin_dir) and info.cli_same_env and info.state == "green"
    monkeypatch.setenv("PATH", "/usr/bin:/bin")                              # started with the full path: no `scope` command, and that is fine for this window
    info = be.detect_local_scope(); assert info.cli_path == "" and info.state == "green" and any("Terminal" in n and s == "ok" for s, n, _ in info.report())

def test_sidebar_shows_light_and_installed_version(monkeypatch):
    import time
    from PySide6.QtWidgets import QDialog
    qapp = app()
    from scope.gui.window import MainWindow
    win = MainWindow(); t0 = time.time()
    while win.local_task is not None and time.time() - t0 < 60: qapp.processEvents(); time.sleep(0.05)
    qapp.processEvents()
    import scope
    text = win.local_label.text()
    assert "SCOPE active" in text and f"v{scope.__version__}" in text and "●" in text
    assert win.local.state == "green" and "Click for details" in win.local_label.toolTip()
    opened = []
    monkeypatch.setattr(QDialog, "exec", lambda self: opened.append(self.text.toPlainText()) or 0)
    win.local_label.clicked.emit()
    assert opened and "SCOPE" in opened[0] and scope.__version__ in opened[0]
    # a newer or older SCOPE is picked up by the next check (the version is read each time, never stored)
    win.check_local()
    while win.local_task is not None and time.time() - t0 < 120: qapp.processEvents(); time.sleep(0.05)
    assert win.local_checked_at > t0
