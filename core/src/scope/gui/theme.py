"""Light and dark themes of the SCOPE GUI.

The native macOS style ignores most palette changes, so the Fusion style is used with a complete palette (every
role, including the Disabled group) plus a stylesheet for the modern look. Colours live in two dictionaries, so
the code that draws by hand (the pipeline graph, status labels) asks `colors()` instead of hard-coding values and
is redrawn when the theme changes.
"""
import os
import tempfile
from PySide6.QtCore    import Qt
from PySide6.QtGui     import QColor, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication

LIGHT = {"window": "#f4f6f8", "base": "#ffffff", "alt": "#edf0f4", "text": "#1f2933", "sub": "#5c6773", "accent": "#2f6fed", "accent_text": "#ffffff", "border": "#d3d9e0", "control": "#8d98a5", "sidebar": "#1f2a37", "sidebar_text": "#e6ebf1", "sidebar_sub": "#93a1b1",
         "ok": "#1e8449", "warn": "#b9650e", "err": "#c0392b", "node": "#d6eaf8", "node_text": "#1b2631", "node_missing": "#fdebd0", "edge": "#34495e", "constrain": "#c0392b", "highlight": "#cfe0ff"}
DARK  = {"window": "#1e232a", "base": "#161a20", "alt": "#272d36", "text": "#e6e9ed", "sub": "#9aa5b1", "accent": "#5b9dff", "accent_text": "#0d1117", "border": "#38414d", "control": "#7b8794", "sidebar": "#12161c", "sidebar_text": "#e6ebf1", "sidebar_sub": "#7f8b99",
         "ok": "#4cd08a", "warn": "#f0b35a", "err": "#ff7a6e", "node": "#cfe3f7", "node_text": "#1b2631", "node_missing": "#f6d9b4", "edge": "#d5dbdb", "constrain": "#ff7a6e", "highlight": "#2c4a7c"}

_state     = {"mode": "light", "pref": "auto", "listeners": []}

def colors() -> dict:
    """Returns the colour dictionary of the theme in use."""
    return DARK if _state["mode"] == "dark" else LIGHT

def mode() -> str:
    """Returns 'light' or 'dark', the theme in use."""
    return _state["mode"]

def preference() -> str:
    """Returns the user's choice: 'light', 'dark' or 'auto' (follow the system)."""
    return _state["pref"]

def on_change(callback) -> None:
    """Registers a function called, with no arguments, after the theme changes."""
    _state["listeners"].append(callback)

def system_mode() -> str:
    """Returns the light/dark setting of the operating system ('light' if it cannot be read)."""
    try: return "dark" if QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark else "light"
    except Exception: return "light"

def palette(c: dict) -> QPalette:
    p = QPalette()
    roles = {QPalette.Window: c["window"], QPalette.WindowText: c["text"], QPalette.Base: c["base"], QPalette.AlternateBase: c["alt"], QPalette.Text: c["text"], QPalette.Button: c["alt"], QPalette.ButtonText: c["text"], QPalette.BrightText: c["err"],
             QPalette.ToolTipBase: c["base"], QPalette.ToolTipText: c["text"], QPalette.PlaceholderText: c["sub"], QPalette.Highlight: c["highlight"], QPalette.HighlightedText: c["text"], QPalette.Link: c["accent"], QPalette.LinkVisited: c["accent"],
             QPalette.Light: c["base"], QPalette.Midlight: c["alt"], QPalette.Mid: c["border"], QPalette.Dark: c["border"], QPalette.Shadow: c["border"]}
    for role, value in roles.items():
        p.setColor(QPalette.Active, role, QColor(value)); p.setColor(QPalette.Inactive, role, QColor(value))
        p.setColor(QPalette.Disabled, role, QColor(c["sub"]) if role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText) else QColor(value))
    return p

ICONS = {                                                                   ## drawn on the accent colour (tick) or on the field colour (dot)
    "check": '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16"><path d="M3.6 8.3l2.9 2.9 5.9-6.2" fill="none" stroke="{fg}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    "dash":  '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16"><path d="M4 8h8" stroke="{fg}" stroke-width="2" stroke-linecap="round"/></svg>',
    "dot":   '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16"><circle cx="8" cy="8" r="3.6" fill="{fg}"/></svg>'}

def icons(c: dict) -> dict:
    """Writes the tick, dash and dot of the check boxes and option buttons in this theme's colours (enabled and disabled) and returns
    {name: path with forward slashes}. A stylesheet that draws the box itself needs its marks as files; they are tiny and rewritten
    when missing, in a folder of the user's temporary directory."""
    folder = os.path.join(tempfile.gettempdir(), f"scope-gui-icons-{getattr(os, 'getuid', lambda: 0)()}"); out = {}
    for name, svg in ICONS.items():
        for state, fg in (("", c["accent"] if name == "dot" else c["accent_text"]), ("_off", c["sub"])):
            path = os.path.join(folder, f"{name}{state}_{fg.lstrip('#')}.svg")
            try:
                if not os.path.exists(path): os.makedirs(folder, exist_ok=True); open(path, "w").write(svg.format(fg=fg))
            except OSError: pass
            out[name + state] = path.replace(os.sep, "/")
    return out

def indicators(c: dict) -> str:
    """Check boxes and option buttons drawn by the stylesheet: Fusion draws their outline from the window colour made darker, which is
    nearly invisible on the dark theme."""
    i = icons(c)
    return f"""
    QCheckBox::indicator, QRadioButton::indicator, QAbstractItemView::indicator {{ width: 14px; height: 14px; border: 1px solid {c['control']}; background: {c['base']}; }}
    QCheckBox::indicator, QAbstractItemView::indicator {{ border-radius: 4px; }}
    QRadioButton::indicator {{ border-radius: 8px; }}
    QCheckBox::indicator:hover, QRadioButton::indicator:hover, QAbstractItemView::indicator:hover {{ border-color: {c['accent']}; }}
    QCheckBox::indicator:checked, QAbstractItemView::indicator:checked {{ background: {c['accent']}; border-color: {c['accent']}; image: url({i['check']}); }}
    QCheckBox::indicator:indeterminate, QAbstractItemView::indicator:indeterminate {{ background: {c['accent']}; border-color: {c['accent']}; image: url({i['dash']}); }}
    QRadioButton::indicator:checked {{ border-color: {c['accent']}; image: url({i['dot']}); }}
    QCheckBox::indicator:disabled, QRadioButton::indicator:disabled, QAbstractItemView::indicator:disabled {{ background: {c['alt']}; border-color: {c['border']}; }}
    QCheckBox::indicator:checked:disabled, QAbstractItemView::indicator:checked:disabled {{ background: {c['border']}; border-color: {c['border']}; image: url({i['check_off']}); }}
    QRadioButton::indicator:checked:disabled {{ image: url({i['dot_off']}); }}
    QCheckBox, QRadioButton {{ spacing: 8px; }}
    """

def stylesheet(c: dict) -> str:
    return indicators(c) + f"""
    QWidget {{ font-size: 13px; }}
    QMainWindow, QDialog {{ background: {c['window']}; }}
    QToolTip {{ background: {c['base']}; color: {c['text']}; border: 1px solid {c['border']}; padding: 4px; }}
    QPushButton {{ background: {c['alt']}; color: {c['text']}; border: 1px solid {c['border']}; border-radius: 7px; padding: 6px 14px; }}
    QPushButton:hover {{ border-color: {c['accent']}; }}
    QPushButton:disabled {{ color: {c['sub']}; background: {c['window']}; }}
    QPushButton[primary="true"] {{ background: {c['accent']}; color: {c['accent_text']}; border: 1px solid {c['accent']}; font-weight: 600; }}
    QPushButton[primary="true"]:disabled {{ background: {c['border']}; color: {c['sub']}; border-color: {c['border']}; }}
    QLineEdit, QSpinBox, QComboBox, QPlainTextEdit, QTextBrowser, QTextEdit {{ background: {c['base']}; color: {c['text']}; border: 1px solid {c['border']}; border-radius: 6px; padding: 4px 6px; selection-background-color: {c['highlight']}; selection-color: {c['text']}; }}
    QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus {{ border: 1px solid {c['accent']}; }}
    QComboBox QAbstractItemView {{ background: {c['base']}; color: {c['text']}; selection-background-color: {c['highlight']}; border: 1px solid {c['border']}; }}
    QTableWidget {{ background: {c['base']}; alternate-background-color: {c['alt']}; color: {c['text']}; border: 1px solid {c['border']}; border-radius: 6px; gridline-color: {c['border']}; selection-background-color: {c['highlight']}; selection-color: {c['text']}; }}
    QHeaderView::section {{ background: {c['alt']}; color: {c['sub']}; border: none; border-bottom: 1px solid {c['border']}; padding: 6px; font-weight: 600; }}
    QTabWidget::pane {{ border: 1px solid {c['border']}; border-radius: 6px; background: {c['window']}; }}
    QTabBar::tab {{ background: transparent; color: {c['sub']}; padding: 6px 12px; border-bottom: 2px solid transparent; }}
    QTabBar::tab:selected {{ color: {c['text']}; border-bottom: 2px solid {c['accent']}; }}
    QSplitter::handle {{ background: {c['border']}; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
    QScrollBar::handle:vertical {{ background: {c['border']}; border-radius: 5px; min-height: 30px; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0; }}
    QScrollBar::handle:horizontal {{ background: {c['border']}; border-radius: 5px; min-width: 30px; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
    QStatusBar {{ background: {c['window']}; color: {c['sub']}; }}
    QFrame#sidebar {{ background: {c['sidebar']}; }}
    QLabel#brand {{ color: {c['sidebar_text']}; font-size: 20px; font-weight: 700; }}
    QFrame#statuscard {{ background: rgba(255,255,255,0.045); border: 1px solid rgba(255,255,255,0.08); border-radius: 8px; }}
    QLabel#statusrow {{ padding: 5px 6px; border-radius: 5px; font-size: 12px; }}
    QLabel#statusrow:hover {{ background: rgba(255,255,255,0.07); }}
    QFrame#sidesep {{ background: rgba(255,255,255,0.08); border: none; margin: 0 14px; }}
    QLabel#brandsub {{ color: {c['sidebar_sub']}; font-size: 11px; }}
    QPushButton#step {{ background: transparent; color: {c['sidebar_text']}; border: none; border-left: 3px solid transparent; border-radius: 0; text-align: left; padding: 9px 16px; }}
    QPushButton#step:hover {{ background: rgba(255,255,255,0.07); }}
    QPushButton#step:checked {{ background: rgba(255,255,255,0.12); border-left: 3px solid {c['accent']}; font-weight: 600; }}
    QPushButton#themebtn {{ background: transparent; color: {c['sidebar_sub']}; border: 1px solid {c['sidebar_sub']}; border-radius: 12px; padding: 4px 10px; }}
    QPushButton#themebtn:hover {{ color: {c['sidebar_text']}; border-color: {c['sidebar_text']}; }}
    QLabel[kind="ok"] {{ color: {c['ok']}; font-weight: 600; }}
    QLabel[kind="warn"] {{ color: {c['warn']}; font-weight: 600; }}
    QLabel[kind="err"] {{ color: {c['err']}; font-weight: 600; }}
    QLabel#pagetitle {{ font-size: 22px; font-weight: 700; color: {c['text']}; }}
    QLabel#pagesub {{ color: {c['sub']}; }}
    QPushButton#linkbtn {{ background: transparent; border: none; color: {c['accent']}; padding: 2px 0; text-align: left; }}
    QPushButton#linkbtn:hover {{ text-decoration: underline; }}
    QLabel#sectiontitle {{ color: {c['text']}; font-weight: 700; padding-top: 8px; }}
    QLabel#wslabel {{ color: {c['sidebar_sub']}; font-size: 10px; font-weight: 600; letter-spacing: 1px; }}
    QComboBox#wscombo {{ background: rgba(255,255,255,0.08); color: {c['sidebar_text']}; border: 1px solid rgba(255,255,255,0.18); border-radius: 6px; padding: 4px 8px; }}
    QPushButton#wsbtn::menu-indicator {{ image: none; width: 0px; }}
    QPushButton#wsbtn {{ background: transparent; color: {c['sidebar_text']}; border: 1px solid rgba(255,255,255,0.18); border-radius: 6px; padding: 3px 8px; }}
    QLabel#badge {{ background: {c['alt']}; border: 1px solid {c['border']}; border-radius: 10px; padding: 3px 10px; color: {c['sub']}; }}
    QListWidget#manualtoc {{ background: transparent; border: none; outline: 0; }}
    QListWidget#manualtoc::item {{ padding: 7px 10px; margin: 1px 0; border-radius: 6px; color: {c['text']}; }}
    QListWidget#manualtoc::item:hover {{ background: {c['alt']}; }}
    QListWidget#manualtoc::item:selected {{ background: {c['highlight']}; color: {c['text']}; font-weight: 600; }}
    QListWidget#manualtoc::item:disabled {{ color: {c['sub']}; padding-top: 14px; }}
    QTextBrowser#manualview {{ background: {c['base']}; border: 1px solid {c['border']}; border-radius: 10px; padding: 0; }}
    QFrame#card {{ background: {c['base']}; border: 1px solid {c['border']}; border-radius: 10px; }}
    QFrame#lighttile {{ background: {c['alt']}; border: 1px solid {c['border']}; border-radius: 8px; }}
    QLabel#restitle {{ font-size: 18px; font-weight: 700; color: {c['text']}; }}
    QLabel#cardtitle {{ color: {c['sub']}; font-size: 11px; font-weight: 700; letter-spacing: 1px; text-transform: uppercase; }}
    QListWidget#navlist {{ background: transparent; border: none; outline: 0; }}
    QListWidget#navlist::item {{ padding: 6px 8px; margin: 1px 0; border-radius: 6px; color: {c['text']}; }}
    QListWidget#navlist::item:hover {{ background: {c['alt']}; }}
    QListWidget#navlist::item:selected {{ background: {c['highlight']}; color: {c['text']}; font-weight: 600; }}
    """

def fit(widget, width: int, height: int) -> None:
    """Open a window at its preferred size, but never larger than the screen's free area (a 1366x768 laptop minus the taskbar), so the
    title bar and the buttons at the bottom stay reachable."""
    screen = widget.screen() or QGuiApplication.primaryScreen()
    if screen is None: widget.resize(width, height); return
    free = screen.availableGeometry(); widget.resize(min(width, int(free.width() * 0.95)), min(height, int(free.height() * 0.92)))

def set_kind(widget, kind: str) -> None:
    """Marks a label as 'ok', 'warn' or 'err' so the stylesheet colours it, and recolours it when the theme changes."""
    widget.setProperty("kind", kind); widget.style().unpolish(widget); widget.style().polish(widget)

def apply(app: QApplication, preference: str="auto") -> str:
    """Applies a theme to the whole application and redraws the widgets that paint themselves.

    Parameters:
        app:         The QApplication.
        preference:  'light', 'dark' or 'auto' (follow the system).

    Returns:
        str: 'light' or 'dark', the theme now in use.
    """
    if preference not in ("light", "dark", "auto"): preference = "auto"
    _state["pref"] = preference
    _state["mode"] = system_mode() if preference == "auto" else preference
    if app.style().objectName().lower() != "fusion": app.setStyle("Fusion")
    c = colors()
    app.setPalette(palette(c)); app.setStyleSheet(stylesheet(c))
    for callback in list(_state["listeners"]):
        try: callback()
        except Exception: pass
    return _state["mode"]

