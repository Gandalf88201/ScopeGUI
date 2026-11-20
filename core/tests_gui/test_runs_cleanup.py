"""Runs page (reported): Refresh seemed to do nothing (it only re-read this computer, which updates by itself, and kept the cluster rows of
the last check), and there was no way to clean the list. Now Refresh also asks the clusters and says when it refreshed; Clean up removes
the ended runs of this computer with their logs, never a running one."""
import os
import pytest

from scope.gui import backend
from test_remote import isolated                                             # noqa: F401  (fixture: temp HOME, real settings untouched)

def runs(tmp_path, monkeypatch):
    """Four records in the window's own run folder: two ended, one running, one of another kind; plus a log no record names any more."""
    folder = backend.runs_dir(); logs = {}
    for name in ("ended_ok", "ended_lost", "running", "other"):
        logs[name] = os.path.join(folder, f"run_{name}_20261120_101010_abcdef.log")
        open(logs[name], "w").write("output\n" + (f"{backend.EXIT_MARKER} 0\n" if name == "ended_ok" else ""))
    orphan = os.path.join(folder, "run_old_20261101_101010.log"); open(orphan, "w").write("old\n")
    outside = tmp_path / "run_elsewhere.log"; outside.write_text("not ours\n")
    records = [{"id": n, "kind": "local", "system": n, "pid": 1, "log": logs[n], "started": 0, "seen": True} for n in ("ended_ok", "ended_lost", "running")]
    records += [{"id": "other", "kind": "cluster", "system": "other", "log": logs["other"], "started": 0, "seen": True},
                {"id": "outside", "kind": "local", "system": "x", "pid": 1, "log": str(outside), "started": 0, "seen": True}]
    backend.save_runs(records)
    real = backend.run_state
    monkeypatch.setattr(backend, "run_state", lambda r: ("running", None) if r.get("id") == "running" else real(r))
    return logs, orphan, outside

def test_clean_removes_ended_runs_and_their_logs_only(tmp_path, monkeypatch):
    logs, orphan, outside = runs(tmp_path, monkeypatch)
    ended, files = backend.cleanable_runs()
    assert sorted(r["id"] for r in ended) == ["ended_lost", "ended_ok", "outside"]
    assert sorted(files) == sorted([logs["ended_ok"], logs["ended_lost"], orphan])         # never a running log, never a file outside the folder
    assert backend.clean_runs() == (3, 3)
    assert sorted(r["id"] for r in backend.load_runs()) == ["other", "running"]
    assert os.path.isfile(logs["running"]) and os.path.isfile(logs["other"]) and outside.exists()
    assert not any(os.path.exists(p) for p in (logs["ended_ok"], logs["ended_lost"], orphan))
    assert backend.cleanable_runs() == ([], []) and backend.clean_runs() == (0, 0)

def test_page_clean_up_asks_and_refresh_says_when(tmp_path, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QMessageBox
    from scope.gui import runs_page
    QApplication.instance() or QApplication([])
    runs(tmp_path, monkeypatch)
    page = runs_page.RunsPage(None)
    page.refresh_all()                                                          # no cluster project: this computer only, and it says so
    assert len(page.rows) == 4 and "Refreshed at" in page.status.text() and "no workspace has a cluster project" in page.status.text().lower()
    asked = []
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: (asked.append(a[2]), QMessageBox.No)[1]))
    page.clean_up(); assert asked and "3 ended run(s)" in asked[0] and len(backend.load_runs()) == 5   # No: nothing removed
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes))
    page.clean_up()
    assert [r.system for r in page.rows] == ["running"] and "3 run(s) removed" in page.status.text()
    page.clean_up(); assert "Nothing to clean up" in page.status.text()

def test_refresh_asks_the_clusters(monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from scope.gui import runs_page
    QApplication.instance() or QApplication([])
    page = runs_page.RunsPage(None); called = []
    monkeypatch.setattr(page, "check", lambda: (called.append(1), True)[1])
    page.refresh_all(); assert called                                           # the button reaches the clusters; the 3-second timer does not
    page.refresh(); assert len(called) == 1
