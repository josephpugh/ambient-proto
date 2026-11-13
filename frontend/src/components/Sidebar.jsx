import { useCallback, useEffect, useReducer, useRef, useState } from 'react'
import { interpret, sendStreaming } from '../a2a.js'
import { initialState, reducer } from '../state.js'
import Header from './Header.jsx'
import ClientBar from './ClientBar.jsx'
import Feed from './Feed.jsx'
import Composer from './Composer.jsx'
import Icon from './Icons.jsx'

const DEFAULT_WIDTH = 420
const MIN_WIDTH = 320
const MAX_WIDTH = 640

export default function Sidebar() {
  const [state, dispatch] = useReducer(reducer, undefined, initialState)
  const [width, setWidth] = useState(() => Math.min(DEFAULT_WIDTH, window.innerWidth - 40))
  const abortRef = useRef(null)
  const feedRef = useRef(null)

  // Reactive sizing: clamp the width to the window, and let the user drag the left edge.
  useEffect(() => {
    const onResize = () => setWidth((w) => Math.max(MIN_WIDTH, Math.min(w, window.innerWidth - 40)))
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])

  const startDrag = (e) => {
    e.preventDefault()
    const startX = e.clientX
    const startW = width
    const move = (ev) => setWidth(Math.max(MIN_WIDTH, Math.min(MAX_WIDTH, window.innerWidth - 40, startW + (startX - ev.clientX))))
    const up = () => {
      window.removeEventListener('mousemove', move)
      window.removeEventListener('mouseup', up)
      document.body.style.cursor = ''
    }
    document.body.style.cursor = 'col-resize'
    window.addEventListener('mousemove', move)
    window.addEventListener('mouseup', up)
  }

  // Keep the feed scrolled to the newest item.
  useEffect(() => {
    const el = feedRef.current
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
  }, [state.feed, state.flows])

  const run = useCallback(
    async (parts, sendAction) => {
      if (state.busy) return
      dispatch({ type: 'send', ...sendAction })
      const controller = new AbortController()
      abortRef.current = controller
      try {
        for await (const result of sendStreaming({ parts, contextId: state.contextId, taskId: state.taskId, signal: controller.signal })) {
          const r = interpret(result)
          if (r.contextId || r.taskId) dispatch({ type: 'ids', contextId: r.contextId, taskId: r.taskId })
          for (const ev of r.events) dispatch({ type: 'event', event: ev })
          if (r.state === 'TASK_STATE_FAILED' || r.state === 'TASK_STATE_CANCELED') break
        }
      } catch (err) {
        if (err.name !== 'AbortError') dispatch({ type: 'event', event: { kind: 'error', text: err.message } })
      } finally {
        abortRef.current = null
        // Only once the stream has ended does the composer open again.
        dispatch({ type: 'done' })
      }
    },
    [state.busy, state.contextId, state.taskId],
  )

  const sendSnippet = (text) => run([{ text }], { kind: 'snippet', text })
  const sendDetail = (label, value) => {
    const text = `branch user: ${label} = ${value}`
    run([{ text }], { kind: 'detail', text, label: `${label}: ${value}` })
  }
  const confirm = (flow) => run([{ data: { action: 'confirm', flow } }], { kind: 'confirm', flow })

  const newSession = () => {
    abortRef.current?.abort()
    dispatch({ type: 'reset' })
  }

  const hasFlows = state.flowOrder.length > 0

  return (
    <aside className="sidebar" style={{ width }} aria-label="Ambient assistant">
      <div className="resize-handle" onMouseDown={startDrag} title="Drag to resize">
        <Icon name="grip" size={14} />
      </div>
      <Header onNewSession={newSession} busy={state.busy} />
      <ClientBar busy={state.busy} />
      <div className="feed" ref={feedRef}>
        {state.feed.length === 0 && !state.busy ? (
          <Empty />
        ) : (
          <Feed state={state} onPick={sendDetail} onConfirm={confirm} />
        )}
        {hasFlows && (
          <div className="consent">
            <Icon name="cert" size={13} />
            Client consent on file. Nothing is submitted without you.
          </div>
        )}
      </div>
      <Composer busy={state.busy} onSend={sendSnippet} />
    </aside>
  )
}

function Empty() {
  return (
    <div className="empty">
      <div className="empty-title">Waiting for transcript</div>
      <div className="empty-sub">
        Paste what was said so far, one line per speaker, as <code>advisor:</code> and <code>client:</code>. The assistant
        summarises it, spots any supported flow, and gathers the inputs. More of the conversation can be added as it goes.
      </div>
    </div>
  )
}
