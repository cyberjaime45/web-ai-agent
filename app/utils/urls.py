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


# ── The site under test ──────────────────────────────────────────────────────

# Suffixes of two labels a registrable domain sits under — country suffixes
# ("example.co.uk") and hosting platforms whose tenants are separate sites
# ("myapp.azurewebsites.net"). Best effort; a flow's `site_domain:` overrides.
_TWO_LABEL_SUFFIXES = frozenset({
    "co.uk", "org.uk", "ac.uk", "gov.uk", "me.uk", "com.au", "net.au", "org.au", "gov.au",
    "co.nz", "co.jp", "ac.jp", "co.kr", "com.cn", "com.br", "com.mx", "co.in", "co.za",
    "com.sg", "com.ar", "azurewebsites.net", "cloudfront.net", "herokuapp.com",
    "appspot.com", "firebaseapp.com", "github.io", "vercel.app", "netlify.app",
    "pages.dev", "web.app",
})
_IP_RE = re.compile(r"^[\d.]+$|:")
_NO_SITE_SCHEMES = frozenset({"tel", "mailto", "javascript", "about", "sms"})


def _ascii_host(host: str) -> str:
    """Lower case, no trailing dot, punycode — how the browser reports hosts."""
    host = (host or "").strip().lower().strip(".")
    try:
        return host.encode("idna").decode("ascii") if not host.isascii() else host
    except UnicodeError:
        return host


def registrable_domain(host: str) -> str:
    """``memberssitestaging.wheelsup.com`` → ``wheelsup.com``; ``a.example.co.uk``
    → ``example.co.uk``. IP addresses, ``localhost`` and single labels stay as they are."""
    host = _ascii_host(host)
    labels = host.split(".")
    if not host or _IP_RE.search(host) or len(labels) < 2:
        return host
    keep = 3 if ".".join(labels[-2:]) in _TWO_LABEL_SUFFIXES else 2
    return ".".join(labels[-keep:])


def site_domain(url: str) -> str:
    """The registrable domain of *url*'s host; ``""`` for a URL without one (about:blank, tel:, file:)."""
    p = urlparse(url or "")
    return registrable_domain(p.hostname or "") if p.scheme in ("http", "https") else ""


def normalize_domain(value: str) -> str:
    """A domain as written in a flow (``Example.com``, ``https://example.com/``,
    ``localhost:3000``) → the bare host ``in_site`` compares with (``example.com``)."""
    value = (value or "").strip().strip('"')
    host = urlparse(value if "://" in value else f"//{value}").hostname or ""
    return _ascii_host(host)


def in_site(url: str, domain: str) -> bool:
    """Whether *url* belongs to the site *domain* (a normalized host, as
    ``site_domain`` / ``normalize_domain`` return it): its host is the domain or
    a subdomain of it, compared label by label — ``otherwheelsup.com`` and
    ``wheelsup.com.example.org`` are not ``wheelsup.com``. With a domain, only
    http(s) and ws(s) URLs can belong to it; with none known (a flow on a
    ``file://`` page), every URL does except tel:, mailto: and the like."""
    p = urlparse(url or "")
    if not domain:
        return p.scheme not in _NO_SITE_SCHEMES
    if p.scheme not in ("http", "https", "ws", "wss"):
        return False
    host = (p.hostname or "").rstrip(".")
    return host == domain or host.endswith("." + domain)
