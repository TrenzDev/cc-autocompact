// Fixed texts the mod sends to the model. Each one is fixed text plus numbers the mod computed itself
// (a context size, a percentage, a time): nothing from the transcript, a file, a message or config.json,
// so none of them can carry an injection. They ask or inform; none of them compacts anything.

const k = (n: number) => (n >= 1_000_000 ? `${(n / 1_000_000).toFixed(1)}M` : `${Math.round(n / 1000)}k`)

// The time of day a window resets, in UTC (the mod has no locale), like "14:05 UTC"
export const hhmm = (ms: number): string => {
  const d = new Date(ms)
  const p = (x: number) => String(x).padStart(2, '0')

  return `${p(d.getUTCHours())}:${p(d.getUTCMinutes())} UTC`
}

// idle_mode 'ask': the session has been quiet for a while with a large context. One question, sent as a
// prompt from the plugin. The model decides: it wraps up and ends with the marker only if nothing is live.
export const idleQuestionText = (tokens: number, idleMin: number, markerLine: string) =>
  `[cc-autocompact] This session has been idle for ${idleMin} min with ${k(tokens)} of context, and nobody is typing. ` +
  'This is a question, not an order: can the work be picked up later from a handoff without losing anything?\n' +
  `If yes (nothing is half-done in a file, no background task or subagent still owes a result, no other session waits for a reply from you): wrap up (the wrap-up skill, unless your instructions name another), and end with ${markerLine}. ` +
  'If another session waits for your reply, send it first. Do not start new work.\n' +
  'If no, or you are not sure: answer with one short line saying why, and nothing else. Do not end with the marker.'

// Pacing near a usage limit, added as context to a message that did NOT come from a person
// (another session, a schedule, a background task). A person's message never gets it.
export const paceText = (level: 'light' | 'hold', window: 'five_hour' | 'seven_day', pct: number, resetsAt: number | null) => {
  const which = window === 'five_hour' ? '5-hour' : 'weekly'
  const when = resetsAt === null ? '' : ` It resets at ${hhmm(resetsAt)}.`
  if (level === 'light') {
    return (
      `[cc-autocompact] The ${which} usage limit is at ${Math.round(pct)}%.${when} ` +
      'This message did not come from a person. Do what it asks if it is light; if it needs heavy new work (many files, subagents, long runs), ' +
      'do the smallest useful step, write down what is left as the next step, and say it will continue after the reset. Never drop the request.'
    )
  }

  return (
    `[cc-autocompact] The ${which} usage limit is at ${Math.round(pct)}%.${when} ` +
    'This message did not come from a person. Do not start new work for it now: acknowledge it, write down what it asks as the next step (with who asked), ' +
    'and say it will be picked up after the reset. If it only needs a one-line answer, give it.'
  )
}

// After a window reset, if pacing deferred work in this session: one fixed prompt to pick it up
export const resumeText = (window: 'five_hour' | 'seven_day') =>
  `[cc-autocompact] The ${window === 'five_hour' ? '5-hour' : 'weekly'} usage limit has reset. ` +
  'If you deferred work earlier because of the limit, pick it up now from your next step. If nothing was deferred, answer "ok" and nothing else.'

// The one-line weekly summary
export const weeklyLine = (o: {
  from: string
  compactions: number
  failed: number
  savedUsd: number
  spentUsd: number
  usdPerPoint: number | null
}) => {
  const net = o.savedUsd - o.spentUsd
  const pts = o.usdPerPoint !== null && o.usdPerPoint > 0 ? ` (${(net / o.usdPerPoint).toFixed(1)} points)` : ''

  return (
    `cc-autocompact, week from ${o.from}: ${o.compactions} compactions, estimated net saving $${net.toFixed(0)}${pts} ` +
    `against the same week without them ($${o.savedUsd.toFixed(0)} saved, $${o.spentUsd.toFixed(0)} spent compacting)` +
    (o.failed > 0 ? `; ${o.failed} did not go through (see /cc-doctor)` : '') +
    '. List prices, an estimate.'
  )
}
