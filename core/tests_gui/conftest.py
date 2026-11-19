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
