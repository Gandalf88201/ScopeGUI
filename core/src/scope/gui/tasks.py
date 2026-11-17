"""A small worker for slow, Qt-free calls (network, subprocess): runs a function on the thread pool and reports back with signals."""
from collections.abc import Callable
from PySide6.QtCore import QObject, QRunnable, Signal

class Signals(QObject):
    done   = Signal(object)
    failed = Signal(str)

class Task(QRunnable):
    """Runs `fn()` in a worker thread. Connect task.signals.done / failed (they are delivered in the window thread). Keep a reference to the task until it ends."""
    def __init__(self, fn: Callable[[], object]):
        super().__init__(); self.fn, self.signals = fn, Signals()
    def run(self) -> None:
        try: res = self.fn()
        except Exception as exc: self.signals.failed.emit(f"{type(exc).__name__}: {exc}")
        else: self.signals.done.emit(res)
