"""test_form — inspect a visible form and run the usual validation checks.

    - test_form                          first visible form with fields; never submits valid data
    - test_form: "form=Contact"          pick the form by name / heading / aria-label
    - test_form: "submit=true"           also submit the valid input and judge the outcome

What runs (each interaction is a ``fill`` / ``select`` / ``check`` / ``click``
probe step through the engine):

    1. inventory        fields, types, required flags, submit buttons
    2. empty submit     required fields present → press submit, expect rejection
    3. invalid email    an email field → fill garbage, expect rejection
    4. too short        a field with minlength → fill less, expect rejection
    5. valid input      fill every field with a plausible value, expect no client-side invalid state
    6. submit           only with submit=true: press submit, check requests and error messages

Rejected = the browser or the app flagged a field (``:invalid`` /
``aria-invalid``) or showed a message. The form staying on the page with no
such signal is a warning (cannot tell); the form going away means the input
was accepted — a failure. Steps 3 and 4 press submit only when that cannot
save anything: the browser flags the bad value itself, or step 2 already
showed validation; otherwise they are skipped. A field that cannot be filled
skips the check that needed it. The submit button passes the safety policy
with its form as context (an unnamed button is judged as "submit"), so a
destructive one — or any button of a "Delete account" form — is never
pressed. Not covered yet: cancel behaviour, keyboard navigation.
"""

from __future__ import annotations

import datetime
import logging
import time

from app.agent.observer import Field, Form, Observation
from app.schemas.actions import ActionType, Check
from app.skills.base import SkillContext, inconclusive, info, missing, skill, skipped

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


def _signal(state: dict) -> bool:
    """The browser or the app flagged the input: a field is :invalid /
    aria-invalid, or a validation message is shown."""
    return bool(state["native"] or state["aria"] or state["errors"])


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
            sc.run(ActionType.SELECT, f.target, options[0], kind="probe")
    elif f.type in ("checkbox", "radio"):
        sc.run(ActionType.CHECK, f.target, kind="probe")
    else:
        sc.run(ActionType.FILL, f.target, value, kind="probe")


def _fill_all(sc: SkillContext, fields: list[Field], *, skip: Field | None = None,
              only_required: bool = False) -> None:
    for f in fields:
        if f is skip or (only_required and not f.required):
            continue
        value = sample_value(f)
        if value is not None:
            _fill(sc, f, value)


def _not_filled(sc: SkillContext, mark: int) -> str:
    """Why the fields filled since *mark* are not usable, or ``""``."""
    if sc.stopped:                  # a limit refused a fill: nothing to judge
        return f"stopped early: {sc.stopped}"
    failed = sc.failures_since(mark)
    return ("could not fill " + ", ".join(s.action.args[0] for s in failed if s.action.args)) if failed else ""


def _submit_and_check(sc: SkillContext, form: Form, submit: str, name: str, mark: int) -> Check:
    """Press submit on input that must be rejected. Passed only on a
    validation signal; the form going away means the input was accepted."""
    if why := _not_filled(sc, mark):
        return skipped(name, why)
    url_before = sc.page.url
    sr = sc.run(ActionType.CLICK, submit, kind="probe")
    if sr.skipped:
        return skipped(name, sr.message)
    if not sr.success:
        return inconclusive(name, f"the agent could not press '{submit}'")
    state = _state(sc, form)
    if _signal(state):
        return Check(name, True, "error", _why(state))
    if state["present"] and state["url"] == url_before:
        return inconclusive(name, "no invalid field or message shown and the form stayed on the page: "
                                  "cannot tell whether the input was rejected")
    return Check(name, False, "error", _why(state) or f"the form was submitted, now at {state['url']}")


def _try_invalid(sc: SkillContext, form: Form, submit: str, name: str, field: Field,
                 bad: str, fields: list[Field], validated: bool) -> Check:
    """Fill *bad* into *field* (the rest valid) and submit — only when that
    cannot save anything: the browser flags the field itself (it will not
    submit), or the form already showed validation on an empty submission."""
    mark = len(sc.steps)
    _fill_all(sc, fields, skip=field, only_required=True)
    sc.run(ActionType.FILL, field.target, bad, kind="probe")
    if why := _not_filled(sc, mark):
        return skipped(name, why)
    if not validated and not _state(sc, form)["native"]:
        return skipped(name, "not submitted: the form showed no validation so far, and submitting "
                             "otherwise valid input could save it")
    return _submit_and_check(sc, form, submit, name, len(sc.steps))


@skill(ActionType.TEST_FORM)
def test_form(sc: SkillContext) -> list[Check]:
    ob = sc.observe()
    form = pick_form(ob, sc.option("form"))
    if form is None:
        return [missing(sc, "form found", "visible form with fields", "form")]
    fields = [f for f in form.fields if f.type not in SKIP_TYPES and not f.disabled]
    required = [f for f in fields if f.required]
    checks = [info("form", f"{form.name}: {len(form.fields)} fields, {len(required)} required; "
                           f"submit: {', '.join(form.submits) or 'none'}"),
              info("fields", ", ".join(f"{f.label} ({f.type}{', required' if f.required else ''})"
                                       for f in form.fields))]
    submit = submit_target(form)
    # An unnamed submit button is judged as a plain "submit" inside its form.
    verdict = sc.policy.verdict(form.submits[0] if form.submits else "submit", role="button",
                                container=f"form:{form.name}", url=ob.url)
    if not verdict.allowed:
        sc.block(form.submits[0] if form.submits else f"submit of '{form.name}'", verdict.reason)
        submit = None

    def gone() -> bool:
        return not _state(sc, form)["present"]

    # 2. empty submission — nothing is filled, so nothing can be saved
    validated = False
    if required and submit:
        check = _submit_and_check(sc, form, submit, "empty submission rejected", len(sc.steps))
        checks.append(check)
        validated = check.outcome == "passed"
        if gone():
            return checks

    # 3. invalid email / 4. minimum length
    email = next((f for f in fields if f.type == "email"), None)
    short = next((f for f in fields if f.minlength and f.type in TEXT_LIKE), None)
    for field, bad, name in ((email, "not-an-email", "invalid email rejected"),
                             (short, "a" * max((short.minlength if short else 1) - 1, 1),
                              f"value shorter than {short.minlength if short else 0} rejected")):
        if field is None or not submit or sc.stopped:
            continue
        checks.append(_try_invalid(sc, form, submit, name, field, bad, fields, validated))
        if gone():
            return checks

    # 5. valid input — judged by the browser's own constraints only: app-level
    # validation (aria-invalid, messages) is often left stale until the next submit.
    mark = len(sc.steps)
    _fill_all(sc, fields)
    if why := _not_filled(sc, mark):
        checks.append(skipped("valid input accepted", why) if sc.stopped
                      else inconclusive("valid input accepted", why))
        return checks
    state = _state(sc, form)
    checks.append(Check("valid input accepted", not state["native"], "error",
                        ("still invalid: " + ", ".join(state["native"])) if state["native"] else
                        f"{len(fields)} fields filled with sample values"))

    # 6. submission
    if not submit:
        checks.append(skipped("submission", "no submit button that is safe to press"))
    elif not sc.flag("submit", False):
        checks.append(skipped("submission", "not submitted — pass submit=true to submit the valid input"))
    else:
        since, url_before = sc.mark(), sc.page.url
        pressed = sc.run(ActionType.CLICK, submit, kind="probe")
        if not pressed.success:
            checks.append(skipped("submission accepted", pressed.message) if pressed.skipped
                          else inconclusive("submission accepted", f"the agent could not press '{submit}'"))
            return checks
        sc.run(ActionType.WAIT_LOAD, kind="probe")
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
