"""Reported: the IR spectrum (notebook and State tab) failed with "'State' object has no attribute 'molecules'" for the state a frequency job
wrote (fstate = 'freq': 132 modes, no atoms). The spectrum asked SCOPE for Z, the formula units, which SCOPE computes from the state's atoms.
A molecule is one formula unit; a cell takes Z from a state of the same source that has atoms."""
from types import SimpleNamespace
import pytest

from scope.gui import results

class NoAtoms:
    """A state as a frequency job leaves it: modes, no coordinates. Its Z fails like SCOPE's (get_z needs the molecules)."""
    def __init__(self, name="freq", modes=((100.0, 2.0), (1600.0, 10.0))):
        self.name, self.labels, self.coord = name, [], []
        self.VNMs = [SimpleNamespace(index=i + 1, freq_cm=f, IR_int=a, red_mass=1.0, sym="A") for i, (f, a) in enumerate(modes)]
        self.calls = []
    @property
    def Z(self): raise AttributeError("'State' object has no attribute 'molecules'")
    def get_ir_spectrum(self, vmin=None, vmax=None, function="gaussian", sigma=10, per_formula_unit=True):
        self.calls.append(per_formula_unit); _ = self.Z if per_formula_unit else None         # SCOPE asks for Z only when dividing
        return [100.0, 1600.0], [2.0, 10.0]
    def get_vdos_spectrum(self, vmin=None, vmax=None, function="gaussian", sigma=10, per_formula_unit=True):
        self.calls.append(per_formula_unit); _ = self.Z if per_formula_unit else None
        return [100.0, 1600.0], [1.0, 1.0]

def system(kind, states):
    src = SimpleNamespace(name="s", object_type=kind, states=states)
    return SimpleNamespace(sources=[src]), src

def test_formula_units():
    _, mol = system("specie", [NoAtoms()])
    assert results.formula_units(mol, mol.states[0]) == 1.0                                # a molecule is one unit, without asking SCOPE
    opt = SimpleNamespace(name="opt", labels=["Fe"] * 8, Z=4)
    _, cell = system("cell", [opt, NoAtoms()])
    assert results.formula_units(cell, cell.states[1]) == 4.0                              # a cell: Z of a state of the same source with atoms
    _, bare = system("cell", [NoAtoms()])
    assert results.formula_units(bare, bare.states[0]) is None                             # nobody can tell

def test_spectrum_of_a_state_without_atoms():
    obj, src = system("specie", [NoAtoms()])
    sp = results.spectrum(obj, "s", "freq", kind="ir")                                      # failed before
    assert sp.y == [2.0, 10.0] and sp.sticks == [(100.0, 2.0), (1600.0, 10.0)] and sp.ylabel == "IR intensity (km/mol)"
    assert src.states[0].calls == [False]                                                   # SCOPE draws the whole state; nothing asks it for Z
    opt = SimpleNamespace(name="opt", labels=["Fe"] * 8, Z=2)
    obj, src = system("cell", [opt, NoAtoms()])
    sp = results.spectrum(obj, "s", "freq", kind="ir")
    assert sp.y == [1.0, 5.0] and sp.sticks[1] == (1600.0, 5.0) and "per formula unit" in sp.ylabel        # divided by Z = 2, as SCOPE would
    vd = results.spectrum(obj, "s", "freq", kind="vdos"); assert vd.y == [0.5, 0.5]
    obj, src = system("cell", [NoAtoms()])
    sp = results.spectrum(obj, "s", "freq", kind="ir"); assert sp.y == [2.0, 10.0] and "Z unknown" in sp.ylabel

def test_status_says_how_to_read_an_output():
    assert "Read on the cluster" in results.CompRow.status_text.fget(SimpleNamespace(group="unregistered"))

def test_thermo_refuses_a_cell_without_z_with_a_reason(monkeypatch):
    obj, src = system("cell", [NoAtoms()]); src.states[0].results = {}
    monkeypatch.setattr(results, "thermo_ready", lambda *a: "")
    with pytest.raises(ValueError, match="formula units"): results.thermo(obj, "s", "freq", [298.15])
