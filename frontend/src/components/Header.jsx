import Icon from './Icons.jsx'

export default function Header({ onNewSession, busy }) {
  return (
    <div className="header">
      <div className="header-left">
        <span className="brand-dot" />
        <span className="brand">Assistant</span>
      </div>
      <button className="btn-icon" onClick={onNewSession} title="Start a new interaction session" aria-label="New session">
        <Icon name="plus" size={16} />
        <span>New session</span>
      </button>
    </div>
  )
}
