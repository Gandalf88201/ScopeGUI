"""A matplotlib canvas for the window: follows the light/dark theme and draws a spectrum (curve, filled area, sticks), curves against
temperature, or horizontal bars; saves PNG, SVG or PDF with where the numbers come from written into the file's metadata.

It uses matplotlib's Figure directly, never pyplot: no global figures, and no plt.show(), which must not run outside the main thread.
"""
from dataclasses import dataclass, field
from PySide6.QtCore    import QSize
from PySide6.QtWidgets import QSizePolicy
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
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

class PlotCanvas(FigureCanvasQTAgg):
    """Attributes: last (the Spectrum, Lines or Bars drawn last, or None), message (text shown instead of a plot)."""
    def __init__(self):
        self.figure = Figure(figsize=(6, 3.4), dpi=100, layout="tight")
        super().__init__(self.figure)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding); self.setMinimumHeight(170)
        self.last, self.message = None, ""
        theme.on_change(self.redraw)

    def sizeHint(self) -> "QSize":
        """Smaller than the figure's own size (600 x 340): the plot takes the room it is given instead of asking for more."""
        return QSize(480, 220)

    def colours(self) -> dict:
        c = theme.colors()
        return {"bg": c["base"], "fg": c["text"], "sub": c["sub"], "grid": c["border"], "line": c["accent"], "stick": c["err"], "series": [c["accent"], c["err"], c["ok"], c["warn"], c["sub"]]}

    def show_message(self, text: str) -> None:
        self.last, self.message = None, text; self.redraw()

    def plot_spectrum(self, sp: "object") -> None:
        self.last, self.message = sp, ""; self.redraw()

    def plot(self, item: "Lines | Bars") -> None:
        self.last, self.message = item, ""; self.redraw()

    def redraw(self) -> None:
        c = self.colours(); fig = self.figure; fig.clear(); fig.set_facecolor(c["bg"])
        ax = fig.add_subplot(111); ax.set_facecolor(c["bg"])
        for spine in ax.spines.values(): spine.set_color(c["grid"])
        ax.tick_params(colors=c["sub"], labelsize=9); ax.xaxis.label.set_color(c["fg"]); ax.yaxis.label.set_color(c["fg"]); ax.title.set_color(c["fg"])
        item = self.last
        if item is None:
            ax.set_xticks([]); ax.set_yticks([])
            ax.text(0.5, 0.5, self.message, ha="center", va="center", color=c["sub"], fontsize=10, wrap=True, transform=ax.transAxes)
        elif isinstance(item, Lines): self.draw_lines(ax, item, c)
        elif isinstance(item, Bars):  self.draw_bars(ax, item, c)
        else:                         self.draw_spectrum(ax, item, c)
        self.draw_idle()

    def draw_spectrum(self, ax, sp, c: dict) -> None:
        ax.plot(sp.x, sp.y, color=c["line"], lw=1.4); ax.fill_between(sp.x, 0, sp.y, color=c["line"], alpha=0.18)
        lo, hi = min(sp.x), max(sp.x)
        sticks = [(p, h) for p, h in sp.sticks if lo <= p <= hi]
        if any(h for _, h in sticks): ax.vlines([p for p, _ in sticks], 0, [h for _, h in sticks], color=c["stick"], lw=0.8, alpha=0.8)
        elif sticks: ax.plot([p for p, _ in sticks], [0] * len(sticks), "|", color=c["stick"], markersize=8, transform=ax.get_xaxis_transform())    ## positions only (VDOS)
        ax.set_xlim(lo, hi); ax.set_ylim(bottom=0)
        ax.set_xlabel(sp.xlabel, fontsize=9); ax.set_ylabel(sp.ylabel, fontsize=9); ax.set_title(sp.title, fontsize=10)
        ax.grid(True, color=c["grid"], lw=0.5, alpha=0.6)

    def draw_lines(self, ax, ln: Lines, c: dict) -> None:
        for k, (label, x, y) in enumerate(ln.series): ax.plot(x, y, color=c["series"][k % len(c["series"])], lw=1.6 if k == 0 else 1.2, label=label)
        if ln.zero: ax.axhline(0, color=c["sub"], lw=0.8)
        for x, label in ln.marks:
            ax.axvline(x, color=c["fg"], lw=0.9, ls="--"); ax.annotate(label, (x, 1), xycoords=("data", "axes fraction"), xytext=(4, -12), textcoords="offset points", color=c["fg"], fontsize=8)
        if ln.series: ax.set_xlim(min(min(s[1]) for s in ln.series), max(max(s[1]) for s in ln.series))
        ax.set_xlabel(ln.xlabel, fontsize=9); ax.set_ylabel(ln.ylabel, fontsize=9); ax.set_title(ln.title, fontsize=10)
        ax.grid(True, color=c["grid"], lw=0.5, alpha=0.6)
        if len(ln.series) > 1:
            legend = ax.legend(fontsize=8, frameon=False)
            for text in legend.get_texts(): text.set_color(c["fg"])

    def draw_bars(self, ax, b: Bars, c: dict) -> None:
        n = len(b.values); pos = list(range(n))[::-1]
        colours = [c["line"] if i == b.highlight else c["sub"] for i in range(n)]
        ax.barh(pos, b.values, color=colours, height=0.6)
        ax.set_yticks(pos); ax.set_yticklabels(b.labels, fontsize=8)
        for p, v in zip(pos, b.values): ax.annotate(f"{v:.2f}", (v, p), xytext=(4, 0), textcoords="offset points", va="center", color=c["fg"], fontsize=8)
        ax.axvline(0, color=c["sub"], lw=0.8)
        if b.values: ax.set_xlim(min(0, min(b.values)), max(b.values) * 1.15 if max(b.values) > 0 else 1)
        ax.set_xlabel(b.xlabel, fontsize=9); ax.set_title(b.title, fontsize=10)
        ax.grid(True, axis="x", color=c["grid"], lw=0.5, alpha=0.6)

    def save(self, path: str, metadata: "dict | None"=None) -> None:
        """Saves what is shown (PNG, SVG or PDF from the extension), with the colours on screen. `metadata` ({'Title', 'Description'},
        see results.plot_metadata) is written into the file itself, under the keys each format allows."""
        self.figure.savefig(path, dpi=200, facecolor=self.figure.get_facecolor(), metadata=file_metadata(path, metadata or {}))

def file_metadata(path: str, meta: dict) -> dict:
    """{'Title', 'Description'} as metadata keys that matplotlib accepts for the format of `path` (SVG refuses unknown keys, PDF warns)."""
    ext = path.rsplit(".", 1)[-1].lower(); title, text = meta.get("Title", ""), meta.get("Description", "")
    if ext == "png": return {"Title": title, "Description": text, "Software": "SCOPE GUI"}
    if ext == "svg": return {"Title": title, "Description": text, "Creator": "SCOPE GUI"}
    if ext == "pdf": return {"Title": title, "Subject": text, "Creator": "SCOPE GUI"}
    return {}
