"""Window that says whether newer SCOPE code is available, lists it, and applies it when that is safe (see scope.gui.updates)."""
import html
import time
from PySide6.QtCore    import Qt
from PySide6.QtGui     import QFontDatabase
from PySide6.QtWidgets import QCheckBox, QDialog, QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit, QPushButton, QVBoxLayout
from scope.gui import theme, updates

class UpdatesDialog(QDialog):
    """Details of the last check, the daily-check setting (the consent), Check now, Update and Restart.

    The window does the work (MainWindow.check_updates, apply_update, restart); this dialog shows its state and follows it.
    """
    def __init__(self, parent, window):
        super().__init__(parent); self.window_ = window
        self.setWindowTitle("SCOPE updates"); self.resize(820, 560)
        self.head = QLabel(); self.head.setTextFormat(Qt.RichText); self.head.setWordWrap(True); self.head.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.auto = QCheckBox("Check for updates once a day (asks GitHub what is new; your files are not changed)")
        self.auto.setToolTip("Runs git fetch in the SCOPE folder at most once a day. Nothing is downloaded into your files until you press Update.")
        self.log = QPlainTextEdit(); self.log.setReadOnly(True); self.log.setLineWrapMode(QPlainTextEdit.NoWrap)
        mono = QFontDatabase.systemFont(QFontDatabase.FixedFont); mono.setPointSize(max(mono.pointSize(), 12)); self.log.setFont(mono)
        self.message = QLabel(); self.message.setWordWrap(True); self.message.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.check_btn, self.update_btn, self.restart_btn, close = QPushButton("Check now"), QPushButton("Update"), QPushButton("Restart the window"), QPushButton("Close")
        self.update_btn.setProperty("primary", True); self.restart_btn.setProperty("primary", True); self.restart_btn.hide()
        self.update_btn.setToolTip("Moves this copy forward to the branch it follows (git merge --ff-only). Only offered when no local change or commit would be affected.")
        self.restart_btn.setToolTip("Closes this window and opens it again with the new code. Runs keep going: they do not depend on the window.")
        row = QHBoxLayout(); row.addWidget(self.check_btn); row.addStretch(1); row.addWidget(close); row.addWidget(self.restart_btn); row.addWidget(self.update_btn)
        lay = QVBoxLayout(self); lay.addWidget(self.head); lay.addWidget(self.auto); lay.addWidget(self.log, 1); lay.addWidget(self.message); lay.addLayout(row)
        enabled = updates.setting().get("enabled")
        self.auto.setChecked(enabled is True); self.asked = enabled is not None
        self.auto.toggled.connect(self.set_auto); self.check_btn.clicked.connect(lambda: window.check_updates(fetch=True))
        self.update_btn.clicked.connect(self.apply); self.restart_btn.clicked.connect(window.restart); close.clicked.connect(self.accept)
        window.updatesChecked.connect(self.refresh); self.refresh()

    def set_auto(self, on: bool) -> None:
        updates.save_setting(enabled=on); self.asked = True
        if on and updates.due(): self.window_.check_updates(fetch=True)
        self.window_.render_updates()

    def done(self, code: int) -> None:                                      ## closing the window answers the question: not ticked means no daily check
        if not self.asked: updates.save_setting(enabled=False); self.window_.render_updates()
        super().done(code)

    def apply(self) -> None:
        st = self.window_.update_status
        if not st or not st.can_update(): return
        t = st.followed()
        if QMessageBox.question(self, "Update SCOPE", f"Move '{st.branch}' forward by {t.behind} commit(s) to {t.ref}?\n\nNo local change is touched (there is none), and runs keep going. The new code is used after the window restarts.") != QMessageBox.Yes: return
        self.window_.apply_update()

    def refresh(self) -> None:
        w = self.window_; st = w.update_status; c = theme.colors()
        self.check_btn.setEnabled(w.update_task is None and bool(st and st.repo)); self.restart_btn.setVisible(w.updated)
        if w.update_task is not None and st is None: self.head.setText("Checking…"); self.update_btn.setEnabled(False); return
        if st is None or not st.repo:
            self.head.setText("SCOPE was not installed from a git checkout (it was installed as a package), so this window cannot check or update it. Use the way it was installed, for instance <tt>pip install -U scope-qc</tt>.")
            self.auto.setEnabled(False); self.update_btn.setEnabled(False); self.log.setPlainText(""); self.message.setText(""); return
        dirty = f' &nbsp;<span style="color:{c["warn"]}">uncommitted changes here</span>' if st.dirty else ""
        when = "checked with GitHub " + time.strftime("%Y-%m-%d %H:%M", time.localtime(st.checked)) if st.fetched else ("not checked with GitHub yet" if not updates.setting().get("last") else "from the last check with GitHub")
        self.head.setText(f"<b>This copy</b>: branch <b>{html.escape(st.branch or '(no branch)')}</b>, commit {st.head} of {st.date}{dirty}<br><span style='color:{c['sub']}'>{html.escape(st.repo)} · {when}</span>")
        lines = []
        for t in st.targets:
            role = "followed by this branch" if t.followed else "main branch"
            if not t.exists: lines.append(f"{t.ref:<22} ({role}) not fetched yet: press Check now"); continue
            lines.append(f"{t.ref:<22} ({role}) {t.behind} new commit(s) for this copy, {t.ahead} commit(s) here that it lacks")
            lines += [f"    {line}" for line in t.new] + ([f"    … and {t.behind - len(t.new)} more"] if t.behind > len(t.new) else [])
        if not st.targets: lines.append("No remote branch to compare with (no 'origin' or 'upstream' remote).")
        self.log.setPlainText("\n".join(lines))
        notes = ([f"Check failed: {st.error}"] if st.error else []) + ([w.update_message] if w.update_message else [])
        blocker = st.blocker() if not w.updated else ""
        self.message.setText("\n".join(n for n in notes + [blocker] if n)); theme.set_kind(self.message, "warn" if st.error or blocker else "ok")
        self.update_btn.setEnabled(st.can_update() and w.update_task is None and not w.updated)
