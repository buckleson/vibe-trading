import { Check, Copy } from 'lucide-react'
import { useState } from 'react'

export function CopyBlock({ text, label }: { text: string; label: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <div className="group relative">
      <pre className="overflow-x-auto whitespace-pre rounded-lg bg-muted px-3 py-2.5 pr-9 font-mono text-[11px] leading-relaxed">
        {text}
      </pre>
      <button
        type="button"
        aria-label={`Copy ${label}`}
        onClick={() => {
          navigator.clipboard?.writeText(text)
          setCopied(true)
          window.setTimeout(() => setCopied(false), 1500)
        }}
        className="absolute right-1.5 top-1.5 flex h-6 w-6 items-center justify-center rounded-md text-muted-foreground hover:bg-background hover:text-foreground"
      >
        {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
      </button>
    </div>
  )
}
