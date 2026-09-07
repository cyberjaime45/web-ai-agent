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
