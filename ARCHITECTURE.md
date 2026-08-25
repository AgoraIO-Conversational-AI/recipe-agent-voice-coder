# Agora Conversational AI Demo — Architecture

This quickstart keeps the web UI and backend responsibilities separate. The Next.js app owns the browser-facing `/api/*` URLs, and `next.config.ts` rewrites them to the Python FastAPI service that owns token generation and agent lifecycle.

## Python-Backed Request Flow

```
Browser
  ↓
Next.js app
  ↓
/api/* rewrites through AGENT_BACKEND_URL
  ↓
FastAPI service
  ↓
Agora Cloud Services
```

- `web` owns the browser UI and the `/api/*` entrypoints
- `server` owns the actual token generation and agent start/stop logic
- this is the mode used by `bun run dev`

## Local Coding Agent Foundation

`bun run dev:local` is a separate local-development entry point. It starts
FastAPI and Next on loopback interfaces and does not start an Agora agent until
the user presses **Start conversation**. It also does not start ngrok.
Its preflight checks the certified macOS Apple Silicon platform, Bun/Node/Python,
and usable Agora configuration without printing credential values.

```text
Browser Settings gate
  -> Next /api/local/* rewrites
  -> loopback FastAPI /local/*
  -> WorkspaceService (durable one-folder scope)
  -> LocalRuntimeCoordinator
  -> one ACP child process + one ACP session
  -> TaskRuntime -> SQLite WorkStore + one FIFO ACP prompt worker
```

The browser opens Local Coding Setup automatically when no valid Project Folder
exists. Agent selection is remembered independently in `agent-settings.json`;
the Project Folder remains in `workspace.json`. The native macOS picker is
invoked by the loopback backend, not the browser. Setup uses a native modal plus focus guards, so keyboard focus
cannot reach the pre-call page while setup is blocking. Picker cancellation
returns to the Settings gate without an error. A successful selection activates ACP, closes Settings automatically,
and focuses **Start Conversation**; bounded activation failures remain in
Settings with a retry action instead of being collapsed into a folder-selection
error. `LandingPage` owns the initial checking gate and focus handoff, while
`LocalCodingSetup` owns Agent choice, folder selection, authentication retry,
cancellation, and failure presentation.
The selected resolved directory is persisted in
`~/Library/Application Support/Agora Voice ACP/workspace.json` by default (or
under `VOICE_ACP_STATE_DIR`). The Project Folder is session context, not a
filesystem sandbox.

`LocalRuntimeCoordinator` permits at most one session. It starts only after a
valid folder exists, closes an old session before opening a replacement, and
returns `configuration_required`, `starting`, `authentication_required`,
`ready`, or `failed` without exposing ACP protocol data.

Ordinary FastAPI lifespan startup never starts ACP, even when a saved Workspace
exists. The local web flow explicitly activates saved state with
`POST /api/local/runtime`; `GET /api/local/runtime` remains read-only. Next
publishes `/api/local/*` rewrites only for an explicit development opt-in, a
loopback backend URL, and a non-production Next process.

`LocalAcpClient` owns the shared ACP child-process boundary. `AgentDefinition`
profiles select either `@agentclientprotocol/codex-acp@1.1.7` or
`@agentclientprotocol/claude-agent-acp@0.70.0`; both commands run through `npx`
without a shell. Codex initializes with `INITIAL_AGENT_MODE=agent`, tries
reusable credentials first, and handles an ACP-advertised ChatGPT method.
Claude Code reuses existing authentication; a typed authentication-required
state lets loopback-only `ClaudeAuthService` open one macOS Terminal with a
fixed official login command and poll a fixed status command for up to 120
seconds. The browser cannot provide commands or receive credential output.
Environment pass-through is allowlisted per profile. A custom compatible ACP
command is accepted only as a JSON argv array and changes neither the selected
identity nor its authentication behavior.

The Task Runtime Core starts only in the opted-in local app. It marks leftover
nonterminal Work failed before accepting new Work, persists acceptance before
queueing, executes one ACP prompt at a time, stores safe activity and a
backend-neutral Final Presentation, and blocks Project Folder changes while
Work or a permission is nonterminal. Shutdown stops Task Runtime before closing
the ACP session and SQLite connection.

The opted-in local app also owns a second, dedicated loopback ASGI listener:

```text
Managed Voice LLM -> ngrok HTTPS -> bearer-authenticated /mcp/
  -> ManagedWorkTools -> TaskRuntime -> codex-acp stdio
```

Each active Agora Agent receives one in-memory bearer bound to its exact Agent
ID, Workspace ID, and Workspace generation. Agent stop revokes it first. The
MCP listener exposes only four Work tools and is never mounted into the
lifecycle FastAPI app. ngrok starts lazily when an Agent is prepared after ACP
readiness and remains in the launcher's process group for forced cleanup.
The Local Launcher Supervisor converts the first terminal shutdown request to
child SIGTERM so Python and web children exit quietly, while its own status
continues to distinguish SIGINT (`130`), SIGTERM (`143`), and SIGHUP (`129`).

Agora may initialize and discover MCP tools before Agent creation returns the
real Agent ID. The prepared bearer permits only that side-effect-free handshake;
all Work tool calls remain closed until exact Agent activation.

The Managed Work system message treats the already-selected Project Folder and
registered tools as available capabilities. It delegates Workspace-dependent
natural-language objectives through `start_work` without exposing the path or
enumerating task categories; the MCP tool description carries the same
contract.

The current experimental completion prototype has completed one partial live
Agora check: delivery and conversational output worked, but the assistant
transcript contained Markdown while TTS did not read it. The static completion
rule now requires plain spoken sentences with no Markdown output; that change
and interruption recovery remain pending live acceptance. After Task Runtime
commits targeted Work, an in-process delivery coordinator
revalidates the exact originating Agent and Workspace and claims the durable
pending result. Completed Work stores a cleaned full inline result plus the
fixed fallback `The work is done.`; the coordinator creates an at-most-8-KiB
`LOCAL_WORK_COMPLETED` JSON envelope and calls that Agent session's Think API
with listening `inject`, thinking/speaking `interrupt`, and user-interruptible
output. The current Managed LLM converts the data into a short response using
the live conversation and is instructed to emit plain spoken text without
Markdown formatting. A normal return records input `accepted`, not generated
text or playback. Only a definite HTTP rejection may use one APPEND Speak
fallback. Ambiguous submission records `delivery_unknown` and is not retried.
Failed Work continues through bounded APPEND speech, cancelled Work stays
silent, and missing/stopped sessions or Workspace mismatch stay
`pending_delivery`. SSE/UI, playback receipts, batching, and reconnect replay
remain separate follow-ons.

## Shared Conversation Flow

### 1. Connection

```
Frontend: GET /api/get_config
  → Generate Token007 config for a user UID, agent UID, and channel
  → Frontend joins RTC and logs into RTM
```

### 2. Agent Start

```
Frontend: POST /api/startAgent { channelName, rtcUid, userUid }
  → Build agent session
  → Scope remote_uids to the requesting user
  → Start session and return agent_id
```

### 3. Conversation

```
User audio → RTC
  → Managed ASR, LLM, and TTS pipeline
  → Agent audio + RTM transcript events
  → UIKit transcript and visualizer in the web app
```

### 4. Agent Stop

```
Frontend: POST /api/stopAgent { agentId }
  → Stop session directly or through stateless fallback
  → Client cleans up RTC and RTM state
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/get_config` | GET | Generate connection config (Token007, channel, UIDs) |
| `/startAgent` | POST | Start the agent session |
| `/stopAgent` | POST | Stop the agent by `agent_id` |

The following derivative extension routes are loopback-only and are not part of
the reusable three-route quickstart contract:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/local/workspace` | GET | Return Project Folder profile, scope, and state |
| `/local/workspace` | PUT | Resolve, persist, and activate an existing Project Folder |
| `/local/workspace` | DELETE | Close local ACP and clear the saved selection |
| `/local/workspace/browse` | POST | Start one backend-owned native macOS folder picker operation and return `202` |
| `/local/workspace/browse/{operation_id}` | GET | Poll the current picker operation until ready, cancelled, or failed |
| `/local/agent` | GET | Return available Agent profiles and the remembered selection |
| `/local/agent` | PUT | Switch the Agent and activate it against the current Project Folder |
| `/local/auth/claude-code` | GET | Return bounded Claude Code authentication readiness |
| `/local/auth/claude-code` | POST | Open or reuse the single fixed macOS Terminal login flow |
| `/local/runtime` | GET | Return safe local ACP readiness state without starting ACP |
| `/local/runtime` | POST | Explicitly activate ACP for a valid saved Workspace |

Frontend calls these as `/api/*`. Next rewrites those calls to `AGENT_BACKEND_URL`; the Next app does not run token or AgentKit logic in-process.

## Authentication

Token007 (AccessToken2) — generated from `AGORA_APP_ID` + `AGORA_APP_CERTIFICATE` only. No API_KEY/API_SECRET needed. The SDK handles token generation and API auth internally.

## Managed-path evidence ingress

The Managed Voice LLM evidence harness adds two ASGI surfaces in one local process so they can share process-local validation state:

```text
Browser -> loopback FastAPI:8000 -> agent lifecycle and local seed controls
Agora Cloud -> ngrok -> public ASGI:8001 -> authenticated /mcp only
```

`server/src/architecture_validation/public_server.py` constructs the public surface. It contains the Streamable HTTP MCP app and no token, agent lifecycle, seed, diagnostics, or report routes. Every MCP request requires a runner-issued, per-session capability. `server/src/server.py` mounts the validation admin router, whose handlers reject non-loopback clients.

The live runner must own both listeners in one process. Running the public app separately would create another in-memory capability registry and is unsupported. The four MCP tools operate on synthetic receipts only; they do not start ACP, coding agents, commands, or file operations.

The existing authenticated Agent session replaces the complete `llm.system_messages` list with the base prompt plus at most one bounded current permission. The same session announces the question with one `say(..., priority="APPEND", interruptable=True)` call. No separate model-provider credentials or public LLM callback are required.

`server/src/architecture_validation/config.py` reads the versioned evidence controls once. `server/src/agent.py` always builds the Agora-managed `OpenAI` provider with the prompt, model controls, history, MCP endpoint, bearer header, allowed tools, STT, TTS, turn detection, and session settings.

The interactive runner owns both Uvicorn listeners, rotates the active scenario on the same per-session capability, seeds only synthetic state, and appends recursively redacted JSONL evidence. Invalidated operator/setup attempts remain in evidence under unique IDs and are rerun. The harness is optional and consumes live Agora usage when run.

## Verification Boundary

The offline suite verifies both profiles, fake ACP protocol behavior, separate
Agent and Workspace persistence,
loopback guards, rewrite contracts, fake FastAPI proxying, and web build output.
It does not prove that `npx` can download/run the pinned ACP package, that a
browser can complete provider authentication, that the native picker works on a
developer machine, or that an Agora conversation/ngrok ingress succeeds. Run
those live/manual checks only with the appropriate credentials and authorization.

## Detailed Documentation

- [docs/ai/L1/02_architecture.md](./docs/ai/L1/02_architecture.md) — web ↔ FastAPI topology, rewrites, lifecycle
- [docs/ai/L1/03_code_map.md](./docs/ai/L1/03_code_map.md) — where code lives under `web/` and `server/`
- [AGENTS.md](./AGENTS.md) — AI agent development guide
- [README.md](./README.md) — Quick start, configuration, deployment
