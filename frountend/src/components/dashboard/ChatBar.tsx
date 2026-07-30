import { useState } from 'react'
import { Send } from 'lucide-react'

export default function ChatBar({
  onSend,
  loading,
}: {
  onSend: (text: string) => void
  loading: boolean
}) {
  const [text, setText] = useState('')

  function submit() {
    const t = text.trim()
    if (!t || loading) return
    setText('')
    onSend(t)
  }

  return (
    <div className="fixed bottom-0 left-0 right-0 z-40 lg:left-[258px]">
      <div className="mx-auto max-w-3xl px-4 pb-5">
        <div className="flex items-center gap-3 rounded-[28px] bg-white px-5 py-3 shadow-[0_8px_30px_rgba(32,42,54,0.12)] border border-[#dce4e7]">
          <input
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && submit()}
            placeholder="Ask TripAI to refine your plan…"
            className="flex-1 bg-transparent text-sm text-[#202a36] outline-none placeholder:text-[#98a3aa]"
            disabled={loading}
          />
          <button
            onClick={submit}
            disabled={loading || !text.trim()}
            className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-[#2a6074] text-white transition hover:bg-[#173c4d] disabled:opacity-40"
            aria-label="Send"
          >
            {loading ? (
              <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-white border-t-transparent" />
            ) : (
              <Send size={15} />
            )}
          </button>
        </div>
      </div>
    </div>
  )
}
