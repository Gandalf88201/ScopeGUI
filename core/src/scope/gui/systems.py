"""Systems, their Sources and their States, as SCOPE holds them, for the Systems page (no Qt).

The hierarchy is: a System (one file, Systems/<system>/<system>.npy) holds Sources (molecules or cells, each from its own .xyz or
.cif), and each Source holds States: 'initial' when it is imported, then the geometries and results calculations write. A Workflow
is one Source inside one Branch; a job reads one State of its source (istate) and writes one (fstate).

Charge and spin belong to the atoms in SCOPE: the total of a source is the sum of its atoms' values, and every state of the source
uses that total. An .xyz carries neither, so an imported source starts with every atom at charge 0 and spin 0. That default is shown
as a default until the user confirms or changes it (the source then carries gui_charge_spin = 'user').

Reading a system file loads a Python pickle: only files the user created or trusts are read (the same rule as the rest of the GUI).
Every change goes through edit(): it refuses while a run of the system is active here, keeps a copy of the file first, and saves.
"""
import os
import shutil
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field

from scope.gui import backend

METAL_BLOCKS = ("d", "f")
KEEP_BACKUPS = 10                                                           ## copies of a system file kept by edits and downloads

#############
### Tree  ###
#############
@dataclass
class StateInfo:
    """One State of a source: what it holds."""
    name:         str
    has_geometry: bool
    has_energy:   bool
    n_freqs:      int
    n_comps:      int

@dataclass
class SourceInfo:
    """One Source of a system.

    Attributes:
        kind (str):          'molecule', 'cell', … (SCOPE's object_subtype).
        charge, spin (int):  Totals (sums of the atoms' values); spin is 2S (alpha minus beta), as SCOPE stores it. None if unknown.
        electrons (int):     Electrons of the neutral atoms (charge not applied).
        origin (str):        'user' (set or confirmed in the GUI) or 'default' (what the import gave: every atom 0).
        branches (list):     Branches with a Workflow for this source.
    """
    name:      str
    kind:      str
    formula:   str
    natoms:    int
    charge:    "int | None"
    spin:      "int | None"
    electrons: "int | None"
    origin:    str
    states:    list = field(default_factory=list)
    branches:  list = field(default_factory=list)

    @property
    def multiplicity(self) -> "int | None":
        return None if self.spin is None else self.spin + 1

    @property
    def parity_ok(self) -> "bool | None":
        """Whether the number of electrons (after the charge) and the spin agree: an even count needs an even 2S, an odd one an odd 2S."""
        return spin_parity_ok(self.electrons, self.charge, self.spin)

    @property
    def summary(self) -> str:
        """'charge 0 · spin 2S=0 (singlet) · SCOPE default'."""
        if self.charge is None or self.spin is None: return "charge and spin not set"
        text = f"charge {self.charge:+d} · 2S={self.spin} ({multiplicity_word(self.spin + 1)})" if self.charge else f"charge 0 · 2S={self.spin} ({multiplicity_word(self.spin + 1)})"
        return text + (" · SCOPE default, not confirmed" if self.origin != "user" else "")

@dataclass
class SystemTree:
    name:     str
    file:     str
    sources:  list
    branches: list

def multiplicity_word(m: int) -> str:
    return {1: "singlet", 2: "doublet", 3: "triplet", 4: "quartet", 5: "quintet", 6: "sextet", 7: "septet"}.get(m, f"multiplicity {m}")

def spin_parity_ok(electrons: "int | None", charge: "int | None", spin: "int | None") -> "bool | None":
    if electrons is None or charge is None or spin is None: return None
    return (electrons - charge) % 2 == spin % 2 and spin >= 0

def lowest_spin(electrons: int, charge: int) -> int:
    """The lowest 2S that agrees with the electron count: 0 for an even count, 1 for an odd one."""
    return (electrons - charge) % 2

def atoms_of(source: object) -> list:
    if not hasattr(source, "atoms"):
        try: source.set_atoms()
        except Exception: return []
    return list(getattr(source, "atoms", []) or [])

def electrons_of(source: object) -> "int | None":
    atoms = atoms_of(source)
    try: return int(sum(int(a.atnum) for a in atoms)) if atoms else int(getattr(source, "eleccount"))
    except Exception: return None

def totals(source: object) -> tuple:
    """(charge, spin) as SCOPE computes them (sums over the atoms), or None where an atom has no value."""
    atoms = atoms_of(source)
    charge = int(sum(a.charge for a in atoms)) if atoms and all(hasattr(a, "charge") for a in atoms) else None
    spin   = int(sum(a.spin for a in atoms)) if atoms and all(hasattr(a, "spin") for a in atoms) else None
    return charge, spin

def source_info(source: object, branches: list=()) -> SourceInfo:
    charge, spin = totals(source)
    states = [StateInfo(str(st.name), getattr(st, "coord", None) is not None and len(getattr(st, "coord", []) or []) > 0,
                        bool(getattr(st, "results", {}) or {}) and (getattr(st, "results", {}) or {}).get("energy") is not None,
                        len(getattr(st, "freqs_cm", None) or []), len(getattr(st, "computations", None) or []))
              for st in getattr(source, "states", []) or []]
    return SourceInfo(str(source.name), str(getattr(source, "object_subtype", "")), str(getattr(source, "formula", "")), len(getattr(source, "labels", []) or []),
                      charge, spin, electrons_of(source), getattr(source, "gui_charge_spin", "default"), states, list(branches))

def tree_from(system: object) -> SystemTree:
    used = {}
    for br in getattr(system, "branches", []) or []:
        for wf in getattr(br, "workflows", []) or []:
            name = getattr(getattr(wf, "source", None), "name", wf.name)
            used.setdefault(str(name).lower(), []).append(br.name)
    sources = [source_info(s, sorted(set(used.get(str(s.name).lower(), [])))) for s in getattr(system, "sources", []) or []]
    return SystemTree(str(system.name), str(getattr(system, "system_file", "")), sources, [br.name for br in getattr(system, "branches", []) or []])

def read_tree(system_file: str) -> SystemTree:
    from scope.gui.results import load_quietly
    system, _ = load_quietly(system_file)
    if getattr(system, "object_type", None) != "system": raise ValueError(f"Not a System binary file: {system_file}")
    return tree_from(system)

_names_cache = {}
def source_names(system_file: str) -> list:
    """Source names of a system file (cached while the file does not change); [] if it cannot be read."""
    from scope.gui.results import fingerprint
    key = (os.path.abspath(system_file), fingerprint(system_file))
    if key not in _names_cache:
        try: _names_cache[key] = [s.name for s in read_tree(system_file).sources]
        except Exception: _names_cache[key] = []
    return _names_cache[key]

@dataclass
class AtomRow:
    index:      int
    label:      str
    charge:     "int | None"
    spin:       "int | None"
    neighbours: list

def adjacency(source: object) -> list:
    """SCOPE's connectivity matrix of a source as a list of 0/1 rows ([] if SCOPE cannot give one)."""
    adj = getattr(source, "adjmat", None)
    if adj is None:
        try: source.get_adjmatrix()
        except Exception: return []
        adj = getattr(source, "adjmat", None)
    try: return [[1 if v else 0 for v in row] for row in adj]
    except TypeError: return []

def atom_rows(source: object) -> list:
    atoms, adj = atoms_of(source), adjacency(source)
    labels = list(getattr(source, "labels", []) or [])
    rows = []
    for i, label in enumerate(labels):
        a = atoms[i] if i < len(atoms) else None
        nb = [j for j, v in enumerate(adj[i]) if v and j != i] if i < len(adj) else []
        rows.append(AtomRow(i, label, getattr(a, "charge", None), getattr(a, "spin", None), nb))
    return rows

def find_source(system: object, name: str) -> object:
    for s in getattr(system, "sources", []) or []:
        if str(s.name).lower() == name.lower(): return s
    raise KeyError(f"No source '{name}' in system '{getattr(system, 'name', '?')}'")

#############
### Edits ###
#############
def stamp() -> str:
    """A time stamp that two calls in the same second never share (backups, logs and run records use it)."""
    return backend.unique_stamp()

def backup(path: str) -> str:
    """Copies a file to <path>.bak-<time>_<id> and returns the copy's path ('' if there was nothing to copy)."""
    if not os.path.isfile(path): return ""
    target = f"{path}.bak-{stamp()}"; shutil.copy2(path, target)
    import glob
    for old in sorted(glob.glob(glob.escape(path) + ".bak-*"))[:-KEEP_BACKUPS]:          ## oldest first: keep the newest KEEP_BACKUPS
        try: os.remove(old)
        except OSError: pass
    return target

def edit_blocked(env_path: str, system: str) -> str:
    """Why the system file cannot be changed now ('' if it can): a run of it is active from this environment on this computer."""
    run = backend.active_local_run(env_path, system) if env_path else None
    if run: return f"A run of '{system}' is active on this computer (started {time.strftime('%H:%M', time.localtime(run['started']))}). It saves the system file when it ends and would overwrite this change: wait for it to end."
    return ""

CLUSTER_NOTE = ("Only this computer's copy changes. If this system also runs on a cluster, upload it before the next cluster run, and do not "
                "download the cluster's system file over it afterwards: that would bring back the old values.")

@contextmanager
def edit(env: object, system: str, env_path: str=""):
    """Loads a system for a change and saves it when the block ends without error. Refuses while a run of it is active here; keeps a copy
    of the file first. Yields the System (paths pointed at this computer's folders, nothing created). env_path is the environment file as
    the window opened it (runs are recorded with that path; the path stored inside the environment can be out of date)."""
    from scope.gui import results
    env_path = env_path or getattr(env, "filepath", "")
    why = edit_blocked(env_path, system)
    if why: raise ValueError(why)
    obj, _ = results.open_system(env, system)
    yield obj
    path = results.system_file(env, system)
    backup(path)
    obj.save(path)

def check_source_name(name: str) -> str:
    name = name.strip().lower().replace(" ", "_")
    if not backend.SAFE_NAME.match(name): raise ValueError(f"'{name}' is not a safe source name. Use letters, digits, '_', '-' or '.', with no spaces (SCOPE builds file names from it).")
    return name

def add_source_xyz(env: object, system: str, xyz_path: str, name: str, env_path: str="") -> str:
    """Adds an .xyz file as a new Source of an existing System (not a new System). The file is copied to <Sources>/<system>/<name>.xyz.
    The name is given explicitly (an .xyz called 'fe.hs.xyz' would otherwise be cut at the first dot). Returns the source name."""
    from scope.classes_specie import Molecule
    from scope.read_write import read_xyz
    if not xyz_path.lower().endswith(".xyz"): raise ValueError("Only .xyz files can be added")
    name = check_source_name(name)
    target_dir = os.path.join(env.sources_path, system); target = os.path.join(target_dir, f"{name}.xyz")
    with edit(env, system, env_path) as obj:
        if any(str(s.name).lower() == name for s in obj.sources): raise ValueError(f"System '{system}' already has a source named '{name}'")
        labels, coord = read_xyz(xyz_path)
        if not labels: raise ValueError(f"No atoms could be read from {os.path.basename(xyz_path)}")
        os.makedirs(target_dir, exist_ok=True)
        if os.path.abspath(xyz_path) != os.path.abspath(target):
            if os.path.exists(target): raise ValueError(f"{target} already exists; choose another source name")
            shutil.copyfile(xyz_path, target)
        obj.add_source(name, Molecule(labels, coord))
    return name

def create_system(env: object, name: str, files: list) -> str:
    """Creates ONE new System whose Sources are several .xyz files (for instance the high- and low-spin geometries of one compound).
    files is a list of (path, source name). Returns the path of the saved system file. Refuses an existing system."""
    from scope.classes_system import System
    from scope.classes_specie import Molecule
    from scope.read_write import read_xyz
    name = name.strip()
    if not backend.SAFE_NAME.match(name): raise ValueError(f"'{name}' is not a safe system name. Use letters, digits, '_', '-' or '.', with no spaces.")
    if not files: raise ValueError("Choose at least one .xyz file")
    names = [check_source_name(n) for _, n in files]
    if len(set(names)) != len(names): raise ValueError("Two files would get the same source name: " + ", ".join(sorted({n for n in names if names.count(n) > 1})))
    if os.path.exists(os.path.join(env.systems_path, name, f"{name}.npy")): raise ValueError(f"System '{name}' already exists: add the files as its sources instead")
    parsed = []
    for (path, _), src in zip(files, names):
        if not path.lower().endswith(".xyz"): raise ValueError(f"{os.path.basename(path)}: only .xyz files can be imported")
        labels, coord = read_xyz(path)
        if not labels: raise ValueError(f"No atoms could be read from {os.path.basename(path)}")
        parsed.append((path, src, labels, coord))
    system = System(name); system.set_paths_from_environment(env, create_folders=True)
    folder = os.path.join(env.sources_path, name); os.makedirs(folder, exist_ok=True)
    for path, src, labels, coord in parsed:
        target = os.path.join(folder, f"{src}.xyz")
        if os.path.abspath(path) != os.path.abspath(target): shutil.copyfile(path, target)
        system.add_source(src, Molecule(labels, coord))
    system.create_folders(); system.save()
    return system.system_file

def default_name(xyz_path: str) -> str:
    """A proposed source name from a file name: 'Fe HS.xyz' -> 'fe_hs'; dots inside the name are kept ('fe.hs.xyz' -> 'fe.hs')."""
    return os.path.splitext(os.path.basename(xyz_path))[0].strip().lower().replace(" ", "_")

def metal_index(source: object) -> int:
    """Index of the first d- or f-block atom (where a total spin or charge is stored), or 0."""
    for i, a in enumerate(atoms_of(source)):
        if getattr(a, "block", "") in METAL_BLOCKS: return i
    return 0

def apply_totals(source: object, charge: int, spin: int) -> int:
    """Sets the totals the safe way: every atom back to 0, then the whole charge and spin on one atom (the first metal, else atom 0).
    SCOPE's own set_total_charge only overwrites atom 0, so atomic values already present would be added to it. Returns that atom's index."""
    atoms = atoms_of(source); where = metal_index(source)
    for a in atoms: a.set_charge(0); a.set_spin(0)
    atoms[where].set_charge(int(charge)); atoms[where].set_spin(int(spin))
    return where

def apply_atomic(source: object, charges: list, spins: list) -> None:
    atoms = atoms_of(source)
    if len(charges) != len(atoms) or len(spins) != len(atoms): raise ValueError(f"{len(atoms)} atoms, but {len(charges)} charges and {len(spins)} spins were given")
    for a, q, s in zip(atoms, charges, spins): a.set_charge(int(q)); a.set_spin(int(s))

def set_charge_spin(env: object, system: str, source: str, charge: "int | None"=None, spin: "int | None"=None, charges: "list | None"=None, spins: "list | None"=None, allow_parity: bool=False, env_path: str="") -> SourceInfo:
    """Sets the charge and spin of a source and saves the system. Either totals (charge, spin: 2S) or per-atom lists (charges, spins).
    Refuses a spin that does not agree with the electron count unless allow_parity. Marks the values as set by the user."""
    with edit(env, system, env_path) as obj:
        src = find_source(obj, source); electrons = electrons_of(src)
        new_q = sum(charges) if charges is not None else charge
        new_s = sum(spins) if spins is not None else spin
        if new_q is None or new_s is None: raise ValueError("Give both a charge and a spin")
        if new_s < 0: raise ValueError("The spin (2S, alpha minus beta electrons) cannot be negative")
        if not allow_parity and spin_parity_ok(electrons, new_q, new_s) is False:
            raise ValueError(f"{electrons - new_q} electrons cannot have 2S = {new_s}: an {'even' if (electrons - new_q) % 2 == 0 else 'odd'} count needs an {'even' if (electrons - new_q) % 2 == 0 else 'odd'} 2S.")
        if charges is not None: apply_atomic(src, list(charges), list(spins))
        else: apply_totals(src, new_q, new_s)
        src.gui_charge_spin = "user"
        info = source_info(src)
    return info

def confirm_defaults(env: object, system: str, source: str, env_path: str="") -> SourceInfo:
    """Marks the current charge and spin of a source as checked by the user, without changing them."""
    with edit(env, system, env_path) as obj:
        src = find_source(obj, source); src.gui_charge_spin = "user"; info = source_info(src)
    return info

_tree_cache = {}
def cached_tree(system_file: str) -> "SystemTree | None":
    """read_tree, read again only when the file changes (the Run and Cluster pages ask often)."""
    from scope.gui.results import fingerprint
    key = (os.path.abspath(system_file), fingerprint(system_file))
    if key not in _tree_cache:
        try: _tree_cache[key] = read_tree(system_file)
        except Exception: _tree_cache[key] = None
    return _tree_cache[key]

def run_checks(system_file: str, software: list=()) -> list:
    """Warnings to show before a run: sources whose charge and spin are still the import default, or whose spin disagrees with the
    electron count; with Quantum ESPRESSO, sources with a non-zero charge (SCOPE's QE input requires a neutral state)."""
    tree = cached_tree(system_file)
    if tree is None: return []
    out = []
    for s in tree.sources:
        if s.origin != "user": out.append(f"Source '{s.name}': charge {s.charge} and 2S={s.spin} are SCOPE's import default (an .xyz has neither). Check them on the Systems page.")
        if s.parity_ok is False: out.append(f"Source '{s.name}': {s.electrons - s.charge} electrons cannot have 2S={s.spin}. Fix the charge or the spin on the Systems page.")
        if "qe" in software and s.charge: out.append(f"Source '{s.name}': charge {s.charge:+d}, but SCOPE writes Quantum ESPRESSO inputs only for neutral states.")
    return out
