"""Workspaces of the SCOPE GUI (no Qt).

A workspace is one project as the window sees it: a local environment file, the input files of its pipeline, the cluster connection it
uses (the name of a saved profile) and its project folder and environment file on that cluster. The window shows one workspace at a time
and switching restores all of it; runs keep going whatever is shown.

Each workspace is one small JSON file in <SCOPE settings>/workspaces/, written whole and atomically, so two windows that save different
workspaces never overwrite each other. The name of the active workspace is a preference (scope_gui.json).

The first time, a workspace called "Default" is made from what the window remembered before workspaces existed (the last environment,
and the cluster project of the only saved profile, if there is exactly one). It is marked `legacy`: runs recorded before workspaces
existed, which carry no environment path, are shown there, and its project on the cluster falls back to the values stored in the
profile while its own are empty. This happens once; after that the folder of workspaces is the only source.
"""
import json
import os
import re
from dataclasses import asdict, dataclass, field
from scope.gui import backend

NAME     = re.compile(r"^[A-Za-z0-9][^/\\\x00-\x1f]{0,59}$")                 ## a label: anything but slashes and control characters
DEFAULT  = "Default"
MIGRATED = "workspaces_migrated"

@dataclass
class Workspace:
    """One project.

    Attributes:
        name (str):         Label shown in the window (starts with a letter or digit; no slashes).
        env_path (str):     Local environment file (scope_env_<name>.npy), or '' if none yet.
        inputs (list):      Paths of the input files of the pipeline, in order.
        profile (str):      Name of the saved cluster connection, or ''.
        remote_root (str):  Project folder on the cluster, or ''.
        remote_env (str):   Cluster environment file, or ''.
        legacy (bool):      True for the workspace made from the settings of a version without workspaces.
    """
    name:        str
    env_path:    str  = ""
    inputs:      list = field(default_factory=list)
    profile:     str  = ""
    remote_root: str  = ""
    remote_env:  str  = ""
    legacy:      bool = False

def folder() -> str:
    from platformdirs import user_config_dir
    path = os.path.join(user_config_dir("scope"), "workspaces"); os.makedirs(path, exist_ok=True)
    return path

def file_name(name: str) -> str:
    """File of a workspace: its name with every character other than a letter, digit, '.', '_' or '-' replaced by '_'."""
    return "".join(ch if (ch.isascii() and (ch.isalnum() or ch in "._-")) else "_" for ch in name) + ".json"

def name_problem(name: str, existing: list, current: str="") -> str:
    """Why `name` cannot be used for a new or renamed workspace ('' if it can). `current` is the name being renamed."""
    name = name.strip()
    if not NAME.match(name): return "Start with a letter or a digit; '/' and '\\' are not allowed (at most 60 characters)."
    taken = {file_name(n).lower() for n in existing if n != current}
    if file_name(name).lower() in taken: return f"A workspace called '{name}' (or one with a name that differs only in punctuation or case) already exists."
    return ""

def load(name: str) -> "Workspace | None":
    try:
        with open(os.path.join(folder(), file_name(name))) as fh: data = json.load(fh)
    except (OSError, ValueError): return None
    return Workspace(**{k: v for k, v in data.items() if k in Workspace.__dataclass_fields__})

def list_names() -> list:
    """Names of all workspaces, sorted (case-insensitive)."""
    names = []
    for entry in os.listdir(folder()):
        if entry.endswith(".json") and not entry.startswith("."):
            try:
                with open(os.path.join(folder(), entry)) as fh: names.append(json.load(fh)["name"])
            except (OSError, ValueError, KeyError): continue
    return sorted(names, key=str.lower)

def save(ws: Workspace) -> None:
    """Writes one workspace (a temporary file renamed over the old one, so a reader never sees half a file)."""
    path = os.path.join(folder(), file_name(ws.name)); tmp = path + f".{os.getpid()}.tmp"
    with open(tmp, "w") as fh: json.dump(asdict(ws), fh, indent=2)
    os.replace(tmp, path)

def delete(name: str) -> None:
    """Removes a workspace record (never any project file). The last workspace cannot be deleted."""
    if len(list_names()) <= 1: raise ValueError("The last workspace cannot be deleted.")
    try: os.remove(os.path.join(folder(), file_name(name)))
    except FileNotFoundError: pass
    if active_name() == name: set_active(list_names()[0])

def rename(old: str, new: str) -> Workspace:
    """Renames a workspace. Raises ValueError with the reason if the new name cannot be used."""
    problem = name_problem(new, list_names(), current=old)
    if problem: raise ValueError(problem)
    ws = load(old)
    if ws is None: raise ValueError(f"No workspace called '{old}'.")
    ws.name = new.strip(); save(ws)
    if file_name(old) != file_name(ws.name):
        try: os.remove(os.path.join(folder(), file_name(old)))
        except FileNotFoundError: pass
    if active_name() == old: set_active(ws.name)
    return ws

def create(name: str, profile: str="") -> Workspace:
    """Makes an empty workspace (no environment, no inputs). Raises ValueError with the reason if the name cannot be used."""
    problem = name_problem(name, list_names())
    if problem: raise ValueError(problem)
    ws = Workspace(name.strip(), profile=profile); save(ws)
    return ws

def active_name() -> str:
    return backend.load_gui_config().get("active_workspace", "")

def set_active(name: str) -> None:
    backend.save_gui_config({"active_workspace": name})

def ensure() -> Workspace:
    """Returns the active workspace, making the Default one first if no workspace has ever existed (migration, done once)."""
    config = backend.load_gui_config()
    if not list_names():
        if config.get(MIGRATED):
            ws = Workspace(DEFAULT)                                                     ## every file was removed by hand: start again, empty
        else:
            profiles = config.get("profiles", {})
            only = next(iter(profiles.values())) if len(profiles) == 1 else {}
            last = config.get("last_env", "")
            ws = Workspace(DEFAULT, env_path=last if last and os.path.isfile(last) else "", profile=only.get("name", ""), remote_root=only.get("remote_root", ""), remote_env=only.get("remote_env", ""), legacy=True)
        save(ws); backend.save_gui_config({MIGRATED: True, "active_workspace": ws.name})
        return ws
    active = load(active_name()) if active_name() else None
    if active is None: active = load(list_names()[0]); set_active(active.name)
    if not config.get(MIGRATED): backend.save_gui_config({MIGRATED: True})
    return active

def remote_fields(ws: Workspace, profile: "object | None") -> tuple:
    """The project on the cluster to show for a workspace: its own values, or, for the legacy workspace while they are empty, the ones the profile stored before workspaces existed."""
    if ws.remote_root or ws.remote_env or not ws.legacy or profile is None: return ws.remote_root, ws.remote_env
    return getattr(profile, "remote_root", ""), getattr(profile, "remote_env", "")

def suggested_remote_root(ws: Workspace) -> str:
    """A project folder to propose on the cluster for a new workspace."""
    return "~/scope_projects/" + file_name(ws.name)[:-5]

def sharing(name: str, host: str, root: str, profiles: dict) -> list:
    """Other workspaces whose project on the cluster is the same folder of the same host (the same system run from two of them would collide)."""
    if not host or not root: return []
    target = (host, root.rstrip("/")); out = []
    for other in list_names():
        if other == name: continue
        ws = load(other); prof = profiles.get(ws.profile) if ws else None
        if ws is None or prof is None: continue
        other_root, _ = remote_fields(ws, prof)
        if (prof.host, other_root.rstrip("/")) == target: out.append(other)
    return out

EXPORT_FORMAT = "scope-gui-workspace"

def export_data(ws: Workspace, profile: "object | None") -> dict:
    """What an exported workspace file holds: the workspace, and the connection of its profile (host and how to start scope; never a password, there is none to store)."""
    data = {"format": EXPORT_FORMAT, "version": 1, "workspace": asdict(ws)}
    data["workspace"]["legacy"] = False
    if profile is not None: data["profile"] = {k: getattr(profile, k) for k in ("name", "host", "scope_bin", "activate")}
    return data

def import_data(data: dict, profiles: dict) -> tuple:
    """Creates a workspace from an exported file. Returns (Workspace, notes). A name already in use gets ' (2)', ' (3)'…; a profile with the same name but a
    different connection is imported under a new name, so no saved connection is ever replaced. Raises ValueError for a file that is not an exported workspace."""
    from scope.gui import remote
    if data.get("format") != EXPORT_FORMAT or "workspace" not in data: raise ValueError("This file is not an exported SCOPE workspace.")
    raw = {k: v for k, v in data["workspace"].items() if k in Workspace.__dataclass_fields__}
    ws = Workspace(**{**raw, "legacy": False}); notes = []
    base, n, names = ws.name, 2, list_names()
    while name_problem(ws.name, names): ws.name = f"{base} ({n})"; n += 1
    if ws.name != base: notes.append(f"A workspace called '{base}' exists: the imported one is '{ws.name}'.")
    conn = data.get("profile")
    if conn:
        incoming = remote.Profile(conn.get("name", ""), conn.get("host", ""), conn.get("scope_bin", ""), conn.get("activate", ""))
        existing = profiles.get(incoming.name)
        if existing is None or (existing.host, existing.scope_bin, existing.activate) != (incoming.host, incoming.scope_bin, incoming.activate):
            if existing is not None:
                k = 2
                while f"{incoming.name}_{k}" in profiles: k += 1
                incoming.name = f"{incoming.name}_{k}"; notes.append(f"A different profile called '{conn.get('name')}' exists: the imported connection is saved as '{incoming.name}'.")
            if not remote.connection_problems(incoming): remote.save_profile(incoming, connection_only=True)
            else: notes.append("The connection in the file is incomplete and was not saved."); incoming.name = ""
        ws.profile = incoming.name
    missing = [p for p in [ws.env_path, *ws.inputs] if p and not os.path.exists(p)]
    if missing: notes.append(f"{len(missing)} path(s) of this workspace do not exist on this computer (for instance {missing[0]}). Open the environment and the inputs from where they are here.")
    save(ws)
    return ws, notes
