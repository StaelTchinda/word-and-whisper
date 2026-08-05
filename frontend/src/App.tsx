import { Link, Route, Routes } from 'react-router'
import HomePage from './pages/HomePage'
import SourceTocPage from './pages/SourceTocPage'
import ReaderPage from './pages/ReaderPage'

export default function App() {
  return (
    <div className="app-shell">
      <header className="topbar">
        <Link className="brand" to="/">
          Word &amp; Whisper
        </Link>
      </header>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/sources/:sourceId" element={<SourceTocPage />} />
        <Route path="/sources/:sourceId/:itemId" element={<ReaderPage />} />
      </Routes>
    </div>
  )
}
