"""Supported local coding Agent profile tests."""

import json

import pytest

from acp_runtime.profiles import (
    AGENT_DEFINITIONS,
    CODEX_SKILLS_CONTEXT_NOTICE,
    resolve_agent_launch,
)


def test_supported_profiles_are_small_and_pinned():
    assert tuple(AGENT_DEFINITIONS) == ("codex", "claude-code")
    assert AGENT_DEFINITIONS["codex"].argv == (
        "npx",
        "-y",
        "@agentclientprotocol/codex-acp@1.1.7",
    )
    assert AGENT_DEFINITIONS["claude-code"].argv == (
        "npx",
        "-y",
        "@agentclientprotocol/claude-agent-acp@0.70.0",
    )


def test_profile_launch_passes_only_supported_environment(monkeypatch):
    monkeypatch.setenv("CODEX_API_KEY", "codex-secret")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-secret")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-secret")
    monkeypatch.setenv("UNRELATED_SECRET", "do-not-forward")

    codex = resolve_agent_launch("codex")
    claude = resolve_agent_launch("claude-code")

    assert codex.env == {
        "INITIAL_AGENT_MODE": "agent",
        "CODEX_API_KEY": "codex-secret",
        "OPENAI_API_KEY": "openai-secret",
    }
    assert claude.env == {"ANTHROPIC_API_KEY": "anthropic-secret"}


def test_custom_command_override_preserves_selected_profile(monkeypatch):
    monkeypatch.setenv(
        "VOICE_ACP_COMMAND_JSON",
        json.dumps(["/opt/acp/custom", "--stdio", "value with spaces"]),
    )

    launch = resolve_agent_launch("claude-code")

    assert launch.definition.profile.id == "claude-code"
    assert launch.argv == ("/opt/acp/custom", "--stdio", "value with spaces")


@pytest.mark.parametrize("value", ["not-json", '"shell"', "[]", '["ok", 3]'])
def test_invalid_custom_command_returns_one_safe_message(monkeypatch, value):
    monkeypatch.setenv("VOICE_ACP_COMMAND_JSON", value)

    with pytest.raises(ValueError) as raised:
        resolve_agent_launch("codex")

    assert str(raised.value) == (
        "VOICE_ACP_COMMAND_JSON must be a JSON array of non-empty argument strings"
    )
    assert value not in str(raised.value)


def test_codex_cleanup_is_leading_and_profile_specific():
    codex = AGENT_DEFINITIONS["codex"]
    claude = AGENT_DEFINITIONS["claude-code"]
    result = f"{CODEX_SKILLS_CONTEXT_NOTICE}\n\nUseful result."

    assert codex.clean_final_text(result) == "Useful result."
    assert claude.clean_final_text(result) == result
    assert codex.clean_final_text(f"Useful.\n{CODEX_SKILLS_CONTEXT_NOTICE}") == (
        f"Useful.\n{CODEX_SKILLS_CONTEXT_NOTICE}"
    )
