"""Dialog that brings results back from the cluster, file by file, into the folders of the workspace shown (see scope.gui.transfer)."""
import fnmatch
import os
import time
from PySide6.QtCore    import QThreadPool, Qt, Signal
from PySide6.QtGui     import QBrush, QColor, QGuiApplication
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QDialog, QDoubleSpinBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout)
from scope.gui import remote, theme, transfer
from scope.gui.tasks import Task

class DownloadDialog(QDialog):
    """Lists the cluster folder of one system, proposes what to copy, and copies only the ticked files (or gives the command to do it by hand).

    Attributes:
        files (list):        transfer.RemoteFile rows, in table order.
        listing (dict):      What the cluster returned.
    """
    downloaded = Signal()

    def __init__(self, parent, profile: "remote.Profile", info, system: str, wanted: list=None):
        super().__init__(parent)
        self.p, self.info, self.system, self.files, self.listing, self.tasks, self.busy, self.unread = profile, info, system, [], {}, [], False, []
        self.wanted = set(wanted or [])                                     ## files to tick (outputs the Results page misses), instead of the usual proposal
        self.setWindowTitle(f"Download results of '{system}'"); theme.fit(self, 980, 640)
        src  = f"{profile.host}:{profile.remote_root.rstrip('/')}/Computations/{system}/"; dst = os.path.join(info.computations_path, system) + "/"
        head = QLabel(f"From  <b>{src}</b><br>to  <b>{dst}</b>  (this workspace's folder)"); head.setTextFormat(Qt.RichText); head.setWordWrap(True)
        self.filter = QLineEdit(); self.filter.setPlaceholderText("Show only… (for instance *.log or opt)"); self.filter.setClearButtonEnabled(True)
        self.limit  = QDoubleSpinBox(); self.limit.setRange(1, 1_000_000); self.limit.setValue(200); self.limit.setSuffix(" MB"); self.limit.setDecimals(0)
        self.propose, self.tick_all, self.untick_all = QPushButton("Propose new and changed"), QPushButton("Tick all shown"), QPushButton("Untick all")
        self.propose.setToolTip("Ticks the files that are new or changed on the cluster, except heavy working files and files larger than the limit.")
        row = QHBoxLayout(); [row.addWidget(w) for w in (self.filter,)]; row.addWidget(QLabel("Size limit")); row.addWidget(self.limit); [row.addWidget(b) for b in (self.propose, self.tick_all, self.untick_all)]
        self.table = QTableWidget(0, 6); self.table.setHorizontalHeaderLabels(["", "File", "Size", "On the cluster", "Here", "Status"]); self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers); self.table.setSelectionMode(QAbstractItemView.NoSelection)
        hh = self.table.horizontalHeader(); hh.setSectionResizeMode(1, QHeaderView.Stretch); [hh.setSectionResizeMode(i, QHeaderView.ResizeToContents) for i in (0, 2, 3, 4, 5)]
        self.with_system = QCheckBox("Also replace the local system file with the cluster's (the local one is kept as a backup)")
        self.summary = QLabel("Listing the cluster folder…"); self.summary.setWordWrap(True)
        self.log = QPlainTextEdit(); self.log.setReadOnly(True); self.log.setMaximumHeight(120)
        self.copy_btn, self.download_btn, close = QPushButton("Copy command line"), QPushButton("Download"), QPushButton("Close")
        self.download_btn.setProperty("primary", True); self.copy_btn.setToolTip("Copies the rsync command that downloads the ticked files, to run it yourself in a Terminal (useful for very large transfers).")
        bottom = QHBoxLayout(); bottom.addWidget(self.copy_btn); bottom.addStretch(1); bottom.addWidget(close); bottom.addWidget(self.download_btn)
        lay = QVBoxLayout(self); lay.addWidget(head); lay.addLayout(row); lay.addWidget(self.table, 1); lay.addWidget(self.with_system); lay.addWidget(self.summary); lay.addWidget(self.log); lay.addLayout(bottom)
        self.filter.textChanged.connect(self.apply_filter); self.propose.clicked.connect(self.propose_default); self.tick_all.clicked.connect(lambda: self.tick(True)); self.untick_all.clicked.connect(lambda: self.tick(False))
        self.table.itemChanged.connect(self.item_changed); self.with_system.toggled.connect(self.update_summary)
        self.copy_btn.clicked.connect(self.copy_command); self.download_btn.clicked.connect(self.start_download); close.clicked.connect(self.reject)
        self.set_busy(True); self.background(lambda: remote.run_script(self.p, transfer.listing_script(self.p, self.system), timeout=120), self.listed)

    ##### helpers #####
    def background(self, fn, on_done) -> None:
        task = Task(fn); self.tasks.append(task)
        task.signals.done.connect(on_done); task.signals.failed.connect(lambda m: (self.set_busy(False), self.log.appendPlainText(f"Failed: {m}")))
        QThreadPool.globalInstance().start(task)

    def set_busy(self, busy: bool) -> None:
        self.busy = busy
        for w in (self.download_btn, self.copy_btn, self.propose, self.tick_all, self.untick_all): w.setEnabled(not busy)

    def chosen(self) -> list:
        return [f for f in self.files if f.selected]

    ##### listing #####
    def listed(self, res: "remote.Result") -> None:
        self.set_busy(False)
        self.listing = transfer.parse_listing(res.stdout)
        if not self.listing: self.summary.setText("The cluster folder could not be listed: " + (res.stderr.strip().splitlines()[-1] if res.stderr.strip() else f"exit code {res.returncode}")); return
        if not self.listing.get("exists"): self.summary.setText(f"There is no Computations/{self.system} folder on the cluster yet. Run the system on the cluster first."); return
        self.files = transfer.compare(self.listing, self.info, self.system, self.limit.value())
        local_npy = os.path.join(self.info.systems_path, self.system, f"{self.system}.npy")
        remote_npy = self.listing.get("system")
        self.with_system.setEnabled(bool(remote_npy))
        self.with_system.setChecked(bool(remote_npy) and (not os.path.isfile(local_npy) or remote_npy[1] > os.path.getmtime(local_npy) + 2))      ## proposed when the cluster's is newer
        if self.listing.get("truncated"): self.log.appendPlainText(f"Only the first {transfer.MAX_LIST} files are listed.")
        self.unread = transfer.unread(self.listing)
        if self.unread:
            self.log.appendPlainText(f"{len(self.unread)} file(s) on the cluster were written after SCOPE last saved the system there, so the cluster's system file does not hold their results yet. "
                                     "To have them read: press Run on the cluster again, then download the system file; or download these outputs and run the system on this computer.")
            self.with_system.setToolTip(f"The cluster's system file was saved before {len(self.unread)} of these files were written: it does not include their results yet.")
        if self.wanted:
            for f in self.files: f.selected = f.rel in self.wanted
            found = sum(1 for f in self.files if f.rel in self.wanted)
            self.log.appendPlainText(f"Ticked the {found} output(s) missing on this computer that exist on the cluster" + (f"; {len(self.wanted) - found} are not on the cluster either (still running, or not started)." if found < len(self.wanted) else "."))
        self.fill()

    def fill(self) -> None:
        c = theme.colors(); colour = {"new": c["ok"], "changed": c["accent"], "same": c["sub"], "newer here": c["warn"]}
        self.table.blockSignals(True); self.table.setRowCount(len(self.files))
        for i, f in enumerate(self.files):
            box = QTableWidgetItem(); box.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled); box.setCheckState(Qt.Checked if f.selected else Qt.Unchecked)
            note = f.status + (", heavy" if f.heavy else "") + (", over the limit" if f.size > self.limit.value() * 1e6 else "")
            cells = [box, QTableWidgetItem(f.rel), QTableWidgetItem(transfer.human(f.size)), QTableWidgetItem(time.strftime("%Y-%m-%d %H:%M", time.localtime(f.mtime))),
                     QTableWidgetItem("—" if f.local_size < 0 else transfer.human(f.local_size)), QTableWidgetItem(note)]
            cells[5].setForeground(QBrush(QColor(colour[f.status])))
            for j, cell in enumerate(cells): self.table.setItem(i, j, cell)
        self.table.blockSignals(False); self.apply_filter(); self.update_summary()

    ##### selection #####
    def apply_filter(self) -> None:
        text = self.filter.text().strip()
        for i, f in enumerate(self.files):
            shown = not text or (fnmatch.fnmatch(f.rel, text) or fnmatch.fnmatch(os.path.basename(f.rel), text) if any(ch in text for ch in "*?[") else text.lower() in f.rel.lower())
            self.table.setRowHidden(i, not shown)

    def tick(self, on: bool) -> None:
        for i, f in enumerate(self.files):
            if on and self.table.isRowHidden(i): continue
            f.selected = on
        self.fill()

    def propose_default(self) -> None:
        self.files = transfer.compare(self.listing, self.info, self.system, self.limit.value()); self.fill()

    def item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() == 0: self.files[item.row()].selected = item.checkState() == Qt.Checked; self.update_summary()

    def update_summary(self) -> None:
        chosen = self.chosen(); total = sum(f.size for f in chosen) + (self.listing.get("system", [0])[0] if self.with_system.isChecked() and self.listing.get("system") else 0)
        heavy = [f for f in chosen if f.heavy or f.size > self.limit.value() * 1e6]
        problem = transfer.space_problem(self.info, total) if total else ""
        text = f"{len(chosen)} of {len(self.files)} file(s) ticked, {transfer.human(total)}." + (f"  {len(heavy)} of them heavy or over the limit." if heavy else "") + (f"\n{problem}" if problem else "")
        if self.unread: text += f"\n{len(self.unread)} output(s) are not read by SCOPE yet: the cluster's system file does not include their results (see below)."
        left = transfer.left_behind(self.files, self.with_system.isChecked())
        if left: text += (f"\nThe cluster's system file is ticked, but {len(left)} input/output file(s) it may refer to are not (new or changed on the cluster). "
                          "Copying the system file alone is not a synchronisation: this computer could not re-read, continue or check those calculations. Press 'Propose new and changed' to tick them.")
        self.summary.setText(text); theme.set_kind(self.summary, "err" if problem else ("warn" if heavy or self.unread or left else "ok"))
        self.download_btn.setEnabled(not self.busy and (bool(chosen) or self.with_system.isChecked()) and not problem)

    ##### copy #####
    def copy_command(self) -> None:
        chosen = [f.rel for f in self.chosen()]
        if not chosen: self.log.appendPlainText("Tick at least one file first."); return
        cmd = transfer.command_line(self.p, self.info, self.system, transfer.list_file(self.system, chosen))
        QGuiApplication.clipboard().setText(cmd)
        self.log.appendPlainText("Copied to the clipboard (paste it in a Terminal; it can be run again to resume):\n" + cmd + ("\nThe system file is not part of it: replace it from this window, which keeps a backup." if self.with_system.isChecked() else ""))

    def start_download(self) -> None:
        chosen = [f.rel for f in self.chosen()]; with_system = self.with_system.isChecked()
        self.set_busy(True); self.log.appendPlainText(f"Downloading {len(chosen)} file(s)" + (" and the system file" if with_system else "") + "…")
        self.background(lambda: transfer.download(self.p, self.info, self.system, chosen, with_system), self.download_finished)

    def download_finished(self, out: dict) -> None:                        ## not `done`: that name belongs to QDialog (closing the dialog calls it)
        self.set_busy(False); res = out.get("files")
        if res is not None:
            changed = [l for l in res.stdout.splitlines() if l.strip()]
            self.log.appendPlainText(("Copied " + f"{len(changed)} item(s)." if res.ok else "rsync failed: " + (res.stderr.strip() or f"exit code {res.returncode}")) + (" Run Download again to resume." if not res.ok else ""))
        if out.get("system"): self.log.appendPlainText(out["system"])
        if self.listing: self.files = transfer.compare(self.listing, self.info, self.system, self.limit.value()); [setattr(f, "selected", False) for f in self.files]; self.fill()
        self.downloaded.emit()
