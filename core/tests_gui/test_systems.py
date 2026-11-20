"""Point 1: Systems and Sources (several .xyz as sources of one system). Point 2: charge and spin of a source, total vs atomic, defaults visible."""
import glob
import os
import time
import pytest

from scope.gui import backend, results, systems
from test_remote import isolated, local, WATER                              # noqa: F401  (fixtures: temp HOME, fake ssh)

FE = "7\nFe(NH3)6? no: a small iron complex\nFe 0 0 0\nN 2.0 0 0\nN -2.0 0 0\nN 0 2.0 0\nN 0 -2.0 0\nN 0 0 2.0\nN 0 0 -2.0\n"
METHYL = "4\nmethyl radical\nC 0 0 0\nH 1.08 0 0\nH -0.54 0.935 0\nH -0.54 -0.935 0\n"

def xyz(tmp_path, name, text):
    p = tmp_path / name; p.write_text(text); return str(p)

def reload(env, system):
    return results.open_system(env, system)[0]

# ---- point 1
def test_one_system_with_several_sources(local, tmp_path):
    env, info = local
    path = systems.create_system(env, "fe_sco", [(xyz(tmp_path, "fe.hs.xyz", FE), "fe.hs"), (xyz(tmp_path, "fe_ls.xyz", FE), "fe_ls")])
    tree = systems.read_tree(path)
    assert [s.name for s in tree.sources] == ["fe.hs", "fe_ls"]                                    # the dot is kept (load_single_xyz would cut it)
    assert [st.name for st in tree.sources[0].states] == ["initial"] and tree.sources[0].states[0].has_geometry
    assert os.path.isfile(os.path.join(info.sources_path, "fe_sco", "fe.hs.xyz"))
    with pytest.raises(ValueError, match="already exists"): systems.create_system(env, "fe_sco", [(xyz(tmp_path, "x.xyz", FE), "x")])
    with pytest.raises(ValueError, match="same source name"): systems.create_system(env, "dup", [(xyz(tmp_path, "a.xyz", FE), "a"), (xyz(tmp_path, "b.xyz", FE), "a")])

def test_add_a_source_to_an_existing_system(local, tmp_path):
    env, info = local
    name = systems.add_source_xyz(env, "water", xyz(tmp_path, "w2.xyz", WATER), "Water Dimer")
    assert name == "water_dimer" and [s.name for s in systems.read_tree(results.system_file(env, "water")).sources] == ["water", "water_dimer"]
    assert glob.glob(results.system_file(env, "water") + ".bak-*")                                # the file before the change is kept
    with pytest.raises(ValueError, match="already has a source"): systems.add_source_xyz(env, "water", xyz(tmp_path, "w3.xyz", WATER), "water_dimer")
    with pytest.raises(ValueError, match="safe"): systems.add_source_xyz(env, "water", xyz(tmp_path, "w4.xyz", WATER), "a;b")

def test_no_change_while_a_run_of_the_system_is_active(local, tmp_path, monkeypatch):
    env, info = local
    monkeypatch.setattr(backend, "active_local_run", lambda env_path, system: {"started": time.time()} if system == "water" else None)
    before = results.fingerprint(results.system_file(env, "water"))
    with pytest.raises(ValueError, match="active"): systems.add_source_xyz(env, "water", xyz(tmp_path, "w2.xyz", WATER), "w2")
    with pytest.raises(ValueError, match="active"): systems.set_charge_spin(env, "water", "water", charge=0, spin=0)
    assert results.fingerprint(results.system_file(env, "water")) == before

def test_backups_made_in_one_second_do_not_overwrite_each_other_and_are_bounded(tmp_path):
    f = tmp_path / "s.npy"; f.write_text("x")
    assert len({systems.backup(str(f)) for _ in range(5)}) == 5
    for _ in range(20): systems.backup(str(f))
    assert len(glob.glob(str(f) + ".bak-*")) == systems.KEEP_BACKUPS

def test_the_guard_uses_the_path_the_window_opened(local, tmp_path, monkeypatch):
    env, info = local
    seen = []
    monkeypatch.setattr(backend, "active_local_run", lambda env_path, system: seen.append(env_path))
    systems.confirm_defaults(env, "water", "water", env_path="/where/the/window/opened/it.npy")
    assert seen == ["/where/the/window/opened/it.npy"]

def test_run_checks_read_the_file_once_per_change(local, monkeypatch):
    env, info = local
    calls = []; real = systems.read_tree
    monkeypatch.setattr(systems, "read_tree", lambda f: calls.append(f) or real(f))
    f = results.system_file(env, "water")
    for _ in range(5): systems.run_checks(f)
    assert len(calls) == 1

# ---- point 2
def test_imported_source_shows_the_default_as_a_default(local):
    env, info = local
    s = systems.read_tree(results.system_file(env, "water")).sources[0]
    assert (s.charge, s.spin, s.electrons, s.origin, s.parity_ok) == (0, 0, 10, "default", True)
    assert "SCOPE default" in s.summary
    assert any("import default" in m for m in systems.run_checks(results.system_file(env, "water")))
    systems.confirm_defaults(env, "water", "water")
    assert systems.run_checks(results.system_file(env, "water")) == []

def test_an_odd_electron_count_needs_an_odd_spin(local, tmp_path):
    env, info = local
    systems.add_source_xyz(env, "water", xyz(tmp_path, "me.xyz", METHYL), "methyl")
    me = next(s for s in systems.read_tree(results.system_file(env, "water")).sources if s.name == "methyl")
    assert me.parity_ok is False and any("cannot have 2S=0" in m for m in systems.run_checks(results.system_file(env, "water")))
    with pytest.raises(ValueError, match="cannot have"): systems.set_charge_spin(env, "water", "methyl", charge=0, spin=0)
    info2 = systems.set_charge_spin(env, "water", "methyl", charge=0, spin=1)
    assert (info2.charge, info2.spin, info2.multiplicity, info2.origin, info2.parity_ok) == (0, 1, 2, "user", True)

def test_totals_go_on_the_metal_and_replace_earlier_atomic_values(local, tmp_path):
    env, info = local
    systems.add_source_xyz(env, "water", xyz(tmp_path, "fe.xyz", FE), "fe")
    systems.set_charge_spin(env, "water", "fe", charges=[1, 0, 0, 0, 0, 0, 1], spins=[0] * 7)       # an atomic assignment first
    systems.set_charge_spin(env, "water", "fe", charge=2, spin=4)                                  # then totals: no leftover on atom 7
    src = systems.find_source(reload(env, "water"), "fe")
    assert src.charge == 2 and src.spin == 4 and [a.charge for a in src.atoms] == [2, 0, 0, 0, 0, 0, 0] and src.atoms[0].spin == 4
    assert getattr(src, "gui_charge_spin") == "user" and src.spin_multiplicity == 5                 # what SCOPE writes into the inputs

def test_atomic_values_are_summed(local, tmp_path):
    env, info = local
    info2 = systems.set_charge_spin(env, "water", "water", charges=[-1, 1, 0], spins=[0, 0, 0])
    assert info2.charge == 0
    rows = systems.atom_rows(systems.find_source(reload(env, "water"), "water"))
    assert [(r.label, r.charge) for r in rows] == [("O", -1), ("H", 1), ("H", 0)] and rows[0].neighbours == [1, 2] and rows[1].neighbours == [0]
    with pytest.raises(ValueError, match="atoms"): systems.set_charge_spin(env, "water", "water", charges=[0], spins=[0])

def test_qe_needs_neutral_states(local):
    env, info = local
    systems.set_charge_spin(env, "water", "water", charge=-2, spin=0)
    checks = systems.run_checks(results.system_file(env, "water"), ["qe"])
    assert any("neutral" in m for m in checks) and not any("neutral" in m for m in systems.run_checks(results.system_file(env, "water"), ["g16"]))

def test_adjacency_matrix_is_symmetric(local):
    env, info = local
    adj = systems.adjacency(systems.find_source(reload(env, "water"), "water"))
    assert adj == [[0, 1, 1], [1, 0, 0], [1, 0, 0]]

# ---- Systems page
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen"); pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])

def test_systems_page_tree_and_source_panel(local, tmp_path):
    app = qapp(); from scope.gui.window import MainWindow
    env, info = local
    systems.add_source_xyz(env, "water", xyz(tmp_path, "me.xyz", METHYL), "methyl")
    win = MainWindow(); win.session.set_environment(env, info); tab = win.sys_tab
    top = tab.tree.topLevelItem(0); top.setExpanded(True); app.processEvents()
    kids = [top.child(i).text(0) for i in range(top.childCount())]
    assert top.text(0) == "water" and kids == ["water", "methyl"] and top.child(0).child(0).text(0) == "initial"
    tab.tree.setCurrentItem(top.child(1)); app.processEvents()
    p = tab.panel
    assert p.charge.isEnabled() and "import default" in p.origin.text() and "cannot have" in p.parity.text() and not p.save_btn.isEnabled()
    p.spin.setValue(1); assert p.save_btn.isEnabled(); p.save(); app.processEvents()
    assert "Set or confirmed by you" in tab.panel.origin.text() and tab.panel.info.spin == 1
    assert systems.find_source(reload(env, "water"), "methyl").spin == 1
