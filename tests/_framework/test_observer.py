"""Observer: aria snapshot parsing, refs, form metadata, classification."""

from __future__ import annotations

from app.agent.observer import Field, Form, Observation, _build_forms, classify, parse_aria

SNAPSHOT = """\
- navigation:
  - link "Home"
  - link "Members"
- heading "Members" [level=1]
- button "Add Member"
- button "Export" [disabled]
- form "Search form":
  - text: Search
  - searchbox "Search"
  - combobox:
    - option "One" [selected]
    - option "Two"
  - checkbox "Active only"
  - textbox
  - button "Go"
- table:
  - rowgroup:
    - row "John \\"J\\" Smith Edit":
      - cell "John \\"J\\" Smith"
      - cell "Edit":
        - button "Edit"
- button "Add Member"
- dialog "Confirm":
  - button "OK"
"""


def test_parse_aria_keeps_interactive_and_headings_with_refs():
    nodes, counts, truncated = parse_aria(SNAPSHOT)
    assert not truncated
    assert [n.ref for n in nodes] == [f"e{i}" for i in range(1, len(nodes) + 1)]
    roles = [(n.role, n.name) for n in nodes]
    assert ("heading", "Members") in roles
    assert ("option", "One") not in roles            # options ride on the combobox
    assert ("cell", 'John "J" Smith') not in roles   # structural roles are not targets
    assert counts["table"] == 1 and counts["dialog"] == 1 and counts["navigation"] == 1


def test_duplicate_names_get_nth_for_locators():
    nodes, _, _ = parse_aria(SNAPSHOT)
    adds = [n for n in nodes if n.name == "Add Member"]
    assert [n.nth for n in adds] == [0, 1]
    assert [n.attrs for n in nodes if n.name == "Export"] == [{"disabled": ""}]
    assert [n.attrs for n in nodes if n.role == "heading"] == [{"level": "1"}]


def test_forms_from_evaluate_payload():
    forms = _build_forms([{
        "index": 0, "name": "Add member", "action": "/save", "method": "post",
        "submits": ["Save member"],
        "fields": [
            {"tag": "input", "type": "text", "name": "name", "id": "", "label": "Full name",
             "placeholder": "", "required": True, "disabled": False, "value": "",
             "minlength": 3, "maxlength": None, "pattern": "", "options": []},
            {"tag": "input", "type": "email", "name": "email", "id": "em", "label": "",
             "placeholder": "you@example.com", "required": True, "disabled": False, "value": "",
             "minlength": None, "maxlength": None, "pattern": "", "options": []},
            {"tag": "select", "type": "select", "name": "role", "id": "", "label": "",
             "placeholder": "", "required": False, "disabled": False, "value": "",
             "minlength": None, "maxlength": None, "pattern": "", "options": ["Select…", "Viewer"]},
        ],
    }])
    (form,) = forms
    assert form.name == "Add member" and form.submits == ["Save member"]
    assert [f.target for f in form.fields] == ["Full name", "you@example.com", "select[name='role']"]
    # a label that wraps its control gives a composite accessible name → selector target
    wrapped = _build_forms([{"index": 0, "name": "", "fields": [
        {"tag": "select", "type": "select", "name": "role", "id": "", "label": "Role",
         "wrapped": True, "placeholder": "", "required": False, "disabled": False, "value": "",
         "minlength": None, "maxlength": None, "pattern": "", "options": []}], "submits": []}])
    assert wrapped[0].fields[0].target == "select[name='role']" and wrapped[0].fields[0].label == "Role"
    assert form.fields[0].minlength == 3 and form.fields[0].required
    assert form.fields[2].options == ["Select…", "Viewer"]


def _ob(**kw) -> Observation:
    ob = Observation()
    for k, v in kw.items():
        setattr(ob, k, v)
    return ob


def test_classify_uses_forms_tables_and_links():
    pw = Form("login", [Field("Email", "email", "Email"), Field("Password", "password", "Password")], ["Sign in"])
    assert classify(_ob(forms=[pw])) == "LOGIN"
    contact = Form("c", [Field("Name", "text", "Name"), Field("Msg", "textarea", "Msg")], ["Send"])
    assert classify(_ob(forms=[contact])) == "FORM"
    assert classify(_ob(tables=2)) == "TABLE"
    nodes, _, _ = parse_aria("\n".join(f'- link "L{i}"' for i in range(12)))
    assert classify(_ob(nodes=nodes)) == "LIST"
    assert classify(_ob(text="hello")) == "CONTENT"
    assert classify(_ob()) == "UNKNOWN"


def test_prompt_is_compact_and_bounded():
    nodes, _, _ = parse_aria(SNAPSHOT)
    ob = _ob(url="https://x.test/members", title="Members", nodes=nodes, text="Members " * 50)
    text = ob.to_prompt(max_chars=200)
    assert text.startswith("url: https://x.test/members\ntitle: Members\ntype: ")
    assert len(text) <= 200 and text.endswith("…")
    assert "<" not in text                       # never HTML


def test_classify_refined_types():
    nodes, _, _ = parse_aria("\n".join(['- button "Next"', '- button "Back"']))
    assert classify(_ob(nodes=nodes, text="Step 2 of 4: your details")) == "WIZARD"
    nodes, _, _ = parse_aria("\n".join(f'- switch "Option {i}"' for i in range(3)))
    assert classify(_ob(nodes=nodes, url="https://x.test/settings", title="Settings")) == "SETTINGS"
    assert classify(_ob(nodes=nodes, url="https://x.test/home", title="Home", text="x")) == "CONTENT"
    nodes, _, _ = parse_aria('- searchbox "Search"\n' + "\n".join(f'- link "R{i}"' for i in range(5)))
    assert classify(_ob(nodes=nodes)) == "SEARCH"
    nodes, _, _ = parse_aria("\n".join(f'- heading "Card {i}" [level=2]' for i in range(4))
                             + "\n" + "\n".join(f'- link "L{i}"' for i in range(6)))
    assert classify(_ob(nodes=nodes)) == "DASHBOARD"
    nodes, _, _ = parse_aria('- heading "John Smith" [level=1]\n- link "Back"')
    assert classify(_ob(nodes=nodes, text="Member since 2020")) == "DETAIL"


def test_containers_give_controls_their_context():
    nodes, _, _ = parse_aria(SNAPSHOT)
    by_name = {n.name: n for n in nodes}
    assert by_name["Home"].container == "navigation:"
    assert by_name["Go"].container == "form:Search form"
    assert by_name["OK"].container == "dialog:Confirm"
    assert by_name["Export"].container == ""
    assert 'button "OK" [ref=' in _ob(nodes=nodes).to_prompt() and "in dialog:Confirm" in _ob(nodes=nodes).to_prompt()
