import { useRef, useState } from 'react'
import { Upload } from 'lucide-react'

const VIDEO_SRC = '/videos/hero.mp4'

const PLACEHOLDER =
  "I'm planning a 7-day trip to Japan in October. I love food, hidden cafes, scenic hikes, and want to avoid crowds...."

function NavButton({ label }: { label: string }) {
  return (
    <button className="bg-transparent border-none cursor-pointer font-sans text-[15px] font-medium uppercase text-wandor-text tracking-[0.04em] transition-opacity hover:opacity-55">
      {label}
    </button>
  )
}

export default function Hero({ onPlan }: { onPlan: (prompt: string) => void }) {
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [fileName, setFileName] = useState<string | null>(null)
  const [videoReady, setVideoReady] = useState(false)
  const [text, setText] = useState('')

  const effectivePrompt = text.trim() || PLACEHOLDER

  return (
    <section
      className="relative min-h-svh w-full overflow-hidden bg-[#dce7eb]"
      style={{
        background:
          'radial-gradient(circle at 72% 28%, rgba(126, 169, 181, 0.58), transparent 28%), radial-gradient(circle at 22% 72%, rgba(207, 177, 139, 0.45), transparent 30%), linear-gradient(135deg, #dfe8ea 0%, #f6f2ea 52%, #c5d9d8 100%)',
      }}
    >
      <video
        className="absolute inset-0 z-0 h-full w-full object-cover"
        src={VIDEO_SRC}
        autoPlay
        muted
        loop
        playsInline
        aria-hidden="true"
        onCanPlay={() => setVideoReady(true)}
        onError={() => setVideoReady(false)}
      />

      <div
        className="pointer-events-none absolute inset-x-0 top-0 z-[1] h-[687px]"
        style={{
          background: videoReady
            ? 'linear-gradient(180deg, rgba(255,255,255,1) 0%, rgba(255,255,255,0) 100%)'
            : 'linear-gradient(180deg, rgba(255,255,255,0.68) 0%, rgba(255,255,255,0.06) 100%)',
        }}
      />

      <div className="relative z-[2] max-w-[1360px] mx-auto">
        <nav className="flex items-center justify-between px-20 pt-6 pb-4 max-md:px-6 max-md:pt-5">
          <span className="font-display text-[40px] max-md:text-[32px] text-black leading-none select-none">
            tripai
          </span>

          <div className="absolute left-1/2 -translate-x-1/2 flex gap-8 max-md:hidden">
            <NavButton label="Discover" />
            <NavButton label="Flights" />
            <NavButton label="Hotels" />
          </div>

          <div className="flex items-center gap-8">
            <button className="max-md:hidden bg-transparent border-none cursor-pointer font-sans text-[15px] font-semibold uppercase text-[#292929] tracking-[0.04em] transition-opacity hover:opacity-55">
              Login
            </button>
            <button
              onClick={() => onPlan(effectivePrompt)}
              className="bg-wandor-dark text-[#fafafa] border-none cursor-pointer font-sans text-[15px] font-medium uppercase tracking-[0.04em] px-5 py-3.5 rounded-full transition-all hover:bg-[#333] active:scale-95"
            >
              Plan My Trip
            </button>
          </div>
        </nav>

        <div className="flex flex-col items-center px-6 pt-16 pb-24 text-center">
          <h1 className="font-sans text-[clamp(40px,6vw,68px)] font-medium text-wandor-text leading-[1.05] tracking-[-0.04em] max-w-[820px] mb-5">
            Where will you go next?
          </h1>
          <p className="font-sans text-xl font-medium text-wandor-muted leading-relaxed max-w-[500px] mb-10">
            Tell our AI where you're going and what you love. We'll create a
            personalized itinerary for you.
          </p>

          {/* Liquid glass prompt card */}
          <div className="relative w-[701px] max-md:w-[calc(100vw-48px)] min-h-[208px] bg-white/[0.06] border-[3px] border-white rounded-[44px] shadow-[0_0_4px_0_rgba(0,0,0,0.15)] overflow-hidden backdrop-blur-[20px]">
            <textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder={PLACEHOLDER}
              rows={3}
              className="absolute left-[29px] top-[28px] w-[609px] max-md:w-[calc(100%-58px)] font-sans text-xl max-md:text-[17px] font-medium text-wandor-prompt leading-relaxed text-left bg-transparent border-none outline-none resize-none placeholder:text-wandor-prompt/60"
            />

            <button
              onClick={() => onPlan(effectivePrompt)}
              className="absolute bottom-[21px] right-[21px] w-[156px] h-14 bg-black border-none rounded-[44px] shadow-[0_0_2px_0_rgba(0,0,0,0.05)] cursor-pointer flex items-center justify-center font-sans text-base font-medium text-[#fafafa] uppercase tracking-[0.02em] transition-all hover:bg-[#333] active:scale-95"
            >
              Plan My Trip
            </button>

            <input
              ref={fileInputRef}
              type="file"
              accept="image/*,video/*"
              className="hidden"
              onChange={(e) => setFileName(e.target.files?.[0]?.name ?? null)}
            />
            <button
              aria-label="Upload inspiration"
              onClick={() => fileInputRef.current?.click()}
              className="absolute left-[21px] bottom-[21px] w-11 h-11 bg-transparent border border-white/70 rounded-full cursor-pointer flex items-center justify-center backdrop-blur-[14px] transition-transform hover:scale-105 focus-visible:outline-2 focus-visible:outline-white focus-visible:outline-offset-2"
            >
              <Upload className="w-[18px] h-[18px] text-wandor-text flex-shrink-0" />
            </button>
            {fileName && (
              <span className="absolute left-[74px] bottom-[32px] text-[13px] font-sans text-wandor-text/80 truncate max-w-[240px]">
                {fileName}
              </span>
            )}
          </div>
        </div>
      </div>
    </section>
  )
}
