import { expect, test } from 'claude-code/testing'

import {
  breakEvenContext,
  decide,
  economics,
  EMPTY_LEDGER,
  isPaceTarget,
  isPerson,
  ledgerOnCompaction,
  ledgerOnRequest,
  pace,
  POLICY_DEFAULTS,
  type PolicyInput,
} from './policy'

const H = 3_600_000
const NOW = 1_800_000_000_000
const base = (over: Partial<PolicyInput> = {}): PolicyInput => ({
  now: NOW,
  contextTokens: 400_000,
  windowTokens: 1_000_000,
  lastCallAt: NOW - 1000,
  taskClosed: true,
  turnRunning: false,
  justCompacted: false,
  cacheTtlMs: H,
  fiveHour: null,
  sevenDay: null,
  trigger: 'turn_end',
  model: 'claude-opus-5-5',
  ...over,
})

test('policy: a closed task at 400k compacts, and says what it saves and costs', () => {
  const d = decide(base())
  expect(d.action).toBe('compact')
  expect(d.saving! > d.cost!).toBe(true)
})

test('policy: the break-even context sits near 150k for Opus and Sonnet, a bit higher for Fable', () => {
  const opus = breakEvenContext('claude-opus-5-5', POLICY_DEFAULTS)
  const sonnet = breakEvenContext('claude-sonnet-5-5', POLICY_DEFAULTS)
  const fable = breakEvenContext('claude-fable-5-1', POLICY_DEFAULTS)
  expect(opus > 140_000 && opus < 170_000).toBe(true)
  expect(Math.abs(sonnet - opus) < 5_000).toBe(true)
  expect(fable > opus).toBe(true)
})

test('policy: a closed task under the break-even does not compact', () => {
  expect(decide(base({ contextTokens: 130_000 })).action).toBe('none')
  expect(decide(base({ contextTokens: 90_000 })).reason).toContain('floor')
})

test('policy: the saving grows with the context, the cost barely does', () => {
  const a = economics(200_000, 'claude-opus-5-5', POLICY_DEFAULTS)
  const b = economics(600_000, 'claude-opus-5-5', POLICY_DEFAULTS)
  expect(b.saving / a.saving > 4).toBe(true)
  expect(b.cost / a.cost < 1.1).toBe(true)
  // with no cold returns at all, the calls needed to pay it back fall as the context grows
  expect(a.cost / a.perCall > 3 * (b.cost / b.perCall)).toBe(true)
})

test('policy: never mid-task, however big, until the window is nearly full', () => {
  expect(decide(base({ taskClosed: false, contextTokens: 800_000 })).action).toBe('none')
  const full = decide(base({ taskClosed: false, contextTokens: 860_000 }))
  expect(full.action).toBe('compact')
  expect(full.reason).toContain('nearly full')
  // a smaller window: 85 % of 200k
  expect(decide(base({ taskClosed: false, contextTokens: 175_000, windowTokens: 200_000 })).action).toBe('compact')
})

test('policy: never with a turn running; a closed task waits for it', () => {
  expect(decide(base({ turnRunning: true })).action).toBe('wait')
  expect(decide(base({ turnRunning: true, taskClosed: false })).action).toBe('none')
  expect(decide(base({ turnRunning: true, contextTokens: 990_000 })).action).toBe('wait')
})

test('policy: never twice in a row (no loop), and nothing without a context figure', () => {
  expect(decide(base({ justCompacted: true, contextTokens: 990_000 })).action).toBe('none')
  expect(decide(base({ contextTokens: null })).action).toBe('none')
})

test('policy: background work still running makes a closed task wait, unless the window is nearly full', () => {
  expect(decide(base({ workRunning: true })).action).toBe('wait')
  expect(decide(base({ workRunning: true, contextTokens: 900_000, taskClosed: false })).action).toBe('compact')
})

test('policy: idle compaction only with the cache still warm, after idle_ms, and (by default) a closed task', () => {
  const idle = (mins: number, over: Partial<PolicyInput> = {}) =>
    decide(base({ trigger: 'idle', lastCallAt: NOW - mins * 60_000, ...over }))
  expect(idle(20).action).toBe('wait')
  expect(idle(20).recheckInMs).toBe(25 * 60_000)
  expect(idle(50).action).toBe('compact')
  expect(idle(56).action).toBe('none') // past ttl - margin: the cache is about to expire
  expect(idle(90).reason).toContain('cold')
  expect(idle(50, { cacheTtlMs: 5 * 60_000 }).action).toBe('none')
  const closedOnly = { ...POLICY_DEFAULTS, idle_mode: 'closed' as const }
  expect(decide(base({ trigger: 'idle', lastCallAt: NOW - 50 * 60_000, taskClosed: false }), closedOnly).action).toBe('none')
})

test('policy: idle_mode ask (default) asks the model once mid-task above idle_any_min_tokens, never compacts by itself', () => {
  const idle = (ctx: number, over: Partial<PolicyInput> = {}) =>
    decide(base({ trigger: 'idle', lastCallAt: NOW - 46 * 60_000, taskClosed: false, contextTokens: ctx, ...over }))
  expect(idle(250_000).action).toBe('none')
  expect(idle(350_000).action).toBe('ask')
  expect(idle(350_000, { askedSinceLastTurn: true }).action).toBe('none')
  expect(idle(350_000, { workRunning: true }).action).toBe('wait')
  expect(idle(350_000, { lastCallAt: NOW - 70 * 60_000 }).action).toBe('none')
})

test('policy: idle_mode any compacts mid-task only above idle_any_min_tokens; off never', () => {
  const p = { ...POLICY_DEFAULTS, idle_mode: 'any' as const }
  const idle = (ctx: number) => decide(base({ trigger: 'idle', lastCallAt: NOW - 50 * 60_000, taskClosed: false, contextTokens: ctx }), p)
  expect(idle(250_000).action).toBe('none')
  expect(idle(350_000).action).toBe('compact')
  const off = { ...POLICY_DEFAULTS, idle_mode: 'off' as const }
  expect(decide(base({ trigger: 'idle', lastCallAt: NOW - 50 * 60_000 }), off).action).toBe('none')
})

test('policy: manual always compacts unless a turn runs or it just compacted', () => {
  expect(decide(base({ trigger: 'manual', contextTokens: 20_000, taskClosed: false })).action).toBe('compact')
  expect(decide(base({ trigger: 'manual', turnRunning: true })).action).not.toBe('compact')
  expect(decide(base({ trigger: 'manual', justCompacted: true })).action).toBe('none')
})

test('policy: an unknown model takes the default prices instead of failing', () => {
  expect(decide(base({ model: 'some-future-model' })).action).toBe('compact')
  expect(decide(base({ model: undefined })).action).toBe('compact')
})

test('pace: thresholds for 5 h and week; the worse window wins', () => {
  expect(pace(null, null).level).toBe('normal')
  expect(pace({ pct: 50, resetsAt: null }, { pct: 50, resetsAt: null }).level).toBe('normal')
  expect(pace({ pct: 86, resetsAt: 1 }, null)).toEqual({ level: 'light', window: 'five_hour', pct: 86, resetsAt: 1 })
  expect(pace({ pct: 96, resetsAt: 1 }, { pct: 91, resetsAt: 2 }).level).toBe('hold')
  expect(pace({ pct: 96, resetsAt: 1 }, { pct: 91, resetsAt: 2 }).window).toBe('five_hour')
  expect(pace({ pct: 10, resetsAt: 1 }, { pct: 98, resetsAt: 2 }).window).toBe('seven_day')
})

test('pace: a person is never a target', () => {
  expect(isPerson('composer')).toBe(true)
  expect(isPerson('bridge')).toBe(true)
  expect(isPerson('peer')).toBe(false)
  expect(isPerson('scheduled-trigger')).toBe(false)
})

test('ledger: a compaction costs once and saves on every later request, more on a cold one', () => {
  let l = ledgerOnCompaction(EMPTY_LEDGER, 500_000, 110_000, 'claude-opus-5-5')
  expect(l.compactions).toBe(1)
  expect(l.spent > 0.5 && l.spent < 2).toBe(true)
  const warm = ledgerOnRequest(l, 'claude-opus-5-5', false).saved
  const cold = ledgerOnRequest(l, 'claude-opus-5-5', true).saved
  expect(Math.abs(warm - 390_000 * 0.2e-6) < 1e-9).toBe(true)
  expect(cold > 30 * warm).toBe(true)
  for (let i = 0; i < 20; i++) l = ledgerOnRequest(l, 'claude-opus-5-5', false)
  expect(l.saved > 1.5).toBe(true)
  expect(ledgerOnRequest(EMPTY_LEDGER, undefined, true).saved).toBe(0)
})

test('policy: the hard cap does not loop when a compaction leaves the context near the cap', () => {
  // the last compaction only got down to 860k: at 870k it must not compact again
  expect(decide(base({ taskClosed: false, contextTokens: 870_000, lastCompactAfter: 860_000 })).action).toBe('none')
  // 50k more and it may
  expect(decide(base({ taskClosed: false, contextTokens: 915_000, lastCompactAfter: 860_000 })).action).toBe('compact')
})

test('policy: a measured after-compaction context replaces the default in the sums', () => {
  const plain = decide(base({ contextTokens: 300_000 }))
  const heavy = decide(base({ contextTokens: 300_000, lastCompactAfter: 260_000 }))
  expect(plain.action).toBe('compact')
  expect(heavy.action).toBe('none')
})

test('policy: a turn-end re-check with a cold cache does nothing', () => {
  expect(decide(base({ lastCallAt: NOW - 70 * 60_000 })).action).toBe('none')
})

test('policy: idle with background work and a cold cache stops instead of waiting forever', () => {
  expect(decide(base({ trigger: 'idle', workRunning: true, lastCallAt: NOW - 90 * 60_000 })).action).toBe('none')
})

test('pacing targets are an allow-list; a Slack ping from the owner is a person', () => {
  expect(isPaceTarget('peer')).toBe(true)
  expect(isPaceTarget('scheduled-trigger')).toBe(true)
  expect(isPaceTarget('slack-ping')).toBe(false)
  expect(isPaceTarget('some-new-origin')).toBe(false)
  expect(isPerson('slack-ping')).toBe(true)
})

test('prices: provider-prefixed model ids are recognised', () => {
  expect(economics(400_000, 'us.anthropic.claude-sonnet-5-5', POLICY_DEFAULTS).cost).toBeLessThan(economics(400_000, 'claude-opus-5-5', POLICY_DEFAULTS).cost)
})
