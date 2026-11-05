// What the mod keeps per session (gone when the session closes).
export type State = {
  // 'wrapping' = /compact-now started a wrap-up and the mod is waiting for it to end
  phase: 'idle' | 'wrapping'
  // who asked for the wrap-up: 'manual' (/compact-now)
  trigger: string
  // when the wrap-up was asked for (ms since epoch)
  wrapStartedAt: number
  // a main-thread turn is running
  inTurn: boolean
  // goes up with every message or turn: if it changes, a scheduled compaction is cancelled
  gen: number
  // just compacted and no turn since
  justCompacted: boolean
  // a compaction is waiting out its delay, and since when
  scheduled: boolean
  scheduledAt: number
  // /compact has been queued and its result has not been seen yet
  compacting: boolean
  compactingAt: number
  compactBefore: number
  compactTrigger: string
  // marker fallback: what the main thread's Stop event saw in this turn
  stopMarker: boolean
  stopTail: string
  // the session's title in the app, and when it was read
  title: string | null
  titleAt: number
  titleTriedAt: number
  // already warned that the title cannot be found
  titleWarned: boolean
  // already warned that config.json is not valid JSON
  configWarned: boolean
  // already warned that summaries_dir or log_file point outside the mod's folders
  pathWarned: boolean
  // already warned that the Handoff: line in CLAUDE.md is not a .md file inside the project
  handoffWarned: boolean
  // the reminder: the last band of context it asked in (-1 = none)
  remindedBand: number
  // a compaction was cancelled and the model doesn't know yet: it goes with the next message
  cancelOwed: boolean
  // what the compaction waiting out its delay was for ('task_done', 'manual', 'retry'); '' when none
  scheduledTrigger: string
  // the id of the compaction the mod queued last (it goes in every log line about it)
  compactionId: string
  // tokensAfter as the session.compact result reported it for the mod's own /compact; null when absent
  compactTokensAfter: number | null
  // a logged compaction whose context_after was not known yet: its id and its context_before
  // ('' = none). The next measurement with a lower figure appends a "context_after" line.
  afterOwed: string
  afterOwedBefore: number
  // a message or a turn cancelled a compaction: it is tried again once, after the next short main-thread
  // turn, if nothing else comes in during the delay. retryAt is when it was cancelled (expires after 30 min).
  retryOwed: boolean
  retryAt: number
  // tool calls the main thread made in the turn that is running (or last ran)
  turnToolCalls: number
  // when the main thread's last model response ended (its last turn.complete), ms since epoch; null = none yet
  lastCallAt: number | null
  // the model that answered the main thread's last turn ('' = not known yet)
  lastModel: string
  // the last main-thread turn ended with the marker and nothing has compacted since (for idle compaction)
  lastTurnClosed: boolean
  // idle_mode 'ask': the idle question was sent (idleAskedAt) and its turn has not started yet (idleAsking);
  // idleAsked stays true until a turn someone else started; idleTurn = the running turn is the question's
  idleAsked: boolean
  idleAsking: boolean
  idleAskedAt: number
  idleTurn: boolean
  // the last rate-limit readings (percent used, reset time in ms or null)
  fiveHour: { pct: number; resetsAt: number | null } | null
  sevenDay: { pct: number; resetsAt: number | null } | null
  // pacing told a message that did not come from a person to defer work until this window resets
  // ('' = nothing deferred); the resume prompt goes once, a minute after deferredResetsAt
  deferredWindow: '' | 'five_hour' | 'seven_day'
  deferredResetsAt: number
  // the savings ledger (policy.ts Ledger): tokens the last compaction removed, and USD saved and spent
  ledger: { removed: number; model: string | null; saved: number; spent: number; compactions: number }
  // this week's share of it, written to savings/<week>/<session>.json (week = its Monday, UTC)
  weekly: { week: string; saved: number; spent: number; compactions: number; failed: number }
  // the length of compactions.jsonl the last time this session read or wrote it: never write a shorter one back
  logSeenChars: number
  // the note about a cancelled compaction reached the model since the last cancellation (then no retry: it chose)
  cancelNoteDelivered: boolean
  // a turn other than the /compact started while the mod's /compact was queued: the compaction is skipped
  compactOvertaken: boolean
  // the id of the last main-thread turn that started as /compact, and of the running main-thread turn
  compactTurnId: string
  turnId: string
  // the context the last compaction left (measured), null if none yet: for the policy's economics
  lastCompactAfter: number | null
  // gen right after the idle question was submitted: its turn counts as the question's only if nothing came in since
  askGen: number
  // counts messages only (gen also counts turns): a resume prompt is skipped if any message came after the deferral
  msgGen: number
  deferredMsgGen: number
  // the compaction owed a context_after was not the mod's (then the ledger only forgets the old saving)
  afterOwedApp: boolean
  // already said once that the shared compactions.jsonl is past 2 MiB and no longer written
  sharedLogWarned: boolean
}

// config.json. Every key is optional: a missing file or key takes the default (see the README).
export type Config = {
  enabled: boolean
  // a toast and a line in debug.jsonl at every main-thread turn end
  debug: boolean
  sessions: string[]
  min_context_tokens: number
  delay_ms: number
  // the skill /compact-now runs, with arguments if any ("wrap-up", "my-close light")
  close_skill: string
  // the last line that means "the task is closed and saved"
  marker: string
  compact_instructions: string
  // where compaction summaries are saved: "" = <claude dir>/compaction-summaries, "off" = not saved;
  // any other folder must be inside <claude dir>
  summaries_dir: string
  // put the handoff back into the context after a compaction or a /clear
  reinject_handoff: boolean
  // the longest handoff that is put back, in characters (500 to 50,000)
  handoff_max_chars: number
  // the compaction log: "" = <claude dir>/cc-autocompact/compactions.jsonl; any other is a .jsonl inside that folder
  log_file: string
  app_sessions_dir: string
  // switch for the reminder and for the note about a cancelled compaction
  reminder: boolean
  // the context the reminder starts asking at (or 40% of the window, if that is less)
  reminder_tokens: number
  // how many tokens more before it asks again (or 10% of the window, if that is less)
  reminder_every_tokens: number
  // a compaction cancelled by a message is tried again after the next turn only if that turn made at most
  // this many tool calls (a short answer, not new work)
  retry_max_tool_calls: number
  // the policy (policy.ts PolicyParams): requests expected after a closed task, returns after the cache expired,
  // the margin saving / cost must reach, and what a compaction leaves behind
  expected_calls: number
  expected_cold_returns: number
  margin: number
  post_compact_tokens: number
  post_compact_cached_tokens: number
  summary_tokens: number
  // compact at a turn end even without a closed task when the window is this full (0.1 to 1)
  hard_cap_share: number
  // idle compaction: after this many minutes without a request; 'ask' | 'closed' | 'any' | 'off';
  // idle_min_tokens is the floor for asking (or compacting with 'any') mid-task
  idle_minutes: number
  idle_mode: 'ask' | 'closed' | 'any' | 'off'
  idle_min_tokens: number
  // how long the main conversation's prompt cache lives (60 min on a subscription; 5 min is used on extra usage)
  main_cache_ttl_minutes: number
  // pacing near the usage limits, for messages that did not come from a person
  pacing: boolean
  five_hour_light_pct: number
  five_hour_hold_pct: number
  seven_day_light_pct: number
  seven_day_hold_pct: number
  // USD per point of usage, for the weekly line (null = no points)
  usd_per_point: number | null
}

declare module 'claude-code' {
  interface PluginState {
    'cc-autocompact': { state: Shaped<State> }
  }
}
