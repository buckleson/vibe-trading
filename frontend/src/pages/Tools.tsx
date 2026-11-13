import { ArrowRight } from 'lucide-react'
import { Link } from 'react-router'
import { tools } from '@/lib/tools'

export default function Tools() {
  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold">Tools</h1>
        <p className="text-muted-foreground mt-1">
          Analytical tools for options trading and market analysis
        </p>
      </div>

      {/* Tool list: one quiet row style, initials on a neutral tile. */}
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
        {tools.map((tool) => (
          <Link
            key={tool.href}
            to={tool.href}
            className="group flex gap-3.5 rounded-xl border bg-card p-4 transition-colors hover:border-foreground/20 hover:bg-accent/40"
          >
            <div className="min-w-0">
              <div className="flex items-center gap-1.5 text-sm font-medium">
                {tool.title}
                <ArrowRight className="h-3.5 w-3.5 -translate-x-1 opacity-0 transition-all group-hover:translate-x-0 group-hover:opacity-100" />
              </div>
              <p className="mt-0.5 line-clamp-2 text-[13px] leading-snug text-muted-foreground">{tool.description}</p>
            </div>
          </Link>
        ))}
      </div>
    </div>
  )
}
