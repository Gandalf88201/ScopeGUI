"""Selective, safe download of cluster results into the workspace's folders (through the stand-in ssh and rsync)."""
import os
import shutil
import subprocess
import time
import pytest

from scope.gui import backend, remote, transfer
from test_remote import isolated, cluster, local, WATER                    # noqa: F401  (fixtures)

@pytest.fixture
def results(cluster, local):
    """A cluster project whose run produced files for 'water', and the matching local workspace folders."""
    p = cluster; env, info = local
    comp = os.path.join(p.remote_root, "Computations", "water", "demo"); os.makedirs(os.path.join(comp, "sub"), exist_ok=True)
    for name, size in (("opt.log", 2000), ("opt.com", 300), ("water.chk", 5000), ("sub/freq.log", 1500), ("huge.out", 3_000_000)):
        with open(os.path.join(comp, name), "wb") as fh: fh.write(b"x" * size)
    os.symlink("/etc/hosts", os.path.join(comp, "link_to_elsewhere"))                     # a link on the cluster is never followed
    os.makedirs(os.path.join(p.remote_root, "Systems", "water"), exist_ok=True)
    with open(os.path.join(p.remote_root, "Systems", "water", "water.npy"), "wb") as fh: fh.write(b"cluster system")
    return p, info

def test_names_that_leave_the_destination_are_refused():
    assert transfer.safe_rel("demo/opt.log") and transfer.safe_rel("a b/c.log")
    for bad in ("", "/etc/passwd", "../x", "demo/../../x", "~/x", "a\nb"): assert not transfer.safe_rel(bad), bad

def test_listing_compare_and_default_selection(results):
    p, info = results
    listing = transfer.parse_listing(remote.run_script(p, transfer.listing_script(p, "water")).stdout)
    names = {f[0] for f in listing["files"]}
    assert listing["exists"] and listing["system"][0] == len(b"cluster system")
    assert names == {"demo/opt.log", "demo/opt.com", "demo/water.chk", "demo/sub/freq.log", "demo/huge.out"}          # the link is not listed
    here = os.path.join(info.computations_path, "water", "demo"); os.makedirs(here, exist_ok=True)
    shutil.copy2(os.path.join(p.remote_root, "Computations", "water", "demo", "opt.com"), os.path.join(here, "opt.com"))   # identical copy
    with open(os.path.join(here, "opt.log"), "wb") as fh: fh.write(b"edited here")
    future = time.time() + 3600; os.utime(os.path.join(here, "opt.log"), (future, future))                          # newer here
    files = {f.rel: f for f in transfer.compare(listing, info, "water", max_mb=1)}
    assert files["demo/opt.com"].status == "same" and not files["demo/opt.com"].selected
    assert files["demo/opt.log"].status == "newer here" and not files["demo/opt.log"].selected                      # a newer local file is never proposed
    assert files["demo/water.chk"].heavy and not files["demo/water.chk"].selected                                     # heavy working file: listed, unticked
    assert files["demo/huge.out"].status == "new" and not files["demo/huge.out"].selected                            # larger than the limit: unticked
    assert files["demo/sub/freq.log"].selected

def test_only_the_chosen_files_are_copied_nothing_local_is_deleted_and_the_system_file_is_backed_up(results):
    p, info = results
    here = os.path.join(info.computations_path, "water"); os.makedirs(here, exist_ok=True)
    open(os.path.join(here, "only_here.txt"), "w").write("mine")
    local_npy = os.path.join(info.systems_path, "water", "water.npy"); before = open(local_npy, "rb").read()
    out = transfer.download(p, info, "water", ["demo/opt.log", "demo/sub/freq.log"], with_system=True)
    assert out["files"].ok, out["files"].stderr
    assert os.path.getsize(os.path.join(here, "demo", "opt.log")) == 2000 and os.path.isfile(os.path.join(here, "demo", "sub", "freq.log"))
    assert not os.path.exists(os.path.join(here, "demo", "huge.out")) and not os.path.exists(os.path.join(here, "demo", "water.chk"))
    assert open(os.path.join(here, "only_here.txt")).read() == "mine"                                                # never deleted
    assert open(local_npy, "rb").read() == b"cluster system" and "kept as" in out["system"]
    backups = [f for f in os.listdir(os.path.dirname(local_npy)) if f.startswith("water.npy.bak-")]
    assert len(backups) == 1 and open(os.path.join(os.path.dirname(local_npy), backups[0]), "rb").read() == before
    assert not os.path.exists(transfer.incoming_path(info, "water"))

def test_a_failed_system_copy_leaves_the_local_system_file_alone(results):
    p, info = results
    os.remove(os.path.join(p.remote_root, "Systems", "water", "water.npy"))
    local_npy = os.path.join(info.systems_path, "water", "water.npy"); before = open(local_npy, "rb").read()
    out = transfer.download(p, info, "water", [], with_system=True)
    assert "not copied" in out["system"] and open(local_npy, "rb").read() == before

def test_the_command_line_does_the_same_download(results):
    p, info = results
    lst = transfer.list_file("water", ["demo/opt.com", "../escape", "demo/sub/freq.log"])
    assert open(lst).read().splitlines() == ["demo/opt.com", "demo/sub/freq.log"]                                       # unsafe names never reach the list
    cmd = transfer.command_line(p, info, "water", lst)
    assert f"--files-from={lst}" in cmd and os.path.join(info.computations_path, "water") in cmd and "--partial" in cmd
    done = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert os.path.isfile(os.path.join(info.computations_path, "water", "demo", "opt.com")) and not os.path.exists(os.path.join(info.computations_path, "water", "demo", "opt.log"))

def test_not_enough_free_space_is_reported(local, monkeypatch):
    env, info = local
    monkeypatch.setattr(shutil, "disk_usage", lambda path: shutil._ntuple_diskusage(10**12, 10**12 - 10**9, 10**9))      # 1 GB free
    assert transfer.space_problem(info, 500_000_000) == ""
    assert "Not enough free space" in transfer.space_problem(info, 2_000_000_000)

def test_human_sizes():
    assert [transfer.human(n) for n in (5, 1500, 2_500_000, 3_200_000_000)] == ["5 B", "1.5 kB", "2.5 MB", "3.2 GB"]
