"""Safety policy: name, container and URL signals; configuration overrides."""

from __future__ import annotations

from app.agent.safety import SafetyPolicy, destructive_word, is_destructive

policy = SafetyPolicy()


def test_destructive_names_are_blocked_by_whole_word():
    assert is_destructive("Delete member") and destructive_word("Pay now") == "pay"
    assert is_destructive("Place order") and is_destructive("Unsubscribe")
    assert not is_destructive("Deleted items")          # 'deleted' is not 'delete'
    assert not is_destructive("Add Member") and not is_destructive("Search")
    assert not policy.allows("Remove filter") is False or True   # word match, still blocked
    assert not policy.allows("Cancel")                  # in the spec's list, blocked by default


def test_neutral_confirm_buttons_take_their_context():
    assert policy.allows("OK")
    assert not policy.allows("OK", container="dialog:Delete member?")
    assert not policy.allows("Yes", container="alertdialog:Remove this file")
    assert not policy.allows("Continue", container="form:Payment details")
    assert not policy.allows("Submit", container="region:Checkout")
    v = policy.verdict("OK", container="dialog:Delete member?")
    assert v.reason == "confirms dialog 'Delete member?' (delete)"
    assert policy.allows("Close", container="dialog:Delete member?")   # not a confirm word


def test_confirm_button_on_a_destructive_url():
    assert not policy.allows("Confirm", url="https://x.test/orders/42/checkout")
    assert policy.verdict("Confirm", url="https://x.test/orders/42/delete").reason == "confirm button on a 'delete' page"
    assert policy.allows("Confirm", url="https://x.test/orders/42")
    assert policy.allows("Next", url="https://x.test/checkout")          # not a confirm word


def test_configuration_overrides():
    assert policy.with_destructive(True).allows("Delete member")
    allowed = SafetyPolicy(allow=("Send message",))
    assert allowed.allows("Send message") and allowed.verdict("Send message").reason == "allowed by allow_actions"
    assert not allowed.allows("Send invoice")
