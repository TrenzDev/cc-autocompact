# Configuration and internals

Back to the [README](../README.md).

## Settings

Nothing is required. To change something, create `~/.claude/cc-autocompact/config.json` with only the keys you want ([`config.example.json`](../plugin/config.example.json) has them all). The mod reads it on every use, so edits apply right away. It lives outside the plugin folder, so updating the plugin never touches it.

| Key | Default | What it does |
| --- | --- | --- |
| `enabled` | `true` | Switch for the automatic trigger. With `false`, only `/compact-now` works. |
| `sessions` | `["*"]` | Which sessions compact on their own. `["*"]`: all of them (the marker only shows up when the model closes a task). A list like `["Backend", "Docs"]`: only sessions whose title in the desktop app contains one of those words. `[]`: none. |
| `min_context_tokens` | `100000` | Below this, nothing compacts on its own: compacting something small isn't worth it. It is a floor, never a ceiling. Above it, the policy still checks that compacting pays (around 150k with the default figures). |
| `reminder` | `true` | Switch for [the reminder](../README.md#the-reminder) and for the note about a cancelled compaction. With `false`, the mod adds nothing to your messages. |
| `reminder_tokens` | `200000` | The context the reminder starts asking at (or 40% of the window, if that is less). It only asks: it never compacts. From 200k a closed task saves about twice what compacting costs. |
| `reminder_every_tokens` | `100000` | How many tokens more before it asks again (or 10% of the window, if that is less). |
| `delay_ms` | `1500` | Time between the toast and the compaction. A message from you or a new turn in that window cancels it. |
| `marker` | `"Ready to compact."` | The last line that means "task closed, everything saved". Change it for another language, and change the skill's last line to match. |
| `compact_instructions` | keep decisions, paths, pending, next step | What the summary must keep (what goes after `/compact`). Write it in the language you want your summaries in. |
| `close_skill` | `"wrap-up"` | The skill `/compact-now` runs, with arguments if it takes any (`"my-close light"`). It has to end with the marker. |
| `summaries_dir` | `""` | Where summaries are saved. `""`: `~/.claude/compaction-summaries/<project>/`. `"off"`: not saved. Another folder must be inside `~/.claude`. |
| `reinject_handoff` | `true` | Put the handoff back into the context after a compaction or a `/clear`. |
| `handoff_max_chars` | `12000` | Longest handoff that is put back (500 to 50,000). A longer one is cut, with a note saying where the full file is. |
| `debug` | `false` | Every turn end shows a toast with the decision and writes a line to `debug.jsonl` (last 400 lines). For debugging. |
| `log_file` | `""` | The compaction log. `""`: `~/.claude/cc-autocompact/compactions.jsonl`. Another one must be a `.jsonl` inside `~/.claude/cc-autocompact`. |
| `app_sessions_dir` | `""` | Where the desktop app keeps session titles. Only used with a list in `sessions` and for titles in the log. On Windows it is found by itself. |
| `expected_calls` | `50` | Requests a session is expected to make after a closed task. With `expected_cold_returns`, `margin`, `post_compact_tokens`, `post_compact_cached_tokens` and `summary_tokens` it sets when compacting pays: the expected saving (a smaller context on every later request, and on every return after the cache expired) against the cost (the `/compact` request and rebuilding the cache). The defaults come from replaying six months of real usage with [`tools/simulate.py`](../tools/simulate.py): after a closed task a session went on for a median of 50 or more requests, with 1 to 7 returns after more than an hour. |
| `expected_cold_returns` | `2` | Returns after the cache expired, expected over that stretch. |
| `margin` | `1` | Compact only if the saving is at least this many times the cost. |
| `post_compact_tokens`, `post_compact_cached_tokens` | `107000`, `44000` | The context a compaction leaves, and how much of it is still cached (the replay's medians). |
| `summary_tokens` | `33000` | The output of the `/compact` request itself. |
| `hard_cap_share` | `0.85` | At a turn end, compact even without a closed task once the window is this full (0.1 to 1). The one size rule, kept for a window about to overflow. |
| `idle_minutes` | `45` | After this long without a request, look again, while the cache is still warm (it lives an hour on a subscription). |
| `idle_mode` | `"ask"` | When idle: `"ask"` compacts a closed task and, mid-task, asks the model once whether it can wrap up (it compacts only if the answer ends with the marker); `"closed"` only compacts a closed task; `"any"` compacts mid-task without asking; `"off"`. |
| `idle_min_tokens` | `300000` | When idle mid-task, ask (or with `"any"`, compact) only from this context. |
| `main_cache_ttl_minutes` | `60` | How long the main conversation's cache lives: an hour on a subscription ([prompt caching](https://code.claude.com/docs/en/prompt-caching)). Once the five-hour window is past 100% (extra usage) the mod uses 5 minutes. |
| `pacing` | `true` | Near a usage limit, add a note to messages that did not come from a person (another session, a schedule, a background task): keep new work light, or defer it until the reset. A message from you is never touched. After a deferred window resets, the session gets one prompt to pick the work up. |
| `five_hour_light_pct`, `five_hour_hold_pct` | `85`, `95` | Five-hour window: from the first, "light"; from the second, "hold". |
| `seven_day_light_pct`, `seven_day_hold_pct` | `90`, `97` | The same for the weekly window. |
| `usd_per_point` | `null` | USD per point of your plan's usage, to show the weekly saving in points too. |
| `retry_max_tool_calls` | `3` | A compaction a message cancelled is tried again after the next turn only if that turn made at most this many tool calls (0 to 100). |

If `config.json` isn't valid JSON, the automatic trigger stays off and a toast says why: a typo should never turn on what you had turned off. A key with the wrong type takes its default. `~/.claude` means `CLAUDE_CONFIG_DIR` if you set it.

## The handoff file

The handoff file is `.claude/HANDOFF.md` in the project. To use another one, put a line `Handoff: docs/STATE.md` in the project's `CLAUDE.md`: the skill and the mod both read it. It has to be a `.md` file inside the project, written relative to it. When a wrap-up ends with `Ready to compact.`, the mod keeps its own copy of the handoff in `~/.claude/cc-autocompact/handoffs/`, and that copy is what goes back after the compaction, never a file read from the project later. So a handoff that came inside a cloned repository is never injected ([SECURITY.md](../SECURITY.md)). The `# Compact instructions` section of your `CLAUDE.md` also steers what `/compact` keeps ([costs](https://code.claude.com/docs/en/costs#manage-context-proactively)).

## The log

The log, `compactions.jsonl`, gets one JSON line per event, appended, never rewritten, and never with the text of a message. Every line has `time`, `event`, `session_id`, `reason` and `context_before`. A finished compaction keeps the shape earlier versions wrote, plus `event` and `compaction_id`:

```json
{"time":"2026-10-31T14:20:05.123Z","event":"compacted","session_id":"…","reason":"command.run","context_before":312000,"session":"Project · Backend","context_after":41000,"trigger":"task_done","compaction_id":"mh3k2x0a1b"}
```

| `event` | When |
| --- | --- |
| `decision` | A main-thread turn ended with the marker, or a `/compact-now` wrap-up ended: `reason` is `compact` or why not (`no: under the floor (60k of 100k)`, `no: this session is not in sessions`…). A turn without the marker logs nothing. |
| `scheduled` | A compaction starts waiting out `delay_ms`, with its `trigger`. |
| `cancelled` | A message (`origin` says from where: `composer`, `peer`…), a new turn, or a compaction in between stopped it. |
| `retry` | The retry after a cancellation: `scheduled`, or `not retried: …` (a long turn, an aborted one, expired, compacted meanwhile). |
| `refused` | The engine refused to queue `/compact`; `will_retry` says whether the mod tries again in 3 s. |
| `compacted` | The mod's compaction finished. `trigger` is `task_done` (the marker), `manual` (`/compact-now`), `retry`, `hard_cap` (window nearly full), `idle` or `idle_ask`. |
| `idle_ask`, `idle_declined` | The idle question went out; its answer did not end with the marker. |
| `pace` | A pacing note went beside a message that did not come from a person (`origin`, `level`, `pct`), or the resume prompt went out. |
| `context_after` | `context_after` was not known when the `compacted` or `app_compaction` line was written: this line brings it, with the same `compaction_id`. |
| `app_compaction` | A compaction the mod didn't start: Claude Code's auto-compact (`trigger: "auto"`) or a `/compact` you typed (`"manual"`). |
| `lost` | A queued `/compact` gave no sign in 10 minutes. |
| `error` | Something inside the mod failed; it did nothing more, and `reason` says where. |

Since 0.6.0 only `compacted`, `app_compaction` and `context_after` go to the shared `compactions.jsonl`. The frequent lines go to a file of each session's own, `~/.claude/cc-autocompact/events/<YYYY-MM>/<session id>.jsonl` (newest 5,000 lines), so sessions running side by side never rewrite each other's lines. A session never writes `compactions.jsonl` back shorter than it last saw it. Each session also keeps its week's estimated savings in `savings/<Monday>/<session id>.json`, and the first session of a new week appends last week's line to `weekly.log` and shows it once. `/cc-doctor` reads all of them.

`context_after` comes from the compaction itself when the engine reports it, otherwise from the first figure after it, in its own `context_after` line. A reader that only wants compactions keeps the lines with `event` `compacted` (or no `event`, written before 0.6.0). If the log exists and can't be read, nothing is written, so history is never clobbered.

## Plug in your own system

- **Your notes, task tracker or changelog:** a `Capture: <command>` line in your `~/.claude/CLAUDE.md` or a `CLAUDE.local.md`. The skill runs it once per wrap-up. One in a `CLAUDE.md` checked into a repository is shown to you and only runs after you say yes.
- **Your own wrap-up skill:** put its name in `close_skill` and make it end with the marker as its last line. No marker, no compaction.

## Check the whole loop

1. **Floor.** In a small session (under 100k), run `/wrap-up`. When it ends with `Ready to compact.` you get "under the 100k floor: not compacting".
2. **Trigger.** In a session above 100k, run `/wrap-up`. You get "Task wrapped up at …k: compacting in a moment", `/compact` running, and "Compacted: …k to …k". Ask what was pending: it should answer without re-reading anything.
3. **Trail.** A new line in `~/.claude/cc-autocompact/compactions.jsonl` and a summary in `~/.claude/compaction-summaries/<project>/`.
4. **Cancel.** Repeat step 2 and send any message within 1.5 s: "Compaction cancelled". With `"debug": true`, `debug.jsonl` gets a line with `"event":"reminder","kind":"cancelled"`, which is the note the model got.

If something doesn't match, run `/cc-doctor`, or set `"debug": true` and try again: the mod explains every decision.
