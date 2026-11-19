"""A matplotlib canvas for the window: follows the light/dark theme and draws a spectrum (curve, filled area, sticks), curves against
temperature, or horizontal bars; zooms on a region dragged with the mouse; saves PNG, SVG or PDF with where the numbers come from written
into the file's metadata.

It uses matplotlib's Figure directly, never pyplot: no global figures, and no plt.show(), which must not run outside the main thread.

Zoom: drag a rectangle on the plot to zoom into it. A drag that is mostly horizontal zooms the x axis only and fits y to what is visible
(the natural gesture for a spectrum). Double-click, or PlotPanel's Reset view, shows everything again. The zoom is kept when the same plot
is redrawn with other settings (a broader width, another model) and dropped when a different plot is shown.
"""
from dataclasses import dataclass, field
from PySide6.QtCore    import QSize, Qt, Signal
from PySide6.QtGui     import QFontMetrics
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle
from scope.gui import theme

@dataclass
class Lines:
    """Curves sharing one x axis. series: [(label, x, y)]; zero: draw y = 0; marks: [(x, label)] drawn as vertical dashed lines."""
    title:  str
    xlabel: str
    ylabel: str
    series: list
    zero:   bool = False
    marks:  list = field(default_factory=list)

@dataclass
class Bars:
    """Horizontal bars, one per label (top to bottom in the order given). highlight: index drawn in the accent colour, or -1."""
    title:     str
    xlabel:    str
    labels:    list
    values:    list
    highlight: int = -1

DRAG_MIN = 6                                                                   ## pixels: a smaller drag is a click
X_ONLY   = 0.25                                                                ## a drag whose height is under this fraction of its width zooms x only

class PlotCanvas(FigureCanvasQTAgg):
    """Attributes: last (the Spectrum, Lines or Bars drawn last, or None), message (text shown instead of a plot), view (the zoomed
    ((x0, x1), (y0, y1)), or None for everything). Signals: zoomed(bool) when the view changes, cursor(str) with the position under the mouse."""
    zoomed = Signal(bool)
    cursor = Signal(str)

    def __init__(self):
        self.figure = Figure(figsize=(6, 3.4), dpi=100, layout="tight")
        super().__init__(self.figure)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding); self.setMinimumHeight(160)
        self.last, self.message, self.view, self.key = None, "", None, None
        self.drag, self.band, self.ax = None, None, None
        for name, handler in (("button_press_event", self.pressed), ("motion_notify_event", self.moved), ("button_release_event", self.released),
                              ("figure_leave_event", lambda e: self.cursor.emit(""))):
            self.mpl_connect(name, handler)
        theme.on_change(self.redraw)

    def sizeHint(self) -> "QSize":
        """Smaller than the figure's own size (600 x 340): the plot takes the room it is given instead of asking for more."""
        return QSize(480, 240)

    def colours(self) -> dict:
        c = theme.colors()
        return {"bg": c["base"], "fg": c["text"], "sub": c["sub"], "grid": c["border"], "line": c["accent"], "stick": c["err"], "series": [c["accent"], c["err"], c["ok"], c["warn"], c["sub"]]}

    ##### what to draw #####
    def show_message(self, text: str) -> None:
        self.last, self.message = None, text; self.set_view(None, emit=True); self.key = None; self.redraw()

    def plot_spectrum(self, sp: "object") -> None:
        self.show_item(sp)

    def plot(self, item: "Lines | Bars") -> None:
        self.show_item(item)

    def show_item(self, item) -> None:
        """Draws `item`; keeps the zoom if it is the same plot as before (same kind, title and axes), drops it otherwise."""
        key = (type(item).__name__, getattr(item, "title", ""), getattr(item, "xlabel", ""), getattr(item, "ylabel", ""))
        if key != self.key: self.set_view(None, emit=True)
        self.key, self.last, self.message = key, item, ""; self.redraw()

    def redraw(self) -> None:
        c = self.colours(); fig = self.figure; fig.clear(); fig.set_facecolor(c["bg"]); self.band = None
        ax = fig.add_subplot(111); ax.set_facecolor(c["bg"]); self.ax = ax
        for spine in ax.spines.values(): spine.set_color(c["grid"])
        ax.tick_params(colors=c["sub"], labelsize=9); ax.xaxis.label.set_color(c["fg"]); ax.yaxis.label.set_color(c["fg"]); ax.title.set_color(c["fg"])
        item = self.last
        if item is None:
            ax.set_xticks([]); ax.set_yticks([]); [s.set_visible(False) for s in ax.spines.values()]
            ax.text(0.5, 0.5, self.message, ha="center", va="center", color=c["sub"], fontsize=10, wrap=True, transform=ax.transAxes)
        elif isinstance(item, Lines): self.draw_lines(ax, item, c)
        elif isinstance(item, Bars):  self.draw_bars(ax, item, c)
        else:                         self.draw_spectrum(ax, item, c)
        if item is not None and self.view: ax.set_xlim(*self.view[0]); ax.set_ylim(*self.view[1])
        for side in ("top", "right"): ax.spines[side].set_visible(False)
        self.draw_idle()

    def draw_spectrum(self, ax, sp, c: dict) -> None:
        ax.plot(sp.x, sp.y, color=c["line"], lw=1.4); ax.fill_between(sp.x, 0, sp.y, color=c["line"], alpha=0.15)
        lo, hi = min(sp.x), max(sp.x)
        sticks = [(p, h) for p, h in sp.sticks if lo <= p <= hi]
        if any(h for _, h in sticks): ax.vlines([p for p, _ in sticks], 0, [h for _, h in sticks], color=c["stick"], lw=0.8, alpha=0.75)
        elif sticks: ax.plot([p for p, _ in sticks], [0] * len(sticks), "|", color=c["stick"], markersize=8, transform=ax.get_xaxis_transform())    ## positions only (VDOS)
        ax.set_xlim(lo, hi); ax.set_ylim(bottom=0)
        ax.set_xlabel(sp.xlabel, fontsize=9); ax.set_ylabel(sp.ylabel, fontsize=9); ax.set_title(sp.title, fontsize=10, pad=10)
        ax.grid(True, color=c["grid"], lw=0.5, alpha=0.6)

    def draw_lines(self, ax, ln: Lines, c: dict) -> None:
        for k, (label, x, y) in enumerate(ln.series): ax.plot(x, y, color=c["series"][k % len(c["series"])], lw=1.7 if k == 0 else 1.3, label=label)
        if ln.zero: ax.axhline(0, color=c["sub"], lw=0.8)
        for x, label in ln.marks:
            ax.axvline(x, color=c["fg"], lw=0.9, ls="--"); ax.annotate(label, (x, 1), xycoords=("data", "axes fraction"), xytext=(4, -12), textcoords="offset points", color=c["fg"], fontsize=8)
        if ln.series: ax.set_xlim(min(min(s[1]) for s in ln.series), max(max(s[1]) for s in ln.series))
        ax.set_xlabel(ln.xlabel, fontsize=9); ax.set_ylabel(ln.ylabel, fontsize=9); ax.set_title(ln.title, fontsize=10, pad=10)
        ax.grid(True, color=c["grid"], lw=0.5, alpha=0.6)
        if len(ln.series) > 1:
            legend = ax.legend(fontsize=8, frameon=False, loc="best")
            for text in legend.get_texts(): text.set_color(c["fg"])

    def draw_bars(self, ax, b: Bars, c: dict) -> None:
        n = len(b.values); pos = list(range(n))[::-1]
        colours = [c["line"] if i == b.highlight else c["sub"] for i in range(n)]
        ax.barh(pos, b.values, color=colours, height=0.6)
        ax.set_yticks(pos); ax.set_yticklabels(b.labels, fontsize=8)
        for p, v in zip(pos, b.values): ax.annotate(f"{v:.2f}", (v, p), xytext=(4, 0), textcoords="offset points", va="center", color=c["fg"], fontsize=8)
        ax.axvline(0, color=c["sub"], lw=0.8)
        if b.values: ax.set_xlim(min(0, min(b.values)), max(b.values) * 1.15 if max(b.values) > 0 else 1)
        ax.set_xlabel(b.xlabel, fontsize=9); ax.set_title(b.title, fontsize=10, pad=10)
        ax.grid(True, axis="x", color=c["grid"], lw=0.5, alpha=0.6)

    ##### zoom #####
    def set_view(self, view, emit: bool=True) -> None:
        changed = (view is None) != (self.view is None) or view != self.view
        self.view = view
        if emit and changed: self.zoomed.emit(view is not None)

    def zoom_to(self, x0: float, x1: float, y0: "float | None"=None, y1: "float | None"=None) -> None:
        """Shows x0..x1 (and y0..y1); without y, y is fitted to the data visible between x0 and x1."""
        if self.last is None: return
        x0, x1 = sorted((x0, x1))
        if y0 is None or y1 is None: y0, y1 = self.fit_y(x0, x1)
        else: y0, y1 = sorted((y0, y1))
        if x1 - x0 <= 0 or y1 - y0 <= 0: return
        self.set_view(((x0, x1), (y0, y1))); self.redraw()

    def fit_y(self, x0: float, x1: float) -> tuple:
        """The y range of what is drawn between x0 and x1, with a small margin (spectra keep 0 at the bottom)."""
        item, ys = self.last, []
        if isinstance(item, Lines): ys = [y for _, xs, yv in item.series for x, y in zip(xs, yv) if x0 <= x <= x1]
        elif isinstance(item, Bars): return self.ax.get_ylim()
        elif item is not None:
            ys = [y for x, y in zip(item.x, item.y) if x0 <= x <= x1] + [h for p, h in item.sticks if x0 <= p <= x1]
        if not ys: return self.ax.get_ylim()
        lo, hi = min(ys), max(ys); pad = (hi - lo) * 0.08 or abs(hi) * 0.08 or 1.0
        if item is not None and not isinstance(item, Lines): return (0.0, hi + pad)
        return (lo - pad, hi + pad)

    def reset_view(self) -> None:
        if self.view is not None: self.set_view(None); self.redraw()

    def pressed(self, e) -> None:
        if self.last is None or e.inaxes is not self.ax: return
        if e.dblclick: self.drag = None; self.reset_view(); return
        if e.button == 1: self.drag = (e.x, e.y, e.xdata, e.ydata)

    def moved(self, e) -> None:
        if e.inaxes is self.ax and e.xdata is not None and self.last is not None:
            self.cursor.emit(self.readout(e.xdata, e.ydata)); self.setCursor(Qt.CrossCursor)
        else: self.cursor.emit(""); self.unsetCursor()
        if self.drag is None or e.xdata is None or e.inaxes is not self.ax: return
        x, y = self.drag[2], self.drag[3]; c = self.colours()
        if self.band is None:
            self.band = Rectangle((x, y), 0, 0, fill=True, facecolor=c["line"], alpha=0.12, edgecolor=c["line"], lw=1, ls="--"); self.ax.add_patch(self.band)
        if abs(e.y - self.drag[1]) < X_ONLY * abs(e.x - self.drag[0]):                   ## mostly horizontal: show the full height
            y0, y1 = self.ax.get_ylim(); self.band.set_bounds(min(x, e.xdata), y0, abs(e.xdata - x), y1 - y0)
        else: self.band.set_bounds(min(x, e.xdata), min(y, e.ydata), abs(e.xdata - x), abs(e.ydata - y))
        self.draw_idle()

    def released(self, e) -> None:
        start, self.drag = self.drag, None
        if start is None: return
        if self.band is not None: self.band.remove(); self.band = None
        if e.xdata is None or e.inaxes is not self.ax: self.draw_idle(); return
        dx, dy = abs(e.x - start[0]), abs(e.y - start[1])
        if dx < DRAG_MIN and dy < DRAG_MIN: self.draw_idle(); return
        if dy < X_ONLY * dx: self.zoom_to(start[2], e.xdata)
        elif dx >= DRAG_MIN and dy >= DRAG_MIN: self.zoom_to(start[2], e.xdata, start[3], e.ydata)
        else: self.draw_idle()

    def readout(self, x: float, y: float) -> str:
        item = self.last
        if isinstance(item, Bars):
            i = round(len(item.labels) - 1 - y) if item.labels else -1
            return f"{item.labels[i]}: {item.values[i]:.2f}" if 0 <= i < len(item.labels) else f"{x:.4g}"
        xl = (getattr(item, "xlabel", "") or "x").split(" (")[0]; yl = (getattr(item, "ylabel", "") or "y").split(" (")[0]
        return f"{xl} {x:.6g}   ·   {yl} {y:.4g}"

    def save(self, path: str, metadata: "dict | None"=None) -> None:
        """Saves what is shown (PNG, SVG or PDF from the extension), with the colours and the zoom on screen. `metadata` ({'Title',
        'Description'}, see results.plot_metadata) is written into the file itself, under the keys each format allows."""
        self.figure.savefig(path, dpi=200, facecolor=self.figure.get_facecolor(), metadata=file_metadata(path, metadata or {}))

def file_metadata(path: str, meta: dict) -> dict:
    """{'Title', 'Description'} as metadata keys that matplotlib accepts for the format of `path` (SVG refuses unknown keys, PDF warns)."""
    ext = path.rsplit(".", 1)[-1].lower(); title, text = meta.get("Title", ""), meta.get("Description", "")
    if ext == "png": return {"Title": title, "Description": text, "Software": "SCOPE GUI"}
    if ext == "svg": return {"Title": title, "Description": text, "Creator": "SCOPE GUI"}
    if ext == "pdf": return {"Title": title, "Subject": text, "Creator": "SCOPE GUI"}
    return {}

class ElidedLabel(QLabel):
    """One line of text cut with '…' to the room it has; the whole text is its tooltip. full_text() returns it."""
    def __init__(self, text: str=""):
        super().__init__(); self._full = ""; self.setMinimumWidth(10); self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred); self.set_full(text)

    def set_full(self, text: str, tip: str="") -> None:
        self._full = text; self.setToolTip(tip or text); self.elide()

    def full_text(self) -> str:
        return self._full

    def elide(self) -> None:
        super().setText(QFontMetrics(self.font()).elidedText(self._full, Qt.ElideMiddle, max(10, self.width())))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event); self.elide()

class PlotPanel(QWidget):
    """A PlotCanvas under a slim toolbar: the position under the mouse, a zoom hint, Reset view, and the buttons given (Copy, Save…)."""
    def __init__(self, canvas: PlotCanvas, buttons: list=()):
        super().__init__()
        self.canvas = canvas
        self.where = ElidedLabel(); self.where.setObjectName("pagesub")
        self.hint = QLabel("Drag to zoom · double-click to reset"); self.hint.setObjectName("pagesub")
        self.reset = QPushButton("Reset view"); self.reset.setEnabled(False); self.reset.clicked.connect(canvas.reset_view)
        self.reset.setToolTip("Show the whole plot again (or double-click on it)")
        bar = QHBoxLayout(); bar.setContentsMargins(0, 0, 0, 0); bar.setSpacing(8)
        bar.addWidget(self.where, 1); bar.addWidget(self.hint); bar.addWidget(self.reset)
        for b in buttons: bar.addWidget(b)
        lay = QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(4); lay.addLayout(bar); lay.addWidget(canvas, 1)
        canvas.zoomed.connect(self.reset.setEnabled); canvas.cursor.connect(self.where.set_full)
