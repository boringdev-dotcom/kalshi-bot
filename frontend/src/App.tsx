import { MotionConfig } from 'framer-motion'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import Layout from './components/Layout'
import Agent from './pages/Agent'
import Game from './pages/Game'
import Markets from './pages/Markets'
import Portfolio from './pages/Portfolio'
import Settings from './pages/Settings'
import SoccerBoard from './pages/soccer/SoccerBoard'
import SoccerMatch from './pages/soccer/SoccerMatch'

/** Old links to /brain?tab=… land on the matching Agent tab. */
function BrainRedirect() {
  const { search } = useLocation()
  return <Navigate to={`/agent${search}`} replace />
}

export default function App() {
  return (
    <MotionConfig reducedMotion="user">
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Markets />} />
          <Route path="game/:id" element={<Game />} />
          <Route path="soccer" element={<SoccerBoard />} />
          <Route path="soccer/:id" element={<SoccerMatch />} />
          <Route path="portfolio" element={<Portfolio />} />
          <Route path="agent" element={<Agent />} />
          <Route path="brain" element={<BrainRedirect />} />
          <Route path="settings" element={<Settings />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </MotionConfig>
  )
}
