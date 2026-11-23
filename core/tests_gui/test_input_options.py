"""Option fields of the input form (backend.OPTIONS): written only when set and when they apply, read back without loss, and accepted by
SCOPE's own validation. The editor test needs Qt; it builds no MainWindow, so a temporary HOME is enough."""
import os
import pytest

from scope.gui import backend

@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    home = tmp_path / "home"; home.mkdir()
    monkeypatch.setenv("HOME", str(home)); monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))

FORM = dict(branch="demo", workflow="*", job="opt", requisites="", constrains="self", software="g16", comp_type="opt", functional="b3lyp", basis="6-31g*", procs=4, want_submit=False)

FILE = """&environment
   requested_procs = 8
   queue = 'std'
   time_limit = 120
/
&options
   want_submit = False
   overwrite_inputs = False
/
&job_data
   branch = 'demo'
   workflow = '*'
   job = 'opt'
   hierarchy = 1
   requisites = []
   constrains = ['self']
   job_setup = 'rep_opt'
   max_steps = 3
   energy_thres = 1e-6
   pseudo = 'x'
/
&qc_data
   software = 'g16'
   comp_type = 'opt'
   functional = 'b3lyp'
   basis = '6-31g*'
   is_grimme = True
   grimme_type = 'd3'
   tight_opt = True
   mix_beta = 0.3
/
"""

def keys(text, section): return set(backend.parse_sections(text)[section])

def test_defaults_are_not_written():
    text, report, problems = backend.validate_form(**FORM, settings={})
    assert report.ok and not problems
    assert not any(k in keys(text, s) for s in backend.SECTIONS for k in (o.key for o in backend.OPTIONS if o.section == s))

def test_file_round_trips_through_the_fields():
    form, extras = backend.sections_to_form(backend.parse_sections(FILE))
    assert form["settings"]["environment"] == {"time_limit": "120"} and form["settings"]["options"] == {"overwrite_inputs": "False"}
    assert form["settings"]["job_data"] == {"job_setup": "'rep_opt'", "max_steps": "3", "energy_thres": "1e-6"}           # value kept as written
    assert form["settings"]["qc_data"] == {"is_grimme": "True", "grimme_type": "'d3'", "tight_opt": "True"}
    assert extras["job_data"] == "pseudo = 'x'" and extras["qc_data"] == "mix_beta = 0.3"                                 # no field (or not for Gaussian): free box
    again = backend.render_sections(backend.build_sections(**form, extras=extras))
    assert backend.parse_sections(again) == backend.parse_sections(FILE) and backend.read_input_text(again).ok

def test_options_that_do_not_apply_are_dropped_and_odd_values_kept():
    form, extras = backend.sections_to_form(backend.parse_sections(FILE))
    form.update(software="qe", comp_type="scf")
    qc = backend.build_sections(**form, extras=extras)["qc_data"]
    assert "tight_opt" not in qc and qc["is_grimme"] == "True" and qc["mix_beta"] == "0.3"                              # Gaussian-only key gone
    odd = FILE.replace("   is_grimme = True\n", "").replace("   job_setup = 'rep_opt'\n", "   save_wf = True\n   job_setup = 'rep_opt'\n")
    form, extras = backend.sections_to_form(backend.parse_sections(odd))
    assert "grimme_type = 'd3'" in extras["qc_data"] and "save_wf = True" in extras["job_data"]                           # not shown by a field: kept as written
    assert backend.parse_sections(backend.render_sections(backend.build_sections(**form, extras=extras))) == backend.parse_sections(odd)

def test_problems_are_reported():
    def problems(software="g16", comp_type="opt", **settings): return backend.validate_form(**{**FORM, "software": software, "comp_type": comp_type}, settings=settings)[2]
    assert any("not a whole number" in p for p in problems(environment={"time_limit": "2h"}))
    assert any("must be at least 1" in p for p in problems(environment={"max_jobs": "0"}))
    assert any("Finite differences" in p for p in problems(job_data={"job_setup": "'findiff'"}))
    assert any("no 'd3m'" in p for p in problems(qc_data={"is_grimme": "True", "grimme_type": "'d3m'"}))
    assert any("both on" in p for p in problems(qc_data={"loose_opt": "True", "tight_opt": "True"}))
    assert not problems(software="qe", comp_type="scf", qc_data={"is_grimme": "True", "grimme_type": "'d3m'"})

def sample(o, software):
    if o.kind == "bool":  return backend.py_value(not o.default)
    if o.kind == "int":   return "7"
    if o.kind == "float": return "0.5"
    if o.key == "grimme_type": return "'d3'"
    return backend.py_value(next(c for c in o.choices if c != o.default))

@pytest.mark.parametrize("software, comp_type, given", [
    ("g16", "opt", {"job_data": {"job_setup": "'rep_opt'"}}), ("g16", "ts", {}), ("g16", "td", {}), ("g16", "scf", {}),
    ("qe", "vc-relax", {"qc_data": {"is_hubbard": "True"}}), ("qe", "scf", {"job_data": {"job_setup": "'findiff'"}})])
def test_scope_accepts_every_field_set(software, comp_type, given):
    """Every field that applies, set to a value other than SCOPE's default, gives a file SCOPE accepts with no form problem."""
    settings = {s: dict(given.get(s, {})) for s in backend.SECTIONS}
    settings["qc_data"].setdefault("is_grimme", "True")
    ctx = backend.option_context(software, comp_type, settings)
    for o in backend.OPTIONS:
        if backend.applies(o, ctx) and o.key not in settings[o.section] and o.key != "loose_opt": settings[o.section][o.key] = sample(o, software)
    states = {"istate": "initial", "fstate": "fd"} if comp_type == "scf" and software == "qe" else {}
    text, report, problems = backend.validate_form(**{**FORM, "software": software, "comp_type": comp_type, "basis": "6-31g*" if software == "g16" else ""}, settings=settings, **states)
    assert report.ok, report.error
    assert not problems, problems
    ctx = backend.option_context(software, comp_type, settings)                     # samples change what applies (tight hides ultrafine…)
    for s in backend.SECTIONS:
        assert {k for k in settings[s] if backend.applies(backend.OPTION[(s, k)], ctx)} <= keys(text, s)

def test_editor_fields(tmp_path):
    pytest.importorskip("PySide6"); os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from scope.gui.editor import InputEditor
    app = QApplication.instance() or QApplication([])
    form, extras = backend.sections_to_form(backend.parse_sections(FILE))
    d = InputEditor(None, str(tmp_path), form, extras, "opt.scope", queues=["std", "short", "std"])
    assert [d.queue.itemText(i) for i in range(d.queue.count())] == ["std", "short"] and d.queue.currentText() == "std"
    assert d.save_btn.isEnabled(), d.status.text()
    assert d.settings()["qc_data"]["tight_opt"] == "True" and "tight_opt   = True" in d.preview.toPlainText()
    forms = d.option_forms["qc_data"]
    assert forms.isRowVisible(d.options[("qc_data", "fctype")]) and not forms.isRowVisible(d.options[("qc_data", "pp_library")])
    assert not forms.isRowVisible(d.options[("qc_data", "ultrafine_grid")])                                          # tight convergence adds it already
    assert d.tabs.tabText(d.tab_index["qc_data"]) == "&&qc_data (3)"
    d.software.setCurrentText("qe")                                                                                     # Gaussian fields hide and are not written
    assert forms.isRowVisible(d.options[("qc_data", "pp_library")]) and not forms.isRowVisible(d.options[("qc_data", "fctype")])
    assert "tight_opt" not in d.preview.toPlainText() and "is_grimme" in d.preview.toPlainText()
    assert not forms.isRowVisible(d.options[("qc_data", "mix_beta")]) and d.details.isVisibleTo(d)                  # solver details on request
    d.details.setChecked(True); assert forms.isRowVisible(d.options[("qc_data", "mix_beta")])
    d.options[("environment", "time_limit")].setText("2h")
    assert not d.save_btn.isEnabled() and "not a whole number" in d.status.text()
    d.options[("environment", "time_limit")].setText("")
    assert "time_limit" not in d.preview.toPlainText()

def test_editor_findiff_writes_a_new_state(tmp_path):
    pytest.importorskip("PySide6"); os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from scope.gui.editor import InputEditor
    app = QApplication.instance() or QApplication([])
    p = tmp_path / "opt.scope"; p.write_text(FILE.replace("   job_setup = 'rep_opt'\n   max_steps = 3\n   energy_thres = 1e-6\n", "")); opt = backend.read_input(str(p))
    d = InputEditor(None, str(tmp_path), {"job": "fd", "requisites": "opt", "software": "qe", "comp_type": "scf"}, reports=[opt])
    assert (d.istate.text(), d.fstate.text()) == ("opt", "opt")                                                         # an scf adds to the state it reads
    w = d.options[("job_data", "job_setup")]; w.setCurrentIndex(w.findData("'findiff'"))
    assert (d.istate.text(), d.fstate.text()) == ("opt", "fd")                                                          # findiff needs a new state
