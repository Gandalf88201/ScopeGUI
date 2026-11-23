"""Non-Qt layer of the SCOPE GUI.

Wraps existing SCOPE functions without prompts, so the window and the tests can call them directly. Nothing here
imports Qt. Long operations (scope run) are not executed here: build_run_command() only prepares the command line
that the window starts as a separate process.
"""
import io
import os
import shutil
import sys
import json
from collections.abc import Callable
from contextlib   import contextmanager, redirect_stdout
from dataclasses  import dataclass, field
from glob         import glob
import re
from pathlib      import Path

SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]*$")

###############
### Helpers ###
###############
def with_slash(path: str) -> str:
    """Returns an absolute path that ends with '/', as SCOPE expects for folders."""
    path = os.path.abspath(os.path.expanduser(path))
    if not path.endswith('/'): path += '/'
    return path

def gui_config_path() -> str:
    """Returns the path of the GUI preferences file, inside the same folder used by scope_config.json."""
    from platformdirs import user_config_dir
    return os.path.join(user_config_dir("scope"), "scope_gui.json")

def load_gui_config() -> dict:
    """Reads the GUI preferences. Returns an empty dictionary if the file is missing or unreadable."""
    try:
        with open(gui_config_path()) as f: return json.load(f)
    except Exception: return {}

@contextmanager
def file_lock(path: str):
    """Exclusive lock held while the block runs (a lock file next to the data), so two windows that update the same file do not overwrite each other."""
    try: import fcntl
    except ImportError: yield; return                                       ## Windows: no fcntl
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try: yield
        finally: fcntl.flock(handle, fcntl.LOCK_UN)

def save_gui_config(data: dict) -> None:
    """Updates some keys of the GUI preferences: the file is read again under a lock and only those keys are replaced. Failures (read-only home, for instance) are ignored."""
    try:
        with file_lock(gui_config_path() + ".lock"):
            config = load_gui_config(); config.update(data)
            tmp = gui_config_path() + f".{os.getpid()}.tmp"
            with open(tmp, "w") as f: json.dump(config, f, indent=4)
            os.replace(tmp, gui_config_path())
    except Exception: pass

###################
### Environment ###
###################
@dataclass
class EnvInfo:
    """Summary of a SCOPE Environment binary.

    Attributes:
        filepath (str):        Path of the .npy file.
        name (str):            Environment name.
        scheduler (str):       'local', 'slurm' or 'sge'.
        sources_path (str):    Folder with the source structures.
        systems_path (str):    Folder with one subfolder per system binary.
        computations_path:     Folder with one subfolder per system with its calculations.
        missing (list):        Names of the folders above that do not exist on this machine.
        queues (list):         Names of the available queues.
        modules (dict):        Gaussian 16 and Quantum ESPRESSO modules, if configured.
    """
    filepath:           str
    name:               str
    scheduler:          str
    sources_path:       str
    systems_path:       str
    computations_path:  str
    missing:            list = field(default_factory=list)
    queues:             list = field(default_factory=list)
    modules:            dict = field(default_factory=dict)

def summarize_environment(env: object, filepath: str) -> EnvInfo:
    """Builds an EnvInfo from a loaded Environment object."""
    paths   = {"sources": getattr(env,"sources_path",""), "systems": getattr(env,"systems_path",""), "computations": getattr(env,"computations_path","")}
    missing = [k for k, v in paths.items() if not v or not os.path.isdir(v)]
    queues  = [q.name for q in getattr(env,"available_queues",[])]
    modules = {"g16": getattr(env,"g16_module",""), "qe": getattr(env,"qe_module","")}
    return EnvInfo(filepath, env.name, getattr(env,"scheduler","unknown"), paths["sources"], paths["systems"], paths["computations"], missing, queues, modules)

def load_environment(filepath: str) -> tuple:
    """Loads an Environment binary and checks its type.

    Parameters:
        filepath (str):    Path of a scope_env_*.npy file. It is a pickle: only open files you trust.

    Returns:
        tuple: (Environment object, EnvInfo). Raises ValueError if the file is not an Environment.
    """
    from scope.read_write import load_binary
    if not os.path.isfile(filepath): raise ValueError(f"Environment file not found: {filepath}")
    env = load_binary(filepath)
    if getattr(env,"object_type",None) != "environment": raise ValueError(f"Not an Environment binary file: {filepath}")
    return env, summarize_environment(env, os.path.abspath(filepath))

def create_environment(name: str, sources_path: str, systems_path: str, computations_path: str, save_dir: str, create_folders: bool=True) -> tuple:
    """Creates and saves a local Environment without prompts (the scheduler is set to 'local').

    Parameters:
        name (str):                 Name; the file is saved as scope_env_<name>.npy inside save_dir.
        sources_path (str):         Folder for the source structures.
        systems_path (str):         Folder for the system binaries.
        computations_path (str):    Folder for the calculations.
        save_dir (str):             Folder where the Environment binary is written.
        create_folders (bool):      Whether the three folders are created if missing.

    Returns:
        tuple: (Environment object, EnvInfo). Raises ValueError for an empty name or equal folders.
    """
    from scope.classes_environment import Environment
    name = name.strip()
    if not SAFE_NAME.match(name): raise ValueError("The environment name must use letters, digits, '_', '-' or '.', with no spaces or slashes")
    if not all(p and p.strip() for p in (sources_path, systems_path, computations_path, save_dir)): raise ValueError("Choose a project folder (or fill in the Sources, Systems, Computations and save-folder boxes).")
    folders = [with_slash(p) for p in (sources_path, systems_path, computations_path)]
    if len(set(folders)) < 3: raise ValueError("Sources, systems and computations must be three different folders")
    env                    = Environment(name)
    env.scheduler          = "local"
    env.set_commands()
    env.sources_path, env.systems_path, env.computations_path = folders
    if create_folders:
        for folder in folders: os.makedirs(folder, exist_ok=True)
    os.makedirs(save_dir, exist_ok=True)
    env.save(os.path.join(os.path.abspath(save_dir), f"scope_env_{name}.npy"))
    return env, summarize_environment(env, env.filepath)

###############
### Systems ###
###############
@dataclass
class SystemRow:
    """One system folder found in the Environment.

    Attributes:
        name (str):        Folder name.
        file (str):        Path of the system binary, or '' if the folder has none.
        finished (list):   Branches with a <branch>_FINISHED marker file.
        terminated (list): Branches with a <branch>_TERMINATED marker file.
        has_comp (bool):   Whether the computations folder exists.
    """
    name:       str
    file:       str
    finished:   list
    terminated: list
    has_comp:   bool

def list_systems(info: EnvInfo) -> list:
    """Lists systems by looking at the folders only (no binary is loaded).

    Branch status is read from the marker files written by Branch.set_status, which are named <branch>_FINISHED and
    <branch>_TERMINATED inside the system folder. Hidden folders are skipped.
    """
    rows = []
    if not os.path.isdir(info.systems_path): return rows
    for name in sorted(os.listdir(info.systems_path)):
        folder = os.path.join(info.systems_path, name)
        if name.startswith(".") or not os.path.isdir(folder): continue
        binary     = os.path.join(folder, f"{name}.npy")
        finished   = sorted(os.path.basename(p)[:-len("_FINISHED")]   for p in glob(os.path.join(folder, "*_FINISHED")))
        terminated = sorted(os.path.basename(p)[:-len("_TERMINATED")] for p in glob(os.path.join(folder, "*_TERMINATED")))
        rows.append(SystemRow(name, binary if os.path.isfile(binary) else "", finished, terminated, os.path.isdir(os.path.join(info.computations_path, name))))
    return rows

def system_details(filepath: str) -> str:
    """Returns the text representation of a system binary (it is a pickle: only open files you trust)."""
    from scope.gui.results import load_quietly
    system, _ = load_quietly(filepath)
    if getattr(system,"object_type",None) != "system": raise ValueError(f"Not a System binary file: {filepath}")
    return repr(system)

def import_xyz(env: object, xyz_path: str, overwrite: bool=False) -> str:
    """Creates a system from one .xyz file, as `scope create_single` does, without prompts or screen clearing.

    The file is copied to <sources_path>/<name>/<name>.xyz if it is not there yet. The system name is the file name
    without extension (the source inside is stored in lower case with underscores).

    Returns:
        str: Path of the saved system binary. Raises ValueError if the system exists and overwrite is False.
    """
    from scope.classes_system import System
    if not xyz_path.lower().endswith(".xyz"): raise ValueError("Only .xyz files can be imported")
    name = os.path.splitext(os.path.basename(xyz_path))[0]
    if not SAFE_NAME.match(name): raise ValueError(f"'{name}' is not a safe system name. Use letters, digits, '_', '-' or '.', with no spaces (SCOPE builds job and file names from it, and `sbatch <file>` is called without quotes).")
    target_dir  = os.path.join(env.sources_path, name)
    target_file = os.path.join(target_dir, f"{name}.xyz")
    system_file = os.path.join(env.systems_path, name, f"{name}.npy")
    if os.path.isfile(system_file) and not overwrite: raise ValueError(f"System '{name}' already exists")
    os.makedirs(target_dir, exist_ok=True)
    if os.path.abspath(xyz_path) != os.path.abspath(target_file): shutil.copyfile(xyz_path, target_file)
    system = System(name)
    system.set_paths_from_environment(env, create_folders=True)
    with redirect_stdout(io.StringIO()): system.load_single_xyz(target_file, overwrite=overwrite)
    system.create_folders()
    system.save()
    return system.system_file

#################
### Pipelines ###
#################
@dataclass
class InputReport:
    """Result of reading one Scope input file.

    Attributes:
        path (str):          Path of the file.
        ok (bool):           Whether SCOPE accepted it.
        error (str):         Error message if not.
        branch, job (str):   Branch and job names.
        workflow (str):      Workflow selector (a source-name pattern or list).
        requisites (list):   Jobs that must be finished and good before this one starts.
        constrains (list):   Jobs that block this one if finished ('self' means this job itself).
        software (str):      'g16' or 'qe'.
        comp_type (str):     Computation type.
        want_submit (bool):  Value of want_submit (SCOPE default is True when &options does not set it).
        procs (int):         Requested processors.
    """
    path:        str
    ok:          bool          = False
    error:       str           = ""
    branch:      str           = ""
    job:         str           = ""
    workflow:    object        = ""
    requisites:  list          = field(default_factory=list)
    constrains:  list          = field(default_factory=list)
    software:    str           = ""
    comp_type:   str           = ""
    want_submit: bool          = True
    procs:       int           = 1
    queues:      list          = field(default_factory=list)
    istate:      str           = "initial"
    fstate:      str           = ""

    @property
    def selectors(self) -> list:
        """The workflow selectors as a list of lower-case strings ('*', 'hs*', 'water')."""
        return selector_list(self.workflow)

    @property
    def workflow_label(self) -> str:
        """The workflow selector as written in a node name: '*', 'hs*' or 'a,b'."""
        return ",".join(self.selectors) or "?"

    @property
    def node(self) -> str:
        """Identity of this job in the pipeline: branch/workflow/job. Two files with one branch and job but different workflows
        (for instance the high-spin and the low-spin sources) are two different jobs, as they are in SCOPE."""
        return f"{self.branch}/{self.workflow_label}/{self.job}"

def read_input(path: str) -> InputReport:
    """Parses and validates a Scope input file with SCOPE's own functions, without loading any system.

    Never raises: problems are reported in InputReport.error. Messages SCOPE prints while parsing are discarded.
    """
    return _read_input(os.path.abspath(path), isfile=True)

def read_input_text(text: str) -> InputReport:
    """Same as read_input for the text of an input file that is not saved yet (path is left empty)."""
    return _read_input(text, isfile=False)

def _read_input(content: str, isfile: bool) -> InputReport:
    from scope.classes_input import set_input_data
    report = InputReport(content if isfile else "")
    try:
        with redirect_stdout(io.StringIO()): environment, options, job_data, qc_data = set_input_data(content, isfile=isfile, debug=0)
    except Exception as exc:
        report.error = f"{type(exc).__name__}: {exc}"
        return report
    report.ok          = True
    report.branch      = str(job_data.branch).lower().replace(" ","_")
    report.job         = job_data.job
    report.workflow    = job_data.workflow
    report.requisites  = list(job_data.requisites)
    report.constrains  = [c for c in job_data.constrains]
    report.software    = qc_data.software
    report.comp_type   = getattr(qc_data,"comp_type","scf")
    report.want_submit = bool(options.want_submit)
    report.procs       = int(environment.requested_procs)
    raw_queues         = getattr(environment, "queues", getattr(environment, "queue", ""))
    report.queues      = [q.strip() for q in str(raw_queues).split(",") if q.strip()]
    report.istate      = str(getattr(job_data, "istate", "initial"))
    report.fstate      = str(getattr(job_data, "fstate", report.job))
    return report

def selector_list(workflow) -> list:
    """job_data.workflow as SCOPE reads it (one selector or a list), lower-cased."""
    items = [workflow] if isinstance(workflow, str) else list(workflow or [])
    return [str(s).strip().lower() for s in items if str(s).strip()]

def selectors_overlap(a: list, b: list, sources: "list | None"=None) -> "bool | None":
    """Whether two workflow selectors can pick a common source. With the source names of a system, the answer is exact (SCOPE's own
    fnmatch rule). Without them: True when both pick the same names for sure ('*', identical selectors, or a pattern that matches the
    other's plain name), False when both are plain names that differ, None when it depends on the sources (two different patterns)."""
    from fnmatch import fnmatchcase
    if sources is not None:
        names = [s.lower() for s in sources]
        pick  = lambda sel: {n for n in names for x in sel if fnmatchcase(n, x)}
        return bool(pick(a) & pick(b))
    if "*" in a or "*" in b or set(a) & set(b): return True
    plain = lambda x: not any(ch in x for ch in "*?[")
    for names, patterns in ((a, b), (b, a)):
        if all(plain(x) for x in names):                                   ## plain names on one side: matching them is exact
            return any(fnmatchcase(n, p) for n in names for p in patterns)
    return None

GEOMETRY_TYPES = ("opt", "relax", "vc-relax", "ts")                         ## computation types that write a new geometry into fstate

def geometry_state(r: "InputReport") -> str:
    """The state a job that follows r should start from: the one r writes when r makes a geometry (opt, ts…) or adds its results to the
    state it read (freq into 'opt'); otherwise r writes its results into a new state that holds no coordinates (an scf writing 'sp'),
    so the next job starts from the geometry r used, r's istate."""
    return r.fstate if r.comp_type in GEOMETRY_TYPES or r.fstate == r.istate else r.istate

def suggest_states(job: str, comp_type: str, requisites: str, reports: list, branch: str="", workflow: str="*") -> tuple:
    """(istate, fstate) to propose in the input form. A job that waits for another one most likely wants that job's result, so istate is the
    fstate of the first requisite found among the loaded files (same branch, overlapping workflow), else 'initial'. A job that writes a
    geometry (opt, ts…) writes its own state, named after the job (SCOPE's default); any other job (freq, scf, td) adds its results to the
    state it reads, so frequencies and energy sit on the optimised geometry."""
    sel, istate = selector_list(split_names(workflow) if isinstance(workflow, str) else workflow) or ["*"], ""
    for name in split_names(requisites):
        found = [r for r in reports if r.ok and r.job == name and (not branch or r.branch == branch.strip().lower().replace(" ", "_")) and selectors_overlap(r.selectors, sel) is not False]
        if found: istate = geometry_state(found[0]) or found[0].job; break
    if not istate: return "initial", job.strip() or "job"                    ## no requisite found: SCOPE's own defaults
    return istate, (job.strip() or "job") if comp_type in GEOMETRY_TYPES else istate

##################
### Input form ###
##################
SECTIONS       = ("environment", "options", "job_data", "qc_data")
SOFTWARE_TYPES = {"g16": ["scf", "opt", "freq", "ts", "td", "tda"], "qe": ["scf", "opt", "relax", "vc-relax", "freq"]}
FORM_KEYS      = {"environment": ["requested_procs", "queue", "queues"], "options": ["want_submit"], "job_data": ["branch", "workflow", "job", "istate", "fstate", "requisites", "constrains"], "qc_data": ["software", "comp_type", "functional", "basis"]}

@dataclass(frozen=True)
class Option:
    """One optional SCOPE setting the input form has a field for (see OPTIONS).

    Attributes:
        section (str):     Section of the input file ('environment', 'options', 'job_data' or 'qc_data').
        key (str):         Key written in the file.
        label (str):       Name shown in the form.
        kind (str):        'bool', 'choice', 'int' or 'float'.
        default:           SCOPE's default value (classes_input.fill_*), used when the key is not written.
        shown (str):       How the default is shown ('queue maximum', 'off'…).
        help (str):        Tooltip: what the setting does.
        choices (tuple):   Accepted values of a 'choice' setting.
        when (Callable):   ctx -> bool: whether the setting applies (software, computation type, other settings). None = always.
        detail (bool):     A solver detail, listed only when the user asks for them (or when the file sets it).
    """
    section: str
    key:     str
    label:   str
    kind:    str
    default: object
    shown:   str
    help:    str
    choices: tuple = ()
    when:    "Callable | None" = None
    detail:  bool = False

def _g16(c): return c["software"] == "g16"
def _qe(c):  return c["software"] == "qe"
QE_GEOMETRY = ("opt", "relax", "vc-relax")

## SCOPE's own settings (classes_input.py, classes_workflow.py and the software writers); none depends on the cluster, except the
## time limit (at most the queue's) and, through the user's allocation, max_jobs and max_procs. overwrite_outputs is left out: SCOPE
## reads it but nothing uses it.
OPTIONS = (
    Option("environment", "time_limit", "Time limit, minutes", "int", None, "the queue's maximum",
           "Wall time asked to the scheduler for each job, in minutes. Empty: the maximum of the queue it is sent to. It cannot exceed that "
           "maximum, which is set by the cluster."),
    Option("environment", "max_jobs", "Max. jobs at once", "int", 100, "100",
           "SCOPE stops submitting while you have this many jobs queued or running on the cluster (all your jobs are counted, not only SCOPE's)."),
    Option("environment", "max_procs", "Max. processors at once", "int", 320, "320",
           "SCOPE stops submitting while your queued and running jobs use this many processors. Keep it within your allocation on the cluster."),
    Option("environment", "method", "Queue choice", "choice", "weighted", "weighted",
           "How SCOPE picks among several queues: 'weighted' (free cores × priority / size), 'total' (most free cores) or 'ratio' (largest free "
           "fraction). It matters only when several queues are given.", ("weighted", "total", "ratio")),

    Option("options", "ignore_submitted", "Resubmit queued jobs", "bool", False, "False",
           "True: a job that is already queued or running is written and submitted again. False: SCOPE waits for it."),
    Option("options", "overwrite_inputs", "Rewrite input files", "bool", True, "True",
           "True: input and submission files that already exist are written again from the current settings. False: they are kept."),

    Option("job_data", "job_setup", "Job setup", "choice", "regular", "regular",
           "'regular': one calculation per source. 'rep_opt': repeats the optimization until the energy stops changing. 'findiff': finite "
           "differences (Quantum ESPRESSO 'scf' on a periodic source; the final state must differ from the initial one).", ("regular", "rep_opt", "findiff")),
    Option("job_data", "max_steps", "Max. repetitions", "int", 5, "5", "rep_opt: most optimizations run one after the other.",
           when=lambda c: c["job_setup"] == "rep_opt"),
    Option("job_data", "energy_thres", "Energy threshold, Hartree", "float", 1e-5, "1e-5",
           "rep_opt: the repetitions stop when the energy changes less than this between two of them.", when=lambda c: c["job_setup"] == "rep_opt"),
    Option("job_data", "findiff_displacement", "Displacement", "float", 0.01, "0.01", "findiff: length of each atomic displacement, in the units below.",
           when=lambda c: c["job_setup"] == "findiff"),
    Option("job_data", "findiff_units", "Displacement units", "choice", "bohr", "bohr", "findiff: units of the displacement.", ("bohr", "angstrom"),
           when=lambda c: c["job_setup"] == "findiff"),
    Option("job_data", "save_wf", "Keep the wavefunction", "choice", False, "no",
           "Stores the wavefunction of the calculation: 'job' in this job's folder, 'workflow' in one place shared by the workflow's jobs.", ("job", "workflow")),
    Option("job_data", "recovery", "Recovery strategy", "choice", "standard", "standard",
           "What SCOPE changes to restart a failed Quantum ESPRESSO calculation: 'standard' or 'diverse' (three different attempts). Gaussian has 'standard' only.",
           ("standard", "diverse"), when=_qe),
    Option("job_data", "must_be_good", "Followers need success", "bool", True, "True",
           "True: jobs that wait for this one start only if it ends well. False: they start once it has finished, even if it failed, and SCOPE does not retry it automatically when it fails."),

    Option("qc_data", "unrestricted", "Unrestricted", "bool", False, "False", "Unrestricted calculation (U prefix on the functional).", when=_g16),
    Option("qc_data", "is_grimme", "Dispersion (Grimme)", "bool", False, "False",
           "Adds Grimme's empirical dispersion correction (ignored with wb97xd, which includes it).", when=lambda c: c["software"] in ("g16", "qe")),
    Option("qc_data", "grimme_type", "Dispersion type", "choice", "d3bj", "d3bj", "Version of the correction. d3m and d3mbj exist for Quantum ESPRESSO only.",
           ("d2", "d3", "d3bj", "d3m", "d3mbj"), when=lambda c: c["is_grimme"] is True),
    Option("qc_data", "loose_opt", "Loose convergence", "bool", False, "False", "Optimization with Gaussian's 'loose' criteria (wins over tight).",
           when=lambda c: _g16(c) and c["comp_type"] == "opt"),
    Option("qc_data", "tight_opt", "Tight convergence", "bool", False, "False", "Optimization with 'VeryTight' criteria and the ultrafine grid.",
           when=lambda c: _g16(c) and c["comp_type"] == "opt"),
    Option("qc_data", "ultrafine_grid", "Ultrafine grid", "bool", False, "False", "Integration grid Int=Ultrafine (tight convergence adds it already).",
           when=lambda c: _g16(c) and not (c["tight_opt"] is True and c["comp_type"] == "opt")),
    Option("qc_data", "fctype", "Force constants", "choice", "recalcfc", "recalcfc",
           "How the Hessian is obtained during the optimization: recomputed every N steps (recalcfc), computed at the start (calcfc) or at every step (calcall).",
           ("recalcfc", "calcfc", "calcall"), when=lambda c: _g16(c) and c["comp_type"] in ("opt", "ts")),
    Option("qc_data", "recalc_steps", "Recompute every N steps", "int", 30, "30", "recalcfc: steps between two Hessian calculations.",
           when=lambda c: _g16(c) and c["comp_type"] in ("opt", "ts") and c["fctype"] == "recalcfc"),
    Option("qc_data", "td_type", "Excited states", "choice", "singlets", "singlets", "Spin of the excited states (ignored for open-shell species).",
           ("singlets", "triplets", "50-50"), when=lambda c: _g16(c) and c["comp_type"] in ("td", "tda")),
    Option("qc_data", "td_nstates", "Number of states", "int", 10, "10", "Excited states computed.", when=lambda c: _g16(c) and c["comp_type"] in ("td", "tda")),
    Option("qc_data", "print_forces", "Print forces", "bool", False, "False", "Writes the forces of a single-point (scf) calculation.",
           when=lambda c: c["comp_type"] == "scf"),

    Option("qc_data", "pp_library", "Pseudopotentials", "choice", "vanderbilt", "vanderbilt",
           "Library of pseudopotentials. 'efficiency' and 'precision' (SSSP) must be installed in SCOPE's PP_Libraries folder where the jobs run.",
           ("vanderbilt", "efficiency", "precision"), when=_qe),
    Option("qc_data", "is_hubbard", "Hubbard U", "bool", False, "False", "Adds a Hubbard U term (DFT+U).", when=_qe),
    Option("qc_data", "uterm", "U value, eV", "float", 2.35, "2.35", "Value of the Hubbard U.", when=lambda c: _qe(c) and c["is_hubbard"] is True),
    Option("qc_data", "version", "QE version", "float", 7.0, "7.0", "Version of Quantum ESPRESSO on the cluster; it decides how the Hubbard term is written.",
           when=lambda c: _qe(c) and c["is_hubbard"] is True),
    Option("qc_data", "elec_conv", "SCF convergence, Ry", "float", 1e-8, "1e-8", "conv_thr of the SCF cycle.", when=_qe, detail=True),
    Option("qc_data", "elec_maxstep", "SCF max. steps", "int", 200, "200", "electron_maxstep.", when=_qe, detail=True),
    Option("qc_data", "mix_beta", "Mixing beta", "float", 0.7, "0.7", "mixing_beta of the SCF cycle; lower it when the SCF oscillates.", when=_qe, detail=True),
    Option("qc_data", "mix_ndim", "Mixing dimension", "int", 8, "8", "mixing_ndim.", when=_qe, detail=True),
    Option("qc_data", "forc_conv", "Force convergence, Ry/Bohr", "float", 1e-4, "1e-4", "forc_conv_thr of the optimization.",
           when=lambda c: _qe(c) and c["comp_type"] in QE_GEOMETRY),
    Option("qc_data", "opt_maxstep", "Optimization max. steps", "int", 100, "100", "nstep of the optimization.", when=lambda c: _qe(c) and c["comp_type"] in QE_GEOMETRY),
    Option("qc_data", "ion_dynamics", "Ion dynamics", "choice", "bfgs", "bfgs", "ion_dynamics.", ("bfgs", "damp"),
           when=lambda c: _qe(c) and c["comp_type"] in QE_GEOMETRY, detail=True),
    Option("qc_data", "bfgs_ndim", "BFGS history", "int", 1, "1", "bfgs_ndim.", when=lambda c: _qe(c) and c["comp_type"] in QE_GEOMETRY, detail=True),
    Option("qc_data", "trust_rad_ini", "Initial trust radius, Bohr", "float", 0.1, "0.1", "trust_radius_ini.", when=lambda c: _qe(c) and c["comp_type"] in QE_GEOMETRY, detail=True),
    Option("qc_data", "trust_rad_min", "Minimum trust radius, Bohr", "float", 1e-6, "1e-6", "trust_radius_min.", when=lambda c: _qe(c) and c["comp_type"] in QE_GEOMETRY, detail=True),
    Option("qc_data", "upscale", "Upscale", "int", 100, "100", "upscale (tightens the SCF threshold near convergence).", when=lambda c: _qe(c) and c["comp_type"] in QE_GEOMETRY, detail=True),
    Option("qc_data", "pressure", "Pressure, kbar", "float", 0, "0", "Target pressure of the variable-cell relaxation.", when=lambda c: _qe(c) and c["comp_type"] == "vc-relax"),
    Option("qc_data", "cell_dynamics", "Cell dynamics", "choice", "bfgs", "bfgs", "cell_dynamics.", ("bfgs", "damp-pr", "damp-w"),
           when=lambda c: _qe(c) and c["comp_type"] == "vc-relax", detail=True),
)
OPTION = {(o.section, o.key): o for o in OPTIONS}

def option_value(option: Option, raw: str):
    """The value SCOPE reads from `raw` (as written after '='), or raises ValueError when it is not one the option accepts.
    Strings are compared in lower case, as SCOPE lowers them."""
    import ast
    raw = str(raw).strip()
    if option.kind == "int":
        if not re.fullmatch(r"[+-]?\d+", raw): raise ValueError(f"{option.label} ({option.key}): '{raw}' is not a whole number.")
        return int(raw)
    if option.kind == "float":
        try: value = float(raw)
        except ValueError: raise ValueError(f"{option.label} ({option.key}): '{raw}' is not a number.") from None
        if value != value or value in (float("inf"), float("-inf")): raise ValueError(f"{option.label} ({option.key}): '{raw}' is not a finite number.")
        return int(value) if re.fullmatch(r"[+-]?\d+", raw) else value
    try: value = ast.literal_eval(raw)
    except Exception: value = raw
    if isinstance(value, str): value = value.strip().lower()
    accepted = (True, False) if option.kind == "bool" else option.choices
    if not any(value is a if isinstance(a, bool) else value == a for a in accepted):
        raise ValueError(f"{option.label} ({option.key}): '{raw}' is not one of {', '.join(map(str, accepted))}.")
    return value

def option_context(software: str, comp_type: str, settings: "dict | None") -> dict:
    """What the conditions of OPTIONS look at: software, computation type, and every option's value (SCOPE's default when not set or
    not readable)."""
    ctx = {"software": software, "comp_type": comp_type}
    for o in OPTIONS:
        raw = (settings or {}).get(o.section, {}).get(o.key, "")
        try: ctx[o.key] = option_value(o, raw) if str(raw).strip() else o.default
        except ValueError: ctx[o.key] = o.default
    return ctx

def applies(option: Option, ctx: dict) -> bool:
    return option.when is None or bool(option.when(ctx))

def option_problems(software: str, comp_type: str, settings: "dict | None") -> list:
    """The values of the option fields that SCOPE would refuse or misread, and combinations it cannot run. Options that do not apply
    are not checked (they are not written)."""
    ctx, problems = option_context(software, comp_type, settings), []
    for o in OPTIONS:
        raw = str((settings or {}).get(o.section, {}).get(o.key, "")).strip()
        if raw and applies(o, ctx):
            try: option_value(o, raw)
            except ValueError as exc: problems.append(str(exc))
    def given(key): return any(str((settings or {}).get(o.section, {}).get(key, "")).strip() for o in OPTIONS if o.key == key)
    if ctx["job_setup"] == "findiff" and (software != "qe" or comp_type != "scf"):
        problems.append("Finite differences (job_setup = 'findiff') need Quantum ESPRESSO with computation type 'scf', on a periodic source.")
    if software == "g16" and ctx["is_grimme"] is True and ctx["grimme_type"] in ("d3m", "d3mbj"):
        problems.append(f"Gaussian has no '{ctx['grimme_type']}' dispersion: use d2, d3 or d3bj.")
    if software == "g16" and comp_type == "opt" and ctx["loose_opt"] is True and ctx["tight_opt"] is True and given("loose_opt") and given("tight_opt"):
        problems.append("Loose and tight convergence are both on: SCOPE uses loose. Choose one.")
    for key in ("time_limit", "max_jobs", "max_procs", "max_steps", "td_nstates", "recalc_steps", "elec_maxstep", "opt_maxstep", "mix_ndim", "bfgs_ndim"):
        if given(key) and isinstance(ctx[key], int) and ctx[key] <= 0 and applies(next(o for o in OPTIONS if o.key == key), ctx):
            problems.append(f"{next(o.label for o in OPTIONS if o.key == key)} ({key}) must be at least 1.")
    return problems

def parse_sections(text: str) -> dict:
    """Reads the raw `key = value` pairs of each &section of an input file, keeping order and the value text as written.

    Comments (after '#') and blank lines are dropped. Unknown sections are ignored. Values stay strings.
    """
    sections, current = {s: {} for s in SECTIONS}, None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("&"): current = stripped[1:].split()[0] if stripped[1:].split() else None; continue
        if stripped.startswith("/"): current = None; continue
        data = stripped.split("#")[0]
        if current in sections and data.count("=") >= 1:
            key, value = data.split("=", 1)
            if key.strip(): sections[current][key.strip()] = value.strip()
    return sections

def render_sections(sections: dict) -> str:
    """Writes sections as a Scope input file, with the '=' aligned inside each section."""
    out = []
    for name in SECTIONS:
        items = sections.get(name, {})
        out.append(f"&{name}")
        width = max((len(k) for k in items), default=0)
        out.extend(f"   {k:<{width}} = {v}" for k, v in items.items())
        out.append("/\n")
    return "\n".join(out)

def py_value(value) -> str:
    """Formats a Python value the way Scope input files are written: quoted strings, bare numbers and booleans, bracketed lists."""
    if isinstance(value, bool):  return "True" if value else "False"
    if isinstance(value, (list, tuple)): return "[" + ", ".join(py_value(v) for v in value) + "]"
    if isinstance(value, (int, float)): return repr(value)
    return "'" + str(value).replace("'", "") + "'"

def split_names(text: str) -> list:
    """Splits 'a, b  c' into ['a', 'b', 'c']."""
    return [n for n in re.split(r"[,\s]+", text.strip()) if n]

def build_sections(branch: str, workflow: str, job: str, requisites: str, constrains: str, software: str, comp_type: str, functional: str, basis: str, procs: int, want_submit: bool, queue: str="", extras: dict=None,
                   istate: str="", fstate: str="", settings: dict=None) -> dict:
    """Builds the four sections from the form values.

    workflow, requisites and constrains accept several names separated by commas or spaces (one name stays a plain
    string, several become a list). basis is written only for Gaussian 16. want_submit is always written, because
    SCOPE assumes True when it is missing. istate and fstate are written when given (SCOPE's defaults are 'initial' and
    the job name). settings maps a section to {key: value as written} for the option fields (OPTIONS): an empty value is
    not written (SCOPE's default), and neither is an option that does not apply (for instance a Gaussian setting once the
    software is Quantum ESPRESSO). extras maps a section to raw `key = value` text; those keys are added after the form
    keys and replace them if they repeat one.
    """
    names, req, con = split_names(workflow), split_names(requisites), split_names(constrains) or ["self"]
    states = {k: py_value(v.strip()) for k, v in (("istate", istate), ("fstate", fstate)) if v and v.strip()}
    sections = {
        "environment": {"requested_procs": str(int(procs))},
        "options":     {"want_submit": py_value(bool(want_submit))},
        "job_data":    {"branch": py_value(branch.strip()), "workflow": py_value(names[0] if len(names) == 1 else names), "job": py_value(job.strip()), **states, "hierarchy": "1", "requisites": py_value(req), "constrains": py_value(con)},
        "qc_data":     {"software": py_value(software), "comp_type": py_value(comp_type), "functional": py_value(functional.strip() or "pbe")},
    }
    if queue.strip(): sections["environment"]["queue"] = py_value(queue.strip())
    if software == "g16" and basis.strip(): sections["qc_data"]["basis"] = py_value(basis.strip())
    ctx = option_context(software, comp_type, settings)
    for o in OPTIONS:
        raw = str((settings or {}).get(o.section, {}).get(o.key, "")).strip()
        if raw and applies(o, ctx): sections[o.section][o.key] = raw
    for name, text in (extras or {}).items():
        for key, value in parse_sections(f"&{name}\n{text}\n/").get(name, {}).items(): sections[name][key] = value
    return sections

def _literal(raw: str):
    import ast
    try: return ast.literal_eval(raw)
    except Exception: return raw.strip("'\"")

def sections_to_form(sections: dict) -> tuple:
    """Maps the sections of an existing file to the form fields; every key the form has no field for goes to extras.

    An option of OPTIONS gets its field (form['settings'], value kept as written) when it applies to this file and its value is one
    the field can show; otherwise it stays in extras, so nothing of the file is lost or reinterpreted.

    Returns:
        tuple: (form dict with the build_sections arguments, extras dict section -> text).
    """
    def get(section, key, default=""): return _literal(sections.get(section, {}).get(key, "")) if key in sections.get(section, {}) else default
    def names(value): return ", ".join(value) if isinstance(value, (list, tuple)) else str(value)
    queue = get("environment", "queue", get("environment", "queues", ""))
    form  = {"branch": str(get("job_data", "branch")), "workflow": names(get("job_data", "workflow", "*")), "job": str(get("job_data", "job")), "requisites": names(get("job_data", "requisites", [])), "constrains": names(get("job_data", "constrains", ["self"])),
             "istate": str(get("job_data", "istate", "")), "fstate": str(get("job_data", "fstate", "")),
             "software": str(get("qc_data", "software", "g16")), "comp_type": str(get("qc_data", "comp_type", "scf")), "functional": str(get("qc_data", "functional", "pbe")), "basis": str(get("qc_data", "basis", "")),
             "procs": int(get("environment", "requested_procs", 4)) if str(get("environment", "requested_procs", 4)).isdigit() else 4, "want_submit": get("options", "want_submit", True) is True, "queue": str(queue)}
    raw_settings = {name: {k: v for k, v in sections.get(name, {}).items() if (name, k) in OPTION} for name in SECTIONS}
    ctx, settings = option_context(form["software"], form["comp_type"], raw_settings), {name: {} for name in SECTIONS}
    for name in SECTIONS:
        for k, v in raw_settings[name].items():
            try: option_value(OPTION[(name, k)], v); readable = True
            except ValueError: readable = False
            if readable and applies(OPTION[(name, k)], ctx): settings[name][k] = v
    form["settings"] = settings
    extras = {}
    for name in SECTIONS:
        lines = [f"{k} = {v}" for k, v in sections.get(name, {}).items() if k not in FORM_KEYS[name] and k not in settings[name] and not (name == "job_data" and k == "hierarchy" and v == "1")]
        extras[name] = "\n".join(lines)
    return form, extras

NEXT_TYPE = {"opt": "freq", "ts": "freq", "relax": "freq", "vc-relax": "freq"}         ## what usually follows a geometry job

def followup_form(report: "InputReport", reports: list=()) -> tuple:
    """The input form for a new job that runs after `report`'s job, as (form, extras): same branch, sources, software, method, resources,
    queue and submission; requisites = that job; a job type that usually follows it (freq after a geometry job, else scf) and a name not
    used yet in the branch. istate and fstate are left empty so the editor fills them from the requisite (istate = the state that job
    writes). Settings of the &qc_data, &environment and &options tabs are copied; those of &job_data (job_setup, max_steps…) are not,
    because they describe that job only."""
    with open(report.path) as fh: form, extras = sections_to_form(parse_sections(fh.read()))
    kind = NEXT_TYPE.get(report.comp_type, "scf")
    if kind not in SOFTWARE_TYPES.get(form["software"], [kind]): kind = SOFTWARE_TYPES[form["software"]][0]
    taken = {r.job for r in reports if r.ok and r.branch == report.branch}
    name = kind if kind not in taken else next(f"{kind}{i}" for i in range(2, 1000) if f"{kind}{i}" not in taken)
    form.update(job=name, comp_type=kind, requisites=report.job, constrains="self", istate="", fstate="")
    extras["job_data"] = ""; form["settings"]["job_data"] = {}
    return form, extras

@dataclass
class Link:
    """What linking job A before job B changes in B's input file (see link_jobs). Nothing is written until the caller saves new_text."""
    path:     str
    old_text: str
    new_text: str
    notes:    list

    @property
    def diff(self) -> list:
        """The settings that change, one per line: `~ key: old → new`, `+ key = value` (added) or `- key = value` (removed), with its section.
        Settings are compared, not lines, so the realignment of a rewritten file is not reported as a change."""
        old, new = parse_sections(self.old_text), parse_sections(self.new_text); out = []
        for sec in SECTIONS:
            for k in dict.fromkeys([*old.get(sec, {}), *new.get(sec, {})]):
                a, b = old.get(sec, {}).get(k), new.get(sec, {}).get(k)
                if a == b: continue
                out.append(f"+ {k} = {b}   (&{sec})" if a is None else f"- {k} = {a}   (&{sec})" if b is None else f"~ {k}: {a}  →  {b}   (&{sec})")
        return out

def link_jobs(a: InputReport, b: InputReport, reports: list, sources: "list | None"=None, b_text: "str | None"=None) -> Link:
    """Makes job B wait for job A and start from A's result: A is added to B's requisites and B's istate becomes the state A writes
    (B's fstate follows when B adds its results to the state it reads, as a freq or scf job does). Refuses, with the reason, what SCOPE
    could not follow: jobs of different branches or of sources that never meet, a job linked to itself, a link already there, or one
    that would close a cycle. When B already waits for a job whose result it starts from, that stays its initial state: only the timing
    changes (a job reads one state). b_text is B's current text when it differs from the file (a chain changes files one after another
    in memory). Returns the new text of B's file for a preview; the file itself is not touched."""
    import networkx as nx
    if not (a.ok and b.ok): raise ValueError("Both input files must be valid first.")
    if a.path == b.path or a.node == b.node: raise ValueError("A job cannot wait for itself.")
    if a.branch != b.branch: raise ValueError(f"'{a.job}' is in branch '{a.branch}' and '{b.job}' in branch '{b.branch}'. SCOPE only waits for jobs of the same branch: give both the same branch first.")
    if selectors_overlap(a.selectors, b.selectors, sources) is False: raise ValueError(f"'{a.job}' runs on sources '{a.workflow_label}' and '{b.job}' on '{b.workflow_label}': no source runs both, and SCOPE only waits for a job of the same source.")
    if a.job in b.requisites: raise ValueError(f"'{b.job}' already waits for '{a.job}'.")
    if a.job == b.job: raise ValueError(f"Both jobs are called '{a.job}': SCOPE would read it as the job waiting for itself. Rename one first.")
    _, edges, _ = build_graph(reports, sources)
    graph = nx.DiGraph(); graph.add_edges_from((x, y) for x, y, k in edges if k == "requisite")
    if b.node in graph and a.node in graph and nx.has_path(graph, b.node, a.node): raise ValueError(f"'{a.job}' already waits (directly or through other jobs) for '{b.job}': this link would make a cycle, and neither could start.")
    if b_text is None:
        with open(b.path) as fh: old = fh.read()
    else: old = b_text
    form, extras = sections_to_form(parse_sections(old))
    form["requisites"] = ", ".join(split_names(form["requisites"]) + [a.job])
    feeding = [q for n in b.requisites for q in related(b, n, reports, sources) if b.istate in (q.fstate, geometry_state(q))]
    start = geometry_state(a)
    if feeding:                                                                ## B already starts from another requisite's result: keep it
        notes = [f"'{b.job}' will also wait for '{a.job}' (requisite). It keeps starting from '{b.istate}', the result of '{feeding[0].job}': a job reads one state."]
        form["istate"], form["fstate"] = b.istate, b.fstate
        updates_own = False
    else:
        notes = [f"'{b.job}' will start only after '{a.job}' has finished (requisite), and from the state '{start}' (it read '{b.istate}' before)."]
        if start != a.fstate: notes.append(f"'{a.job}' writes its results into '{a.fstate}', a state without a geometry, so '{b.job}' starts from '{start}', the geometry '{a.job}' used.")
        ## B adds its results to the state it starts from when it already did so, or when it is a freq job still writing SCOPE's default
        ## state (its own name): frequencies belong on the geometry they were computed for (thermochemistry needs both on one state)
        updates_own = b.comp_type not in GEOMETRY_TYPES and (b.fstate == b.istate or (b.comp_type == "freq" and b.fstate == b.job))
        form["istate"] = start
        form["fstate"] = start if updates_own else b.fstate
    if updates_own and b.fstate != start: notes.append(f"'{b.job}' adds its results to the state it reads, so it now writes into '{start}' too.")
    if not feeding and b.istate != "initial" and b.istate != start: notes.append(f"Its previous initial state '{b.istate}' is replaced.")
    if "#" in old: notes.append("Comments in the file are not kept (the file is written again from its settings).")
    new = render_sections(build_sections(**form, extras=extras))
    check = read_input_text(new)
    if not check.ok: raise ValueError(f"SCOPE would not accept the changed file: {check.error}")
    return Link(b.path, old, new, notes)

def chain_order(reports: list, sources: "list | None"=None) -> list:
    """A proposed order for jobs to chain: jobs already linked keep their order in the pipeline (column of the graph); otherwise the
    order of the table, which is the order the files were added."""
    nodes, edges, _ = build_graph(reports, sources); place = layout_graph(nodes, edges)
    return [r for _, _, r in sorted((place.get(r.node, (0, 0))[0], i, r) for i, r in enumerate(reports))]

def link_chain(chain: list, reports: list, sources: "list | None"=None) -> list:
    """Links jobs in sequence: each waits for the one before it and starts from its result (A → B → C …), with the checks of link_jobs
    for every pair. Files are changed in memory one after another, so a later link sees the earlier ones (a cycle through the chain is
    refused too). Returns one Link per changed file, in chain order; nothing is written. Raises ValueError naming the pair that cannot be linked."""
    if len(chain) < 2: raise ValueError("Choose at least two jobs to chain.")
    if len({r.path for r in chain}) != len(chain): raise ValueError("A job appears twice in the chain.")
    current = {r.path: r for r in reports}; texts, links = {}, {}
    for a, b in zip(chain, chain[1:]):
        a, b = current[a.path], current[b.path]
        if a.job in b.requisites and b.branch == a.branch: continue                  ## already linked: nothing to change for this pair
        try: change = link_jobs(a, b, list(current.values()), sources, texts.get(b.path))
        except ValueError as exc: raise ValueError(f"'{a.job}' → '{b.job}': {exc}")
        first = links.get(b.path)
        links[b.path] = Link(b.path, first.old_text if first else change.old_text, change.new_text, (first.notes if first else []) + change.notes)
        texts[b.path] = change.new_text
        updated = read_input_text(change.new_text); updated.path = b.path; current[b.path] = updated
    return [links[r.path] for r in chain if r.path in links]

def form_problems(branch: str, job: str, workflow: str, procs: int, requisites: str="") -> list:
    """Checks that SCOPE's own validation does not cover: names used for folders and files, an empty workflow, and a job that requires itself."""
    problems = []
    if job.strip() and job.strip().lower().replace("-", "_") in [r.lower().replace("-", "_") for r in split_names(requisites)]: problems.append(f"Requisites contains '{job.strip()}', the job itself. SCOPE accepts this but the job would wait for itself and never run. Requisites are the jobs that must finish BEFORE this one (for instance 'opt' for a 'freq' job).")
    for label, value in (("Branch", branch.strip()), ("Job", job.strip())):
        if not value: problems.append(f"{label} is empty.")
        elif not SAFE_NAME.match(value): problems.append(f"{label} '{value}': use letters, digits, '_', '-' or '.', with no spaces (it becomes part of folder and file names).")
    if not split_names(workflow): problems.append("Workflow is empty: use '*' for every source, a name, or a pattern such as 'water*'.")
    if procs < 1: problems.append("Processors must be at least 1.")
    return problems

def validate_form(**values) -> tuple:
    """Renders the form and validates it with SCOPE's own input functions.

    Returns:
        tuple: (text, InputReport, problems). The text can be saved when the report is ok and problems is empty.
    """
    text = render_sections(build_sections(**values))
    problems = form_problems(values["branch"], values["job"], values["workflow"], values["procs"], values.get("requisites", ""))
    problems += option_problems(values["software"], values["comp_type"], values.get("settings"))
    return text, read_input_text(text), problems

def related(r: InputReport, name: str, reports: list, sources: "list | None"=None) -> list:
    """The loaded jobs that `name` in r's requisites or constrains can mean: same branch, that job name, and a workflow that can pick a
    source r also runs on. SCOPE checks requisites inside one Workflow (one source), so a job of another workflow never counts."""
    return [q for q in reports if q.ok and q is not r and q.branch == r.branch and q.job == name and selectors_overlap(q.selectors, r.selectors, sources) is not False]

def build_graph(reports: list, sources: "list | None"=None) -> tuple:
    """Builds the pipeline graph from valid input reports.

    Nodes are 'branch/workflow/job' (InputReport.node). Edges are (from, to, kind): kind 'requisite' (from must finish before to) or
    'constrain' (from blocks to), drawn only between jobs whose workflows can share a source. Names that no loaded file defines are
    added as nodes with kind 'missing'. `sources` (the source names of the chosen system) makes the workflow overlap exact.

    Returns:
        tuple: (nodes, edges, cycles). nodes is a dict node -> kind ('job' or 'missing'); cycles is a list of cycles.
    """
    import networkx as nx
    nodes = {r.node: "job" for r in reports if r.ok}
    edges = []
    for r in reports:
        if not r.ok: continue
        for kind, names in (("requisite", r.requisites), ("constrain", r.constrains)):
            for name in names:
                if name == "self" or name == r.job: continue
                found = related(r, name, reports, sources)
                if not found:
                    ghost = f"{r.branch}/{r.workflow_label}/{name}"
                    nodes.setdefault(ghost, "missing"); found_nodes = [ghost]
                else: found_nodes = list(dict.fromkeys(q.node for q in found))
                edges += [(n, r.node, kind) for n in found_nodes if (n, r.node, kind) not in edges]
    graph = nx.DiGraph(); graph.add_nodes_from(nodes); graph.add_edges_from((a, b) for a, b, k in edges if k == "requisite")
    cycles = list(nx.simple_cycles(graph))
    return nodes, edges, cycles

def state_graph(reports: list, sources: "list | None"=None) -> tuple:
    """The pipeline as SCOPE's manuscript draws it: jobs and the States they read and write.

    Returns (nodes, edges, cycles). nodes maps an id to (kind, label): kind 'job', 'missing' (a requisite no file defines), 'state' (written
    by a loaded job) or 'given' (read but written by no loaded job: 'initial', or a state that must already be in the system). Edges are
    (from, to, kind): 'reads' (state -> job, istate), 'writes' (job -> state, fstate), 'requisite' and 'constrain' (job -> job, timing only).
    A state is one name on the sources of a workflow; readers are joined to the writer of that name whose workflow overlaps theirs.
    """
    jobs, edges, cycles = build_graph(reports, sources)
    nodes = {n: (kind, n.rsplit("/", 1)[-1]) for n, kind in jobs.items()}
    ok, writers = [r for r in reports if r.ok], {}
    for r in ok:
        if r.fstate == r.istate: continue                                     ## adds results to the state it reads: drawn as 'updates' below
        sid = f"state:{r.workflow_label}:{r.fstate}"; nodes[sid] = ("state", r.fstate)
        writers.setdefault(r.fstate, []).append((r, sid)); edges.append((r.node, sid, "writes"))
    for r in ok:
        found = [sid for w, sid in writers.get(r.istate, []) if w is not r and selectors_overlap(w.selectors, r.selectors, sources) is not False]
        if not found:
            sid = f"state:given:{r.istate}"                                   ## one pill per name ('initial' is where every source starts)
            if sid not in nodes: nodes[sid] = ("given", r.istate)
            found = [sid]
        for sid in dict.fromkeys(found):
            edges.append((sid, r.node, "reads"))
            if r.fstate == r.istate: edges.append((r.node, sid, "updates"))  ## not a forward edge: the state stays left of the job
    return nodes, edges, cycles

def missing_requisite(r: InputReport, name: str, ok: list, sources: "list | None"=None) -> str:
    """Why requisite `name` of r matches no loaded job, in the words a newcomer needs: a state name written where a job name belongs,
    a job of another branch, or a job of other sources (SCOPE only waits for jobs of the same branch and the same source)."""
    if name == r.fstate:
        return (f"{r.node} requires '{name}', but that is the state this job writes itself, not a job. Requisites are JOB names (the job to wait for); "
                "states go in istate/fstate. Leave requisites empty if nothing must finish first.")
    elsewhere = [q for q in ok if q is not r and q.job == name and q.branch != r.branch]          ## a job of that name first: a job's default state has the same name
    if elsewhere:
        q = elsewhere[0]
        return (f"{r.node} requires '{name}', which is a job of branch '{q.branch}' ({os.path.basename(q.path)}), not of branch '{r.branch}'. SCOPE only waits for jobs of the same "
                f"branch and the same source: put both jobs in one branch.")
    writers = [q for q in ok if q is not r and q.fstate == name and not any(x.job == name for x in ok)]
    if writers:
        w = writers[0]
        return (f"{r.node} requires '{name}', but that is a state (written by job '{w.job}' in {os.path.basename(w.path)}), not a job. Requisites are JOB names: "
                f"write requisites = ['{w.job}'] and istate = '{name}' to start from its result.")
    other = [q for q in ok if q is not r and q.job == name and q.branch == r.branch]
    if other:
        q = other[0]
        return (f"{r.node} requires '{name}', but '{name}' runs on other sources ({q.workflow_label}) than this job ({r.workflow_label}). SCOPE only waits for a job of the same source: "
                "make the workflows overlap.")
    return f"{r.node} requires '{name}', which none of the loaded files defines for these sources. It must already exist in the system or this job never starts."

def pipeline_issues(reports: list, sources: "list | None"=None) -> list:
    """Finds problems that only show when the input files are looked at together.

    Returns a list of (path, message): a job that requires itself, a requisite no loaded file defines, two files that define the same
    job for the same sources, cycles of requisites, a job that waits for another one but reads a different state than the one it
    writes, and two branches writing one state of the same sources. These are warnings: SCOPE itself accepts all of them.
    """
    issues = []
    nodes, edges, cycles = build_graph(reports, sources)
    ok = [r for r in reports if r.ok]
    for i, r in enumerate(ok):
        if r.job in [q.replace("-", "_").replace(" ", "_") for q in r.requisites]: issues.append((r.path, f"{r.node} lists itself as a requisite, so it would never start."))
        for q in ok[:i]:
            if q.branch == r.branch and q.job == r.job and selectors_overlap(q.selectors, r.selectors, sources):
                issues.append((r.path, f"{r.node} is also defined in {os.path.basename(q.path)} for the same sources ({q.workflow_label}); the last file read wins."))
        for name in r.requisites:
            if name == r.job: continue
            found = related(r, name, reports, sources)
            if not found: issues.append((r.path, missing_requisite(r, name, ok, sources))); continue
            produced = {q.fstate for q in found} | {geometry_state(q) for q in found}
            if r.istate not in produced and not any(r.istate in (x.fstate, geometry_state(x)) for n in r.requisites for x in related(r, n, reports, sources)):
                state = geometry_state(found[0])
                issues.append((r.path, f"{r.node} waits for '{name}' (which writes state '{state}') but reads state '{r.istate}'. Requisites only decide WHEN a job starts, not which geometry it uses: set istate = '{state}' to start from the result of '{name}'."))
        if r.istate != "initial" and not any(q.fstate == r.istate and selectors_overlap(q.selectors, r.selectors, sources) is not False for q in ok if q is not r):
            issues.append((r.path, f"{r.node} reads state '{r.istate}', which none of the loaded jobs writes. It must already exist in the system, or the job waits."))
        for q in ok[:i]:
            if q.branch != r.branch and q.fstate == r.fstate and selectors_overlap(q.selectors, r.selectors, sources):
                issues.append((r.path, f"{r.node} and {q.node} (in {os.path.basename(q.path)}) both write state '{r.fstate}' of the same sources. States belong to the source, not to the branch, so one overwrites the other: give one of them another fstate."))
    for cycle in cycles: issues.append(("", "Cycle of requisites: " + " -> ".join(cycle) + ". None of these jobs can start."))
    return issues

FORWARD = ("requisite", "reads", "writes")                         ## edges that place their end to the right of their start

def layout_graph(nodes: dict, edges: list) -> dict:
    """Assigns each node a (column, row): column is the longest chain of requisites (and, in a state graph, of reads and writes) before it, rows are numbered per column."""
    depth = {n: 0 for n in nodes}
    for _ in range(len(nodes)):                                   ## bounded relaxation: stays finite even if there is a cycle
        changed = False
        for a, b, kind in edges:
            if kind in FORWARD and depth[b] < depth[a] + 1: depth[b] = depth[a] + 1; changed = True
        if not changed: break
    ## rows: each column is ordered by the mean row of the nodes it is linked to (barycentre method, a few sweeps left to right and back),
    ## so a job sits next to the states it reads and writes and arrows rarely cross; ties are broken by name
    cols = {}
    for n in sorted(nodes, key=lambda n: (depth[n], n)): cols.setdefault(depth[n], []).append(n)
    pos = {n: i for c in cols.values() for i, n in enumerate(c)}
    linked = [(a, b) for a, b, kind in edges if kind in FORWARD + ("constrain", "updates") and a in depth and b in depth and depth[a] != depth[b]]
    before = {n: [a if depth[a] < depth[b] else b for a, b in linked if n in (a, b) and max(depth[a], depth[b]) == depth[n]] for n in nodes}
    after  = {n: [b if depth[a] < depth[b] else a for a, b in linked if n in (a, b) and min(depth[a], depth[b]) == depth[n]] for n in nodes}
    for sweep in range(4):
        forward = sweep % 2 == 0; near = before if forward else after
        for c in sorted(cols, reverse=not forward):
            mean = lambda n: sum(pos[m] for m in near[n]) / len(near[n]) if near[n] else pos[n]
            cols[c].sort(key=lambda n: (mean(n), n))
            for i, n in enumerate(cols[c]): pos[n] = i
    return {n: (depth[n], pos[n]) for n in nodes}

###########
### Run ###
###########
def build_run_command(env_path: str, system: str, inputs: list, quiet: bool=False, verbose: bool=False, errors: bool=False) -> tuple:
    """Prepares `scope run` for a separate process.

    The same Python that runs the GUI is used, so the child sees the same SCOPE installation. Returns (program, args).
    """
    args = ["-c", "from scope.cli.main import main; main()", "run", "-n", os.path.abspath(env_path), "-s", system, "-i", *[os.path.abspath(i) for i in inputs]]
    if quiet:   args.append("-q")
    if verbose: args.append("-v")
    if errors:  args.append("-e")
    return sys.executable, args

def child_environment() -> dict:
    """Environment variables for the child process: unbuffered output (live log) and TERM set (clear_screen needs it)."""
    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"
    env["TERM"]             = "dumb"
    return env

def queue_problems(info: EnvInfo, reports: list) -> list:
    """Lists queue names in the inputs that are not exactly available in the environment.

    SCOPE asks a Y/N question on an approximate match (for instance 'shor' for 'short'), which cannot be answered
    when the GUI runs it, so the run would stop with EOFError. Exact names (or the alternative names SCOPE stored)
    never prompt. Local environments have no queues and are skipped.
    """
    if info is None or info.scheduler == "local": return []
    return [f"{os.path.basename(r.path)}: queue '{q}' is not one of {info.queues}" for r in reports if r.ok for q in r.queues if q not in info.queues]

@dataclass
class ReviewRow:
    """One job as it will run, for the review table shown where Run is pressed.

    Attributes:
        level (str):     'ok', 'warn' (look at it) or 'err' (it will not run as meant).
        problems (list): Plain sentences; the first is shown in the table, all in the tooltip.
    """
    file:      str
    job:       str
    where:     str
    kind:      str
    states:    str
    waits_for: str
    procs:     str
    queue:     str
    submits:   str
    level:     str
    problems:  list

def review_rows(reports: list, scheduler: str="", queues: "list | None"=None, sources: "list | None"=None, extra: "dict | None"=None) -> list:
    """Every input file as it will run, with what needs a look, for the review before Run (here or on a cluster).

    scheduler and queues are those of the environment that runs the jobs ('' and None when unknown, for instance a cluster not tested
    yet). extra maps a file path to more messages (missing software on the cluster). Queue names are checked exactly (SCOPE would ask a
    question on a near match, which a run started by this window cannot answer); want_submit is shown as what it will do there."""
    issues = {}
    for path, message in pipeline_issues(reports, sources): issues.setdefault(path, []).append(message)
    rows = []
    for r in reports:
        name = os.path.basename(r.path)
        if not r.ok:
            rows.append(ReviewRow(name, "", "", "", "", "", "", "", "", "err", [f"SCOPE does not accept this file: {r.error}"])); continue
        errs, warns = [], list(issues.get(r.path, [])) + list((extra or {}).get(r.path, []))
        if scheduler and scheduler != "local" and queues is not None:
            errs += [f"Queue '{q}' is not a queue of this environment ({', '.join(queues) or 'none'}): SCOPE would stop to ask, and the run cannot answer." for q in r.queues if q not in queues]
        if not scheduler: submits = "yes" if r.want_submit else "no"
        elif scheduler == "local": submits = "no (local: nothing is submitted)"
        else: submits = "YES, to " + scheduler if r.want_submit else "no (want_submit = False)"
        rows.append(ReviewRow(name, r.job, f"{r.branch} · {r.workflow_label}", f"{r.software} {r.comp_type}", f"{r.istate} → {r.fstate}", ", ".join(r.requisites) or "—",
                              str(r.procs), ", ".join(r.queues) or "—", submits, "err" if errs else ("warn" if warns else "ok"), errs + warns))
    return rows

def submission_warning(info: EnvInfo, reports: list) -> str:
    """Returns a warning if running these inputs on this environment can submit jobs, or '' otherwise.

    SCOPE submits when want_submit is true, and the default is true when the &options section does not say otherwise.
    """
    if info is None or info.scheduler == "local": return ""
    risky = [r for r in reports if r.ok and r.want_submit]
    if not risky: return ""
    return f"Scheduler '{info.scheduler}': {len(risky)} input file(s) have want_submit=True (the default). Running will submit jobs."


#####################
### This computer ###
#####################
LOCAL_PROBE = r'''
import json, os, sys
from importlib import metadata
def version(name):
    try: return metadata.version(name)
    except Exception: return ""
out = {"python": sys.version.split()[0], "executable": sys.executable, "scope_dist": version("scope-qc"), "cell2mol": version("cell2mol"), "rdkit": version("rdkit"), "networkx": version("networkx"), "pyside6": version("PySide6-Essentials") or version("PySide6")}
try:
    import scope, scope.cli.main
    out["scope_version"], out["scope_file"] = scope.__version__, scope.__file__
except Exception as exc:
    out["import_error"] = f"{type(exc).__name__}: {exc}"
print("__LOCAL_SCOPE__" + json.dumps(out))
'''

@dataclass
class LocalScope:
    """What the GUI found out about SCOPE on this computer, by asking the same Python that starts `scope run`.

    Attributes:
        runs_ok (bool):      Whether `import scope.cli.main` works in that Python, which is what every run needs.
        scope_version (str): Version of the installed scope-qc ('' if it cannot be imported).
        editable (bool):     True when SCOPE is imported from a source folder (a development install) rather than from site-packages.
        cli_path (str):      The `scope` command found on the PATH of this window ('' if none). A Terminal needs it; this window does not, so it only appears in the details.
        cli_same_env (bool): Whether that command belongs to the same Python environment as this window.
        python_ok (bool):    Whether this is Python 3.12, the only version SCOPE supports.
    """
    python:        str  = ""
    python_version: str = ""
    runs_ok:       bool = False
    import_error:  str  = ""
    scope_version: str  = ""
    scope_file:    str  = ""
    editable:      bool = False
    cli_path:      str  = ""
    cli_same_env:  bool = False
    python_ok:     bool = False
    cell2mol:      str  = ""
    rdkit:         str  = ""
    networkx:      str  = ""
    pyside6:       str  = ""
    config_dir:    str  = ""
    probe_error:   str  = ""

    @property
    def state(self) -> str:
        """'green' SCOPE can run from this window, 'amber' it runs but on a Python other than 3.12 (unsupported), 'red' it cannot be started from this Python.
        The `scope` command of a Terminal is shown in the details but does not change the light: this window does not use it."""
        if not self.runs_ok: return "red"
        return "green" if self.python_ok else "amber"

    @property
    def short(self) -> str:
        if not self.runs_ok: return "SCOPE not installed" if not self.probe_error else "check failed"
        return f"SCOPE {self.scope_version}"

    def report(self) -> list:
        """The lines of the details dialog: (status, item, detail) with status 'ok', 'warn' or 'fail'."""
        rows = []
        rows.append(("ok" if self.python_ok else "warn", "Python", f"{self.python_version} at {self.python}" + ("" if self.python_ok else " (SCOPE supports Python 3.12 only)")))
        if self.probe_error: return rows + [("fail", "Check", self.probe_error)]
        if self.runs_ok: rows.append(("ok", "SCOPE", f"version {self.scope_version}, " + ("development install from " if self.editable else "installed in ") + os.path.dirname(self.scope_file)))
        else: rows.append(("fail", "SCOPE", "cannot be imported by this Python: " + (self.import_error or "unknown error")))
        rows.append(("ok" if self.runs_ok else "fail", "Starting a run", "`scope run` can be started from this window" if self.runs_ok else "runs from this window would fail"))
        if self.cli_path: rows.append(("ok" if self.cli_same_env else "warn", "`scope` in a Terminal", self.cli_path + ("" if self.cli_same_env else " (belongs to another Python environment than this window)")))
        else: rows.append(("ok", "`scope` in a Terminal", "no `scope` command on the PATH of this window (it was probably started with the full path). This window does not need it; to type `scope` in a Terminal, activate the environment first."))
        for label, value, needed in (("cell2mol", self.cell2mol, True), ("rdkit", self.rdkit, True), ("networkx", self.networkx, True), ("PySide6", self.pyside6, False)):
            rows.append(("ok" if value else ("fail" if needed else "warn"), label, value or "not installed"))
        rows.append(("ok", "SCOPE settings folder", self.config_dir))
        return rows

INSTALL_HINT = """To install SCOPE with this interface in its own environment:

    conda create --name scope python=3.12
    conda activate scope
    pip install "cell2mol @ git+https://github.com/lcmd-epfl/cell2mol.git@55649ba5f444895846a5d049adcb056c01bb0421"
    pip install "scope-qc[gui]"

(or, from a clone of the repository: pip install -e "core[gui]"). Then start it again with: scope gui"""

def detect_local_scope(python: str=None, timeout: int=60) -> LocalScope:
    """Asks a Python (by default the one running this window) whether SCOPE can be imported, and collects versions. Never raises.

    The question is asked in a separate process, exactly as `scope run` will start: the answer is what a run will see.
    """
    import subprocess
    from platformdirs import user_config_dir
    python = python or sys.executable
    info = LocalScope(python=python, config_dir=user_config_dir("scope"))
    info.cli_path = shutil.which("scope") or ""
    info.cli_same_env = bool(info.cli_path) and os.path.dirname(info.cli_path) == os.path.dirname(python)
    try:
        done = subprocess.run([python, "-c", LOCAL_PROBE], capture_output=True, text=True, timeout=timeout, env=child_environment())
    except (OSError, subprocess.TimeoutExpired) as exc:
        info.probe_error = f"Could not run {python}: {exc}"; return info
    data = {}
    for line in done.stdout.splitlines():
        if line.startswith("__LOCAL_SCOPE__"):
            try: data = json.loads(line[len("__LOCAL_SCOPE__"):])
            except ValueError: pass
    if not data: info.probe_error = (done.stderr.strip().splitlines() or [f"exit code {done.returncode}"])[-1]; return info
    info.python_version, info.cell2mol, info.rdkit, info.networkx, info.pyside6 = data.get("python", ""), data.get("cell2mol", ""), data.get("rdkit", ""), data.get("networkx", ""), data.get("pyside6", "")
    info.python_ok = info.python_version.startswith("3.12")
    info.import_error = data.get("import_error", "")
    info.runs_ok = "import_error" not in data
    if info.runs_ok:
        info.scope_version, info.scope_file = data["scope_version"], data["scope_file"]
        info.editable = "site-packages" not in info.scope_file and "dist-packages" not in info.scope_file
    return info


###################################
### Runs that outlive the window ###
###################################
EXIT_MARKER = "__SCOPE_GUI_EXIT__"
WRAPPER     = 'log="$1"; shift; "$@" > "$log" 2>&1 < /dev/null; code=$?; echo "__SCOPE_GUI_EXIT__ $code" >> "$log"'

def unique_stamp() -> str:
    """'YYYYmmdd_HHMMSS_<6 hex>': a time stamp that two runs (or backups) started in the same second never share, even from two projects
    with a system of the same name. Names built from it still start with the date and time, so they sort by time."""
    import time, uuid
    return f"{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"

def runs_dir() -> str:
    """Folder with the logs and the records of runs started from the GUI (next to the GUI preferences)."""
    from platformdirs import user_config_dir
    path = os.path.join(user_config_dir("scope"), "gui_runs"); os.makedirs(path, exist_ok=True)
    return path

def load_runs() -> list:
    """All run records saved by the GUI (newest last). A record is a dict: id, system, pid, log, started, seen."""
    try:
        with open(os.path.join(runs_dir(), "runs.json")) as f: return json.load(f)
    except Exception: return []

def save_runs(records: list) -> None:
    """Writes the records, keeping the last 30 and every record not yet seen (so an active run is never dropped)."""
    keep = [r for i, r in enumerate(records) if i >= len(records) - 30 or not r.get("seen")]
    try:
        with open(os.path.join(runs_dir(), "runs.json"), "w") as f: json.dump(keep, f, indent=2)
    except Exception: pass

def runs_lock():
    """Exclusive lock on the run records, so two windows that update them at the same time do not overwrite each other."""
    return file_lock(os.path.join(runs_dir(), "runs.lock"))

def update_runs(change: "Callable[[list], None]") -> list:
    """Loads the records, lets `change` modify the list in place, and saves it, all under runs_lock. Returns the saved list."""
    with runs_lock():
        records = load_runs(); change(records); save_runs(records)
    return records

def cleanable_runs() -> tuple:
    """What Clean up would remove on this computer: (ended run records, log files). A record is ended when its run is not running
    (finished, stopped, or lost); the log files are those of ended records plus run logs in runs_dir() that no record names any more
    (records beyond the last 30 are dropped, their logs stayed). Logs of running runs are never included. Read-only."""
    records = [r for r in load_runs() if r.get("kind") == "local"]
    running = {os.path.abspath(r.get("log", "")) for r in records if run_state(r)[0] == "running"}
    ended = [r for r in records if os.path.abspath(r.get("log", "")) not in running]
    folder = runs_dir(); logs = set()
    for r in ended:
        log = os.path.abspath(r.get("log", ""))
        if os.path.dirname(log) == os.path.abspath(folder) and os.path.isfile(log): logs.add(log)       ## only the GUI's own folder
    named = {os.path.abspath(r.get("log", "")) for r in load_runs()}
    for name in os.listdir(folder):
        path = os.path.abspath(os.path.join(folder, name))
        if name.startswith("run_") and name.endswith(".log") and path not in named and path not in running: logs.add(path)
    return ended, sorted(logs)

def clean_runs() -> tuple:
    """Removes the ended local runs from the run records and deletes their logs (see cleanable_runs). Running runs, and records of
    other kinds, are kept. Returns (records removed, log files deleted)."""
    with runs_lock():
        ended, logs = cleanable_runs(); gone = {r.get("id") or r.get("log") for r in ended}
        records = load_runs(); keep = [r for r in records if (r.get("id") or r.get("log")) not in gone]
        try:
            with open(os.path.join(runs_dir(), "runs.json"), "w") as f: json.dump(keep, f, indent=2)
        except OSError: return 0, 0
    deleted = 0
    for log in logs:
        try: os.remove(log); deleted += 1
        except OSError: pass
    return len(records) - len(keep), deleted

def start_detached_local(env_path: str, system: str, inputs: list, quiet: bool=False, verbose: bool=False, errors: bool=False) -> dict:
    """Starts `scope run` so that it does not depend on the window.

    The run gets its own session (a Ctrl-C or the closing of the Terminal that started the GUI does not reach it), no pipe to
    the GUI (a crash of the GUI cannot make it fail with a broken pipe), and writes to a log file. A wrapper appends
    `__SCOPE_GUI_EXIT__ <code>` when it ends, so the end can be recognised even if the window is closed meanwhile.

    Returns:
        dict: the run record (also saved), with the pid of the wrapper (also the id of the process group) and the log path.
    """
    import subprocess, time
    program, args = build_run_command(env_path, system, inputs, quiet, verbose, errors)
    stamp = unique_stamp()
    log   = os.path.join(runs_dir(), f"run_{system}_{stamp}.log")
    open(log, "x").close()                                                  ## created exclusively: a name already used fails here, never shared by two runs
    proc  = subprocess.Popen(["bash", "-c", WRAPPER, "_", log, program, *args], start_new_session=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=child_environment())
    record = {"id": f"{stamp}_{system}", "kind": "local", "system": system, "env": os.path.abspath(env_path), "pid": proc.pid, "log": log, "started": time.time(), "seen": False, "command": "scope " + " ".join(args[2:])}
    update_runs(lambda records: records.append(record))
    return record

def complete_utf8(data: bytes) -> int:
    """Length of the longest start of `data` that does not end inside a UTF-8 character. The bytes of an unfinished character are left for the next read."""
    end = len(data)
    for back in range(1, min(4, end) + 1):
        byte = data[end - back]
        if byte & 0xC0 != 0x80:                                              ## first byte of the last character (or plain ASCII)
            need = 2 if byte >> 5 == 0b110 else 3 if byte >> 4 == 0b1110 else 4 if byte >> 3 == 0b11110 else 1
            return end if back >= need else end - back
    return end

def read_log(path: str, offset: int=0, final: bool=False) -> tuple:
    """Returns (new text, new offset): what was appended to the log since `offset` bytes. The end marker line is not part of the text.

    A character that is still being written (its bytes split between two reads) is kept for the next read, unless `final` is set.
    """
    try:
        with open(path, "rb") as f:
            f.seek(offset); data = f.read()
    except OSError: return "", offset
    if not final: data = data[:complete_utf8(data)]
    text = data.decode("utf-8", errors="replace")
    return "\n".join(l for l in text.split("\n") if not l.startswith(EXIT_MARKER)), offset + len(data)

def exit_code(path: str) -> "int | None":
    """The exit code written by the wrapper at the end of a run, or None if the run has not ended (or was killed hard)."""
    try:
        with open(path, "rb") as f:
            f.seek(max(0, os.path.getsize(path) - 400)); tail = f.read().decode("utf-8", errors="replace")
    except OSError: return None
    for line in reversed(tail.splitlines()):
        if line.startswith(EXIT_MARKER):
            try: return int(line.split()[1])
            except (IndexError, ValueError): return None
    return None

def pid_alive(pid: int) -> bool:
    """Whether a process is running. A run started by this window is its child: once it has ended it stays a zombie (still answering to kill -0)
    until it is collected, so it is collected here first."""
    try:
        done, _ = os.waitpid(pid, os.WNOHANG)
        if done == pid: return False
    except ChildProcessError: pass                                          ## not our child (a run started by an earlier window): fall through
    try: os.kill(pid, 0)
    except ProcessLookupError: return False
    except PermissionError: return True
    return True

_confirmed = set()                                                          ## (pid, log) pairs already matched to their run

def process_command(pid: int) -> str:
    """Full command line of a process ('' if it cannot be read)."""
    import subprocess
    try: return subprocess.run(["ps", "-ww", "-p", str(pid), "-o", "command="], capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.TimeoutExpired): return ""

def is_our_run(record: dict) -> bool:
    """Whether the process with the record's pid is still this run. A pid is reused once its process has ended (for instance after a
    restart), so the command line of the process is checked once: the run's wrapper carries the path of its log."""
    pid, log = record["pid"], record["log"]
    if not pid_alive(pid): _confirmed.discard((pid, log)); return False
    if (pid, log) in _confirmed: return True
    command = process_command(pid)
    if command and log not in command: return False                         ## a different program got this pid
    if command: _confirmed.add((pid, log))
    return True                                                             ## ps unavailable: trust the pid, as before

def run_state(record: dict) -> tuple:
    """('running', None), ('finished', exit code) or ('lost', None): the process is gone without writing its end marker (killed, or the computer restarted)."""
    code = exit_code(record["log"])
    if code is not None: return "finished", code
    return ("running", None) if is_our_run(record) else ("lost", None)

def stop_run(record: dict) -> bool:
    """Asks the whole run (wrapper and `scope run`) to end. Returns whether the signal was sent. Nothing is sent if the pid now belongs to another program."""
    import signal
    if not is_our_run(record): return False
    try: os.killpg(record["pid"], signal.SIGTERM); return True
    except (ProcessLookupError, PermissionError, OSError): return False

def record_belongs(record: dict, env_path: str, legacy: bool=False) -> bool:
    """Whether a run record belongs to the workspace of environment `env_path`. Records made before workspaces existed have no environment: they belong to the legacy workspace."""
    if "env" not in record: return legacy
    return bool(env_path) and os.path.abspath(env_path) == record["env"]

def active_local_run(env_path: str, system: str) -> "dict | None":
    """A local run of `system` that is still running from the environment `env_path` (from any window or workspace), or None.
    Old records without an environment count when the system name matches: being careful is cheaper than two runs of one system."""
    for record in reversed(load_runs()):
        if record.get("kind") != "local" or record.get("system") != system: continue
        if "env" in record and record["env"] != os.path.abspath(env_path): continue
        if run_state(record)[0] == "running": return record
    return None

def mark_seen(record_id: str) -> None:
    def change(records: list) -> None:
        for r in records:
            if r["id"] == record_id: r["seen"] = True
    update_runs(change)
