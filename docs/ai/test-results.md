# PD Documentation Test Results

Tested: 2026-05-28
Agent: Codex with read-only explorer sub-agents
Repo: `agent-quickstart-python`

## Summary

- Total questions: 6
- Passed: 6
- L1 gaps: 0
- L2 gaps: 0
- Cross-ref issues: 0

The tree passed structural checks and a clean read-only content test. Source-verified drift found during review was fixed before the final content test.

## Results

### Setup & Build

| # | Question | Answer Correct? | Files Read | Level Loaded | Result |
| - | -------- | --------------- | ---------- | ------------ | ------ |
| 1 | How do I install dependencies and run the web + server dev stack? | Yes | `README.md`, `L0`, `L1/01_setup.md`, `L1/05_workflows.md`, `package.json` | L0+L1 sufficient | Pass |
| 2 | Which env vars are required and which process owns each? | Yes | `README.md`, `server/.env.example`, `L1/01_setup.md`, `L1/06_interfaces.md`, `L1/08_security.md`, `server/src/server.py`, `server/src/agent.py`, `web/next.config.ts` | L0+L1 sufficient | Pass |

### Test & Run

| # | Question | Answer Correct? | Files Read | Level Loaded | Result |
| - | -------- | --------------- | ---------- | ------------ | ------ |
| 3 | What does the verification suite cover, and what does `py_compile` not cover? | Yes | `L1/01_setup.md`, `L1/04_conventions.md`, `L2/verification_scripts.md`, `package.json`, `web/scripts/verify-api-contracts.ts`, `web/scripts/verify-local-proxy.ts`, `web/scripts/verify-local-fastapi.ts`, `server/scripts/run_fake_server.py` | L2 required | Pass |

### Conventions

| # | Question | Answer Correct? | Files Read | Level Loaded | Result |
| - | -------- | --------------- | ---------- | ------------ | ------ |
| 4 | How do I add a new backend endpoint exposed to the browser? | Yes | `L1/05_workflows.md`, `L1/06_interfaces.md`, `L2/verification_scripts.md`, `server/src/server.py`, `server/src/agent.py`, `web/next.config.ts`, `web/src/services/api.ts`, `web/scripts/verify-api-contracts.ts`, `web/scripts/verify-local-proxy.ts`, `web/scripts/verify-local-fastapi.ts` | L2 required | Pass |

### Development

| # | Question | Answer Correct? | Files Read | Level Loaded | Result |
| - | -------- | --------------- | ---------- | ------------ | ------ |
| 5 | Where do I change the agent prompt, voice, VAD, and model defaults? | Yes | `L1/02_architecture.md`, `L1/05_workflows.md`, `L1/06_interfaces.md`, `L2/managed_agent_config.md`, `server/src/agent.py` | L2 required | Pass |

### Deep Dive

| # | Question | Answer Correct? | Files Read | Level Loaded | Result |
| - | -------- | --------------- | ---------- | ------------ | ------ |
| 6 | How does token renewal keep RTC and RTM UIDs consistent? | Yes | `L1/02_architecture.md`, `L1/05_workflows.md`, `L1/06_interfaces.md`, `L1/07_gotchas.md`, `L1/08_security.md`, `L2/session_lifecycle.md`, `web/src/components/LandingPage.tsx`, `web/src/components/ConversationComponent.tsx`, `server/src/server.py` | L2 required | Pass |

## Recommended Fixes

- [x] Update `L0_repo_card.md` `Last Reviewed` to 2026-05-28.
- [x] Fix setup sequence and stale Agora SDK dependency wording in `L1/01_setup.md`.
- [x] Align `L1/02_architecture.md` rewrite snippet with `web/next.config.ts`.
- [x] Clarify hook-owned cleanup, FastAPI error detail shape, git conventions, and `py_compile` limits in `L1/04_conventions.md`.
- [x] Replace CI wording with local pre-ship checks in `L1/06_interfaces.md`.
- [x] Correct `AGENT_BACKEND_URL` trailing-slash behavior in `L1/07_gotchas.md`.
- [x] Fix `DEFAULT_GREETING` reference in `L2/managed_agent_config.md`.
- [x] Fix `GET /api/get_config` and current `getConfig({ channel, uid })` examples in `L2/session_lifecycle.md`.
- [x] Fix `py_compile` claims in `L2/verification_scripts.md`.
- [x] Replace stale Vite/Zustand/React Query `web/docs/ARCHITECTURE.md` content with the current Next.js + FastAPI shape.
- [x] Add `docs/ai/RECIPE.md` and mark this repo as an experimental base recipe in `L0_repo_card.md`.
- [x] Add `L1/L2/from_scratch_bootstrap.md` using the same recipe pattern as the Next.js quickstart: compact recipe contract plus detailed baseline implementation map in L2.

## Review Fix Retest

Retested: 2026-05-28

| Finding | Source checked | Docs changed | Result | Notes |
| ------- | -------------- | ------------ | ------ | ----- |
| Stale L0 review date | `git log`, `AGENTS.md` | `docs/ai/L0_repo_card.md` | Pass | Date now reflects this review. |
| `bun run setup` sequence drift | `package.json` | `docs/ai/L1/01_setup.md` | Pass | Setup sequence no longer lists `setup:deps`. |
| `py_compile` overclaimed import coverage | `package.json`, Python `py_compile` behavior | `docs/ai/L1/04_conventions.md`, `docs/ai/L1/L2/verification_scripts.md` | Pass | Docs now say syntax only and point to runtime checks. |
| FastAPI error detail shape | `server/src/server.py` | `docs/ai/L1/04_conventions.md` | Pass | Docs now describe string `detail`. |
| Session lifecycle method/signature drift | `web/src/services/api.ts`, `LandingPage.tsx` | `docs/ai/L1/L2/session_lifecycle.md` | Pass | L2 now uses `GET` and object-form `getConfig`. |
| Agent greeting constant drift | `server/src/agent.py` | `docs/ai/L1/L2/managed_agent_config.md` | Pass | Docs now reference the inline fallback string. |
| Stale web architecture template | `web/package.json`, `web/app/page.tsx`, `web/src/components/LandingPage.tsx`, `web/next.config.ts` | `web/docs/ARCHITECTURE.md` | Pass | Web doc now reflects Next.js App Router and rewrite-only API boundary. |
| Missing recipe artifact | `/private/tmp/ai-devkit/docs/standard/recipe-profile.md`, `README.md`, `server/src/server.py`, `server/src/agent.py`, `web/next.config.ts`, `web/src/services/api.ts` | `docs/ai/RECIPE.md`, `docs/ai/L0_repo_card.md`, `AGENTS.md` | Pass | Repo now declares `Recipe Role: base` and documents extension points, invariants, stable contracts, and internal surfaces. |
| Recipe lacked from-scratch guidance | `../agent-quickstart-nextjs/docs/ai/RECIPE.md`, `../agent-quickstart-nextjs/docs/ai/L1/L2/from_scratch_bootstrap.md`, local source files | `docs/ai/RECIPE.md`, `docs/ai/L1/L2/from_scratch_bootstrap.md`, `docs/ai/L1/L2/_index.md`, `docs/ai/L1/03_code_map.md`, `docs/ai/L1/05_workflows.md` | Pass | Python recipe now follows the Next.js recipe shape and links implementation detail from RECIPE/L1 into L2. |

## Verification Commands

| Command | Result | Notes |
| ------- | ------ | ----- |
| Structural docs checks | Pass | Required files exist; L1 files include purpose + `## Related Deep Dives`; L2 files include `When to Read This`. |
| `bun run verify:backend` | Pass | Required escalation because Python bytecode cache writes outside sandbox roots. |
| `bun run verify:web:api` | Pass | API contract checks passed. |
| `bun run verify:web:proxy` | Pass | Initial sandbox run could not bind local ports; rerun with escalation passed. |
| `bun run verify:web` | Blocked | Doctor and API checks passed after `bun install`; `next build` failed because restricted network could not fetch Google Fonts for `next/font`. |

## 2026-08-20 Project Folder Setup Acceptance

This acceptance used mocked loopback Workspace/runtime responses only. It did
not open the native picker, start ngrok, call Agora, or consume Agora minutes.

| Check | Result | Evidence |
| ----- | ------ | -------- |
| Missing Workspace opens Settings automatically | Pass | The pre-call page rendered a native `dialog` with **Choose a Project Folder** and no start error. |
| Modal contains keyboard focus | Pass | Eight forward Tab presses plus Shift+Tab kept `document.activeElement` inside the dialog. |
| Picker cancellation is silent | Pass | The dialog stayed open without cancellation error copy. |
| Failure remains actionable after cancellation | Pass | **Needs attention**, the bounded runtime error, and **Try Again** remained visible after a cancelled retry. |
| Repeated click guard | Pass | Two synchronous button clicks produced one `POST /api/local/workspace/browse` request. |
| Successful setup handoff | Pass | The dialog closed and focus moved to **Start Conversation** after a mocked ready outcome. |
| Narrow layout | Pass | At 390 by 844 pixels, neither the document nor dialog overflowed horizontally. |
| Browser errors | Pass | No new page errors were observed; the existing Agora logo aspect-ratio development warning remains unrelated. |

## 2026-08-21 Real macOS Local Runtime Acceptance

This acceptance used the real `bun run dev:codex` entry point, macOS folder
picker, and Codex ACP child process. It did not click **Start Conversation**,
start ngrok, create an Agora Agent, or consume Agora minutes.

| Check | Result | Evidence |
| ----- | ------ | -------- |
| Native folder selection | Pass | The `202 + operation_id` flow completed `ready` for `/Users/zhangqianze/Documents/recipe-agent-voice-coder`. |
| Persisted Workspace | Pass | `GET /local/workspace` returned the selected resolved directory and Codex profile. |
| Codex readiness and cwd | Pass | `POST /local/runtime` returned `ready`; the live `codex-acp` process cwd matched the selected Project Folder. No additional login was required on this machine. |
| Agora cost boundary | Pass | Browser network history contained no `/api/startAgent` request, port 4040 remained closed, and no Agora Agent was created. |
| One-command cold start | Pass | From closed ports, `bun run dev:codex` completed preflight and started Next, FastAPI, and the local Codex runtime. |
| Quiet Ctrl-C | Pass after fix | The initial live run exposed Python interrupt tracebacks. The supervisor now sends child SIGTERM while retaining launcher status `130`; the same live flow exited without traceback. |
| Residual cleanup | Pass | After shutdown, ports 3000, 8000, and 4040 were closed and no supervisor, Next, `concurrently`, or `codex-acp` process remained. |

## 2026-08-22 Controlled Voice E2E Attempt

One explicitly authorized Agora conversation used a local prerecorded fake
microphone input. The attempt was stopped without retrying when the input did
not produce a user transcript.

| Check | Result | Evidence |
| ----- | ------ | -------- |
| Agent lifecycle | Pass | The live Agent joined the RTC channel, the client reported connected, and `POST /api/stopAgent` returned 200. |
| Managed MCP discovery | Pass | The public tunnel became available and the backend processed the authenticated `ListToolsRequest` handshake. |
| Greeting delivery | Pass | The transcript received the Agent greeting, **Voice coding is ready.** |
| Synthetic microphone input | Failed | Agora reported `AUDIO_INPUT_LEVEL_TOO_LOW`; the prerecorded request never appeared as a user transcript. |
| Voice to Work routing | Not proven | No new Work receipt was created, so this attempt does not prove Managed LLM tool selection, MCP `start_work`, or Codex execution. |
| Completion notification | Not proven | Without a Work receipt, proactive completion delivery could not run. |
| Cost containment | Pass | Exactly one conversation was created; the failed input was not retried. |
| Cleanup | Pass | The Agent leave request succeeded; after launcher shutdown, ports 3000, 8000, and 4040 were closed with no related process remaining. |

## 2026-08-22 Real Microphone Voice E2E Acceptance

A separately authorized follow-up used the selected Project Folder, the real
Chrome microphone, the Managed voice LLM, the public MCP ingress, and the local
Codex ACP runtime. An initial in-app-browser Agent was stopped immediately after
the RTC client failed to join with an SDP parsing error; the successful Chrome
conversation was then started and stopped explicitly.

| Check | Result | Evidence |
| ----- | ------ | -------- |
| Real microphone and transcription | Pass | Chrome reached **RTC connected** and transcribed the user's request, **Tell me the root folder file structure.** |
| Managed MCP discovery | Pass | Before the Agent joined, the backend accepted the authenticated `ListToolsRequest` handshake over the ngrok-backed MCP ingress. |
| Voice to Work routing | Pass with retry | The first turn did not call the tool and asked what to do. After the user clarified **I'm saying just list them**, the Agent acknowledged the queued request and created Work `98efd426fecd4b8d8cc6b99d543f4511` with objective **List the root folder file structure**. |
| Local Codex execution | Pass | The Work moved from `running` to `completed` and returned the real `recipe-agent-voice-coder` root structure from the selected Project Folder. |
| Completion notification | Pass | The Work moved through `sending` to `accepted`; the backend's Agora `/speak` request returned 200 and the completion appeared in the live Agent transcript. `accepted` proves API acceptance, not playback completion. |
| Result quality | Needs follow-up | The spoken result included an internal Codex skills-context warning and a long directory tree. The end-to-end transport works, but completion projection should suppress runtime warnings and better bound voice output. |
| Cost containment | Pass with caveat | The failed in-app-browser Agent was left immediately after the RTC join error. One additional Chrome conversation completed the authorized test and was stopped as soon as delivery was verified. |
| Cleanup | Pass | Both Agent leave requests returned 200. After launcher shutdown, ports 3000, 8000, and 4040 were closed and no supervisor, Next, ngrok, or `codex-acp` process remained. |

## 2026-08-22 Managed Completion Re-entry Offline Verification

This implementation check used only fake ACP and Agora session boundaries. It
did not start ngrok, create an Agora Agent, open a microphone, or consume Agora
conversation minutes.

| Command | Result | Evidence |
| --- | --- | --- |
| `PYTHONPATH=src pytest tests/acp_runtime/test_acp_client.py -q` | Pass | 21 tests; the exact leading Codex skills-context notice is removed while unrelated and non-leading warnings remain. |
| `PYTHONPATH=src pytest tests/task_runtime -q` | Pass | 42 tests; completed Work stores fixed fallback speech plus cleaned inline detail, and compact JSON envelopes remain within 8 KiB under UTF-8 and escape expansion. |
| `PYTHONPATH=src pytest tests/managed_ingress/test_agent_bridge.py -q` | Pass | 11 tests; the exact active Work session receives the approved Think action values, and known HTTP rejection remains distinct from ambiguous SDK failure. |
| `PYTHONPATH=src pytest tests/managed_ingress -q` | Pass | 61 tests; successful, unavailable, rejected, ambiguous, failed, cancelled, Workspace-mismatch, shutdown, and duplicate-notification paths use the approved delivery states. |

| Live acceptance question | Status | Required observation |
| --- | --- | --- |
| Conversational completion quality | Not run — separately authorized Agora session required | The response should sound like a natural continuation and provide one or two useful conclusions. |
| Speaking interruption and recovery | Not run — separately authorized Agora session required | A completion arriving during speech should interrupt and recover coherently. |
| Synthetic input transcript visibility | Not run — separately authorized Agora session required | The `LOCAL_WORK_COMPLETED` JSON must not become an unexplained visible user message. |
| Recursive MCP behavior | Not run — separately authorized Agora session required | Completion re-entry must not create another `start_work` call. |

Offline checks do not establish any of these four live qualities. A normal
`/think` return means only that Agora accepted the injected input; it is not
generated-text, TTS-start, playback-complete, or user-heard evidence.
