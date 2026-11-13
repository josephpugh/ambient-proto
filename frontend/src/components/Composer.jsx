import { useEffect, useRef, useState } from 'react'
import Icon from './Icons.jsx'

const MAX_HEIGHT = 160

// The input box: grows with the text up to a point, then scrolls. Locked while a turn is in flight.
export default function Composer({ busy, onSend }) {
  const [text, setText] = useState('')
  const ref = useRef(null)

  useEffect(() => {
    const el = ref.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, MAX_HEIGHT) + 'px'
    el.style.overflowY = el.scrollHeight > MAX_HEIGHT ? 'auto' : 'hidden'
  }, [text])

  const canSend = !busy && text.trim().length > 0

  const submit = () => {
    if (!canSend) return
    onSend(text.trim())
    setText('')
  }

  // Enter sends. Shift+Enter inserts a newline for typing a multi-line transcript by hand.
  const onKey = (e) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
      e.preventDefault()
      submit()
    }
  }

  return (
    <div className={`composer ${busy ? 'is-busy' : ''}`}>
      <textarea
        ref={ref}
        rows={1}
        value={text}
        disabled={busy}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={onKey}
        placeholder={busy ? 'Working through what was said…' : 'Paste what was said, or add a detail'}
        aria-label="Transcript input"
      />
      <button className="send" onClick={submit} disabled={!canSend} aria-label="Send" title="Send (Enter)">
        {busy ? <span className="spinner" /> : <Icon name="arrowUp" size={16} color="#fff" />}
      </button>
    </div>
  )
}
