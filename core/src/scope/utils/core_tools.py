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


def gen_run_block(run_command: str, debug: int=0) -> str:
    """Returns Bash commands that stop a calculation on USR1/TERM/INT before copying results.

    Runs the command and its local children in a separate process group.
    Allows two seconds after TERM before forcing that group to stop. Sets
    run_status=124 on interruption, otherwise 0 as in existing submissions.
    The caller copies results, cleans scratch and exits with run_status.
    SIGKILL cannot be handled; SLURM needs an advance-warning directive.
    """
    return f'''# Stop the calculation on a time warning or termination request
run_status=0
calculation_pid=
stop_calculation() {{
    trap '' USR1 TERM INT
    run_status=124
    echo "SCOPE: Interrupted; returning partial output"
    if [ -n "$calculation_pid" ]; then
        kill -TERM -- "-$calculation_pid" 2>/dev/null

        # Allow up to two seconds for the calculation and local children to stop
        for attempt in {{1..20}}; do
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
trap stop_calculation USR1 TERM INT

# Start the calculation in its own process group, then wait for it
set -m
{run_command} &
calculation_pid=$!
set +m
if [ "$run_status" -ne 0 ]; then stop_calculation; fi  # Warning during startup
wait "$calculation_pid" 2>/dev/null

# The calculation has stopped; allow the result-copy blocks below to finish
trap '' USR1 TERM INT
'''
