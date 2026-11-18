import { AnimatePresence, motion } from 'framer-motion'
import { BookOpen, Library, LineChart } from 'lucide-react'
import { useSearchParams } from 'react-router-dom'
import { Page } from '../components/Layout'
import { Tabs } from '../components/ui'
import LearningTab from './brain/LearningTab'
import MemoryTab from './brain/MemoryTab'
import Playbook from './brain/Playbook'

type Tab = 'playbook' | 'memory' | 'learning'
const TABS: Tab[] = ['playbook', 'memory', 'learning']

export default function Brain() {
  const [params, setParams] = useSearchParams()
  const raw = params.get('tab') as Tab | null
  const tab: Tab = raw && TABS.includes(raw) ? raw : 'playbook'

  return (
    <Page title="Brain" subtitle="Your rules, what the agent remembers, and what it has learned from results.">
      <Tabs<Tab>
        id="brain"
        value={tab}
        onChange={(t) => setParams(t === 'playbook' ? {} : { tab: t }, { replace: true })}
        className="mb-5"
        tabs={[
          {
            value: 'playbook',
            label: (
              <span className="flex items-center gap-1.5">
                <BookOpen size={13} /> Playbook
              </span>
            ),
          },
          {
            value: 'memory',
            label: (
              <span className="flex items-center gap-1.5">
                <Library size={13} /> Guidance & Memory
              </span>
            ),
          },
          {
            value: 'learning',
            label: (
              <span className="flex items-center gap-1.5">
                <LineChart size={13} /> Learning
              </span>
            ),
          },
        ]}
      />
      <AnimatePresence mode="wait" initial={false}>
        <motion.div
          key={tab}
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.15 }}
        >
          {tab === 'playbook' && <Playbook />}
          {tab === 'memory' && <MemoryTab />}
          {tab === 'learning' && <LearningTab />}
        </motion.div>
      </AnimatePresence>
    </Page>
  )
}
