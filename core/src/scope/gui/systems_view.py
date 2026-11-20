"""Systems page: the System → Source → State tree, importing .xyz files as new systems or as sources of an existing one, and the
charge and spin of each source (totals, per atom, connectivity). The logic is in scope.gui.systems; this module only shows it."""
import os
from PySide6.QtCore    import Qt
from PySide6.QtGui     import QBrush, QColor
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QMenu, QMessageBox,
                               QPushButton, QSpinBox, QSplitter, QTableWidget, QTableWidgetItem, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)
from scope.gui import backend, systems, theme
from scope.gui.theme import set_kind

ROLE = Qt.UserRole

class AtomsDialog(QDialog):
    """Per-atom charges and spins of one source, with each atom's neighbours (SCOPE's connectivity). The totals are the sums, shown live."""
    def __init__(self, parent, session, system: str, source: object):
        super().__init__(parent); self.session, self.system, self.source_name = session, system, source.name
        self.setWindowTitle(f"Atoms of source '{source.name}'"); theme.fit(self, 720, 560)
        self.rows = systems.atom_rows(source); self.electrons = systems.electrons_of(source)
        self.table = QTableWidget(len(self.rows), 5); self.table.setHorizontalHeaderLabels(["#", "Element", "Charge", "Spin (2S)", "Bonded to"])
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch); self.table.verticalHeader().hide()
        labels = [r.label for r in self.rows]
        for i, r in enumerate(self.rows):
            fixed = [QTableWidgetItem(str(i + 1)), QTableWidgetItem(r.label)]
            for it in fixed: it.setFlags(it.flags() & ~Qt.ItemIsEditable)
            nb = QTableWidgetItem(", ".join(f"{labels[j]}{j + 1}" for j in r.neighbours) or "none"); nb.setFlags(nb.flags() & ~Qt.ItemIsEditable)
            for j, it in enumerate(fixed + [QTableWidgetItem(str(r.charge or 0)), QTableWidgetItem(str(r.spin or 0)), nb]): self.table.setItem(i, j, it)
        self.total = QLabel(); self.total.setWordWrap(True)
        note = QLabel("SCOPE keeps the charge and the spin on the atoms; the totals of the source (and of every state of it) are their sums. "
                      "Gaussian uses only the totals; Quantum ESPRESSO also starts the magnetisation from the atomic spins."); note.setWordWrap(True); note.setObjectName("pagesub")
        save, cancel = QPushButton("Save"), QPushButton("Cancel"); save.setProperty("primary", True); save.clicked.connect(self.save); cancel.clicked.connect(self.reject)
        row = QHBoxLayout(); row.addWidget(self.total, 1); row.addWidget(cancel); row.addWidget(save)
        lay = QVBoxLayout(self); lay.addWidget(note); lay.addWidget(self.table, 1); lay.addLayout(row)
        self.table.itemChanged.connect(self.update_total); self.update_total()

    def values(self) -> tuple:
        out = ([], [])
        for i in range(self.table.rowCount()):
            for k, col in ((0, 2), (1, 3)):
                text = (self.table.item(i, col).text() if self.table.item(i, col) else "0").strip() or "0"
                try: out[k].append(int(text))
                except ValueError: raise ValueError(f"Atom {i + 1}: '{text}' is not a whole number")
        return out

    def update_total(self) -> None:
        try: q, s = self.values()
        except ValueError as exc: self.total.setText(str(exc)); set_kind(self.total, "err"); return
        ok = systems.spin_parity_ok(self.electrons, sum(q), sum(s))
        self.total.setText(f"Total charge {sum(q):+d}, total 2S = {sum(s)} ({systems.multiplicity_word(sum(s) + 1)})" + ("" if ok is not False else f": {self.electrons - sum(q)} electrons cannot have this spin"))
        set_kind(self.total, "err" if ok is False else "")

    def save(self) -> None:
        try:
            q, s = self.values()
            systems.set_charge_spin(self.session.env, self.system, self.source_name, charges=q, spins=s, env_path=self.session.info.filepath)
        except Exception as exc: QMessageBox.warning(self, "Not saved", str(exc)); return
        self.accept()

class AdjacencyDialog(QDialog):
    """SCOPE's connectivity (adjacency) matrix of a source: a 1 where two atoms are bonded."""
    def __init__(self, parent, source: object):
        super().__init__(parent); self.setWindowTitle(f"Connectivity of source '{source.name}'"); theme.fit(self, 760, 640)
        adj = systems.adjacency(source); labels = list(getattr(source, "labels", []) or [])
        names = [f"{l}{i + 1}" for i, l in enumerate(labels)]
        self.table = QTableWidget(len(adj), len(adj)); self.table.setHorizontalHeaderLabels(names); self.table.setVerticalHeaderLabels(names)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers); self.table.horizontalHeader().setDefaultSectionSize(34)
        accent = QColor(theme.colors()["highlight"])
        for i, row in enumerate(adj):
            for j, v in enumerate(row):
                it = QTableWidgetItem("1" if v else ""); it.setTextAlignment(Qt.AlignCenter)
                if v: it.setBackground(QBrush(accent))
                self.table.setItem(i, j, it)
        bonds = sum(sum(r) for r in adj) // 2
        info = QLabel(f"{len(adj)} atoms, {bonds} bonds, as SCOPE perceived them from the geometry (covalent radii). This is the connectivity SCOPE uses to find molecules, ligands and fragments."
                      if adj else "SCOPE could not build a connectivity matrix for this source."); info.setWordWrap(True)
        close = QPushButton("Close"); close.clicked.connect(self.accept)
        lay = QVBoxLayout(self); lay.addWidget(info); lay.addWidget(self.table, 1); r = QHBoxLayout(); r.addStretch(1); r.addWidget(close); lay.addLayout(r)

class SourcePanel(QGroupBox):
    """Charge and spin of the selected source: the totals SCOPE will use, where they come from, and buttons to change them."""
    def __init__(self, tab: "SystemsTab"):
        super().__init__("Source"); self.tab, self.system, self.source, self.info = tab, "", None, None
        self.head = QLabel("Select a source in the tree to see and set its charge and spin."); self.head.setWordWrap(True)
        self.charge, self.spin = QSpinBox(), QSpinBox(); self.charge.setRange(-30, 30); self.spin.setRange(0, 30)
        for box in (self.charge, self.spin): box.setMinimumWidth(90); box.setMinimumHeight(28)
        self.charge.setToolTip("Total charge of the source: the sum of its atoms' charges. Every state of the source uses it.")
        self.spin.setToolTip("Total spin as SCOPE stores it: 2S, the number of unpaired electrons (alpha minus beta). Multiplicity = 2S + 1.")
        self.mult = QLabel(); self.origin = QLabel(); self.origin.setWordWrap(True); self.parity = QLabel(); self.parity.setWordWrap(True)
        self.save_btn, self.confirm_btn = QPushButton("Save totals"), QPushButton("Confirm as they are")
        self.atoms_btn, self.adj_btn = QPushButton("Atoms…"), QPushButton("Connectivity…")
        self.save_btn.setProperty("primary", True)
        self.save_btn.setToolTip("Every atom is set to 0, then the whole charge and spin go on one atom (the first metal, else the first atom). Use Atoms… to place them yourself.")
        self.confirm_btn.setToolTip("Marks the current values as checked, without changing them.")
        self.save_btn.clicked.connect(self.save); self.confirm_btn.clicked.connect(self.confirm); self.atoms_btn.clicked.connect(self.open_atoms); self.adj_btn.clicked.connect(self.open_adjacency)
        self.charge.valueChanged.connect(self.check); self.spin.valueChanged.connect(self.check)
        self.where = QLabel(); self.where.setWordWrap(True); self.where.setObjectName("pagesub")
        form = QFormLayout(); form.addRow("Total charge", self.charge); sp = QHBoxLayout(); sp.addWidget(self.spin); sp.addWidget(self.mult, 1); form.addRow("Total spin (2S)", sp)
        b1 = QHBoxLayout(); b1.addWidget(self.save_btn); b1.addWidget(self.confirm_btn); b1.addStretch(1)
        b2 = QHBoxLayout(); b2.addWidget(self.atoms_btn); b2.addWidget(self.adj_btn); b2.addStretch(1)
        lay = QVBoxLayout(self); lay.addWidget(self.head); lay.addLayout(form); lay.addWidget(self.origin); lay.addWidget(self.parity); lay.addLayout(b1); lay.addLayout(b2); lay.addWidget(self.where); lay.addStretch(1)
        self.show_none()

    def show_none(self, text: str="Select a source in the tree to see and set its charge and spin.") -> None:
        self.system, self.source, self.info = "", None, None; self.head.setText(text)
        for w in (self.charge, self.spin, self.save_btn, self.confirm_btn, self.atoms_btn, self.adj_btn): w.setEnabled(False)
        for w in (self.mult, self.origin, self.parity, self.where): w.setText("")

    def show_source(self, system: str, source: object, info: "systems.SourceInfo") -> None:
        self.system, self.source, self.info = system, source, info
        self.head.setText(f"<b>{info.name}</b> in system <b>{system}</b>: {info.kind or 'source'}, {info.formula}, {info.natoms} atoms, {info.electrons} electrons when neutral")
        for w in (self.charge, self.spin, self.save_btn, self.confirm_btn, self.atoms_btn, self.adj_btn): w.setEnabled(True)
        for w, v in ((self.charge, info.charge or 0), (self.spin, info.spin or 0)): w.blockSignals(True); w.setValue(int(v)); w.blockSignals(False)
        if info.origin == "user": self.origin.setText("Set or confirmed by you."); set_kind(self.origin, "ok")
        else: self.origin.setText("SCOPE's import default: every atom has charge 0 and spin 0, because an .xyz file has neither. Check these values before running: SCOPE will use them for every calculation of this source."); set_kind(self.origin, "warn")
        self.where.setText(("Used by branches: " + ", ".join(info.branches) + ". " if info.branches else "No branch uses this source yet. ") + systems.CLUSTER_NOTE)
        self.confirm_btn.setVisible(info.origin != "user"); self.check()

    def check(self) -> None:
        q, s = self.charge.value(), self.spin.value(); self.mult.setText(f"multiplicity {s + 1} ({systems.multiplicity_word(s + 1)})")
        ok = systems.spin_parity_ok(self.info.electrons if self.info else None, q, s)
        if ok is False:
            self.parity.setText(f"{self.info.electrons - q} electrons cannot have 2S = {s}: use 2S = {systems.lowest_spin(self.info.electrons, q)}, {systems.lowest_spin(self.info.electrons, q) + 2}, …"); set_kind(self.parity, "err")
        else: self.parity.setText(""); set_kind(self.parity, "")
        changed = self.info is not None and (q, s) != (self.info.charge, self.info.spin)
        self.save_btn.setEnabled(self.info is not None and ok is not False and (changed or self.info.origin != "user"))
        self.confirm_btn.setEnabled(self.info is not None and not changed and self.info.parity_ok is not False)

    def save(self) -> None:
        try: systems.set_charge_spin(self.tab.session.env, self.system, self.info.name, charge=self.charge.value(), spin=self.spin.value(), env_path=self.tab.session.info.filepath)
        except Exception as exc: QMessageBox.warning(self, "Not saved", str(exc)); return
        self.tab.reload_source(self.system, self.info.name)

    def confirm(self) -> None:
        try: systems.confirm_defaults(self.tab.session.env, self.system, self.info.name, env_path=self.tab.session.info.filepath)
        except Exception as exc: QMessageBox.warning(self, "Not saved", str(exc)); return
        self.tab.reload_source(self.system, self.info.name)

    def open_atoms(self) -> None:
        why = systems.edit_blocked(self.tab.session.info.filepath if self.tab.session.info else "", self.system)
        if why: QMessageBox.information(self, "Not now", why); return
        if AtomsDialog(self, self.tab.session, self.system, self.source).exec(): self.tab.reload_source(self.system, self.info.name)

    def open_adjacency(self) -> None:
        AdjacencyDialog(self, self.source).exec()

class SystemsTab(QWidget):
    """The systems of the environment as a tree: System → Source → State. Selecting a system shows its structures; selecting a source
    (or one of its states) shows its charge and spin."""
    def __init__(self, session):
        super().__init__()
        self.session, self.rows, self.cache = session, [], {}                  ## cache: system file -> (fingerprint, loaded System)
        self.tree = QTreeWidget(); self.tree.setColumnCount(4); self.tree.setHeaderLabels(["System / Source / State", "What", "Charge · spin", "Used by / holds"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeToContents); self.tree.header().setStretchLastSection(True)
        self.tree.itemExpanded.connect(self.expand); self.tree.itemSelectionChanged.connect(self.show_details)
        from scope.gui.structure_view import StructurePanel
        self.structure = StructurePanel(); self.panel = SourcePanel(self)
        refresh = QPushButton("Refresh"); refresh.clicked.connect(session.systemsChanged.emit)
        imp = QPushButton("Import .xyz…"); imp.setProperty("primary", True); menu = QMenu(self)
        menu.addAction("One new system per file (system = file name)…", self.import_each)
        menu.addAction("One new system with these files as its sources…", self.import_as_one)
        self.add_action = menu.addAction("Add files as sources of the selected system…", self.import_into)
        imp.setMenu(menu); self.import_btn = imp
        legend = QLabel("A <b>System</b> is one file of results. It holds <b>Sources</b> (one per .xyz: for instance the high- and the low-spin geometry of one compound), "
                        "and each source holds <b>States</b>: 'initial' when imported, then the states that jobs write (their fstate)."); legend.setWordWrap(True); legend.setObjectName("pagesub")
        row = QHBoxLayout(); row.addWidget(imp); row.addWidget(refresh); row.addStretch(1)
        from PySide6.QtWidgets import QScrollArea, QFrame
        panel_scroll = QScrollArea(); panel_scroll.setWidgetResizable(True); panel_scroll.setFrameShape(QFrame.NoFrame); panel_scroll.setWidget(self.panel)        ## never squeezed: it scrolls instead
        top = QSplitter(Qt.Horizontal); top.addWidget(self.tree); top.addWidget(panel_scroll); top.setStretchFactor(0, 3); top.setStretchFactor(1, 2); top.setSizes([560, 420])
        split = QSplitter(Qt.Vertical); split.addWidget(top); split.addWidget(self.structure); split.setStretchFactor(0, 1); split.setStretchFactor(1, 1); split.setSizes([400, 360])
        lay = QVBoxLayout(self); lay.addLayout(row); lay.addWidget(legend); lay.addWidget(split, 1)
        session.systemsChanged.connect(self.refresh)

    ##### tree #####
    def loaded(self, file: str) -> "object | None":
        """The System of a file, read once and again only when the file changes (it is a pickle: only files the user trusts are read)."""
        from scope.gui.results import fingerprint, load_quietly
        fp = fingerprint(file)
        if file not in self.cache or self.cache[file][0] != fp:
            try: obj, _ = load_quietly(file)
            except Exception: obj = None
            self.cache[file] = (fp, obj if getattr(obj, "object_type", None) == "system" else None)
        return self.cache[file][1]

    def refresh(self) -> None:
        self.rows = self.session.systems(); self.tree.clear(); self.panel.show_none()
        for r in self.rows:
            what = "system" if r.file else "no system file"
            done = (("finished: " + ", ".join(r.finished)) if r.finished else "") + (("  terminated: " + ", ".join(r.terminated)) if r.terminated else "")
            it = QTreeWidgetItem(self.tree, [r.name, what, "", done]); it.setData(0, ROLE, ("system", r.name))
            if r.file: QTreeWidgetItem(it, ["…"])                              ## filled when expanded
        self.structure.clear("Import a system to see its structure here." if not self.rows else "")
        if self.rows: self.tree.setCurrentItem(self.tree.topLevelItem(0)); self.tree.topLevelItem(0).setExpanded(True)

    def row(self, name: str):
        return next((r for r in self.rows if r.name == name), None)

    def expand(self, item: QTreeWidgetItem) -> None:
        data = item.data(0, ROLE)
        if not data or data[0] != "system" or (item.childCount() and item.child(0).data(0, ROLE)): return
        item.takeChildren(); r = self.row(data[1]); obj = self.loaded(r.file) if r and r.file else None
        if obj is None: QTreeWidgetItem(item, ["(the system file cannot be read)"]); return
        tree = systems.tree_from(obj)
        item.setText(3, (item.text(3) + "   " if item.text(3) else "") + f"{len(tree.sources)} source(s), branches: {', '.join(tree.branches) or 'none'}")
        for s in tree.sources: self.add_source_item(item, data[1], s)

    def add_source_item(self, parent: QTreeWidgetItem, system: str, s: "systems.SourceInfo") -> QTreeWidgetItem:
        c = theme.colors()
        it = QTreeWidgetItem(parent, [s.name, f"{s.kind or 'source'} {s.formula}", s.summary, ", ".join(s.branches) or "no branch yet"]); it.setData(0, ROLE, ("source", system, s.name))
        if s.origin != "user" or s.parity_ok is False: it.setForeground(2, QBrush(QColor(c["err"] if s.parity_ok is False else c["warn"])))
        it.setToolTip(2, "Totals of the source (sums of its atoms' values). Every state uses them." + ("" if s.origin == "user" else " Still SCOPE's import default: check them."))
        for st in s.states:
            holds = ", ".join(x for x in ("geometry" if st.has_geometry else "", "energy" if st.has_energy else "", f"{st.n_freqs} frequencies" if st.n_freqs else "") if x) or "nothing yet"
            sit = QTreeWidgetItem(it, [st.name, "state", "", holds + (f" · {st.n_comps} calculation(s)" if st.n_comps else "")]); sit.setData(0, ROLE, ("state", system, s.name, st.name))
        it.setExpanded(True)
        return it

    def reload_source(self, system: str, source: str) -> None:
        """After a change: reads the system again and redraws its branch of the tree, keeping the source selected."""
        self.session.forget_systems()
        top = next((self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount()) if self.tree.topLevelItem(i).data(0, ROLE) == ("system", system)), None)
        if top is None: self.refresh(); return
        top.takeChildren(); QTreeWidgetItem(top, ["…"]); top.setExpanded(False); top.setExpanded(True); self.expand(top)
        for i in range(top.childCount()):
            if top.child(i).data(0, ROLE) == ("source", system, source): self.tree.setCurrentItem(top.child(i)); break

    ##### selection #####
    def show_details(self) -> None:
        from scope.gui import structure
        items = self.tree.selectedItems()
        if not items or not items[0].data(0, ROLE): return
        data = items[0].data(0, ROLE); r = self.row(data[1])
        if r is None: return
        obj = self.loaded(r.file) if r.file else None
        details = repr(obj) if obj is not None else ("No system binary in this folder." if not r.file else f"Cannot read {r.file}")
        found = structure.structures_from(obj) if obj is not None else structure.structures_for(r, self.session.info.sources_path if self.session.info else "")
        if found: self.structure.set_structures(found, details, r.name)
        else: self.structure.clear("No structure could be read for this system.", details)
        if data[0] == "system" or obj is None: self.panel.show_none(f"System <b>{r.name}</b>: select one of its sources to see and set its charge and spin."); return
        try: src = systems.find_source(obj, data[2])
        except KeyError: self.panel.show_none(); return
        self.panel.show_source(r.name, src, systems.source_info(src))
        title = f"{src.name} · {data[3]}" if data[0] == "state" else None
        for i in range(self.structure.chooser.count()):
            text = self.structure.chooser.itemText(i)
            if (title and text == title) or (not title and (text == src.name or text.startswith(f"{src.name} · "))): self.structure.chooser.setCurrentIndex(i); break

    def selected_system(self) -> str:
        items = self.tree.selectedItems(); data = items[0].data(0, ROLE) if items else None
        return data[1] if data else ""

    def select_system(self, name: str) -> None:
        for i in range(self.tree.topLevelItemCount()):
            if self.tree.topLevelItem(i).text(0) == name: self.tree.setCurrentItem(self.tree.topLevelItem(i)); return

    ##### import #####
    def pick_files(self) -> list:
        if not self.session.env: QMessageBox.information(self, "No environment", "Create or open an environment first."); return []
        paths, _ = QFileDialog.getOpenFileNames(self, "Import .xyz files", self.session.info.sources_path, "XYZ files (*.xyz)")
        return paths

    def import_each(self) -> None:
        for p in self.pick_files():
            try: backend.import_xyz(self.session.env, p)
            except Exception as exc: QMessageBox.warning(self, "Import failed", f"{os.path.basename(p)}: {exc}")
        self.session.systemsChanged.emit()

    def import_as_one(self) -> None:
        paths = self.pick_files()
        if not paths: return
        name, ok = QInputDialog.getText(self, "New system", f"Name of the new system ({len(paths)} source(s): " + ", ".join(systems.default_name(p) for p in paths) + "):")
        if not ok or not name.strip(): return
        try: systems.create_system(self.session.env, name.strip(), [(p, systems.default_name(p)) for p in paths])
        except Exception as exc: QMessageBox.warning(self, "System not created", str(exc)); return
        self.session.systemsChanged.emit(); self.select_system(name.strip())

    def import_into(self) -> None:
        names = [r.name for r in self.rows if r.file]
        if not names: QMessageBox.information(self, "No system yet", "Create a system first: Import .xyz → One new system…"); return
        current = self.selected_system()
        system, ok = QInputDialog.getItem(self, "Add sources", "Add the files as sources of system:", names, names.index(current) if current in names else 0, False)
        if not ok: return
        why = systems.edit_blocked(self.session.info.filepath, system)
        if why: QMessageBox.information(self, "Not now", why); return
        added = []
        for p in self.pick_files():
            name, ok = QInputDialog.getText(self, "Source name", f"Name of the source made from {os.path.basename(p)}:", text=systems.default_name(p))
            if not ok: continue
            try: added.append(systems.add_source_xyz(self.session.env, system, p, name, env_path=self.session.info.filepath))
            except Exception as exc: QMessageBox.warning(self, "Not added", f"{os.path.basename(p)}: {exc}")
        self.session.systemsChanged.emit(); self.select_system(system)
        if added: QMessageBox.information(self, "Sources added", f"Added to '{system}': {', '.join(added)}.\n\nTheir charge and spin are SCOPE's import default (0, singlet): check them in the Source box.\n\n{systems.CLUSTER_NOTE}")
