// The pinned client bar: who the client is and what the assistant is doing right now.
export default function ClientBar({ busy }) {
  const status = busy ? 'working' : 'ready'
  const label = { working: 'Working', ready: 'Ready' }[status]

  return (
    <div className="client-bar">
      <div className="avatar">MH</div>
      <div className="client-meta">
        <div className="client-name">Margaret Hartley</div>
      </div>
      <div className={`pill pill-${status}`}>
        <span className="pill-dot" />
        {label}
      </div>
    </div>
  )
}
