import sys

def gui_parser(subparsers):
    parser = subparsers.add_parser("gui", help="Opens the graphical interface", description="Opens the SCOPE graphical interface. The first time, if PySide6 is not installed, a private virtual environment with PySide6 is created automatically (internet needed, about a minute); it is reused afterwards.")
    parser.add_argument("-n", "--env_path", help="Path to an Environment binary to open at start")
    parser.add_argument("--reset-env", action="store_true", help="Delete the private GUI environment (it is created again at the next start if PySide6 is missing)")
    parser.add_argument("--check", action="store_true", help="Build the window, print a one-line report and exit (to test an installation)")
    parser.set_defaults(func=gui)

def gui(args):
    from scope.cli import gui_env
    if args.reset_env:
        try: gui_env.remove(gui_env.env_dir()); print(f"Removed {gui_env.env_dir()}")
        except RuntimeError as exc: print(f"SCOPE: {exc}", file=sys.stderr); sys.exit(1)
    if not gui_env.pyside_available():
        argv = ["gui"] + (["-n", args.env_path] if args.env_path else []) + (["--check"] if args.check else [])
        sys.exit(gui_env.ensure_gui_python(argv, log=lambda m: print(m, file=sys.stderr, flush=True)))
    try:
        from scope.gui.window import main
    except ImportError as exc:
        print(f"The graphical interface could not load PySide6 ({exc}). If it is a missing system library, install it; otherwise reset with:  scope gui --reset-env", file=sys.stderr)
        sys.exit(1)
    sys.exit(main(args.env_path, check=args.check))
