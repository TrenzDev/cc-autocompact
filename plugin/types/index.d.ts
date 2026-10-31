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
}

declare module 'claude-code' {
  interface PluginState {
    'cc-autocompact': { state: Shaped<State> }
  }
}
