"""
Startup banner for the Web Agent test runner.

Edit BANNER_CONFIG to change the displayed values without touching
the render logic.
"""

from __future__ import annotations

from rich.align import Align
from rich.console import Console
from rich.text import Text

from app.utils.build import get_build_name

# ── Configuration ──────────────────────────────────────────────────────────
# All user-facing values live here.  Swap ascii_title for any ASCII art
# string you like — the layout will center it automatically.

BANNER_CONFIG: dict = {
    "agent_name": "Web Agent",
    "version":    "1.0",
    "author":     "Cyberjaime45",

    # ASCII art title.  Replace with any multi-line string.
    "ascii_title": (
        "██╗    ██╗███████╗██████╗   █████╗  ██████╗ ███████╗███╗   ██╗████████╗\n"
        "██║    ██║██╔════╝██╔══██╗ ██╔══██╗██╔════╝ ██╔════╝████╗  ██║╚══██╔══╝\n"
        "██║ █╗ ██║█████╗  ██████╔╝ ███████║██║  ███╗█████╗  ██╔██╗ ██║   ██║   \n"
        "██║███╗██║██╔══╝  ██╔══██╗ ██╔══██║██║   ██║██╔══╝  ██║╚██╗██║   ██║   \n"
        "╚███╔███╔╝███████╗██████╔╝ ██║  ██║╚██████╔╝███████╗██║ ╚████║   ██║   \n"
        " ╚══╝╚══╝ ╚══════╝╚═════╝  ╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝  ╚═══╝   ╚═╝  "
    ),

    # Rich style strings — see https://rich.readthedocs.io/en/stable/style.html
    "title_color": "dark_cyan",
    "meta_color":  "dark_cyan",
}


# ── Render ─────────────────────────────────────────────────────────────────

def show_banner(config: dict | None = None) -> None:
    """Print the startup banner to stdout using Rich."""
    cfg = config or BANNER_CONFIG
    console = Console()

    title   = Text(cfg["ascii_title"], style=cfg["title_color"], no_wrap=True)
    version = Text(f"Version: {cfg['version']}",    style=cfg["meta_color"], justify="center")
    author  = Text(f"Created by: {cfg['author']}", style=cfg["meta_color"], justify="center")
    build   = Text(f"Build: {get_build_name()}",     style=cfg["meta_color"], justify="center")

    console.print()
    console.print(Align.center(title))
    console.print()
    console.print(Align.center(version))
    console.print(Align.center(author))
    console.print(Align.center(build))
    console.print()
