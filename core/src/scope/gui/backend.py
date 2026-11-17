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
from contextlib   import redirect_stdout
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

def save_gui_config(data: dict) -> None:
    """Updates the GUI preferences. Failures (read-only home, for instance) are ignored."""
    try:
        config = load_gui_config(); config.update(data)
        os.makedirs(os.path.dirname(gui_config_path()), exist_ok=True)
        with open(gui_config_path(), "w") as f: json.dump(config, f, indent=4)
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
    from scope.read_write import load_binary
    system = load_binary(filepath)
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

    @property
    def node(self) -> str:
        return f"{self.branch}/{self.job}"

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
    return report

##################
### Input form ###
##################
SECTIONS       = ("environment", "options", "job_data", "qc_data")
SOFTWARE_TYPES = {"g16": ["scf", "opt", "freq", "ts", "td", "tda"], "qe": ["scf", "opt", "relax", "vc-relax", "freq"]}
FORM_KEYS      = {"environment": ["requested_procs", "queue", "queues"], "options": ["want_submit"], "job_data": ["branch", "workflow", "job", "requisites", "constrains"], "qc_data": ["software", "comp_type", "functional", "basis"]}

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

def build_sections(branch: str, workflow: str, job: str, requisites: str, constrains: str, software: str, comp_type: str, functional: str, basis: str, procs: int, want_submit: bool, queue: str="", extras: dict=None) -> dict:
    """Builds the four sections from the form values.

    workflow, requisites and constrains accept several names separated by commas or spaces (one name stays a plain
    string, several become a list). basis is written only for Gaussian 16. want_submit is always written, because
    SCOPE assumes True when it is missing. extras maps a section to raw `key = value` text; those keys are added
    after the form keys and replace them if they repeat one.
    """
    names, req, con = split_names(workflow), split_names(requisites), split_names(constrains) or ["self"]
    sections = {
        "environment": {"requested_procs": str(int(procs))},
        "options":     {"want_submit": py_value(bool(want_submit))},
        "job_data":    {"branch": py_value(branch.strip()), "workflow": py_value(names[0] if len(names) == 1 else names), "job": py_value(job.strip()), "hierarchy": "1", "requisites": py_value(req), "constrains": py_value(con)},
        "qc_data":     {"software": py_value(software), "comp_type": py_value(comp_type), "functional": py_value(functional.strip() or "pbe")},
    }
    if queue.strip(): sections["environment"]["queue"] = py_value(queue.strip())
    if software == "g16" and basis.strip(): sections["qc_data"]["basis"] = py_value(basis.strip())
    for name, text in (extras or {}).items():
        for key, value in parse_sections(f"&{name}\n{text}\n/").get(name, {}).items(): sections[name][key] = value
    return sections

def _literal(raw: str):
    import ast
    try: return ast.literal_eval(raw)
    except Exception: return raw.strip("'\"")

def sections_to_form(sections: dict) -> tuple:
    """Maps the sections of an existing file to the form fields; every key the form has no field for goes to extras.

    Returns:
        tuple: (form dict with the build_sections arguments, extras dict section -> text).
    """
    def get(section, key, default=""): return _literal(sections.get(section, {}).get(key, "")) if key in sections.get(section, {}) else default
    def names(value): return ", ".join(value) if isinstance(value, (list, tuple)) else str(value)
    queue = get("environment", "queue", get("environment", "queues", ""))
    form  = {"branch": str(get("job_data", "branch")), "workflow": names(get("job_data", "workflow", "*")), "job": str(get("job_data", "job")), "requisites": names(get("job_data", "requisites", [])), "constrains": names(get("job_data", "constrains", ["self"])),
             "software": str(get("qc_data", "software", "g16")), "comp_type": str(get("qc_data", "comp_type", "scf")), "functional": str(get("qc_data", "functional", "pbe")), "basis": str(get("qc_data", "basis", "")),
             "procs": int(get("environment", "requested_procs", 4)) if str(get("environment", "requested_procs", 4)).isdigit() else 4, "want_submit": get("options", "want_submit", True) is True, "queue": str(queue)}
    extras = {}
    for name in SECTIONS:
        lines = [f"{k} = {v}" for k, v in sections.get(name, {}).items() if k not in FORM_KEYS[name] and not (name == "job_data" and k == "hierarchy" and v == "1")]
        extras[name] = "\n".join(lines)
    return form, extras

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
    return text, read_input_text(text), problems

def build_graph(reports: list) -> tuple:
    """Builds the pipeline graph from valid input reports.

    Nodes are 'branch/job'. Edges are (from, to, kind): kind 'requisite' (from must finish before to) or 'constrain'
    (from blocks to). Names that no loaded file defines are added as nodes with kind 'missing'.

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
                source = f"{r.branch}/{name}"
                if source not in nodes: nodes[source] = "missing"
                edges.append((source, r.node, kind))
    graph = nx.DiGraph(); graph.add_nodes_from(nodes); graph.add_edges_from((a, b) for a, b, k in edges if k == "requisite")
    cycles = list(nx.simple_cycles(graph))
    return nodes, edges, cycles

def pipeline_issues(reports: list) -> list:
    """Finds problems that only show when the input files are looked at together.

    Returns a list of (path, message): a job that requires itself, a requisite no loaded file defines, two files that
    define the same branch/job, and cycles of requisites. These are warnings: SCOPE itself accepts all of them.
    """
    issues, seen = [], {}
    nodes, edges, cycles = build_graph(reports)
    for r in reports:
        if not r.ok: continue
        if r.job in [q.replace("-", "_").replace(" ", "_") for q in r.requisites]: issues.append((r.path, f"{r.node} lists itself as a requisite, so it would never start."))
        if r.node in seen: issues.append((r.path, f"{r.node} is also defined in {os.path.basename(seen[r.node])}; the last file read wins."))
        seen[r.node] = r.path
        for name in r.requisites:
            if name != r.job and f"{r.branch}/{name}" in nodes and nodes[f"{r.branch}/{name}"] == "missing": issues.append((r.path, f"{r.node} requires '{name}', which none of the loaded files defines. It must already exist in the system or this job never starts."))
    for cycle in cycles: issues.append(("", "Cycle of requisites: " + " -> ".join(cycle) + ". None of these jobs can start."))
    return issues

def layout_graph(nodes: dict, edges: list) -> dict:
    """Assigns each node a (column, row): column is the longest chain of requisites before it, rows are numbered per column."""
    depth = {n: 0 for n in nodes}
    for _ in range(len(nodes)):                                   ## bounded relaxation: stays finite even if there is a cycle
        changed = False
        for a, b, kind in edges:
            if kind == "requisite" and depth[b] < depth[a] + 1: depth[b] = depth[a] + 1; changed = True
        if not changed: break
    rows, place = {}, {}
    for n in sorted(nodes, key=lambda n: (depth[n], n)):
        place[n] = (depth[n], rows.get(depth[n], 0)); rows[depth[n]] = rows.get(depth[n], 0) + 1
    return place

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
