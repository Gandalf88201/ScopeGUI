"""Tests of the remote layer against a fake `ssh` that runs the command on this computer. No real host is contacted."""
import os
import re
import stat
import sys
import pytest

from scope.gui import backend, remote

WATER = "3\nwater\nO 0 0 0.117\nH 0 0.757 -0.469\nH 0 -0.757 -0.469\n"
FAKE_SSH = """#!/bin/bash
# Fake ssh: skips the options, ignores the host, runs the rest as one shell command (like a remote shell would).
[ -n "${FAKE_SSH_FAIL:-}" ] && { echo "ssh: connect to host fake port 22: Connection refused" >&2; exit 255; }
[ -n "${FAKE_SSH_LOG:-}" ] && printf '%s\n' "$*" >> "$FAKE_SSH_LOG"
while [ $# -gt 0 ]; do case "$1" in -o|-p|-l) shift 2;; -*) shift;; *) break;; esac; done
shift
exec bash -c "$*"
"""

@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    home = tmp_path / "home"; home.mkdir()
    monkeypatch.setenv("HOME", str(home)); monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    fake = tmp_path / "fake_ssh"; fake.write_text(FAKE_SSH); fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("SCOPE_GUI_SSH", str(fake))
    monkeypatch.delenv("FAKE_SSH_FAIL", raising=False)

def scope_link(folder) -> str:
    """The `scope` program of this Python. The GUI rejects a cluster path with a space, and the Python that runs the tests may live
    in one (for instance ~/Library/Application Support/... on macOS): then the whole environment folder is reached through a link
    in `folder`, so that `bin/scope`, `bin/python` (which the probe looks for next to scope) and pyvenv.cfg stay together."""
    bin_dir = os.path.dirname(sys.executable); real = os.path.join(bin_dir, "scope")
    if not re.search(r"\s", real): return real
    os.makedirs(folder, exist_ok=True); link = os.path.join(folder, "env")
    if not os.path.lexists(link): os.symlink(os.path.dirname(bin_dir), link)
    return os.path.join(link, os.path.basename(bin_dir), "scope")

@pytest.fixture
def cluster(tmp_path):
    """A 'cluster': a project folder with its own environment, and a profile that points to it."""
    root = tmp_path / "cluster_proj"
    env, info = backend.create_environment("cl", str(root / "Sources"), str(root / "Systems"), str(root / "Computations"), str(root))
    return remote.Profile("fake", "fakehost", scope_link(str(tmp_path / "bin")), "", str(root), info.filepath)

@pytest.fixture
def local(tmp_path):
    env, info = backend.create_environment("loc", str(tmp_path / "L" / "Sources"), str(tmp_path / "L" / "Systems"), str(tmp_path / "L" / "Computations"), str(tmp_path / "L"))
    x = tmp_path / "water.xyz"; x.write_text(WATER); backend.import_xyz(env, str(x))
    return env, info

# ---- profile
def test_profile_validation():
    ok = remote.Profile("c1", "login.example.org", "/home/u/bin/scope", "", "/home/u/proj", "/home/u/proj/scope_env_c.npy")
    assert remote.validate_profile(ok) == []
    assert remote.validate_profile(remote.Profile("c 1", "h", "/s", "", "/p", "/e"))                       # name with a space
    assert remote.validate_profile(remote.Profile("c", "-oProxyCommand=x", "/s", "", "/p", "/e"))           # option injection through the host
    assert remote.validate_profile(remote.Profile("c", "h", "relative/scope", "", "/p", "/e"))
    assert remote.validate_profile(remote.Profile("c", "h", "/s", "", "$HOME/p", "/e"))                    # variables are not expanded
    assert remote.validate_profile(remote.Profile("c", "h", "~/bin/scope", "", "~/proj", "~/proj/scope_env_c.npy")) == []   # ~/ is fine
    assert remote.validate_profile(remote.Profile("c", "h", "", "", "/p", "/e"))                           # neither scope path nor activation
    assert remote.validate_profile(remote.Profile("c", "h", "/s", "", "/my project", "/e"))                # space in a path

def test_profiles_are_saved_and_deleted():
    p = remote.Profile("c1", "h", "/s", "", "/p", "/e"); remote.save_profile(p)
    assert remote.load_profiles()["c1"] == p
    remote.delete_profile("c1"); assert remote.load_profiles() == {}

def test_ssh_hosts_from_config(tmp_path):
    cfg = tmp_path / "config"; cfg.write_text("Host *\n  ServerAliveInterval 5\nHost alpha beta\n  User x\nhost gamma.example\n  Port 2222\nHost *.corp !bad\n")
    assert remote.list_ssh_hosts(str(cfg)) == ["alpha", "beta", "gamma.example"]
    assert remote.list_ssh_hosts(str(tmp_path / "missing")) == []

def test_ssh_options_never_prompt_and_socket_is_short():
    assert "BatchMode=yes" in remote.ssh_options()
    assert len(remote.control_path().replace("%C", "x" * 40)) < 104
    assert "ControlPath" in remote.master_command(remote.Profile("c", "my host", "/s", "", "/p", "/e")) and "'my host'" in remote.master_command(remote.Profile("c", "my host", "/s", "", "/p", "/e"))

# ---- connection test
def test_probe_through_fake_ssh(cluster):
    import scope
    checks = remote.evaluate_probe(cluster, remote.run_script(cluster, remote.probe_script(cluster)), scope.__version__)
    by = {c.name: c for c in checks}
    assert by["SSH connection and login shell"].status == "ok"
    assert by["SCOPE on the cluster"].status == "ok" and by["Cluster environment file"].status == "ok"
    assert by["Folder layout"].status == "ok" and by["Project folder"].status == "ok"
    assert by["Scheduler"].status == "warn"                                   # the stand-in cluster environment is a local one
    assert not any(c.status == "fail" for c in checks)

def test_probe_reports_missing_scope_and_env(cluster):
    bad = remote.Profile(**{**cluster.__dict__, "scope_bin": "/nonexistent/bin/scope"})
    by = {c.name: c for c in remote.evaluate_probe(bad, remote.run_script(bad, remote.probe_script(bad)))}
    assert by["SCOPE on the cluster"].status == "fail"
    gone = remote.Profile(**{**cluster.__dict__, "remote_env": cluster.remote_root + "/nope.npy"})
    by = {c.name: c for c in remote.evaluate_probe(gone, remote.run_script(gone, remote.probe_script(gone)))}
    assert by["Cluster environment file"].status == "fail"

def test_probe_flags_a_different_folder_layout(cluster, tmp_path):
    other = remote.Profile(**{**cluster.__dict__, "remote_root": str(tmp_path)})           # project folder that is not the parent of the environment's folders
    by = {c.name: c for c in remote.evaluate_probe(other, remote.run_script(other, remote.probe_script(other)))}
    assert by["Folder layout"].status == "fail" and "systems" in by["Folder layout"].detail     # every run would stop in scope set_path (reported)

def test_connection_failure_gives_a_hint(cluster, monkeypatch):
    monkeypatch.setenv("FAKE_SSH_FAIL", "1")
    checks = remote.evaluate_probe(cluster, remote.run_script(cluster, remote.probe_script(cluster)))
    assert len(checks) == 1 and checks[0].status == "fail" and "Connection refused" in checks[0].detail and "terminal command" in checks[0].detail

def test_version_mismatch_is_a_warning(cluster):
    by = {c.name: c for c in remote.evaluate_probe(cluster, remote.run_script(cluster, remote.probe_script(cluster)), "0.0.1")}
    assert by["SCOPE on the cluster"].status == "warn"

# ---- sync
def test_upload_dry_run_then_upload_skips_heavy_files(cluster, local, tmp_path):
    env, info = local
    open(os.path.join(info.sources_path, "water", "big.wfc1"), "w").write("x")                # must be excluded
    inp = tmp_path / "opt.scope"; inp.write_text("&environment\n/\n"); 
    assert remote.run_script(cluster, remote.remote_dirs_script(cluster, "water")).ok
    items = remote.upload_items(cluster, info, "water", [str(inp)])
    dry = remote.sync(items, dry_run=True)
    assert all(r.ok for _, r, _ in dry), [r.stderr for _, r, _ in dry]
    assert not os.path.exists(os.path.join(cluster.remote_root, "Systems", "water", "water.npy"))      # a dry run copies nothing
    assert any("water.xyz" in l for kind, _, lines in dry if kind == "sources" for l in lines)
    done = remote.sync(items, dry_run=False)
    assert all(r.ok for _, r, _ in done), [r.stderr for _, r, _ in done]
    assert os.path.isfile(os.path.join(cluster.remote_root, "Systems", "water", "water.npy"))
    assert os.path.isfile(os.path.join(cluster.remote_root, "Sources", "water", "water.xyz")) and not os.path.exists(os.path.join(cluster.remote_root, "Sources", "water", "big.wfc1"))
    assert os.path.isfile(os.path.join(cluster.remote_root, "inputs", "opt.scope"))

def test_run_on_the_cluster_then_download(cluster, local, tmp_path):
    env, info = local
    inp = tmp_path / "opt.scope"
    inp.write_text("&environment\n   requested_procs = 2\n/\n&options\n   want_submit = False\n/\n&job_data\n   branch = 'demo'\n   workflow = '*'\n   job = 'opt'\n   hierarchy = 1\n   requisites = []\n   constrains = ['self']\n/\n&qc_data\n   software = 'g16'\n   comp_type = 'opt'\n/\n")
    assert remote.run_script(cluster, remote.remote_dirs_script(cluster, "water")).ok
    assert all(r.ok for _, r, _ in remote.sync(remote.upload_items(cluster, info, "water", [str(inp)]), dry_run=False))
    script = remote.run_script_text(cluster, "water", [cluster.remote_root + "/inputs/opt.scope"])
    assert "set_path" in script and script.index("set_path") < script.index(" run ")
    res = remote.run_script(cluster, script, timeout=120)
    assert res.ok, res.stdout + res.stderr
    assert "MANUAL ATTENTION" in res.stdout
    assert os.path.isdir(os.path.join(cluster.remote_root, "Computations", "water", "demo"))
    dl = remote.download_items(cluster, info, "water")
    dry = remote.sync(dl, dry_run=True)
    assert all(r.ok for _, r, _ in dry), [r.stderr for _, r, _ in dry]
    assert all(r.ok for _, r, _ in remote.sync(dl, dry_run=False))
    assert os.path.isfile(os.path.join(info.systems_path, "water", "water.npy"))

def test_script_quotes_everything():
    p = remote.Profile("c", "h", "/home/u/my bin/scope", "", "/p/a'b", "/e")                  # not valid as a profile, but the script must still not break out
    text = remote.run_script_text(p, "water", ["/p/in put.scope"])
    assert "'/home/u/my bin/scope'" in text and "'/p/in put.scope'" in text and "'\"'\"'" in text


def test_paths_with_tilde_work_end_to_end(tmp_path, monkeypatch):
    """The cluster home is this computer's (fake) HOME: `~/proj` must reach the same folder in every command."""
    home = tmp_path / "home"
    env, info = backend.create_environment("cl", str(home / "cproj" / "Sources"), str(home / "cproj" / "Systems"), str(home / "cproj" / "Computations"), str(home / "cproj"))
    p = remote.Profile("t", "fakehost", os.path.join(os.path.dirname(sys.executable), "scope"), "", "~/cproj", "~/cproj/" + os.path.basename(info.filepath))
    assert remote.shell_path("~/cproj") == '"$HOME"/cproj' and remote.shell_path("~") == '"$HOME"' and remote.shell_path("/a b") == "'/a b'"
    by = {c.name: c for c in remote.evaluate_probe(p, remote.run_script(p, remote.probe_script(p)))}
    assert by["Project folder"].status == "ok" and by["Cluster environment file"].status == "ok" and by["Folder layout"].status == "ok"
    assert remote.run_script(p, remote.remote_dirs_script(p, "water")).ok and os.path.isdir(home / "cproj" / "Systems" / "water")
    assert remote.expand_home("~/x", "/h/u") == "/h/u/x" and remote.expand_home("/abs", "/h/u") == "/abs"

def test_field_problems_name_each_field():
    p = remote.field_problems(remote.Profile("", "", "", "", "", ""))
    assert set(p) == {"name", "host", "scope_bin", "root", "env"}
    assert remote.field_problems(remote.Profile("c", "h", "/s", "", "~/p", "~/p/e.npy")) == {}
    assert "root" in remote.field_problems(remote.Profile("c", "h", "/s", "", "my folder", "/e"))

# ---- the three lights
def info_with(**software):
    return {"scope_version": "1.0.1", "env_exists": True, "env": {"object_type": "environment", "name": "cl"}, "software": software}

QE_OK = {"status": "available", "module": "qe/7.0", "module_ok": True, "executable": "/opt/qe/bin/pw.x", "launcher": "mpirun", "mpi_family": "Open MPI", "candidates": ["mpirun"], "warnings": []}
G16_OK = {"status": "available", "module": "gaussian/16", "module_ok": True, "executable": "/opt/g16/g16", "launcher": "g16", "mpi_family": None, "candidates": [], "warnings": []}

def test_lights_are_in_priority_order_and_green_when_all_found():
    lights = remote.lights_from_probe(info_with(qe=QE_OK, g16=G16_OK))
    assert [l.name for l in lights] == ["SCOPE", "Quantum ESPRESSO", "Gaussian 16"] and [l.state for l in lights] == ["green"] * 3
    assert "pw.x at /opt/qe/bin/pw.x" in lights[1].detail and "mpirun" in lights[1].detail

def test_lights_states_follow_scope_matching():
    grey = remote.lights_from_probe(info_with(qe={"status": "not_configured"}, g16=G16_OK))
    assert grey[1].state == "grey" and grey[1].short == "not set" and "scope config" in grey[1].detail and grey[2].state == "green"
    red = remote.lights_from_probe(info_with(qe={**QE_OK, "status": "inconclusive", "module_ok": False}, g16={**G16_OK, "status": "unavailable"}))
    assert red[1].state == "red" and "module load qe/7.0" in red[1].detail and red[2].state == "red" and "not in the path" in red[2].detail
    amber = remote.lights_from_probe(info_with(qe={**QE_OK, "launcher": None, "warnings": ["No launcher candidates found."]}, g16={"status": "inconclusive", "module": "gaussian/16", "module_ok": True, "warnings": ["Inspection incomplete."]}))
    assert amber[1].state == "amber" and "no MPI launcher" in amber[1].short and amber[2].state == "amber"
    assert remote.lights_from_probe(info_with(qe={"status": "error", "module": "qe/7.0", "error": "boom"}, g16=G16_OK))[1].state == "red"

def test_lights_when_scope_or_connection_is_missing():
    broken = remote.lights_from_probe({"scope_error": "ModuleNotFoundError: scope"})
    assert broken[0].state == "red" and broken[1].state == "grey" and broken[2].state == "grey"
    assert [l.state for l in remote.lights_from_probe({})] == ["grey"] * 3
    noenv = remote.lights_from_probe({"scope_version": "1.0.1", "env_exists": False})
    assert noenv[0].state == "amber" and "scope config" in noenv[0].detail and noenv[1].state == "grey"

def test_unavailable_software_names_the_inputs(tmp_path):
    class R:                                                                   # minimal stand-in for an InputReport
        def __init__(self, path, software, ok=True): self.path, self.software, self.ok = path, software, ok
    lights = remote.lights_from_probe(info_with(qe={"status": "not_configured"}, g16={**G16_OK, "module_ok": False}))
    msgs = remote.unavailable_software(lights, [R("/x/a.scope", "qe"), R("/x/b.scope", "g16"), R("/x/c.scope", "qe", ok=False)])
    assert len(msgs) == 2 and "a.scope needs Quantum ESPRESSO" in msgs[0] and "b.scope needs Gaussian 16" in msgs[1]
    assert remote.unavailable_software(remote.unchecked_lights(), [R("/x/a.scope", "qe")]) == []        # nothing tested yet: no claim

@pytest.fixture
def software_cluster(cluster, tmp_path, monkeypatch):
    """The stand-in cluster with `module`, `g16`, `pw.x` and `mpirun` stand-ins on the path of a login shell."""
    bin_dir = tmp_path / "swbin"; bin_dir.mkdir()
    def script(name, body): f = bin_dir / name; f.write_text("#!/bin/bash\n" + body + "\n"); f.chmod(f.stat().st_mode | stat.S_IEXEC)
    script("module", 'if [ "$1" = load ]; then case "$2" in gaussian/16|qe/7.0) exit 0;; esac; fi; echo "module: unknown $2" >&2; exit 1')
    for name in ("g16", "pw.x"): script(name, f"echo fake {name}")
    for name in ("mpirun", "mpiexec"): script(name, 'echo "mpirun (Open MPI) 4.1.4"')
    (tmp_path / "home" / ".bash_profile").write_text(f'export PATH="{bin_dir}:$PATH"\n')
    from scope.read_write import load_binary
    env = load_binary(cluster.remote_env); env.g16_module, env.qe_module = "gaussian/16", "qe/7.0"; env.save(cluster.remote_env)
    return cluster, bin_dir, env

def lights_of(profile):
    return remote.lights_from_probe(remote.parse_probe(remote.run_script(profile, remote.probe_script(profile), timeout=120).stdout))

def test_lights_through_the_probe_with_module_stand_ins(software_cluster):
    profile, bin_dir, env = software_cluster
    lights = lights_of(profile)
    assert [l.state for l in lights] == ["green", "green", "green"], [(l.name, l.state, l.detail) for l in lights]
    env.qe_module = "nope/1"; env.save(profile.remote_env)                                         # a module name that does not load
    assert [l.state for l in lights_of(profile)] == ["green", "red", "green"]
    env.qe_module = "qe/7.0"; env.g16_module = ""; env.save(profile.remote_env)                    # Gaussian not named in the environment
    assert [l.state for l in lights_of(profile)] == ["green", "green", "grey"]
    for name in ("mpirun", "mpiexec"): (bin_dir / name).write_text("#!/bin/bash\nexit 1\n")        # launchers that do not work (this computer has a real mpirun on its path, so deleting the stand-ins would not hide it)
    assert lights_of(profile)[1].state == "amber"

def test_default_stand_in_cluster_has_no_software_named(cluster):
    assert [l.state for l in lights_of(cluster)] == ["green", "grey", "grey"]
