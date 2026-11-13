import { useEffect, useState } from 'react'
import { SAMPLES, transcriptText } from '../samples.js'
import Icon from './Icons.jsx'

// Sample transcripts on the desk, one panel each, with a button that copies the transcript for pasting
// into the sidebar's composer.
export default function Samples() {
  return (
    <section className="samples" aria-label="Sample transcripts">
      <div className="samples-head">
        <div className="samples-title">Sample transcripts</div>
        <div className="samples-sub">Copy one and paste it into the assistant to see the flow resolve.</div>
      </div>
      <div className="samples-grid">
        {SAMPLES.map((s) => (
          <SamplePanel key={s.id} sample={s} />
        ))}
      </div>
    </section>
  )
}

function SamplePanel({ sample }) {
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    if (!copied) return
    const t = setTimeout(() => setCopied(false), 1600)
    return () => clearTimeout(t)
  }, [copied])

  const copy = async () => {
    const text = transcriptText(sample)
    try {
      await navigator.clipboard.writeText(text)
    } catch {
      // Clipboard API unavailable (insecure origin or permission denied): fall back to a selection copy.
      const ta = document.createElement('textarea')
      ta.value = text
      ta.setAttribute('readonly', '')
      ta.style.position = 'fixed'
      ta.style.opacity = '0'
      document.body.appendChild(ta)
      ta.select()
      document.execCommand('copy')
      document.body.removeChild(ta)
    }
    setCopied(true)
  }

  return (
    <article className="sample">
      <header className="sample-head">
        <div className="sample-title-wrap">
          <h2 className="sample-title">{sample.title}</h2>
          <p className="sample-summary">{sample.summary}</p>
        </div>
        <button className={`btn-icon copy ${copied ? 'is-copied' : ''}`} onClick={copy} title="Copy transcript to clipboard">
          <Icon name={copied ? 'check' : 'copy'} size={14} />
          {copied ? 'Copied' : 'Copy'}
        </button>
      </header>
      <ol className="sample-lines">
        {sample.lines.map(([speaker, text], i) => (
          <li key={i} className={`sample-line ${speaker}`}>
            <span className="speaker">{speaker}</span>
            <span className="said">{text}</span>
          </li>
        ))}
      </ol>
    </article>
  )
}
