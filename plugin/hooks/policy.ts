// The decision, as pure functions: no `$`, no clock, no files. Everything it needs comes in as
// arguments, so it can be tested on its own and replayed against recorded usage.
//
// Idea: compacting has a cost now (the /compact request reads the whole conversation and writes a
// summary, and the next request rebuilds the cache) and a saving later (every later request reads a
// smaller conversation, and every return after the cache has expired rebuilds a smaller one).
// Compact when the expected saving is larger than the cost. Size alone never decides, except when
// the window is nearly full.
//
// Defaults come from replaying six months of real usage (see the repository's tools/simulate.py):
// after a closed task a session went on for a median of 50 or more requests in every context band,
// with 1 to 7 returns after more than an hour; the context after a compaction was ~107k, of which
// ~44k was still cached.

export type Limit = { pct: number; resetsAt: number | null }

export type PolicyInput = {
  now: number
  // the context of the last request, in tokens (null: not known yet, e.g. right after a compaction)
  contextTokens: number | null
  // the context window (0: unknown, taken as 1M)
  windowTokens: number
  // when the last main-thread request finished (ms), null if none yet
  lastCallAt: number | null
  // the model wrote the close marker at the end of its last answer: the task is closed and saved
  taskClosed: boolean
  // a main-thread turn is running (never compact then)
  turnRunning: boolean
  // compacted and no turn since (never twice in a row)
  justCompacted: boolean
  // how long the main conversation's cache lives (1 h on a subscription, 5 min on extra usage)
  cacheTtlMs: number
  fiveHour: Limit | null
  sevenDay: Limit | null
  // 'turn_end': a main-thread turn has just ended; 'idle': the session has been quiet for a while
  trigger: 'turn_end' | 'idle' | 'manual'
  // the model that answered (for prices); unknown takes the default family
  model?: string
  // work that a compaction could lose: a background task or subagent still running
  workRunning?: boolean
  // idle_mode 'ask': the idle question was already asked and no other turn has run since
  askedSinceLastTurn?: boolean
  // this session's context right after its last compaction, once measured (null: none yet). When it is
  // larger than post_compact_tokens it replaces it in the sums, and it stops the hard cap from looping.
  lastCompactAfter?: number | null
}

export type Decision = {
  // 'ask': the session is idle mid-task; ask the model (one fixed prompt) whether it can wrap up.
  // It compacts only if the model's answer ends with the marker, as at any turn end.
  action: 'compact' | 'ask' | 'wait' | 'none'
  reason: string
  // when action is 'wait': check again after this long
  recheckInMs?: number
  // the figures behind it, for the log (USD at list price)
  cost?: number
  saving?: number
}

export type PolicyParams = {
  // requests expected after a closed task before the next compaction or the end of the session
  expected_calls: number
  // returns after the cache expired, expected over that life
  expected_cold_returns: number
  // compact only if saving >= margin x cost
  margin: number
  // never compact below this context, whatever the sums say
  min_context_tokens: number
  // context after a compaction (base + summary) and the part of it still cached
  post_compact_tokens: number
  post_compact_cached_tokens: number
  // output tokens of the /compact request itself
  summary_tokens: number
  // compact at a turn end even without a closed task when the window is this full (0..1)
  hard_cap_share: number
  // compact while idle: after this long without a request, with the cache still alive
  idle_ms: number
  // 'closed': only if the last answer closed the task; 'ask': if not closed, ask the model whether it
  // can wrap up (it decides; it compacts only on the marker); 'any': compact mid-task without asking
  // (not recommended); 'off'
  idle_mode: 'closed' | 'ask' | 'any' | 'off'
  // for idle_mode 'ask' and 'any': not below this context
  idle_any_min_tokens: number
  // leave this much cache life unused: compacting needs the cache warm
  ttl_margin_ms: number
}

export const POLICY_DEFAULTS: PolicyParams = {
  expected_calls: 50,
  expected_cold_returns: 2,
  margin: 1,
  min_context_tokens: 100_000,
  post_compact_tokens: 107_000,
  post_compact_cached_tokens: 44_000,
  summary_tokens: 33_000,
  hard_cap_share: 0.85,
  idle_ms: 45 * 60_000,
  idle_mode: 'ask',
  idle_any_min_tokens: 300_000,
  ttl_margin_ms: 5 * 60_000,
}

// USD per million tokens: cache read, 1 h cache write, output. Official list prices
// (platform.claude.com/docs/en/about-claude/pricing, November 2026). Only the ratios matter for
// the decision; the figures go to the log.
type Price = { read: number; write1h: number; output: number }
const PRICES: { prefix: string; price: Price }[] = [
  { prefix: 'claude-fable-5-1', price: { read: 0.25, write1h: 20, output: 50 } },
  { prefix: 'claude-mythos-5-1', price: { read: 0.25, write1h: 20, output: 50 } },
  { prefix: 'claude-fable-5', price: { read: 1, write1h: 20, output: 50 } },
  { prefix: 'claude-opus-5-5', price: { read: 0.2, write1h: 8, output: 20 } },
  { prefix: 'claude-opus', price: { read: 0.5, write1h: 10, output: 25 } },
  { prefix: 'claude-sonnet-5-5', price: { read: 0.1, write1h: 4, output: 10 } },
  { prefix: 'claude-sonnet-5', price: { read: 0.2, write1h: 4, output: 10 } },
  { prefix: 'claude-sonnet', price: { read: 0.3, write1h: 6, output: 15 } },
  { prefix: 'claude-haiku-5-5', price: { read: 0.01, write1h: 0.2, output: 0.5 } },
  { prefix: 'claude-haiku', price: { read: 0.1, write1h: 2, output: 5 } },
]
const DEFAULT_PRICE = PRICES[3].price

export const priceOf = (model: string | undefined): Price => {
  if (model === undefined) return DEFAULT_PRICE
  // `includes`, not `startsWith`: provider ids carry a prefix (us.anthropic.claude-...) or a suffix
  for (const p of PRICES) if (model.includes(p.prefix)) return p.price

  return DEFAULT_PRICE
}

const k = (n: number) => `${Math.round(n / 1000)}k`

// What a compaction at `ctx` costs and what it is expected to save, in USD.
//   cost   = ctx * read            (the /compact request reads the conversation from cache)
//          + summary * output      (it writes the summary)
//          + (post - cached) * (write - read)   (the next request rebuilds the cache)
//   saving = (ctx - post) * (calls * read + cold * (write - read))
// Break-even: calls* = (cost - cold * D * (write - read)) / (D * read), with D = ctx - post.
export const economics = (ctx: number, model: string | undefined, p: PolicyParams) => {
  const pr = priceOf(model)
  const r = pr.read / 1e6
  const w = pr.write1h / 1e6
  const o = pr.output / 1e6
  const d = Math.max(0, ctx - p.post_compact_tokens)
  const cost = ctx * r + p.summary_tokens * o + Math.max(0, p.post_compact_tokens - p.post_compact_cached_tokens) * (w - r)
  const perCall = d * r
  const perColdReturn = d * (w - r)
  const saving = p.expected_calls * perCall + p.expected_cold_returns * perColdReturn
  const breakEvenCalls = perCall > 0 ? Math.max(0, (cost - p.expected_cold_returns * perColdReturn) / perCall) : Number.POSITIVE_INFINITY

  return { cost, saving, perCall, perColdReturn, breakEvenCalls }
}

// The smallest context at which compacting a closed task pays, for a model (for the docs and doctor)
export const breakEvenContext = (model: string | undefined, p: PolicyParams): number => {
  let lo = p.post_compact_tokens
  let hi = 2_000_000
  for (let i = 0; i < 40; i++) {
    const mid = (lo + hi) / 2
    const e = economics(mid, model, p)
    if (e.saving >= p.margin * e.cost) hi = mid
    else lo = mid
  }

  return Math.round(hi)
}

const cacheAlive = (inp: PolicyInput, p: PolicyParams): boolean =>
  // the margin never eats more than half the lifetime (a 5-minute cache would otherwise never count as alive)
  inp.lastCallAt !== null && inp.now - inp.lastCallAt < inp.cacheTtlMs - Math.min(p.ttl_margin_ms, inp.cacheTtlMs / 2)

export function decide(inp: PolicyInput, p: PolicyParams = POLICY_DEFAULTS): Decision {
  const ctx = inp.contextTokens
  if (inp.justCompacted) return { action: 'none', reason: 'just compacted, no turn since' }
  if (ctx === null) return { action: 'none', reason: 'context not known yet' }
  if (inp.turnRunning) {
    return inp.taskClosed ? { action: 'wait', reason: 'a turn is running', recheckInMs: 60_000 } : { action: 'none', reason: 'a turn is running' }
  }
  const window = inp.windowTokens > 0 ? inp.windowTokens : 1_000_000
  // what this session really drops to after compacting, once known (never assume it drops lower)
  const after = typeof inp.lastCompactAfter === 'number' && inp.lastCompactAfter > 0 ? inp.lastCompactAfter : null
  const pp = after !== null && after > p.post_compact_tokens ? { ...p, post_compact_tokens: after } : p
  const e = economics(ctx, inp.model, pp)
  const figures = { cost: round2(e.cost), saving: round2(e.saving) }

  if (inp.trigger === 'manual') return { action: 'compact', reason: 'asked for', ...figures }
  if (inp.trigger === 'idle') {
    if (p.idle_mode === 'off') return { action: 'none', reason: 'idle compaction is off', ...figures }
    if (!cacheAlive(inp, p)) return { action: 'none', reason: 'cache already cold: compacting now costs a full rewrite', ...figures }
  } else if (inp.lastCallAt !== null && inp.now - inp.lastCallAt >= inp.cacheTtlMs) {
    // a re-check long after the turn ended: the cache is cold, compacting now would rewrite it all
    return { action: 'none', reason: 'cache already cold at the re-check', ...figures }
  }
  // the hard cap only fires if compacting would really free room: never right after a compaction that
  // left the context still near the cap (that would compact after every turn)
  const capStep = Math.max(50_000, 0.05 * window)
  const atCap = ctx >= p.hard_cap_share * window && (after === null || ctx >= after + capStep)
  // background work could be lost: wait. Only a turn end with the window nearly full may go ahead.
  if (inp.workRunning === true && (inp.trigger === 'idle' || !atCap)) {
    return { action: 'wait', reason: 'background work still running', recheckInMs: 5 * 60_000, ...figures }
  }

  if (inp.trigger === 'turn_end') {
    if (atCap) return { action: 'compact', reason: `window nearly full (${k(ctx)} of ${k(window)})`, ...figures }
    if (ctx >= p.hard_cap_share * window && !inp.taskClosed) {
      return { action: 'none', reason: `near the cap but the last compaction only got to ${k(after ?? 0)}`, ...figures }
    }
    if (!inp.taskClosed) return { action: 'none', reason: 'task not closed', ...figures }
    if (ctx < p.min_context_tokens) return { action: 'none', reason: `under the floor (${k(ctx)} < ${k(p.min_context_tokens)})`, ...figures }
    if (e.saving < p.margin * e.cost) {
      return { action: 'none', reason: `does not pay at ${k(ctx)} (saves ${usd(e.saving)}, costs ${usd(e.cost)})`, ...figures }
    }

    return { action: 'compact', reason: `task closed at ${k(ctx)}: saves ${usd(e.saving)} for ${usd(e.cost)}`, ...figures }
  }

  // idle (off and cold cache already handled above)
  const idleFor = inp.lastCallAt === null ? 0 : inp.now - inp.lastCallAt
  if (idleFor < p.idle_ms) return { action: 'wait', reason: 'not idle long enough', recheckInMs: p.idle_ms - idleFor, ...figures }
  if (ctx < p.min_context_tokens) return { action: 'none', reason: `under the floor (${k(ctx)})`, ...figures }
  if (inp.taskClosed) {
    if (e.saving < p.margin * e.cost) return { action: 'none', reason: `idle, does not pay at ${k(ctx)}`, ...figures }

    return { action: 'compact', reason: `idle ${Math.round(idleFor / 60_000)} min after a closed task at ${k(ctx)}`, ...figures }
  }
  if (p.idle_mode === 'closed') return { action: 'none', reason: 'idle, but the task is not closed', ...figures }
  if (ctx < p.idle_any_min_tokens) return { action: 'none', reason: `idle mid-task under ${k(p.idle_any_min_tokens)}`, ...figures }
  if (e.saving < p.margin * e.cost) return { action: 'none', reason: `idle mid-task, does not pay at ${k(ctx)}`, ...figures }
  if (p.idle_mode === 'ask') {
    if (inp.askedSinceLastTurn === true) return { action: 'none', reason: 'already asked; waiting for a new turn', ...figures }

    return { action: 'ask', reason: `idle ${Math.round(idleFor / 60_000)} min mid-task at ${k(ctx)}: asking whether it can wrap up`, ...figures }
  }

  return { action: 'compact', reason: `idle ${Math.round(idleFor / 60_000)} min mid-task at ${k(ctx)} (idle_mode any)`, ...figures }
}

// ------------------------------------------------------------------------------------------------
// Pacing near the 5-hour and weekly limits. It never blocks a person: it only says how heavy new
// work started by something other than a person (another session, a schedule) should be.
// ------------------------------------------------------------------------------------------------
export type PaceParams = {
  five_hour_light_pct: number
  five_hour_hold_pct: number
  seven_day_light_pct: number
  seven_day_hold_pct: number
}

export const PACE_DEFAULTS: PaceParams = {
  five_hour_light_pct: 85,
  five_hour_hold_pct: 95,
  seven_day_light_pct: 90,
  seven_day_hold_pct: 97,
}

export type Pace = {
  // 'normal': nothing to say; 'light': finish what is running, start nothing heavy; 'hold': finish
  // the current step, write down what is left, and pick it up after the reset
  level: 'normal' | 'light' | 'hold'
  window: 'five_hour' | 'seven_day' | null
  pct: number | null
  resetsAt: number | null
}

export function pace(fiveHour: Limit | null, sevenDay: Limit | null, p: PaceParams = PACE_DEFAULTS): Pace {
  const lv = (l: Limit | null, light: number, hold: number) => (l === null ? 0 : l.pct >= hold ? 2 : l.pct >= light ? 1 : 0)
  const a = lv(fiveHour, p.five_hour_light_pct, p.five_hour_hold_pct)
  const b = lv(sevenDay, p.seven_day_light_pct, p.seven_day_hold_pct)
  if (a === 0 && b === 0) return { level: 'normal', window: null, pct: null, resetsAt: null }
  const useWeek = b > a || (b === a && sevenDay !== null)
  const l = (useWeek ? sevenDay : fiveHour) as Limit
  const level = Math.max(a, b) === 2 ? 'hold' : 'light'

  return { level, window: useWeek ? 'seven_day' : 'five_hour', pct: l.pct, resetsAt: l.resetsAt }
}

// Which messages pacing may speak to. A person's message is never held, delayed or reordered;
// pacing only adds a note to messages that did not come from a person.
export const PERSON_ORIGINS = ['composer', 'bridge', 'sdk', 'channel', 'auto-continuation', 'slack-ping']
export const isPerson = (originKind: string): boolean => PERSON_ORIGINS.includes(originKind)
// Pacing speaks only to these (an allow-list: a new origin kind the engine adds is left alone)
export const PACED_ORIGINS = ['peer', 'peer-send-message', 'projects-relay', 'coordinator', 'task-notification', 'scheduled-trigger', 'observer', 'observer-activity']
export const isPaceTarget = (originKind: string): boolean => PACED_ORIGINS.includes(originKind)

// ------------------------------------------------------------------------------------------------
// Savings, measured live. After a compaction from `before` to `after`, every later request would
// have read (before - after) more tokens, and every return after the cache expired would have
// rewritten them. The compaction's own cost is charged once. Until the next compaction.
// ------------------------------------------------------------------------------------------------
export type Ledger = {
  // tokens a request would carry without the last compaction
  removed: number
  model: string | null
  saved: number
  spent: number
  compactions: number
}

export const EMPTY_LEDGER: Ledger = { removed: 0, model: null, saved: 0, spent: 0, compactions: 0 }

export function ledgerOnCompaction(l: Ledger, before: number, after: number, model: string | undefined, p: PolicyParams = POLICY_DEFAULTS): Ledger {
  const e = economics(before, model, { ...p, post_compact_tokens: after })
  // from now on, each request carries (before - after) fewer tokens than it would without this compaction
  return { ...l, removed: Math.max(0, before - after), model: model ?? null, spent: l.spent + e.cost, compactions: l.compactions + 1 }
}

export function ledgerOnRequest(l: Ledger, model: string | undefined, cold: boolean): Ledger {
  if (l.removed <= 0) return l
  const pr = priceOf(model ?? l.model ?? undefined)
  const add = cold ? (l.removed * (pr.write1h - pr.read)) / 1e6 + (l.removed * pr.read) / 1e6 : (l.removed * pr.read) / 1e6

  return { ...l, saved: l.saved + add }
}

const round2 = (x: number) => Math.round(x * 100) / 100
const usd = (x: number) => `$${x.toFixed(2)}`
