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
  const res = await fetch(`${BASE}/session/${sessionId}/message/start`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text }),
  })
  if (!res.ok) throw new Error(`sendMessage ${res.status}`)
  const { job_id } = await res.json() as { job_id: string }
  const deadline = Date.now() + 10 * 60_000
  while (Date.now() < deadline) {
    await new Promise((resolve) => setTimeout(resolve, 2000))
    let status: Response
    try {
      status = await fetch(`${BASE}/session/${sessionId}/message/status/${job_id}`, {
        signal: AbortSignal.timeout(90_000),
      })
    } catch {
      continue
    }
    if (status.status >= 500 || status.status === 429) continue
    if (!status.ok) throw new Error(`Planning request ${status.status}`)
    const job = await status.json() as { status: string; result?: AgentResponse; message?: string }
    if (job.status === 'failed') throw new Error(job.message ?? 'The travel assistant is temporarily unavailable.')
    if (job.status === 'complete' && job.result) return job.result
  }
  throw new Error('Planning is taking longer than expected. Please try again later.')
}

export async function getSessionState(sessionId: string): Promise<SessionStateResponse> {
  const res = await fetch(`${BASE}/session/${sessionId}/state`)
  if (!res.ok) throw new Error(`getSessionState ${res.status}`)
  return res.json() as Promise<SessionStateResponse>
}
