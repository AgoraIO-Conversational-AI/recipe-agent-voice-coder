"""Persist one selected local coding Agent independently from Workspace."""

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .profiles import AGENT_DEFINITIONS, AgentDefinition, get_agent_definition
from .workspace import AgentProfile


@dataclass(frozen=True)
class AgentSettingsStatus:
    profiles: tuple[AgentProfile, ...]
    selected_profile: AgentProfile


class AgentSettingsStore:
    """Atomic local record containing only one supported profile ID."""

    SCHEMA_VERSION = "1.0"

    def __init__(self, path: Path) -> None:
        self.path = path

    @classmethod
    def default(cls) -> "AgentSettingsStore":
        state_directory = os.getenv("VOICE_ACP_STATE_DIR")
        root = (
            Path(state_directory).expanduser()
            if state_directory
            else Path.home()
            / "Library"
            / "Application Support"
            / "Agora Voice ACP"
        )
        return cls(root / "agent-settings.json")

    def load(self) -> str | None:
        if not self.path.exists():
            return None
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != self.SCHEMA_VERSION:
            raise ValueError("Unsupported Agent settings version")
        profile_id = str(payload.get("agent_profile_id", ""))
        get_agent_definition(profile_id)
        return profile_id

    def save(self, profile_id: str) -> None:
        get_agent_definition(profile_id)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            dir=self.path.parent,
            prefix=f".{self.path.name}.",
            suffix=".tmp",
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(
                    {
                        "agent_profile_id": profile_id,
                        "schema_version": self.SCHEMA_VERSION,
                    },
                    stream,
                    sort_keys=True,
                )
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_path, self.path)
        except BaseException:
            temporary_path.unlink(missing_ok=True)
            raise


class AgentSettingsService:
    """Select one known profile and expose only its public metadata."""

    def __init__(self, store: AgentSettingsStore) -> None:
        self.store = store

    def status(self) -> AgentSettingsStatus:
        profile_id = self.store.load() or "codex"
        return AgentSettingsStatus(
            profiles=tuple(item.profile for item in AGENT_DEFINITIONS.values()),
            selected_profile=get_agent_definition(profile_id).profile,
        )

    def select(self, profile_id: str) -> AgentSettingsStatus:
        get_agent_definition(profile_id)
        self.store.save(profile_id)
        return self.status()

    def selected_definition(self) -> AgentDefinition:
        return get_agent_definition(self.status().selected_profile.id)
