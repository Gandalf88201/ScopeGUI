"""The Results page and its no-Qt layer (scope.gui.results): read-only, paths pointed at this computer, honest about what is missing.

Most tests use stand-in objects or a system imported in the test. The tests against real registered results need the SCOPE tutorials
(CC BY-NC-ND, so they are not copied into this repository): set SCOPE_TUTORIALS to the Scope_Tutorials folder to run them."""
import os
import pickle
import shutil
import sys
import time
from types import SimpleNamespace as NS
import pytest

from scope.gui import backend, results
from test_remote import isolated, local, cluster, WATER                     # noqa: F401  (fixtures)

TUTORIALS = os.environ.get("SCOPE_TUTORIALS", "")
ABITEM    = os.path.join(TUTORIALS, "Data", "1-Tutorial_1")
needs_tutorials = pytest.mark.skipif(not os.path.isfile(os.path.join(ABITEM, "Systems", "ABITEM", "ABITEM.npy")), reason="set SCOPE_TUTORIALS to the Scope_Tutorials folder")

def tree(root) -> list:
    """Every file (with size and date) and folder under root: compared before and after, to prove nothing was written."""
    out = []
    for d, dirs, files in os.walk(root):
        out.append(("dir", os.path.relpath(d, root)))
        out += [("file", os.path.relpath(os.path.join(d, f), root), os.path.getsize(os.path.join(d, f)), os.path.getmtime(os.path.join(d, f))) for f in files]
    return sorted(out)

# ---- stand-ins for SCOPE objects (only the attributes results.py reads)
def comp(job="opt", run=1, step=1, status="worked", registered=True, out="", qc=None):
    return NS(_job=NS(name=job), run_number=run, step=step, status=status, isregistered=registered, out_path=out, inp_path="", software="g16", type=job,
              qc_data=qc or NS(software="g16", functional="pbe", basis="sto-3g", istate="initial", fstate="opt"), elapsed_time=1.0, cpu_time=2.0)

def state(name, energy=None, comps=(), freqs=None, minimum=None):
    res = {} if energy is None else {"energy": NS(value=energy, units="au")}
    return NS(name=name, computations=list(comps), results=res, freqs_cm=freqs or [], isminimum=minimum)

def test_status_groups_never_call_an_unknown_or_missing_result_good(tmp_path):
    out = tmp_path / "x.log"; out.write_text("Normal termination\n")
    assert results.comp_group(comp(status="worked")) == "ok" and results.comp_group(comp(status="no_coord")) == "ok"           # a finished single point
    assert results.comp_group(comp(status="time_stopped")) == "warn"
    assert results.comp_group(comp(status="aborted")) == "err" and results.comp_group(comp(status="no_scf_convergence")) == "err"
    assert results.comp_group(comp(status="something new")) == "unknown"
    assert results.comp_group(comp(registered=False, out=str(tmp_path / "none.log"))) == "waiting"
    assert results.comp_group(comp(registered=False, out=str(out))) == "unregistered"

def test_a_state_takes_the_status_of_its_last_run_and_remembers_the_retry():
    src = NS(name="g1", object_subtype="molecule", formula="H2-O", states=[
        state("opt", -76.0, [comp("opt", 1, status="time_stopped"), comp("opt", 2, status="worked")]),
        state("vc", -75.0, [comp("vc", 1, step=3, status="no_scf_convergence"), comp("vc", 2, step=3, status="aborted")]),
        state("initial")])
    rows = results.state_rows(NS(sources=[src]))
    assert [r.group for r in rows] == ["ok", "err", "none"] and rows[0].retried and rows[1].retried and not rows[2].retried
    assert rows[0].runs == ["opt r1", "opt r2"] and rows[1].runs == ["vc s3 r1", "vc s3 r2"]                                 # as in SCOPE's file names
    assert rows[2].energy is None and rows[2].energy_note                                                                     # missing, never 0
    assert rows[0].method == "g16 pbe sto-3g"

def test_energies_are_compared_only_within_one_formula_and_one_method():
    b3 = NS(software="g16", functional="b3lyp", basis="def2svp"); pbe = NS(software="g16", functional="pbe", basis="def2svp")
    src = lambda name, formula, states: NS(name=name, object_subtype="molecule", formula=formula, states=states)
    obj = NS(sources=[src("hs", "C2", [state("b3", -100.0, [comp(qc=b3)]), state("pbe", -99.0, [comp(qc=pbe)])]),
                      src("ls", "C2", [state("b3", -100.01, [comp(qc=b3)])]),
                      src("other", "N2", [state("b3", -50.0, [comp(qc=b3)])])])
    rel = results.relative_energies(results.state_rows(obj))
    assert rel[("ls", "b3")] == 0 and abs(rel[("hs", "b3")] - 0.01) < 1e-12
    assert ("hs", "pbe") not in rel and ("other", "b3") not in rel                                                           # nothing comparable: no ΔE
    csv = results.overview_csv(results.state_rows(obj), "kcal/mol")
    assert "6.2751" in csv.splitlines()[1] and "same formula and method" not in csv                                            # 0.01 Eh; provenance lines only when given

def test_energy_units_are_converted_for_display_only():
    data = NS(value=-27.211386, units="eV")
    assert abs(results.to_hartree(data)[0] + 1.0) < 1e-9 and data.units == "eV" and data.value == -27.211386
    assert results.to_hartree(NS(value=1.0, units="parsec"))[0] is None and results.to_hartree(None) == (None, "no energy registered")

def test_logs_are_cut_to_their_end_and_marked(tmp_path):
    f = tmp_path / "big.log"; f.write_text("x" * 100 + "\n" + " SCF Done:  E(RPBE) = -1.0\n" + " Normal termination of Gaussian\n")
    text, note = results.read_log(str(f), limit=60)
    assert note and "x" * 100 not in text and text.endswith("Normal termination of Gaussian\n")
    assert [k for _, k, _ in results.log_marks(text)] == ["info", "ok"]
    steps = "\n".join(f" SCF Done:  E = -{i}.0" for i in range(50)) + "\n Error termination\n"
    marks = results.log_marks(steps)
    assert [(n, k) for n, k, _ in marks] == [(0, "info"), (49, "info"), (50, "err")]                                       # first and last energy, every error

# ---- a real system, imported in the test
def test_a_fresh_system_opens_without_writing_anything(local, tmp_path):
    env, info = local; root = tmp_path / "L"; before = tree(root)
    loaded = results.load(info.filepath, "water")
    assert loaded.provenance.file == os.path.join(info.systems_path, "water", "water.npy") and not loaded.provenance.moved
    assert [(r.source, r.state, r.group, r.energy) for r in loaded.summary.states] == [("water", "initial", "none", None)]
    assert loaded.summary.comps == [] and loaded.summary.counts() == (0, 1)
    assert tree(root) == before

def test_a_project_moved_elsewhere_is_read_from_its_new_folders(local, tmp_path):
    env, info = local
    moved = tmp_path / "elsewhere"; shutil.copytree(tmp_path / "L", moved)                                                    # like a download into another computer
    env2, info2 = backend.create_environment("loc2", str(moved / "Sources"), str(moved / "Systems"), str(moved / "Computations"), str(moved))
    before = tree(moved)
    obj, prov = results.open_system(info2.filepath, "water")
    assert prov.moved and prov.stored_root.startswith(str(tmp_path / "L")) and obj.computations_path.startswith(str(moved)) and obj.system_file == prov.file
    assert tree(moved) == before                                                                                                # pointed here in memory only

def test_errors_say_what_to_do(local, tmp_path):
    env, info = local
    with pytest.raises(results.ResultsError) as e: results.open_system(info.filepath, "nosuch")
    assert e.value.kind == "no_system" and "Run" in e.value.hint
    with pytest.raises(results.ResultsError) as e: results.open_system(str(tmp_path / "none.npy"), "water")
    assert e.value.kind == "no_environment"
    bad = os.path.join(info.systems_path, "broken", "broken.npy"); os.makedirs(os.path.dirname(bad)); open(bad, "wb").write(b"not a pickle")
    with pytest.raises(results.ResultsError) as e: results.open_system(info.filepath, "broken")
    assert e.value.kind == "unreadable"

def test_a_missing_addon_is_named_with_its_install_command(local, tmp_path, monkeypatch):
    env, info = local
    mod = tmp_path / "mods"; mod.mkdir(); (mod / "scope_sco_fake.py").write_text("class Thing:\n    object_type = 'system'\n")
    monkeypatch.syspath_prepend(str(mod)); import scope_sco_fake
    path = os.path.join(info.systems_path, "addon", "addon.npy"); os.makedirs(os.path.dirname(path))
    with open(path, "wb") as fh: pickle.dump(scope_sco_fake.Thing(), fh)
    monkeypatch.delitem(sys.modules, "scope_sco_fake"); monkeypatch.setattr(sys, "path", [p for p in sys.path if p != str(mod)])
    with pytest.raises(results.ResultsError) as e: results.open_system(info.filepath, "addon")
    assert e.value.kind == "addon" and "scope_sco_fake" in str(e.value) and "pip install scope_sco_fake" in e.value.hint

# ---- the page
def wait_for(app, condition, timeout=30) -> bool:
    t0 = time.time()
    while not condition() and time.time() - t0 < timeout: app.processEvents(); time.sleep(0.02)
    app.processEvents(); return condition()

def test_the_results_step_shows_the_system_and_reloads_when_its_file_changes(local, tmp_path):
    from PySide6.QtWidgets import QApplication
    from scope.gui.window import MainWindow, STEPS
    app = QApplication.instance() or QApplication([])
    env, info = local; root = tmp_path / "L"
    win = MainWindow(); win.show(); win.session.set_environment(env, info); before = tree(root)                       # shown: the page watches its file only while visible
    assert [s[0] for s in STEPS][-1] == "results" and win.pages[-1].key == "results"
    win.show_step("results"); tab = win.results_tab
    assert wait_for(app, lambda: tab.loaded is not None)
    assert tab.table.rowCount() == 1 and tab.table.item(0, 0).text() == "water" and tab.table.item(0, 1).text() == "initial"
    assert tab.table.item(0, 3).text() == "—" and "no calculation" in tab.table.item(0, 8).text()
    assert "water.npy" in tab.prov.text() and "0 of 1 sources" in tab.prov.text() and not tab.missing_btn.isEnabled()
    assert win.step_buttons[-1].text().startswith("✓")
    assert tree(root) == before
    first = tab.loaded
    npy = os.path.join(info.systems_path, "water", "water.npy"); os.utime(npy, (time.time() + 5, time.time() + 5))             # a run or a download saved it again
    assert wait_for(app, lambda: tab.loaded is not first, timeout=15)
    win.close()

@needs_tutorials
def test_tutorial_system_from_another_computer(tmp_path):
    """Tutorial 1's ABITEM was saved on its author's computer, with SCOPE 0.9.6, and only some outputs are shipped."""
    pytest.importorskip("scope_sco")
    root = tmp_path / "T1"; shutil.copytree(ABITEM, root)
    env, info = backend.create_environment("t1", str(root / "Sources"), str(root / "Systems"), str(root / "Computations"), str(tmp_path))
    before = tree(root)
    loaded = results.load(info.filepath, "ABITEM"); s, p = loaded.summary, loaded.provenance
    assert p.moved and p.saved_version == "0.9.6" and p.version_differs
    assert all(c.out_path.startswith(str(root)) for c in s.comps)
    assert len(s.comps) == 19 and len(s.missing_outputs) == 12 and s.counts() == (4, 6)
    rows = {(r.source, r.state): r for r in s.states}
    assert rows[("ref_hs_cell", "relax")].group == "ok" and rows[("ref_hs_cell", "relax")].retried                               # r1 failed, r2 worked
    assert rows[("ref_hs_cell", "vc_relax")].runs[2:5] == ["vc s3 r1", "vc s3 r2", "vc s3 r3"]
    assert rows[("ref_hs_mol", "b3lyp_opt")].minimum is True and rows[("ref_hs_mol", "b3lyp_opt")].n_freqs == 135
    de = results.relative_energies(s.states)
    assert abs(de[("ref_ls_mol", "b3lyp_opt")] * results.UNITS["kcal/mol"] - 4.329) < 0.01 and de[("ref_hs_mol", "b3lyp_opt")] == 0    # HS below LS, as in Tutorial 4
    assert ("ref_hs_mol", "pbe_opt") in de and abs(de[("ref_hs_mol", "pbe_opt")] * results.UNITS["kcal/mol"] - 9.85) < 0.05              # PBE compared with PBE only
    assert tree(root) == before

def test_download_missing_outputs_ticks_exactly_those_files(local, cluster):
    """The Results page's 'Download missing outputs…' opens the usual download with only the outputs it misses ticked."""
    from PySide6.QtWidgets import QApplication
    from scope.gui import remote
    from scope.gui.window import MainWindow
    app = QApplication.instance() or QApplication([])
    env, info = local
    comp = os.path.join(cluster.remote_root, "Computations", "water", "demo"); os.makedirs(comp)
    for name in ("opt_r1.log", "freq_r1.log", "opt_r1.chk"): open(os.path.join(comp, name), "w").write("x\n")
    win = MainWindow(); win.session.set_environment(env, info); tab = win.remote_tab
    tab.name.setText("fake"); tab.host.setEditText(cluster.host); tab.scope_bin.setText(cluster.scope_bin); tab.root.setText(cluster.remote_root); tab.env_file.setText(cluster.remote_env)
    assert tab.save_profile() and "fake" in remote.load_profiles()
    tab.refresh_systems()
    dialog = tab.open_download(system="water", wanted=["demo/opt_r1.log", "demo/scf_r1.log"]); t0 = time.time()
    while (dialog.busy or not dialog.listing) and time.time() - t0 < 30: app.processEvents(); time.sleep(0.02)
    assert {f.rel for f in dialog.files if f.selected} == {"demo/opt_r1.log"}                                 # freq_r1.log is new too, but was not asked for
    assert "1 are not on the cluster either" in dialog.log.toPlainText()
    dialog.close(); win.close()

# ---- R2: one state in detail (structure, frequencies, spectra)
AZO = os.path.join(TUTORIALS, "Data", "9-Tutorial_9")
needs_azo = pytest.mark.skipif(not os.path.isfile(os.path.join(AZO, "Systems", "test", "test.npy")), reason="set SCOPE_TUTORIALS to the Scope_Tutorials folder")

def test_geometry_and_frequencies_export_text():
    from scope.gui import structure
    s = structure.Structure("w", ["O", "H", "H"], [[0, 0, 0.117], [0, 0.757, -0.469], [0, -0.757, -0.469]])
    lines = results.xyz_text(s, "water\nopt").splitlines()
    assert lines[0] == "3" and lines[1] == "water opt" and lines[2].split() == ["O", "0.00000000", "0.00000000", "0.11700000"]
    csv = results.modes_csv([results.Mode(1, -45.2, 1.45, 8.37, "A"), results.Mode(2, 48.4, None, None, "")]).splitlines()
    assert csv[1] == "1,-45.2000,1.4500,8.3700,A" and csv[2] == "2,48.4000,,,"

def test_a_state_without_its_own_coordinates_has_no_structure():
    from scope.gui import structure
    src = NS(name="m", labels=["O", "H", "H"], coord=[[0, 0, 0], [1, 0, 0], [0, 1, 0]], adjmat=None)
    assert structure.state_structure(src, NS(name="opt", coord=[])) is None
    assert structure.state_structure(src, NS(name="opt", coord=[[0, 0, 0]], labels=["O", "H", "H"])) is None                  # coordinates and atoms disagree
    assert structure.state_structure(src, None).title == "m"

def test_the_state_tab_of_a_fresh_system_shows_its_structure_and_saves_it(local, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication, QFileDialog
    from scope.gui.window import MainWindow
    app = QApplication.instance() or QApplication([])
    env, info = local; root = tmp_path / "L"; out = tmp_path / "export" / "water.xyz"; out.parent.mkdir()
    win = MainWindow(); win.show(); win.session.set_environment(env, info); before = tree(root)
    win.show_step("results"); tab = win.results_tab
    assert wait_for(app, lambda: tab.loaded is not None)
    tab.open_state(0); st = tab.state
    assert tab.tabs.currentIndex() == 2 and st.detail.state == "initial" and st.kind.count() == 0
    assert st.lower.currentIndex() == 2 and "No frequencies" in st.canvas.message and st.modes.rowCount() == 0          # nothing to plot: the structure is shown
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(out), "")))
    st.save_xyz()
    lines = out.read_text().splitlines()
    assert lines[0] == "3" and "water initial" in lines[1] and [l.split()[0] for l in lines[2:]] == ["O", "H", "H"]
    assert tree(root) == before                                                                                                  # the export went where it was asked, not into the project
    win.close()

@needs_tutorials
def test_tutorial_ir_spectrum_is_scopes_own(tmp_path):
    """R2's check: the IR curve shown is SCOPE's get_ir_spectrum (what plot_ir_spectrum draws) with the same settings."""
    import numpy as np
    from scope.read_write import load_binary
    pytest.importorskip("scope_sco")
    root = tmp_path / "T1"; shutil.copytree(os.path.join(ABITEM, "Systems"), root / "Systems"); (root / "Computations").mkdir(); (root / "Sources").mkdir()
    env, info = backend.create_environment("t1", str(root / "Sources"), str(root / "Systems"), str(root / "Computations"), str(tmp_path))
    obj, _ = results.open_system(info.filepath, "ABITEM")
    d = results.state_detail(obj, "ref_hs_mol", "b3lyp_opt")
    assert len(d.modes) == 135 and not any(m.freq < 0 for m in d.modes) and d.has_ir and d.n_excited == 0 and len(d.structure.labels) == 47
    sp = results.spectrum(obj, "ref_hs_mol", "b3lyp_opt", "ir", "lorentzian", 15.0, 0, 2500)
    ref = load_binary(str(root / "Systems" / "ABITEM" / "ABITEM.npy"))                                                         # an independent copy, SCOPE's own call
    st = [s for src in ref.sources if src.name == "ref_hs_mol" for s in src.states if s.name == "b3lyp_opt"][0]
    x, y = st.get_ir_spectrum(vmin=0, vmax=2500, function="lorentzian", sigma=15.0)
    assert np.allclose(sp.x, x) and np.allclose(sp.y, y) and len(sp.sticks) == 135

@needs_azo
def test_tutorial_azo_transition_state_and_absorption(tmp_path):
    pytest.importorskip("scope_azo")
    root = tmp_path / "T9"; shutil.copytree(os.path.join(AZO, "Systems"), root / "Systems"); (root / "Computations").mkdir(); (root / "Sources").mkdir()
    env, info = backend.create_environment("t9", str(root / "Sources"), str(root / "Systems"), str(root / "Computations"), str(tmp_path))
    loaded = results.load(info.filepath, "test"); obj = loaded.system
    rows = {(r.source, r.state): r for r in loaded.summary.states}
    ts = results.state_detail(obj, "tsrot_a_s", "opt")
    assert [round(m.freq, 2) for m in ts.modes if m.freq < 0] == [-45.16] and rows[("tsrot_a_s", "opt")].minimum is False        # one imaginary mode: a transition state
    trans = results.state_detail(obj, "trans", "opt")
    assert trans.n_excited == 10 and rows[("trans", "opt")].minimum is True
    ab = results.spectrum(obj, "trans", "opt", "abs", "gaussian", 0.2, 200, 1000)
    assert ab.x[0] >= 200 and ab.x[-1] <= 1000 and all(200 <= p <= 1000 for p, _ in ab.sticks) and max(ab.y) > 0
    with pytest.raises(Exception): results.spectrum(obj, "tsrot_a_s", "opt", "abs")                                              # no excited states there

# ---- R3: thermochemistry and comparison
def th(name, T, G, Helec=0.0, Hvib=None, Svib=None, Selec=0.0):
    n = len(T); return results.Thermo(name, "s", list(T), Helec, Selec, Hvib or [0.0] * n, Svib or [0.0] * n, list(G), 1.0, 0, {})

def test_where_delta_g_changes_sign():
    d = results.difference(th("a", [100, 200, 300], [1.0, 0.0, -1.0]), th("b", [100, 200, 300], [0.0, 0.5, 0.0]))
    assert d.crossing == [166.667] and d.dG == [1.0, -0.5, -1.0]
    assert results.difference(th("a", [100, 200], [0.0, -1.0]), th("b", [100, 200], [0.0, 0.0])).crossing == [100.0]               # exactly zero on the grid
    assert results.difference(th("a", [100, 200, 300], [-1, -2, -3]), th("b", [100, 200, 300], [0, 0, 0])).crossing == []
    only = results.difference(th("a", [100, 200, 300], [0, 0, 0]), th("b", [200, 300, 400], [1, 1, 1]))
    assert only.T == [200, 300]                                                                                                   # only temperatures both have
    two = results.difference(th("a", [300], [0.0], Helec=-1.0, Hvib=[0.2], Svib=[0.001]), th("b", [300], [0.0], Helec=-1.5, Hvib=[0.1], Svib=[0.0005]))
    assert abs(two.dH[0] - 0.6) < 1e-12 and abs(two.mTdS[0] + 0.15) < 1e-12                                                       # ΔH = 0.5 + 0.1; −TΔS = −300 × 0.0005

def test_comparison_only_within_one_formula_and_method_across_systems():
    R = results.CompareRow
    rows = [R("s1", "a", "opt", "C2", "g16 pbe", -10.0), R("s2", "b", "opt", "C2", "g16 pbe", -10.5), R("s2", "c", "opt", "C2", "g16 b3lyp", -11.0),
            R("s3", "d", "opt", "N2", "g16 pbe", -5.0), R("s3", "e", "opt", "C2", "g16 pbe", None, "no frequencies")]
    rel = results.compare_relative(rows)
    assert rel == {("s1", "a", "opt"): 0.5, ("s2", "b", "opt"): 0.0}
    csv = results.compare_csv(rows, "kcal/mol", "gibbs", 300).splitlines()
    assert csv[0].startswith("# quantity: G at 300 K") and "313.7547" in csv[2] and csv[-1].endswith("no frequencies")

def test_thermochemistry_and_comparison_of_a_fresh_system_say_why_not(local, tmp_path):
    from PySide6.QtWidgets import QApplication
    from scope.gui.window import MainWindow
    app = QApplication.instance() or QApplication([])
    env, info = local
    loaded = results.load(info.filepath, "water")
    assert "no frequencies" in results.thermo_ready(loaded.system, "water", "initial")
    with pytest.raises(ValueError): results.thermo(loaded.system, "water", "initial", [298.15])
    assert results.compare_rows([loaded], "energy") == []                                                                         # no energy registered yet
    win = MainWindow(); win.show(); win.session.set_environment(env, info); win.show_step("results"); tab = win.results_tab
    assert wait_for(app, lambda: tab.loaded is not None)
    assert tab.thermo.a.count() == 0 and "No state of this system has frequencies" in tab.thermo.canvas.message
    tab.compare.run(); assert wait_for(app, lambda: tab.compare.task is None)
    assert tab.compare.rows == [] and "0 state(s)" in tab.compare.status.text()
    win.close()

@needs_tutorials
def test_tutorial_spin_states_thermochemistry(tmp_path):
    """Tutorial 4: G of the HS state as SCOPE computes it, and HS below LS from 10 to 500 K, so no T½. The loaded state is not changed."""
    pytest.importorskip("scope_sco")
    root = tmp_path / "T1"; shutil.copytree(os.path.join(ABITEM, "Systems"), root / "Systems"); (root / "Computations").mkdir(); (root / "Sources").mkdir()
    env, info = backend.create_environment("t1", str(root / "Sources"), str(root / "Systems"), str(root / "Computations"), str(tmp_path))
    obj, _ = results.open_system(info.filepath, "ABITEM")
    st = results.find_state(obj, "ref_hs_mol", "b3lyp_opt")[1]; before = (dict(st.results), sorted(vars(st)))
    hs = results.thermo(obj, "ref_hs_mol", "b3lyp_opt", range(10, 501, 10)); ls = results.thermo(obj, "ref_ls_mol", "b3lyp_opt", range(10, 501, 10))
    assert hs.G[0] == pytest.approx(-3159.273935896281, abs=1e-9) and hs.z == 1 and hs.n_imag == 0                               # SCOPE's value (Tutorial 4 settings)
    d = results.difference(hs, ls)
    assert all(x < 0 for x in d.dG) and d.crossing == [] and d.dG[d.T.index(300)] * results.UNITS["kcal/mol"] == pytest.approx(-10.0, abs=0.1)
    assert dict(st.results) == before[0] and all(st.results[k] is before[0][k] for k in before[0]) and sorted(vars(st)) == before[1]
    qr = results.thermo(obj, "ref_hs_mol", "b3lyp_opt", [300], "QRRHO")
    assert qr.settings["model"] == "QRRHO" and qr.G[0] != hs.G[hs.T.index(300)]
    csv = results.difference_csv(d).splitlines(); assert "no temperature in range" in csv[0] and csv[1].startswith("T_K,dG_kcal/mol")

@needs_azo
def test_tutorial_azo_comparison_and_imaginary_policy(tmp_path):
    pytest.importorskip("scope_azo")
    root = tmp_path / "T9"; shutil.copytree(os.path.join(AZO, "Systems"), root / "Systems"); (root / "Computations").mkdir(); (root / "Sources").mkdir()
    env, info = backend.create_environment("t9", str(root / "Sources"), str(root / "Systems"), str(root / "Computations"), str(tmp_path))
    loaded = results.load(info.filepath, "test")
    with pytest.raises(ValueError): results.thermo(loaded.system, "tsrot_a_s", "opt", [298.15], imaginary="raise")                 # a transition state is not a minimum
    ts = results.thermo(loaded.system, "tsrot_a_s", "opt", [298.15]); assert ts.n_imag == 1
    rows = results.compare_rows([loaded], "gibbs", 298.15); rel = results.compare_relative(rows)
    assert len(rows) == 10 and rel[("test", "trans", "opt")] == 0                                                                  # trans is the most stable isomer
    assert rel[("test", "cis", "opt")] * results.UNITS["kcal/mol"] == pytest.approx(3.55, abs=0.05)

# ---- R4: notebooks, exports with provenance, older copies
from scope.gui import notebooks

def run_notebook(path, monkeypatch) -> str:
    """Executes a notebook as Jupyter would (kernel 'python3' of this Python) and returns all it printed; fails on any error output."""
    import nbformat
    from nbclient import NotebookClient
    monkeypatch.setenv("JUPYTER_PREFER_ENV_PATH", "1"); monkeypatch.delenv("MPLBACKEND", raising=False)
    nb = nbformat.read(path, as_version=4)
    NotebookClient(nb, kernel_name=nb.metadata.kernelspec.name, timeout=600, resources={"metadata": {"path": os.path.dirname(path)}}).execute()          # the kernel the notebook names
    out, images = [], 0
    for c in nb.cells:
        for o in c.get("outputs", []):
            assert o.output_type != "error", f"{o.ename}: {o.evalue}"
            if o.output_type == "stream": out.append(o.text)
            images += "image/png" in o.get("data", {})
    return "".join(out) + f"\n[{images} images]"

def test_notebook_names_and_folder_never_replace_the_users_work(tmp_path):
    info = NS(filepath=str(tmp_path / "P" / "scope_env_x.npy"), sources_path=str(tmp_path / "P" / "Sources"), systems_path=str(tmp_path / "P" / "Systems"), computations_path=str(tmp_path / "P" / "Computations/"))
    assert notebooks.notebooks_dir(info) == str(tmp_path / "P" / "Notebooks")
    odd = NS(filepath=str(tmp_path / "envs" / "e.npy"), sources_path="/a/Sources", systems_path="/b/Systems", computations_path="/a/Computations")
    assert notebooks.project_folder(odd) == str(tmp_path / "envs")                                          # not side by side: the environment's folder
    folder = tmp_path / "P" / "Notebooks"; folder.mkdir(parents=True); mine = folder / "water.ipynb"; mine.write_text("my work")
    nb = notebooks.build("/x/scope_env.npy", "water")
    first = notebooks.write_new(str(folder), nb, "water"); second = notebooks.write_new(str(folder), nb, "water")
    assert os.path.basename(first) == "water-2.ipynb" and os.path.basename(second) == "water-3.ipynb" and mine.read_text() == "my work"
    assert set(map(os.path.basename, notebooks.existing(str(folder), "water"))) == {"water.ipynb", "water-2.ipynb", "water-3.ipynb"}

def test_notebook_template_is_valid_code_even_with_windows_paths():
    nb = notebooks.build(r"C:\Users\me\proj\scope_env_loc.npy", "o'water", ("s", "opt"), (("a", "opt"), ("b", "opt")), r"C:\Users\me\proj\Systems\w\w.npy.bak-1")
    code = [c.source for c in nb.cells if c.cell_type == "code"]
    for src in code: compile(src, "cell", "exec")
    assert r"'C:\\Users\\me\\proj\\scope_env_loc.npy'" in code[0] and "FILE" in code[0] and "system, prov = results.open_system(ENV_FILE, SYSTEM, FILE)" in code[0]
    assert "STATE = ('s', 'opt')" in code[3] and "PAIR = (('a', 'opt'), ('b', 'opt'))" in code[5]
    assert not any(".save(" in src for src in code) and "get_T12" not in "".join(code)                                       # read-only; no scope_sco writes
    program, args = notebooks.jupyter_command("/p/Notebooks/w.ipynb", "/p/Notebooks")
    assert program == sys.executable and args[:3] == ["-m", "jupyter", "lab"] and "--ServerApp.root_dir=/p/Notebooks" in args and args[-1] == "/p/Notebooks/w.ipynb"
    env = notebooks.jupyter_environment({"A": "1"}); own = os.path.join(sys.prefix, "share", "jupyter", "lab")
    assert env["A"] == "1" and env["JUPYTER_PREFER_ENV_PATH"] == "1" and env["JUPYTERLAB_DIR"] == own                       # this environment's JupyterLab files only
    assert notebooks.jupyter_environment({"JUPYTERLAB_DIR": "/mine"})["JUPYTERLAB_DIR"] == "/mine"
    assert notebooks.notebook_url({"url": "http://localhost:8890/", "token": "abc"}, "/p/Notebooks", "/p/Notebooks/my water.ipynb") == "http://localhost:8890/lab/tree/my%20water.ipynb?token=abc"

def test_the_generated_notebook_runs_on_a_fresh_system(local, tmp_path, monkeypatch):
    """R4's check on a system with nothing computed: every cell runs, says why there is nothing to show, and only Notebooks/ is new."""
    pytest.importorskip("nbclient")
    env, info = local; root = tmp_path / "L"; before = tree(root)
    assert notebooks.kernel_dir().startswith(str(tmp_path))                                                                # never the user's real Jupyter folder
    kernel = notebooks.ensure_kernel(); assert kernel == "scope-gui"                                                       # registered in the test's own HOME
    path = notebooks.write_new(notebooks.notebooks_dir(info), notebooks.build(info.filepath, "water", kernel=kernel), "water")
    assert path == str(root / "Notebooks" / "water.ipynb")
    text = run_notebook(path, monkeypatch)
    assert "0 of 1 sources" in text and "No state has frequencies yet" in text and "no ΔG to show" in text
    assert f"Python:       {sys.executable}" in text and "this kernel is not the Python" not in text                       # the kernel is this window's Python
    assert [x for x in tree(root) if x not in before and not x[1].startswith("Notebooks")] == []                           # nothing else was written

@needs_tutorials
def test_the_generated_notebook_runs_on_tutorial_1(tmp_path, monkeypatch):
    """R4's check on registered results: Tutorial 1's ABITEM, read from another computer's paths, HS below LS (Tutorial 4)."""
    pytest.importorskip("scope_sco"); pytest.importorskip("nbclient")
    root = tmp_path / "T1"; shutil.copytree(os.path.join(ABITEM, "Systems"), root / "Systems"); (root / "Computations").mkdir(); (root / "Sources").mkdir()
    env, info = backend.create_environment("t1", str(root / "Sources"), str(root / "Systems"), str(root / "Computations"), str(root))
    before = tree(root)
    path = notebooks.write_new(notebooks.notebooks_dir(info), notebooks.build(info.filepath, "ABITEM"), "ABITEM")
    text = run_notebook(path, monkeypatch)
    assert "Saved by SCOPE 0.9.6" in text and "Written where SCOPE ran" in text and "4 of 6 sources" in text
    assert "ref_hs_mol · b3lyp_opt: 135 modes, 0 imaginary" in text and "G = -3159.3" in text
    assert "A = ref_hs_mol · b3lyp_opt, B = ref_ls_mol · b3lyp_opt" in text and "ΔG keeps its sign" in text and "[3 images]" in text
    assert [x for x in tree(root) if x not in before and not x[1].startswith("Notebooks")] == []

@needs_azo
def test_the_generated_notebook_runs_on_tutorial_9(tmp_path, monkeypatch):
    pytest.importorskip("scope_azo"); pytest.importorskip("nbclient")
    root = tmp_path / "T9"; shutil.copytree(os.path.join(AZO, "Systems"), root / "Systems"); (root / "Computations").mkdir(); (root / "Sources").mkdir()
    env, info = backend.create_environment("t9", str(root / "Sources"), str(root / "Systems"), str(root / "Computations"), str(root))
    path = notebooks.write_new(notebooks.notebooks_dir(info), notebooks.build(info.filepath, "test", ("trans", "opt"), (("cis", "opt"), ("trans", "opt"))), "test")
    text = run_notebook(path, monkeypatch)
    assert "trans · opt:" in text and "A = cis · opt, B = trans · opt" in text and "[4 images]" in text                    # IR, absorption, G(T), ΔG(T)

def test_exports_say_where_their_numbers_come_from(local, tmp_path):
    import warnings
    from PIL import Image
    env, info = local; loaded = results.load(info.filepath, "water"); p = loaded.provenance
    h = results.header(p, {"units": "kcal/mol"}).splitlines()
    assert h[0] == "# system: water" and h[1].startswith(f"# file: {p.file} (") and "read with SCOPE" in h[2] and h[3] == f"# folders of environment: {info.filepath}"
    assert h[4].startswith("# exported: ") and h[-1] == "# units: kcal/mol"
    assert results.overview_csv(loaded.summary.states, "kcal/mol", p).startswith("# system: water\n")
    calc = results.comps_csv(loaded.summary.comps, p).splitlines(); assert calc[0] == "# system: water" and calc[-1].startswith("branch,workflow")
    th = results.Thermo("a", "s", [300.0], -1.0, 0.0, [0.1], [0.0], [-0.9], 1.0, 0, {"model": "HO"})
    assert results.thermo_csv(th, "kcal/mol", p).startswith("# system: water") and results.difference_csv(results.difference(th, th), "kcal/mol", p, {"model": "HO"}).count("# model: HO") == 1
    from PySide6.QtWidgets import QApplication
    from scope.gui.plots import PlotCanvas, Lines
    app = QApplication.instance() or QApplication([])
    canvas = PlotCanvas(); canvas.plot(Lines("t", "x", "y", [("a", [1, 2], [3, 4])]))
    meta = results.plot_metadata(p, {"model": "HO"}, "G(T) of water")
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        for ext in ("png", "svg", "pdf"): canvas.save(str(tmp_path / f"plot.{ext}"), meta)
    with Image.open(tmp_path / "plot.png") as im: text = im.text
    assert text["Title"] == "G(T) of water" and f"file: {p.file}" in text["Description"] and "model: HO" in text["Description"]
    assert f"file: {p.file}" in (tmp_path / "plot.svg").read_text() and (tmp_path / "plot.pdf").stat().st_size > 0
    sp = results.Spectrum([1.0, 2.0, 3.0], [0.0, 5.0, 0.0], [(2.0, 7.5)], "Wavenumber (cm⁻¹)", "IR", "IR · w · opt")
    rows = results.spectrum_csv(sp, p, {"kernel": "gaussian"}).splitlines()
    assert rows[0] == "# system: water" and "# kernel: gaussian" in rows and "# spectrum: IR · w · opt" in rows
    i = rows.index("Wavenumber (cm⁻¹),IR,stick Wavenumber (cm⁻¹),stick height"); assert rows[i + 1:] == ["1,0,2,7.5", "2,5,,", "3,0,,"]

def test_version_diff_names_what_changed():
    S = lambda *rows: results.Summary([results.StateRow(s, "molecule", "H2-O", st, e, "", None, 0, 0, runs, g) for s, st, e, runs, g in rows], [])
    old = S(("w", "initial", None, [], "none"), ("w", "opt", -76.0, ["opt r1"], "warn"), ("w", "freq", -76.1, ["freq r1"], "ok"), ("w", "old", -1.0, ["x r1"], "ok"))
    new = S(("w", "initial", -75.0, ["scf r1"], "ok"), ("w", "opt", -76.0, ["opt r1"], "ok"), ("w", "freq", -76.1, ["freq r1", "freq r2"], "ok"), ("w", "td", -70.0, ["td r1"], "ok"))
    assert [(r.state, r.change) for r in results.version_diff(old, new)] == [("initial", "computed"), ("opt", "status"), ("freq", "runs"), ("td", "new"), ("old", "gone")]
    same = results.version_diff(new, new); assert all(r.change == "" for r in same)

def test_an_older_copy_opens_beside_the_current_file_without_writing(local, tmp_path):
    from PySide6.QtWidgets import QApplication
    from scope.gui.window import MainWindow
    app = QApplication.instance() or QApplication([])
    env, info = local; root = tmp_path / "L"
    npy = os.path.join(info.systems_path, "water", "water.npy"); bak = npy + ".bak-20261119_101200"; shutil.copy2(npy, bak); os.utime(bak, (time.time() - 3600, time.time() - 3600))
    before = tree(root)
    obj, prov = results.open_system(info.filepath, "water", bak)
    assert prov.is_copy and prov.file == bak and prov.current_file == npy and prov.backups == [bak] and "(copy of " in prov.label
    assert obj.computations_path == os.path.join(info.computations_path, "water") + "/" and "older copy of: " + npy in results.header(prov)
    assert not results.open_system(info.filepath, "water")[1].is_copy
    win = MainWindow(); win.show(); win.session.set_environment(env, info); win.show_step("results"); tab = win.results_tab
    assert wait_for(app, lambda: tab.loaded is not None)
    assert tab.older_btn.isEnabled() and tab.older_btn.text() == "Older copies (1)" and len(tab.older_menu.actions()) == 1
    dialog = tab.open_copy(bak)
    assert wait_for(app, lambda: dialog.old is not None)
    assert dialog.table.rowCount() == 1 and dialog.table.item(0, 1).text() == "initial" and dialog.table.item(0, 8).text() == ""     # the same state, unchanged
    dialog.only.setChecked(True); assert dialog.table.rowCount() == 0
    assert tab.loaded.provenance.file == npy and tree(root) == before                                                             # the page still shows the current file
    dialog.close(); win.close()

def test_open_in_notebook_writes_it_and_starts_or_reuses_jupyter(local, tmp_path, monkeypatch):
    """The page writes a new notebook each time, starts Jupyter Lab with this window's Python (the start is replaced here: no real server
    in tests), opens the next notebook in the running server, copies the first cell, and exports the current table with its provenance."""
    from PySide6.QtGui import QDesktopServices, QGuiApplication
    from PySide6.QtWidgets import QApplication, QFileDialog
    from scope.gui.window import MainWindow
    app = QApplication.instance() or QApplication([])
    env, info = local; root = tmp_path / "L"; folder = str(root / "Notebooks")
    started, opened, server, stopped = [], [], {}, []
    proc = NS(alive=True); proc.poll = lambda: None if proc.alive else 0; proc.terminate = lambda: stopped.append(1)
    monkeypatch.setattr(notebooks, "spawn", lambda program, args, env, log: started.append((program, args, env, log)) or proc)
    monkeypatch.setattr(notebooks, "running_server", lambda r: server or None)
    monkeypatch.setattr(QDesktopServices, "openUrl", staticmethod(lambda url: opened.append(url.toString()) or True))
    win = MainWindow(); win.show(); win.session.set_environment(env, info); win.show_step("results"); tab = win.results_tab
    assert wait_for(app, lambda: tab.loaded is not None) and tab.notebook_btn.isEnabled()
    first = tab.open_notebook()
    assert first == os.path.join(folder, "water.ipynb") and os.path.isfile(first) and tab.jupyter is proc and tab.jupyter_running()
    program, args, jenv, log = started[0]
    assert program == sys.executable and args[:3] == ["-m", "jupyter", "lab"] and f"--ServerApp.root_dir={folder}" in args and args[-1] == first and jenv["JUPYTER_PREFER_ENV_PATH"] == "1"
    second = tab.open_notebook()                                                                              # clicked again while Jupyter is still starting
    assert os.path.basename(second) == "water-2.ipynb" and len(started) == 1 and stopped == [] and "still starting" in tab.issues.text()
    server.update(url="http://localhost:8899/", token="tok", pid=1, root_dir=folder); tab.poll_jupyter()     # it is up: the waiting notebook opens in it
    assert opened == ["http://localhost:8899/lab/tree/water-2.ipynb?token=tok"] and not tab.jupyter_timer.isActive()
    third = tab.open_notebook()
    assert os.path.basename(third) == "water-3.ipynb" and len(started) == 1 and opened[-1].endswith("/lab/tree/water-3.ipynb?token=tok")
    tab.copy_code(); code = QGuiApplication.clipboard().text()
    assert f"ENV_FILE = {info.filepath!r}" in code and "results.open_system(ENV_FILE, SYSTEM)" in code
    out = tmp_path / "export" / "o.csv"; out.parent.mkdir()
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(out), "")))
    tab.tabs.setCurrentIndex(0); tab.export_table(); assert out.read_text().startswith("# system: water\n")
    tab.tabs.setCurrentIndex(1); tab.export_table(); assert "branch,workflow,calculation" in out.read_text()
    monkeypatch.setattr(notebooks, "jupyter_missing", lambda: "python -m pip install jupyterlab")
    fourth = tab.open_notebook(); assert os.path.isfile(fourth) and len(started) == 1 and "pip install jupyterlab" in tab.issues.text()
    proc.alive = False                                                                                                            # quit from Jupyter's own menu
    assert tab.close_jupyter() and tab.jupyter is None and stopped == []                                                          # nothing running: no question, no signal
    win.close()

def test_a_real_jupyter_lab_serves_its_settings(tmp_path):
    """Starts Jupyter Lab as the page does (without a browser) and asks for what its page loads first. On the user's Mac an older
    system-wide JupyterLab left a schema in /usr/local/share/jupyter/lab that made /lab/api/settings fail, and the page stayed blank."""
    import urllib.request
    pytest.importorskip("jupyterlab")
    root = tmp_path / "Notebooks"; root.mkdir()
    path = notebooks.write_new(str(root), notebooks.build("/x/scope_env.npy", "w"), "w")
    program, args = notebooks.jupyter_command(path, str(root))
    proc = notebooks.spawn(program, args[:-1] + ["--no-browser", "--ServerApp.port_retries=50", args[-1]], notebooks.jupyter_environment(os.environ), str(tmp_path / "log.txt"))
    try:
        server, t0 = None, time.time()
        while server is None and proc.poll() is None and time.time() - t0 < 90: time.sleep(0.5); server = notebooks.running_server(str(root))
        assert server, (tmp_path / "log.txt").read_text()[-2000:]
        for api in ("lab/api/settings", "lab/api/themes", "api/kernelspecs"):
            with urllib.request.urlopen(f"{server['url']}{api}?token={server['token']}", timeout=30) as r: assert r.status == 200, api
        with urllib.request.urlopen(notebooks.notebook_url(server, str(root), path), timeout=30) as r: assert r.status == 200
    finally:
        notebooks.stop(proc); proc.wait(timeout=30)

def test_rdkit_warnings_about_a_newer_rdkit_become_one_note():
    """A pickle written with a newer RDKit makes RDKit print two lines per molecule while it is read (288 lines for ABITEM). They are
    counted into Provenance.rdkit_note; any other RDKit message is still printed."""
    import logging
    pytest.importorskip("rdkit")
    seen = []; catch = logging.Handler(); catch.emit = lambda r: seen.append(r.getMessage())
    log = logging.getLogger("rdkit"); log.addHandler(catch)
    quiet = results._RDKitDepickle()
    with quiet:
        for _ in range(3):
            log.warning("[15:51:20] Depickling from a version number (16.3)that is higher than our version (16.2).")
            log.warning("This probably won't work.")
        log.warning("something else from RDKit")
    shown = " ".join(seen)
    assert quiet.count == 3 and "Depickling" not in shown and "probably" not in shown and "something else from RDKit" in shown
    assert quiet.note.startswith("3 RDKit molecule(s) stored by a newer RDKit (pickle format 16.3; this RDKit reads 16.2")
    logging.getLogger("rdkit").warning("Depickling from a version number (1)that is higher than our version (0).")      # only while a file is read
    log.removeHandler(catch)
    assert "Depickling" in seen[-1] and quiet.count == 3

@needs_tutorials
def test_reading_tutorial_1_prints_no_rdkit_flood(tmp_path, capfd):
    pytest.importorskip("scope_sco")
    root = tmp_path / "T1"; shutil.copytree(os.path.join(ABITEM, "Systems"), root / "Systems"); (root / "Computations").mkdir(); (root / "Sources").mkdir()
    env, info = backend.create_environment("t1", str(root / "Sources"), str(root / "Systems"), str(root / "Computations"), str(tmp_path))
    capfd.readouterr(); obj, prov = results.open_system(info.filepath, "ABITEM"); err = capfd.readouterr().err
    assert "Depickling" not in err and err.count("\n") < 5
    assert not prov.rdkit_note or (prov.rdkit_note in results.header(prov) and "newer RDKit" in prov.rdkit_note)                # one line, also in exports

def test_the_notebook_says_which_python_lacks_scope():
    """Run with a Python that has no SCOPE (here: no scope on the path, as the system Jupyter's kernel on the user's Mac), the first cell
    names that Python and the one to use, instead of a bare ModuleNotFoundError."""
    import subprocess
    code = notebooks.setup_code("/x/scope_env.npy", "water")
    out = subprocess.run([sys.executable, "-I", "-S", "-c", code], capture_output=True, text=True)
    assert out.returncode != 0 and "ModuleNotFoundError: This kernel runs" in out.stderr and sys.executable in out.stderr and "Open in notebook" in out.stderr

def test_the_scope_gui_kernel_runs_this_python_and_is_corrected():
    """'Open in notebook' registers the 'SCOPE GUI' kernel in the user's Jupyter folder (here the test's HOME), pointing at this Python by
    full path, so a system-wide Jupyter or VS Code runs the notebook with SCOPE. A kernel left by another Python is corrected."""
    import json
    folder = notebooks.kernel_dir()
    assert folder.startswith(os.environ["HOME"]) and os.environ["HOME"] != os.path.expanduser("~" + os.environ.get("USER", ""))   # isolated, never the real one
    assert notebooks.ensure_kernel() == "scope-gui"
    spec = json.load(open(os.path.join(folder, "kernel.json")))
    assert spec["argv"][:3] == [sys.executable, "-m", "ipykernel_launcher"] and spec["display_name"].startswith("SCOPE GUI (Python 3.")
    json.dump({"argv": ["/old/python", "-m", "ipykernel_launcher", "-f", "{connection_file}"], "display_name": "x", "language": "python"}, open(os.path.join(folder, "kernel.json"), "w"))
    assert notebooks.ensure_kernel() == "scope-gui" and json.load(open(os.path.join(folder, "kernel.json")))["argv"][0] == sys.executable
    from jupyter_client.kernelspec import KernelSpecManager
    assert KernelSpecManager().get_kernel_spec("scope-gui").argv[0] == sys.executable                                          # Jupyter finds it
    nb = notebooks.build("/x/e.npy", "w", kernel="scope-gui"); assert nb.metadata.kernelspec.name == "scope-gui"
    assert notebooks.build("/x/e.npy", "w").metadata.kernelspec.name == "python3"
