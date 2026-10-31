# Measurement method

How I measured the context cost that motivated cc-autocompact, and how to repeat it on your own data with [`tools/measure_context.py`](../tools/measure_context.py). This document has no one's session data: only the method and, at the end, the aggregate percentages from my reference week.

Those percentages are one user's measurements from one week of heavy use. Your numbers will differ. The savings figures at the end come from a simulation, not from savings I observed.

## Data source

Claude Code stores each session as a `.jsonl` file in `~/.claude/projects/<project folder>/`. Subagents have their own file in `<session>/subagents/`. Each model reply carries a `usage` block with the tokens of that API call:

| `usage` field | What it is |
| --- | --- |
| `input_tokens` | New input that does not go through the cache (usually close to zero) |
| `cache_creation_input_tokens` | Context written to the cache in that call, with its `ephemeral_5m` and `ephemeral_1h` breakdown |
| `cache_read_input_tokens` | Context read from the cache |
| `output_tokens` | Model output, including reasoning |

Compactions are stored as `system` records with subtype `compact_boundary`, carrying `trigger` (manual or auto), `preTokens` (context before) and `postTokens` (size of the summary).

The script reads those fields and nothing else. It never prints or stores message text.

## Definitions

- **Turn**: one API call, that is, one assistant message. The same message can appear on several lines (it arrives in pieces); it is counted once, using the maximum of each field.
- **Duplicates across files**: when you fork a session, the new one copies the history of the old one. Messages are identified by `message.id` and counted once across the whole set.
- **Context of a turn**: new input + cache write + cache read. It is what the model "sees" in that call.
- **Equivalent cost**: the tokens of each turn at the API list price of its model, with cache writes at 1.25x (5 minutes) or 2x (1 hour) of the input price. **It is not a bill** and not what a subscription deducts: use it to compare what weighs more than what. The prices are at the top of the script and can be changed with `--prices`.
- **Window**: a turn counts if it starts inside the window. A session opened before the window still contributes its context, but only its turns inside the window are counted.

## How the cost is split

Each turn is divided into four parts:

| Part | Calculation |
| --- | --- |
| Output | `output_tokens` at the output price |
| Cache reads | `cache_read_input_tokens` at the read price |
| Rewriting of old context | The part of the input and cache write that is not explained by the growth of the context since the previous turn: context that was already there and had to be written again because the cache expired or was invalidated |
| New context | The rest of the input and cache write: what the turn really adds (tool results, messages) |

**Carry** = cache reads + rewriting of old context. It is what you pay for carrying earlier context along.

The rewriting is calculated by comparing each turn with the previous one in the same file: `extra = max(input + cache_write - max(context - previous_context, 0), 0)`. It is not counted after a compaction, nor when the context drops by more than 30% (that is a reset, not a miss).

## Cache misses by pause length

For turns that already carried 100k or more of context, the script looks at the time since the end of the previous turn (under 5 minutes, 5 to 60, over 60). A miss is a turn that rewrites more than 20% of the previous context and more than 20k tokens. Its extra cost is what rewriting cost compared with what reading it from the cache would have cost.

It shows whether the 1-hour cache holds up across your pauses, and what it costs to return to a big session the next day.

## Compactions

For each `compact_boundary` in the window: the trigger, the context before (`preTokens`), the size of the summary (`postTokens`) and the real context of the first turn afterwards. That last figure includes the summary and everything Claude Code reloads by itself (system prompt, tools, `CLAUDE.md`, memory, recent files and whatever hooks add). The difference between the last two figures is your "base": what you pay on every turn even if the conversation is empty.

## Usage

```powershell
python tools\measure_context.py                         # last 7 days up to now
python tools\measure_context.py --days 14
python tools\measure_context.py --until 2026-10-31T12:00:00Z
python tools\measure_context.py --titles --top 25       # with session titles (do not share the output)
python tools\measure_context.py --json figures.json     # also save all the figures as JSON
python tools\measure_context.py --prices prices.json    # {"claude-opus-5-5": [4.0, 20.0, 0.20], ...}
```

It takes a few seconds per hundred files. The output is Markdown: a summary, cost by context size, cache misses by pause, compactions and the most expensive sessions.

## Before and after

```powershell
python tools\measure_context.py --compare BEFORE_FROM BEFORE_UNTIL AFTER_FROM AFTER_UNTIL --log <the mod's compactions.jsonl>
```

Dates are ISO with a time zone (`2026-11-01T00:00:00+01:00`). It loads the transcripts once and prints the two windows side by side: cost per day, the share spent carrying context (all, and main threads alone), context per main-thread turn, turns above 200k and 400k, cost per main-thread turn, main-thread cost per 1k output tokens, compactions and what they cost, and the share lost to reopening after an hour. `--json` saves every figure; `--figures` writes the file that `assets/make_assets.py --figures` turns into the README chart.

Two weeks of real work are not a controlled test. As a check, I ran it on two weeks before the plugin existed (18 to 24 October against 25 to 31 October): the share spent carrying context went from 80% to 67%, and the cost per 1k output tokens of the main threads fell 41%, with nothing installed. Different tasks, models and hours move these figures more than any plugin would. So the comparison also prints a direct estimate:

**What the mod's own compactions saved.** For each compaction in the mod's log, it finds the compaction in that session's transcript, the context before it and the context on the next turn. Every later turn of that session, until its next compaction or the end of the window, would have read that difference from the cache. It stops counting once the context it would have had passes 95% of a 1M window, where Claude Code's own auto-compact would have fired anyway. It then takes off the compaction's own request, as a range (reading the conversation from the cache, or writing it again at the 1 h price, plus the summary as output). The result is a lower bound on the carrying removed: it leaves out the larger cache rewrites after long pauses, and it assumes each session would have gone on the same way.

On the one compaction of the first live run (31 October, 779,856 tokens before, 122,599 on the next turn) it gives: 657k tokens dropped, 61 later turns, $8.02 not re-read, minus $0.79 to $6.87 for the compaction, net $1.15 to $7.23.

## The simulation from the original study

The original study also included a simulation. It is not in the script because it relied on markers specific to one workflow. The method, in case you want to reproduce it:

1. Each main session is simulated on its own; subagents do not change.
2. The session is cut before a turn (it ends and a new one starts from a 30k handoff) when there is a task boundary: a pause of more than 30 minutes, or a message that marks the end of a task. Optionally, also when a context threshold is passed, only at a safe point (the previous turn ended with no pending tools).
3. Each cut costs one extra turn in the old session (reading its context and writing the handoff).
4. After each cut, every turn adds the same context as it did in reality.
5. Validation: with all the rules switched off, the simulator reproduced the real cost with a deviation of 0.09%.

It is an upper bound: it assumes the handoff is enough to continue the work, and it does not measure quality.

## Results from the reference week

One week of heavy use by one user, main sessions and subagents together. Everything below is measured except the last bullet, which comes from the simulation above.

- Carrying context: **67%** of the equivalent cost (cache reads 46%, rewriting 21%). Output 16%, new context 17%. Cache reads were 97% of the tokens.
- Context per turn: median 265k, mean 307k.
- 68% of turns ran above 200k and accounted for 82% of the cost.
- Cost per turn: x3 between the 100-200k band and the over-600k band. The carry part, x5. The useful work per turn stayed flat.
- Pauses: with under 5 minutes, the cache missed on 0% of the large turns; from 5 to 60 minutes, on 4%; over 60, on 99%. Those reopenings were 18% of the cost.
- Compactions: on average at 520k, three out of four manual. Summary of about 30k.
- Simulation (not observed savings): closing at task boundaries with a 30k handoff saved 33%; adding a 300k threshold raised it to 35%. Range across assumptions (handoff from 20k to 60k, threshold from 200k to 400k): 28% to 37%. The threshold alone saved 26% at 300k and dropped to 11% at 500k.

## Limitations

- The amounts are list prices. If you use a subscription, how it weighs each token type in your limits is not documented: rely on the percentages and the order of magnitude.
- The request that generates each compaction summary does not appear in `usage`, so it is not counted.
- The `.jsonl` format is internal to Claude Code and can change between versions.
- Claude Code deletes old transcripts according to `cleanupPeriodDays` (30 days by default): you can only measure what is still on disk.
