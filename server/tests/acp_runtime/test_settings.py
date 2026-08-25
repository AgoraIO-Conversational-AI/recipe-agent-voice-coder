"""Local coding Agent settings persistence tests."""

import json
import os
import stat

import pytest

from acp_runtime.settings import AgentSettingsService, AgentSettingsStore


def test_missing_settings_defaults_to_codex_without_writing(tmp_path):
    store = AgentSettingsStore(tmp_path / "agent-settings.json")
    service = AgentSettingsService(store)

    status = service.status()

    assert status.selected_profile.id == "codex"
    assert [profile.id for profile in status.profiles] == ["codex", "claude-code"]
    assert not store.path.exists()


def test_selected_profile_persists_independently(tmp_path):
    store = AgentSettingsStore(tmp_path / "state" / "agent-settings.json")
    service = AgentSettingsService(store)

    selected = service.select("claude-code")
    restored = AgentSettingsService(store).status()

    assert selected == restored
    assert restored.selected_profile.label == "Claude Code"
    assert json.loads(store.path.read_text(encoding="utf-8")) == {
        "agent_profile_id": "claude-code",
        "schema_version": "1.0",
    }
    if os.name == "posix":
        assert stat.S_IMODE(store.path.stat().st_mode) == 0o600


def test_unknown_profile_preserves_previous_selection(tmp_path):
    store = AgentSettingsStore(tmp_path / "agent-settings.json")
    service = AgentSettingsService(store)
    service.select("claude-code")
    before = store.path.read_bytes()

    with pytest.raises(ValueError, match="Unsupported coding Agent profile"):
        service.select("unknown")

    assert store.path.read_bytes() == before
    assert service.status().selected_profile.id == "claude-code"


def test_unsupported_schema_fails_closed(tmp_path):
    path = tmp_path / "agent-settings.json"
    path.write_text(
        json.dumps({"schema_version": "2.0", "agent_profile_id": "codex"}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Unsupported Agent settings version"):
        AgentSettingsService(AgentSettingsStore(path)).status()
