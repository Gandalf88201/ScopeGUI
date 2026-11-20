"""Item 3: one review table before running (here or on a cluster): every job, its type, states, what it waits for, processors, queue,
whether it submits, and what needs a look."""
import os
import pytest

from scope.gui import backend
from test_remote import isolated, local, WATER                              # noqa: F401  (fixtures: temp HOME, fake ssh)

def job(name="opt", requisites="[]", submit="False", queue="", comp_type="opt", branch="demo"):
    q = f"   queue = '{queue}'\n" if queue else ""
    return (f"&environment\n   requested_procs = 8\n{q}/\n&options\n   want_submit = {submit}\n/\n&job_data\n   branch = '{branch}'\n   workflow = '*'\n   job = '{name}'\n   hierarchy = 1\n"
            f"   requisites = {requisites}\n   constrains = ['self']\n/\n&qc_data\n   software = 'g16'\n   comp_type = '{comp_type}'\n   functional = 'b3lyp'\n   basis = '6-31g*'\n/\n")

def read(tmp_path, name, text):
    p = tmp_path / name; p.write_text(text); return backend.read_input(str(p))

def test_review_rows_on_a_cluster(tmp_path):
    opt  = read(tmp_path, "opt.scope", job(submit="True", queue="std"))
    freq = read(tmp_path, "freq.scope", job(name="freq", comp_type="freq", requisites="['opt']", submit="True", queue="shor"))
    bad  = read(tmp_path, "bad.scope", "nonsense\n")
    rows = {r.file: r for r in backend.review_rows([opt, freq, bad], "slurm", ["std", "short"], extra={freq.path: ["freq.scope needs Gaussian 16"]})}
    o, f, b = rows["opt.scope"], rows["freq.scope"], rows["bad.scope"]
    assert (o.job, o.kind, o.states, o.waits_for, o.procs, o.queue, o.submits, o.level) == ("opt", "g16 opt", "initial → opt", "—", "8", "std", "YES, to slurm", "ok")
    assert f.level == "err" and "Queue 'shor' is not a queue" in f.problems[0] and any("reads state 'initial'" in p for p in f.problems) and "freq.scope needs Gaussian 16" in f.problems
    assert b.level == "err" and "does not accept" in b.problems[0]

def test_review_rows_here_and_unknown(tmp_path):
    opt = read(tmp_path, "opt.scope", job(submit="True", queue="anything"))
    assert backend.review_rows([opt], "local", [])[0].submits.startswith("no (local") and backend.review_rows([opt], "local", [])[0].level == "ok"   # local: queues not used
    unknown = backend.review_rows([opt], "", None)[0]
    assert unknown.submits == "yes" and unknown.level == "ok"                                       # cluster not tested yet: nothing claimed

def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen"); pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])

def test_the_table_is_where_run_is_pressed(local, tmp_path, monkeypatch):
    app = qapp(); from scope.gui.window import MainWindow
    from scope.gui import review_view
    env, info = local
    (tmp_path / "opt.scope").write_text(job()); (tmp_path / "freq.scope").write_text(job(name="freq", comp_type="freq", requisites="['opt']"))
    win = MainWindow(); win.session.set_environment(env, info); win.session.add_inputs([str(tmp_path / "opt.scope"), str(tmp_path / "freq.scope")])
    rt = win.run_tab; rt.refresh(); rt.system.setCurrentText("water")
    assert rt.review.rowCount() == 2 and "2 job(s)" in rt.review_note.text() and "1 to look at" in rt.review_note.text()
    assert rt.review.item(1, 9).text().startswith("!") and "reads state 'initial'" in rt.review.item(1, 9).toolTip()
    tab = win.remote_tab
    assert tab.review.rowCount() == 2 and "after Test connection" in tab.review_note.text()
    tab.probe = {"env": {"scheduler": "slurm", "queues": ["std"]}}; tab.update_review()
    assert tab.review.item(0, 8).text() == "no (want_submit = False)" and "after Test connection" not in tab.review_note.text()
    shown = []; monkeypatch.setattr(review_view.ReviewDialog, "exec", lambda self: shown.append(self.table.rowCount()) or 0)
    win.pipe_tab.review(); assert shown == [2]
