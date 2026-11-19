"""Jupyter notebooks for the Results page (no Qt): a notebook written from a template, a file name that never replaces the user's work,
and the command that starts Jupyter Lab with the Python of this window.

The template opens the system with scope.gui.results.open_system, the same resolver as the Results page, so the notebook shows the same
data as the window. It follows Tutorials 3 and 4: sources and states, energies and ΔE, frequencies and IR, thermochemistry and ΔG(T).
It never calls system.save().

Notebooks live in <project>/Notebooks/. Upload sends only Sources/<system>, the system file and the inputs, and download writes only into
Computations/<system> and Systems/<system>, so that folder is never touched by a transfer.
"""
import importlib.util
import os
import sys
import time

FOLDER = "Notebooks"

def project_folder(info: object) -> str:
    """The project folder of an environment (backend.EnvInfo): the common parent of Sources, Systems and Computations when they sit side
    by side in it (the layout the Environment page creates), otherwise the folder of the environment file."""
    paths = [getattr(info, k, "") for k in ("sources_path", "systems_path", "computations_path")]
    if all(paths):
        parents = {os.path.dirname(os.path.normpath(p)) for p in paths}
        if len(parents) == 1: return parents.pop()
    return os.path.dirname(os.path.abspath(info.filepath))

def notebooks_dir(info: object) -> str:
    return os.path.join(project_folder(info), FOLDER)

def unique_path(folder: str, system: str) -> str:
    """<folder>/<system>.ipynb, or <system>-2.ipynb, -3… if that exists: a notebook written once is the user's and is never replaced."""
    path = os.path.join(folder, f"{system}.ipynb"); n = 2
    while os.path.exists(path): path = os.path.join(folder, f"{system}-{n}.ipynb"); n += 1
    return path

def existing(folder: str, system: str) -> list:
    """Notebooks of this system already in the folder, newest first."""
    if not os.path.isdir(folder): return []
    names = [f for f in os.listdir(folder) if f.endswith(".ipynb") and (f == f"{system}.ipynb" or (f.startswith(f"{system}-") and f[len(system) + 1:-6].isdigit()))]
    return sorted((os.path.join(folder, f) for f in names), key=os.path.getmtime, reverse=True)

#################
### Template  ###
#################
def setup_code(env_path: str, system: str, file: str="") -> str:
    """The first cell: opens the system as the Results page does and prints where it comes from. Also what 'Copy code' puts on the clipboard."""
    copy = f"\nFILE     = {file!r}                              # an older copy of the system file, read instead of the current one" if file else ""
    return f'''import os
import sys
import scope
from scope.gui import results

ENV_FILE = {env_path!r}
SYSTEM   = {system!r}{copy}
GUI_PYTHON = {sys.executable!r}       # the Python of the SCOPE window that wrote this notebook
GUI_PREFIX = {sys.prefix!r}

# The same entry point as the Results page: the system file is read and its paths are pointed at this computer's folders, in memory only.
# RDKit's per-molecule warnings about a newer RDKit are counted into prov.rdkit_note (printed below) instead of filling this cell.
system, prov = results.open_system(ENV_FILE, SYSTEM{", FILE" if file else ""})
summary = results.summarize(system)
try: import rdkit
except ImportError: rdkit = None

print(f"System file:  {{prov.file}}  ({{prov.size / 1e6:.2f}} MB)")
print(f"Saved by SCOPE {{prov.saved_version or '?'}}, read with SCOPE {{prov.local_version}} ({{scope.__file__}})")
print(f"Folders of:   {{prov.env_file}}")
if prov.moved: print(f"Written where SCOPE ran ({{prov.stored_root}}); paths pointed at {{prov.local_root}} for reading")
if prov.rdkit_note: print("Note:", prov.rdkit_note)
print(f"Python:       {{sys.executable}}" + (f"  (RDKit {{rdkit.__version__}})" if rdkit else ""))
if os.path.realpath(sys.prefix) != os.path.realpath(GUI_PREFIX):
    print("Note: this kernel is not the Python of the SCOPE window, so SCOPE or its add-ons may differ. Choose the kernel of", GUI_PYTHON)
'''

INTRO = """# {system}: results

Written by the SCOPE GUI on {date} for the system **{system}**{copy}.

This notebook is yours: the GUI never writes over it (a new one is called `{system}-2.ipynb`, and so on). Edit and extend it freely.

> **It only reads.** It never calls `system.save()`. Here the system's paths point at this computer's folders and analyses add values in
> memory: saving would write all that into the system file that SCOPE (and the cluster) use. To change results, run SCOPE."""

STATES_MD = "## Sources and states\n\nOne row per state, as the Overview tab shows it. The status is that of the last calculation that wrote the state."
STATES = '''done, total = summary.counts()
print(f"{done} of {total} sources have results\\n")
print(f"{'source':<16} {'state':<14} {'method':<28} {'energy (Eh)':>18} {'min':>4} {'imag':>4}  status / runs")
for r in summary.states:
    energy = f"{r.energy:.8f}" if r.energy is not None else "—"
    minimum = "" if r.minimum is None else ("yes" if r.minimum else "no")
    print(f"{r.source:<16} {r.state:<14} {r.method[:28]:<28} {energy:>18} {minimum:>4} {r.n_imag if r.n_freqs else '':>4}  {r.group}{' (after a retry)' if r.retried else ''}  {', '.join(r.runs)}")
missing = summary.missing_outputs
if missing: print(f"\\n{len(missing)} output file(s) are not on this computer (energies and frequencies are in the system file anyway).")
'''

ENERGY_MD = "## Energies and ΔE\n\nΔE is measured from the lowest energy among the states with the same formula **and** the same method (other energies are not comparable)."
ENERGY = '''UNITS = "kcal/mol"                                         # or "kJ/mol", "eV"
factor = results.UNITS[UNITS]
rel = results.relative_energies(summary.states)
if not rel: print("No two states share formula and method yet, so there is no ΔE to show.")
for r in sorted(summary.states, key=lambda r: (r.formula, r.method, rel.get((r.source, r.state), 0))):
    if (r.source, r.state) in rel: print(f"{r.formula:<14} {r.method[:28]:<28} {r.source:<16} {r.state:<14} ΔE = {rel[(r.source, r.state)] * factor:9.2f} {UNITS}")
'''

IR_MD = "## Frequencies and IR spectrum\n\nComputed by SCOPE's own `get_ir_spectrum` (what `plot_ir_spectrum` draws), broadened as chosen here."
IR = '''import matplotlib.pyplot as plt

STATE = __STATE__                                          # any (source, state) of the table above that has frequencies
choices = results.with_frequencies(summary)
if STATE not in choices: STATE = choices[0] if choices else None
if STATE is None:
    print("No state has frequencies yet (a frequency job writes them): nothing to plot.")
else:
    detail = results.state_detail(system, *STATE)
    imag = [m.freq for m in detail.modes if m.freq < 0]
    print(f"{STATE[0]} · {STATE[1]}: {len(detail.modes)} modes, {len(imag)} imaginary {imag if imag else '(a minimum)'}")
    sp = results.spectrum(system, *STATE, kind="ir", function="gaussian", sigma=10.0)
    fig, ax = plt.subplots(figsize=(8, 3.5))
    ax.plot(sp.x, sp.y); ax.fill_between(sp.x, 0, sp.y, alpha=0.2)
    ax.vlines([p for p, h in sp.sticks], 0, [h for p, h in sp.sticks], color="tab:red", lw=0.7)
    ax.set_xlabel(sp.xlabel); ax.set_ylabel(sp.ylabel); ax.set_title(sp.title); ax.set_ylim(bottom=0)
    plt.show()
    if detail.n_excited:                                   # TD-DFT excited states: the absorption spectrum too
        ab = results.spectrum(system, *STATE, kind="abs", function="gaussian", sigma=0.2)
        fig, ax = plt.subplots(figsize=(8, 3)); ax.plot(ab.x, ab.y); ax.set_xlabel(ab.xlabel); ax.set_ylabel(ab.ylabel); ax.set_title(ab.title); plt.show()
'''

THERMO_MD = """## Thermochemistry

SCOPE's `get_thermal_data`, run by `results.thermo` on a copy of the state, so the system in memory keeps its values. Per formula unit;
translational and rotational terms are not included, as in SCOPE. Models: `HO` or `QRRHO`; imaginary frequencies: `ignore`, `absolute` or `raise`."""
THERMO = '''TEMPERATURES = sorted(set(range(10, 501, 10)) | {298.15})    # K
MODEL, IMAGINARY = "HO", "ignore"
if STATE is None:
    print("No state has frequencies yet: no thermochemistry.")
else:
    th = results.thermo(system, *STATE, TEMPERATURES, MODEL, IMAGINARY)
    i = th.at(298.15)
    print(f"{STATE[0]} · {STATE[1]} at {th.T[i]:g} K: G = {th.G[i]:.8f} Eh, G - H_elec = {(th.G[i] - th.Helec) * factor:.2f} {UNITS}")
    fig, ax = plt.subplots(figsize=(8, 3.5))
    ax.plot(th.T, [(g - th.Helec) * factor for g in th.G], label="G - H_elec")
    ax.plot(th.T, [h * factor for h in th.Hvib], label="H_vib")
    ax.plot(th.T, [-t * (th.Selec + s) * factor for t, s in zip(th.T, th.Svib)], label="-T·S")
    ax.axhline(0, color="grey", lw=0.8); ax.set_xlabel("Temperature (K)"); ax.set_ylabel(f"Energy ({UNITS})"); ax.legend(); plt.show()
'''

DELTA_MD = """## ΔG(T) between two states

Two states with the same formula and method in two sources. Where ΔG = 0 they are equally stable: for the high- and low-spin states of a
spin-crossover compound this is T½. It is computed here from ΔG, not with `scope_sco`'s `get_T12`, which stores its result in the
system's branches."""
DELTA = '''PAIR = __PAIR__                                            # (A, B): ΔG = G(A) - G(B)
pairs = results.comparable_pairs(summary)
if PAIR is None or PAIR[0] not in choices or PAIR[1] not in choices: PAIR = pairs[0] if pairs else None
if PAIR is None:
    print("No two states with frequencies share formula and method: no ΔG to show.")
else:
    ta = results.thermo(system, *PAIR[0], TEMPERATURES, MODEL, IMAGINARY)
    tb = results.thermo(system, *PAIR[1], TEMPERATURES, MODEL, IMAGINARY)
    d = results.difference(ta, tb)
    i = d.T.index(min(d.T, key=lambda t: abs(t - 298.15)))
    print(f"A = {d.a}, B = {d.b}. At {d.T[i]:g} K: ΔG = {d.dG[i] * factor:.2f} {UNITS}, ΔH = {d.dH[i] * factor:.2f}, -TΔS = {d.mTdS[i] * factor:.2f}")
    if d.crossing: print("ΔG = 0 at", ", ".join(f"{t:.1f} K" for t in d.crossing), "(T½ for a high-spin / low-spin pair)")
    else: print(f"ΔG keeps its sign from {d.T[0]:g} to {d.T[-1]:g} K: {d.a if d.dG[0] < 0 else d.b} is the more stable throughout.")
    fig, ax = plt.subplots(figsize=(8, 3.5))
    for label, ys in (("ΔG", d.dG), ("ΔH", d.dH), ("-TΔS", d.mTdS)): ax.plot(d.T, [y * factor for y in ys], label=label)
    for t in d.crossing: ax.axvline(t, ls="--", color="k", lw=0.8)
    ax.axhline(0, color="grey", lw=0.8); ax.set_xlabel("Temperature (K)"); ax.set_ylabel(f"Δ ({UNITS})"); ax.legend(); plt.show()
'''

NEXT_MD = """## Going further

The SCOPE objects are all here: `system.sources`, each source's `.states`, each state's `.results`, `.VNMs` and `.computations`. For
example `system.sources[0].states[-1].results`. `results.read_log(path)` reads an output file (see `prov.local_root`). Remember: no
`system.save()`."""

def build(env_path: str, system: str, state: "tuple | None"=None, pair: "tuple | None"=None, file: str="") -> object:
    """The notebook (an nbformat NotebookNode) for one system. `state` and `pair` are the defaults the page has shown ((source, state), and
    ((source, state), (source, state)) for ΔG); the notebook falls back to the first suitable ones itself, so it runs on any system."""
    import nbformat
    from nbformat.v4 import new_code_cell, new_markdown_cell, new_notebook
    copy = f", from the older copy `{os.path.basename(file)}`" if file else ""
    as_tuple = lambda x: tuple(x) if x else None
    cells = [new_markdown_cell(INTRO.format(system=system, date=time.strftime("%d %b %Y %H:%M"), copy=copy)), new_code_cell(setup_code(env_path, system, file)),
             new_markdown_cell(STATES_MD), new_code_cell(STATES), new_markdown_cell(ENERGY_MD), new_code_cell(ENERGY),
             new_markdown_cell(IR_MD), new_code_cell(IR.replace("__STATE__", repr(as_tuple(state)))), new_markdown_cell(THERMO_MD), new_code_cell(THERMO),
             new_markdown_cell(DELTA_MD), new_code_cell(DELTA.replace("__PAIR__", repr((as_tuple(pair[0]), as_tuple(pair[1])) if pair else None))), new_markdown_cell(NEXT_MD)]
    nb = new_notebook(cells=cells, metadata={"kernelspec": {"name": "python3", "display_name": "Python 3", "language": "python"},
                                             "language_info": {"name": "python"}, "scope_gui": {"env_file": env_path, "system": system, "file": file}})
    nbformat.validate(nb)
    return nb

def write_new(folder: str, nb: object, system: str) -> str:
    """Writes the notebook under a name not used yet (unique_path) and returns its path. Opening with 'x' means an existing file is never
    replaced, even if one appears between choosing the name and writing."""
    import nbformat
    os.makedirs(folder, exist_ok=True)
    for _ in range(100):
        path = unique_path(folder, system)
        try:
            with open(path, "x", encoding="utf-8") as fh: nbformat.write(nb, fh)
            return path
        except FileExistsError: continue
    raise OSError(f"Cannot find a free notebook name in {folder}")

#################
### Jupyter   ###
#################
def jupyter_missing() -> str:
    """'' if Jupyter Lab can be started from this Python, otherwise the install command."""
    if importlib.util.find_spec("jupyterlab") is not None: return ""
    return f"{sys.executable} -m pip install jupyterlab"

def jupyter_command(path: str, root: str) -> tuple:
    """(program, args) that start Jupyter Lab on `path`, serving `root`, with the Python of this window, so the notebook gets the same SCOPE
    and add-ons. The kernel named python3 then runs this Python too (Jupyter replaces a kernel command 'python' by its own interpreter)."""
    return sys.executable, ["-m", "jupyter", "lab", f"--ServerApp.root_dir={root}", path]

def jupyter_environment(base: dict) -> dict:
    """Environment for Jupyter Lab, so that it uses only what this Python's environment installed:
    - JUPYTER_PREFER_ENV_PATH: kernels of this environment come before ones in the user's folders, so a 'python3' kernel defined
      elsewhere cannot take the notebook to another Python;
    - JUPYTERLAB_DIR: JupyterLab's own files (settings schemas, themes) from this environment. Without it, files left in
      /usr/local/share/jupyter/lab by an older system-wide JupyterLab are read too; one of them made every settings request fail
      (HTTP 500) and the page stayed blank. A JUPYTERLAB_DIR the user set is kept."""
    env = dict(base) | {"JUPYTER_PREFER_ENV_PATH": "1"}
    own = os.path.join(sys.prefix, "share", "jupyter", "lab")
    if "JUPYTERLAB_DIR" not in env and os.path.isdir(own): env["JUPYTERLAB_DIR"] = own
    return env

def running_server(root: str) -> "dict | None":
    """A Jupyter server of this user that serves `root` and is still alive (Jupyter's own list of running servers, which drops dead ones),
    or None. Its 'url', 'token' and 'pid' are used to open more notebooks in it and to stop it."""
    try: from jupyter_server.serverapp import list_running_servers
    except ImportError: return None
    want = os.path.normcase(os.path.realpath(root))
    try:
        for srv in list_running_servers():
            if os.path.normcase(os.path.realpath(srv.get("root_dir", "") or "")) == want: return srv
    except Exception: return None
    return None

def notebook_url(server: dict, root: str, path: str) -> str:
    """The address of `path` in a running Jupyter server (running_server) that serves `root`."""
    from urllib.parse import quote
    rel = os.path.relpath(path, root).replace(os.sep, "/")
    base = server["url"] if server["url"].endswith("/") else server["url"] + "/"
    return f"{base}lab/tree/{quote(rel)}" + (f"?token={server['token']}" if server.get("token") else "")

def spawn(program: str, args: list, env: dict, log_path: str) -> object:
    """Starts Jupyter on its own (it may outlive the window, if the user keeps it), its output going to `log_path`. Returns the process
    (subprocess.Popen): poll() says whether it still runs, so a server that is still starting is not taken for a missing one."""
    import subprocess
    with open(log_path, "ab") as log:
        kw = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
        proc = subprocess.Popen([program] + list(args), env=env, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, **kw)
    return proc

def stop(proc: object) -> None:
    """Asks a Jupyter server started by spawn to stop, if it still runs. On macOS and Linux this is SIGTERM: it shuts its kernels down and
    exits. On Windows it is a hard stop of the server process."""
    try:
        if proc.poll() is None: proc.terminate()
    except OSError: pass
