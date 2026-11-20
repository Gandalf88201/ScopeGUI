"""Tests of the GUI. Backend tests need no Qt; the window tests run offscreen (QT_QPA_PLATFORM=offscreen)."""
import os
import pickle
import time
import pytest

from scope.gui import backend

WATER = "3\nwater\nO 0 0 0.117\nH 0 0.757 -0.469\nH 0 -0.757 -0.469\n"

def job(branch="demo", name="opt", requisites="[]", constrains="['self']", submit="False", extra=""):
    return f"&environment\n   requested_procs = 4\n{extra}/\n&options\n   want_submit = {submit}\n/\n&job_data\n   branch = '{branch}'\n   workflow = '*'\n   job = '{name}'\n   hierarchy = 1\n   requisites = {requisites}\n   constrains = {constrains}\n/\n&qc_data\n   software = 'g16'\n   comp_type = 'opt'\n   functional = 'b3lyp'\n   basis = '6-31g*'\n/\n"

@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    home = tmp_path / "home"; home.mkdir()
    monkeypatch.setenv("HOME", str(home)); monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))

@pytest.fixture
def env(tmp_path):
    e, info = backend.create_environment("t", str(tmp_path / "S"), str(tmp_path / "Y"), str(tmp_path / "C"), str(tmp_path))
    return e, info

def write(tmp_path, name, text):
    p = tmp_path / name; p.write_text(text); return str(p)

# ---- environment
def test_create_and_reload_environment(env, tmp_path):
    e, info = env
    assert info.scheduler == "local" and info.missing == [] and os.path.isfile(info.filepath)
    _, again = backend.load_environment(info.filepath)
    assert again.systems_path == info.systems_path

@pytest.mark.parametrize("name", ["", "a b", "a/b", "../x", ".hidden"])
def test_environment_name_rejected(tmp_path, name):
    with pytest.raises(ValueError): backend.create_environment(name, str(tmp_path / "a"), str(tmp_path / "b"), str(tmp_path / "c"), str(tmp_path))

def test_equal_folders_rejected(tmp_path):
    with pytest.raises(ValueError): backend.create_environment("x", str(tmp_path / "a"), str(tmp_path / "a"), str(tmp_path / "c"), str(tmp_path))

def test_load_environment_rejects_other_pickles(tmp_path):
    p = tmp_path / "x.npy"; p.write_bytes(pickle.dumps({"a": 1}))
    with pytest.raises(ValueError): backend.load_environment(str(p))
    with pytest.raises(ValueError): backend.load_environment(str(tmp_path / "missing.npy"))

def test_moved_environment_reports_missing_folders(env, tmp_path):
    import shutil
    _, info = env
    shutil.rmtree(info.systems_path)
    _, again = backend.load_environment(info.filepath)
    assert again.missing == ["systems"]

# ---- systems
def test_import_xyz_and_list(env, tmp_path):
    e, info = env
    backend.import_xyz(e, write(tmp_path, "water.xyz", WATER))
    rows = backend.list_systems(info)
    assert [r.name for r in rows] == ["water"] and rows[0].file
    assert "water" in backend.system_details(rows[0].file)
    with pytest.raises(ValueError): backend.import_xyz(e, str(tmp_path / "water.xyz"))                  # exists
    backend.import_xyz(e, str(tmp_path / "water.xyz"), overwrite=True)

@pytest.mark.parametrize("name", ["My Water.xyz", "-x.xyz", "a;b.xyz"])
def test_import_rejects_unsafe_names(env, tmp_path, name):
    with pytest.raises(ValueError): backend.import_xyz(env[0], write(tmp_path, name, WATER))

def test_import_rejects_non_xyz(env, tmp_path):
    with pytest.raises(ValueError): backend.import_xyz(env[0], write(tmp_path, "a.txt", WATER))

def test_marker_files_are_read_from_system_folder(env, tmp_path):
    e, info = env
    backend.import_xyz(e, write(tmp_path, "water.xyz", WATER))
    folder = os.path.join(info.systems_path, "water")
    open(os.path.join(folder, "demo_FINISHED"), "w").close(); open(os.path.join(folder, "other_TERMINATED"), "w").close()
    row = backend.list_systems(info)[0]
    assert row.finished == ["demo"] and row.terminated == ["other"]

# ---- inputs and pipeline
def test_read_input_valid_and_invalid(tmp_path):
    ok  = backend.read_input(write(tmp_path, "a.scope", job()))
    bad = backend.read_input(write(tmp_path, "b.scope", "nonsense\n"))
    assert ok.ok and ok.node == "demo/*/opt" and ok.want_submit is False and ok.procs == 4
    assert not bad.ok and "branch" in bad.error
    assert not backend.read_input(str(tmp_path / "nope.scope")).ok

def test_want_submit_defaults_to_true_when_missing(tmp_path):
    text = job().replace("   want_submit = False\n", "")
    assert backend.read_input(write(tmp_path, "a.scope", text)).want_submit is True

def test_graph_missing_cycle_and_layout(tmp_path):
    a = backend.read_input(write(tmp_path, "a.scope", job(name="a", requisites="['b']")))
    b = backend.read_input(write(tmp_path, "b.scope", job(name="b", requisites="['a']")))
    nodes, edges, cycles = backend.build_graph([a, b]); assert cycles
    backend.layout_graph(nodes, edges)                                                                    # must terminate on a cycle
    c = backend.read_input(write(tmp_path, "c.scope", job(name="c", requisites="['ghost']")))
    nodes, edges, cycles = backend.build_graph([c])
    assert nodes["demo/*/ghost"] == "missing" and not cycles
    place = backend.layout_graph(nodes, edges); assert place["demo/*/ghost"][0] < place["demo/*/c"][0]

# ---- run command and warnings
def test_run_command_and_child_env(tmp_path):
    program, args = backend.build_run_command("e.npy", "water", ["a.scope", "b.scope"], quiet=True, errors=True)
    assert args[:3] == ["-c", "from scope.cli.main import main; main()", "run"] and "-q" in args and "-e" in args and args.count("-i") == 1
    assert backend.child_environment()["TERM"] == "dumb" and backend.child_environment()["PYTHONUNBUFFERED"] == "1"

def test_warnings(tmp_path):
    cluster = backend.EnvInfo("e.npy", "c", "slurm", "/s/", "/y/", "/c/", queues=["short", "long"])
    local   = backend.EnvInfo("e.npy", "l", "local", "/s/", "/y/", "/c/")
    submit  = backend.read_input(write(tmp_path, "a.scope", job(submit="True", extra="   queue = shor\n")))
    assert backend.submission_warning(cluster, [submit]) and not backend.submission_warning(local, [submit])
    assert backend.queue_problems(cluster, [submit]) and not backend.queue_problems(local, [submit])
    exact = backend.read_input(write(tmp_path, "b.scope", job(submit="False", extra="   queue = short\n")))
    assert not backend.queue_problems(cluster, [exact]) and not backend.submission_warning(cluster, [exact])

# ---- window (offscreen)
def test_window_end_to_end(env, tmp_path):
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from scope.gui.window import MainWindow
    app = QApplication.instance() or QApplication([])
    e, info = env
    win = MainWindow(); win.session.set_environment(e, info)
    backend.import_xyz(e, write(tmp_path, "water.xyz", WATER)); win.session.systemsChanged.emit()
    win.session.add_inputs([write(tmp_path, "a.scope", job()), write(tmp_path, "bad.scope", "x\n")])
    assert win.pipe_tab.graph.scene() is not None and len(win.pipe_tab.graph.scene().items()) > 0      # regression: scene was garbage collected
    from scope.gui import systems; systems.confirm_defaults(e, "water", "water")                         # charge and spin checked: no question before the run
    rt = win.run_tab; rt.system.setCurrentText("water"); rt.start()
    t0 = time.time()
    while rt.running() and time.time() - t0 < 90: app.processEvents(); time.sleep(0.05)
    app.processEvents()
    assert "exit code 0" in rt.status.text() and "MANUAL ATTENTION" in rt.log.toPlainText()
    assert os.path.isdir(os.path.join(info.computations_path, "water", "demo"))


def test_project_folder_fills_the_other_boxes_and_creates(tmp_path):
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from scope.gui.window import MainWindow
    app = QApplication.instance() or QApplication([])
    win = MainWindow(); et = win.env_tab
    et.root.setText(str(tmp_path / "proj"))                                   # what the Browse button does: setText, no editingFinished
    assert et.sources.text().endswith("Sources") and et.savedir.text() == str(tmp_path / "proj")
    et.create()
    assert win.session.info is not None and os.path.isfile(win.session.info.filepath)
    assert os.path.isdir(win.session.info.systems_path)

def test_empty_folders_give_a_clear_message(tmp_path):
    with pytest.raises(ValueError, match="project folder"): backend.create_environment("x", "", "", "", "")

# ---- input form
FORM = dict(branch="demo", workflow="*", job="opt", requisites="", constrains="self", software="g16", comp_type="opt", functional="b3lyp", basis="6-31g*", procs=4, want_submit=False)

@pytest.mark.parametrize("software,comp_type", [(s, t) for s, types in backend.SOFTWARE_TYPES.items() for t in types])
def test_every_software_and_type_is_accepted_by_scope(software, comp_type):
    text, report, problems = backend.validate_form(**{**FORM, "software": software, "comp_type": comp_type})
    assert report.ok and not problems, report.error
    assert report.software == software and report.comp_type == comp_type and report.want_submit is False
    assert ("basis" in text) == (software == "g16")

def test_form_round_trip_keeps_unknown_keys():
    extras = {"qc_data": "mix_beta = 0.5\nsave_wf_note = 'x'", "job_data": "hierarchy = 2"}
    text, report, _ = backend.validate_form(**{**FORM, "requisites": "a, b"}, extras=extras)
    parsed = backend.parse_sections(text)
    assert report.ok and report.requisites == ["a", "b"] and parsed["job_data"]["hierarchy"] == "2" and parsed["qc_data"]["mix_beta"] == "0.5"
    form, back = backend.sections_to_form(backend.parse_sections(text))
    assert form["requisites"] == "a, b" and back["qc_data"].startswith("mix_beta = 0.5") and back["job_data"] == "hierarchy = 2"
    text2 = backend.render_sections(backend.build_sections(**form, extras=back))
    assert text2 == text

def test_form_workflow_list_and_defaults():
    text, report, _ = backend.validate_form(**{**FORM, "workflow": "water*, ethanol", "constrains": ""})
    assert report.ok and report.workflow == ["water*", "ethanol"] and report.constrains == ["self"]

@pytest.mark.parametrize("change,fragment", [({"branch": "my branch"}, "Branch"), ({"job": ""}, "Job is empty"), ({"workflow": " "}, "Workflow is empty"), ({"procs": 0}, "Processors")])
def test_form_problems(change, fragment):
    _, _, problems = backend.validate_form(**{**FORM, **change})
    assert any(fragment in p for p in problems)

def test_scope_rejects_bad_values_through_the_form():
    _, report, _ = backend.validate_form(**{**FORM, "comp_type": "nonsense"})
    assert not report.ok and "comp_type" in report.error or "computation type" in report.error
    _, report, _ = backend.validate_form(**{**FORM}, extras={"options": "want_submit = maybe"})
    assert not report.ok

def test_existing_file_loads_into_the_form(tmp_path):
    path = write(tmp_path, "a.scope", job(name="freq", requisites="['opt']", submit="True", extra="   queue = short\n"))
    form, extras = backend.sections_to_form(backend.parse_sections(open(path).read()))
    assert form["job"] == "freq" and form["requisites"] == "opt" and form["want_submit"] is True and form["queue"] == "short" and form["procs"] == 4

def test_editor_dialog(tmp_path, monkeypatch):
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QFileDialog
    from scope.gui.editor import InputEditor
    app = QApplication.instance() or QApplication([])
    dialog = InputEditor(None, str(tmp_path))
    assert dialog.save_btn.isEnabled() and "want_submit = False" in dialog.text
    dialog.software.setCurrentText("qe")
    assert dialog.comp_type.currentText() in backend.SOFTWARE_TYPES["qe"] and not dialog.basis.isEnabled() and "basis" not in dialog.text
    dialog.branch.setText("bad branch")
    assert not dialog.save_btn.isEnabled() and "Branch" in dialog.status.text()
    dialog.branch.setText("good")
    out = str(tmp_path / "x.scope")
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (out, "")))
    dialog.save()
    assert dialog.saved_path == out and backend.read_input(out).ok and backend.read_input(out).branch == "good"


def test_job_requiring_itself_is_flagged_in_form_and_pipeline(tmp_path):
    _, _, problems = backend.validate_form(**{**FORM, "job": "freq", "requisites": "freq"})
    assert any("the job itself" in p for p in problems)
    _, _, ok_problems = backend.validate_form(**{**FORM, "job": "freq", "requisites": "opt"})
    assert not ok_problems
    selfish = backend.read_input(write(tmp_path, "f.scope", job(name="freq", requisites="['freq']")))
    assert selfish.ok                                                          # SCOPE itself accepts it
    assert any("itself" in m for _, m in backend.pipeline_issues([selfish]))

def test_pipeline_issues_missing_duplicate_and_cycle(tmp_path):
    a = backend.read_input(write(tmp_path, "a.scope", job(name="a", requisites="['ghost']")))
    a2 = backend.read_input(write(tmp_path, "a2.scope", job(name="a")))
    messages = [m for _, m in backend.pipeline_issues([a, a2])]
    assert any("ghost" in m for m in messages) and any("also defined" in m for m in messages)
    x = backend.read_input(write(tmp_path, "x.scope", job(name="x", requisites="['y']")))
    y = backend.read_input(write(tmp_path, "y.scope", job(name="y", requisites="['x']")))
    assert any("Cycle" in m for _, m in backend.pipeline_issues([x, y]))
    assert backend.pipeline_issues([backend.read_input(write(tmp_path, "ok.scope", job()))]) == []

def test_graph_draws_with_edges_and_badge(tmp_path):
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from scope.gui.window import GraphView
    app = QApplication.instance() or QApplication([])
    view = GraphView(); view.resize(800, 400)
    opt  = backend.read_input(write(tmp_path, "o.scope", job(name="opt")))
    freq = backend.read_input(write(tmp_path, "f.scope", job(name="freq", requisites="['opt']")))
    view.draw([opt, freq]); n_edge = len(view._scene.items())
    freq_alone = backend.read_input(write(tmp_path, "f2.scope", job(name="freq")))
    view.draw([opt, freq_alone]); n_plain = len(view._scene.items())
    selfish = backend.read_input(write(tmp_path, "s.scope", job(name="s", requisites="['s']")))
    view.draw([selfish]); texts = [i.toPlainText() for i in view._scene.items() if hasattr(i, "toPlainText")]
    assert n_edge == n_plain + 2 and any("never starts" in t for t in texts)      # an arrow adds a line and a head
