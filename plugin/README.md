# cc-autocompact

Auto-compact for Claude Code at the end of each task, not when the context window is full.

When the model finishes a task and the next one doesn't need that context, the `wrap-up` skill writes a handoff file and ends the answer with the line `Ready to compact.`. The mod in this plugin sees that line, waits 1.5 seconds (any message from you cancels it) and runs `/compact`. When the compaction is done it saves the summary to `~/.claude/compaction-summaries/<project>/` and puts the handoff back into the fresh context. It also adds `/compact-now`, which wraps up and compacts on demand.

Install it in a Claude Code session in the terminal:

```text
/plugin install cc-autocompact --marketplace TrenzDev/cc-autocompact
```

It needs no configuration. Optional settings go in `~/.claude/cc-autocompact/config.json`; see `config.example.json` and the full README at https://github.com/TrenzDev/cc-autocompact.

For the model to close tasks by itself, add the "Closing tasks" rule from the README to your `CLAUDE.md`.

No network, no shell, and it writes only inside `~/.claude`. After a compaction it puts back only its own copy of the handoff, taken when your wrap-up ended, never a file a repository brought. Details and private reporting: https://github.com/TrenzDev/cc-autocompact/blob/main/SECURITY.md.
