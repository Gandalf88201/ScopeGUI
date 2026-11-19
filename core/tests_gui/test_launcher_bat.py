"""Static checks of scope-gui.bat. The script itself can only run on Windows; these checks catch the mistakes that are possible anywhere:
wrong line endings (labels and goto break with bare LF), a missing option, a label that is jumped to but never defined."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BAT  = (ROOT / "scope-gui.bat").read_bytes()
TEXT = BAT.decode("utf-8")

def test_line_endings_are_crlf_and_pinned_in_gitattributes():
    assert b"\r\n" in BAT and BAT.count(b"\n") == BAT.count(b"\r\n")                          # every line ends with CRLF
    attrs = (ROOT / ".gitattributes").read_text()
    assert "scope-gui.bat text eol=crlf" in attrs and "scope-gui text eol=lf" in attrs

def test_every_goto_and_call_target_exists_and_no_label_is_defined_twice():
    labels = re.findall(r"^:([A-Za-z_0-9]+)\s*$", TEXT, re.M)
    assert len(labels) == len(set(l.lower() for l in labels))
    targets = set(t.lower() for t in re.findall(r"\bgoto\s+:?([A-Za-z_0-9]+)", TEXT, re.I)) | set(t.lower() for t in re.findall(r"\bcall\s+:([A-Za-z_0-9]+)", TEXT, re.I))
    targets -= {"eof"}
    assert targets <= set(l.lower() for l in labels), targets - set(l.lower() for l in labels)

def test_same_options_and_settings_as_the_shell_launcher():
    sh = (ROOT / "scope-gui").read_text()
    for token in ("--where", "--reinstall", "SCOPE_GUI_HOME", "SCOPE_GUI_PYTHON", "installed.stamp", "pip install", "-e", "[gui]", "scope.cli.main", "import cell2mol",
                  "cell2mol @ git+https://github.com/lcmd-epfl/cell2mol.git@55649ba5f444895846a5d049adcb056c01bb0421"):
        assert token in TEXT and token in sh, token
    assert "-3.12" in TEXT and "(3,12)" in TEXT and "LOCALAPPDATA" in TEXT                    # Python 3.12 only, per-user folder
