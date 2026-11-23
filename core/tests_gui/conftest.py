"""Shared safety net for the GUI tests."""
import pytest

@pytest.fixture(autouse=True)
def dialogs_fail_instead_of_waiting(monkeypatch):
    """A message box that a test did not expect would wait for a click that never comes (offscreen, nobody to press OK) and hang
    the whole run. Make it fail the test with its text instead. A test that expects a dialog patches it itself, which wins."""
    try: from PySide6.QtWidgets import QMessageBox
    except ImportError: return
    for name in ("warning", "information", "critical", "question", "about"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(lambda *a, _n=name, **k: pytest.fail(f"unexpected QMessageBox.{_n}: {a[1:3]}")))

def pytest_sessionfinish(session, exitstatus):
    """Dialogs the tests built without a parent would otherwise be destroyed during the interpreter's shutdown, after Qt's own
    teardown: Python then crashes (exit 139) at random, even when every test passed. Delete them while Qt is still alive.

    Only QDialogs, and never close(): at this point the fixtures that point HOME to a temporary folder are gone, and closing a
    MainWindow saves its workspace into the user's REAL settings (this happened once). deleteLater() runs no closeEvent."""
    try:
        from PySide6.QtCore    import QCoreApplication, QEvent
        from PySide6.QtWidgets import QApplication, QDialog
    except ImportError: return
    app = QApplication.instance()
    if app is None: return
    import gc; gc.collect()
    for w in app.topLevelWidgets():
        if isinstance(w, QDialog): w.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    gc.collect()
