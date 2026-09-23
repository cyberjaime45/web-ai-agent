"""test_form — inspect a visible form and run the usual validation checks.

    - test_form                          first visible form with fields; never submits valid data
    - test_form: "form=Contact"          pick the form by name / heading / aria-label
    - test_form: "submit=true"           also submit the valid input and judge the outcome

What runs (each interaction is a ``fill`` / ``select`` / ``check`` / ``click``
child step through the engine):

    1. inventory        fields, types, required flags, submit buttons
    2. empty submit     required fields present → press submit, expect rejection
    3. invalid email    an email field → fill garbage, expect rejection
    4. too short        a field with minlength → fill less, expect rejection
    5. valid input      fill every field with a plausible value, expect no client-side invalid state
    6. submit           only with submit=true: press submit, check requests and error messages

Rejection = the browser or the app flagged a field (``:invalid`` /
``aria-invalid``), showed an error message, or kept the form on the same
URL. A submit button whose name looks destructive (pay, delete, send…) is
never pressed. Not covered yet: cancel behaviour, keyboard navigation.
"""

from __future__ import annotations

import datetime
import logging
import time

from app.agent.observer import Field, Form, Observation
from app.schemas.actions import ActionType, Check
from app.skills.base import SkillContext, info, skill

logger = logging.getLogger(__name__)

TEXT_LIKE = frozenset({"text", "email", "password", "search", "tel", "url", "textarea", "number"})
SKIP_TYPES = frozenset({"file", "hidden", "color", "range", "image"})

_STATE_JS = r"""
(index) => {
  const vis = el => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const form = [...document.querySelectorAll('form')].filter(vis)[index];
  if (!form) return { present: false, url: location.href, native: [], aria: [], errors: [], empty: 0, fields: 0 };
  const fields = [...form.querySelectorAll('input, select, textarea')].filter(vis);
  const nameOf = el => el.name || el.id || el.type;
  const native = fields.filter(el => el.matches(':invalid')).map(nameOf);            // browser constraints
  const aria = fields.filter(el => el.getAttribute('aria-invalid') === 'true').map(nameOf);   // app validation
  const sel = '[role=alert], .error, .invalid-feedback, .error-message, .validation-error, .field-error, [class*="error" i], [aria-live]';
  const errors = [...new Set([...form.querySelectorAll(sel), ...document.querySelectorAll('[role=alert]')]
    .filter(vis).map(e => (e.innerText || '').trim()).filter(Boolean))].slice(0, 5);
  const empty = fields.filter(el => el.type !== 'checkbox' && el.type !== 'radio' && !el.value).length;
  return { present: true, url: location.href, native: native.slice(0, 10), aria: aria.slice(0, 10),
           errors, empty, fields: fields.length };
}
"""


def sample_value(f: Field) -> str | None:
    """A plausible, clearly synthetic value for the field, or None to skip it."""
    t = f.type
    if t in SKIP_TYPES or f.disabled:
        return None
    if t == "email":
        return f"qa.webagent+{int(time.time()) % 100000}@example.com"
    if t == "tel":
        return "5551234567"
    if t == "number":
        return "1"
    if t == "url":
        return "https://example.com"
    if t == "date":
        return datetime.date.today().isoformat()
    if t == "time":
        return "10:30"
    if t == "password":
        return "Qa!Test12345"
    if t == "textarea":
        base = "Automated QA test input."
    elif t == "search":
        base = "test"
    else:
        base = "QA Test"
    if f.minlength and len(base) < f.minlength:
        base = (base + " ") * (f.minlength // len(base) + 1)
    if f.maxlength:
        base = base[:f.maxlength]
    return base.strip()


def pick_form(ob: Observation, wanted: str) -> Form | None:
    candidates = [f for f in ob.forms if f.fields]
    if wanted:
        w = wanted.lower()
        candidates = [f for f in candidates if w in f.name.lower()] or []
    return max(candidates, key=lambda f: len(f.fields), default=None)


def submit_target(form: Form) -> str | None:
    """Accessible name of the submit button, else an XPath into the form."""
    if form.submits:
        return form.submits[0]
    return f"(//form)[{form.index + 1}]//*[self::button or self::input][@type='submit']"


_GONE = {"present": False, "url": "", "native": [], "aria": [], "errors": [], "empty": 0, "fields": 0}


def _state(sc: SkillContext, form: Form) -> dict:
    return sc.evaluate(_STATE_JS, form.index) or dict(_GONE)


def _rejected(state: dict, url_before: str) -> bool:
    """The attempt did not go through: a field is flagged (browser or app),
    a message is shown, or the form is still there on the same URL."""
    return bool(state["native"] or state["aria"] or state["errors"]
                or (state["present"] and state["url"] == url_before))


def _why(state: dict) -> str:
    bits = []
    flagged = list(dict.fromkeys(state["native"] + state["aria"]))
    if flagged:
        bits.append("invalid: " + ", ".join(flagged))
    if state["errors"]:
        bits.append("messages: " + " / ".join(state["errors"]))
    if not state["present"]:
        bits.append("form is gone (submitted?)")
    return "; ".join(bits)


def _fill(sc: SkillContext, f: Field, value: str) -> None:
    if f.type == "select":
        options = [o for o in f.options if o and not o.lower().startswith(("select", "choose", "--"))]
        if options:
            sc.run(ActionType.SELECT, f.target, options[0])
    elif f.type in ("checkbox", "radio"):
        sc.run(ActionType.CHECK, f.target)
    else:
        sc.run(ActionType.FILL, f.target, value)


def _fill_all(sc: SkillContext, fields: list[Field], *, skip: Field | None = None,
              only_required: bool = False) -> None:
    for f in fields:
        if f is skip or (only_required and not f.required):
            continue
        value = sample_value(f)
        if value is not None:
            _fill(sc, f, value)


def _submit_and_check(sc: SkillContext, form: Form, submit: str, name: str) -> Check:
    url_before = sc.page.url
    sc.run(ActionType.CLICK, submit)
    state = _state(sc, form)
    return Check(name, _rejected(state, url_before), "error", _why(state) or "no validation state found")


@skill(ActionType.TEST_FORM)
def test_form(sc: SkillContext) -> list[Check]:
    ob = sc.observe()
    form = pick_form(ob, sc.option("form"))
    if form is None:
        return [Check("form found", False, "error",
                      f"no visible form with fields on {ob.url}" + (f" matching '{sc.option('form')}'" if sc.option("form") else ""))]
    fields = [f for f in form.fields if f.type not in SKIP_TYPES and not f.disabled]
    required = [f for f in fields if f.required]
    checks = [info("form", f"{form.name}: {len(form.fields)} fields, {len(required)} required; "
                           f"submit: {', '.join(form.submits) or 'none'}"),
              info("fields", ", ".join(f"{f.label} ({f.type}{', required' if f.required else ''})"
                                       for f in form.fields))]
    submit = submit_target(form)
    verdict = sc.policy.verdict(submit, role="button", container=f"form:{form.name}", url=ob.url) \
        if submit and form.submits else None
    if verdict is not None and not verdict.allowed:
        checks.append(Check("submit button safe to press", False, "warn",
                            f"'{submit}' not pressed — {verdict.reason}; submission checks skipped"))
        submit = None

    # 2. empty submission
    if required and submit:
        checks.append(_submit_and_check(sc, form, submit, "empty submission rejected"))
        if not _state(sc, form)["present"] or sc.child_failed:
            return checks

    # 3. invalid email
    email = next((f for f in fields if f.type == "email"), None)
    if email and submit:
        _fill_all(sc, fields, skip=email, only_required=True)
        sc.run(ActionType.FILL, email.target, "not-an-email")
        checks.append(_submit_and_check(sc, form, submit, "invalid email rejected"))
        if not _state(sc, form)["present"] or sc.child_failed:
            return checks

    # 4. minimum length
    short = next((f for f in fields if f.minlength and f.type in TEXT_LIKE), None)
    if short and submit:
        _fill_all(sc, fields, skip=short, only_required=True)
        sc.run(ActionType.FILL, short.target, "a" * max(short.minlength - 1, 1))
        checks.append(_submit_and_check(sc, form, submit, f"value shorter than {short.minlength} rejected"))
        if not _state(sc, form)["present"] or sc.child_failed:
            return checks

    # 5. valid input — judged by the browser's own constraints only: app-level
    # validation (aria-invalid, messages) is often left stale until the next submit.
    _fill_all(sc, fields)
    if sc.child_failed:
        return checks
    state = _state(sc, form)
    checks.append(Check("valid input accepted", not state["native"], "error",
                        ("still invalid: " + ", ".join(state["native"])) if state["native"] else
                        f"{len(fields)} fields filled with sample values"))

    # 6. submission
    if not submit:
        checks.append(info("submission", "no submit button to press"))
    elif not sc.flag("submit", False):
        checks.append(info("submission", "skipped — pass submit=true to submit the valid input"))
    else:
        since, url_before = sc.mark(), sc.page.url
        sc.run(ActionType.CLICK, submit)
        sc.run(ActionType.WAIT_LOAD)
        after = _state(sc, form)
        # After a successful submit the form is gone, reset (empty required fields
        # are natively :invalid again) or left as is — so only the app's own
        # signals count here: aria-invalid and visible messages.
        accepted = not after["aria"] and not after["errors"]
        if not after["present"]:
            outcome = f"form is gone, now at {after['url']}"
        elif after["url"] != url_before:
            outcome = f"now at {after['url']}"
        elif after["empty"] == after["fields"] and after["fields"]:
            outcome = "form was reset"
        else:
            outcome = "same URL, no errors shown"
        checks.append(Check("submission accepted", accepted, "error", _why(after) if not accepted else outcome))
        checks += [c for c in sc.diagnostics(since) if c.name in ("no failed requests", "no page errors")]
    return checks
