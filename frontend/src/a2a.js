// Minimal A2A JSON-RPC client for the browser: SendStreamingMessage over Server-Sent Events.
// The backend's agent card is at /.well-known/agent-card.json and its RPC endpoint at /a2a.

const RPC_URL = import.meta.env.VITE_A2A_URL || '/a2a'

function uuid() {
  return crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(16).slice(2)}`
}

export async function fetchAgentCard() {
  const r = await fetch('/.well-known/agent-card.json')
  if (!r.ok) throw new Error(`agent card: HTTP ${r.status}`)
  return r.json()
}

/**
 * Send one message and yield each streamed result object ({task} | {statusUpdate} | {artifactUpdate}).
 * parts: array of A2A parts, e.g. [{text: "..."}] or [{data: {action: "confirm", flow: "order_check"}}]
 */
export async function* sendStreaming({ parts, contextId, taskId, signal }) {
  const message = { messageId: uuid(), role: 'ROLE_USER', parts }
  if (contextId) message.contextId = contextId
  if (taskId) message.taskId = taskId
  const body = { jsonrpc: '2.0', id: uuid(), method: 'SendStreamingMessage', params: { message } }

  const res = await fetch(RPC_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream', 'A2A-Version': '1.0' },
    body: JSON.stringify(body),
    signal,
  })
  if (!res.ok) throw new Error(`A2A: HTTP ${res.status}`)
  if (!res.headers.get('content-type')?.includes('text/event-stream')) {
    const j = await res.json()
    if (j.error) throw new Error(j.error.message || 'A2A error')
    if (j.result) yield j.result
    return
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n')
    let idx
    while ((idx = buffer.indexOf('\n\n')) >= 0) {
      const chunk = buffer.slice(0, idx)
      buffer = buffer.slice(idx + 2)
      const data = chunk
        .split('\n')
        .filter((l) => l.startsWith('data:'))
        .map((l) => l.slice(5).trim())
        .join('\n')
      if (!data) continue
      let msg
      try {
        msg = JSON.parse(data)
      } catch {
        continue
      }
      if (msg.error) throw new Error(msg.error.message || 'A2A error')
      if (msg.result) yield msg.result
    }
  }
}

/** Pull the UI-facing events out of one streamed result: [{kind, ...}] plus task ids. */
export function interpret(result) {
  const out = { events: [], contextId: null, taskId: null, state: null, final: false }
  if (result.task) {
    out.contextId = result.task.contextId
    out.taskId = result.task.id
    out.state = result.task.status?.state
  } else if (result.statusUpdate) {
    const su = result.statusUpdate
    out.contextId = su.contextId
    out.taskId = su.taskId
    out.state = su.status?.state
    out.final = !!su.final
    for (const p of su.status?.message?.parts || []) {
      if (p.data && p.data.kind) out.events.push(p.data)
      else if (p.text && su.status?.state === 'TASK_STATE_FAILED') out.events.push({ kind: 'error', text: p.text })
    }
  } else if (result.artifactUpdate) {
    const au = result.artifactUpdate
    out.contextId = au.contextId
    out.taskId = au.taskId
    for (const p of au.artifact?.parts || []) {
      if (p.data && p.data.flow) out.events.push({ kind: 'artifact', flow: p.data.flow, record: p.data })
    }
  }
  return out
}
