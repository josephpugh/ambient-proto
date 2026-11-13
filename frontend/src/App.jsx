import Samples from './components/Samples.jsx'
import Sidebar from './components/Sidebar.jsx'

// The desk to the left of the sidebar holds sample transcripts to copy into it. The sidebar is the deliverable.
export default function App() {
  return (
    <>
      <main className="desk">
        <Samples />
      </main>
      <Sidebar />
    </>
  )
}
