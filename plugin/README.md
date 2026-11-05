# cc-autocompact

Auto-compact for Claude Code at the end of each task, not when the context window is full.

When the model finishes a task and the next one doesn't need that context, the `wrap-up` skill writes a handoff file and ends the answer with the line `Ready to compact.`. The mod in this plugin sees that line, waits 1.5 seconds (any message from you cancels it) and runs `/compact`. When the compaction is done it saves the summary to `~/.claude/compaction-summaries/<project>/` and puts the handoff back into the fresh context. It also adds `/compact-now`, which wraps up and compacts on demand, and `/cc-doctor`, a read-only check of the setup and the recent log.

From 200k of context, when a message comes in, the model gets a short question next to it: is the task closed, and does what comes next not need this context? It only asks. Size compacts nothing, with one exception: a window about to overflow (85% full by default) compacts at a turn end. And `"reminder": false` turns it off. If the message comes from another session, the model is told not to compact yet: that session never sees the reply, so it does the request, replies if it is waiting, and wraps up after.

If a message cancels a compaction during its 1.5 seconds, the mod tries once more after the next short answer (at most `retry_max_tool_calls` tool calls, 3 by default). Every decision, cancellation, retry and compaction, its own or the app's, is one line in `~/.claude/cc-autocompact/compactions.jsonl`, with the reason and the context before and after, never the text of a message.

In the desktop app: click **+** next to the prompt box, **Add plugins**, and add the marketplace `TrenzDev/cc-autocompact`. In a Claude Code session in the terminal:

```text
/plugin install cc-autocompact --marketplace TrenzDev/cc-autocompact
```

It needs no configuration. Optional settings go in `~/.claude/cc-autocompact/config.json`; see `config.example.json` and the full README at https://github.com/TrenzDev/cc-autocompact.

From 200k the mod asks the model whether the task is closed. For it to close smaller tasks by itself as well, add the "Closing tasks" rule from the README to your `CLAUDE.md`.

No network, no shell, and it writes only inside `~/.claude`. After a compaction it puts back only its own copy of the handoff, taken when your wrap-up ended, never a file a repository brought. The question is fixed text plus a number. Details and private reporting: https://github.com/TrenzDev/cc-autocompact/blob/main/SECURITY.md.
