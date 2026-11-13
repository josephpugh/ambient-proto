// Session state and how each A2A event changes it.
//
// feed: chronological items the branch user reads (snippet heard, activity per turn, review, submitted, error)
// flows: the live record per flow, rendered under "Working in the background"

let seq = 0
const nid = () => `i${++seq}`
export const now = () => new Date()

export const initialState = () => ({
  contextId: null,
  taskId: null,
  busy: false,
  turn: 0,
  feed: [],
  flows: {},
  flowOrder: [],
})

function pushActivity(state, line) {
  const feed = state.feed.slice()
  const last = feed[feed.length - 1]
  if (last && last.type === 'activity' && last.turn === state.turn) {
    feed[feed.length - 1] = { ...last, lines: [...last.lines, { id: nid(), ...line }] }
  } else {
    feed.push({ type: 'activity', id: nid(), turn: state.turn, at: now(), lines: [{ id: nid(), ...line }] })
  }
  return { ...state, feed }
}

function alreadyShown(state, line) {
  // The backend suppresses repeat rejections; this is the belt to its braces.
  const last = state.feed[state.feed.length - 1]
  return !!(last && last.type === 'activity' && last.turn === state.turn &&
    last.lines.some((l) => l.icon === line.icon && l.text === line.text && l.sub === line.sub))
}

function sameResolved(prev, next) {
  // True when the previous record was also ready and resolved to the same values.
  if (!prev || prev.status !== 'ready') return false
  const key = (r) => JSON.stringify(r.resolved.map((x) => [x.field, x.value]))
  return key(prev) === key(next)
}

function listLabels(items) {
  return items.map((x) => x.label.toLowerCase()).join(', ')
}

export function reducer(state, action) {
  switch (action.type) {
    case 'reset':
      return initialState()

    case 'send': {
      const turn = state.turn + 1
      const item = action.kind === 'detail'
        ? { type: 'detail', id: nid(), at: now(), turn, text: action.text, label: action.label }
        : action.kind === 'confirm'
          ? { type: 'confirming', id: nid(), at: now(), turn, flow: action.flow }
          : { type: 'snippet', id: nid(), at: now(), turn, text: action.text, summary: null }
      return { ...state, busy: true, turn, feed: [...state.feed, item] }
    }

    case 'ids':
      return { ...state, contextId: action.contextId || state.contextId, taskId: action.taskId || state.taskId }

    case 'done':
      return { ...state, busy: false, feed: state.feed.map((f) => (f.type === 'snippet' && f.summary === null ? { ...f, summary: '' } : f)) }

    case 'event':
      return applyEvent(state, action.event)

    default:
      return state
  }
}

function applyEvent(state, ev) {
  switch (ev.kind) {
    case 'summary': {
      // Attach to the most recent snippet still waiting for its summary.
      const feed = state.feed.slice()
      for (let i = feed.length - 1; i >= 0; i--) {
        if (feed[i].type === 'snippet' && feed[i].summary === null) {
          feed[i] = { ...feed[i], summary: ev.text }
          break
        }
      }
      return { ...state, feed }
    }

    case 'flow_activated': {
      const flows = {
        ...state.flows,
        [ev.flow]: { name: ev.flow, title: ev.title, rationale: ev.rationale, record: null, supporting: null, fields: null, activatedAt: now() },
      }
      const flowOrder = state.flowOrder.includes(ev.flow) ? state.flowOrder : [...state.flowOrder, ev.flow]
      return pushActivity({ ...state, flows, flowOrder }, { icon: 'spark', text: `Identified ${ev.title.toLowerCase()}`, sub: ev.rationale })
    }

    case 'fields': {
      const flow = state.flows[ev.flow] || { name: ev.flow, title: ev.title, record: null, supporting: null, activatedAt: now() }
      let s = { ...state, flows: { ...state.flows, [ev.flow]: { ...flow, fields: ev } } }
      if (!s.flowOrder.includes(ev.flow)) s.flowOrder = [...s.flowOrder, ev.flow]
      const matched = ev.accepted.filter((a) => a.new)
      const updated = ev.accepted.filter((a) => a.changed)
      if (matched.length) s = pushActivity(s, { icon: 'check', text: `Matched ${listLabels(matched)}`, sub: matched.map((m) => `${m.label}: ${m.display}`).join(', ') })
      if (updated.length) s = pushActivity(s, { icon: 'check', text: `Updated ${listLabels(updated)}`, sub: updated.map((m) => `${m.label}: ${m.display}`).join(', ') })
      for (const r of ev.rejected) {
        const line = { icon: 'alert', text: `Rejected ${r.label.toLowerCase()} "${r.value}"`, sub: r.reason }
        if (!alreadyShown(s, line)) s = pushActivity(s, line)
      }
      const prevRequired = new Set((flow.fields?.required || []).map((r) => r.field))
      const newlyRequired = ev.required.filter((r) => !prevRequired.has(r.field))
      if (newlyRequired.length && (matched.length || updated.length || ev.rejected.length || !flow.fields)) {
        s = pushActivity(s, { icon: 'clock', text: `Still needed: ${listLabels(ev.required)}` })
      }
      return s
    }

    case 'supporting': {
      const flow = state.flows[ev.flow]
      if (!flow) return state
      return { ...state, flows: { ...state.flows, [ev.flow]: { ...flow, supporting: { choices: ev.choices || {}, notes: ev.notes || [] } } } }
    }

    case 'artifact': {
      const flow = state.flows[ev.flow] || { name: ev.flow, title: ev.record.title, activatedAt: now() }
      let s = { ...state, flows: { ...state.flows, [ev.flow]: { ...flow, title: ev.record.title, record: ev.record } } }
      if (!s.flowOrder.includes(ev.flow)) s.flowOrder = [...s.flowOrder, ev.flow]
      if (ev.record.status === 'ready' && !sameResolved(flow.record, ev.record)) {
        // The record is complete, or complete again with different values. Only the most recent review card
        // for a flow is shown, so any earlier one is dropped and a fresh one goes at the end of the feed.
        s = { ...s, feed: s.feed.filter((f) => !(f.type === 'review' && f.flow === ev.flow)) }
        s = pushActivity(s, { icon: 'flag', text: `${ev.record.title} is ready for review` })
        s = { ...s, feed: [...s.feed, { type: 'review', id: nid(), at: now(), flow: ev.flow }] }
      }
      return s
    }

    case 'submitted': {
      const feed = state.feed.filter((f) => f.type !== 'confirming')
      const s = { ...state, feed }
      // The review card for this flow turns into the receipt; if there is none (edge case), add one.
      if (feed.some((f) => f.type === 'review' && f.flow === ev.flow)) {
        return pushActivity(s, { icon: 'checks', text: `${ev.title} submitted as ${ev.reference}`, sub: ev.summary })
      }
      return { ...s, feed: [...feed, { type: 'submitted', id: nid(), at: now(), flow: ev.flow, title: ev.title, reference: ev.reference, summary: ev.summary }] }
    }

    case 'error': {
      const feed = state.feed.filter((f) => f.type !== 'confirming')
      return { ...state, feed: [...feed, { type: 'error', id: nid(), at: now(), text: ev.text }] }
    }

    case 'turn_done':
      return state

    default:
      return state
  }
}

export function fmtTime(d) {
  return d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }).toLowerCase()
}
