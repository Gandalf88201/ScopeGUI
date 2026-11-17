import sys

def gui_parser(subparsers):
    parser = subparsers.add_parser("gui", help="Opens the graphical interface", description="Opens the SCOPE graphical interface. Requires the optional dependency PySide6: pip install 'scope-qc[gui]'")
    parser.add_argument("-n", "--env_path", help="Path to an Environment binary to open at start")
    parser.set_defaults(func=gui)

def gui(args):
    try:
        from scope.gui.window import main
    except ImportError as exc:
        print(f"The graphical interface needs PySide6 ({exc}). Install it with:  pip install 'scope-qc[gui]'", file=sys.stderr)
        sys.exit(1)
    sys.exit(main(args.env_path))
