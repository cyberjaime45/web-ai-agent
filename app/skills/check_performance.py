"""check_performance — how fast the current document loaded, against budgets.

    - check_performance
    - check_performance: "lcp=4000" | "load=8000"       budgets in ms (cls is a score)

One ``page.evaluate`` reading the browser's own measurements for the
current document: Navigation Timing (time to first byte, DOMContentLoaded,
load), Largest Contentful Paint and Cumulative Layout Shift, plus the
number and size of the resources it fetched.

    metric   budget (default)   meaning
    ttfb     800 ms             server answered the document request
    dcl      3000 ms            DOM ready
    load     5000 ms            load event finished
    lcp      2500 ms            largest text or image painted
    cls      0.1                layout shift while loading (a score, not ms)

Over-budget metrics are warnings; nothing here fails a step, because test
machines and networks are noisy. The values are in the check details so the
report doubles as a trend record. The timings describe the last full page
load: after in-page navigation in a single-page app they still show the
initial load.
"""

from __future__ import annotations

from app.schemas.actions import ActionType, Check
from app.skills.base import SkillContext, info, skill

BUDGETS: dict[str, float] = {"ttfb": 800, "dcl": 3000, "load": 5000, "lcp": 2500, "cls": 0.1}
LABELS = {"ttfb": "time to first byte", "dcl": "DOM ready", "load": "page load",
          "lcp": "largest contentful paint", "cls": "layout shift"}

_METRICS_JS = r"""
async () => {
  const observed = type => new Promise(resolve => {
    const entries = [];
    try {
      const po = new PerformanceObserver(list => entries.push(...list.getEntries()));
      po.observe({ type, buffered: true });
      setTimeout(() => { po.disconnect(); resolve(entries); }, 50);
    } catch (e) { resolve(entries); }
  });
  const nav = performance.getEntriesByType('navigation')[0];
  const lcp = await observed('largest-contentful-paint');
  const shifts = await observed('layout-shift');
  const resources = performance.getEntriesByType('resource');
  const round = v => v == null ? null : Math.round(v);
  return {
    ttfb: nav ? round(nav.responseStart) : null,
    dcl: nav && nav.domContentLoadedEventEnd ? round(nav.domContentLoadedEventEnd) : null,
    load: nav && nav.loadEventEnd ? round(nav.loadEventEnd) : null,
    lcp: lcp.length ? round(lcp[lcp.length - 1].startTime) : null,
    cls: shifts.filter(s => !s.hadRecentInput).reduce((sum, s) => sum + s.value, 0),
    resources: resources.length,
    kb: Math.round(resources.reduce((sum, r) => sum + (r.transferSize || 0), 0) / 1024),
  };
}
"""


def _fmt(metric: str, value: float) -> str:
    return f"{value:.3f}" if metric == "cls" else f"{int(value)} ms"


@skill(ActionType.CHECK_PERFORMANCE)
def check_performance(sc: SkillContext) -> list[Check]:
    m = sc.evaluate(_METRICS_JS)
    if not m:
        return [Check("performance measured", False, "warn", "the browser returned no timing data")]
    budgets = {k: float(sc.option(k, str(v)) or v) for k, v in BUDGETS.items()}
    measured = [f"{k} {_fmt(k, m[k])}" for k in BUDGETS if m.get(k) is not None]
    checks = [info("performance", ", ".join(measured) + f"; {m['resources']} resources, {m['kb']} KB")]
    for metric, budget in budgets.items():
        value = m.get(metric)
        if value is None:
            continue
        ok = value <= budget
        checks.append(Check(f"{LABELS[metric]} within budget", ok, "warn",
                            f"{_fmt(metric, value)} (budget {_fmt(metric, budget)})"))
    return checks
