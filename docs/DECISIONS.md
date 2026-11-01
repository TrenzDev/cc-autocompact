# Design decisions

Why it is built this way and not another. Each decision has its reason and, where there is one, the official Claude Code source behind it. Sources checked on 31 October 2026.

Official docs cited:

- Costs: https://code.claude.com/docs/en/costs
- Context window and what survives a compaction: https://code.claude.com/docs/en/context-window
- Best practices: https://code.claude.com/docs/en/best-practices
- Hooks: https://code.claude.com/docs/en/hooks
- Model config and the auto-compact window: https://code.claude.com/docs/en/model-config
- Prompt caching: https://code.claude.com/docs/en/prompt-caching
- Settings (`idleCompaction`, `autoCompactWindow`): https://code.claude.com/docs/en/settings-reference
- Cross-session messages: https://code.claude.com/docs/en/cross-session-messaging

---

## D1. The task decides, not the size

**Decision.** Size never compacts anything: no context ceiling, no "compact above X tokens". It compacts when a task ends and the next one doesn't need its context. The one number that looks at size, the reminder, only asks the question (see [D19](#d19-size-may-ask-it-never-decides)).

**Why.** Some tasks need the million tokens (a big migration, a long document, a batch of work in progress), and cutting them by size breaks the work. In my measurement, closing at task boundaries captured almost all of the saving; a 300k threshold on top only added two points, and on its own it lost value fast as it went up (see [MEASUREMENT.md](MEASUREMENT.md)).

**Source.** Every turn re-reads the whole context: *"a one-line question in a session that has been open all day still draws usage for the whole conversation"* ([costs](https://code.claude.com/docs/en/costs#why-usage-climbs-in-a-long-session)). What is wasted is the context of a finished task, not a large context as such.

## D2. Compact, don't clear

**Decision.** When a task closes, the session compacts (`/compact`); it doesn't clear (`/clear`).

**Why.** `/clear` is cheaper, but it wipes the visible history and the thread of decisions. Compacting keeps a summary inside the same session, and you feel the continuity. You pay for the compaction once per task; you pay for old context on every turn.

**Sources.** `/clear` is free and `/compact` is a big request: *"/compact reads the conversation it summarizes, so compacting a large context is itself a large request"* ([costs](https://code.claude.com/docs/en/costs#why-usage-climbs-in-a-long-session)). The docs recommend `/clear` between unrelated tasks because *"a focused context gets you better answers and costs less"* ([best-practices](https://code.claude.com/docs/en/best-practices#keep-cost-and-context-down)). Compacting gets the same focus and keeps the thread. If you prefer `/clear`, the SessionStart hook is ready for `clear` too.

## D3. Judgment in the model, action in the harness

**Decision.** The model decides (a rule in `CLAUDE.md` plus a skill); a mod runs the compaction.

**Why.** Only the model knows whether a task is done and whether the next thing is something else. And nothing outside the UI itself can run `/compact`: not a hook, not a skill, not the model. A message from another session saying "/compact" arrives as plain text. A mod can: it queues `/compact` in the session (see D12).

**Sources.** Which hooks exist and what they can do ([hooks](https://code.claude.com/docs/en/hooks)); cross-session messages arrive as text turns ([cross-session-messaging](https://code.claude.com/docs/en/cross-session-messaging)). `$.command.run` and `$.session.compact` are in the types the engine itself ships.

## D4. A line of text as the contract

**Decision.** The signal between the skill and the mod is the exact last line `Ready to compact.` (configurable with `marker`).

**Why.** You can see it, it is easy to test, and it needs no extra channel. Above all, it is only written once the handoff is safe: if something fails, the skill doesn't write it and the mod doesn't compact. Any skill of your own can use the same contract.

## D5. Claude Code's auto-compact stays as it is

**Decision.** This doesn't lower `autoCompactWindow` or touch `idleCompaction`.

**Why.** Lowering the auto-compact window is a size threshold in disguise (it goes against D1). The default auto-compact, near the end of the window, stays as the safety net for when a task really does fill everything.

**Sources.** The window can be set between 100k and 1M with `/autocompact`, `autoCompactWindow` or `CLAUDE_CODE_AUTO_COMPACT_WINDOW` ([model-config](https://code.claude.com/docs/en/model-config#set-the-auto-compact-window)); idle compaction ([settings-reference](https://code.claude.com/docs/en/settings-reference#idlecompaction)).

## D6. A small floor (80k)

**Decision.** Below 80k of context, the marker doesn't compact (except with `/compact-now`).

**Why.** Compacting a small session saves little and costs a request. It is a floor, not a ceiling: it never stops you using context, it only avoids pointless compactions.

## D7. A short, cancelable delay

**Decision.** 1.5 s pass between the toast and the compaction, and any message or new turn cancels it.

**Why.** It gives you a way out when you see the toast and want to keep going, without a confirmation on every close.

## D8. Nothing is lost: handoff first, summary on disk, handoff back after

**Decision.** Three independent pieces: the skill writes the handoff before the marker; the mod saves the summary when a compaction ends (`PostCompact`); and it puts the handoff back after a compaction or a clear (`SessionStart`). Until 0.3.0 the last two were Python hooks (see D15).

**Why.** An automatic summary can drop details. With the handoff on disk and the summary archived, what matters exists outside the conversation, and the essentials come back into the context by themselves.

**Sources.** PostCompact receives `compact_summary` and `trigger`; SessionStart receives `source` (`startup`, `resume`, `clear`, `compact`, `fork`) and what it adds goes into the context ([hooks](https://code.claude.com/docs/en/hooks)). After a compaction, Claude Code runs the SessionStart hooks with `compact` and reloads `CLAUDE.md`, memory and up to five recent files ([context-window](https://code.claude.com/docs/en/context-window#what-survives-compaction)).

## D9. Summaries outside your projects

**Decision.** Summaries go to `~/.claude/compaction-summaries/<project>/`, never inside a repository.

**Why.** A summary can hold a private project's data. Saving it inside another repository risks mixing it in or pushing it by mistake.

## D10. No panels

**Decision.** The mod only shows short toasts and adds one command.

**Why.** It should go unnoticed. Another panel competes for attention and space with the work.

## D11. The installers don't edit `settings.json` on their own

**Decision.** The main way in is the plugin marketplace, which needs no `settings.json` edit at all. The installers for a clone (`install.sh`, `install.ps1`) print the one line they need and only apply it with `--apply-settings` / `-ApplySettings`, after a backup.

**Why.** `settings.json` usually holds hooks, permissions and variables from other tools. Touching it without you seeing it is a risk that isn't worth ten seconds of copy and paste.

## D12. Compact by queueing `/compact`, not with `$.session.compact()`

**Decision (0.2.0).** The mod compacts with `$.command.run({ command: 'compact', args: compact_instructions })`.

**Why.** 0.1.0 used `$.session.compact()` and never compacted in the desktop app. There every session runs headless (SDK), and on engine 2.1.309 that function always rejects: *"not available in a headless (-p / SDK) session yet: compaction here runs inside a turn (a /compact prompt)"*. `$.command.run` runs a command *"as if the person typed `/command args`"*, queued, as soon as the session is idle, so the compaction is a normal `/compact`: the `# Compact instructions` section of `CLAUDE.md` and the hooks of a manual compaction apply. Checked live on 31 October 2026.

**Consequences.** The compaction no longer returns the before and after numbers: the mod reads the context with `$.session.usage()` before and after, and if the number hasn't dropped yet it logs `context_after: null`. Since `/compact` is a turn, the mod recognizes that turn so it doesn't count as "a turn in between" and doesn't fire again on the marker it keeps.

**Source.** The engine's types (`CommandRunInput.command`: *"Names the command without its slash (`compact`, `hello`)"*) and engine 2.1.309 itself, which is what rejects `compact()` when headless.

## D13. A marker fallback with the `Stop` event

**Decision (0.2.0).** Besides `turn.complete`, the mod listens to the main thread's `classic.Stop`, which carries `last_assistant_message`.

**Why.** If some release delivered `turn.complete` without the answer's text, the marker would be lost without a trace. `Stop` arrives first and carries the last message. It is cleared on every `turn.start`, so it never carries over from one turn to the next, and a subagent's doesn't count. Reading the whole transcript with `$.session.messages()` was ruled out: it copies thousands of messages at every turn end for something two events already carry.

## D14. Debug mode, off by default

**Decision (0.2.0).** With `"debug": true`, the mod explains every turn end with a toast and a line in `debug.jsonl`. It is off by default.

**Why.** A toast is gone if you aren't looking, and "it doesn't compact" with no trail is impossible to debug. The file keeps the decision and the engine's exact reason. Off by default because in normal use it is noise.

## D15. One plugin: no Python, no `settings.json`

**Decision (0.4.0).** The two hooks that saved the summary and put the handoff back are now part of the mod: it listens to `classic.PostCompact` and `classic.SessionStart` and does the same work with `$.fs`. The skill ships inside the plugin. The repository is a plugin marketplace, so installing is one line.

**Why.** Python hooks meant three things a new user had to get right: Python on the PATH (and `python` versus `python3`), the path to the interpreter, and two hook groups merged by hand into `settings.json`. Each was a way for the install to fail, and none of them is needed: the mod API raises the settings hooks' events for mods too, with the same input, and lets a `SessionStart` answer carry `additionalContext`.

**Source.** The engine's types: `PostCompactHookInput.compact_summary`, `SessionStartHookInput.source`, and `ClassicResult.additionalContext` (*"text handed to the model with the event"*). Covered by tests; the live check is pending (see the README's known limits).

## D16. No config file needed

**Decision (0.4.0).** With no `config.json`, the mod runs on its defaults (switched on, every session, 80k floor). The optional file lives in `~/.claude/cc-autocompact/`, outside the plugin. A file that isn't valid JSON switches the automatic trigger off and says so once.

**Why.** A plugin installed from a marketplace is replaced on update, so a config inside it would be lost. A missing file is the normal case and should just work. A broken file is a mistake, and the safe reading of a mistake is "off": a typo in `"enabled": false` must not turn compaction on.

## D17. The name: cc-autocompact

**Decision (0.4.0).** The project is `cc-autocompact` (it was `second wind` in 0.3.0, which was never published).

**Why.** Searched on 31 October 2026: `secondwind` is already an active tool in the same space (LLM context compression for coding agents, on GitHub, npm and PyPI), and "second wind" brings up a large YouTube channel, a game mod and dictionary pages, so nobody would find this by its name. "autocompact" is the word people use in Claude Code issues and posts (about 500 issue titles say auto-compact), and on GitHub it is nearly empty (36 repositories, none above 11 stars). The `cc-` prefix is how small Claude Code utilities are usually named (`ccusage`, `ccstatusline`, `cc-switch`), it tells it apart from Claude Code's own auto-compact, and it keeps a trademark out of the name. The data and the other names that were weighed are in the release notes of 0.4.0.

## D18. Only the mod's own copy of the handoff goes back

**Decision (0.4.0, before the first public release).** When a main-thread turn ends with the marker, the mod copies the handoff into `~/.claude/cc-autocompact/handoffs/<hash of the project folder>.json`. After a compaction or a `/clear` it puts back that copy, never the file in the project. A `Handoff:` path must be a relative `.md` path inside the project, and the file is read only if its real path, links followed, is inside the project. Config paths that would write outside the mod's folders are refused. The full list is in [SECURITY.md](../SECURITY.md).

**Why.** Until then, `SessionStart` read `.claude/HANDOFF.md` from the session's folder and handed it to the model as "the state the last wrap-up left". A repository you clone controls that file and its `CLAUDE.md`, so it could have planted instructions that come back with that authority after any compaction, Claude Code's own included. It could also have pointed the `Handoff:` line, or a symbolic link, at `~/.ssh` and had the mod read a secret into the context without any permission prompt. The marker is the moment the user's own session vouches for the handoff: the skill has just written and re-read it. Taking the copy then, outside the project, closes both holes without losing anything in normal use. The handoff still comes back after the mod's compaction, after a `/compact` you type and after a `/clear`, as long as a wrap-up has run in that project.

**Cost.** A handoff edited by hand after the wrap-up doesn't come back until the next wrap-up. In a project where no wrap-up has run, nothing comes back. Both are the safe side.

## D19. Size may ask, it never decides

**Decision (0.5.0).** When a message from the user or another session comes in between turns on the main thread and the context has crossed a new band (from 400k, then every 100k more), the mod adds a short question next to it, as `prompt.submit` context: is the task closed, and does what comes next not need this context? If a message cancels a compaction waiting out its delay, it brings a note saying so instead, once. Both are fixed text plus a number, and neither compacts anything.

**Why.** D3 leaves the judgment in the model, and that is right, but nothing reminded it. In the log of the first six compactions, none came from the model's own initiative: the user or a coordinating session asked, each time with 500k to 880k of context. D1 still stands: the task decides. What changes is that the model is asked at a moment it can answer, when a new message shows what comes next. The other gap was worse: a message from another session arrived during the 1.5 s delay, the compaction was cancelled (D7, as designed), and nothing told the model it had to ask again.

**Why 400k and 100k.** Simulated over 14 days of my sessions: 140 sessions, 5,891 messages.

| Threshold, step | Questions | Sessions reached | One in every N messages above it |
| --- | --- | --- | --- |
| 300k, 100k | 703 | 70 | 5.7 |
| **400k, 100k** | **511** | **63** | **5.7** |
| 500k, 100k | 348 | 53 | 5.8 |
| 400k, 50k | 811 | 63 | 3.6 |
| 400k, 200k | 315 | 63 | 9.3 |

Going down to 300k spends 38% more questions to reach 7 more sessions. Going up to 500k leaves 10 out. A 50k step asks on every third or fourth message, which gets ignored; a 200k step can carry 200k more before asking again. The count runs high, since compacting earlier means fewer questions, and it doesn't take out the messages that arrive with a turn running. A question is about 150 tokens and there are at most seven up to a million, so it costs far less than carrying the context for one more turn.

**Consequences.** It doesn't ask with a turn running: the task isn't closed, and the band stays pending for the next message between turns. It doesn't ask for background tasks, plugin messages, routines or commands. It starts over by itself after any compaction, a `/compact` you type, auto-compact and `/clear` included, because the engine gives no context figure until the first response of the new context. In a window under a million, the threshold drops to 40% of the window and the step to 10%, never below the floor, or the default would never fire in a 200k window. After a compaction the session waits for a message, so a long request that came with the question stays as the next step until someone says "go on".

**Source.** `PromptSubmitInput.context` in the engine's types (*"What the model reads beside the prompt and the user never sees"*), and engine 2.1.309 run the way the desktop app runs it (long-lived stream-json, `CLAUDE_CODE_PLUGIN_DIRS`, `entrypoint: claude-desktop`), with a local server in the model's place: the note is in the real request, right after the user's message, also for a real message from another session sent through the engine's messaging socket during the delay. It isn't in a subagent's request. A real `/compact` leaves `$.session.usage()` with no figure, and the next crossing asks again. What the model does with the question has not been measured yet. Unlike `$.session.compact()` (D12), this works in the headless host.

## What was ruled out

| Idea | Why not |
| --- | --- |
| Compact above a size (300k, 550k) | It cuts tasks that need their context (D1). Above a size it only asks (D19). |
| Ask on every message past a size | A reminder on every message gets ignored, and it costs tokens in every session (D19). |
| Compact after X minutes idle | The app already has idle compaction, and a pause doesn't mean the task is done. |
| `/clear` at the end of every task | Loses the history and the thread (D2). |
| A coordinating session that compacts the others | Not possible from outside (D3). |
| A panel with every session's context | Noise (D10). The status line or `/context` already give it when you need it. |
