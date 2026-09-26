"""check_links — broken links and broken images, without clicking anything.

Every ``a[href]`` on the page is requested through the browser context's
request API, which shares the page's cookies: HEAD first, GET when HEAD is
refused. Nothing is pressed and nothing is added to the report's network
log. Links are deduplicated (fragment ignored) and same-site by default.

    - check_links                                  same-site links, up to 50
    - check_links: "external=true" | "max_links=100"
    - check_links: "images=false"                  links only

Broken (error): 404 / 410, 5xx, or unreachable.
Restricted (warn): 401 / 403 / 429 / other 4xx, or a redirect to a login page.
Never requested: logout links, and links whose path looks destructive
(delete, unsubscribe, checkout…) unless the flow allows destructive actions.
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from app.agent.safety import DESTRUCTIVE_PATHS
from app.schemas.actions import ActionType, Check, summarize
from app.skills.base import SkillContext, info, skill
from app.utils.urls import LOGIN_RE, LOGOUT_RE

logger = logging.getLogger(__name__)

DEFAULT_MAX_LINKS = 50
REQUEST_TIMEOUT_MS = 10_000


_COLLECT_JS = r"""
() => {
  const links = [], seen = new Set(), images = [];
  for (const a of document.querySelectorAll('a[href]')) {
    if (!/^https?:/i.test(a.href)) continue;
    const url = a.href.split('#')[0];
    if (seen.has(url)) continue;
    seen.add(url);
    links.push(url);
  }
  for (const img of document.images) {
    const r = img.getBoundingClientRect();
    if (!img.getAttribute('src') || r.width < 2 || r.height < 2) continue;
    if (img.complete && img.naturalWidth === 0) images.push(img.currentSrc || img.src);
  }
  return { links, images };
}
"""


def _unsafe(url: str, destructive_allowed: bool) -> str:
    """Why *url* must not be requested, or ``""``."""
    parsed = urlparse(url)
    target = f"{parsed.path}?{parsed.query}"
    if LOGOUT_RE.search(target):
        return "logout"
    path = parsed.path.lower()
    if not destructive_allowed and (hit := next((p for p in DESTRUCTIVE_PATHS if p in path), None)):
        return hit
    return ""


def _status(api, url: str) -> tuple[int | None, str, str]:
    """``(status, final url, error)`` — HEAD, then GET when HEAD is refused."""
    try:
        resp = api.head(url, timeout=REQUEST_TIMEOUT_MS, fail_on_status_code=False)
        if resp.status >= 400 and resp.status not in (404, 410):
            resp.dispose()
            resp = api.get(url, timeout=REQUEST_TIMEOUT_MS, fail_on_status_code=False)
        status, final = resp.status, resp.url
        resp.dispose()
        return status, final, ""
    except Exception as exc:
        return None, url, str(exc).splitlines()[0][:120]


@skill(ActionType.CHECK_LINKS)
def check_links(sc: SkillContext) -> list[Check]:
    found = sc.evaluate(_COLLECT_JS) or {"links": [], "images": []}
    origin = urlparse(sc.page.url).netloc
    external = sc.flag("external")
    max_links = int(sc.option("max_links", str(DEFAULT_MAX_LINKS)) or DEFAULT_MAX_LINKS)

    same_site = [u for u in found["links"] if urlparse(u).netloc == origin]
    candidates = found["links"] if external else same_site
    skipped: list[str] = []
    to_check: list[str] = []
    for url in candidates:
        if why := _unsafe(url, sc.policy.destructive_allowed):
            skipped.append(f"{url} ({why})")
        else:
            to_check.append(url)
    checked = to_check[:max_links]

    api = sc.page.context.request
    broken: list[str] = []
    restricted: list[str] = []
    for url in checked:
        status, final, error = _status(api, url)
        if status is None:
            broken.append(f"unreachable {url}: {error}")
        elif status in (404, 410) or status >= 500:
            broken.append(f"{status} {url}")
        elif status >= 400:
            restricted.append(f"{status} {url}")
        elif final != url and LOGIN_RE.search(urlparse(final).path) and not LOGIN_RE.search(urlparse(url).path):
            restricted.append(f"login redirect {url} → {final}")
    logger.info("[check_links] %d link(s) checked, %d broken, %d restricted",
                len(checked), len(broken), len(restricted))

    scope = "all sites" if external else "same site"
    summary = f"{len(checked)} of {len(found['links'])} links checked ({scope})"
    if not external and len(found["links"]) > len(same_site):
        summary += f"; {len(found['links']) - len(same_site)} external not checked (external=true)"
    if len(to_check) > max_links:
        summary += f"; {len(to_check) - max_links} over max_links={max_links}"
    checks = [
        info("links checked", summary),
        Check.listing("no broken links", broken, "error"),
        Check.listing("no restricted links", restricted, "warn"),
    ]
    if skipped:
        checks.append(info("links not requested", summarize(skipped)))
    if sc.flag("images", True):
        images = found["images"]
        checks.append(Check.listing("no broken images", images, "error"))
    return checks
