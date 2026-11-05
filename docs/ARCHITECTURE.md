# Architecture

How the pieces fit, which events the mod listens to, what state it keeps, and what happens when something fails.

## Who does what

| Layer | Piece | Job | What it does not do |
| --- | --- | --- | --- |
| Judgment | Rule in `CLAUDE.md` + `wrap-up` skill | Decide whether the next task needs the context; leave the handoff; write the marker only when everything is safe | Compact (it can't) |
| Action | The mod (`plugin/hooks/register.ts`) | See the marker, apply the filters (session, floor, activity) and compact | Judge whether it's time to close; write the handoff |
| Reminder | The mod, on `prompt.submit` | Ask the model the question when the context is high, and tell it when a message cancels a compaction | Compact, or decide anything |
| Memory on disk | The mod, on `classic.PostCompact` | Save every compaction summary | Decide anything |
| Continuity | The mod, on `classic.SessionStart` (`compact`, `clear`) | Put the handoff back into the context | Write the handoff |
| Safety net | Claude Code's own auto-compact | Compact when the window fills up | Nothing new: left as it is |

The split comes from one constraint in Claude Code: no hook, no skill and not the model can run `/compact`. A mod can, with `$.command.run({ command: 'compact' })`, which queues `/compact` in the session as if the user typed it. (The mod API also has `$.session.compact()`, but in the desktop app, where every session runs headless, engine 2.1.309 always rejects it; see [DECISIONS.md](DECISIONS.md#d12-compact-by-queueing-compact-not-with-sessioncompact).) The judgment stays with the model because it is the only one that knows whether a task is done.

Until 0.3.0 the summary and the handoff were two Python hooks in `settings.json`. Since 0.4.0 the mod handles both events itself ([D15](DECISIONS.md#d15-one-plugin-no-python-no-settingsjson)), so the whole thing is one plugin.

## An automatic close, step by step

```mermaid
sequenceDiagram
    autonumber
    participant M as Model
    participant S as wrap-up skill
    participant D as Disk
    participant Mod as cc-autocompact mod
    participant CC as Claude Code

    M->>S: Task done, and the next one doesn't need this context
    S->>D: Updates .claude/HANDOFF.md
    S->>D: Checks it was written
    S-->>M: Short summary + "Ready to compact."
    CC->>Mod: classic.Stop (last_assistant_message), the marker fallback
    CC->>Mod: turn.complete (reason = answer)
    Mod->>D: Copies the handoff into ~/.claude/cc-autocompact/handoffs/
    Mod->>Mod: Marker? enabled? session allowed? context above the floor?
    Mod->>CC: Toast: "compacting in a moment"
    Note over Mod: Waits delay_ms (1.5 s).<br/>A message or a new turn cancels it.
    Mod->>CC: $.command.run({ command: 'compact', args: compact_instructions })
    Note over CC: /compact runs as soon as the session is idle,<br/>as if the user typed it
    CC->>Mod: classic.PostCompact (compact_summary)
    Mod->>D: Saves the summary in compaction-summaries/<project>/
    CC->>Mod: classic.SessionStart (source = compact)
    Mod->>D: Reads its own copy of the handoff
    Mod-->>CC: additionalContext: the handoff
    Mod->>D: Adds a line to compactions.jsonl
    Mod->>CC: Toast: "Compacted: Xk to Yk"
```

With `/compact-now` it starts earlier: the mod sets the `wrapping` phase, runs the skill with `$.command.run` (first as `wrap-up`, then as `cc-autocompact:wrap-up`, since a plugin's skill may only answer to its namespaced name) and, when that turn ends, compacts without looking at the floor or the session list. If neither name runs, the mod asks for the skill in plain words with `$.prompt.submit` (the host refuses text that starts with `/`).

## Events the mod listens to

| Event | What it does |
| --- | --- |
| `session.start` | Registers `/compact-now` and `/cc-doctor` and clears "scheduled", "compacting" and "turn running" (timers don't survive a reload). |
| `prompt.submit` | Bumps the `gen` counter: cancels any compaction still waiting out its delay (a `cancelled` line with the message's origin kind, never its text, and one retry owed). If that happened, or the context crossed a new band and the message isn't inside a turn, it adds a fixed note as `context` ([D19](DECISIONS.md#d19-size-may-ask-it-never-decides)). |
| `turn.start` | Main thread only: marks a turn as running, bumps `gen`, zeroes the turn's tool-call count, clears what `Stop` saw and allows a new compaction (unless the turn is the `/compact` itself). A compaction still waiting out its delay is cancelled here (a `cancelled` line, the note owed, one retry owed). |
| `tool.call` | Main thread only: counts the running turn's tool calls, so a retry only follows a short turn. Never changes the call. |
| `classic.Stop` | Main thread only (no `agent_id`): records whether `last_assistant_message` ends with the marker. Read only if `turn.complete` arrives without text. |
| `session.compact` | Main thread only, not `precompute`, not a veto: for the mod's own `/compact`, keeps the `tokensAfter` the result reports; for any other (auto-compact, a typed `/compact`), writes an `app_compaction` line with its `trigger`, marks "just compacted" and drops any retry owed. |
| `session.measure` | If a logged compaction is still missing its `context_after`, the first figure below its `context_before` is appended as a `context_after` line. |
| `classic.PostCompact` | Main thread only: writes `compact_summary` to `<summaries>/<project folder>/<UTC time>_<session>.md`. Every compaction, whoever started it. |
| `classic.SessionStart` | `source` `compact` or `clear`, main thread only: returns the mod's own copy of this project's handoff as `additionalContext`. It never reads the project's file here. |
| `turn.complete` | Main thread only: records the time of the last model response, fills a missing `context_after`, and if a `/compact` is queued, marks it done; otherwise looks for the marker. With the marker, copies the handoff into the mod's folder, builds a `PolicyInput` and asks the policy (today `decideStub`: marker, floor, never twice in a row) whether to schedule the compaction; the decision goes to the log. Without the marker, a retry owed is scheduled if the turn was a short, clean answer. In debug mode, writes the decision and the policy's input. |
| `command.run` (`compact-now`) | Starts a wrap-up the user asked for. |
| Idle timer (after each main-thread answer) | After `idle_minutes` with no message or turn: asks the policy (`trigger: 'idle'`), which may compact, ask the model once (`idle_mode` `ask`) or wait. |
| Pacing (in `prompt.submit`) | For an origin that is not a person: near the 5-hour or weekly limit, a fixed note beside the message; a deferred window gets one resume prompt after it resets. A person's message is never looked at. |
| `command.run` (`cc-doctor`) | Returns a read-only plain-text report: config, log, last week's events, rate limits, context, warnings. |

## Where it reads and writes

The mod works out Claude Code's folder from `CLAUDE_CONFIG_DIR`, else the home folder (`USERPROFILE` when it is a Windows drive path, since `HOME` can be a Git Bash path there), plus `.claude`. Its own files go in `<that>/cc-autocompact/`, outside the plugin, so an update never touches them. With no home folder at all, it falls back to the plugin folder.

| File | By | When |
| --- | --- | --- |
| `.claude/HANDOFF.md` (or the `Handoff:` path in `CLAUDE.md`) | `wrap-up` skill | Every wrap-up |
| `~/.claude/cc-autocompact/config.json` | You, optional | Read on every use |
| `~/.claude/cc-autocompact/handoffs/<hash>.json` | Mod | Every main-thread turn that ends with the marker: its copy of the project's handoff |
| `~/.claude/compaction-summaries/<project>/<date>_<time>Z_<id>.md` (or `summaries_dir`, inside `~/.claude`) | Mod | Every compaction (manual, automatic, or from the mod) |
| `~/.claude/cc-autocompact/compactions.jsonl` (or `log_file`, a `.jsonl` inside that folder) | Mod | Every decision on a marker or a wrap-up, and every scheduled, cancelled, refused, retried, finished, lost or app-started compaction: one append-only line each, never message text |
| `~/.claude/cc-autocompact/events/<YYYY-MM>/<session id>.jsonl` | Mod, that session only | Frequent events (decision, scheduled, cancelled, refused, retry, lost, idle, pace, error), newest 5,000 lines |
| `~/.claude/cc-autocompact/savings/<Monday>/<session id>.json`, `weekly.log` | Mod | The session's estimated savings this week; last week's line, once |
| `~/.claude/cc-autocompact/debug.jsonl` | Mod, only with `"debug": true` | Every main-thread turn end and every compaction step (last 400 lines) |

The handoff path: a `Handoff: <path>` line in the nearest `CLAUDE.md` (the mod reads them with `$.fs.ancestors`), else `.claude/HANDOFF.md`, relative to the session's folder. The path must be a relative `.md` path inside the project (no `~`, no `..`, no absolute path); a line that breaks that rule is ignored with one toast. The mod reads the file only when a turn ends with the marker, and only if its real path (links followed) is inside the project's real path. The skill follows the same rules, so they agree.

The copy is named by a SHA-256 of the project folder and records that folder; at `SessionStart` it is used only if the folder matches. A wrap-up whose file is missing or refused empties the copy, so an older one never comes back. The mod writes nowhere else: `summaries_dir` and `log_file` outside its folders are refused ([SECURITY.md](../SECURITY.md)).

## Session state

The mod keeps one value per session (`$.state`, contract in [`plugin/types/index.d.ts`](../plugin/types/index.d.ts)). It doesn't survive closing the session, and doesn't need to.

| Field | What for |
| --- | --- |
| `phase` | `idle` or `wrapping` (`/compact-now` started a wrap-up and the mod is waiting for its turn). A wrap-up older than 15 minutes is considered stale. |
| `trigger` | `manual` when it comes from `/compact-now`; the automatic one logs `task_done`. |
| `inTurn` | A main-thread turn is running: never compact. |
| `gen` | Activity counter. If it changes during the delay, the compaction is cancelled. |
| `justCompacted` | Just compacted, no turn since: stops two compactions in a row. The `/compact` turn itself doesn't clear it. |
| `scheduled`, `scheduledAt` | A compaction is waiting out its delay: stops a second one being scheduled (expires after 10 minutes). |
| `compacting`, `compactingAt`, `compactBefore`, `compactTrigger` | `/compact` is queued and its result hasn't been seen. The first sign (what `$.command.run` returns, or the end of the `/compact` turn) closes it exactly once: toast, log and debug line. With no sign in 10 minutes, it is considered lost. |
| `stopMarker`, `stopTail` | What the main thread's `Stop` event saw in this turn (the marker fallback). |
| `title`, `titleAt`, `titleTriedAt`, `titleWarned` | Cached session title (30 minutes), a retry every 2 minutes, and a single warning if it can't be found. |
| `configWarned` | Already said once that `config.json` is not valid JSON. |
| `pathWarned`, `handoffWarned` | Already said once that `summaries_dir` or `log_file` point outside the mod's folders, or that the `Handoff:` line was ignored. |
| `remindedBand` | The last band of context the reminder asked in (-1 = none). Back to -1 whenever the engine has no context figure, which is what follows any compaction or `/clear`. |
| `cancelOwed` | A compaction was cancelled and the model doesn't know yet. Cleared when the note goes out, when a compaction is scheduled (not a retry) or done, or when there is no figure. |
| `scheduledTrigger` | What the compaction waiting out its delay is for (`task_done`, `manual`, `retry`): a cancelled retry is not owed again. |
| `compactionId` | The id of the mod's last queued compaction, in its log lines. |
| `compactTokensAfter` | `tokensAfter` as `session.compact` reported it for the mod's own `/compact`. |
| `afterOwed`, `afterOwedBefore` | A logged compaction whose `context_after` wasn't known: its id and its `context_before`. The next lower figure fills it. |
| `retryOwed`, `retryAt` | A message or a turn cancelled a compaction: one retry is owed, from that time, for 30 minutes. |
| `turnToolCalls` | Tool calls the main thread made in the current turn. |
| `lastCallAt` | When the main thread's last model response ended (its last `turn.complete`); `null` until then. |

## Safety rules

1. **Never with a turn running.** Checked when scheduling and again when the delay ends, and `/compact` waits in the queue until the session is idle.
2. **Never twice in a row** without a turn in between, and never two at once. The `/compact` turn doesn't count: if it keeps the message with the marker, it doesn't fire again.
3. **Any activity cancels.** A message from the user or a new turn during the delay. The mod retries once, only after a short answer that ended cleanly, within 30 minutes, and never if anything compacted in the meantime.
4. **Only the exact marker on the last line of the model's own answer**, bold or italic aside. "I am not Ready to compact." doesn't fire, and neither does a quoted marker (block quote, quotes, backticks, an open code block), a tool's output, a file or a subagent.
5. **A wrap-up that ends badly doesn't compact.** If the `/compact-now` turn ends interrupted, with an error or without the marker, the mod says so and does nothing.
6. **Subagents don't count**, for the trigger, the summaries or the handoff.
7. **No config means defaults; a broken config means off.** A missing `config.json` runs on the defaults. One that isn't valid JSON switches the automatic trigger off and says so once, so a typo never turns on what you had turned off.
8. **The turn never breaks.** Everything the mod does runs inside `try`; if something fails, it just doesn't compact, save or re-inject.
9. **The log never clobbers history.** It is append-only, a missing `context_after` comes in a line of its own, and if the file exists and can't be read, nothing is written. It never holds the text of a message.
10. **A refusal isn't swallowed.** If the engine refuses to queue `/compact`, the mod retries twice (3 s apart), then shows the exact reason and is free again.
11. **Only its own handoff goes back.** What is re-injected is the copy the mod took when your wrap-up ended, never a file a repository brought ([D18](DECISIONS.md#d18-only-the-mods-own-copy-of-the-handoff-goes-back)).
12. **It writes only in its folders and calls nothing outside.** No network, no shell, no `eval`; config paths stay inside `~/.claude`.
13. **The reminder only asks.** Fixed text plus a number, main thread only, and at most once per band. A failure never stops the message: it goes in without the note, and the note stays pending. A message that doesn't enter doesn't use it up.

## Tests

`plugin/hooks/` holds 167 tests in three files that run against the real engine with `claude plugin test plugin`. The test engine answers like the desktop app: `$.session.compact()` always rejects, and `/compact` is handled as a command. They cover the trigger and the log, the marker with decoration, sentences that aren't the marker, a custom marker, a session outside the list, the floor, `"*"`, no `config.json` at all, a partial one, a broken one, `CLAUDE_CONFIG_DIR`, a Windows home folder next to a Git Bash `HOME`, the app folder found under `LOCALAPPDATA`, the switch, cancelling with a message, two in a row and the `/compact` turn itself, a single close when `/compact` ends its turn before `command.run` answers, a refusal with a retry, three refusals, the `Stop` fallback (and that a subagent's or an earlier turn's doesn't count), subagents, debug on and off, `/compact-now` (normal, another skill, with arguments, interrupted, the namespaced skill name, the plain-words fallback), saving summaries (and `"off"`, and subagents), putting the handoff back (after a compaction and a `/clear`, not at startup, the `Handoff:` line, the length cap, no file, switched off), and the reminder (threshold, cadence, who gets it, the reset after any compaction, subagents, a turn running, the cancelled-compaction note and its three ways, the switch, the session list, an internal error, a refused message, a small window, custom numbers), and since 0.6.0 the question for a message from another session, every log event (decision, scheduled, cancelled with its origin and without the text, refused with its retry, lost, the unreadable-log guard, appending to an old log), `context_after` (reported by the compaction, filled by the next measurement or turn end, never rewritten), app compactions (auto, typed, not precompute, not subagents, and that one stops a scheduled compaction), the retry (after a short answer, not after a long, aborted or failed turn, not twice, not after 30 minutes, not after a compaction in between, `retry_max_tool_calls`), the policy input, and `/cc-doctor`. The 30 tests named `security: ...` cover what [SECURITY.md](../SECURITY.md) promises: a handoff shipped in a cloned repository, one changed after the wrap-up, a copy from another folder or tampered with, links that lead outside the project, seven hostile `Handoff:` lines, a quoted marker and an open code block, the `Stop` fallback against a real answer, hostile `summaries_dir`, `log_file`, `close_skill` and `marker` values, a project folder named `..`, capped numbers, a reminder that stays fixed text against a hostile config, title, handoff and message, and a reminder that never compacts by itself.

What the tests can't cover, because it needs a real, signed-in session: whether the `/compact` summary is good, and whether the engine raises `classic.PostCompact` and `classic.SessionStart` for the mod in the desktop app exactly as the test engine does. The live run on 31 October 2026 (0.2.0, with the Python hooks) confirmed the compaction and the saved summary. The reminder was also run on engine 2.1.309 the way the desktop app runs it, against a local server standing in for the model ([D19](DECISIONS.md#d19-size-may-ask-it-never-decides)). That shows the engine's side, not what a real model does with the question.
