"""The window must change size freely (a Windows laptop at 1366x768, a half-screen window): no page may force a minimum width or height
larger than a small screen, pages scroll instead, and windows never open larger than the screen's free area."""
import pytest

from test_remote import isolated                                             # noqa: F401  (fixture: temp HOME, real settings untouched)

SMALL = (1000, 640)                                                         # a 1366x768 laptop at 125 % scaling, minus the taskbar

@pytest.fixture
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])

def test_main_window_shrinks_and_grows(app):
    from PySide6.QtWidgets import QScrollArea
    from scope.gui.window import MainWindow, STEPS
    w = MainWindow(); w.show(); app.processEvents()
    hint = w.minimumSizeHint()
    assert hint.width() <= SMALL[0] and hint.height() <= SMALL[1], f"window cannot shrink below {hint.toTuple()}"
    for size in ((900, 560), SMALL, (1600, 1000)):
        w.resize(*size); app.processEvents(); assert w.size().toTuple() == size
    for i, (key, *_) in enumerate(STEPS):                                   # every page scrolls instead of forcing its size on the window
        assert w.tabs.widget(i).findChild(QScrollArea) is not None, f"page {key} does not scroll"
    w.resize(*SMALL)
    for key in ("pipeline", "cluster", "systems", "run", "results"):        # the busy pages fit their width at the small size: no sideways scrolling
        w.show_step(key); app.processEvents()
        area = w.tabs.currentWidget().findChild(QScrollArea)
        assert area.widget().minimumSizeHint().width() <= area.viewport().width(), f"page {key} needs a wider window"
    w.close()

def test_dialogs_fit_a_small_screen(app, tmp_path):
    from scope.gui.editor import InputEditor
    from scope.gui.review_view import ReviewDialog
    for d in (InputEditor(None, "", ""), ReviewDialog(None, [], "Here.")):
        hint = d.minimumSizeHint()
        assert hint.width() <= SMALL[0] and hint.height() <= SMALL[1], f"{type(d).__name__} cannot shrink below {hint.toTuple()}"
        d.close()

def test_windows_never_open_larger_than_the_screen(app):
    from PySide6.QtWidgets import QWidget
    from scope.gui import theme
    w = QWidget(); free = w.screen().availableGeometry()
    theme.fit(w, 300, 200); assert w.size().toTuple() == (300, 200)          # small enough: the preferred size
    theme.fit(w, 20000, 20000)                                              # too big: clamped to the free area
    assert w.width() <= free.width() and w.height() <= free.height() and w.width() < 20000
