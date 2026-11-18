import clsx from 'clsx'
import { Pause, Play } from 'lucide-react'
import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api, ApiError } from '../api'
import { ActivityFeed } from '../components/Activity'
import AgentChat from '../components/AgentChat'
import { agentTone } from '../components/Layout'
import { Button, Card, Tabs } from '../components/ui'
import { useStore } from '../store'
import LearningTab from './brain/LearningTab'
import MemoryTab from './brain/MemoryTab'
import Rules from './brain/Playbook'

type Tab = 'activity' | 'rules' | 'memory' | 'learning'
const TABS: Tab[] = ['activity', 'rules', 'memory', 'learning']

/** `?tab=` value → tab, accepting the names the old Brain page used. */
function readTab(raw: string | null): Tab {
  if (raw === 'playbook') return 'rules'
  return TABS.includes(raw as Tab) ? (raw as Tab) : 'activity'
}

function Status() {
  const app = useStore((s) => s.app)
  const setApp = useStore((s) => s.setApp)
  const toast = useStore((s) => s.toast)
  const liveGames = useStore((s) => s.games.filter((g) => g.state === 'live').length)
  const [busy, setBusy] = useState(false)

  const agent = app?.agent
  const enabled = app?.settings.agent_enabled ?? false
  const tone = agent ? agentTone[agent.state] : agentTone.paused

  let sentence = 'Connecting…'
  if (agent) {
    if (agent.state === 'paused') sentence = 'Paused'
    else if (agent.state === 'acting') sentence = 'Placing an order'
    else if (agent.state === 'watching')
      sentence = liveGames > 0 ? `Watching ${liveGames} ${liveGames === 1 ? 'game' : 'games'}` : 'Watching'
    else sentence = 'Waiting for the next game'
  }

  const toggle = async () => {
    setBusy(true)
    try {
      setApp(enabled ? await api.pauseAgent() : await api.startAgent())
    } catch (e) {
      toast({ level: 'error', title: 'Could not reach the agent', body: e instanceof ApiError ? e.message : '' })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex flex-wrap items-center justify-between gap-4">
      <div className="min-w-0">
        <div className="flex items-center gap-2.5">
          <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: tone.color }} />
          <span className="text-xl font-semibold text-white">{sentence}</span>
        </div>
        <p className="hint mt-1">
          {agent?.focus ||
            (enabled
              ? 'Looking for a game that fits your rules.'
              : 'Press Start and it will watch live games and trade by your rules.')}
        </p>
      </div>
      <Button variant={enabled ? 'outline' : 'primary'} size="md" onClick={toggle} loading={busy} disabled={!app}>
        {!busy && (enabled ? <Pause size={15} /> : <Play size={15} />)}
        {enabled ? 'Pause' : 'Start'}
      </Button>
    </div>
  )
}

export default function Agent() {
  const [params, setParams] = useSearchParams()
  const tab = readTab(params.get('tab'))

  return (
    <div className="page">
      <h1 className="h-page">Agent</h1>
      <p className="hint mt-1">What it is doing, the rules it follows, what it remembers and what it has learned.</p>

      <Card className="mt-5 px-5 py-4">
        <Status />
      </Card>

      <Tabs<Tab>
        id="agent-page"
        value={tab}
        onChange={(t) => setParams(t === 'activity' ? {} : { tab: t }, { replace: true })}
        className="mb-5 mt-5"
        tabs={[
          { value: 'activity', label: 'Activity' },
          { value: 'rules', label: 'Rules' },
          { value: 'memory', label: 'Memory' },
          { value: 'learning', label: 'Learning' },
        ]}
      />

      {/* Activity stays mounted so a chat answer in flight survives a look at another tab. */}
      <div className={clsx('grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_400px]', tab !== 'activity' && 'hidden')}>
        <ActivityFeed />
        <Card className="h-[560px] overflow-hidden lg:sticky lg:top-4 lg:h-[min(640px,calc(100vh-140px))]">
          <AgentChat />
        </Card>
      </div>
      {tab === 'rules' && <Rules />}
      {tab === 'memory' && <MemoryTab />}
      {tab === 'learning' && <LearningTab />}
    </div>
  )
}
