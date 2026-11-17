"""The structure panel of the Systems page: what SCOPE holds (atoms, bonds, states), the 2D drawing, and the 3D view."""
import os
import shutil
import pytest

from scope.gui import backend, structure
from test_remote import isolated, local, WATER                              # noqa: F401  (fixtures)

ESTER = os.path.join(os.path.dirname(__file__), "data", "isoamyl_acetate.xyz")     # 3-methylbutyl ethanoate, C7H14O2

@pytest.fixture
def ester_system(local, tmp_path):
    env, info = local
    xyz = tmp_path / "ester.xyz"; shutil.copy(ESTER, xyz)
    return env, info, backend.import_xyz(env, str(xyz))

def test_formula_and_bonds_from_distances():
    s = structure.read_xyz(ESTER)
    assert s.formula == "C7H14O2" and len(s.labels) == 23 and s.origin == "xyz"
    assert len(s.bonds) == 22                                                                   # an acyclic molecule: atoms - 1
    water = structure.Structure("w", ["O", "H", "H"], [[0, 0, 0], [0.96, 0, 0], [-0.24, 0.93, 0]])
    assert structure.perceive_bonds(water.labels, water.coords) == [(0, 1), (0, 2)] and water.formula == "H2O"
    assert structure.Structure("x", ["Fe", "Cl", "Cl"], [[0] * 3] * 3).formula == "Cl2Fe"                         # no carbon: alphabetical
    assert structure.read_xyz("/nowhere.xyz") is None

def test_bad_xyz_files_are_refused(tmp_path):
    for text in ("", "abc\n", "3\nshort\nO 0 0 0\n", "2\n\nO 0 0 x\nH 1 0 0\n"):
        f = tmp_path / "bad.xyz"; f.write_text(text); assert structure.read_xyz(str(f)) is None, text

def test_the_structure_is_the_one_scope_holds(ester_system):
    env, info, npy = ester_system
    found = structure.structures_of(npy)
    assert [s.title for s in found] == ["ester · initial"] and found[0].origin == "system" and found[0].charge == 0
    s = found[0]; ref = structure.read_xyz(ESTER)
    assert s.labels == ref.labels and all(abs(a - b) < 1e-6 for p, q in zip(s.coords, ref.coords) for a, b in zip(p, q))
    assert sorted(s.bonds) == sorted(ref.bonds)                                                 # SCOPE's connectivity, here identical to the distance one

def test_without_a_readable_system_file_the_xyz_is_shown(ester_system):
    env, info, npy = ester_system
    row = [r for r in backend.list_systems(info) if r.name == "ester"][0]
    os.remove(npy); row.file = ""
    found = structure.structures_for(row, info.sources_path)
    assert len(found) == 1 and found[0].origin == "xyz" and found[0].formula == "C7H14O2"

def test_the_drawing_never_invents_hydrogens_and_says_when_bond_orders_are_unknown():
    good = structure.read_xyz(ESTER)
    mol, note = structure.rdkit_mol(good)
    assert note == "" and sum(1 for b in mol.GetBonds() if b.GetBondTypeAsDouble() == 2.0) == 1                  # the ester C=O
    svg, note = structure.drawing_svg(good); assert svg.startswith("<?xml") and "<svg" in svg and note == ""
    broken = structure.Structure("radical", good.labels[:-1], good.coords[:-1], [b for b in good.bonds if 22 not in b])   # one hydrogen missing
    mol, note = structure.rdkit_mol(broken)
    assert "could not be assigned" in note
    assert all(a.GetNumImplicitHs() == 0 for a in mol.GetAtoms()) and mol.GetNumAtoms() == 22                     # drawn as SCOPE has it, nothing added
    svg, note = structure.drawing_svg(broken, dark=True); assert "<svg" in svg and note

def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])

def test_systems_page_shows_the_first_system_at_once_and_follows_the_selection(ester_system):
    app = qapp(); from scope.gui.window import MainWindow
    env, info, npy = ester_system
    win = MainWindow(); win.session.set_environment(env, info); win.show_step("systems"); panel = win.sys_tab.structure
    names = [r.name for r in win.sys_tab.rows]
    assert names == sorted(names) and panel.current() is not None                                # something is shown without clicking
    win.sys_tab.table.selectRow(names.index("ester")); app.processEvents()
    assert panel.formula.text() == "C7H14O2" and panel.atoms.text().startswith("23") and "SCOPE perceived" in panel.origin.text()
    assert panel.chooser.count() == 1 and panel.drawing.isVisibleTo(panel) and "Bond orders" not in panel.no_drawing.text()
    panel.details_btn.click(); assert panel.details.isVisibleTo(panel) and "ester" in panel.details.toPlainText().lower()

def test_the_3d_view_rotates_zooms_resets_and_draws(ester_system):
    app = qapp(); from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QMouseEvent, QWheelEvent
    from PySide6.QtWidgets import QApplication
    from scope.gui.structure_view import MoleculeView
    view = MoleculeView(); view.resize(400, 300); view.set_structure(structure.read_xyz(ESTER)); view.show(); app.processEvents()
    before = [row[:] for row in view.rot]
    for kind, pos in ((QMouseEvent.MouseButtonPress, (100, 100)), (QMouseEvent.MouseMove, (160, 130)), (QMouseEvent.MouseButtonRelease, (160, 130))):
        QApplication.sendEvent(view, QMouseEvent(kind, QPointF(*pos), QPointF(*pos), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
    assert view.rot != before
    QApplication.sendEvent(view, QWheelEvent(QPointF(200, 150), QPointF(200, 150), QPoint(0, 0), QPoint(0, 240), Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False))
    assert view.zoom > 1.0
    view.show_h = False; assert all(view.s.labels[i] != "H" for i in view.visible())
    image = view.grab().toImage(); assert len({image.pixel(x, 150) for x in range(0, 400, 7)}) > 3                  # atoms were painted
    view.mouseDoubleClickEvent(None); assert view.zoom == 1.0
    view.set_structure(None); view.grab()                                                                            # an empty view paints its hint, no error
