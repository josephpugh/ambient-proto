import Icon from './Icons.jsx'

// One active flow: its fields as they stand, the domain's supporting notes, and choice chips for what is outstanding.
export default function FlowCard({ flow, busy, onPick }) {
  const record = flow.record
  const status = record?.status || 'in_progress'
  const resolved = record?.resolved || []
  const outstanding = record?.outstanding || []
  const rejected = record?.rejected || []
  const choices = flow.supporting?.choices || {}
  const notes = flow.supporting?.notes || []

  const statusIcon = status === 'submitted' ? 'checks' : status === 'ready' ? 'check' : 'loader'
  const statusColor = status === 'submitted' || status === 'ready' ? '#3B6D11' : '#BA7517'
  const statusText = status === 'submitted' ? 'Submitted' : status === 'ready' ? 'Ready' : `${resolved.length} of ${resolved.length + outstanding.length}`

  return (
    <div className={`flow flow-${status}`}>
      <div className="flow-head">
        <Icon name={statusIcon} size={16} color={statusColor} className={status === 'in_progress' ? 'spin' : ''} />
        <div className="flow-title">
          <div>{flow.title}</div>
        </div>
        <span className={`pill ${status === 'submitted' ? 'pill-done' : status === 'ready' ? 'pill-ready' : 'pill-progress'}`}>{statusText}</span>
      </div>

      <div className="fields">
        {resolved.map((r) => (
          <div className="field ok" key={r.field} title={r.evidence}>
            <Icon name="check" size={13} color="#3B6D11" />
            <span className="field-label">{r.label}</span>
            <span className="field-value">{r.display}</span>
          </div>
        ))}
        {rejected.map((r) => (
          <div className="field bad" key={r.field}>
            <Icon name="alert" size={13} color="#A32D2D" />
            <span className="field-label">{r.label}</span>
            <span className="field-value">{r.reason}</span>
          </div>
        ))}
        {outstanding.map((o) => (
          <div className="field-block" key={o.field}>
            <div className="field todo">
              <Icon name="clock" size={13} color="#888780" />
              <span className="field-label">{o.label}</span>
              <span className="field-value muted">{o.last_rejection ? `"${o.last_rejection.value}" ${o.last_rejection.reason}` : o.hint || o.why}</span>
            </div>
            {choices[o.field]?.length > 0 && status !== 'submitted' && (
              <div className="chips">
                {choices[o.field].map((c) => (
                  <button key={c.value} className="chip" disabled={busy} onClick={() => onPick(o.label, c.value)} title={`Record ${o.label}: ${c.value}`}>
                    {c.label}
                  </button>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>

      {notes.length > 0 && status !== 'submitted' && (
        <div className="notes">
          {notes.map((n, i) => (
            <div className="note" key={i}>
              <Icon name="bulb" size={13} color="#BA7517" />
              <span>{n}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
