# Changelog

Every notable change goes here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow [Semantic Versioning](https://semver.org/).

## [0.4.0] - 2026-10-31

One plugin, installed with one line, that works with no configuration. And a new name.

### Changed

- **Name: cc-autocompact** (was second wind, never published). "secondwind" is already a tool for compressing coding agents' context, on GitHub, npm and PyPI; "autocompact" is the word people use for this in Claude Code, and almost nothing on GitHub uses it. The reasons are in [D17](docs/DECISIONS.md#d17-the-name-cc-autocompact).
- **One plugin.** The mod and the `wrap-up` skill live in `plugin/`, and the repository is a plugin marketplace: `/plugin install cc-autocompact --marketplace TrenzDev/cc-autocompact`.
- **No Python, no `settings.json`.** The mod now saves each compaction summary (`classic.PostCompact`) and puts the handoff back after a compaction or a `/clear` (`classic.SessionStart`) by itself. `hooks/save_summary.py` and `hooks/reinject_handoff.py` are gone, and so are the `SECOND_WIND_*` variables.
- **No config needed.** With no `config.json` the mod runs on its defaults (on, every session, 80k floor). The optional file moved to `~/.claude/cc-autocompact/config.json`, outside the plugin, so updates don't touch it; the logs moved there too. A `config.json` that isn't valid JSON switches the automatic trigger off and says so once.
- The handoff path comes from a `Handoff:` line in `CLAUDE.md`, read by both the skill and the mod (a relative `.md` path inside the project).
- `/compact-now` also tries the skill's namespaced name (`cc-autocompact:wrap-up`).
- On Windows the mod finds the desktop app's session titles by itself (`app_sessions_dir` can stay empty).
- New config keys: `summaries_dir` (or `"off"`), `reinject_handoff`, `handoff_max_chars`.
- The README images are redrawn: a tide record of the context, with a pen lettering of its own (`assets/lettering.py`), an animated illustration of the flow, and the plugin icon.

### Added

- `install.sh` for macOS and Linux. Both installers copy the plugin and add one line to `settings.json` only when asked.
- `tools/measure_context.py --compare`: two windows side by side, plus a direct estimate of what the mod's own compactions saved (`--log`), and `--figures` for the README chart.
- `assets/make_demo.py`: turns a screen recording into a light GIF and MP4 for the README.
- 67 tests (was 26), 28 of them on security.
- `SECURITY.md`: what the plugin reads and writes, the threat model, and private reporting.

### Security

A review before the first public release, against one question: can a repository you clone, or a hostile config, use this plugin against you? Every point has a test. See [SECURITY.md](SECURITY.md) and [D18](docs/DECISIONS.md#d18-only-the-mods-own-copy-of-the-handoff-goes-back).

- **The handoff that goes back is the mod's own copy.** When a turn ends with the marker, the mod copies the handoff into `~/.claude/cc-autocompact/handoffs/`; after a compaction or a `/clear` it puts back that copy, never the project's file. A `HANDOFF.md` that came inside a cloned repository, or one a later pull changed, is never injected, and the injected text says it is notes, not a message from the user.
- **The handoff can't point outside the project.** A `Handoff:` path must be a relative `.md` path inside the project (no `~`, no `..`, no absolute path), and the file is read only if its real path, links followed, is inside the project. A link to `~/.ssh` is refused.
- **The marker only counts as the model's own last line.** Not in a block quote, quotes, backticks or an open code block. The `Stop` fallback is read only when the turn's text is empty.
- **It writes only in its folders.** `summaries_dir` must be inside `~/.claude` and `log_file` a `.jsonl` inside `~/.claude/cc-autocompact`; anything else is refused with one toast. A project folder named `..` can't climb out of the summaries folder.
- **A hostile config can't inject text or commands.** `close_skill` must be a plain command name on one line (never `compact-now`), `marker` one line, long text is cut, and `delay_ms` and `handoff_max_chars` are capped.
- **The skill** applies the same `Handoff:` rule, and runs a `Capture:` command without asking only when it comes from your private instructions; one from a repository's `CLAUDE.md` waits for your yes.
- Checked: no network calls, no telemetry, no shell or `eval`; the installers download nothing and change only `env.CLAUDE_CODE_PLUGIN_DIRS` (tested on a sample `settings.json` with hooks, permissions and Unicode).

## [0.3.0] - 2026-10-31

The project gets a name, second wind, and everything public is now in English.

### Changed

- **Names.** The mod is `second-wind` (was `context-autopilot`), the command is `/compact-now` (was `/compactar-ya`) and the skill is `wrap-up` (was `cierre-ligero`). The hooks are `save_summary.py` and `reinject_handoff.py`, the meter is `tools/measure_context.py`, and the environment variables start with `SECOND_WIND_`.
- **Default marker** is `Ready to compact.` (was `Listo para compactar.`).
- **`config.json` keys** are in English: `enabled`, `debug`, `sessions`, `min_context_tokens`, `delay_ms`, `close_skill`, `marker`, `compact_instructions`, `log_file`, `app_sessions_dir`. Old configs are not read; copy your values over.
- **Log files**: `compactions.jsonl` with `time`, `session`, `session_id`, `context_before`, `context_after`, `trigger` (`task_done` or `manual`), and `debug.jsonl`.
- Summaries go to `~/.claude/compaction-summaries` by default.
- The installer switch is `-ApplySettings` (`-AplicarSettings` still works).
- The meter's flags are `--days`, `--until`, `--titles` and `--prices` (the Spanish ones still work) and its `--json` keys are in English.

### Added

- `marker` in `config.json`: use your own closing line, in any language.
- README images, drawn as SVG by `assets/make_assets.py`, in a light and a dark version, plus a 1280x640 social preview.
- 26 tests with `claude plugin test` (one more: a custom marker).

## [0.2.0] - 2026-10-31

The mod now compacts in the desktop app. Live check: it saw the marker, compacted a 779,650-token session, and the PostCompact hook saved the summary.

### Fixed

- **0.1.0 never compacted in the desktop app.** There every session runs headless (SDK), and on engine 2.1.309 `$.session.compact()` always rejects in that case (*"not available in a headless (-p / SDK) session yet: compaction here runs inside a turn (a /compact prompt)"*). The mod caught the error and only showed a 7-second toast. It now queues `/compact` with `$.command.run({ command: 'compact', args })`, which runs it as if the user typed it, as soon as the session is idle.

### Added

- **Marker fallback:** the mod also listens to the main thread's `Stop` event (`classic.Stop`, field `last_assistant_message`). If `turn.complete` arrives without text, the marker that `Stop` saw in that same turn counts. A subagent's `Stop`, or one from an earlier turn, does not.
- **Debug mode** (off by default): at every turn end, a toast with the decision and its reason, and a line in a JSONL file in the mod folder (last 400) with each compaction step and the engine's exact reason if it refuses.
- **Retries:** if the engine refuses to queue `/compact`, the mod retries twice, 3 s apart, then shows the reason and is free for the next one.
- The closing-skill setting accepts arguments.
- A more forgiving `config.json`: a key with the wrong type falls back to its default.
- 25 tests with `claude plugin test` (was 17). The test engine answers like the app: `$.session.compact()` always rejects.

### Changed

- A compaction is closed exactly once, by the first sign (what `$.command.run` returns, or the end of the `/compact` turn itself), and the `/compact` turn does not count as "a turn in between".
- A compaction that gives no sign in 10 minutes is considered lost.
- `context_after` in the log is `null` when the app hadn't updated the number yet.

## [0.1.0] - 2026-10-31

First version, in Spanish and private.

### Added

- A mod for the Claude Code desktop app that compacts the session when an answer ends with the marker line, with a context floor, an optional session list, a cancelable delay, a JSONL log and a manual command.
- A light wrap-up skill: when to close, a configurable handoff file, an optional step for your own system, and the marker.
- A PostCompact hook that saves every summary outside your projects, and a SessionStart hook that puts the handoff back after a compaction or a `/clear`.
- A meter that reads local `.jsonl` transcripts and reports how much carrying context costs.
- A Windows installer that copies everything into `~/.claude`, prints the `settings.json` block, and applies it only when asked, after a backup.

### Tested with

- Windows 11, the Claude Code desktop app with engine 2.1.309.
- Python 3.12 and Windows PowerShell 5.1.

[0.4.0]: https://github.com/TrenzDev/cc-autocompact/releases/tag/v0.4.0
