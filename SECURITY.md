# Security

cc-autocompact is a Claude Code mod plus one skill. This page says what it can and can't do on your machine, what it was checked against, and how to report a problem.

## What it does and doesn't do

- **No network.** The mod makes no network calls and sends no telemetry. It doesn't use `$.http`, and the engine's own listing of what the module calls (`claude plugin validate plugin`) shows none.
- **No commands or code.** The mod runs no shell, no process and no `eval`. The only commands it runs are Claude Code slash commands: `/compact`, and for `/compact-now` the closing skill named in your config (`wrap-up` by default).
- **No secrets.** It reads no credentials, tokens or keys, and writes none.
- **It only changes your context in two ways:** after a compaction or a `/clear`, it puts back the handoff your last wrap-up left; and when the context is high, it adds one of two short fixed notes next to a message coming in (see below).

### Files it reads

| What | Why |
| --- | --- |
| `~/.claude/cc-autocompact/config.json` | Your optional settings. |
| `CLAUDE.md` files above the session's folder, through the engine | To find a `Handoff:` line. |
| The project's handoff (`.claude/HANDOFF.md`, or the `Handoff:` path) | Copied once, at the moment a wrap-up ends with the marker. Only if, every link followed, it is a file inside the project. |
| The desktop app's session metadata (`local_*.json` under `%LOCALAPPDATA%/Claude-Data/…/claude-code-sessions`, or `app_sessions_dir`) | Only the `title` field, for the `sessions` filter and the log. Read only. |

### Files it writes

Only these, inside Claude Code's folder (`~/.claude`, or `CLAUDE_CONFIG_DIR`):

| What | Where |
| --- | --- |
| Compaction log | `~/.claude/cc-autocompact/compactions.jsonl` (or `log_file`, which must be a `.jsonl` inside that folder) |
| Debug log, only with `"debug": true` | `~/.claude/cc-autocompact/debug.jsonl` |
| The mod's copy of each project's handoff | `~/.claude/cc-autocompact/handoffs/<hash of the project folder>.json` |
| Compaction summaries | `~/.claude/compaction-summaries/<project>/` (or `summaries_dir`, which must be inside `~/.claude`; `"off"` writes none) |

A `log_file` or `summaries_dir` outside those folders is refused, the default is used and a toast says so once. The mod never writes inside your projects. The `wrap-up` skill does: the model writes the handoff file there, with Claude Code's normal permissions.

The installers (`install.sh`, `install.ps1`) copy the plugin to `~/.claude/mods/cc-autocompact`, move any previous copy to `~/.claude/backups/`, and touch `settings.json` only with `--apply-settings` / `-ApplySettings`. Then they save a backup first and change one key, `env.CLAUDE_CODE_PLUGIN_DIRS`. They download nothing.

## Threat model

The question was: can someone use this plugin against the person running it? The main risk is a repository you clone, since the plugin reads files from your projects and adds text to the model's context.

| Risk | What stops it |
| --- | --- |
| **Someone gets text into the reminder**: a repository, a file, the transcript, a session title, a hostile `config.json`. | The two notes are constants in the code plus one number, the context size as the engine reports it, formatted by the mod (`512k`). They read nothing from the transcript, a file or `config.json`. A custom `marker` isn't quoted either: the text then says "the marker line your wrap-up ends with". They only ask: a note can't compact, run a command or grant anything, and the only thing that compacts is still the marker on the model's own last line. They reach the main thread only, never a subagent. `"reminder": false` turns them off. |
| **A cloned repository ships a `.claude/HANDOFF.md` with instructions**, hoping it gets injected after a compaction. | The mod never puts back a file read from the project. It puts back only its own copy, taken when a main-thread turn of yours ends with the marker, and kept outside the project. Claude Code's auto-compact, a `/compact` you type or a `/clear` re-inject nothing in a project where no wrap-up of yours has run. A later `git pull` that changes the file doesn't change the copy. The injected text says it is notes, not a message from the user, and grants no permission. |
| **A `Handoff:` line or a link that points at your secrets** (`Handoff: ~/.ssh/id_rsa`, `../../.aws/credentials`, a `HANDOFF.md` that is a symbolic link to `~/.ssh`). | A `Handoff:` path must be a relative `.md` path inside the project, with no `~`, no `..`, no drive and no absolute path. Otherwise the default is used. The file is read only if its real path, every link followed, is inside the project's real path. A link that leads outside is refused and a toast says so. The skill applies the same rule before writing. |
| **The marker is triggered by text that isn't the model's own** (a tool's output, a file, a subagent, your message). | Only the main thread's final answer counts (`turn.complete` without `agentId`, `reason` `answer`). Its last line must be the marker: not in a block quote, not in an unclosed code block, not in quotes or backticks. The `Stop` fallback is only read when the answer arrived empty, and never from a subagent. The worst a false trigger can do is compact once. |
| **A `Capture:` line in a repository's `CLAUDE.md` runs a command** at wrap-up. | The skill runs a `Capture:` command without asking only if it comes from your private instructions (`~/.claude/CLAUDE.md`, `CLAUDE.local.md`). From a checked-in `CLAUDE.md` it shows the command and waits for your yes, and it never runs one that downloads and runs code. Claude Code's own permission prompts still apply. |
| **A broken or hostile `config.json`.** | Invalid JSON switches the automatic trigger off. Paths are kept inside the mod's folders. `close_skill` must be a plain command name on one line, and never `compact-now`. `marker` must be one line. Long text is cut and numbers are capped (`delay_ms` at 60 s, `handoff_max_chars` at 50,000). Nothing from the config is run as a shell command. Anyone who can write your `~/.claude` can already change Claude Code's own `settings.json` hooks, so this is hardening, not a boundary. |
| **The plugin itself changes under you.** | Installing from the marketplace follows the `main` branch, which is protected against force pushes and deletion. To pin a version, clone a release tag (`git clone --branch v0.4.0 …`) and use the installer. Read the code first: it is one file, [`plugin/hooks/register.ts`](plugin/hooks/register.ts). |

What it doesn't protect against: a model that is already following injected instructions from elsewhere (a file, a web page, a repository's `CLAUDE.md`, which Claude Code loads by itself). The handoff copy holds whatever the model wrote into the handoff before saying `Ready to compact.`

Every row above has a test in [`plugin/hooks/register.test.ts`](plugin/hooks/register.test.ts) (the ones named `security: …`), run with `claude plugin test plugin`.

## Reporting a vulnerability

Please don't open a public issue. Use GitHub's private reporting: the **Security** tab of this repository, then **Report a vulnerability** ([direct link](https://github.com/TrenzDev/cc-autocompact/security/advisories/new)). Say what an attacker controls, what they get, and how to reproduce it. I'll reply in the advisory.

Only the latest release gets fixes.
