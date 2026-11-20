"""Structure panel of the Systems page: a ball-and-stick view to rotate and zoom, and a card with the formula, the charge and spin,
a choice of source and state, and a 2D drawing (see scope.gui.structure)."""
import math
from PySide6.QtCore    import QPointF, QRectF, Qt, QByteArray
from PySide6.QtGui     import QBrush, QColor, QFont, QPainter, QPen, QRadialGradient
from PySide6.QtSvg     import QSvgRenderer
from PySide6.QtWidgets import QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QSizePolicy, QSplitter, QVBoxLayout, QWidget
from PySide6.QtGui     import QFontDatabase, QGuiApplication
from scope.gui import structure, theme

def rotation(ax: float, ay: float) -> list:
    """3x3 rotation matrix: ay around the vertical axis, then ax around the horizontal one (radians)."""
    cx, sx, cy, sy = math.cos(ax), math.sin(ax), math.cos(ay), math.sin(ay)
    return [[cy, 0, sy], [sx * sy, cx, -sx * cy], [-cx * sy, sx, cx * cy]]

def matmul(a: list, b: list) -> list:
    return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]

class SvgView(QWidget):
    """Shows an SVG drawing at the largest size that fits, keeping its proportions (a plain QSvgWidget stretches it)."""
    def __init__(self):
        super().__init__(); self.renderer = QSvgRenderer(self); self.setMinimumSize(200, 150); self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def load(self, data: QByteArray) -> None:
        self.renderer.load(data); self.update()

    def target(self) -> QRectF:
        """The largest rectangle with the drawing's proportions that fits in the widget, centred."""
        size = self.renderer.defaultSize(); w, h = max(size.width(), 1), max(size.height(), 1)
        scale = min(self.width() / w, self.height() / h)
        return QRectF((self.width() - w * scale) / 2, (self.height() - h * scale) / 2, w * scale, h * scale)

    def paintEvent(self, event) -> None:
        if not self.renderer.isValid(): return
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing); self.renderer.render(p, self.target())

class DetailsDialog(QDialog):
    """SCOPE's own text description of a system, in a window large enough to read it (monospaced, resizable, copyable)."""
    def __init__(self, parent, title: str, text: str):
        super().__init__(parent); self.setWindowTitle(title); theme.fit(self, 980, 720)
        self.text = QPlainTextEdit(text); self.text.setReadOnly(True); self.text.setLineWrapMode(QPlainTextEdit.NoWrap)
        mono = QFontDatabase.systemFont(QFontDatabase.FixedFont); mono.setPointSize(max(mono.pointSize(), 12)); self.text.setFont(mono)
        copy, close = QPushButton("Copy"), QPushButton("Close"); copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.text.toPlainText())); close.clicked.connect(self.accept)
        row = QHBoxLayout(); row.addWidget(copy); row.addStretch(1); row.addWidget(close)
        lay = QVBoxLayout(self); lay.addWidget(self.text, 1); lay.addLayout(row)

class MoleculeView(QWidget):
    """Ball-and-stick drawing of one Structure. Drag to rotate, wheel to zoom, double-click to reset."""
    def __init__(self):
        super().__init__()
        self.s, self.rot, self.zoom, self.last, self.show_h, self.show_labels, self.frame = None, rotation(0, 0), 1.0, None, True, False, None
        self.setMinimumSize(260, 220); self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding); self.setMouseTracking(False)
        self.setToolTip("Drag to rotate, scroll to zoom, double-click to reset the view.")

    def set_structure(self, s: "structure.Structure | None") -> None:
        self.s = s; self.frame = structure.view_frame(s) if s is not None and s.labels else None; self.reset()

    def reset(self) -> None:
        """Back to the start view: the molecule spread out most on the screen, the same way round as the 2D drawing."""
        self.rot, self.zoom = ([row[:] for row in self.frame] if self.frame else rotation(0, 0)), 1.0; self.update()

    def visible(self) -> list:
        if self.s is None: return []
        return [i for i, l in enumerate(self.s.labels) if self.show_h or l != "H"]

    def paintEvent(self, event) -> None:
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing); c = theme.colors()
        p.fillRect(self.rect(), QColor(c["base"]))
        if self.s is None or not self.s.labels:
            p.setPen(QColor(c["sub"])); p.drawText(self.rect(), Qt.AlignCenter, "Select a system to see its structure."); return
        keep = set(self.visible()); coords = self.s.coords
        centre = [sum(coords[i][k] for i in keep) / len(keep) for k in range(3)] if keep else [0, 0, 0]
        pts = {i: [sum(self.rot[r][k] * (coords[i][k] - centre[k]) for k in range(3)) for r in range(3)] for i in keep}
        extent = max((math.hypot(v[0], v[1]) + structure.radius(self.s.labels[i]) * 0.6 for i, v in pts.items()), default=1.0)
        scale = self.zoom * 0.46 * min(self.width(), self.height()) / max(extent, 0.8)
        cx, cy = self.width() / 2, self.height() / 2
        screen = {i: QPointF(cx + v[0] * scale, cy - v[1] * scale) for i, v in pts.items()}
        size = {i: max(3.0, scale * (0.18 + 0.32 * structure.radius(self.s.labels[i]))) for i in pts}
        items = [(pts[i][2], "atom", i) for i in pts] + [((pts[a][2] + pts[b][2]) / 2 - 0.01, "bond", (a, b)) for a, b in self.s.bonds if a in pts and b in pts]
        bond_w = max(2.0, scale * 0.14)
        for _, kind, what in sorted(items, key=lambda t: t[0]):
            if kind == "bond":
                a, b = what; pa, pb = screen[a], screen[b]; mid = (pa + pb) / 2
                for start, end, atom in ((pa, mid, a), (mid, pb, b)):
                    pen = QPen(QColor(structure.color(self.s.labels[atom])).darker(115), bond_w, Qt.SolidLine, Qt.RoundCap); p.setPen(pen); p.drawLine(start, end)
            else:
                i = what; r = size[i]; base = QColor(structure.color(self.s.labels[i]))
                grad = QRadialGradient(screen[i] + QPointF(-r * 0.35, -r * 0.35), r * 1.3); grad.setColorAt(0, base.lighter(165)); grad.setColorAt(0.55, base); grad.setColorAt(1, base.darker(190))
                p.setPen(QPen(QColor(0, 0, 0, 90), 1)); p.setBrush(QBrush(grad)); p.drawEllipse(screen[i], r, r)
                if self.show_labels and self.s.labels[i] != "H":
                    f = QFont(self.font()); f.setPixelSize(int(max(9, min(26, r * 1.05)))); f.setBold(True); p.setFont(f); p.setPen(QColor("#000000") if base.lightness() > 120 else QColor("#FFFFFF"))
                    p.drawText(QRectF(screen[i].x() - r, screen[i].y() - r, 2 * r, 2 * r), Qt.AlignCenter, self.s.labels[i])

    def mousePressEvent(self, event) -> None:
        self.last = event.position()

    def mouseMoveEvent(self, event) -> None:
        if self.last is None: return
        d = event.position() - self.last; self.last = event.position()
        self.rot = matmul(rotation(d.y() * 0.01, d.x() * 0.01), self.rot); self.update()

    def mouseReleaseEvent(self, event) -> None:
        self.last = None

    def mouseDoubleClickEvent(self, event) -> None:
        self.reset()

    def wheelEvent(self, event) -> None:
        self.zoom = max(0.3, min(6.0, self.zoom * (1.0015 ** event.angleDelta().y()))); self.update()

class StructurePanel(QWidget):
    """The lower half of the Systems page: the 3D view on the left, the card (source and state, formula, 2D drawing, SCOPE's own text) on the right."""
    def __init__(self):
        super().__init__()
        self.structures, self.details_text = [], ""
        self.view = MoleculeView()
        self.chooser = QComboBox(); self.chooser.setToolTip("The sources of the system and their states (initial, then the geometries calculations produced).")
        self.formula, self.atoms, self.charge, self.origin = QLabel("—"), QLabel("—"), QLabel("—"), QLabel(""); self.origin.setWordWrap(True); self.origin.setObjectName("pagesub")
        f = self.formula.font(); f.setPointSize(f.pointSize() + 4); f.setBold(True); self.formula.setFont(f)
        self.hydrogens, self.labels = QCheckBox("Hydrogens"), QCheckBox("Element labels"); self.hydrogens.setChecked(True)
        reset = QPushButton("Reset view"); reset.clicked.connect(self.view.reset)
        self.drawing = SvgView()
        self.no_drawing = QLabel("No 2D drawing for this structure."); self.no_drawing.setObjectName("pagesub"); self.no_drawing.setWordWrap(True); self.no_drawing.hide()
        self.details_btn = QPushButton("SCOPE details…"); self.details_btn.setToolTip("SCOPE's own description of the system, in a window of its own"); self.details_dialog, self.title = None, ""
        card = QWidget(); cl = QVBoxLayout(card); cl.setContentsMargins(12, 4, 4, 4)
        form = QFormLayout(); form.addRow("Show", self.chooser); form.addRow("Formula", self.formula); form.addRow("Atoms", self.atoms); form.addRow("Charge, spin", self.charge)
        toggles = QHBoxLayout(); [toggles.addWidget(w) for w in (self.hydrogens, self.labels, reset)]; toggles.addStretch(1)
        cl.addLayout(form); cl.addLayout(toggles); cl.addWidget(self.drawing, 1); cl.addWidget(self.no_drawing); cl.addWidget(self.origin); cl.addWidget(self.details_btn)
        split = QSplitter(Qt.Horizontal); split.addWidget(self.view); split.addWidget(card); split.setStretchFactor(0, 3); split.setStretchFactor(1, 2)
        lay = QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.addWidget(split)
        self.chooser.currentIndexChanged.connect(self.show_index); self.hydrogens.toggled.connect(self.toggle); self.labels.toggled.connect(self.toggle)
        self.details_btn.clicked.connect(self.open_details); theme.on_change(self.redraw)

    def set_structures(self, structures: list, details: str="", title: str="") -> None:
        self.structures, self.details_text, self.title = structures, details, title
        self.chooser.blockSignals(True); self.chooser.clear(); self.chooser.addItems([s.title for s in structures]); self.chooser.blockSignals(False)
        self.chooser.setEnabled(len(structures) > 1); self.show_index(0 if structures else -1)

    def clear(self, message: str="", details: str="") -> None:
        self.set_structures([], details); self.origin.setText(message)

    def open_details(self) -> None:
        """Opens SCOPE's description of the system in its own window (one at a time, updated if already open)."""
        text = self.details_text or "Nothing to show: select a system."
        if self.details_dialog is None: self.details_dialog = DetailsDialog(self.window(), "", text)
        self.details_dialog.setWindowTitle(f"SCOPE details — {self.title}" if self.title else "SCOPE details"); self.details_dialog.text.setPlainText(text)
        self.details_dialog.show(); self.details_dialog.raise_()

    def current(self) -> "structure.Structure | None":
        i = self.chooser.currentIndex()
        return self.structures[i] if 0 <= i < len(self.structures) else None

    def show_index(self, index: int) -> None:
        s = self.structures[index] if 0 <= index < len(self.structures) else None
        self.view.set_structure(s)
        if s is None: self.formula.setText("—"); self.atoms.setText("—"); self.charge.setText("—"); self.drawing.load(QByteArray()); self.drawing.hide(); self.origin.setText(""); return
        self.formula.setText(s.formula); self.atoms.setText(f"{len(s.labels)}  ({len(s.bonds)} bonds)")
        self.charge.setText(", ".join(x for x in ((f"{s.charge:+d}" if isinstance(s.charge, int) and s.charge else ("0" if s.charge == 0 else "")), (str(s.spin) if s.spin is not None else "")) if x) or "not set")
        self.origin.setText("As SCOPE holds it in the system file: atoms, coordinates and the bonds SCOPE perceived." if s.origin == "system" else "From the .xyz file (no system file could be read): bonds guessed from distances.")
        self.redraw()

    def toggle(self) -> None:
        self.view.show_h, self.view.show_labels = self.hydrogens.isChecked(), self.labels.isChecked(); self.view.update()

    def redraw(self) -> None:
        s = self.current(); self.view.update()
        svg, note = structure.drawing_svg(s, 360, 260, dark=theme.mode() == "dark", frame=self.view.frame) if s else ("", "")
        self.drawing.setVisible(bool(svg)); self.no_drawing.setVisible(bool(s) and (not svg or bool(note)))
        self.no_drawing.setText(note if svg else "No 2D drawing for this structure.")
        if svg: self.drawing.load(QByteArray(svg.encode()))
