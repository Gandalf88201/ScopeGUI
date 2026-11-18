"""Connect…: opening the shared SSH connection from the GUI, answering a password, a verification code or the host-key question.
A fake ssh asks on its controlling terminal exactly as the real one does, so the pseudo-terminal relay is tested for real."""
import os
import stat
import subprocess
import pytest
from scope.gui import remote

pytestmark = pytest.mark.skipif(not remote.can_login_here(), reason="needs a pseudo-terminal")

FAKE = r"""#!/bin/bash
case " $* " in
  *" -O check "*) [ -f "$FAKE_MASTER" ] && exit 0; echo "Control socket connect: No such file or directory" >&2; exit 255;;
  *" -O exit "*)  rm -f "$FAKE_MASTER"; exit 0;;
esac
ask() { printf "%s" "$1" > /dev/tty; }
if [ -n "${FAKE_HOSTKEY:-}" ]; then
  ask $'The authenticity of host \'fake\' can\'t be established.\nED25519 key fingerprint is SHA256:abcdef.\nAre you sure you want to continue connecting (yes/no/[fingerprint])? '
  read -r a < /dev/tty; [ "$a" = yes ] || { echo "Host key verification failed." >&2; exit 255; }
fi
for i in 1 2 3; do
  ask "me@fake's password: "
  stty -echo < /dev/tty; read -r pw < /dev/tty; stty echo < /dev/tty; echo > /dev/tty
  if [ "$pw" = "s3cret" ]; then
    if [ -n "${FAKE_CODE:-}" ]; then
      ask "Verification code: "; stty -echo < /dev/tty; read -r code < /dev/tty; stty echo < /dev/tty; echo > /dev/tty
      [ "$code" = "123456" ] || { echo "Permission denied (keyboard-interactive)." >&2; exit 255; }
    fi
    touch "$FAKE_MASTER"; exit 0
  fi
  echo "Permission denied, please try again." > /dev/tty
done
echo "me@fake: Permission denied (publickey,password)." >&2; exit 255
"""

@pytest.fixture
def login(tmp_path, monkeypatch):
    fake = tmp_path / "fake_ssh"; fake.write_text(FAKE); fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("SCOPE_GUI_SSH", str(fake)); monkeypatch.setenv("FAKE_MASTER", str(tmp_path / "master"))
    for name in ("FAKE_HOSTKEY", "FAKE_CODE"): monkeypatch.delenv(name, raising=False)
    return remote.Profile("fake", "fakehost", "/s", "", "/p", "/e", user="me", port="2122")

def script(*answers):
    """An `ask` that gives the answers in turn and records what it was asked."""
    asked, left = [], list(answers)
    def ask(context, prompt, kind): asked.append((context, prompt, kind)); return left.pop(0) if left else None
    return ask, asked

def test_password_opens_the_connection_and_it_is_reported_alive(login):
    ask, asked = script("s3cret")
    assert not remote.connection_alive(login)
    res = remote.open_connection(login, ask)
    assert res.ok and remote.connection_alive(login)
    assert [(p, k) for _, p, k in asked] == [("me@fake's password:", "secret")]

def test_wrong_password_is_asked_again_then_fails_without_leaking_it(login):
    ask, asked = script("nope-1", "nope-2", "nope-3")
    res = remote.open_connection(login, ask)
    assert not res.ok and not remote.connection_alive(login) and len(asked) == 3
    assert "Permission denied" in res.stderr and not any(w in res.stderr for w in ("nope-1", "nope-2", "nope-3"))
    assert "Permission denied, please try again." in asked[1][0]                          # the second question shows why it is asked again

def test_second_factor_is_a_second_question(login, monkeypatch):
    monkeypatch.setenv("FAKE_CODE", "1")
    ask, asked = script("s3cret", "123456")
    assert remote.open_connection(login, ask).ok and [p for _, p, _ in asked] == ["me@fake's password:", "Verification code:"]

def test_first_time_host_key_is_a_yes_no_question_with_the_fingerprint(login, monkeypatch):
    monkeypatch.setenv("FAKE_HOSTKEY", "1")
    ask, asked = script("yes", "s3cret")
    assert remote.open_connection(login, ask).ok
    context, prompt, kind = asked[0]
    assert kind == "confirm" and "SHA256:abcdef" in context + prompt and asked[1][2] == "secret"

def test_cancel_stops_ssh_and_opens_nothing(login):
    ask, asked = script()                                                                 # answers None at once
    res = remote.open_connection(login, ask)
    assert not res.ok and res.returncode == 130 and "Cancelled" in res.stderr and not remote.connection_alive(login)

def test_the_password_is_never_in_an_argument_or_the_environment(login, monkeypatch):
    seen = []; real = subprocess.Popen
    def spy(argv, *a, **k): seen.append((list(argv), dict(k.get("env") or {}))); return real(argv, *a, **k)
    monkeypatch.setattr(subprocess, "Popen", spy)
    ask, _ = script("s3cret")
    assert remote.open_connection(login, ask).ok
    assert seen and not any("s3cret" in part for argv, env in seen for part in argv + list(env.values()))
    assert "s3cret" not in os.environ.values().__repr__()

def test_disconnect_closes_it(login):
    ask, _ = script("s3cret"); assert remote.open_connection(login, ask).ok
    assert remote.close_connection(login) and not remote.connection_alive(login)

def test_the_connection_uses_the_same_socket_and_account_as_every_other_command(login):
    m = remote.master_options(login)
    assert f"ControlPath={remote.control_path()}" in m and m[m.index("-p") + 1] == "2122" and m[m.index("-l") + 1] == "me" and "BatchMode=no" in m
    assert "BatchMode=yes" in remote.ssh_options(login) and f"ControlPath={remote.control_path()}" in remote.ssh_options(login)
    assert remote.control_argv(login, "check")[-1] == "fakehost"

def test_auth_failure_is_recognised():
    assert remote.auth_failed(remote.Result(255, "", "me@h: Permission denied (publickey,password)."))
    assert not remote.auth_failed(remote.Result(255, "", "ssh: connect to host h port 22: Connection refused")) and not remote.auth_failed(remote.Result(1, "", "Permission denied"))
