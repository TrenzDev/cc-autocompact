import { expect, test } from 'claude-code/testing'

import {
  decide,
  economics,
  isPerson,
  pace,
  PACE_DEFAULTS,
  POLICY_DEFAULTS,
  type Limit,
  type PaceParams,
  type PolicyInput,
  type PolicyParams,
} from './policy'

// Property-style tests: thousands of random inputs from a small deterministic PRNG (mulberry32),
// so a failure always replays the same way. The seed and the case number go into every message.

const prng = (seed: number) => {
  let a = seed >>> 0
  const next = () => {
    a = (a + 0x6d2b79f5) >>> 0
    let t = a
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
  const int = (lo: number, hi: number) => lo + Math.floor(next() * (hi - lo + 1))
  const pick = <T>(xs: readonly T[]): T => xs[Math.floor(next() * xs.length)]
  const bool = (pTrue = 0.5) => next() < pTrue
  return { next, int, pick, bool }
}
type Rng = ReturnType<typeof prng>

const N = 5000
const MIN = 60_000
const H = 3_600_000
const NOW = 1_800_000_000_000

const MODELS = [
  'claude-fable-5-1',
  'claude-mythos-5-1',
  'claude-fable-5',
  'claude-opus-5-5',
  'claude-opus',
  'claude-sonnet-5-5',
  'claude-sonnet-5',
  'claude-sonnet',
  'claude-haiku-5-5',
  'claude-haiku',
] as const
const ANY_MODEL = [...MODELS, 'claude-opus-4-20250514', 'some-unknown-model', '', undefined] as const

const randParams = (r: Rng): PolicyParams => ({
  expected_calls: r.int(0, 120),
  expected_cold_returns: r.int(0, 8),
  margin: r.pick([0.5, 1, 1, 1.5, 2, 3]),
  min_context_tokens: r.int(0, 250_000),
  post_compact_tokens: r.int(50_000, 150_000),
  post_compact_cached_tokens: r.int(0, 50_000),
  summary_tokens: r.int(0, 60_000),
  hard_cap_share: 0.5 + r.next() * 0.5,
  idle_ms: r.int(0, 90) * MIN,
  idle_mode: r.pick(['closed', 'ask', 'any', 'off'] as const),
  idle_any_min_tokens: r.int(0, 600_000),
  ttl_margin_ms: r.int(0, 10) * MIN,
})

const randLimit = (r: Rng): Limit | null => (r.bool(0.3) ? null : { pct: r.int(0, 110), resetsAt: r.bool(0.2) ? null : NOW + r.int(0, 5 * H) })

const randInput = (r: Rng, over: Partial<PolicyInput> = {}): PolicyInput => ({
  now: NOW,
  contextTokens: r.bool(0.1) ? null : r.int(0, 1_200_000),
  windowTokens: r.pick([0, 0, 200_000, 1_000_000, 1_000_000, r.int(100_000, 2_000_000)]),
  lastCallAt: r.bool(0.1) ? null : NOW - r.int(0, 3 * H),
  taskClosed: r.bool(),
  turnRunning: r.bool(0.2),
  justCompacted: r.bool(0.2),
  cacheTtlMs: r.pick([5 * MIN, H, H]),
  fiveHour: randLimit(r),
  sevenDay: randLimit(r),
  trigger: r.pick(['turn_end', 'idle', 'idle', 'manual'] as const),
  model: r.pick(ANY_MODEL),
  workRunning: r.pick([undefined, false, false, true]),
  askedSinceLastTurn: r.pick([undefined, false, true]),
  ...over,
})

const ACTIONS = ['compact', 'ask', 'wait', 'none']

test('stress: never compacts with a turn running, right after a compaction, or without a context figure', () => {
  const r = prng(1)
  let checked = 0
  for (let i = 0; i < N; i++) {
    const p = r.bool(0.3) ? POLICY_DEFAULTS : randParams(r)
    const which = r.int(0, 2)
    const over: Partial<PolicyInput> =
      which === 0 ? { turnRunning: true } : which === 1 ? { justCompacted: true } : { contextTokens: null }
    const d = decide(randInput(r, over), p)
    expect(ACTIONS.includes(d.action)).toBe(true)
    if (d.action === 'compact') throw new Error(`case ${i} (${JSON.stringify(over)}): compacted: ${d.reason}`)
    checked++
  }
  expect(checked).toBe(N)
})

test('stress: at a turn end with the task open, it compacts if and only if the window is nearly full (0 is 1M)', () => {
  const r = prng(2)
  let compacts = 0
  for (let i = 0; i < N; i++) {
    const p = r.bool(0.3) ? POLICY_DEFAULTS : randParams(r)
    const inp = randInput(r, { trigger: 'turn_end', taskClosed: false, turnRunning: false, justCompacted: false })
    if (inp.contextTokens === null) inp.contextTokens = r.int(0, 1_200_000)
    const window = inp.windowTokens > 0 ? inp.windowTokens : 1_000_000
    // at a real turn end the last request has just finished, so the cache is warm
    inp.lastCallAt = inp.now
    inp.workRunning = false
    const full = inp.contextTokens >= p.hard_cap_share * window
    const d = decide(inp, p)
    if ((d.action === 'compact') !== full) {
      throw new Error(`case ${i}: ctx ${inp.contextTokens} window ${inp.windowTokens} cap ${p.hard_cap_share}: ${d.action} (${d.reason})`)
    }
    if (d.action === 'compact') compacts++
  }
  // the generator does reach both sides
  expect(compacts > 100 && compacts < N - 100).toBe(true)
})

test('stress: idle never compacts or asks with the cache about to expire, no last call, or not idle long enough', () => {
  const r = prng(3)
  const counts = [0, 0, 0]
  for (let i = 0; i < N; i++) {
    const p = randParams(r)
    if (r.bool(0.3)) p.idle_mode = r.pick(['ask', 'any'] as const)
    const ttl = r.pick([5 * MIN, H, 2 * H])
    const which = r.int(0, 2)
    let lastCallAt: number | null
    if (which === 0) {
      // at or past ttl - margin
      lastCallAt = NOW - Math.max(0, ttl - p.ttl_margin_ms) - r.int(0, 2 * H)
    } else if (which === 1) {
      lastCallAt = null
    } else {
      // under idle_ms (possibly a clock that went backwards)
      lastCallAt = NOW - (p.idle_ms > 0 ? r.int(0, p.idle_ms - 1) : 0) + (r.bool(0.1) ? r.int(1, H) : 0)
      if (p.idle_ms === 0) lastCallAt = NOW + r.int(1, H)
    }
    const inp = randInput(r, { trigger: 'idle', lastCallAt, cacheTtlMs: ttl, turnRunning: false, justCompacted: false })
    if (r.bool(0.5)) inp.askedSinceLastTurn = false
    const d = decide(inp, p)
    if (d.action === 'compact' || d.action === 'ask') {
      throw new Error(`case ${i} (kind ${which}): idle ${lastCallAt === null ? 'null' : NOW - lastCallAt} ttl ${ttl}: ${d.action} (${d.reason})`)
    }
    counts[which]++
  }
  expect(counts.every((c) => c > N / 5)).toBe(true)
})

test("stress: 'ask' only on idle in idle_mode 'ask', never twice before a turn, never under idle_any_min_tokens", () => {
  const r = prng(4)
  let asks = 0
  for (let i = 0; i < 4 * N; i++) {
    const p = randParams(r)
    // bias towards inputs that can reach 'ask': warm cache, idle long enough, open task
    const inp = randInput(r)
    if (r.bool(0.6)) {
      inp.trigger = 'idle'
      inp.turnRunning = false
      inp.justCompacted = false
      inp.workRunning = r.pick([undefined, false])
      inp.taskClosed = r.bool(0.2)
      inp.cacheTtlMs = H
      p.ttl_margin_ms = r.int(0, 5) * MIN
      p.idle_ms = r.int(0, 40) * MIN
      inp.lastCallAt = NOW - p.idle_ms - r.int(0, 10) * MIN
      p.margin = r.pick([0.5, 1])
      p.expected_calls = r.int(20, 120)
    }
    const d = decide(inp, p)
    if (d.action !== 'ask') continue
    asks++
    expect(inp.trigger).toBe('idle')
    expect(p.idle_mode).toBe('ask')
    expect(inp.askedSinceLastTurn === true).toBe(false)
    expect(inp.contextTokens !== null && inp.contextTokens >= p.idle_any_min_tokens).toBe(true)
  }
  expect(asks > 100).toBe(true)
})

test('stress: a closed task at a turn end that compacts at C also compacts at any larger C', () => {
  const r = prng(5)
  let compacting = 0
  for (let i = 0; i < N / 5; i++) {
    const p = r.bool(0.3) ? POLICY_DEFAULTS : randParams(r)
    const inp = randInput(r, { trigger: 'turn_end', taskClosed: true, turnRunning: false, justCompacted: false })
    // a sorted sweep of contexts from 0 to 2M, plus random points
    const cs = [...Array.from({ length: 41 }, (_, j) => j * 50_000), ...Array.from({ length: 40 }, () => r.int(0, 2_000_000))].sort((a, b) => a - b)
    let seen: number | null = null
    for (const c of cs) {
      const a = decide({ ...inp, contextTokens: c }, p).action
      if (a === 'compact') {
        if (seen === null) seen = c
        compacting++
      } else if (seen !== null) {
        throw new Error(`case ${i}: compacts at ${seen} but not at ${c} (${a}); model ${inp.model} window ${inp.windowTokens} work ${inp.workRunning}`)
      }
    }
  }
  expect(compacting > 0).toBe(true)
})

test('stress: a simulated session never compacts twice without a turn between, nor more often than it has turns', () => {
  const r = prng(6)
  let totalCompactions = 0
  let totalIdleCompactions = 0
  for (let s = 0; s < 300; s++) {
    const p = r.bool(0.3) ? { ...POLICY_DEFAULTS } : randParams(r)
    if (r.bool(0.3)) p.idle_mode = 'any'
    const model = r.pick(ANY_MODEL)
    const windowTokens = r.pick([0, 200_000, 1_000_000])
    const cacheTtlMs = r.pick([5 * MIN, H, H])
    let now = NOW
    let ctx: number | null = r.bool(0.5) ? null : r.int(20_000, 120_000)
    let lastCallAt: number | null = null
    let justCompacted = false
    let askedSinceLastTurn = false
    let taskClosed = false
    let turns = 0
    let compactions = 0
    let compactedSinceTurn = false
    const compact = (why: string) => {
      if (compactedSinceTurn) throw new Error(`session ${s}: second compaction without a turn (${why})`)
      compactions++
      compactedSinceTurn = true
      ctx = r.bool(0.3) ? null : 107_000 + r.int(-5_000, 5_000)
      justCompacted = true
      lastCallAt = now
    }
    const base = () => ({ now, contextTokens: ctx, windowTokens, lastCallAt, taskClosed, justCompacted, cacheTtlMs, fiveHour: null, sevenDay: null, model, askedSinceLastTurn })
    for (let step = 0; step < 200; step++) {
      const ev = r.int(0, 9)
      if (ev < 5) {
        // a turn: it runs (a check meanwhile must not compact), then ends with a bigger context
        if (decide({ ...base(), turnRunning: true, trigger: r.pick(['turn_end', 'idle'] as const) }, p).action === 'compact') {
          throw new Error(`session ${s}: compacted while a turn ran`)
        }
        now += r.int(1, 15) * MIN
        turns++
        compactedSinceTurn = false
        justCompacted = false
        askedSinceLastTurn = false
        ctx = (ctx ?? 107_000) + r.int(1_000, 120_000)
        if (windowTokens > 0) ctx = Math.min(ctx, windowTokens)
        lastCallAt = now
        taskClosed = r.bool(0.4)
        const d = decide({ ...base(), turnRunning: false, trigger: 'turn_end' }, p)
        if (d.action === 'compact') compact('turn_end')
      } else {
        // an idle tick
        now += r.int(1, 70) * MIN
        const d = decide({ ...base(), turnRunning: false, trigger: 'idle' }, p)
        if (d.action === 'compact') {
          compact('idle')
          totalIdleCompactions++
        } else if (d.action === 'ask') {
          if (askedSinceLastTurn) throw new Error(`session ${s}: asked twice without a turn`)
          askedSinceLastTurn = true
        }
      }
      if (compactions > turns) throw new Error(`session ${s}: ${compactions} compactions in ${turns} turns`)
    }
    totalCompactions += compactions
  }
  expect(totalCompactions > 100).toBe(true)
  expect(totalIdleCompactions > 0).toBe(true)
})

test('stress: pace never drops a level when either percentage rises', () => {
  const r = prng(7)
  const rank = { normal: 0, light: 1, hold: 2 }
  for (let i = 0; i < N; i++) {
    const pp: PaceParams = r.bool(0.4)
      ? PACE_DEFAULTS
      : { five_hour_light_pct: r.int(50, 100), five_hour_hold_pct: r.int(50, 100), seven_day_light_pct: r.int(50, 100), seven_day_hold_pct: r.int(50, 100) }
    const f = randLimit(r)
    const w = randLimit(r)
    const before = rank[pace(f, w, pp).level]
    const up = (l: Limit | null): Limit | null => (l === null ? (r.bool(0.5) ? null : { pct: r.int(0, 110), resetsAt: null }) : { ...l, pct: l.pct + r.int(0, 30) })
    // null only ever turns into a figure here when the other side stays put, so: raise one side
    const raiseFive = r.bool()
    const f2 = raiseFive ? (f === null ? null : up(f)) : f
    const w2 = raiseFive ? w : w === null ? null : up(w)
    const after = rank[pace(f2, w2, pp).level]
    if (after < before) throw new Error(`case ${i}: ${JSON.stringify({ f, w })} -> ${JSON.stringify({ f2, w2 })} dropped ${before} -> ${after}`)
    // both raised at once
    const both = rank[pace(f === null ? null : up(f), w === null ? null : up(w), pp).level]
    if (both < before) throw new Error(`case ${i}: raising both dropped ${before} -> ${both}`)
    const p2 = pace(f2, w2, pp)
    if (p2.level === 'normal') expect(p2.window).toBe(null)
    else expect(p2.pct).toBe(p2.window === 'seven_day' ? w2!.pct : f2!.pct)
  }
})

test('stress: isPerson is true for people, false for everything else', () => {
  for (const o of ['composer', 'bridge', 'sdk', 'channel', 'auto-continuation']) expect(isPerson(o)).toBe(true)
  for (const o of ['peer', 'peer-send-message', 'scheduled-trigger', 'task-notification', 'plugin', 'unclassified', '', 'Composer', 'composer '])
    expect(isPerson(o)).toBe(false)
})

test('stress: economics is finite and non-negative from 0 to 2M for every model, known or not', () => {
  const r = prng(8)
  for (const model of ANY_MODEL) {
    for (let i = 0; i < 1000; i++) {
      const ctx = i < 41 ? i * 50_000 : r.int(0, 2_000_000)
      const p = i % 2 === 0 ? POLICY_DEFAULTS : randParams(r)
      const e = economics(ctx, model, p)
      for (const [name, v] of [['cost', e.cost], ['saving', e.saving], ['perCall', e.perCall], ['perColdReturn', e.perColdReturn]] as const) {
        if (!Number.isFinite(v) || v < 0) throw new Error(`${model} at ${ctx}: ${name} = ${v}`)
      }
      expect(e.breakEvenCalls >= 0).toBe(true)
    }
  }
})
