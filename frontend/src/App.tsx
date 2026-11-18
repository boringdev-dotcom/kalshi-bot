import { MotionConfig } from 'framer-motion'
import { Navigate, Route, Routes } from 'react-router-dom'
import Layout from './components/Layout'
import Brain from './pages/Brain'
import Desk from './pages/Desk'
import Portfolio from './pages/Portfolio'
import Settings from './pages/Settings'

export default function App() {
  return (
    <MotionConfig reducedMotion="user">
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Desk />} />
          <Route path="portfolio" element={<Portfolio />} />
          <Route path="brain" element={<Brain />} />
          <Route path="settings" element={<Settings />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </MotionConfig>
  )
}
