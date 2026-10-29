"""Local, offline poker advisor."""
import os as _os

# Hide harmless Qt warnings about keyboard text input on Wayland
# ("QWaylandTextInputv3 ... is already enabled") that flood the terminal.
_os.environ.setdefault("QT_LOGGING_RULES", "qt.qpa.wayland.textinput=false")
