import os
from argparse import ArgumentParser
from scope.classes_environment import Environment
from scope.read_write import load_binary, clear_screen
from scope.utils.run_task import run_task

## Exit code of `scope run` when the scheduler refused at least one job (2 is argparse's code for bad arguments, 1 an uncaught error).
EXIT_SUBMISSION_FAILED = 4

def path_exists(path):
    if not os.path.exists(path):
        raise ValueError(f'Path {path} does not exist!')
    return path

def env_exists(path):
    if not os.path.isfile(path):
        raise ValueError(f'Environment Path {path} does not exist!')
    env = load_binary(path)
    if env.object_type == "environment":
        return path
    else:
        raise ValueError(f'Path {path} is not an Environment binary file!')

def run_parser(subparsers):
    parser = subparsers.add_parser("run",help="Run a SCOPE task",description="Run a SCOPE task for a given system")
    parser.add_argument('-n',       '--env_path',   type=env_exists,   help='Path to the Environment. Script will load Source data in env.sources_path')
    parser.add_argument('-s',       '--sys_name',   help='Name of the System. SCOPE will search in the stored Environment Paths')
    parser.add_argument('-i', '-t', '--inp_path', nargs="+", type=path_exists,  help='Path to the Scope Input File(s). If more than one, you can write them in any order')
    parser.add_argument('-q', '--quiet',      help='If true, will not print the progress on screen', action='store_true')
    parser.add_argument('-v', '--verbose',    help='If true, will print extra information on screen', action='store_true')
    parser.add_argument('-e', '--errors',     help='If true, will automatically handle some common errors', action='store_true')
    parser.set_defaults(func=run)

def run(args):
    """Runs the task; returns EXIT_SUBMISSION_FAILED when the scheduler refused a job, else 0."""
    clear_screen()
    
    ###############################
    # Defines Overwrite and Debug #
    ###############################
    if   args.quiet:   debug = 0  
    elif args.verbose: debug = 2
    else:              debug = 1
    ###############################

    ## Convert to absolute paths
    args.inp_path = [os.path.abspath(ip) for ip in args.inp_path] 
    args.env_path = os.path.abspath(args.env_path)

    ## Prepare System Paths 
    env           = load_binary(args.env_path)
    args.sys_name = args.sys_name.strip()
    sys_path      = f"{env.systems_path}{args.sys_name}/{args.sys_name}.npy"

    summary = ""
    report = run_task(sys_path, args.inp_path, env, handle_errors=args.errors, debug=debug)
    if isinstance(report, str): summary += report
    failures = getattr(report, "submission_failures", [])

    print("")
    print("#################################")
    print("### MANUAL ATTENTION REQUIRED ###")
    print("#################################")
    if len(summary) > 0: print(summary)
    else:                print("No manual action required")
    print("#################################")
    if failures:
        print(f"SCOPE RUN: the scheduler refused {len(failures)} job(s); exiting with code {EXIT_SUBMISSION_FAILED}.")
        return EXIT_SUBMISSION_FAILED
    return 0

if __name__ == "__main__":
    run()
