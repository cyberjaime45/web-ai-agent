"""URL helpers shared by skills, the diagnosis and the flow writer.

"The same page" throughout the framework means the same URL without its
``#fragment``: in-page anchors and hash routing do not count as navigation.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

# Sign-in and sign-out pages, by path or link text ("Log in", "/sso", "sign-out").
LOGIN_RE = re.compile(r"log[-_ ]?in|sign[-_ ]?in|/sso\b|/auth\b|/oauth", re.IGNORECASE)
LOGOUT_RE = re.compile(r"log[-_ ]?out|sign[-_ ]?out|log[-_ ]?off", re.IGNORECASE)


def strip_fragment(url: str) -> str:
    return (url or "").split("#", 1)[0]


def same_page(a: str, b: str) -> bool:
    """True when *a* and *b* differ at most in their ``#fragment``."""
    return strip_fragment(a) == strip_fragment(b)


def origin(url: str) -> str:
    """``https://example.com`` — scheme and host, the same-site boundary."""
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}"


def path_and_query(url: str) -> str:
    """``/members?page=2`` — what an ``assert_url`` step checks."""
    p = urlparse(url)
    return (p.path or "/") + (f"?{p.query}" if p.query else "")
