"""Results of a system, as SCOPE registered them, for the Results page and for notebooks (no Qt).

Everything here is read-only: a system file is loaded, its paths are pointed at the folders of this computer in memory, and tables are
built from it. Nothing is saved and no folder is created, so looking at results can never change a project.

The same entry point serves the window and a notebook, so both always show the same data:

    from scope.gui.results import open_system
    system, prov = open_system("/path/to/scope_env_loc.npy", "water")

Reading a system file loads a Python pickle: only open files you created or trust (the same rule as the rest of the GUI).
"""
import csv
import glob
import io
import os
import threading
import time
from dataclasses import dataclass, field

HARTREE = {"au": 1.0, "a.u.": 1.0, "hartree": 1.0, "ha": 1.0, "eh": 1.0}
UNITS   = {"Eh": 1.0, "kcal/mol": 627.509474, "kJ/mol": 2625.4996, "eV": 27.211386}     ## factors from Hartree, for display only
ADDONS  = {"scope_sco": "scope-sco", "scope_azo": "scope-azo"}                                ## module in a pickle -> package to install

## Status written by the output parsers (g16_output / qe_output get_last_block_status), grouped for colours. Anything else is 'unknown'.
STATUS_GROUP = {"worked": "ok", "no_coord": "ok", "time_stopped": "warn", "no_scf_convergence": "err", "aborted": "err"}
STATUS_TEXT  = {"worked": "worked", "no_coord": "finished (no new geometry: normal for single points)", "time_stopped": "stopped by the time limit",
                "no_scf_convergence": "SCF did not converge", "aborted": "aborted"}

class ResultsError(Exception):
    """A system that cannot be shown. `kind` is 'no_environment', 'no_system', 'addon' or 'unreadable'; `hint` says what to do."""
    def __init__(self, kind: str, message: str, hint: str=""):
        super().__init__(message); self.kind, self.hint = kind, hint

@dataclass
class Provenance:
    """Where the numbers on screen come from.

    Attributes:
        system (str):          Name of the system.
        file (str):            The system file read.
        size, mtime (int):     Its size (bytes) and modification time (seconds) when it was read.
        saved_version (str):   SCOPE version stored in the file.
        local_version (str):   SCOPE version of this computer.
        env_file (str):        Environment whose folders were used to find the files.
        stored_root (str):     Computations folder written in the file (where SCOPE ran), before it was pointed here.
        local_root (str):      Computations folder of this system on this computer.
        backups (list):        Older copies kept by downloads (<system>.npy.bak-<time>), newest first.
    """
    system:        str
    file:          str
    size:          int
    mtime:         float
    saved_version: str
    local_version: str
    env_file:      str
    stored_root:   str
    local_root:    str
    backups:       list = field(default_factory=list)
    current_file:  str  = ""                                                   ## the system's own file, when `file` is an older copy of it

    @property
    def is_copy(self) -> bool:
        """True when what was read is an older copy (<system>.npy.bak-<time>), not the system file itself."""
        return bool(self.current_file) and os.path.normpath(self.current_file) != os.path.normpath(self.file)

    @property
    def label(self) -> str:
        """'water', or 'water (copy of 19 Nov 10:12)' for an older copy."""
        return f"{self.system} (copy of {time.strftime('%d %b %H:%M', time.localtime(self.mtime))})" if self.is_copy else self.system

    @property
    def moved(self) -> bool:
        """True when the file was written on another computer or in another folder (its paths were pointed here)."""
        return os.path.normpath(self.stored_root or "") != os.path.normpath(self.local_root)

    @property
    def version_differs(self) -> bool:
        return bool(self.saved_version) and bool(self.local_version) and self.saved_version != self.local_version

@dataclass
class CompRow:
    """One calculation (one run of one job).

    Attributes:
        branch, workflow, job (str):  Where it sits in the workflow.
        step (int):                   Step of a repeated job (rep_opt: s2, s3…), 1 otherwise.
        run (int):                    Run number (2, 3… are continuations of a stopped or failed run).
        software, comp_type (str):    For instance 'g16', 'opt'.
        istate, fstate (str):         State read and state written.
        status (str):                 As SCOPE registered it ('' if not registered yet).
        group (str):                  'ok', 'warn', 'err', 'unknown', 'waiting' (no output here) or 'unregistered' (output here, not read yet).
        elapsed, cpu (float|None):    Wall and CPU time as registered.
        out_path (str):               Output file on this computer.
        out_rel (str):                The same, relative to Computations/<system>/ (what a download names).
        out_exists (bool):            Whether the output is on this computer.
        inp_exists (bool):            Whether the input is on this computer.
    """
    branch:     str
    workflow:   str
    job:        str
    step:       int
    run:        int
    software:   str
    comp_type:  str
    istate:     str
    fstate:     str
    status:     str
    group:      str
    elapsed:    "float | None"
    cpu:        "float | None"
    out_path:   str
    out_rel:    str
    out_exists: bool
    inp_exists: bool

    @property
    def label(self) -> str:
        return run_label(self.job, self.step, self.run)

    @property
    def status_text(self) -> str:
        if self.group == "waiting":      return "no output here (still running, not downloaded, or not started)"
        if self.group == "unregistered": return "output here, not registered yet (run SCOPE to read it)"
        return STATUS_TEXT.get(self.status, self.status or "unknown")

@dataclass
class StateRow:
    """One state of one source, with what was computed for it.

    Attributes:
        source, source_type (str):  Source name and type ('specie', 'cell', …).
        formula (str):              Formula of the source.
        state (str):                State name ('initial', 'pbe_opt', …).
        energy (float|None):        Energy in Hartree, None if none was registered (never 0).
        energy_note (str):          Why the energy is missing or how it was converted.
        minimum (bool|None):        True/False once frequencies are known, None otherwise.
        n_freqs, n_imag (int):      Number of frequencies and of imaginary ones.
        runs (list):                Labels of the calculations that wrote this state, in order ('opt r1', 'freq r1').
        group (str):                Status group of the LAST of those calculations (whose values the state holds); 'none' if no calculation wrote it.
        retried (bool):             An earlier calculation of this state failed or stopped and was continued.
        method (str):               Software, functional and basis (or pseudopotentials) of the last calculation, as SCOPE's input asked for them.
    """
    source:      str
    source_type: str
    formula:     str
    state:       str
    energy:      "float | None"
    energy_note: str
    minimum:     "bool | None"
    n_freqs:     int
    n_imag:      int
    runs:        list
    group:       str
    retried:     bool = False
    method:      str  = ""

@dataclass
class Summary:
    """Tables of one system."""
    states: list
    comps:  list

    @property
    def missing_outputs(self) -> list:
        """Outputs that SCOPE registered (or expects) but that are not on this computer, relative to Computations/<system>/."""
        return [c.out_rel for c in self.comps if not c.out_exists and c.group != "unregistered"]

    def counts(self) -> tuple:
        """(sources with at least one computed state, all sources)."""
        names = []; done = set()
        for r in self.states:
            if r.source not in names: names.append(r.source)
            if r.runs and r.group != "none": done.add(r.source)
        return len(done), len(names)

@dataclass
class Loaded:
    """A system ready to show: the object (kept for later analyses), where it came from, and its tables."""
    system:     object
    provenance: Provenance
    summary:    Summary

#################
### Open      ###
#################
def fingerprint(path: str) -> tuple:
    """(size, modification time in ns) of a file, or () if it does not exist. Compared to know whether a shown file changed."""
    try: st = os.stat(path); return (st.st_size, st.st_mtime_ns)
    except OSError: return ()

def system_file(env: object, system: str) -> str:
    return os.path.join(env.systems_path, system, f"{system}.npy")

def open_system(env, system: str, file: str="") -> tuple:
    """Loads a system and points its paths at the folders of `env` on this computer, without saving anything or creating folders.

    Parameters:
        env (str | Environment):  Environment file (or object) of this computer.
        system (str):             Name of the system (its folder in Systems/).
        file (str):               Another file to read instead of Systems/<system>/<system>.npy, for instance an older copy
                                  kept by a download (<system>.npy.bak-<time>). Its paths are pointed at the same folders.

    Returns:
        tuple: (System, Provenance). Raises ResultsError with a hint when it cannot be shown.
    """
    import scope
    from scope.read_write import load_binary
    if isinstance(env, str):
        if not os.path.isfile(env): raise ResultsError("no_environment", f"Environment file not found: {env}", "Open or create the environment of this project on the Environment page.")
        env_file = os.path.abspath(env)
        try: env = load_binary(env_file)
        except Exception as exc: raise ResultsError("unreadable", f"Cannot read the environment {env_file}: {type(exc).__name__}: {exc}")
    else: env_file = getattr(env, "filepath", "")
    own = system_file(env, system); path = os.path.abspath(file) if file else own
    if not os.path.isfile(path):
        if file: raise ResultsError("no_system", f"File not found: {path}", "The copy may have been deleted or moved.")
        raise ResultsError("no_system", f"No system file for '{system}': {path}", "Run the system (Run page), or download its results from the cluster (Cluster page).")
    try: obj = load_binary(path)
    except ModuleNotFoundError as exc:
        top = (exc.name or "").split(".")[0]; pkg = ADDONS.get(top, top)
        raise ResultsError("addon", f"'{system}' was saved with the SCOPE add-on '{top}', which is not installed here.", f"Install it in the Python that runs this window:  {os.path.basename(_python())} -m pip install {pkg}")
    except Exception as exc: raise ResultsError("unreadable", f"Cannot read {path}: {type(exc).__name__}: {exc}", "The file may be incomplete (an interrupted copy) or from a very different SCOPE version.")
    if getattr(obj, "object_type", "") != "system": raise ResultsError("unreadable", f"{path} is not a SCOPE system (object_type={getattr(obj, 'object_type', '?')!r})")
    st = os.stat(path); stored = getattr(obj, "computations_path", "")
    remap(obj, env, system)
    prov = Provenance(system, path, st.st_size, st.st_mtime, str(getattr(obj, "version", "")), str(getattr(scope, "__version__", "")), env_file, stored, obj.computations_path,
                      sorted(glob.glob(glob.escape(own) + ".bak-*"), reverse=True), own)
    return obj, prov

def remap(obj: object, env: object, system: str) -> None:
    """Points the paths of a loaded system (and of its branches, jobs and calculations) at the folders of `env`, in memory only.
    SCOPE's set_paths_from_environment is not used: it creates Computations/<system>/<branch>/ even with create_folders=False."""
    obj.sources_path      = os.path.join(env.sources_path, system) + "/"
    obj.system_path       = os.path.join(env.systems_path, system) + "/"
    obj.system_file       = system_file(env, system)
    obj.computations_path = os.path.join(env.computations_path, system) + "/"
    obj.set_paths_down_hierarchy(create_folders=False)

def _python() -> str:
    import sys
    return sys.executable

#################
### Tables    ###
#################
def to_hartree(data: object) -> tuple:
    """(value in Hartree or None, note) from a SCOPE Data object; the object itself is not changed."""
    if data is None: return None, "no energy registered"
    value, units = getattr(data, "value", None), str(getattr(data, "units", "")).strip().lower()
    try: value = float(value)
    except (TypeError, ValueError): return None, f"energy not a number ({value!r})"
    if units in HARTREE: return value, ""
    for name, factor in UNITS.items():
        if units == name.lower().replace("/mol", "mol").replace(" ", "") or units == name.lower(): return value / factor, f"converted from {name}"
    return None, f"energy in unknown units '{units}'"

def run_label(job: str, step: int, run: int) -> str:
    """'opt r1', or 'vc s3 r2' for step 3 of a repeated job, as in SCOPE's file names (…_vc_s3_r2)."""
    return f"{job}{f' s{step}' if step and step > 1 else ''} r{run}"

def method_of(c: object) -> str:
    """What a calculation asked for, from its input data: 'g16 b3lyp** def2svp', 'qe pbe vanderbilt'."""
    qc = getattr(c, "qc_data", None)
    parts = [getattr(qc, "software", ""), getattr(qc, "functional", ""), getattr(qc, "basis", "") or getattr(qc, "pseudo", "")]
    return " ".join(str(x) for x in parts if x)

def comp_group(c: object) -> str:
    """Status group of one calculation: ok / warn / err / unknown once registered; unregistered (output here, not read yet) or waiting otherwise."""
    if getattr(c, "isregistered", False): return STATUS_GROUP.get(str(getattr(c, "status", "") or ""), "unknown")
    out = getattr(c, "out_path", "") or ""
    return "unregistered" if out and os.path.isfile(out) else "waiting"

def comp_rows(obj: object) -> list:
    rows = []
    for br in getattr(obj, "branches", []):
        for wf in br.workflows:
            for job in wf.jobs:
                for c in job.computations:
                    out = getattr(c, "out_path", "") or ""; out_exists = bool(out) and os.path.isfile(out)
                    registered = bool(getattr(c, "isregistered", False)); status = str(getattr(c, "status", "") or "") if registered else ""
                    qc = getattr(c, "qc_data", None)
                    rel = os.path.relpath(out, obj.computations_path) if out else ""
                    rows.append(CompRow(br.name, wf.name, job.name, int(getattr(c, "step", 1) or 1), int(getattr(c, "run_number", 1) or 1), str(getattr(c, "software", "")), str(getattr(c, "type", "")),
                                        str(getattr(qc, "istate", "")), str(getattr(qc, "fstate", "")), status, comp_group(c),
                                        _num(getattr(c, "elapsed_time", None)) if registered else None, _num(getattr(c, "cpu_time", None)) if registered else None,
                                        out, rel, out_exists, bool(getattr(c, "inp_path", "")) and os.path.isfile(c.inp_path)))
    return rows

def state_rows(obj: object) -> list:
    rows = []
    for src in getattr(obj, "sources", []):
        for st in getattr(src, "states", []):
            comps = list(getattr(st, "computations", []) or [])
            energy, note = to_hartree(getattr(st, "results", {}).get("energy"))
            freqs = [f for f in (getattr(st, "freqs_cm", None) or [])]
            labels = [run_label(c._job.name, getattr(c, "step", 1), getattr(c, "run_number", 1)) for c in comps]
            groups = [comp_group(c) for c in comps]
            minimum = getattr(st, "isminimum", None) if freqs else None
            rows.append(StateRow(src.name, str(getattr(src, "object_subtype", "")), str(getattr(src, "formula", "")), st.name, energy, note,
                                 minimum, len(freqs), sum(1 for f in freqs if f < 0), labels, groups[-1] if groups else "none",
                                 any(g != "ok" for g in groups[:-1]), method_of(comps[-1]) if comps else ""))
    return rows

def summarize(obj: object) -> Summary:
    return Summary(state_rows(obj), comp_rows(obj))

def load(env, system: str, file: str="") -> Loaded:
    """open_system + summarize: everything the Results page needs, built in a worker thread."""
    obj, prov = open_system(env, system, file)
    return Loaded(obj, prov, summarize(obj))

def _num(value) -> "float | None":
    try: return None if value is None else float(value)
    except (TypeError, ValueError): return None

def relative_energies(rows: list) -> dict:
    """ΔE (Hartree) of each row against the lowest energy among the rows that can be compared with it: same formula AND same method
    (energies of different methods or compositions are not comparable). {(source, state): ΔE}; rows without energy, or alone in their group, are left out."""
    groups = {}
    for r in rows:
        if r.energy is not None: groups.setdefault((r.formula, r.method), []).append(r)
    return {(r.source, r.state): r.energy - min(x.energy for x in g) for g in groups.values() if len(g) > 1 for r in g}

#################
### Exports   ###
#################
def provenance_lines(prov: Provenance) -> list:
    """Where exported numbers come from, one fact per line (no comment sign)."""
    when = time.strftime("%Y-%m-%d %H:%M", time.localtime(prov.mtime))
    lines = [f"system: {prov.system}", f"file: {prov.file} ({when}, {prov.size} bytes)"]
    if prov.is_copy: lines.append(f"older copy of: {prov.current_file}")
    lines += [f"saved by SCOPE {prov.saved_version or '?'}; read with SCOPE {prov.local_version or '?'}", f"folders of environment: {prov.env_file}"]
    if prov.moved: lines.append(f"written where SCOPE ran: {prov.stored_root} (paths pointed at {prov.local_root} for reading)")
    return lines

def header(provs: "Provenance | list | None"=None, settings: "dict | None"=None) -> str:
    """Comment lines ('# …') that open every CSV export: the provenance of each system used, the export time, then the settings."""
    provs = [] if provs is None else (provs if isinstance(provs, (list, tuple)) else [provs])
    lines = [l for p in provs for l in provenance_lines(p)]
    if provs: lines.append(f"exported: {time.strftime('%Y-%m-%d %H:%M:%S')} by the SCOPE GUI (read-only)")
    lines += [f"{k}: {v}" for k, v in (settings or {}).items()]
    return "".join(f"# {l}\n" for l in lines)

def plot_metadata(provs: "Provenance | list | None", settings: "dict | None"=None, title: str="") -> dict:
    """The same provenance for a saved plot, as {'Title', 'Description'}; plots.PlotCanvas.save maps it to each format's metadata keys."""
    text = header(provs, settings).replace("# ", "").strip()
    return {"Title": title, "Description": text}

def overview_csv(rows: list, units: str="kcal/mol", prov: "Provenance | None"=None) -> str:
    """The overview table as CSV, with the provenance as leading comment lines."""
    out = io.StringIO(); factor = UNITS[units]; rel = relative_energies(rows)
    if prov: out.write(header(prov, {"dE": "against the lowest energy of the same formula and method"}))
    w = csv.writer(out)
    w.writerow(["source", "formula", "state", "method", "energy_Eh", f"dE_{units}", "minimum", "n_freqs", "n_imaginary", "runs", "status", "retried"])
    for r in rows:
        de = rel.get((r.source, r.state))
        w.writerow([r.source, r.formula, r.state, r.method, "" if r.energy is None else f"{r.energy:.10f}", "" if de is None else f"{de * factor:.4f}",
                    "" if r.minimum is None else ("yes" if r.minimum else "no"), r.n_freqs, r.n_imag, " ".join(r.runs), r.group, "yes" if r.retried else ""])
    return out.getvalue()

def comps_csv(comps: list, prov: "Provenance | None"=None) -> str:
    """The Calculations table as CSV (one row per run), with the provenance first."""
    out = io.StringIO()
    if prov: out.write(header(prov))
    w = csv.writer(out)
    w.writerow(["branch", "workflow", "calculation", "software", "type", "reads", "writes", "status", "group", "wall_s", "cpu_s", "output", "output_here"])
    for c in comps:
        w.writerow([c.branch, c.workflow, c.label, c.software, c.comp_type, c.istate, c.fstate, c.status, c.group, "" if c.elapsed is None else f"{c.elapsed:g}",
                    "" if c.cpu is None else f"{c.cpu:g}", c.out_rel, "yes" if c.out_exists else "no"])
    return out.getvalue()

@dataclass
class VersionRow:
    """One state in an older copy of a system file and in the current one. energy/group/runs are None when the state is not in that file."""
    source:     str
    state:      str
    old_energy: "float | None"
    new_energy: "float | None"
    old_group:  "str | None"
    new_group:  "str | None"
    old_runs:   "list | None"
    new_runs:   "list | None"

    @property
    def change(self) -> str:
        """'' (same), 'new', 'gone', 'computed' (no energy before), 'energy' (the value moved), 'status' or 'runs'."""
        if self.old_group is None: return "new"
        if self.new_group is None: return "gone"
        if self.old_energy is None and self.new_energy is not None: return "computed"
        if (self.old_energy is None) != (self.new_energy is None) or (self.old_energy is not None and abs(self.old_energy - self.new_energy) > 1e-10): return "energy"
        if self.old_group != self.new_group: return "status"
        if self.old_runs != self.new_runs: return "runs"
        return ""

def version_diff(old: Summary, new: Summary) -> list:
    """The states of two summaries of one system side by side (an older copy and the current file), in the current file's order, then
    the states that only the older copy has."""
    o = {(r.source, r.state): r for r in old.states}; n = {(r.source, r.state): r for r in new.states}
    keys = list(n) + [k for k in o if k not in n]
    get = lambda d, k, a: getattr(d[k], a) if k in d else None
    return [VersionRow(k[0], k[1], get(o, k, "energy"), get(n, k, "energy"), get(o, k, "group"), get(n, k, "group"), get(o, k, "runs"), get(n, k, "runs")) for k in keys]

#################
### Logs      ###
#################
MARKS = [("Normal termination", "ok"), ("Error termination", "err"), ("SCF Done", "info"), ("Optimization completed", "ok"), ("Stationary point found", "ok"),
         ("imaginary frequencies", "warn"), ("Convergence failure", "err"), ("!    total energy", "info"), ("JOB DONE", "ok"), ("convergence NOT achieved", "err"),
         ("End of BFGS", "ok"), ("Error in routine", "err"), ("%%%%%%%%", "err")]

def read_log(path: str, limit: int=8_000_000) -> tuple:
    """(text, note) of an output file; files larger than `limit` bytes are cut to their last `limit` bytes, and the note says so."""
    size = os.path.getsize(path)
    with open(path, "rb") as fh:
        if size > limit: fh.seek(size - limit); data = fh.read(); note = f"Only the last {limit // 1_000_000} MB of {size / 1e6:.0f} MB are shown."
        else:            data = fh.read(); note = ""
    text = data.decode("utf-8", errors="replace")
    if note: text = text[text.find("\n") + 1:]                                     ## drop the partial first line
    return text, note

def log_marks(text: str) -> list:
    """Lines worth jumping to: [(line number from 0, kind, line text)], kind in ok / err / warn / info.
    Every ok / err / warn line is kept; of the repeated 'info' lines (an energy at each optimisation step) only the first and the last."""
    found, info = [], {}
    for i, line in enumerate(text.splitlines()):
        for pattern, kind in MARKS:
            if pattern in line:
                if kind == "info": info.setdefault(pattern, []).append((i, kind, line.strip()))
                else: found.append((i, kind, line.strip()))
                break
    for hits in info.values(): found += [hits[0]] + ([hits[-1]] if len(hits) > 1 else [])
    return sorted(found)

#################
### States    ###
#################
KERNELS = ["gaussian", "lorentzian", "laplacian"]                              ## as SCOPE's build_spectrum accepts them

@dataclass
class Mode:
    """One vibrational normal mode as SCOPE stored it: number (from 1), frequency (cm⁻¹, negative = imaginary), IR intensity (km/mol), reduced mass (amu), symmetry."""
    index:    int
    freq:     float
    ir:       "float | None"
    red_mass: "float | None"
    sym:      str

@dataclass
class StateDetail:
    """What the State tab shows for one state.

    Attributes:
        source, state (str):     Names.
        structure:               scope.gui.structure.Structure of the state's geometry, or None.
        modes (list):            Mode rows (empty if no frequencies were computed).
        has_ir (bool):           At least one mode has a non-zero IR intensity (otherwise an IR spectrum would be flat).
        n_excited (int):         Number of stored excited states (absorption spectrum possible when > 0).
        z (float|None):          Formula units in the state (cells); spectra can be shown per formula unit.
    """
    source:    str
    state:     str
    structure: object
    modes:     list
    has_ir:    bool
    n_excited: int
    z:         "float | None"

def find_state(obj: object, source: str, state: str) -> object:
    for src in getattr(obj, "sources", []):
        if src.name != source: continue
        for st in getattr(src, "states", []):
            if st.name == state: return src, st
    raise KeyError(f"No state '{state}' in source '{source}'")

def state_detail(obj: object, source: str, state: str) -> StateDetail:
    from scope.gui import structure
    src, st = find_state(obj, source, state)
    modes = [Mode(int(getattr(v, "index", i + 1) or i + 1), float(v.freq_cm), _num(getattr(v, "IR_int", None)), _num(getattr(v, "red_mass", None)), str(getattr(v, "sym", "") or ""))
             for i, v in enumerate(getattr(st, "VNMs", None) or []) if _num(getattr(v, "freq_cm", None)) is not None]
    try: z = float(st.Z)
    except Exception: z = None
    return StateDetail(source, state, structure.state_structure(src, st), modes, any((m.ir or 0) > 0 for m in modes), len(getattr(st, "exc_states", None) or []), z)

@dataclass
class Spectrum:
    """A broadened spectrum ready to draw: the curve, the sticks under it, and the axis labels."""
    x:      list
    y:      list
    sticks: list                                                               ## [(position, height)]
    xlabel: str
    ylabel: str
    title:  str

def spectrum(obj: object, source: str, state: str, kind: str="ir", function: str="gaussian", sigma: float=10.0, xmin: "float | None"=None, xmax: "float | None"=None,
             per_formula_unit: bool=True) -> Spectrum:
    """IR, VDOS or absorption spectrum of a state, computed by SCOPE's own get_ir_spectrum / get_vdos_spectrum / get_abs_spectrum, so it is
    the curve SCOPE's plot_* functions draw with the same settings. SCOPE caches the arrays on the state object in memory; nothing is saved.

    Parameters:
        kind (str):                  'ir', 'vdos' or 'abs'.
        function (str):              Broadening kernel (KERNELS).
        sigma (float):               Width: cm⁻¹ for IR and VDOS, eV for absorption.
        xmin, xmax (float|None):     Range (cm⁻¹, or nm for absorption); None for SCOPE's defaults (absorption: 200–1000 nm).
        per_formula_unit (bool):     Divide by the formula units of a cell (IR, VDOS).
    """
    import numpy as np
    src, st = find_state(obj, source, state)
    if function not in KERNELS: raise ValueError(f"Unknown kernel '{function}'")
    if kind == "abs":
        lmin, lmax = int(xmin if xmin is not None else 200), int(xmax if xmax is not None else 1000)
        x, y = st.get_abs_spectrum(lmin=lmin, lmax=lmax, function=function, sigma=sigma)
        sticks = [(float(e.wavelength), float(e.fosc)) for e in (getattr(st, "exc_states", None) or []) if lmin <= float(e.wavelength) <= lmax]
        return Spectrum(list(map(float, x)), list(map(float, y)), sticks, "Wavelength (nm)", "Oscillator strength (broadened)", f"Absorption · {source} · {state}")
    units = float(st.Z) if per_formula_unit else 1.0
    if kind == "ir":
        x, y = st.get_ir_spectrum(vmin=xmin, vmax=xmax, function=function, sigma=sigma, per_formula_unit=per_formula_unit)
        sticks = [(float(v.freq_cm), float(v.IR_int) / units) for v in st.VNMs]
        label = "IR intensity (km/mol" + (" per formula unit)" if per_formula_unit and units != 1 else ")")
        return Spectrum(list(map(float, x)), list(map(float, y)), sticks, "Wavenumber (cm⁻¹)", label, f"IR · {source} · {state}")
    if kind == "vdos":
        x, y = st.get_vdos_spectrum(vmin=xmin, vmax=xmax, function=function, sigma=sigma, per_formula_unit=per_formula_unit)
        sticks = [(float(v.freq_cm), 0.0) for v in st.VNMs]
        return Spectrum(list(map(float, x)), list(map(float, np.asarray(y))), sticks, "Wavenumber (cm⁻¹)", "Modes per cm⁻¹" + (" per formula unit" if per_formula_unit and units != 1 else ""), f"Vibrational density of states · {source} · {state}")
    raise ValueError(f"Unknown spectrum '{kind}'")

def xyz_text(s: object, comment: str="") -> str:
    """A structure (scope.gui.structure.Structure) as the text of an .xyz file."""
    lines = [str(len(s.labels)), comment.replace("\n", " ")]
    lines += [f"{a:<3} {c[0]:14.8f} {c[1]:14.8f} {c[2]:14.8f}" for a, c in zip(s.labels, s.coords)]
    return "\n".join(lines) + "\n"

def spectrum_csv(sp: Spectrum, prov: "Provenance | None"=None, settings: "dict | None"=None) -> str:
    """A spectrum as CSV: the broadened curve (x, y) and, in two more columns, the sticks under it (modes or excited states)."""
    out = io.StringIO(); out.write(header(prov, (settings or {}) | {"spectrum": sp.title}) if prov or settings else ""); w = csv.writer(out)
    w.writerow([sp.xlabel, sp.ylabel, f"stick {sp.xlabel}", "stick height"])
    for i in range(max(len(sp.x), len(sp.sticks))):
        a = [f"{sp.x[i]:.6g}", f"{sp.y[i]:.6g}"] if i < len(sp.x) else ["", ""]
        b = [f"{sp.sticks[i][0]:.6g}", f"{sp.sticks[i][1]:.6g}"] if i < len(sp.sticks) else ["", ""]
        w.writerow(a + b)
    return out.getvalue()

def modes_csv(modes: list, prov: "Provenance | None"=None, settings: "dict | None"=None) -> str:
    out = io.StringIO(); out.write(header(prov, settings) if prov or settings else ""); w = csv.writer(out); w.writerow(["mode", "frequency_cm-1", "IR_km/mol", "reduced_mass_amu", "symmetry"])
    for m in modes: w.writerow([m.index, f"{m.freq:.4f}", "" if m.ir is None else f"{m.ir:.4f}", "" if m.red_mass is None else f"{m.red_mass:.4f}", m.sym])
    return out.getvalue()

#######################
### Thermochemistry ###
#######################
MODELS     = ["HO", "QRRHO"]                                                   ## SCOPE's vibrational models (QRRHO: Grimme's quasi-rigid-rotor)
IMAGINARY  = ["ignore", "absolute", "raise"]                                   ## SCOPE's policies for imaginary frequencies

@dataclass
class Thermo:
    """Thermochemistry of one state over temperature, from SCOPE's get_thermal_data, per formula unit (cells: divided by Z).

    Attributes:
        source, state (str):     Names.
        T (list):                Temperatures (K).
        Helec (float):           Electronic energy per formula unit (Eh).
        Selec (float):           Electronic (spin) entropy (Eh/K).
        Hvib, Svib, G (list):    Vibrational enthalpy (Eh), vibrational entropy (Eh/K) and Gibbs energy (Eh) at each T.
        z (float):               Formula units.
        n_imag (int):            Imaginary frequencies (treated as `imaginary` says).
        settings (dict):         model, imaginary and QRRHO parameters used.
    """
    source:   str
    state:    str
    T:        list
    Helec:    float
    Selec:    float
    Hvib:     list
    Svib:     list
    G:        list
    z:        float
    n_imag:   int
    settings: dict

    def at(self, temperature: float) -> int:
        return min(range(len(self.T)), key=lambda i: abs(self.T[i] - temperature))

def thermo_ready(obj: object, source: str, state: str) -> str:
    """'' if thermochemistry can be computed for this state, otherwise why not (no frequencies, no energy)."""
    src, st = find_state(obj, source, state)
    if not (getattr(st, "VNMs", None) or []): return "no frequencies were computed for this state (a frequency job writes them)"
    if st.results.get("energy") is None: return "no energy is registered for this state"
    return ""

_THERMO_LOCK = threading.Lock()

def thermo(obj: object, source: str, state: str, temps: list, model: str="HO", imaginary: str="ignore", fr_cutoff: float=100.0, fr_alpha: float=4.0) -> Thermo:
    """Runs SCOPE's state.get_thermal_data on a shallow copy of the state that has its own results dictionary: the arithmetic is SCOPE's,
    and the state's results, energies and attributes are not changed (so the other tabs show the same values). Computing Z lets SCOPE fill
    derived caches (molecular graphs, adjacency) on the molecules the copy shares with the system; they change no value and are never saved.
    Calls are serialised, so two worker threads never build those caches at once. Raises ValueError with SCOPE's reason when it cannot."""
    import copy
    if model not in MODELS or imaginary not in IMAGINARY: raise ValueError(f"Unknown model or policy: {model}, {imaginary}")
    why = thermo_ready(obj, source, state)
    if why: raise ValueError(why)
    src, st = find_state(obj, source, state)
    work = copy.copy(st); work.results = dict(st.results)
    options = {"model": model, "imaginary": imaginary} | ({"FR_cutoff": fr_cutoff, "FR_alpha": fr_alpha} if model == "QRRHO" else {})
    temps = sorted({float(t) for t in temps})
    with _THERMO_LOCK: work.get_thermal_data(temp=temps, vib_options=options)
    r = work.results
    pick = lambda key: [r[key].find_value_with_property("temperature", t).value for t in temps]
    units = {r[k].units if hasattr(r[k], "units") else r[k].datas[0].units for k in ("Helec", "Selec", "Hvib", "Svib", "Gtot")}
    if units != {"au"}: raise ValueError(f"Unexpected units from SCOPE: {units}")
    return Thermo(source, state, temps, float(r["Helec"].value), float(r["Selec"].value), pick("Hvib"), pick("Svib"), pick("Gtot"), float(work.z),
                  sum(1 for f in (st.freqs_cm or []) if f < 0), options)

@dataclass
class Difference:
    """A minus B over the temperatures both have (Eh): ΔG, ΔH and −TΔS, and where ΔG changes sign."""
    a:        str
    b:        str
    T:        list
    dG:       list
    dH:       list
    mTdS:     list
    crossing: list                                                             ## temperatures (K) where ΔG = 0, linearly interpolated

def difference(a: Thermo, b: Thermo) -> Difference:
    """ΔX = X(a) − X(b). A crossing of ΔG through zero is the temperature where the two states are equally stable (T½ for a spin-crossover HS/LS pair)."""
    common = sorted(set(a.T) & set(b.T))
    ia, ib = {t: i for i, t in enumerate(a.T)}, {t: i for i, t in enumerate(b.T)}
    dG, dH, mTdS = [], [], []
    for t in common:
        i, j = ia[t], ib[t]
        h = (a.Helec + a.Hvib[i]) - (b.Helec + b.Hvib[j]); s = (a.Selec + a.Svib[i]) - (b.Selec + b.Svib[j])
        dG.append(a.G[i] - b.G[j]); dH.append(h); mTdS.append(-t * s)
    crossing = [common[k] + (common[k + 1] - common[k]) * dG[k] / (dG[k] - dG[k + 1]) for k in range(len(common) - 1) if dG[k] == 0 or dG[k] * dG[k + 1] < 0]
    if common and dG[-1] == 0: crossing.append(common[-1])
    return Difference(f"{a.source} · {a.state}", f"{b.source} · {b.state}", common, dG, dH, mTdS, sorted(set(round(c, 3) for c in crossing)))

def with_frequencies(summary: Summary) -> list:
    """(source, state) of the states that have frequencies and an energy: the ones thermochemistry and IR can be computed for."""
    return [(r.source, r.state) for r in summary.states if r.n_freqs and r.energy is not None]

def comparable_pairs(summary: Summary) -> list:
    """Pairs ((source, state), (source, state)) of states with frequencies and the same formula and method, in two different sources:
    the pairs whose ΔG(T) means something (for instance the high- and low-spin states of a spin-crossover compound)."""
    rows = [r for r in summary.states if r.n_freqs and r.energy is not None]
    return [((a.source, a.state), (b.source, b.state)) for i, a in enumerate(rows) for b in rows[i + 1:] if a.source != b.source and (a.formula, a.method) == (b.formula, b.method)]

def thermo_csv(th: Thermo, units: str="kcal/mol", prov: "Provenance | None"=None) -> str:
    out = io.StringIO(); f = UNITS[units]; w = csv.writer(out)
    if prov: out.write(header(prov))
    out.write(f"# {th.source} {th.state}; per formula unit (Z = {th.z:g}); settings {th.settings}; Helec = {th.Helec:.10f} Eh, Selec = {th.Selec:.6e} Eh/K\n")
    w.writerow(["T_K", "G_Eh", f"Hvib_{units}", f"minus_TS_{units}", f"G_minus_Helec_{units}"])
    for i, t in enumerate(th.T): w.writerow([f"{t:g}", f"{th.G[i]:.10f}", f"{th.Hvib[i] * f:.4f}", f"{-t * (th.Selec + th.Svib[i]) * f:.4f}", f"{(th.G[i] - th.Helec) * f:.4f}"])
    return out.getvalue()

def difference_csv(d: Difference, units: str="kcal/mol", prov: "Provenance | None"=None, settings: "dict | None"=None) -> str:
    out = io.StringIO(); f = UNITS[units]; w = csv.writer(out)
    if prov or settings: out.write(header(prov, settings))
    out.write(f"# A ={d.a}; B = {d.b}; ΔX = X(A) - X(B); ΔG = 0 at {', '.join(f'{c:g} K' for c in d.crossing) or 'no temperature in range'}\n")
    w.writerow(["T_K", f"dG_{units}", f"dH_{units}", f"minus_TdS_{units}"])
    for i, t in enumerate(d.T): w.writerow([f"{t:g}", f"{d.dG[i] * f:.4f}", f"{d.dH[i] * f:.4f}", f"{d.mTdS[i] * f:.4f}"])
    return out.getvalue()

###############
### Compare ###
###############
@dataclass
class CompareRow:
    """One state of one system, for the Compare tab. value is the electronic energy (Eh) or G(T) per formula unit (Eh); None when unavailable."""
    system:  str
    source:  str
    state:   str
    formula: str
    method:  str
    value:   "float | None"
    note:    str = ""

def compare_rows(loaded: list, quantity: str="energy", temperature: float=298.15, model: str="HO", imaginary: str="ignore") -> list:
    """Rows of several loaded systems (results.Loaded). quantity 'energy' uses the registered energies; 'gibbs' computes G(T) with SCOPE's
    thermochemistry for every state that has frequencies (others get None and a note)."""
    rows = []
    for L in loaded:
        for r in L.summary.states:
            if r.energy is None: continue
            if quantity == "energy": rows.append(CompareRow(L.provenance.system, r.source, r.state, r.formula, r.method, r.energy)); continue
            why = thermo_ready(L.system, r.source, r.state)
            if why: rows.append(CompareRow(L.provenance.system, r.source, r.state, r.formula, r.method, None, why)); continue
            try: th = thermo(L.system, r.source, r.state, [temperature], model, imaginary); rows.append(CompareRow(L.provenance.system, r.source, r.state, r.formula, r.method, th.G[0]))
            except Exception as exc: rows.append(CompareRow(L.provenance.system, r.source, r.state, r.formula, r.method, None, f"{type(exc).__name__}: {exc}"))
    return rows

def compare_relative(rows: list) -> dict:
    """Δ of each row against the lowest value among rows of the same formula AND method, across systems: {(system, source, state): Δ (Eh)}.
    Rows alone in their group, or without a value, are left out (their values cannot be compared with anything shown)."""
    groups = {}
    for r in rows:
        if r.value is not None: groups.setdefault((r.formula, r.method), []).append(r)
    return {(r.system, r.source, r.state): r.value - min(x.value for x in g) for g in groups.values() if len(g) > 1 for r in g}

def compare_csv(rows: list, units: str="kcal/mol", quantity: str="energy", temperature: float=298.15, provs: "list | None"=None, settings: "dict | None"=None) -> str:
    out = io.StringIO(); f = UNITS[units]; rel = compare_relative(rows); w = csv.writer(out)
    what = {"quantity": f"{'electronic energy' if quantity == 'energy' else f'G at {temperature:g} K per formula unit'}; Δ against the lowest of the same formula and method"}
    out.write(header(provs, what | (settings or {})))
    w.writerow(["system", "source", "state", "formula", "method", "value_Eh", f"delta_{units}", "note"])
    for r in rows:
        d = rel.get((r.system, r.source, r.state))
        w.writerow([r.system, r.source, r.state, r.formula, r.method, "" if r.value is None else f"{r.value:.10f}", "" if d is None else f"{d * f:.4f}", r.note])
    return out.getvalue()
