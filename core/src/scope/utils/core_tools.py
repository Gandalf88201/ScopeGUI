#!/usr/bin/env python3
import sys
import os

def get_status(sys_path: str, core: str, branch_keyword, debug: int=0):
    if sys_path[-1] != '/' : sys_path += '/'
    ##########################################################
    ## Keep in mind that here, the system is not yet loaded ##
    ## The status is set based, only, on the files present  ##
    ##########################################################
    ## We do not want to load the system to save time       ##
    ##########################################################

    status = "active"

    ## If system file is not present
    if not os.path.isfile(sys_path+core+'/'+core+".sys"):
        if debug > 1: print(f"System file of {core} not found in {sys_path+core+'/'+core+'.sys'}")
        return "absent"

    ## Otherwise..
    if os.path.isfile(sys_path+core+'/'+"TERMINATED"):  return "terminated"

    ## If one branch keyword is given
    if type(branch_keyword) == str:
        if branch_keyword.lower() == "isolated" and os.path.isfile(sys_path+core+'/'+"ISO_FINISHED"):  return "finished"
        elif branch_keyword.lower() == "solid" and os.path.isfile(sys_path+core+'/'+"SOLID_FINISHED"): return "finished" 

    ## If more than one branch keyword is given
    elif type(branch_keyword) == list:
        sk = []
        for bk in branch_keyword:
            if bk.lower() == "isolated":
                if os.path.isfile(sys_path+core+'/'+"ISO_FINISHED"): sk.append("finished")
                else:                                                sk.append("active")
            elif bk.lower() == "solid":
                if os.path.isfile(sys_path+core+'/'+"SOLID_FINISHED"): sk.append("finished")
                else:                                                  sk.append("active")
        if "active" in sk: return "active"
        else:              return "finished"

    else: print("GET_STATUS: I could not understand branch_keyword:", branch_keyword)
    return "active"


def get_attempt_number(comp: object, origin: str, debug: int=0) -> int:
    """Returns the next recovery attempt number for an origin in a continuation chain.

    Counts matching origins in comp._job.computations with the same keyword
    and step and run_number <= comp.run_number. Includes the current
    Computation when its origin matches. Untagged Computations do not count.
    This is logical creation order, not submission or execution chronology;
    resubmitting a Computation does not consume another attempt.

    Parameters:
        comp (object): Current Computation, attached to its Job.
        origin (str): Recovery identifier, such as 'g16_ts_recovery_standard'.
        debug (int): Verbosity level.

    Returns:
        int: One plus the matching count; 1 identifies the first recovery attempt.
    """
    attempt_number = 1
    for candidate in comp._job.computations:
        # Computations without origin
        if getattr(candidate,'origin',None) != origin:
            continue
        # Computations with other keywords or step numbers
        if candidate.keyword != comp.keyword or candidate.step != comp.step:
            continue
        # Computations with a latter run_number
        if candidate.run_number > comp.run_number:
            continue
        attempt_number += 1
    if debug > 0: print(f'GET_ATTEMPT_NUMBER: {origin}: next attempt {attempt_number}, step={comp.step}, keyword={comp.keyword!r}')
    return attempt_number


def get_slurm_time_limit(queue: object, debug: int=0) -> int | str | None:
    """The wall time (minutes, or a Slurm time string) to request with #SBATCH --time for a job on `queue`.

    In order: the input's time_limit (&environment), the partition's MaxTime, its DefaultTime, then the
    Environment's fallback_time_limit. A partition with MaxTime=UNLIMITED and no DefaultTime gives neither,
    and some clusters then refuse any job without --time; fallback_time_limit covers that case. None when
    none is known: a warning is printed and no --time is written.
    """
    env = queue._environment
    for value in (getattr(env,'time_limit',None), getattr(queue,'time_limit',None),
                  getattr(queue,'default_time_limit',None), getattr(env,'fallback_time_limit',None)):
        if value is not None and value != 'none': return value
    print(f"GEN_SUBFILE: WARNING: no wall time known for queue {queue.name} (its maximum is unlimited and it has no default); "
          "the scheduler may reject the job. Set time_limit in &environment, or fallback_time_limit in the Environment.")
    return None


def get_slurm_signal_time(time_limit: int | str | None, debug: int=0) -> int:
    """Returns advance-warning seconds for a SLURM wall-time limit.

    Uses 10% of the limit, between 10 and 60 seconds. Numeric values represent
    minutes; formatted strings use slurm_time_to_seconds(). None or an
    unlimited queue uses 60 seconds. SLURM may deliver its warning early.
    """
    from scope.parse_general import slurm_time_to_seconds
    if time_limit is None: return 60
    if isinstance(time_limit,str) and not time_limit.isdigit():
        if '-' in time_limit and ':' not in time_limit: time_limit += ':00:00'
        elif '-' not in time_limit and time_limit.count(':') == 1: time_limit = '0:'+time_limit
        seconds = slurm_time_to_seconds(time_limit)
    else:
        seconds = int(time_limit)*60
    return min(60,max(10,seconds//10)) if seconds > 0 else 60


def gen_sge_time_directives(queue: object, debug: int=0) -> tuple[str,str]:
    """Returns SGE wall-time directives and the signal that triggers result copying.

    Uses the Environment's requested time_limit, or the Queue's maximum, in
    minutes. Omits h_rt when neither limit is available. Older Queues collect
    missing settings when possible; unavailable settings use -notify/USR2.

    Without a finite soft limit, -notify requests USR2 before termination; USR1
    then denotes suspension. A finite s_rt instead uses USR1 for termination
    warning and omits -notify to avoid that ambiguity. Its value is reduced when
    necessary to leave copying time before h_rt. The queue's notify interval
    controls the grace period; zero or unavailable intervals cannot guarantee it.
    Assumes SGE's standard warning signals.
    """
    from scope.classes_queue import _queue_time_to_seconds
    if hasattr(queue,'update_settings'): queue.update_settings(debug=max(debug-1,0))

    # 1) Converts the requested and configured wall times from minutes to seconds.
    time_limit = getattr(queue._environment,'time_limit',None)
    if time_limit is None: time_limit = getattr(queue,'time_limit',None)
    soft_limit = getattr(queue,'soft_time_limit',None)
    notify     = getattr(queue,'notify_time',None)
    if isinstance(time_limit,str): time_limit = _queue_time_to_seconds(time_limit,'slurm')
    elif time_limit is not None:   time_limit = int(time_limit*60)
    if isinstance(soft_limit,str): soft_limit = _queue_time_to_seconds(soft_limit,'slurm')
    elif soft_limit is not None:   soft_limit = int(soft_limit*60)

    # 2) Selects the appropriate SGE warning without confusing it with suspension.
    directives = []
    if soft_limit is None:
        directives.append('#$ -notify')
        warning_signal = 'USR2'
    else:
        warning_signal = 'USR1'
        if time_limit is not None:
            margin = int(notify) if notify is not None and notify > 0 else min(60,max(1,time_limit//10))
            soft_limit = min(soft_limit,max(1,time_limit-margin))

    # 3) Writes hours without a day prefix, as required by SGE.
    for resource, seconds in [('h_rt',time_limit),('s_rt',soft_limit)]:
        if seconds is not None:
            hours, remainder = divmod(seconds,3600)
            minutes, seconds = divmod(remainder,60)
            directives.append(f'#$ -l {resource}={hours:02d}:{minutes:02d}:{seconds:02d}')
    if debug > 0: print(f'GEN_SGE_TIME_DIRECTIVES: {queue.name}: warning={warning_signal}, notify={notify} s')
    return '\n'.join(directives), warning_signal


def gen_run_block(run_command: str, warning_signal: str='USR1', notify_time: float | None=None, debug: int=0) -> str:
    """Returns Bash commands that stop a calculation before copying partial results.

    Runs the command and its local children in a separate process group.
    Allows at most two seconds after TERM before forcing that group to stop,
    using at most half of notify_time when that interval is known. Sets
    run_status=124 on interruption, otherwise 0 as in existing submissions.
    The caller copies results, cleans scratch and exits with run_status.
    warning_signal is USR1 for SLURM and SGE soft limits, or USR2 for SGE
    -notify. With USR2, suspension warnings on USR1 are ignored. TERM/INT
    also trigger copying. SIGKILL cannot be handled; scheduler grace periods
    must allow enough time to stop the calculation and copy its files.
    """
    if warning_signal not in ('USR1','USR2'): raise ValueError('GEN_RUN_BLOCK: warning_signal must be USR1 or USR2')
    signals       = f'{warning_signal} TERM INT'
    stop_timeout  = 2 if notify_time is None else min(2,max(0,notify_time/2))
    stop_checks   = int(stop_timeout*10)
    suspension    = "# Leave SGE suspension warnings to the scheduler\ntrap '' USR1\n\n" if warning_signal == 'USR2' else ''
    return suspension + f'''# Stop the calculation on a time warning or termination request
run_status=0
calculation_pid=
stop_calculation() {{
    trap '' {signals}
    run_status=124
    echo "SCOPE: Interrupted; returning partial output"
    if [ -n "$calculation_pid" ]; then
        kill -TERM -- "-$calculation_pid" 2>/dev/null

        # Allow up to {stop_checks/10:g} seconds for the calculation and local children to stop
        for ((attempt=0; attempt<{stop_checks}; attempt++)); do
            if ! kill -0 -- "-$calculation_pid" 2>/dev/null; then break; fi
            sleep 0.1
        done
        if kill -0 -- "-$calculation_pid" 2>/dev/null; then
            echo "SCOPE: Calculation did not stop; forcing termination"
            kill -KILL -- "-$calculation_pid" 2>/dev/null
        fi
        wait "$calculation_pid" 2>/dev/null
    fi
}}
trap stop_calculation {signals}

# Start the calculation in its own process group, then wait for it
set -m
{run_command} &
calculation_pid=$!
set +m
if [ "$run_status" -ne 0 ]; then stop_calculation; fi  # Warning during startup
wait "$calculation_pid" 2>/dev/null

# The calculation has stopped; allow the result-copy blocks below to finish
trap '' {signals}
'''
