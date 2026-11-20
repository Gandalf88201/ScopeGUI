"""Point 5: 'worked' is not 'finished and converged'. Point 7: energies are compared only when every energy setting and the charge agree."""
from types import SimpleNamespace as NS
import pytest

from scope.gui import results

def comp(status="worked", finished=None, good=None, job=None, qc=None, step=1, run=1):
    c = NS(_job=job or NS(name="opt", job_setup="regular"), run_number=run, step=step, status=status, isregistered=True, out_path="", inp_path="", software="g16", type="opt",
           qc_data=qc or NS(software="g16", functional="pbe", basis="sto-3g", istate="initial", fstate="opt"), elapsed_time=1.0, cpu_time=1.0)
    if finished is not None: c.isfinished = finished
    if good is not None: c.isgood = good
    return c

def state(name, energy, comps):
    return NS(name=name, computations=list(comps), results={"energy": NS(value=energy, units="au")}, freqs_cm=[], isminimum=None)

# ---- point 5
def test_worked_needs_a_normal_end_and_convergence():
    assert results.comp_group(comp(finished=True, good=True)) == "ok"
    assert results.comp_group(comp(finished=False, good=True)) == "partial"                      # results extracted, program did not end normally
    assert results.comp_group(comp(finished=True, good=False)) == "unconverged"                  # e.g. optimisation not converged
    assert results.comp_group(comp()) == "ok"                                                     # an older file without the flags is not lowered
    assert results.comp_group(comp(status="aborted", finished=True, good=True)) == "err"          # a bad status is never raised

def test_rep_opt_newest_step_follows_the_job_convergence():
    job = NS(name="vc", job_setup="rep_opt", isconverged=False)
    old, new = comp(job=job, finished=True, good=True, step=1), comp(job=job, finished=True, good=True, step=2)
    job.computations = [old, new]
    assert results.comp_group(old, job) == "ok" and results.comp_group(new, job) == "unconverged"
    job.isconverged = True; assert results.comp_group(new, job) == "ok"

def test_states_and_texts_show_the_lowered_group():
    src = NS(name="w", object_subtype="molecule", formula="H2O", charge=0, states=[state("opt", -76.0, [comp(finished=True, good=False)])])
    row = results.state_rows(NS(sources=[src]))[0]
    assert row.group == "unconverged" and row.charge == 0
    c = results.CompRow("b", "w", "opt", 1, 1, "g16", "opt", "initial", "opt", "worked", "partial", 1.0, 1.0, "", "", False, False, False, True)
    assert "did not finish" in c.status_text

def test_comps_csv_has_finished_and_converged_columns():
    c = results.CompRow("b", "w", "opt", 1, 1, "g16", "opt", "initial", "opt", "worked", "unconverged", 1.0, 1.0, "", "x.log", False, False, True, False)
    lines = results.comps_csv([c]).splitlines()
    assert "finished,converged" in lines[0] and ",yes,no,unconverged," in lines[1]

# ---- point 7
def qe(pp="vanderbilt", mix_beta=0.7):
    return NS(software="qe", functional="pbe", pp_library=pp, is_hubbard=False, uterm=None, is_grimme=False, grimme_type="d3bj", version=7.0, mix_beta=mix_beta)

def test_qe_pseudopotential_library_is_part_of_the_method():
    a, b = results.method_of(NS(qc_data=qe("vanderbilt"))), results.method_of(NS(qc_data=qe("sssp")))
    assert a == "qe pbe vanderbilt" and b == "qe pbe sssp" and a != b
    assert results.method_of(NS(qc_data=qe(mix_beta=0.3))) == a                                      # a mixing setting does not change the energy
    hub = NS(software="qe", functional="pbe", pp_library="sssp", is_hubbard=True, uterm=2.35, is_grimme=True, grimme_type="d3bj")
    assert results.method_of(NS(qc_data=hub)) == "qe pbe sssp +U=2.35 +d3bj"
    g = NS(software="g16", functional="b3lyp", basis="def2svp", is_grimme=False, grimme_type="d3bj", unrestricted=True, ultrafine_grid=False)
    assert results.method_of(NS(qc_data=g)) == "g16 b3lyp def2svp unrestricted"

def test_different_pp_library_gets_no_common_reference():
    src = lambda name, qc, e: NS(name=name, object_subtype="cell", formula="Fe2", charge=0, states=[state("relax", e, [comp(qc=qc, finished=True, good=True)])])
    obj = NS(sources=[src("hs", qe("vanderbilt"), -100.0), src("ls", qe("sssp"), -100.5), src("ls2", qe("vanderbilt"), -100.2)])
    rel = results.relative_energies(results.state_rows(obj))
    assert ("ls", "relax") not in rel and abs(rel[("hs", "relax")] - 0.2) < 1e-12 and rel[("ls2", "relax")] == 0

def test_charge_separates_but_spin_does_not():
    src = lambda name, q, e: NS(name=name, object_subtype="molecule", formula="Fe", charge=q, states=[state("opt", e, [comp(finished=True, good=True)])])
    rows = results.state_rows(NS(sources=[src("hs", 2, -10.0), src("ls", 2, -10.1), src("ox", 3, -9.0)]))
    rel = results.relative_energies(rows)
    assert ("hs", "opt") in rel and ("ls", "opt") in rel and ("ox", "opt") not in rel             # HS/LS of one charge: compared
    cmp = [results.CompareRow("A", r.source, r.state, r.formula, r.method, r.energy, "", r.charge) for r in rows]
    assert ("A", "ox", "opt") not in results.compare_relative(cmp)
