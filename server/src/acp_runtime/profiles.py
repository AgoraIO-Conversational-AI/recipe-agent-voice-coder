"""Small, pinned definitions for supported local coding Agents."""

import json
import os
from dataclasses import dataclass
from typing import Callable, Mapping

from .workspace import AgentProfile


_CUSTOM_COMMAND_ERROR = (
    "VOICE_ACP_COMMAND_JSON must be a JSON array of non-empty argument strings"
)
CODEX_SKILLS_CONTEXT_NOTICE = (
    "Warning: Skill descriptions were shortened to fit the 2% skills context "
    "budget. Codex can still see every skill, but some descriptions are shorter. "
    "Disable unused skills or plugins to leave more room for the rest."
)


def _identity(value: str) -> str:
    return value


def strip_codex_skills_notice(value: str) -> str:
    """Remove only the exact leading runtime notice observed from Codex ACP."""
    candidate = value.lstrip()
    if not candidate.startswith(CODEX_SKILLS_CONTEXT_NOTICE):
        return value
    return candidate[len(CODEX_SKILLS_CONTEXT_NOTICE) :].lstrip()


@dataclass(frozen=True)
class AgentDefinition:
    """Private process details paired with serializable public profile metadata."""

    profile: AgentProfile
    argv: tuple[str, ...]
    base_env: Mapping[str, str]
    forwarded_env: tuple[str, ...]
    agent_auth_method_id: str | None = None
    clean_final_text: Callable[[str], str] = _identity


@dataclass(frozen=True)
class AgentLaunch:
    """One resolved child-process launch without shell evaluation."""

    definition: AgentDefinition
    argv: tuple[str, ...]
    env: Mapping[str, str]


AGENT_DEFINITIONS: Mapping[str, AgentDefinition] = {
    "codex": AgentDefinition(
        profile=AgentProfile(id="codex", label="Codex"),
        argv=("npx", "-y", "@agentclientprotocol/codex-acp@1.1.7"),
        base_env={"INITIAL_AGENT_MODE": "agent"},
        forwarded_env=("CODEX_PATH", "CODEX_API_KEY", "OPENAI_API_KEY"),
        agent_auth_method_id="chatgpt",
        clean_final_text=strip_codex_skills_notice,
    ),
    "claude-code": AgentDefinition(
        profile=AgentProfile(id="claude-code", label="Claude Code"),
        argv=("npx", "-y", "@agentclientprotocol/claude-agent-acp@0.70.0"),
        base_env={},
        forwarded_env=("CLAUDE_CONFIG_DIR", "ANTHROPIC_API_KEY"),
    ),
}


def get_agent_definition(profile_id: str) -> AgentDefinition:
    try:
        return AGENT_DEFINITIONS[profile_id]
    except KeyError as exc:
        raise ValueError("Unsupported coding Agent profile") from exc


def resolve_agent_launch(
    profile_id: str, environ: Mapping[str, str] | None = None
) -> AgentLaunch:
    """Resolve one selected profile and its narrow advanced command override."""
    values = os.environ if environ is None else environ
    definition = get_agent_definition(profile_id)
    argv = definition.argv
    raw_override = values.get("VOICE_ACP_COMMAND_JSON")
    if raw_override:
        try:
            parsed = json.loads(raw_override)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError(_CUSTOM_COMMAND_ERROR) from exc
        if (
            not isinstance(parsed, list)
            or not parsed
            or len(parsed) > 64
            or any(
                not isinstance(argument, str)
                or not argument.strip()
                or len(argument.encode("utf-8")) > 4096
                for argument in parsed
            )
        ):
            raise ValueError(_CUSTOM_COMMAND_ERROR)
        argv = tuple(parsed)

    child_env = dict(definition.base_env)
    for name in definition.forwarded_env:
        value = values.get(name)
        if value:
            child_env[name] = value
    return AgentLaunch(definition=definition, argv=argv, env=child_env)
