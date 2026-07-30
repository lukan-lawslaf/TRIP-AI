import { useEffect, useRef, useState } from 'react'
import { createSession, sendMessage } from '@/api/client'
import type { AgentResponse } from '@/api/client'

const STEPS = [
  '01 / Reading your travel style',
  '02 / Scanning flights & routes',
  '03 / Matching stays & hidden gems',
  '04 / Drafting your itinerary',
]

const STEP_MS = 1400

export default function PlanningLoader({
  prompt,
  onDone,
}: {
  prompt: string
  onDone: (result: AgentResponse | null) => void
}) {
  const [step, setStep] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const apiDone = useRef(false)
  const apiResult = useRef<AgentResponse | null>(null)

  // Kick off the real API call immediately
  useEffect(() => {
    let cancelled = false
    async function run() {
      try {
        const sessionId = await createSession()
        const result = await sendMessage(sessionId, prompt)
        if (!cancelled) {
          apiResult.current = result
          apiDone.current = true
        }
      } catch {
        if (!cancelled) setError('backend offline')
        if (!cancelled) {
          apiDone.current = true // still advance to dashboard with null
        }
      }
    }
    run()
    return () => { cancelled = true }
  }, [prompt])

  // Advance steps on a timer; after all steps wait for API then call onDone
  useEffect(() => {
    if (step < STEPS.length) {
      const t = setTimeout(() => setStep((s) => s + 1), STEP_MS)
      return () => clearTimeout(t)
    }
    // All steps done — poll until API resolves (max ~10 s extra)
    if (apiDone.current) {
      const t = setTimeout(() => onDone(apiResult.current), 400)
      return () => clearTimeout(t)
    }
    const t = setInterval(() => {
      if (apiDone.current) {
        clearInterval(t)
        onDone(apiResult.current)
      }
    }, 300)
    return () => clearInterval(t)
  }, [step, onDone])

  const progress = Math.min((step / STEPS.length) * 100, 100)

  return (
    <section className="relative w-full min-h-svh overflow-hidden bg-black font-figtree text-white">
      <div className="max-w-[1340px] mx-auto min-h-svh flex flex-col justify-end px-[15px] max-md:px-[18px] pb-[60px] pt-[190px] max-md:pt-[140px]">
        <div className="flex items-center gap-3 mb-10 anim-fade-in-up">
          <span
            className="w-[7px] h-[7px] rounded-full bg-[#F598F2] anim-dot-pulse"
            style={{ boxShadow: '0 0 12px 2px rgba(245,152,242,0.6)' }}
            aria-hidden="true"
          />
          <span className="text-xs font-medium uppercase tracking-[-0.12px] text-white/80">
            {error ? 'Using demo data — backend offline' : 'TripAI is working on your plan'}
          </span>
        </div>

        <h1 className="text-[clamp(68px,14vw,200px)] leading-[0.81] tracking-[-6px] max-md:tracking-[-3px] font-medium uppercase anim-reveal-up">
          Planning<span className="text-[#F598F2]">.</span>
        </h1>

        <p
          className="mt-10 max-w-[560px] text-base leading-6 tracking-[-0.16px] font-medium text-white/70 anim-reveal-right"
          style={{ animationDelay: '0.08s' }}
        >
          "{prompt}"
        </p>

        <ul className="mt-12 flex flex-col gap-3" aria-live="polite">
          {STEPS.map((label, i) => {
            const done = i < step
            const active = i === step
            return (
              <li
                key={label}
                className={`text-xs uppercase tracking-[-0.12px] font-medium transition-opacity duration-500 ${
                  done ? 'opacity-40 line-through' : active ? 'opacity-100' : 'opacity-25'
                }`}
              >
                {label}
                {active && <span className="ml-2 text-[#F598F2]">…</span>}
              </li>
            )
          })}
        </ul>

        <div className="mt-10 h-px w-full bg-white/15" role="progressbar" aria-valuenow={Math.round(progress)} aria-valuemin={0} aria-valuemax={100}>
          <div
            className="h-px bg-[#F598F2] transition-all duration-700"
            style={{ width: `${progress}%`, transitionTimingFunction: 'var(--ease-spring)' }}
          />
        </div>
      </div>
    </section>
  )
}
