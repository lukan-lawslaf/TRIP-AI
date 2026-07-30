import { useState } from 'react'
import Hero from '@/components/landing/Hero'
import PlanningLoader from '@/components/loading/PlanningLoader'
import Dashboard from '@/components/dashboard/Dashboard'
import type { AgentResponse } from '@/api/client'

type Screen = 'landing' | 'planning' | 'dashboard'

const SESSION_KEY = 'tripai_session_id'

export default function App() {
  const [screen, setScreen] = useState<Screen>('landing')
  const [prompt, setPrompt] = useState('')
  const [agentResult, setAgentResult] = useState<AgentResponse | null>(null)
  const [sessionId, setSessionId] = useState<string | null>(
    () => localStorage.getItem(SESSION_KEY)
  )

  function handleDone(result: AgentResponse | null) {
    if (result) {
      setSessionId(result.session_id)
      localStorage.setItem(SESSION_KEY, result.session_id)
    }
    setAgentResult(result)
    setScreen('dashboard')
  }

  function handleLogoClick() {
    setScreen('landing')
  }

  return (
    <div>
      {screen === 'landing' && (
        <Hero
          onPlan={(p) => {
            setPrompt(p)
            setScreen('planning')
          }}
        />
      )}
      {screen === 'planning' && (
        <PlanningLoader prompt={prompt} onDone={handleDone} />
      )}
      {screen === 'dashboard' && (
        <Dashboard
          agentResult={agentResult}
          sessionId={sessionId}
          onNewResult={(r) => {
            setAgentResult(r)
            setSessionId(r.session_id)
            localStorage.setItem(SESSION_KEY, r.session_id)
          }}
          onLogoClick={handleLogoClick}
        />
      )}
    </div>
  )
}
