# Multi-Provider LLM Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hard-coded OpenAI integration in Layer 3 with a configurable provider abstraction supporting OpenAI, Google Gemini, and Anthropic Claude, selected via `AI_PROVIDER` / `LLM_KEY` / `LLM_MODEL` env vars.

**Architecture:** Introduce `app/layers/providers/` with an `LLMProvider` ABC and three thin SDK adapters (`OpenAIProvider`, `GeminiProvider`, `ClaudeProvider`). A `get_provider()` factory reads settings and returns the configured provider, or `None` when L3 is disabled. `AIResolver` is refactored to consume the provider interface; no other layers change.

**Tech Stack:** Python 3.11+, pytest, Playwright, OpenAI SDK, `google-generativeai`, `anthropic`.

**Spec:** `docs/superpowers/specs/2026-04-18-multi-provider-llm-design.md`

---

## File Structure

| File | Responsibility |
|------|---------------|
| `app/layers/providers/__init__.py` | `ConfigError` + `get_provider()` factory |
| `app/layers/providers/base.py` | `LLMProvider` ABC — single `complete(system, user, *, temperature, max_tokens) -> str` method |
| `app/layers/providers/openai_provider.py` | `OpenAIProvider` — adapts OpenAI SDK (`chat.completions.create`) |
| `app/layers/providers/gemini_provider.py` | `GeminiProvider` — adapts `google-generativeai` (`GenerativeModel.generate_content`) |
| `app/layers/providers/anthropic_provider.py` | `ClaudeProvider` — adapts `anthropic` SDK (`messages.create`) |
| `app/config/settings.py` | Replaces `openai_*` fields with `ai_provider`, `llm_key`, `llm_model` |
| `app/layers/ai_resolver.py` | Refactored to consume `LLMProvider` instead of calling OpenAI directly |
| `app/execution/engine.py` | Generic error/log wording (drop "OPENAI_API_KEY" references) |
| `tests/__init__.py` | Empty marker (enables test discovery) |
| `tests/unit/__init__.py` | Empty marker |
| `tests/unit/providers/__init__.py` | Empty marker |
| `tests/unit/providers/test_factory.py` | Factory + `ConfigError` behavior |
| `tests/unit/providers/test_openai_provider.py` | `OpenAIProvider.complete()` with mocked SDK |
| `tests/unit/providers/test_gemini_provider.py` | `GeminiProvider.complete()` with mocked SDK |
| `tests/unit/providers/test_anthropic_provider.py` | `ClaudeProvider.complete()` with mocked SDK |
| `tests/unit/test_ai_resolver.py` | `AIResolver` with a fake `LLMProvider` |
| `requirements.txt` | Add `google-generativeai`, `anthropic` |
| `pytest.ini` | Add `tests` to `testpaths` so unit tests run |
| `.env.example`, `.env` | Swap OpenAI vars for new vars |

---

## Task 1: Update pytest config to include unit tests

**Files:**
- Modify: `pytest.ini`
- Create: `tests/__init__.py`
- Create: `tests/unit/__init__.py`
- Create: `tests/unit/providers/__init__.py`

Why first: later tasks write unit tests under `tests/`. Today `pytest.ini` only discovers `flows/`, so tests would silently be skipped. Also avoids touching flow discovery semantics.

- [ ] **Step 1: Extend `testpaths`**

Modify `pytest.ini` so the `testpaths` line reads:

```ini
testpaths = flows tests
```

Leave all other lines unchanged.

- [ ] **Step 2: Create empty package markers**

Create the three `__init__.py` files as empty files:

- `tests/__init__.py`
- `tests/unit/__init__.py`
- `tests/unit/providers/__init__.py`

- [ ] **Step 3: Verify unit-test discovery still works**

Run:

```bash
pytest tests/ --collect-only -q
```

Expected: exits cleanly with `no tests ran` (we haven't added any yet). The important signal is no errors about missing directory.

- [ ] **Step 4: Verify flow discovery is unaffected**

Run:

```bash
pytest --collect-only -q flows/ | head -20
```

Expected: a list of flow tests (same as before). If the list is empty or errors, stop and investigate — do not proceed.

- [ ] **Step 5: Commit**

```bash
git add pytest.ini tests/__init__.py tests/unit/__init__.py tests/unit/providers/__init__.py
git commit -m "test: enable unit-test discovery alongside flow tests"
```

---

## Task 2: Update dependencies

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Add the two new SDKs**

Append to `requirements.txt` (after the existing `openai==1.58.1` line, keeping file order otherwise intact):

```
google-generativeai==0.8.3
anthropic==0.40.0
```

- [ ] **Step 2: Install**

Run:

```bash
pip install -r requirements.txt
```

Expected: installs `google-generativeai` and `anthropic` (plus transitive deps). No errors.

- [ ] **Step 3: Verify imports work**

Run:

```bash
python -c "import openai, google.generativeai, anthropic; print('ok')"
```

Expected: prints `ok`.

- [ ] **Step 4: Commit**

```bash
git add requirements.txt
git commit -m "deps: add google-generativeai and anthropic SDKs"
```

---

## Task 3: Replace OpenAI-specific settings fields

**Files:**
- Modify: `app/config/settings.py` (lines 49–51 today)

- [ ] **Step 1: Swap the AI block**

Replace this block in `app/config/settings.py`:

```python
    # ── AI ────────────────────────────────────────────────────────
    openai_api_key:    str  = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
    openai_model:      str  = field(default_factory=lambda: os.getenv("OPENAI_MODEL", "gpt-4o-mini"))
```

With:

```python
    # ── AI ────────────────────────────────────────────────────────
    ai_provider:       str  = field(default_factory=lambda: os.getenv("AI_PROVIDER", ""))
    llm_key:           str  = field(default_factory=lambda: os.getenv("LLM_KEY", ""))
    llm_model:         str  = field(default_factory=lambda: os.getenv("LLM_MODEL", ""))
```

Note: no defaults for `llm_model` — fail-fast at the factory layer, per spec.

- [ ] **Step 2: Verify settings import still works**

Run:

```bash
python -c "from app.config.settings import settings; print(settings.ai_provider, settings.llm_key == '', settings.llm_model == '')"
```

Expected: prints three values; no exceptions.

- [ ] **Step 3: Commit**

```bash
git add app/config/settings.py
git commit -m "config: replace OPENAI_* with AI_PROVIDER/LLM_KEY/LLM_MODEL"
```

---

## Task 4: LLMProvider base class + ConfigError

**Files:**
- Create: `app/layers/providers/__init__.py`
- Create: `app/layers/providers/base.py`
- Test: `tests/unit/providers/test_factory.py` (just the `ConfigError` + import test for now)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/providers/test_factory.py` with:

```python
"""Tests for the LLM provider factory and ConfigError."""

from __future__ import annotations

import pytest


def test_config_error_is_exception():
    from app.layers.providers import ConfigError
    assert issubclass(ConfigError, Exception)


def test_llm_provider_is_abstract():
    from app.layers.providers.base import LLMProvider
    with pytest.raises(TypeError):
        LLMProvider()  # type: ignore[abstract]
```

- [ ] **Step 2: Run test — expect failure**

Run:

```bash
pytest tests/unit/providers/test_factory.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.layers.providers'`.

- [ ] **Step 3: Create the base module**

Create `app/layers/providers/base.py`:

```python
"""Base interface for LLM providers consumed by Layer 3 (AIResolver)."""

from __future__ import annotations

from abc import ABC, abstractmethod


class LLMProvider(ABC):
    """Minimal single-turn completion interface.

    Providers translate a (system, user) prompt pair into their vendor
    SDK's call shape and return the raw text response. They do not log,
    parse JSON, or know anything about Playwright or flow actions.
    """

    @abstractmethod
    def complete(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.0,
        max_tokens: int = 500,
    ) -> str:
        """Return the model's text response to the system+user prompt."""
        raise NotImplementedError
```

- [ ] **Step 4: Create the package init with ConfigError**

Create `app/layers/providers/__init__.py`:

```python
"""LLM provider abstraction for Layer 3 (AIResolver)."""

from __future__ import annotations

from app.layers.providers.base import LLMProvider


class ConfigError(Exception):
    """Raised when AI provider configuration is invalid or incomplete."""


__all__ = ["LLMProvider", "ConfigError"]
```

- [ ] **Step 5: Run test — expect pass**

Run:

```bash
pytest tests/unit/providers/test_factory.py -v
```

Expected: both tests pass.

- [ ] **Step 6: Commit**

```bash
git add app/layers/providers/__init__.py app/layers/providers/base.py tests/unit/providers/test_factory.py
git commit -m "feat: add LLMProvider base class and ConfigError"
```

---

## Task 5: OpenAIProvider

**Files:**
- Create: `app/layers/providers/openai_provider.py`
- Test: `tests/unit/providers/test_openai_provider.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/providers/test_openai_provider.py`:

```python
"""Unit tests for OpenAIProvider."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch


def _mock_response(text: str):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text))]
    )


def test_complete_maps_system_and_user_to_messages():
    from app.layers.providers.openai_provider import OpenAIProvider

    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = _mock_response("hi")

    with patch(
        "app.layers.providers.openai_provider.OpenAI",
        return_value=fake_client,
    ):
        provider = OpenAIProvider(api_key="k", model="gpt-4o-mini")
        out = provider.complete("SYS", "USR", temperature=0.0, max_tokens=123)

    assert out == "hi"
    fake_client.chat.completions.create.assert_called_once_with(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "SYS"},
            {"role": "user", "content": "USR"},
        ],
        temperature=0.0,
        max_tokens=123,
    )


def test_complete_returns_empty_string_when_content_is_none():
    from app.layers.providers.openai_provider import OpenAIProvider

    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = _mock_response(None)

    with patch(
        "app.layers.providers.openai_provider.OpenAI",
        return_value=fake_client,
    ):
        provider = OpenAIProvider(api_key="k", model="gpt-4o-mini")
        assert provider.complete("s", "u") == ""
```

- [ ] **Step 2: Run test — expect failure**

Run:

```bash
pytest tests/unit/providers/test_openai_provider.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.layers.providers.openai_provider'`.

- [ ] **Step 3: Implement OpenAIProvider**

Create `app/layers/providers/openai_provider.py`:

```python
"""OpenAI SDK adapter for LLMProvider."""

from __future__ import annotations

from openai import OpenAI

from app.layers.providers.base import LLMProvider


class OpenAIProvider(LLMProvider):
    def __init__(self, api_key: str, model: str) -> None:
        self._model = model
        self._client = OpenAI(api_key=api_key)

    def complete(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.0,
        max_tokens: int = 500,
    ) -> str:
        resp = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return (resp.choices[0].message.content or "").strip() if False else (resp.choices[0].message.content or "")
```

Note: the second `if False` is confusing — use the simpler form:

```python
        return resp.choices[0].message.content or ""
```

Final file content:

```python
"""OpenAI SDK adapter for LLMProvider."""

from __future__ import annotations

from openai import OpenAI

from app.layers.providers.base import LLMProvider


class OpenAIProvider(LLMProvider):
    def __init__(self, api_key: str, model: str) -> None:
        self._model = model
        self._client = OpenAI(api_key=api_key)

    def complete(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.0,
        max_tokens: int = 500,
    ) -> str:
        resp = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return resp.choices[0].message.content or ""
```

- [ ] **Step 4: Run test — expect pass**

Run:

```bash
pytest tests/unit/providers/test_openai_provider.py -v
```

Expected: both tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/layers/providers/openai_provider.py tests/unit/providers/test_openai_provider.py
git commit -m "feat: add OpenAIProvider adapter"
```

---

## Task 6: GeminiProvider

**Files:**
- Create: `app/layers/providers/gemini_provider.py`
- Test: `tests/unit/providers/test_gemini_provider.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/providers/test_gemini_provider.py`:

```python
"""Unit tests for GeminiProvider."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch


def test_complete_configures_api_key_and_system_instruction():
    from app.layers.providers import gemini_provider

    fake_model = MagicMock()
    fake_model.generate_content.return_value = SimpleNamespace(text="hello")

    with patch.object(gemini_provider.genai, "configure") as mock_cfg, \
         patch.object(
             gemini_provider.genai, "GenerativeModel", return_value=fake_model
         ) as mock_ctor:
        provider = gemini_provider.GeminiProvider(api_key="k", model="gemini-1.5-flash")
        out = provider.complete("SYS", "USR", temperature=0.1, max_tokens=222)

    assert out == "hello"
    mock_cfg.assert_called_once_with(api_key="k")
    mock_ctor.assert_called_once_with(
        model_name="gemini-1.5-flash",
        system_instruction="SYS",
    )
    fake_model.generate_content.assert_called_once()
    args, kwargs = fake_model.generate_content.call_args
    assert args[0] == "USR"
    gen_cfg = kwargs["generation_config"]
    assert gen_cfg["temperature"] == 0.1
    assert gen_cfg["max_output_tokens"] == 222


def test_complete_returns_empty_string_when_text_missing():
    from app.layers.providers import gemini_provider

    fake_model = MagicMock()
    fake_model.generate_content.return_value = SimpleNamespace(text=None)

    with patch.object(gemini_provider.genai, "configure"), \
         patch.object(gemini_provider.genai, "GenerativeModel", return_value=fake_model):
        provider = gemini_provider.GeminiProvider(api_key="k", model="gemini-1.5-flash")
        assert provider.complete("s", "u") == ""
```

- [ ] **Step 2: Run test — expect failure**

Run:

```bash
pytest tests/unit/providers/test_gemini_provider.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.layers.providers.gemini_provider'`.

- [ ] **Step 3: Implement GeminiProvider**

Create `app/layers/providers/gemini_provider.py`:

```python
"""Google Gemini SDK adapter for LLMProvider."""

from __future__ import annotations

import google.generativeai as genai

from app.layers.providers.base import LLMProvider


class GeminiProvider(LLMProvider):
    def __init__(self, api_key: str, model: str) -> None:
        genai.configure(api_key=api_key)
        self._model_name = model

    def complete(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.0,
        max_tokens: int = 500,
    ) -> str:
        model = genai.GenerativeModel(
            model_name=self._model_name,
            system_instruction=system,
        )
        resp = model.generate_content(
            user,
            generation_config={
                "temperature": temperature,
                "max_output_tokens": max_tokens,
            },
        )
        return resp.text or ""
```

- [ ] **Step 4: Run test — expect pass**

Run:

```bash
pytest tests/unit/providers/test_gemini_provider.py -v
```

Expected: both tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/layers/providers/gemini_provider.py tests/unit/providers/test_gemini_provider.py
git commit -m "feat: add GeminiProvider adapter"
```

---

## Task 7: ClaudeProvider (Anthropic)

**Files:**
- Create: `app/layers/providers/anthropic_provider.py`
- Test: `tests/unit/providers/test_anthropic_provider.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/providers/test_anthropic_provider.py`:

```python
"""Unit tests for ClaudeProvider."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch


def _mock_response(text: str):
    return SimpleNamespace(content=[SimpleNamespace(text=text)])


def test_complete_uses_system_param_and_user_message():
    from app.layers.providers.anthropic_provider import ClaudeProvider

    fake_client = MagicMock()
    fake_client.messages.create.return_value = _mock_response("hi")

    with patch(
        "app.layers.providers.anthropic_provider.Anthropic",
        return_value=fake_client,
    ):
        provider = ClaudeProvider(api_key="k", model="claude-haiku-4-5-20251001")
        out = provider.complete("SYS", "USR", temperature=0.2, max_tokens=321)

    assert out == "hi"
    fake_client.messages.create.assert_called_once_with(
        model="claude-haiku-4-5-20251001",
        system="SYS",
        messages=[{"role": "user", "content": "USR"}],
        temperature=0.2,
        max_tokens=321,
    )


def test_complete_returns_empty_string_when_no_content():
    from app.layers.providers.anthropic_provider import ClaudeProvider

    fake_client = MagicMock()
    fake_client.messages.create.return_value = SimpleNamespace(content=[])

    with patch(
        "app.layers.providers.anthropic_provider.Anthropic",
        return_value=fake_client,
    ):
        provider = ClaudeProvider(api_key="k", model="claude-haiku-4-5-20251001")
        assert provider.complete("s", "u") == ""
```

- [ ] **Step 2: Run test — expect failure**

Run:

```bash
pytest tests/unit/providers/test_anthropic_provider.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.layers.providers.anthropic_provider'`.

- [ ] **Step 3: Implement ClaudeProvider**

Create `app/layers/providers/anthropic_provider.py`:

```python
"""Anthropic Claude SDK adapter for LLMProvider."""

from __future__ import annotations

from anthropic import Anthropic

from app.layers.providers.base import LLMProvider


class ClaudeProvider(LLMProvider):
    def __init__(self, api_key: str, model: str) -> None:
        self._model = model
        self._client = Anthropic(api_key=api_key)

    def complete(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.0,
        max_tokens: int = 500,
    ) -> str:
        resp = self._client.messages.create(
            model=self._model,
            system=system,
            messages=[{"role": "user", "content": user}],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if not resp.content:
            return ""
        return resp.content[0].text or ""
```

- [ ] **Step 4: Run test — expect pass**

Run:

```bash
pytest tests/unit/providers/test_anthropic_provider.py -v
```

Expected: both tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/layers/providers/anthropic_provider.py tests/unit/providers/test_anthropic_provider.py
git commit -m "feat: add ClaudeProvider adapter"
```

---

## Task 8: `get_provider()` factory

**Files:**
- Modify: `app/layers/providers/__init__.py`
- Modify: `tests/unit/providers/test_factory.py`

- [ ] **Step 1: Extend the failing test**

Append to `tests/unit/providers/test_factory.py`:

```python
from unittest.mock import patch


def _stub_settings(provider="", key="", model=""):
    """Return a fresh settings-like object; patch app.layers.providers.settings."""
    from types import SimpleNamespace
    return SimpleNamespace(ai_provider=provider, llm_key=key, llm_model=model)


def test_factory_returns_none_when_all_unset():
    from app.layers.providers import get_provider
    with patch("app.layers.providers.settings", _stub_settings()):
        assert get_provider() is None


def test_factory_raises_on_missing_key():
    from app.layers.providers import ConfigError, get_provider
    with patch(
        "app.layers.providers.settings",
        _stub_settings(provider="openai", model="gpt-4o-mini"),
    ):
        with pytest.raises(ConfigError, match="LLM_KEY"):
            get_provider()


def test_factory_raises_on_missing_model():
    from app.layers.providers import ConfigError, get_provider
    with patch(
        "app.layers.providers.settings",
        _stub_settings(provider="openai", key="k"),
    ):
        with pytest.raises(ConfigError, match="LLM_MODEL"):
            get_provider()


def test_factory_raises_on_missing_provider():
    from app.layers.providers import ConfigError, get_provider
    with patch(
        "app.layers.providers.settings",
        _stub_settings(key="k", model="m"),
    ):
        with pytest.raises(ConfigError, match="AI_PROVIDER"):
            get_provider()


def test_factory_raises_on_invalid_provider_name():
    from app.layers.providers import ConfigError, get_provider
    with patch(
        "app.layers.providers.settings",
        _stub_settings(provider="cohere", key="k", model="m"),
    ):
        with pytest.raises(ConfigError, match="Invalid AI_PROVIDER"):
            get_provider()


def test_factory_returns_openai_provider():
    from app.layers.providers import get_provider
    from app.layers.providers.openai_provider import OpenAIProvider
    with patch("app.layers.providers.settings",
               _stub_settings(provider="openai", key="k", model="gpt-4o-mini")), \
         patch("app.layers.providers.openai_provider.OpenAI"):
        p = get_provider()
    assert isinstance(p, OpenAIProvider)


def test_factory_returns_gemini_provider():
    from app.layers.providers import get_provider
    from app.layers.providers.gemini_provider import GeminiProvider
    with patch("app.layers.providers.settings",
               _stub_settings(provider="gemini", key="k", model="gemini-1.5-flash")), \
         patch("app.layers.providers.gemini_provider.genai.configure"):
        p = get_provider()
    assert isinstance(p, GeminiProvider)


def test_factory_returns_claude_provider():
    from app.layers.providers import get_provider
    from app.layers.providers.anthropic_provider import ClaudeProvider
    with patch(
        "app.layers.providers.settings",
        _stub_settings(provider="anthropic", key="k", model="claude-haiku-4-5-20251001"),
    ), patch("app.layers.providers.anthropic_provider.Anthropic"):
        p = get_provider()
    assert isinstance(p, ClaudeProvider)
```

- [ ] **Step 2: Run factory tests — expect failures**

Run:

```bash
pytest tests/unit/providers/test_factory.py -v
```

Expected: the new factory tests fail with `ImportError: cannot import name 'get_provider'` (or similar).

- [ ] **Step 3: Implement the factory**

Replace the contents of `app/layers/providers/__init__.py` with:

```python
"""LLM provider abstraction for Layer 3 (AIResolver)."""

from __future__ import annotations

from app.config.settings import settings
from app.layers.providers.base import LLMProvider


class ConfigError(Exception):
    """Raised when AI provider configuration is invalid or incomplete."""


_VALID_PROVIDERS = ("openai", "gemini", "anthropic")


def _missing_vars(provider: str, key: str, model: str) -> list[str]:
    missing: list[str] = []
    if not provider:
        missing.append("AI_PROVIDER")
    if not key:
        missing.append("LLM_KEY")
    if not model:
        missing.append("LLM_MODEL")
    return missing


def get_provider() -> LLMProvider | None:
    """Return the configured LLMProvider, or None if L3 is disabled.

    L3 is disabled only when all three env vars (AI_PROVIDER, LLM_KEY,
    LLM_MODEL) are unset. Any partial or invalid configuration raises
    ConfigError with a message naming the problem.
    """
    provider = (settings.ai_provider or "").strip().lower()
    key      = (settings.llm_key or "").strip()
    model    = (settings.llm_model or "").strip()

    if not provider and not key and not model:
        return None

    missing = _missing_vars(provider, key, model)
    if missing:
        raise ConfigError(
            "Incomplete LLM configuration — missing: "
            + ", ".join(missing)
        )

    if provider not in _VALID_PROVIDERS:
        raise ConfigError(
            f"Invalid AI_PROVIDER: {settings.ai_provider!r}. "
            f"Must be one of: {', '.join(_VALID_PROVIDERS)}"
        )

    if provider == "openai":
        from app.layers.providers.openai_provider import OpenAIProvider
        return OpenAIProvider(api_key=key, model=model)
    if provider == "gemini":
        from app.layers.providers.gemini_provider import GeminiProvider
        return GeminiProvider(api_key=key, model=model)
    # provider == "anthropic"
    from app.layers.providers.anthropic_provider import ClaudeProvider
    return ClaudeProvider(api_key=key, model=model)


__all__ = ["LLMProvider", "ConfigError", "get_provider"]
```

- [ ] **Step 4: Run factory tests — expect pass**

Run:

```bash
pytest tests/unit/providers/test_factory.py -v
```

Expected: all factory tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/layers/providers/__init__.py tests/unit/providers/test_factory.py
git commit -m "feat: add get_provider() factory with validation"
```

---

## Task 9: Refactor AIResolver to consume LLMProvider

**Files:**
- Modify: `app/layers/ai_resolver.py` (full rewrite)
- Create: `tests/unit/test_ai_resolver.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_ai_resolver.py`:

```python
"""Unit tests for AIResolver with a fake LLM provider."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.layers.ai_resolver import AIResolver
from app.layers.providers.base import LLMProvider
from app.schemas.actions import ActionType, FlowAction, StepResult


class FakeProvider(LLMProvider):
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[dict] = []

    def complete(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.0,
        max_tokens: int = 500,
    ) -> str:
        self.calls.append(
            {
                "system": system,
                "user": user,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        )
        return self.response


def _action(kind: ActionType = ActionType.AI_ASSERT, args=("page is loaded",)) -> FlowAction:
    return FlowAction(type=kind, args=list(args), raw="", step_num=1)


def test_available_false_when_provider_is_none():
    resolver = AIResolver(provider=None)
    assert resolver.available is False


def test_available_true_when_provider_set():
    resolver = AIResolver(provider=FakeProvider("ignored"))
    assert resolver.available is True


def test_ai_assert_parses_provider_json_response():
    provider = FakeProvider('{"result": true, "reason": "all good"}')
    resolver = AIResolver(provider=provider)

    page = MagicMock()
    page.url = "http://x"
    page.title.return_value = "t"
    page.inner_text.return_value = "some page text"

    result = resolver.resolve_ai_action(_action(), page, ctx=None)
    assert isinstance(result, StepResult)
    assert result.success is True
    assert result.layer_used == 3
    assert "all good" in result.message
    assert len(provider.calls) == 1


def test_resolve_returns_none_when_provider_unavailable():
    resolver = AIResolver(provider=None)
    assert resolver.resolve(_action(), MagicMock(), error="boom") is None


def test_resolve_ai_action_returns_none_when_provider_unavailable():
    resolver = AIResolver(provider=None)
    assert resolver.resolve_ai_action(_action(), MagicMock()) is None
```

- [ ] **Step 2: Run test — expect failure**

Run:

```bash
pytest tests/unit/test_ai_resolver.py -v
```

Expected: fails because `AIResolver` currently takes no `provider` argument.

- [ ] **Step 3: Rewrite `app/layers/ai_resolver.py`**

Replace the entire file with:

```python
"""
AI Resolver (Layer 3) — last-resort LLM invocation.

Only called when both deterministic (L1) and fallback (L2) strategies
fail. Sends a minimal page snapshot to an LLM and asks for an
alternative locator strategy.

Also handles AI-native actions (ai_click, ai_extract, ai_assert,
ai_summarize) that bypass L1/L2 entirely.

Skipped entirely when no LLM provider is configured.
"""

from __future__ import annotations

import json
import logging

from playwright.sync_api import Page

from app.agent.prompts.resolver import (
    SYSTEM as _SYSTEM,
    USER_TEMPLATE as _USER_TMPL,
    PROMPTS as _AI_PROMPTS,
)
from app.layers.providers import LLMProvider
from app.schemas.actions import ActionType, FlowAction, RunContext, StepResult

logger = logging.getLogger(__name__)

_MAX_PAGE_TEXT = 4000
_RESOLVE_MAX_TOKENS = 200
_AI_ACTION_MAX_TOKENS = 500


def _get_page_text(page: Page) -> str:
    try:
        text = page.inner_text("body")
        return text[:_MAX_PAGE_TEXT] if text else ""
    except Exception:
        return ""


def _history_block(ctx: RunContext | None) -> str:
    if not ctx or not ctx.history:
        return ""
    recent = ctx.recent_history(5)
    lines = [
        f"  - {h['action']}({h['target']}) → {h['result']} [L{h['layer']}]"
        for h in recent
    ]
    return "\n\nRecent execution history (last steps):\n" + "\n".join(lines)


class AIResolver:
    """Layer 3: LLM-based element resolution as a last resort."""

    def __init__(self, provider: LLMProvider | None) -> None:
        self._provider = provider

    @property
    def available(self) -> bool:
        return self._provider is not None

    def resolve(
        self,
        action: FlowAction,
        page: Page,
        error: str,
        ctx: RunContext | None = None,
    ) -> StepResult | None:
        if self._provider is None:
            return None

        try:
            user_msg = _USER_TMPL.format(
                url=page.url,
                title=page.title(),
                action_type=action.type.value,
                args=action.args,
                error=error,
            ) + _history_block(ctx)

            raw = self._provider.complete(
                _SYSTEM, user_msg,
                temperature=0.0, max_tokens=_RESOLVE_MAX_TOKENS,
            ).strip() or "{}"

            suggestion = json.loads(raw)
            loc = self._build_locator(page, suggestion)
            if loc is None:
                logger.warning(f"[L3] Suggestion yielded no match: {suggestion}")
                return None

            self._execute_with_locator(action, loc)
            reason = suggestion.get("reason", "AI resolved")
            logger.info(f"[L3] Step {action.step_num}: {reason}")
            return StepResult(
                action=action, success=True,
                message=f"[L3] {reason}", layer_used=3,
            )

        except Exception as exc:
            logger.warning(f"[L3] AI resolver failed: {exc}")
            return None

    def resolve_ai_action(
        self,
        action: FlowAction,
        page: Page,
        ctx: RunContext | None = None,
    ) -> StepResult | None:
        if self._provider is None:
            return None

        action_key = action.type.value
        prompts = _AI_PROMPTS.get(action_key)
        if not prompts:
            logger.warning(f"[L3] No prompt template for AI action: {action_key}")
            return None

        try:
            target = action.args[0] if action.args else ""
            page_text = _get_page_text(page)
            user_msg = prompts["user"].format(
                url=page.url,
                title=page.title(),
                page_text=page_text,
                target=target,
            ) + _history_block(ctx)

            raw_response = self._provider.complete(
                prompts["system"], user_msg,
                temperature=0.0, max_tokens=_AI_ACTION_MAX_TOKENS,
            ).strip()

            if action.type == ActionType.AI_CLICK:
                return self._handle_ai_click(action, page, raw_response)
            if action.type == ActionType.AI_EXTRACT:
                if ctx is not None:
                    ctx.store("last_extract", raw_response)
                    if target:
                        ctx.store(f"extract_{target}", raw_response)
                return StepResult(
                    action=action, success=True,
                    message=f"[L3] Extracted: {raw_response}", layer_used=3,
                )
            if action.type == ActionType.AI_ASSERT:
                return self._handle_ai_assert(action, raw_response)
            if action.type == ActionType.AI_SUMMARIZE:
                return StepResult(
                    action=action, success=True,
                    message=f"[L3] Summary: {raw_response}", layer_used=3,
                )

        except Exception as exc:
            logger.warning(f"[L3] AI action failed: {exc}")

        return None

    def _handle_ai_click(
        self, action: FlowAction, page: Page, raw: str
    ) -> StepResult | None:
        try:
            suggestion = json.loads(raw)
            loc = self._build_locator(page, suggestion)
            if loc is None:
                return None
            loc.click()
            reason = suggestion.get("reason", "AI-resolved click")
            return StepResult(
                action=action, success=True,
                message=f"[L3] {reason}", layer_used=3,
            )
        except Exception as exc:
            logger.warning(f"[L3] AI click failed: {exc}")
            return None

    def _handle_ai_assert(
        self, action: FlowAction, raw: str
    ) -> StepResult | None:
        try:
            data = json.loads(raw)
            passed = data.get("result", False)
            reason = data.get("reason", "AI assertion")
            return StepResult(
                action=action, success=passed,
                message=f"[L3] {reason}", layer_used=3,
            )
        except Exception as exc:
            logger.warning(f"[L3] AI assert parse failed: {exc}")
            return None

    @staticmethod
    def _execute_with_locator(action: FlowAction, loc) -> None:
        value = action.args[1] if len(action.args) > 1 else ""
        t = action.type.value

        if t in ("click", "click_link_text"):
            loc.click()
        elif t == "double_click":
            loc.dblclick()
        elif t == "right_click":
            loc.click(button="right")
        elif t == "hover":
            loc.hover()
        elif t == "fill":
            loc.fill(value)
        elif t == "type":
            loc.press_sequentially(value)
        elif t == "select":
            loc.select_option(value)
        elif t == "check":
            loc.check()
        elif t == "uncheck":
            loc.uncheck()
        elif t == "clear":
            loc.clear()
        elif t == "focus":
            loc.focus()

    @staticmethod
    def _build_locator(page: Page, s: dict):
        strategy = s.get("strategy", "css")
        value    = s.get("value", "")
        role     = s.get("role", "")
        try:
            if strategy == "css":
                loc = page.locator(value)
            elif strategy == "text":
                loc = page.get_by_text(value)
            elif strategy == "role" and role:
                loc = page.get_by_role(role, name=value)
            elif strategy == "label":
                loc = page.get_by_label(value)
            elif strategy == "placeholder":
                loc = page.get_by_placeholder(value)
            else:
                loc = page.locator(value)

            return loc.first if loc.count() > 0 else None
        except Exception:
            return None
```

Key changes vs. original:
- Constructor now takes `provider: LLMProvider | None` (no kwargs).
- No `os`, `openai` imports at all.
- `available` is a plain attribute-based check.
- Both `resolve` and `resolve_ai_action` use `self._provider.complete(system, user, ...)`.
- `_history_block` helper removes the duplicated history-appending code.

- [ ] **Step 4: Run test — expect pass**

Run:

```bash
pytest tests/unit/test_ai_resolver.py -v
```

Expected: all five tests pass.

- [ ] **Step 5: Verify no stray OpenAI references**

Run:

```bash
grep -rn "OPENAI_API_KEY\|OPENAI_MODEL\|from openai" app/layers/ai_resolver.py || echo "clean"
```

Expected: prints `clean`.

- [ ] **Step 6: Commit**

```bash
git add app/layers/ai_resolver.py tests/unit/test_ai_resolver.py
git commit -m "refactor: AIResolver consumes LLMProvider interface"
```

---

## Task 10: Wire factory into engine and generalize messages

**Files:**
- Modify: `app/execution/engine.py` (imports, `FlowRunner.__init__`, three message strings)

- [ ] **Step 1: Update imports**

In `app/execution/engine.py`, change the layer imports block (around line 32–33):

```python
from app.layers.ai_resolver import AIResolver
from app.layers.deterministic import DeterministicRunner
```

To:

```python
from app.layers.ai_resolver import AIResolver
from app.layers.deterministic import DeterministicRunner
from app.layers.providers import get_provider
```

- [ ] **Step 2: Inject provider into AIResolver**

Find the `FlowRunner.__init__` method. Change this line (around line 111):

```python
        self._ai = AIResolver()
```

To:

```python
        self._ai = AIResolver(provider=get_provider())
```

Note: `get_provider()` may raise `ConfigError` on misconfiguration — this is the correct behavior (fail fast at startup).

- [ ] **Step 3: Generalize the three OpenAI-specific messages**

Find and replace the three messages.

Replacement A — the AI-action guard log (around line 320):

```python
                logger.warning(
                    f"[L3] Skipped AI action '{action.type.value}' — "
                    "OPENAI_API_KEY is not set"
                )
```

→

```python
                logger.warning(
                    f"[L3] Skipped AI action '{action.type.value}' — "
                    "LLM provider not configured"
                )
```

Replacement B — the StepResult message/error for AI-action guard (around lines 326–331):

```python
                    message=(
                        f"AI action '{action.type.value}' requires OPENAI_API_KEY "
                        "(L3 skipped: missing API key)"
                    ),
                    layer_used=3,
                    error="OPENAI_API_KEY is not set",
```

→

```python
                    message=(
                        f"AI action '{action.type.value}' requires AI_PROVIDER, LLM_KEY and LLM_MODEL "
                        "(L3 skipped: provider not configured)"
                    ),
                    layer_used=3,
                    error="LLM provider not configured",
```

Replacement C — the L3-skipped log + L2-failure message (around lines 387–390):

```python
            logger.info("[L3] Skipped — OPENAI_API_KEY is not set")
            return StepResult(
                action=action, success=False,
                message=f"L1+L2 failed (L3 skipped: missing API key): {error_msg}",
```

→

```python
            logger.info("[L3] Skipped — LLM provider not configured")
            return StepResult(
                action=action, success=False,
                message=f"L1+L2 failed (L3 skipped: provider not configured): {error_msg}",
```

- [ ] **Step 4: Verify no OpenAI leakage remains in engine**

Run:

```bash
grep -n "OPENAI_API_KEY\|OPENAI_MODEL\|openai" app/execution/engine.py || echo "clean"
```

Expected: prints `clean`.

- [ ] **Step 5: Run all unit tests**

Run:

```bash
pytest tests/ -v
```

Expected: all unit tests pass (10+ tests across provider, factory, resolver files).

- [ ] **Step 6: Commit**

```bash
git add app/execution/engine.py
git commit -m "feat: wire LLM provider factory into engine; generic error messages"
```

---

## Task 11: Update env file templates

**Files:**
- Modify: `.env.example`
- Modify: `.env`

- [ ] **Step 1: Update `.env.example`**

In `.env.example`, find this block:

```
# ── AI resolver (Layer 3 — optional) ──────────────────────────────────────────
OPENAI_API_KEY=              # required to enable Layer 3 AI fallback
OPENAI_MODEL=gpt-4o-mini    # OpenAI model to use for element resolution
```

Replace with:

```
# ── AI resolver (Layer 3 — optional) ──────────────────────────────────────────
# Set all three to enable L3. Leave all three empty to disable L3.
AI_PROVIDER=                 # openai | gemini | anthropic
LLM_KEY=                     # API key for the selected provider
LLM_MODEL=                   # model id (e.g. gpt-4o-mini, gemini-1.5-flash, claude-haiku-4-5-20251001)
```

- [ ] **Step 2: Update `.env`**

In `.env`, find the same block — note that the current `.env` has the key commented out:

```
# ── AI resolver (Layer 3 — optional) ──────────────────────────────────────────
# OPENAI_API_KEY=<YOUR_OPENAI_KEY>
OPENAI_MODEL=gpt-4o-mini    # OpenAI model to use for element resolution
```

Replace with:

```
# ── AI resolver (Layer 3 — optional) ──────────────────────────────────────────
# Set all three to enable L3. Leave all three empty to disable L3.
AI_PROVIDER=openai           # openai | gemini | anthropic
# LLM_KEY=<YOUR_OPENAI_KEY>
LLM_MODEL=gpt-4o-mini        # model id for the selected provider
```

This preserves the user's existing commented-out OpenAI key (just renamed to `LLM_KEY`). To re-enable L3, the user uncomments the `LLM_KEY` line.

- [ ] **Step 3: Verify engine still starts (L3 disabled branch)**

With `LLM_KEY` commented out (current state of `.env`), run:

```bash
python -c "from app.layers.providers import get_provider; print(get_provider())"
```

Expected: prints `None` (all three vars aren't all set because `LLM_KEY` is missing → but `AI_PROVIDER=openai` is set).

Wait — that's a partial config and should raise `ConfigError`. That is correct behavior per spec. To test the "disabled" branch cleanly:

```bash
AI_PROVIDER= LLM_KEY= LLM_MODEL= python -c "from app.layers.providers import get_provider; print(get_provider())"
```

Expected: prints `None`.

And to confirm misconfig fails loudly:

```bash
AI_PROVIDER=openai LLM_KEY= LLM_MODEL=gpt-4o-mini python -c "from app.layers.providers import get_provider; get_provider()"
```

Expected: exits with `ConfigError: Incomplete LLM configuration — missing: LLM_KEY`.

- [ ] **Step 4: Commit**

```bash
git add .env.example .env
git commit -m "docs: update env templates for new LLM provider vars"
```

---

## Task 12: Full regression — run all tests and one flow

**Files:** none (verification only)

- [ ] **Step 1: Run the full unit-test suite**

Run:

```bash
pytest tests/ -v
```

Expected: all unit tests pass. No errors, no warnings about the AI layer.

- [ ] **Step 2: Check for any residual OpenAI references**

Run:

```bash
grep -rn "OPENAI_API_KEY\|OPENAI_MODEL" app/ tests/ || echo "clean"
```

Expected: `clean`.

Run:

```bash
grep -rn "from openai\|import openai" app/ tests/
```

Expected: only one hit — `app/layers/providers/openai_provider.py`. Any other occurrence means cleanup was incomplete; go back and fix.

- [ ] **Step 3: Smoke-run the smallest flow with L3 disabled**

With `LLM_KEY` commented out in `.env` (so L3 stays disabled), pick the smallest flow file and run it:

```bash
ls flows/login/ 2>/dev/null || ls flows/ | head -5
```

Then:

```bash
pytest --flow_file=<path-to-smallest-flow.md> -v
```

Expected: flow runs to completion (or fails for reasons unrelated to L3). The logs should include `[L3] Skipped — LLM provider not configured` if any L1/L2 step fails. There should be no Python exceptions from the AI layer.

- [ ] **Step 4: Smoke-run with L3 enabled (OpenAI)**

Uncomment `LLM_KEY=` in `.env` (restore the user's OpenAI key line). Run the same flow:

```bash
pytest --flow_file=<path-to-smallest-flow.md> -v
```

Expected: flow runs to completion. If the flow contains any `ai_*` action, it should invoke the OpenAI provider and succeed.

- [ ] **Step 5: Confirm no uncommitted changes**

Run:

```bash
git status
```

Expected: clean working tree (all task commits already landed).

---

## Self-Review Results

**Spec coverage check:**

| Spec section | Covered by |
|--------------|-----------|
| Configuration — new env vars | Task 3, 11 |
| Configuration — removed vars | Task 3, 10, 11 |
| Validation rules | Task 8 |
| Provider abstraction — module layout | Task 4, 5, 6, 7 |
| Base interface | Task 4 |
| Provider implementations | Task 5, 6, 7 |
| Factory | Task 8 |
| AIResolver refactor | Task 9 |
| Engine updates | Task 10 |
| Dependencies | Task 2 |
| Error handling table | Task 8, 10 |
| Env file updates | Task 11 |
| Testing — unit | Task 4, 5, 6, 7, 8, 9 |
| Testing — integration | Task 12 |
| Success criteria | Task 12 |

No gaps.

**Placeholder scan:** No TBDs, TODOs, or "similar to Task N" references. Every code block is complete and copy-pasteable.

**Type consistency:** `LLMProvider.complete(system, user, *, temperature, max_tokens) -> str` signature is identical across base (Task 4), all three provider implementations (Tasks 5/6/7), the fake in `test_ai_resolver.py` (Task 9), and the two call sites in the resolver (Task 9). `get_provider()` return type `LLMProvider | None` matches consumer annotation in `AIResolver.__init__`. `ConfigError` is defined in Task 4, referenced consistently in Task 8. No drift found.

---

Plan complete and saved to `docs/superpowers/plans/2026-04-18-multi-provider-llm.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
