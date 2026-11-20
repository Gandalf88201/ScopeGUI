"""Initial/final States in the input form and the pipeline, and pipeline nodes that tell workflows apart (no Qt except the editor test)."""
import os
import pathlib
import pytest

from scope.gui import backend

@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    home = tmp_path / "home"; home.mkdir()
    monkeypatch.setenv("HOME", str(home)); monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))

def job(name="opt", workflow="'*'", requisites="[]", comp_type="opt", branch="demo", states=""):
    return (f"&environment\n   requested_procs = 4\n/\n&options\n   want_submit = False\n/\n&job_data\n   branch = '{branch}'\n   workflow = {workflow}\n   job = '{name}'\n{states}"
            f"   hierarchy = 1\n   requisites = {requisites}\n   constrains = ['self']\n/\n&qc_data\n   software = 'g16'\n   comp_type = '{comp_type}'\n   functional = 'b3lyp'\n   basis = '6-31g*'\n/\n")

def read(tmp_path, name, text):
    p = tmp_path / name; p.write_text(text); return backend.read_input(str(p))

FORM = dict(branch="demo", workflow="*", job="freq", requisites="opt", constrains="self", software="g16", comp_type="freq", functional="b3lyp", basis="6-31g*", procs=4, want_submit=False)

# ---- point 3: istate / fstate
def test_report_reads_scope_defaults_and_explicit_states(tmp_path):
    plain = read(tmp_path, "a.scope", job())
    assert plain.istate == "initial" and plain.fstate == "opt"                                # SCOPE's defaults
    given = read(tmp_path, "b.scope", job(name="freq", comp_type="freq", states="   istate = 'opt'\n   fstate = 'opt'\n"))
    assert given.istate == "opt" and given.fstate == "opt"

def test_form_writes_states_and_round_trips():
    text, report, problems = backend.validate_form(**FORM, istate="opt", fstate="opt")
    assert report.ok and not problems and report.istate == "opt" and report.fstate == "opt"
    form, extras = backend.sections_to_form(backend.parse_sections(text))
    assert form["istate"] == "opt" and form["fstate"] == "opt" and "istate" not in extras["job_data"]          # not lost into the extras box
    assert backend.render_sections(backend.build_sections(**form, extras=extras)) == text

def test_suggestion_follows_the_requisite(tmp_path):
    opt = read(tmp_path, "opt.scope", job())
    assert backend.suggest_states("freq", "freq", "opt", [opt], "demo", "*") == ("opt", "opt")          # freq adds to the optimised state
    assert backend.suggest_states("opt2", "opt", "opt", [opt], "demo", "*") == ("opt", "opt2")          # a geometry job writes its own state
    assert backend.suggest_states("opt", "opt", "", [opt], "demo", "*") == ("initial", "opt")           # no requisite: SCOPE's defaults
    assert backend.suggest_states("freq", "freq", "opt", [opt], "other", "*") == ("initial", "freq")    # another branch is not a requisite

def test_issue_when_requisite_does_not_give_the_geometry(tmp_path):
    """The reported case: freq with requisites=['opt'] still reads 'initial'."""
    opt  = read(tmp_path, "opt.scope", job())
    freq = read(tmp_path, "freq.scope", job(name="freq", comp_type="freq", requisites="['opt']"))
    messages = [m for _, m in backend.pipeline_issues([opt, freq])]
    assert any("reads state 'initial'" in m and "istate = 'opt'" in m for m in messages)
    fixed = read(tmp_path, "freq2.scope", job(name="freq", comp_type="freq", requisites="['opt']", states="   istate = 'opt'\n   fstate = 'opt'\n"))
    assert backend.pipeline_issues([opt, fixed]) == []

def test_issue_when_two_branches_write_one_state(tmp_path):
    a = read(tmp_path, "a.scope", job(branch="pbe"))
    b = read(tmp_path, "b.scope", job(branch="b3lyp"))
    assert any("both write state 'opt'" in m for _, m in backend.pipeline_issues([a, b]))

def test_state_graph_links_jobs_through_states(tmp_path):
    opt  = read(tmp_path, "opt.scope", job())
    freq = read(tmp_path, "freq.scope", job(name="freq", comp_type="freq", requisites="['opt']", states="   istate = 'opt'\n   fstate = 'opt'\n"))
    nodes, edges, cycles = backend.state_graph([opt, freq])
    assert nodes["state:given:initial"] == ("given", "initial") and nodes["state:*:opt"] == ("state", "opt") and not cycles
    assert ("state:given:initial", opt.node, "reads") in edges and (opt.node, "state:*:opt", "writes") in edges
    assert ("state:*:opt", freq.node, "reads") in edges and (freq.node, "state:*:opt", "updates") in edges
    place = backend.layout_graph(nodes, edges)
    assert place["state:given:initial"][0] < place[opt.node][0] < place["state:*:opt"][0] < place[freq.node][0]

# ---- point 6: workflows in the graph
def test_same_job_in_two_workflows_is_not_a_duplicate(tmp_path):
    hs = read(tmp_path, "hs.scope", job(workflow="'hs*'"))
    ls = read(tmp_path, "ls.scope", job(workflow="'ls*'"))
    assert hs.node == "demo/hs*/opt" and ls.node == "demo/ls*/opt"
    nodes, _, _ = backend.build_graph([hs, ls]); assert len([n for n, k in nodes.items() if k == "job"]) == 2
    assert not any("also defined" in m for _, m in backend.pipeline_issues([hs, ls]))
    every = read(tmp_path, "all.scope", job(workflow="'*'"))
    assert any("also defined" in m for _, m in backend.pipeline_issues([hs, every]))                 # '*' does run on the hs sources

def test_requisites_join_only_overlapping_workflows(tmp_path):
    hs, ls = read(tmp_path, "hs.scope", job(workflow="'hs*'")), read(tmp_path, "ls.scope", job(workflow="'ls*'"))
    freq = read(tmp_path, "f.scope", job(name="freq", workflow="'hs_1'", comp_type="freq", requisites="['opt']"))
    _, edges, _ = backend.build_graph([hs, ls, freq])
    assert (hs.node, freq.node, "requisite") in edges and (ls.node, freq.node, "requisite") not in edges

@pytest.mark.parametrize("a,b,sources,expected", [(["*"], ["x"], None, True), (["hs*"], ["ls*"], None, None), (["hs*"], ["hs_1"], None, True), (["a"], ["b"], None, False),
                                                  (["hs*"], ["*_1"], ["hs_1", "ls_1"], True), (["hs*"], ["ls*"], ["hs_1", "ls_1"], False)])
def test_selector_overlap(a, b, sources, expected):
    assert backend.selectors_overlap(a, b, sources) is expected

def test_overlap_with_system_sources_is_exact(tmp_path):
    hs = read(tmp_path, "hs.scope", job(workflow="'*_hs'"))
    ls = read(tmp_path, "ls.scope", job(workflow="'fe*'"))
    assert not any("also defined" in m for _, m in backend.pipeline_issues([hs, ls], sources=["fe_ls", "co_hs"]))
    assert any("also defined" in m for _, m in backend.pipeline_issues([hs, ls], sources=["fe_hs"]))

# ---- editor
def test_editor_fills_states_from_the_requisite(tmp_path):
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from scope.gui.editor import InputEditor
    app = QApplication.instance() or QApplication([])
    opt = read(tmp_path, "opt.scope", job())
    d = InputEditor(None, str(tmp_path), reports=[opt])
    d.job.setText("freq"); d.comp_type.setCurrentText("freq"); d.requisites.setText("opt")
    assert d.istate.text() == "opt" and d.fstate.text() == "opt" and backend.parse_sections(d.text)["job_data"]["istate"] == "'opt'"
    from PySide6.QtTest import QTest
    d.fstate.clear(); QTest.keyClicks(d.fstate, "mine")                                              # typed by the user: kept
    assert d.fstate.text() == "mine" and backend.parse_sections(d.text)["job_data"]["fstate"] == "'mine'"
    d.requisites.setText("opt "); assert d.fstate.text() == "mine"
    form, extras = backend.sections_to_form(backend.parse_sections(job(name="freq", comp_type="freq", requisites="['opt']")))
    old = InputEditor(None, str(tmp_path), form, extras, "freq.scope", reports=[opt])                            # an existing file: shown as SCOPE reads it
    assert old.istate.text() == "initial" and not old.use_result.isHidden() and "initial" in old.states_note.text()
    old.job.setText("freq2"); assert old.fstate.text() == "freq2"                                     # fstate = job name (SCOPE's default) follows a rename
    old.apply_suggestion(); assert old.istate.text() == "opt"

# ---- requisites that cannot work, said in plain words (the newcomer case of the screenshot)
def test_a_state_name_written_as_requisite(tmp_path):
    own = read(tmp_path, "a.scope", job(name="test2", requisites="['geofinal']", states="   fstate = 'geofinal'\n"))
    assert any("the state this job writes itself, not a job" in m for _, m in backend.pipeline_issues([own]))
    opt  = read(tmp_path, "o.scope", job(states="   fstate = 'geo'\n"))
    freq = read(tmp_path, "f.scope", job(name="freq", comp_type="freq", requisites="['geo']"))
    assert any("that is a state (written by job 'opt'" in m and "requisites = ['opt']" in m for _, m in backend.pipeline_issues([opt, freq]))

def test_a_requisite_in_another_branch_or_on_other_sources(tmp_path):
    opt  = read(tmp_path, "o.scope", job(branch="test2"))
    freq = read(tmp_path, "f.scope", job(branch="test", name="freq", comp_type="freq", requisites="['opt']"))
    assert any("job of branch 'test2'" in m and "same branch" in m for _, m in backend.pipeline_issues([opt, freq]))
    hs = read(tmp_path, "h.scope", job(workflow="'hs'"))
    ls = read(tmp_path, "l.scope", job(name="freq", workflow="'ls'", comp_type="freq", requisites="['opt']"))
    assert any("runs on other sources" in m for _, m in backend.pipeline_issues([hs, ls]))

def test_columns_are_ordered_to_avoid_crossings():
    nodes = {"a": 0, "b": 0, "x": 0, "y": 0}
    edges = [("a", "y", "writes"), ("b", "x", "writes")]                     # by name x would sit next to a, and the arrows would cross
    place = backend.layout_graph(nodes, edges)
    assert place["a"][1] == place["y"][1] and place["b"][1] == place["x"][1]

# ---- Add a job after this one
def test_followup_form_copies_the_method_and_waits_for_the_job(tmp_path):
    opt = read(tmp_path, "opt.scope", job(branch="sco", workflow="'hs*'").replace("   requested_procs = 4\n", "   requested_procs = 8\n   queue = 'short'\n").replace("&qc_data\n", "&qc_data\n   is_grimme = True\n").replace("   hierarchy = 1\n", "   hierarchy = 1\n   job_setup = 'rep_opt'\n"))
    form, extras = backend.followup_form(opt, [opt])
    assert (form["branch"], form["workflow"], form["requisites"], form["job"], form["comp_type"]) == ("sco", "hs*", "opt", "freq", "freq")
    assert (form["functional"], form["basis"], form["procs"], form["queue"]) == ("b3lyp", "6-31g*", 8, "short") and "is_grimme" in extras["qc_data"]
    assert extras["job_data"] == "" and form["istate"] == form["fstate"] == ""                    # job_setup belongs to the opt job only; states follow the requisite
    freq = read(tmp_path, "freq.scope", job(branch="sco", name="freq", comp_type="freq"))
    assert backend.followup_form(opt, [opt, freq])[0]["job"] == "freq2"                           # never a name the branch already has

def test_add_after_from_the_pipeline_page(tmp_path, monkeypatch):
    pytest.importorskip("PySide6"); os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QFileDialog
    from scope.gui.window import MainWindow
    app = QApplication.instance() or QApplication([])
    path = tmp_path / "opt.scope"; path.write_text(job())
    win = MainWindow(); win.session.add_inputs([str(path)]); pt = win.pipe_tab
    out = str(tmp_path / "freq.scope"); seen = {}
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (out, "")))
    from scope.gui import editor
    def run(dialog):
        seen.update(title=dialog.windowTitle(), istate=dialog.istate.text(), fstate=dialog.fstate.text(), req=dialog.requisites.text()); dialog.save(); return True
    monkeypatch.setattr(editor.InputEditor, "exec", run)
    pt.table.selectRow(0); pt.add_after_selected()
    assert seen == {"title": "New job after 'opt'", "istate": "opt", "fstate": "opt", "req": "opt"}
    r = backend.read_input(out)
    assert r.ok and r.job == "freq" and r.requisites == ["opt"] and r.istate == "opt" and [x.path for x in win.session.reports][-1] == out
    assert backend.pipeline_issues(win.session.reports) == []                                     # the new pair is consistent: no warning
    assert pt.graph.jobs == {"demo/*/opt", "demo/*/freq"}

# ---- drag job A onto job B: B waits for A and starts from its result
def test_link_jobs_changes_requisites_and_states_only_in_the_preview(tmp_path):
    opt  = read(tmp_path, "opt.scope", job(states="   fstate = 'geo'\n"))
    freq = read(tmp_path, "freq.scope", job(name="freq", comp_type="freq", states="   istate = 'initial'\n   fstate = 'initial'\n"))
    before = pathlib.Path(freq.path).read_text()
    change = backend.link_jobs(opt, freq, [opt, freq])
    assert pathlib.Path(freq.path).read_text() == before                                                       # nothing written by link_jobs
    new = backend.read_input_text(change.new_text)
    assert new.ok and new.requisites == ["opt"] and new.istate == "geo" and new.fstate == "geo"    # freq adds to the state it reads: follows it
    assert "~ requisites: []  →  ['opt']   (&job_data)" in change.diff and "~ istate: 'initial'  →  'geo'   (&job_data)" in change.diff and len(change.diff) == 3 and any("'freq' will start only after 'opt'" in n for n in change.notes)
    opt2 = read(tmp_path, "opt2.scope", job(name="opt2", states="   fstate = 'opt2'\n"))
    assert backend.read_input_text(backend.link_jobs(opt, opt2, [opt, opt2]).new_text).fstate == "opt2"   # a geometry job keeps writing its own state

@pytest.mark.parametrize("case,fragment", [("branch", "same branch"), ("sources", "no source runs both"), ("self", "itself"), ("twice", "already waits"), ("cycle", "cycle")])
def test_link_jobs_refuses_what_scope_could_not_follow(tmp_path, case, fragment):
    a = read(tmp_path, "a.scope", job(name="a", workflow="'hs'"))
    b = {"branch": job(name="b", branch="other"), "sources": job(name="b", workflow="'ls'"), "self": job(name="a", workflow="'hs'"),
         "twice": job(name="b", requisites="['a']"), "cycle": job(name="b")}[case]
    b = read(tmp_path, "b.scope", b)
    if case == "self": b = a
    reports = [a, b]
    if case == "cycle":
        a = read(tmp_path, "a.scope", job(name="a", workflow="'hs'", requisites="['b']")); reports = [a, b]       # a already waits for b: b cannot wait for a
    with pytest.raises(ValueError, match=fragment): backend.link_jobs(a, b, reports)

def test_dragging_one_job_onto_another_links_them(tmp_path, monkeypatch):
    pytest.importorskip("PySide6"); os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QDialog
    from scope.gui.window import MainWindow
    from scope.gui import editor
    app = QApplication.instance() or QApplication([])
    (tmp_path / "opt.scope").write_text(job()); (tmp_path / "freq.scope").write_text(job(name="freq", comp_type="freq"))
    win = MainWindow(); win.resize(1240, 900); win.show(); win.show_step("pipeline"); win.session.add_inputs([str(tmp_path / "opt.scope"), str(tmp_path / "freq.scope")]); app.processEvents()
    g = win.pipe_tab.graph; shown = []
    monkeypatch.setattr(editor.LinkDialog, "exec", lambda self: shown.append(self.diff.toPlainText()) or QDialog.Accepted)
    start, end = (g.mapFromScene(g.boxes[n].center()) for n in ("demo/*/opt", "demo/*/freq"))
    QTest.mousePress(g.viewport(), Qt.LeftButton, Qt.NoModifier, start); QTest.mouseMove(g.viewport(), end); QTest.mouseRelease(g.viewport(), Qt.LeftButton, Qt.NoModifier, end); app.processEvents()
    assert shown and "requisites" in shown[0]
    r = backend.read_input(str(tmp_path / "freq.scope"))
    assert r.requisites == ["opt"] and r.istate == "opt" and backend.pipeline_issues(win.session.reports) == []
    assert ("demo/*/opt", "demo/*/freq", "requisite") in backend.build_graph(win.session.reports)[1]

# ---- more than two jobs: chains and fan-in
def test_chain_of_four_jobs(tmp_path):
    opt  = read(tmp_path, "1.scope", job(name="opt"))
    opt2 = read(tmp_path, "2.scope", job(name="opt2", states="   fstate = 'opt2'\n"))
    freq = read(tmp_path, "3.scope", job(name="freq", comp_type="freq", states="   istate = 'initial'\n   fstate = 'initial'\n"))
    td   = read(tmp_path, "4.scope", job(name="td", comp_type="td", states="   istate = 'initial'\n   fstate = 'initial'\n"))
    reports = [opt, opt2, freq, td]
    links = backend.link_chain([opt, opt2, freq, td], reports)
    assert [os.path.basename(l.path) for l in links] == ["2.scope", "3.scope", "4.scope"] and all(pathlib.Path(l.path).read_text() == l.old_text for l in links)   # nothing written
    new = {os.path.basename(l.path): backend.read_input_text(l.new_text) for l in links}
    assert new["2.scope"].requisites == ["opt"] and new["2.scope"].istate == "opt" and new["2.scope"].fstate == "opt2"
    assert new["3.scope"].requisites == ["opt2"] and new["3.scope"].istate == new["3.scope"].fstate == "opt2"      # freq on the result of opt2
    assert new["4.scope"].requisites == ["freq"] and new["4.scope"].istate == "opt2"                              # td reads what freq wrote into
    for l in links: pathlib.Path(l.path).write_text(l.new_text)
    after = [backend.read_input(r.path) for r in reports]
    assert backend.pipeline_issues(after) == [] and not backend.build_graph(after)[2]                              # consistent, no cycle
    assert backend.link_chain([opt, opt2, freq, td], after) == []                                                  # chaining again changes nothing

def test_chain_refuses_an_order_that_makes_a_cycle_and_names_the_pair(tmp_path):
    a = read(tmp_path, "a.scope", job(name="a")); b = read(tmp_path, "b.scope", job(name="b", requisites="['a']"))
    with pytest.raises(ValueError, match="'b' → 'a'.*cycle"): backend.link_chain([b, a], [a, b])
    with pytest.raises(ValueError, match="at least two"): backend.link_chain([a], [a])

def test_a_job_can_wait_for_several_and_keeps_one_initial_state(tmp_path):
    hs  = read(tmp_path, "a.scope", job(name="opt"))
    ref = read(tmp_path, "b.scope", job(name="ref", comp_type="scf", states="   fstate = 'ref'\n"))
    sp  = read(tmp_path, "c.scope", job(name="sp", comp_type="scf", states="   istate = 'initial'\n   fstate = 'sp'\n"))
    first = backend.link_jobs(hs, sp, [hs, ref, sp]); pathlib.Path(sp.path).write_text(first.new_text); sp = backend.read_input(sp.path)
    second = backend.link_jobs(ref, sp, [hs, ref, sp]); new = backend.read_input_text(second.new_text)
    assert new.requisites == ["opt", "ref"] and new.istate == "opt" and any("keeps starting from 'opt'" in n for n in second.notes)

def test_chain_dialog_reorders_and_saves(tmp_path, monkeypatch):
    pytest.importorskip("PySide6"); os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QDialog
    from scope.gui.window import MainWindow
    from scope.gui import editor
    app = QApplication.instance() or QApplication([])
    for name, text in (("1.scope", job(name="opt")), ("2.scope", job(name="freq", comp_type="freq")), ("3.scope", job(name="sp", comp_type="scf"))): (tmp_path / name).write_text(text)
    win = MainWindow(); win.session.add_inputs([str(tmp_path / n) for n in ("1.scope", "2.scope", "3.scope")]); pt = win.pipe_tab
    seen = []
    def run(dialog):
        seen.append([r.job for r in dialog.chain()])
        item = dialog.order.takeItem(2); dialog.order.insertItem(1, item); dialog.refresh()        # the user drags 'sp' before 'freq'
        seen.append([r.job for r in dialog.chain()]); return QDialog.Accepted
    monkeypatch.setattr(editor.ChainDialog, "exec", run)
    pt.table.selectAll(); pt.chain_selected()
    assert seen[0] == ["opt", "freq", "sp"] and seen[1] == ["opt", "sp", "freq"]
    r = {x.job: x for x in win.session.reports}
    assert r["sp"].requisites == ["opt"] and r["freq"].requisites == ["sp"] and r["freq"].istate == "opt"

def test_a_freq_with_the_default_state_writes_onto_the_geometry_it_starts_from(tmp_path):
    opt  = read(tmp_path, "1.scope", job(name="opt"))
    sp   = read(tmp_path, "2.scope", job(name="sp", comp_type="scf"))                                  # SCOPE defaults: fstate 'sp'
    freq = read(tmp_path, "3.scope", job(name="freq", comp_type="freq"))                              # SCOPE defaults: fstate 'freq'
    new = {os.path.basename(l.path): backend.read_input_text(l.new_text) for l in backend.link_chain([opt, sp, freq], [opt, sp, freq])}
    assert new["2.scope"].fstate == "sp" and new["3.scope"].istate == new["3.scope"].fstate == "opt"   # sp keeps its own state; freq lands on 'opt'
