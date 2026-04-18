# Multi-Provider LLM Support — Design

Date: 2026-04-18
Status: Approved

## Problem

Layer 3 of the WebAgent (AI fallback resolver) is hard-coded to OpenAI. To support
teams using different LLM vendors, the agent must be able to call OpenAI, Google
Gemini, or Anthropic Claude interchangeably, selected via configuration.

## Goals

- Swap LLM provider via `.env` with no code changes: `AI_PROVIDER=openai|gemini|anthropic`.
- A single abstraction so Layer 3 logic is provider-agnostic.
- Adding a fourth provider in the future means one new file, no changes to the resolver.
- Remove OpenAI-specific code and configuration that is no longer needed.

## Non-goals

- Streaming, tool use, vision, or JSON mode features of any SDK — not needed by L3.
- Per-call provider switching mid-flow.
- Backward compatibility with `OPENAI_API_KEY` / `OPENAI_MODEL` env vars.

## Configuration

### New environment variables

| Variable | Values | Required |
|----------|--------|----------|
| `AI_PROVIDER` | `openai` \| `gemini` \| `anthropic` | Yes, when L3 is enabled |
| `LLM_KEY` | API key for the selected provider | Yes, when L3 is enabled |
| `LLM_MODEL` | Model identifier | Yes, when L3 is enabled (fail fast, no defaults) |

### Removed environment variables

- `OPENAI_API_KEY` — replaced by `LLM_KEY`.
- `OPENAI_MODEL` — replaced by `LLM_MODEL`.

### Config load validation (`app/config/settings.py`)

Replace the two `openai_*` fields with:

```python
ai_provider: str  # "" when disabled
llm_key:     str  # "" when disabled
llm_model:   str  # "" when disabled
```

Validation happens in the provider factory (see below), not at settings load,
so importing `settings` never raises.

Rules:

- If **all three** are empty → L3 is disabled (factory returns `None`).
- If **any** of the three is set → all three must be set. Otherwise the
  factory raises `ConfigError` listing which vars are missing.
- `AI_PROVIDER` must be one of the three valid values. Otherwise
  `ConfigError("Invalid AI_PROVIDER: '<x>'. Must be one of: openai, gemini, anthropic")`.

## Architecture

### Module layout

```
app/layers/providers/
├── __init__.py              # get_provider() factory + ConfigError
├── base.py                  # LLMProvider ABC
├── openai_provider.py       # OpenAIProvider
├── gemini_provider.py       # GeminiProvider
└── anthropic_provider.py    # ClaudeProvider
```

### Base interface

```python
class LLMProvider(ABC):
    @abstractmethod
    def complete(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0,
        max_tokens: int = 500,
    ) -> str:
        """Return the raw text response from the model."""
```

**Design rationale:** the two existing Layer 3 call sites both need only a
single-turn `(system, user) -> text` exchange. Prompts already produce
plain text (or JSON embedded in text); the AIResolver parses. Keeping the
interface this thin means each provider class is small and each SDK's
idiosyncrasies are localized.

### Provider implementations

Each provider class is a thin adapter that:

1. Reads `LLM_KEY` and `LLM_MODEL` from settings at construction time.
2. Instantiates the vendor SDK client once per instance.
3. Translates the `(system, user)` pair into the SDK's call shape:
   - **OpenAI:** `messages=[{role: "system", content: system}, {role: "user", content: user}]`
   - **Anthropic:** `system=system, messages=[{role: "user", content: user}]`
   - **Gemini:** `GenerativeModel(model, system_instruction=system).generate_content(user)`
4. Returns the text content of the first (and only) response.

No provider class touches logging, screenshots, action types, or history —
those are the AIResolver's responsibility.

### Factory

```python
def get_provider() -> LLMProvider | None:
    """
    Return a configured LLMProvider, or None if all LLM vars are unset.
    Raises ConfigError on invalid or partial configuration.
    """
```

Mapping:
- `"openai"`    → `OpenAIProvider`
- `"gemini"`    → `GeminiProvider`
- `"anthropic"` → `ClaudeProvider`

## AIResolver refactor (`app/layers/ai_resolver.py`)

- Drop `from openai import OpenAI` and all direct SDK imports.
- Constructor accepts an `LLMProvider | None` (injected via `get_provider()`
  at engine startup).
- `available` property becomes `self._provider is not None`.
- `resolve()` and `resolve_ai_action()` replace their inline
  `client.chat.completions.create(...)` call with:

  ```python
  raw = self._provider.complete(system, user_msg, max_tokens=<current value>)
  ```

- `_build_locator`, `_execute_with_locator`, `_handle_ai_click`,
  `_handle_ai_assert`, and all prompt loading stay unchanged — they are
  already provider-agnostic.

## Engine updates (`app/execution/engine.py`)

Replace user-facing strings that name OpenAI specifically:

| Current | New |
|---------|-----|
| `"OPENAI_API_KEY is not set"` | `"LLM provider not configured"` |
| `"AI action '<x>' requires OPENAI_API_KEY ..."` | `"AI action '<x>' requires AI_PROVIDER/LLM_KEY/LLM_MODEL ..."` |
| `"[L3] Skipped — OPENAI_API_KEY is not set"` | `"[L3] Skipped — LLM provider not configured"` |

No structural engine changes. `self._ai.available` continues to gate L3.

## Dependencies (`requirements.txt`)

Add:

```
google-generativeai==0.8.3
anthropic==0.40.0
```

Keep `openai==1.58.1`. All three SDKs are always installed — simpler UX
for an internal automation tool.

## Error handling

| Scenario | Behavior |
|----------|----------|
| All three env vars unset | Factory returns `None`. L3 disabled. Same behavior as today with a missing OpenAI key. |
| Partial config (e.g., `AI_PROVIDER=gemini` but no `LLM_KEY`) | `ConfigError` listing the missing vars. Raised at engine startup when the factory is first called. |
| Invalid `AI_PROVIDER` value | `ConfigError` naming the bad value and valid options. |
| Invalid `LLM_MODEL` for the selected provider | Raised by the vendor SDK at first call. Caught by existing `try/except` in AIResolver. Step fails cleanly as L3 failure with the SDK error surfaced in logs. |
| Rate limit / network failure | Caught by existing `try/except` in AIResolver. Returns `None`, step fails as L3 failure. No retry semantics changed. |

## Env file updates

- `.env.example` — remove old OpenAI vars, add the three new vars with brief comments.
- `.env` — same change to the comment block. User's actual secrets untouched.

## Testing

### Unit tests (new)

- `tests/unit/providers/test_openai_provider.py`
- `tests/unit/providers/test_gemini_provider.py`
- `tests/unit/providers/test_anthropic_provider.py`
- `tests/unit/providers/test_factory.py`

Each provider test mocks the SDK client and asserts the `(system, user)`
pair maps to the correct SDK call shape and that `complete()` returns the
extracted string.

Factory test covers:
- All three valid configurations return the expected class.
- All-empty config returns `None`.
- Each partial config raises `ConfigError` with an informative message.
- Invalid `AI_PROVIDER` string raises `ConfigError`.

### Integration

Existing flow tests must pass with:
```
AI_PROVIDER=openai
LLM_KEY=<existing OpenAI key>
LLM_MODEL=gpt-4o-mini
```

No flow `.md` files change.

## Files touched

| File | Change |
|------|--------|
| `app/config/settings.py` | Replace `openai_*` fields with `ai_provider`, `llm_key`, `llm_model`. |
| `app/layers/providers/__init__.py` | **New** — factory + `ConfigError`. |
| `app/layers/providers/base.py` | **New** — `LLMProvider` ABC. |
| `app/layers/providers/openai_provider.py` | **New**. |
| `app/layers/providers/gemini_provider.py` | **New**. |
| `app/layers/providers/anthropic_provider.py` | **New**. |
| `app/layers/ai_resolver.py` | Inject `LLMProvider`, drop direct OpenAI SDK usage. |
| `app/execution/engine.py` | Update error/log messages. |
| `requirements.txt` | Add `google-generativeai`, `anthropic`. |
| `.env.example`, `.env` | Replace OpenAI vars with new ones (secrets untouched in `.env`). |
| `tests/unit/providers/...` | **New** unit tests. |

## Success criteria

1. `AI_PROVIDER=openai` — all existing flows run and L3 fires as before.
2. `AI_PROVIDER=gemini` / `anthropic` — L3 fires with the selected provider; AI-native actions (`ai_click`, `ai_extract`, `ai_assert`, `ai_summarize`) behave identically.
3. All env vars empty — L3 is disabled cleanly, no errors.
4. Partial / invalid config — clear `ConfigError` message naming the problem.
5. `grep -r "OPENAI_API_KEY\|OPENAI_MODEL\|from openai" app/ tests/` returns only the new `openai_provider.py` import.
6. Adding a hypothetical `CohereProvider` requires only one new file plus one line in the factory.
