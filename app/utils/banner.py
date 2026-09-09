"""Startup banner printed once at the top of a pytest session.

Ported from Astra's ``banner.py``: plain text centered to the terminal width,
green when stdout is a TTY, no third-party rendering. Shows the version,
the author, the run's build name, and the same environment label the
execution summary ends with (``env · browser · mode[ · lambda]``).
"""

from __future__ import annotations

import shutil
import sys

from app.config.settings import settings
from app.utils.build import get_build_name

APP_VERSION = "1.0.0"
CREATED_BY = "Cyberjaime45"

_ART = (
    "██╗    ██╗███████╗██████╗   █████╗  ██████╗ ███████╗███╗   ██╗████████╗\n"
    "██║    ██║██╔════╝██╔══██╗ ██╔══██╗██╔════╝ ██╔════╝████╗  ██║╚══██╔══╝\n"
    "██║ █╗ ██║█████╗  ██████╔╝ ███████║██║  ███╗█████╗  ██╔██╗ ██║   ██║   \n"
    "██║███╗██║██╔══╝  ██╔══██╗ ██╔══██║██║   ██║██╔══╝  ██║╚██╗██║   ██║   \n"
    "╚███╔███╔╝███████╗██████╔╝ ██║  ██║╚██████╔╝███████╗██║ ╚████║   ██║   \n"
    " ╚══╝╚══╝ ╚══════╝╚═════╝  ╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝  ╚═══╝   ╚═╝  "
)

# Pad the art to one block width so centering can't skew the lines.
_ART_WIDTH = max(len(line) for line in _ART.splitlines())

_GREEN = "\033[32m"
_RESET = "\033[0m"


def banner_text(*, color: bool = False, width: int | None = None) -> str:
    """The banner centered to *width* (defaults to the terminal width)."""
    width = width or shutil.get_terminal_size(fallback=(80, 24)).columns
    lines = [
        *(line.ljust(_ART_WIDTH) for line in _ART.splitlines()),
        "",
        f"Version: {APP_VERSION}",
        f"Created by: {CREATED_BY}",
        f"Build: {get_build_name()}",
        settings.run_label(),
    ]
    text = "\n".join(line.center(width).rstrip() for line in lines)
    return f"{_GREEN}{text}{_RESET}" if color else text


def show_banner() -> None:
    print(f"\n{banner_text(color=sys.stdout.isatty())}\n")
