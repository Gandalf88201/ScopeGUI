"""The chemical structures of a system, as SCOPE holds them, for the Systems page (no Qt).

A system has sources (molecules, or the molecules of a cell), and each source has states: 'initial' when it is imported, then the
geometries that calculations produce. Each (source, state) is one Structure: its atoms and coordinates, and the bonds SCOPE itself
perceived (the source's connectivity matrix), so the picture is the structure SCOPE will compute. When no system file can be read,
the .xyz file of the system is shown instead, with bonds guessed from distances.

Reading a system file loads a Python pickle: only files the user created or trusts are read (the same rule as the rest of the GUI).
"""
import os
from collections import Counter
from dataclasses import dataclass, field

## Covalent radii (Å, Cordero et al. 2008) and CPK-like colours; anything not listed gets a default.
RADII  = {"H": 0.31, "B": 0.84, "C": 0.76, "N": 0.71, "O": 0.66, "F": 0.57, "Si": 1.11, "P": 1.07, "S": 1.05, "Cl": 1.02, "Br": 1.20, "I": 1.39, "Li": 1.28, "Na": 1.66, "K": 2.03, "Mg": 1.41, "Ca": 1.76,
          "Ti": 1.60, "V": 1.53, "Cr": 1.39, "Mn": 1.39, "Fe": 1.32, "Co": 1.26, "Ni": 1.24, "Cu": 1.32, "Zn": 1.22, "Ru": 1.46, "Rh": 1.42, "Pd": 1.39, "Ag": 1.45, "Ir": 1.41, "Pt": 1.36, "Au": 1.36}
COLORS = {"H": "#FFFFFF", "C": "#909090", "N": "#3050F8", "O": "#FF0D0D", "F": "#90E050", "Cl": "#1FF01F", "Br": "#A62929", "I": "#940094", "S": "#FFFF30", "P": "#FF8000", "B": "#FFB5B5", "Si": "#F0C8A0",
          "Li": "#CC80FF", "Na": "#AB5CF2", "K": "#8F40D4", "Mg": "#8AFF00", "Ca": "#3DFF00", "Ti": "#BFC2C7", "V": "#A6A6AB", "Cr": "#8A99C7", "Mn": "#9C7AC7", "Fe": "#E06633", "Co": "#F090A0", "Ni": "#50D050",
          "Cu": "#C88033", "Zn": "#7D80B0", "Ru": "#248F8F", "Rh": "#0A7D8C", "Pd": "#006985", "Ag": "#C0C0C0", "Ir": "#175487", "Pt": "#D0D0E0", "Au": "#FFD123"}
DEFAULT_RADIUS, DEFAULT_COLOR = 1.50, "#FF1493"

@dataclass
class Structure:
    """One geometry to show.

    Attributes:
        title (str):    What the selector shows, for instance 'water · initial'.
        labels (list):  Element symbols.
        coords (list):  [x, y, z] in Å, one per atom.
        bonds (list):   (i, j) pairs, i < j.
        charge (int):   Total charge, if known.
        spin (int):     Spin as SCOPE stores it, if known.
        origin (str):   'system' (from the system file, bonds by SCOPE) or 'xyz' (bonds guessed from distances).
    """
    title:  str
    labels: list
    coords: list
    bonds:  list = field(default_factory=list)
    charge: "int | None" = None
    spin:   "int | None" = None
    origin: str = "system"

    @property
    def formula(self) -> str:
        """Hill formula: C first, then H, then the others alphabetically (for instance C7H14O2)."""
        n = Counter(self.labels); keys = (["C", "H"] if "C" in n else []) + sorted(k for k in n if k not in (("C", "H") if "C" in n else ()))
        return "".join(f"{k}{n[k] if n[k] > 1 else ''}" for k in keys if k in n)

def radius(symbol: str) -> float:
    return RADII.get(symbol, DEFAULT_RADIUS)

def color(symbol: str) -> str:
    return COLORS.get(symbol, DEFAULT_COLOR)

def perceive_bonds(labels: list, coords: list, tolerance: float=0.45) -> list:
    """Bonds from distances: two atoms are bonded when closer than the sum of their covalent radii plus `tolerance` (Å)."""
    out = []
    for i in range(len(labels)):
        for j in range(i + 1, len(labels)):
            d2 = sum((a - b) ** 2 for a, b in zip(coords[i], coords[j]))
            limit = radius(labels[i]) + radius(labels[j]) + tolerance
            if 0.16 < d2 < limit * limit: out.append((i, j))
    return out

def bonds_from_matrix(adjmat, natoms: int) -> list:
    """Bonds from SCOPE's connectivity matrix (only if it matches the number of atoms)."""
    try:
        if len(adjmat) != natoms: return []
        return [(i, j) for i in range(natoms) for j in range(i + 1, natoms) if adjmat[i][j]]
    except TypeError: return []

def read_xyz(path: str, title: str="") -> "Structure | None":
    """A Structure from an .xyz file (bonds guessed from distances), or None if the file cannot be read."""
    try:
        with open(path) as fh: lines = fh.read().splitlines()
        n = int(lines[0].split()[0]); labels, coords = [], []
        for line in lines[2:2 + n]:
            parts = line.split(); labels.append(parts[0].capitalize() if len(parts[0]) <= 2 else parts[0]); coords.append([float(x) for x in parts[1:4]])
    except (OSError, ValueError, IndexError): return None
    if len(labels) != n: return None
    return Structure(title or os.path.splitext(os.path.basename(path))[0], labels, coords, perceive_bonds(labels, coords), origin="xyz")

def structures_of(system_file: str) -> list:
    """Every (source, state) geometry of a system, in order: each source's states (initial first), as SCOPE holds them.

    A state with its own coordinates and the same atoms keeps the source's bonds (SCOPE's connectivity); otherwise bonds are guessed.
    Returns [] if the file is not a SCOPE system.
    """
    from scope.read_write import load_binary
    system = load_binary(system_file)
    if getattr(system, "object_type", None) != "system": return []
    out = []
    for source in getattr(system, "sources", []):
        labels, coords = list(getattr(source, "labels", [])), [list(map(float, c)) for c in getattr(source, "coord", [])]
        if not labels or len(labels) != len(coords): continue
        bonds = bonds_from_matrix(getattr(source, "adjmat", None), len(labels)) or perceive_bonds(labels, coords)
        name = getattr(source, "name", "") or getattr(source, "formula", "source")
        charge, spin = getattr(source, "charge", None), getattr(source, "spin", None)
        states = [s for s in getattr(source, "states", []) if getattr(s, "coord", None) is not None and len(getattr(s, "coord", [])) == len(labels)]
        if not states: out.append(Structure(f"{name}", labels, coords, bonds, charge, spin)); continue
        for st in states:
            st_labels = list(getattr(st, "labels", labels)) or labels
            st_coords = [list(map(float, c)) for c in st.coord]
            st_bonds = bonds if st_labels == labels else perceive_bonds(st_labels, st_coords)
            out.append(Structure(f"{name} · {getattr(st, 'name', 'state')}", st_labels, st_coords, st_bonds, charge, spin))
    return out

def structures_for(row, sources_path: str="") -> list:
    """The structures to show for a row of the Systems page: from its system file, or, failing that, from <Sources>/<system>/<system>.xyz."""
    if getattr(row, "file", ""):
        try:
            found = structures_of(row.file)
            if found: return found
        except Exception: pass                                                   ## a file SCOPE cannot read: fall back to the .xyz
    xyz = os.path.join(sources_path, row.name, f"{row.name}.xyz") if sources_path else ""
    found = read_xyz(xyz, row.name) if xyz and os.path.isfile(xyz) else None
    return [found] if found else []

def drawing_svg(s: Structure, width: int=360, height: int=260, dark: bool=False) -> tuple:
    """A 2D drawing of the structure (RDKit), hydrogens on carbon hidden. Returns (svg, note): svg is '' if it cannot be drawn.

    The drawing uses exactly SCOPE's atoms and bonds: no hydrogen is ever added. Bond orders (double bonds, aromatic rings) are shown
    when RDKit can assign them from the geometry and the charge; otherwise every bond is drawn single and the note says so.
    """
    try:
        from rdkit import Chem
        from rdkit.Chem import rdDepictor
        from rdkit.Chem.Draw import rdMolDraw2D
        mol, note = rdkit_mol(s)
        if mol is None: return "", ""
        try: shown = Chem.RemoveHs(mol, sanitize=False)
        except Exception: shown = mol
        rdDepictor.Compute2DCoords(shown)
        drawer = rdMolDraw2D.MolDraw2DSVG(width, height); opts = drawer.drawOptions(); opts.clearBackground = False; opts.padding = 0.08
        if dark:
            try: rdMolDraw2D.SetDarkMode(opts)
            except Exception: pass
            opts.clearBackground = False
        drawer.DrawMolecule(shown); drawer.FinishDrawing()
        return drawer.GetDrawingText(), note
    except Exception:
        return "", ""

def rdkit_mol(s: Structure) -> tuple:
    """An RDKit molecule with exactly SCOPE's atoms and bonds (no hydrogen added), bond orders assigned when possible. Returns (mol or None, note)."""
    try:
        from rdkit import Chem, RDLogger
        from rdkit.Chem import rdDetermineBonds
        from rdkit.Geometry import Point3D
        RDLogger.DisableLog("rdApp.*")
        mol = Chem.RWMol()
        for symbol in s.labels:
            atom = Chem.Atom(symbol); atom.SetNoImplicit(True); mol.AddAtom(atom)           ## never invent hydrogens
        for i, j in s.bonds: mol.AddBond(int(i), int(j), Chem.BondType.SINGLE)
        conf = Chem.Conformer(len(s.labels))
        for k, (x, y, z) in enumerate(s.coords): conf.SetAtomPosition(k, Point3D(x, y, z))
        mol.AddConformer(conf, assignId=True); mol = mol.GetMol(); note = ""
        try:
            trial = Chem.Mol(mol); rdDetermineBonds.DetermineBondOrders(trial, charge=int(s.charge or 0)); mol = trial
        except Exception:
            mol.UpdatePropertyCache(strict=False)
            note = "Bond orders could not be assigned from the geometry and the charge (a missing hydrogen, a radical, or a metal), so every bond is drawn single."
        return mol, note
    except Exception:
        return None, ""
