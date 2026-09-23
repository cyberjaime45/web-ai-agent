"""Observer — a small, structured picture of the current page.

Built from Playwright's accessibility snapshot (``aria_snapshot``), not the
DOM: headings, interactive controls, dialogs, navigation, tables, plus one
``page.evaluate`` for form metadata (field types, labels, required flags).
Every interactive node gets a stable ``ref`` (``e12``) that maps back to a
``get_by_role(role, name=…).nth(k)`` locator.

Deterministic skills (inspect_page, test_form) consume it directly; the
``to_prompt`` rendering is what a planner would send to an LLM — a few KB,
never the DOM. Two round-trips per call; only skills call it, never the
per-step loop.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# `option` is left out on purpose: a select's options ride on its combobox node.
INTERACTIVE_ROLES = frozenset({
    "button", "link", "textbox", "searchbox", "combobox", "listbox", "checkbox",
    "radio", "switch", "slider", "spinbutton", "tab", "menuitem",
})
STRUCTURAL_ROLES = frozenset({"heading", "dialog", "alertdialog", "navigation", "table", "form", "main"})
# Landmarks whose name gives their children context (safety: "OK" inside "Delete member?").
CONTAINER_ROLES = frozenset({"dialog", "alertdialog", "form", "navigation", "region", "main", "banner", "contentinfo"})
MAX_LINES = 600          # aria lines parsed (a huge page yields a partial, still useful picture)
MAX_TEXT = 300           # chars of visible text kept as a summary

# `- role "name" [attr=…] [attr]:`  — name and attrs optional; trailing ':' opens children
_LINE_RE = re.compile(r'^(\s*)- ([a-z]+)(?: "((?:[^"\\]|\\.)*)")?((?:\s*\[[^\]]*\])*)\s*:?\s*(.*)$')
_ATTR_RE = re.compile(r"\[([a-z]+)(?:=([^\]]*))?\]")
_TEXT_RE = re.compile(r'^\s*- (?:text: )?"?(.*?)"?\s*$')


@dataclass
class Node:
    ref:   str
    role:  str
    name:  str
    depth: int = 0
    nth:   int = 0                       # index among nodes with the same role + name
    attrs: dict[str, str] = field(default_factory=dict)   # level, checked, disabled, expanded…
    container: str = ""                  # nearest named landmark: "dialog:Confirm", "navigation:Main", "form:Search"

    def locator(self, page: Any):
        loc = page.get_by_role(self.role, name=self.name, exact=True) if self.name \
            else page.get_by_role(self.role)
        return loc.nth(self.nth)


@dataclass
class Field:
    label:       str
    type:        str                      # text, email, password, select, checkbox, radio, textarea, file…
    target:      str                      # what a flow step would use: label, placeholder or a selector
    name:        str = ""
    required:    bool = False
    disabled:    bool = False
    placeholder: str = ""
    minlength:   int | None = None
    maxlength:   int | None = None
    pattern:     str = ""
    options:     list[str] = field(default_factory=list)   # select options (visible text)
    value:       str = ""


@dataclass
class Form:
    name:    str
    fields:  list[Field]
    submits: list[str]                    # accessible names of submit buttons
    action:  str = ""
    method:  str = ""
    index:   int = 0                      # position among visible forms (for XPath fallbacks)


@dataclass
class Observation:
    url:      str = ""
    title:    str = ""
    viewport: dict | None = None
    nodes:    list[Node] = field(default_factory=list)      # headings + interactive, document order
    forms:    list[Form] = field(default_factory=list)
    dialogs:  int = 0
    tables:   int = 0
    nav:      int = 0
    text:     str = ""                                       # visible text summary
    text_hash: int = 0                                       # hash of all visible text (change detection)
    truncated: bool = False

    def by_role(self, *roles: str) -> list[Node]:
        return [n for n in self.nodes if n.role in roles]

    def fingerprint(self) -> tuple:
        """What "the same page state" means: URL without fragment, title, the
        first controls, open dialogs. Two observations with equal fingerprints
        are one node in an exploration graph."""
        url = self.url.split("#", 1)[0]
        controls = tuple((n.role, n.name) for n in self.nodes[:80])
        return (url, self.title, controls, self.dialogs, self.text_hash)

    @property
    def headings(self) -> list[Node]:
        return self.by_role("heading")

    @property
    def page_type(self) -> str:
        return classify(self)

    def to_prompt(self, max_chars: int = 3500) -> str:
        """Compact, LLM-safe rendering — refs, roles, names; no HTML."""
        lines = [f"url: {self.url}", f"title: {self.title}", f"type: {self.page_type}"]
        for n in self.nodes:
            attrs = " ".join(f"[{k}={v}]" if v else f"[{k}]" for k, v in n.attrs.items())
            where = f" in {n.container}" if n.container else ""
            lines.append(f"- {n.role} \"{n.name}\" [ref={n.ref}]{' ' + attrs if attrs else ''}{where}")
        for f in self.forms:
            lines.append(f"- form \"{f.name}\" submits={f.submits}:")
            for fld in f.fields:
                req = " required" if fld.required else ""
                lines.append(f"    - {fld.type} \"{fld.label}\"{req}")
        if self.text:
            lines.append(f"text: {self.text}")
        out = "\n".join(lines)
        return out if len(out) <= max_chars else out[:max_chars - 1] + "…"


# ── aria snapshot parsing ────────────────────────────────────────────────────

def parse_aria(snapshot: str) -> tuple[list[Node], dict[str, int], bool]:
    """YAML-ish aria lines → (nodes, role counts, truncated)."""
    nodes: list[Node] = []
    counts: Counter[str] = Counter()
    seen: Counter[tuple[str, str]] = Counter()
    containers: list[tuple[int, str]] = []      # (depth, "role:name") of open landmarks
    lines = snapshot.splitlines()
    truncated = len(lines) > MAX_LINES
    for line in lines[:MAX_LINES]:
        m = _LINE_RE.match(line)
        if not m:
            continue
        indent, role, name, attr_text, _rest = m.groups()
        depth = len(indent) // 2
        while containers and containers[-1][0] >= depth:
            containers.pop()
        counts[role] += 1
        name = (name or "").replace('\\"', '"')
        if role in CONTAINER_ROLES:
            containers.append((depth, f"{role}:{name}"))
        if role not in INTERACTIVE_ROLES and role != "heading":
            continue
        attrs = {k: (v or "") for k, v in _ATTR_RE.findall(attr_text or "")}
        key = (role, name)
        nodes.append(Node(ref=f"e{len(nodes) + 1}", role=role, name=name, depth=depth,
                          nth=seen[key], attrs=attrs,
                          container=containers[-1][1] if containers else ""))
        seen[key] += 1
    return nodes, dict(counts), truncated


# ── form metadata (one evaluate) ─────────────────────────────────────────────

_FORMS_JS = r"""
() => {
  const visible = el => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const labelText = lbl => {
    // the label's own words — not the text of a control nested inside it
    const clone = lbl.cloneNode(true);
    clone.querySelectorAll('input, select, textarea, button').forEach(n => n.remove());
    return (clone.textContent || '').replace(/\s+/g, ' ').trim();
  };
  const labelOf = el => {
    if (el.labels && el.labels.length) return labelText(el.labels[0]);
    const aria = el.getAttribute('aria-label'); if (aria) return aria.trim();
    const by = el.getAttribute('aria-labelledby');
    if (by) { const t = document.getElementById(by); if (t) return t.innerText.trim(); }
    return '';
  };
  const submitName = b => (b.innerText || b.value || b.getAttribute('aria-label') || '').trim();
  const forms = [...document.querySelectorAll('form')].filter(visible).slice(0, 10);
  return forms.map((form, index) => {
    const fields = [...form.querySelectorAll('input, select, textarea')]
      .filter(el => visible(el) && !['hidden', 'submit', 'button', 'reset', 'image'].includes(el.type))
      .slice(0, 40)
      .map(el => ({
        tag: el.tagName.toLowerCase(), type: el.tagName === 'SELECT' ? 'select' : (el.type || 'text'),
        name: el.name || '', id: el.id || '', label: labelOf(el), placeholder: el.placeholder || '',
        wrapped: !!(el.labels && el.labels[0] && el.labels[0].contains(el)),
        required: !!el.required, disabled: !!el.disabled, value: el.type === 'password' ? '' : (el.value || ''),
        minlength: el.minLength > 0 ? el.minLength : null, maxlength: el.maxLength > 0 ? el.maxLength : null,
        pattern: el.pattern || '',
        options: el.tagName === 'SELECT' ? [...el.options].map(o => o.text.trim()).slice(0, 20) : [],
      }));
    const submits = [...form.querySelectorAll('button, input[type=submit]')]
      .filter(b => visible(b) && (b.type === 'submit' || b.tagName === 'INPUT'))
      .map(submitName).filter(Boolean);
    const heading = form.querySelector('h1,h2,h3,legend');
    const name = (form.getAttribute('aria-label') || form.getAttribute('name') || form.id ||
                  (heading ? heading.innerText : '')).trim();
    return { index, name, action: form.getAttribute('action') || '', method: (form.method || '').toLowerCase(), fields, submits };
  });
}
"""

_TEXT_JS = """
() => {
  const text = (document.body && document.body.innerText || '').replace(/\\s+/g, ' ').trim();
  let h = 5381;                                   // djb2 over the whole visible text: cheap change detector
  for (let i = 0; i < text.length; i++) h = ((h << 5) + h + text.charCodeAt(i)) | 0;
  return { text: text.slice(0, %d), hash: h };
}
""" % MAX_TEXT


def _field_target(raw: dict) -> str:
    """What a `fill:` step needs to find the field through L1.

    Label text first — unless the label *wraps* the control: the accessible
    name then also carries the control's own content (a select's chosen
    option, a typed value), so an exact label match stops working after the
    first fill. Such fields get a selector instead.
    """
    if raw.get("label") and not raw.get("wrapped"):
        return raw["label"]
    if raw.get("placeholder"):
        return raw["placeholder"]
    if raw.get("id"):
        return f"#{raw['id']}"
    if raw.get("name"):
        return f"{raw['tag']}[name='{raw['name']}']"
    return raw.get("label") or raw["tag"]


def _build_forms(raw_forms: list[dict]) -> list[Form]:
    forms = []
    for rf in raw_forms:
        fields = [Field(
            label=f.get("label") or f.get("placeholder") or f.get("name") or f["tag"],
            type=f["type"] if f["tag"] != "textarea" else "textarea",
            target=_field_target(f), name=f.get("name", ""), required=bool(f.get("required")),
            disabled=bool(f.get("disabled")), placeholder=f.get("placeholder", ""),
            minlength=f.get("minlength"), maxlength=f.get("maxlength"), pattern=f.get("pattern", ""),
            options=f.get("options") or [], value=f.get("value", ""),
        ) for f in rf.get("fields", [])]
        forms.append(Form(name=rf.get("name") or f"form {rf['index'] + 1}", fields=fields,
                          submits=rf.get("submits") or [], action=rf.get("action", ""),
                          method=rf.get("method", ""), index=rf["index"]))
    return forms


# ── public API ───────────────────────────────────────────────────────────────

def observe(page: Any) -> Observation:
    """Snapshot the page. Each part is best-effort; a failure leaves it empty."""
    ob = Observation()
    try:
        ob.url, ob.title, ob.viewport = page.url, page.title(), page.viewport_size
    except Exception as exc:
        logger.debug("[observer] page state unavailable: %s", exc)
    try:
        ob.nodes, counts, ob.truncated = parse_aria(page.locator("body").aria_snapshot())
        ob.dialogs = counts.get("dialog", 0) + counts.get("alertdialog", 0)
        ob.tables = counts.get("table", 0)
        ob.nav = counts.get("navigation", 0)
    except Exception as exc:
        logger.debug("[observer] aria snapshot unavailable: %s", exc)
    try:
        ob.forms = _build_forms(page.evaluate(_FORMS_JS) or [])
    except Exception as exc:
        logger.debug("[observer] form metadata unavailable: %s", exc)
    try:
        summary = page.evaluate(_TEXT_JS) or {}
        ob.text, ob.text_hash = summary.get("text", ""), int(summary.get("hash", 0))
    except Exception as exc:
        logger.debug("[observer] text unavailable: %s", exc)
    return ob


PAGE_TYPES = ("LOGIN", "WIZARD", "SETTINGS", "FORM", "TABLE", "SEARCH", "DASHBOARD",
              "LIST", "DETAIL", "CONTENT", "UNKNOWN")
_WIZARD_RE = re.compile(r"\bstep \d+ (?:of|/) \d+\b", re.IGNORECASE)
_SETTINGS_RE = re.compile(r"settings|preferences|account|profile", re.IGNORECASE)


def classify(ob: Observation) -> str:
    """Deterministic page type from what the observation shows — one of
    ``PAGE_TYPES``. Signals only, in priority order; a planner may ask an
    LLM to break a tie when this says CONTENT or UNKNOWN (``ai_classify``).
    """
    field_types = [f.type for form in ob.forms for f in form.fields]
    buttons = {n.name.lower() for n in ob.by_role("button", "link")}
    links = len(ob.by_role("link"))
    toggles = len(ob.by_role("switch", "checkbox", "radio"))
    if "password" in field_types:
        return "LOGIN"
    if _WIZARD_RE.search(ob.text or "") and buttons & {"next", "continue", "back", "previous"}:
        return "WIZARD"
    if toggles >= 3 and _SETTINGS_RE.search(f"{ob.url} {ob.title}"):
        return "SETTINGS"
    if any(len(form.fields) >= 2 for form in ob.forms):
        return "FORM"
    if ob.tables:
        return "TABLE"
    if ob.by_role("searchbox") and (links >= 5 or ob.by_role("button")):
        return "SEARCH"
    if len(ob.headings) >= 4 and links >= 6:
        return "DASHBOARD"
    if links >= 10 and len(ob.headings) <= 3:
        return "LIST"
    if len(ob.headings) == 1 and links + len(ob.by_role("button")) <= 5 and ob.text:
        return "DETAIL"
    if ob.headings or ob.text:
        return "CONTENT"
    return "UNKNOWN"
