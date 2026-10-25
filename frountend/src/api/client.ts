const BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? (import.meta.env.DEV ? 'http://localhost:8000' : '/api')

export interface AgentResponse {
  session_id: string
  message: string
  trip_state: Record<string, unknown>
  served_by: string | null
  tools_used: string[]
  rounds: number
}

export interface SessionStateResponse {
  session_id: string
  trip_state: Record<string, unknown>
}

export async function createSession(): Promise<string> {
  // Wake the free backend before submitting a mutation. Only the GET is retried.
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      const health = await fetch(`${BASE}/health`, { signal: AbortSignal.timeout(90_000) })
      if (health.ok) break
      if (health.status < 500 && health.status !== 429) throw new Error(`health ${health.status}`)
      if (attempt === 2) throw new Error('Travel assistant is waking up. Please try again.')
    } catch (error) {
      if (attempt === 2) throw error
    }
    await new Promise((resolve) => setTimeout(resolve, 1500 * (attempt + 1)))
  }
  const res = await fetch(`${BASE}/session`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: '{}',
  })
  if (!res.ok) throw new Error(`createSession ${res.status}`)
  const data = (await res.json()) as { session_id: string }
  return data.session_id
}

export async function sendMessage(sessionId: string, text: string): Promise<AgentResponse> {
  const res = await fetch(`${BASE}/session/${sessionId}/message`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text }),
  })
  if (!res.ok) throw new Error(`sendMessage ${res.status}`)
  return res.json() as Promise<AgentResponse>
}

export async function getSessionState(sessionId: string): Promise<SessionStateResponse> {
  const res = await fetch(`${BASE}/session/${sessionId}/state`)
  if (!res.ok) throw new Error(`getSessionState ${res.status}`)
  return res.json() as Promise<SessionStateResponse>
}
