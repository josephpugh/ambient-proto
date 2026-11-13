import { useState } from 'react'
import { fmtTime } from '../state.js'
import Icon from './Icons.jsx'
import FlowCard from './FlowCard.jsx'

export default function Feed({ state, onPick, onConfirm }) {
  // A flow stays in the background list only while it is still gathering inputs. Once its record is
  // complete it is represented by its review card in the feed instead.
  const inProgress = state.flowOrder.filter((name) => (state.flows[name]?.record?.status || 'in_progress') === 'in_progress')
  return (
    <>
      {state.feed.map((item, i) => (
        <FeedItem key={item.id} item={item} prev={state.feed[i - 1]} state={state} onConfirm={onConfirm} />
      ))}
      {inProgress.length > 0 && (
        <>
          <div className="section-head">
            <span>Working in the background</span>
            <span className="section-count">
              {inProgress.length} {inProgress.length === 1 ? 'flow' : 'flows'}
            </span>
          </div>
          <div className="flow-list">
            {inProgress.map((name) => (
              <FlowCard key={name} flow={state.flows[name]} busy={state.busy} onPick={onPick} />
            ))}
          </div>
        </>
      )}
      {state.busy && <WorkingLine />}
    </>
  )
}

function Stamp({ item, prev }) {
  // Show a timestamp when the minute changes or the previous item was not in this turn.
  if (prev && prev.turn === item.turn && fmtTime(prev.at) === fmtTime(item.at)) return null
  return <div className="stamp">{fmtTime(item.at)}</div>
}

function FeedItem({ item, prev, state, onConfirm }) {
  switch (item.type) {
    case 'snippet':
      return (
        <>
          <Stamp item={item} prev={prev} />
          <HeardCard item={item} />
        </>
      )
    case 'detail':
      return (
        <>
          <Stamp item={item} prev={prev} />
          <div className="detail-line">
            <Icon name="user" size={13} />
            <span>You added</span>
            <b>{item.label}</b>
          </div>
        </>
      )
    case 'confirming':
      return (
        <div className="detail-line">
          <span className="spinner dark" />
          <span>Submitting {state.flows[item.flow]?.title?.toLowerCase() || item.flow}…</span>
        </div>
      )
    case 'activity':
      return <ActivityCard item={item} />
    case 'review':
      return <ReviewCard flow={state.flows[item.flow]} busy={state.busy} onConfirm={onConfirm} />
    case 'submitted':
      return (
        <div className="card submitted">
          <div className="card-head">
            <Icon name="checks" size={15} color="#3B6D11" />
            <span className="card-label">Submitted</span>
            <span className="ref">{item.reference}</span>
          </div>
          <div className="card-body">{item.summary}</div>
        </div>
      )
    case 'error':
      return (
        <div className="card error">
          <div className="card-head">
            <Icon name="alert" size={15} color="#A32D2D" />
            <span className="card-label">Something went wrong</span>
          </div>
          <div className="card-body">{item.text}</div>
        </div>
      )
    default:
      return null
  }
}

function HeardCard({ item }) {
  const [open, setOpen] = useState(false)
  const pending = item.summary === null
  return (
    <div className="card heard">
      <div className="card-head">
        <Icon name="ear" size={15} color="#5F5E5A" />
        <span className="card-label">{pending ? 'Processing' : 'Heard'}</span>
        <button className="link" onClick={() => setOpen((o) => !o)}>
          {open ? 'Hide transcript' : 'Transcript'}
        </button>
      </div>
      {pending ? (
        <div className="bars" aria-label="Summarising">
          {[6, 12, 18, 9, 14, 5, 16, 8, 11].map((h, i) => (
            <span key={i} style={{ height: h, animationDelay: `${i * 0.08}s` }} />
          ))}
        </div>
      ) : (
        <div className="serif summary">{item.summary || 'No summary was returned for this snippet.'}</div>
      )}
      {open && <pre className="transcript">{item.text}</pre>}
    </div>
  )
}

const activityColor = { spark: '#185FA5', check: '#3B6D11', checks: '#3B6D11', alert: '#A32D2D', clock: '#888780', flag: '#BA7517' }

function ActivityCard({ item }) {
  return (
    <div className="activity">
      {item.lines.map((l) => (
        <div className="activity-line" key={l.id}>
          <Icon name={l.icon} size={14} color={activityColor[l.icon] || '#5F5E5A'} />
          <div>
            <div className="activity-text">{l.text}</div>
            {l.sub && <div className="activity-sub">{l.sub}</div>}
          </div>
        </div>
      ))}
    </div>
  )
}

function ReviewCard({ flow, busy, onConfirm }) {
  const record = flow?.record
  if (!record) return null
  const submitted = record.status === 'submitted'
  const ready = record.status === 'ready'
  return (
    <div className={`card review ${submitted ? 'is-submitted' : ''}`}>
      <div className="card-head">
        <Icon name={submitted ? 'checks' : 'flag'} size={15} color={submitted ? '#3B6D11' : '#BA7517'} />
        <span className="card-label">{submitted ? 'Submitted' : 'Ready for review'}</span>
        <span className="review-title">{record.title}</span>
      </div>
      <dl className="review-grid">
        {record.resolved.map((r) => (
          <div className="review-row" key={r.field}>
            <dt>{r.label}</dt>
            <dd>
              <div className="review-value">{r.display}</div>
              {r.evidence && (
                <div className="review-evidence">
                  <Icon name="quote" size={11} />
                  {r.evidence}
                </div>
              )}
            </dd>
          </div>
        ))}
      </dl>
      {submitted ? (
        <div className="review-foot done">
          <Icon name="check" size={14} color="#3B6D11" />
          Submitted as <b>{record.submitted?.reference}</b>
        </div>
      ) : ready ? (
        <div className="review-foot">
          <span className="review-note">Confirm with the client, then submit as yourself.</span>
          <button className="btn-primary" disabled={busy} onClick={() => onConfirm(record.flow)}>
            Confirm
          </button>
        </div>
      ) : (
        <div className="review-foot">
          <span className="review-note">A later snippet changed this record. It is back in progress.</span>
        </div>
      )}
    </div>
  )
}

function WorkingLine() {
  return (
    <div className="working-line">
      <span className="spinner dark" />
      Working through what was said
    </div>
  )
}
