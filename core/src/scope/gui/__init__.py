"""Optional graphical interface of SCOPE.

The Qt window lives in scope.gui.window and is imported lazily by the `scope gui` command, so SCOPE keeps working
on machines without PySide6 (for instance on a cluster). scope.gui.backend has no Qt dependency.
"""
