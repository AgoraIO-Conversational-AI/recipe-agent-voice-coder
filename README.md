# Agora Voice Coder

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)
[![Python](https://img.shields.io/badge/python-%3E%3D3.10-blue)](https://www.python.org/)
[![Bun](https://img.shields.io/badge/bun-latest-black)](https://bun.sh/)

Control a local coding agent through an Agora voice conversation.

Speak naturally while Agora handles the realtime voice experience. When a
request depends on your selected Project Folder, the voice agent delegates the
work to a local coding agent over the [Agent Client Protocol
(ACP)](https://agentclientprotocol.com/), keeps you in control of permissions
and cancellation, and speaks the result when it is done.

## What It Does

- Runs the coding agent locally against one selected Project Folder.
- Uses Agora Managed STT, LLM, and TTS for the voice conversation.
- Delegates durable background Work through authenticated MCP tools.
- Relays coding-agent permission decisions through the voice conversation.
- Supports status checks, cancellation, and context-aware spoken completion
  results through the current Managed Voice LLM conversation.

## Current Support

- macOS on Apple Silicon
- Codex and Claude Code through pinned ACP adapters
- One remembered Agent selection and one separately remembered Project Folder

> **Experimental completion prototype:** Managed `/think` re-entry is
> implemented. Its first live check was conversationally acceptable and created
> no recursive Work, but the assistant transcript contained Markdown even
> though TTS did not read it aloud. The prompt now requires plain spoken text;
> that transcript fix and interruption recovery still need live acceptance, so
> this is not a stable recipe contract yet.

## Prerequisites

- [Python 3.10+](https://www.python.org/)
- [Bun](https://bun.sh/)
- [Agora CLI](https://github.com/AgoraIO/cli)
- [ngrok](https://ngrok.com/)
- Node.js 22 or newer
- Codex or Claude Code authentication supported by the selected ACP adapter

## Run It

```bash
git clone https://github.com/AgoraIO-Conversational-AI/recipe-agent-voice-coder.git
cd recipe-agent-voice-coder

agora login
agora project use <your-project>
bun run setup
agora project env write server/.env.local

# One-time ngrok account setup, if it is not already configured:
ngrok config add-authtoken <your-token>

bun run dev:local
```

Open [http://127.0.0.1:3000](http://127.0.0.1:3000). On first launch, **Local
Coding Setup** opens automatically. Choose Codex or Claude Code, then select an
existing **Project Folder**. Successful setup closes the dialog and enables
**Start Conversation** without a separate Save action. Cancelling the macOS
picker simply returns to setup. Reopen the same dialog from the pre-call page
to change either choice.

The selected Agent reuses existing credentials when possible. Codex follows
its ACP-provided ChatGPT sign-in flow. When Claude Code needs authentication,
setup opens one macOS Terminal window for the official Claude login command,
waits for completion, and retries without asking for the folder again. Starting
a conversation uses Agora minutes; setup and offline verification do not.

Services started by `bun run dev:local`:

- Web app: `http://127.0.0.1:3000`
- Local API: `http://127.0.0.1:8000`
- Private MCP listener: `http://127.0.0.1:8001`

## How It Works

```text
Voice -> Agora Managed STT / LLM / TTS
      -> authenticated MCP over ngrok
      -> local Task Runtime
      -> selected Project Folder
      -> ACP over local stdio
      -> selected local coding agent
```

1. The browser joins an Agora RTC/RTM channel and starts a managed voice Agent.
2. The managed LLM receives four authenticated Work tools: start, status,
   cancel, and permission response.
3. Workspace-dependent requests become natural-language Work objectives. The
   public tool returns immediately while the local FIFO Task Runtime executes
   the objective through ACP.
4. Coding-agent activity and permission requests are converted into bounded,
   voice-safe state. Permission decisions remain explicit.
5. Completed Work keeps its full cleaned result in durable status and injects
   one bounded `LOCAL_WORK_COMPLETED` envelope into the originating active
   Agent through Agora `/think`. The Managed LLM turns it into a short answer
   grounded in the live conversation and is instructed to output plain spoken
   sentences without Markdown formatting. Failed Work keeps a bounded direct-speech
   error; cancelled Work remains silent.
6. A normal `/think` return records input acceptance only, not generated text,
   playback, or proof that the user heard it. A definite HTTP rejection may use
   one fixed `The work is done.` direct-speech fallback; ambiguous outcomes are
   never retried. Durable status remains authoritative.

## Safety and Privacy

- Only the authenticated MCP listener crosses the ngrok tunnel. The local API,
  Project Folder routes, ACP session, and coding-agent process remain loopback
  or local-only.
- Every voice Agent receives a short-lived bearer bound to its exact Agent and
  Workspace generation. Ending the Agent revokes that capability.
- The Project Folder is working context, **not a filesystem sandbox**. The
  local coding agent retains the access allowed by its own process and account.
- The Project Folder path is shown only in the loopback settings UI. ACP
  identifiers, credentials, and full MCP configuration are not returned to the
  browser or included in public MCP results.
- Local Work state is stored in SQLite. Public status output is bounded and
  durable text is redacted before storage.
- Completed ACP output is cleaned before storage and enters the Managed LLM as
  bounded untrusted JSON data. The voice prompt forbids treating that result as
  instructions or reading code, paths, logs, warnings, or protocol fields aloud.
- Agent-native authentication and provider billing remain between you and the
  selected coding agent.

## Environment Variables

Primary backend environment file: [`server/.env.example`](server/.env.example).

| Variable | Required | Default | Notes |
| --- | :---: | --- | --- |
| `AGORA_APP_ID` | Yes | — | Agora project App ID |
| `AGORA_APP_CERTIFICATE` | Yes | — | Server-only Agora App Certificate |
| `AGENT_GREETING` | No | Built in | Opening voice message |
| `VOICE_ACP_STATE_DIR` | No | macOS Application Support | Workspace and Work state parent directory |
| `HOST` | No | `0.0.0.0` | `dev:local` always binds the local API to `127.0.0.1` |
| `PORT` | No | `8000` | Local API port |
| `CODEX_PATH` | No | Packaged Codex | Advanced Codex binary override passed only to the ACP child |
| `CODEX_API_KEY` | No | — | Advanced child-process credential pass-through |
| `OPENAI_API_KEY` | No | — | Advanced child-process credential pass-through |
| `CLAUDE_CONFIG_DIR` | No | Claude default | Advanced child-process configuration directory pass-through |
| `ANTHROPIC_API_KEY` | No | — | Advanced child-process credential pass-through |
| `VOICE_ACP_COMMAND_JSON` | No | Pinned adapter | Advanced JSON argv array; never evaluated by a shell |

Agora manages the default voice STT, LLM, and TTS providers, so the voice
pipeline does not require separate provider keys. Per-Agent MCP credentials are
generated at runtime and are not developer-managed environment variables.

## Commands

```bash
# Setup and local run
bun run setup
bun run doctor:local
bun run preflight:local-agent
bun run dev:local

# Offline verification
bun run verify
bun run verify:backend
bun run verify:local
bun run verify:launcher
```

Offline checks use fake ACP, ngrok, voice Agent, and FastAPI paths. They do not
start a conversation, open the native picker, authenticate a real coding agent,
or consume Agora minutes.

### Advanced ACP launch options

```bash
bun run dev:local -- --workspace /absolute/path/to/project
CODEX_PATH=/absolute/path/to/codex bun run dev:local
ANTHROPIC_API_KEY=... bun run dev:local
bun run dev:local -- --acp-command-json '["/absolute/path/to/acp-agent","--stdio"]'
```

The custom command must be a JSON argv array and is never run through a shell.
It replaces the launch command for the selected Agent identity; it does not
change that identity or its authentication behavior. These options do not
bypass Project Folder validation. Secret values and child environments are
never logged.

### Managed voice validation harness

`bun run validate:managed` is an isolated architecture-evidence harness. It
uses synthetic MCP and permission behavior and does not execute local coding
Work. It starts a real Agora Agent and therefore requires separate permission
when conversation minutes are limited. See [`validation/README.md`](validation/README.md).

## Architecture

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="./.github/images/system-architecture-dark.svg">
  <img src="./.github/images/system-architecture.svg" alt="Agora Voice Coder system architecture">
</picture>

The web client owns RTC/RTM and the visible conversation. FastAPI owns Agora
tokens, Agent lifecycle, Workspace settings, the Task Runtime, and the private
MCP listener. The launcher owns the frontend, backend, ngrok, native picker,
and ACP child-process lifecycle so one shutdown cleans up the complete local
process group. It gives children a graceful SIGTERM shutdown while preserving
the terminal-facing exit status, including `130` for Ctrl-C.

The selected Project Folder is persisted at
`~/Library/Application Support/Agora Voice ACP/workspace.json` unless
`VOICE_ACP_STATE_DIR` overrides the state directory. This compatibility path
does not change when the repository is renamed.

The ACP commands are pinned and launched on demand:

```text
Codex:       npx -y @agentclientprotocol/codex-acp@1.1.7
Claude Code: npx -y @agentclientprotocol/claude-agent-acp@0.70.0
```

Release metadata needs one explicit recheck: the
[`claude-agent-acp` source and package](https://github.com/agentclientprotocol/claude-agent-acp)
identify the adapter code as Apache-2.0, while the current
[ACP Registry](https://agentclientprotocol.com/get-started/registry) labels the
Claude Agent entry `proprietary`. This recipe invokes the package and does not
vendor its source. Before a public release, confirm how the adapter license and
the separately governed Claude service should be described.

See [ARCHITECTURE.md](./ARCHITECTURE.md) for component boundaries and
[docs/ai/L1/02_architecture.md](./docs/ai/L1/02_architecture.md) for the detailed
lifecycle.

## Repo Map

- `web/` — Next.js conversation UI and RTC/RTM lifecycle
- `server/src/agent.py` — Agora voice Agent lifecycle and managed provider setup
- `server/src/managed_ingress/` — authenticated MCP ingress and Work tools
- `server/src/task_runtime/` — durable Work, permissions, cancellation, and delivery
- `server/src/acp_runtime/` — Agent settings, Project Folder state, and shared ACP client
- `scripts/` — setup, verification, and supervised local launcher
- `validation/` — optional architecture-evidence corpus and local results

## Troubleshooting

| Problem | Fix |
| --- | --- |
| Setup or credentials are incomplete | Run `bun run doctor:local` and `bun run preflight:local-agent`. |
| Agent greets but does not start Work | Confirm ngrok is authenticated, then restart and check that the selected Project Folder reports ready. |
| Local Coding Setup remains open | Follow the actionable message and use **Try Again**. Missing configuration and picker cancellation are not errors. |
| Codex requests authentication | Complete the advertised ChatGPT flow, or configure a supported child-process API key. |
| Claude Code requests authentication | Finish sign-in in the Terminal window opened by setup, then return to the browser; the selected folder is retained. |
| Port 3000 is already in use | Stop the exact process using that port, then run `bun run dev:local` again. |
| A previous terminal closed unexpectedly | Restart the launcher; interrupted nonterminal Work is marked failed rather than silently resumed. |
| You need the latest result again | Ask for Work status; the full cleaned inline result remains durable, while spoken delivery is intentionally not replayed into a newer Agent session. |

## Upstream

This recipe is derived from
[`agent-quickstart-python`](https://github.com/AgoraIO-Conversational-AI/agent-quickstart-python).
See [UPSTREAM.md](./UPSTREAM.md) for the pinned base and sync policy.

## License

Released under the [MIT License](./LICENSE).
