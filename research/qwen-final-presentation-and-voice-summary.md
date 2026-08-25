# Qwen final presentation compared with local voice summary design

Research date: 2026-08-22<br>
Qwen source inspected: [`QwenAudio/qwen-audio-agent@7b363f668932e85fafbd2a23b24d60caba7ce4d9`](https://github.com/QwenAudio/qwen-audio-agent/tree/7b363f668932e85fafbd2a23b24d60caba7ce4d9) (`main` at inspection time)<br>
Local comparison point: `recipe-agent-voice-coder@c843e08876a1b8f99dabf16af0b07efe4283c8dc`

## Conclusion

Qwen already uses the same important abstraction we are considering: its
backend **coordinator** returns a structured `presentation` with separate
`speech` and optional `inline` fields. It does **not** normally send a project
Agent's raw full answer directly to speech. For delegated project work, the
target ACP Agent itself does not emit this pair; Qwen gives its raw result to
the coordinator in a separate finalization turn.

Qwen then goes one step further: it injects the backend-authored `speech`
material into Qwen Realtime and asks the Realtime model to produce another
context-aware spoken response. Therefore Qwen's design has two semantic
presentation stages:

1. the backend coordinator turns the work result into `speech` plus optional
   `inline` content;
2. the Realtime model adapts the `speech` material to the live conversation.

For this recipe, the first stage is worth copying; the second is not currently
necessary. Codex can author the one- or two-sentence voice summary in the same
work response, while Agora `session.say(...)` delivers it deterministically.
The complete result should remain available to Activity independently.

## What Qwen stores

Qwen's coordinator response schema requires this shape:

```json
{
  "work_id": "request id",
  "state": "completed",
  "mode": "respond",
  "presentation": {
    "speech": "concise result material",
    "inline": null
  }
}
```

`speech` is required. `inline` is also required as a field but may be `null`; if
present, it is a typed object containing a title, `markdown|code|link` format,
and content. The schema and normalization are implemented in the coordinator,
not in the voice gateway ([coordinator schema and normalization](https://github.com/QwenAudio/qwen-audio-agent/blob/7b363f668932e85fafbd2a23b24d60caba7ce4d9/server/src/agent/coordinator.mjs#L7-L116)). The coordinator prompt explicitly says that
`presentation` is the final user-facing result and that `inline` may carry
Markdown, code, or links ([coordinator output contract](https://github.com/QwenAudio/qwen-audio-agent/blob/7b363f668932e85fafbd2a23b24d60caba7ce4d9/server/src/agent/coordinator.mjs#L211-L234)).

After parsing, Qwen returns `decision.presentation.speech` as the Task's
canonical `content` and stores the whole presentation under metadata
([coordinator result envelope](https://github.com/QwenAudio/qwen-audio-agent/blob/7b363f668932e85fafbd2a23b24d60caba7ce4d9/server/src/agent/coordinator.mjs#L278-L315)). `TaskManager` consequently stores the speech
material in `task.result` and the optional inline material in
`task.resultMetadata.presentation.inline`
([task completion persistence](https://github.com/QwenAudio/qwen-audio-agent/blob/7b363f668932e85fafbd2a23b24d60caba7ce4d9/server/src/task/task-manager.mjs#L642-L703)). The gateway sends the optional inline object to the
shared timeline separately from notification speech
([inline timeline delivery](https://github.com/QwenAudio/qwen-audio-agent/blob/7b363f668932e85fafbd2a23b24d60caba7ce4d9/server/src/voice/realtime-gateway.mjs#L944-L968)).

This means Qwen does **not** guarantee a “raw full result plus summary” pair.
The backend Agent decides whether to create `inline`, and `inline` may be null.
For delegated work, Qwen obtains the target Session's result to create the
presentation, but the public Work result is the presentation speech; this path
does not copy the raw target result into the public Work receipt. Qwen's
architecture document also defines Work as a delivery receipt rather than a
mirror of the backend's internal state
([Work and final presentation model](https://github.com/QwenAudio/qwen-audio-agent/blob/7b363f668932e85fafbd2a23b24d60caba7ce4d9/docs/architecture.md#L166-L231)).

## Where the extra LLM turns occur

For work completed directly in the coordinator Session, the coordinator's
normal task turn must return the structured presentation. There is no separate
backend summarizer request after that turn.

For work delegated to a third-layer backend Session, Qwen waits for the raw
target result and then sends that verified result back to the coordinator in a
new prompt, explicitly asking it to produce the final `presentation`
([delegated result finalization](https://github.com/QwenAudio/qwen-audio-agent/blob/7b363f668932e85fafbd2a23b24d60caba7ce4d9/server/src/agent/acp-backend-adapter.mjs#L1139-L1152),
[second coordinator turn](https://github.com/QwenAudio/qwen-audio-agent/blob/7b363f668932e85fafbd2a23b24d60caba7ce4d9/server/src/agent/acp-backend-adapter.mjs#L1232-L1268)). That is a real additional backend LLM turn.

After either path completes, the voice gateway formats `task.result` into a
synthetic result event and injects it as a Realtime conversation item. It then
requests a response with `tool_choice: "none"`
([Realtime result injection](https://github.com/QwenAudio/qwen-audio-agent/blob/7b363f668932e85fafbd2a23b24d60caba7ce4d9/server/src/voice/realtime-provider.mjs#L393-L414),
[DashScope response request](https://github.com/QwenAudio/qwen-audio-agent/blob/7b363f668932e85fafbd2a23b24d60caba7ce4d9/server/src/voice/providers/dashscope.mjs#L94-L111)). The Realtime prompt tells the model to treat the result as factual
material, summarize or merge it according to the conversation, avoid reading
paths and URLs, and speak only the key points when detailed results are already
on screen
([result speech instructions](https://github.com/QwenAudio/qwen-audio-agent/blob/7b363f668932e85fafbd2a23b24d60caba7ce4d9/server/src/voice/frontend-tools.mjs#L248-L256)).

Thus Qwen does not use direct TTS for final completion announcements. Its final
spoken wording is authored by a second, context-aware Realtime response even
though the backend has already supplied `presentation.speech`.

## Bounds and truncation

Qwen has several transport/context bounds, but it does not enforce a strict
one- or two-sentence speech contract:

- a delegated backend result is sliced to 12,000 JavaScript code units before
  being sent to the coordinator for final presentation
  ([delegation result envelope](https://github.com/QwenAudio/qwen-audio-agent/blob/7b363f668932e85fafbd2a23b24d60caba7ce4d9/server/src/agent/acp-backend-adapter.mjs#L1139-L1149));
- the announcement manager batches at most eight Work events and bounds the
  formatted Realtime input to 6,000 Unicode code points by default
  ([announcement limits and batching](https://github.com/QwenAudio/qwen-audio-agent/blob/7b363f668932e85fafbd2a23b24d60caba7ce4d9/server/src/voice/announcement/announcement-manager.mjs#L1-L27),
  [bounded batch construction](https://github.com/QwenAudio/qwen-audio-agent/blob/7b363f668932e85fafbd2a23b24d60caba7ce4d9/server/src/voice/announcement/announcement-manager.mjs#L235-L266));
- oversized announcement text is hard-truncated with a suffix saying the full
  event remains in the task record
  ([truncation implementation](https://github.com/QwenAudio/qwen-audio-agent/blob/7b363f668932e85fafbd2a23b24d60caba7ce4d9/server/src/voice/announcement/announcement-manager.mjs#L376-L402)).

The `presentation.speech` schema itself has no maximum length, and
`normalizePresentation()` does not shorten it. The 6,000-character limit is a
Realtime context safety bound, not a good spoken-length budget. Qwen primarily
relies on the backend coordinator and Realtime instructions to make the result
concise.

## Runtime warnings and diagnostics

No dedicated filter for Codex skills-context warnings or generic runtime
notices was found in the current final-result path.

Qwen gets most of its isolation from structure. The ACP process client joins
all `agent_message_chunk` text into one response
([ACP text collection](https://github.com/QwenAudio/qwen-audio-agent/blob/7b363f668932e85fafbd2a23b24d60caba7ce4d9/server/src/agent/acp-process-client.mjs#L287-L301),
[prompt result assembly](https://github.com/QwenAudio/qwen-audio-agent/blob/7b363f668932e85fafbd2a23b24d60caba7ce4d9/server/src/agent/acp-process-client.mjs#L436-L515)), but the coordinator parser extracts the structured JSON object and uses only
`presentation.speech` and `presentation.inline`
([payload parser](https://github.com/QwenAudio/qwen-audio-agent/blob/7b363f668932e85fafbd2a23b24d60caba7ce4d9/server/src/agent/acp-backend-session-utils.mjs#L13-L42)). Text outside a valid JSON object therefore normally does not become speech.

However, parsing has a permissive fallback: if no valid presentation is found,
`normalizePresentation()` uses the raw coordinator content as `speech`
([fallback behavior](https://github.com/QwenAudio/qwen-audio-agent/blob/7b363f668932e85fafbd2a23b24d60caba7ce4d9/server/src/agent/coordinator.mjs#L98-L115)). Qwen also has no Codex-specific process-output sanitizer in its backend
profile
([Codex backend profile](https://github.com/QwenAudio/qwen-audio-agent/blob/7b363f668932e85fafbd2a23b24d60caba7ce4d9/server/src/agent/backends/codex.mjs#L1-L54)). Therefore the structured contract materially reduces warning leakage, but
does not make it impossible when structured parsing fails.

## Reconnect, retry, and acknowledgement

Qwen persists notification state separately from Work state. A terminal Work
sets its notification to `pending`; a voice gateway must atomically claim it as
`delivering`, renew the claim, and later confirm or release it. Persisted stale
`delivering` claims are reset to `pending` on restart
([terminal notification creation](https://github.com/QwenAudio/qwen-audio-agent/blob/7b363f668932e85fafbd2a23b24d60caba7ce4d9/server/src/task/task-manager.mjs#L680-L703),
[claim lifecycle](https://github.com/QwenAudio/qwen-audio-agent/blob/7b363f668932e85fafbd2a23b24d60caba7ce4d9/server/src/task/task-manager.mjs#L831-L938)).

The announcement manager waits for a ready Realtime frontend, renews leases,
retries with exponential backoff, avoids injecting the same result context
twice, and releases the claim after bounded retries
([announcement delivery and retry](https://github.com/QwenAudio/qwen-audio-agent/blob/7b363f668932e85fafbd2a23b24d60caba7ce4d9/server/src/voice/announcement/announcement-manager.mjs#L202-L365)). Provider reconnect triggers a new claim/flush, while a full voice-client
disconnect releases active claims so another connection for the same owner can
recover them
([provider reconnect recovery](https://github.com/QwenAudio/qwen-audio-agent/blob/7b363f668932e85fafbd2a23b24d60caba7ce4d9/server/src/voice/realtime-gateway.mjs#L1492-L1555),
[client disconnect cleanup](https://github.com/QwenAudio/qwen-audio-agent/blob/7b363f668932e85fafbd2a23b24d60caba7ce4d9/server/src/voice/realtime-gateway.mjs#L2125-L2148)).

There is a documentation/code mismatch worth preserving in our comparison.
The architecture document says delivery is marked after playback finishes, but
current code confirms an announcement when the active output client reports
that playback **starts**. A user interruption after playback begins is also
treated as delivered/dismissed
([playback-start confirmation](https://github.com/QwenAudio/qwen-audio-agent/blob/7b363f668932e85fafbd2a23b24d60caba7ce4d9/server/src/voice/realtime-gateway.mjs#L668-L703)). Qwen therefore proves that playback began, not that the full message was
heard.

## Implications for this recipe

### Copy

1. **Use an explicit final-presentation contract.** Qwen validates the design
   boundary: screen material and spoken material are different products of the
   backend Agent, not one string reused everywhere.
2. **Have the executing Agent author the semantic summary.** It knows what
   mattered and can write a meaningful one- or two-sentence conclusion without
   a separate summarizer model.
3. **Parse only the explicitly delimited/structured speech field.** Runtime
   notices outside that field should never enter speech.
4. **Keep delivery state independent from Work completion.** A completed Work
   may still need delivery, and a successful submission is not proof that the
   whole message was heard.

### Be stricter than Qwen

1. **Always preserve the complete clean result for Activity.** Unlike Qwen's
   nullable `inline`, this recipe's Activity is the durable place for the full
   result. The voice summary must not replace it.
2. **Enforce a speech budget suitable for listening.** One or two sentences,
   with a small soft budget and a 512-byte delivery ceiling, is more appropriate
   for direct `session.say(...)` than Qwen's 6,000-character Realtime context
   limit.
3. **Fail closed.** If the summary block is absent, malformed, or oversized,
   say a fixed completion fallback and keep the full result in Activity. Do not
   fall back to speaking raw ACP output as Qwen can.
4. **Do not add Qwen's Realtime rewrite turn.** Qwen owns its Realtime socket,
   response correlation, audio queue, and playback receipts. This recipe uses
   Agora Managed LLM plus deterministic `session.say(...)`; adding another LLM
   merely to rewrite an already-authored summary would add latency, cost, and a
   new failure point.

## Recommended local contract

The proposed contract remains sound, with one refinement learned from Qwen:
model it internally as a typed `FinalPresentation`, even if the cross-ACP text
encoding initially uses a simple `<voice_summary>` delimiter.

```text
FinalPresentation
  inline: complete cleaned Markdown result
  speech: one or two informative plain-language sentences
```

The parser should remove the summary block from `inline`, validate `speech`,
and never derive speech from arbitrary leading text. Known Codex runtime notices
may be precisely removed from `inline` as a separate cleanup, but the voice
safety boundary should remain “only validated summary text can be spoken.”
