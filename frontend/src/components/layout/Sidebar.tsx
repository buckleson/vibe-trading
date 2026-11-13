import { Link, useLocation } from 'react-router'
import { BrandWordmark } from '@/components/brand/BrandMark'
import { StatusDot, useClaudeState } from '@/components/claude/ClaudePanel'
import { isActiveSection, type NavItem, sidebarGroups } from '@/config/navigation'
import { cn } from '@/lib/utils'
import { useBrokerStore } from '@/stores/brokerStore'

function SidebarLink({ item, onNavigate }: { item: NavItem; onNavigate?: () => void }) {
  const { pathname } = useLocation()
  const active = isActiveSection(pathname, item.href)
  const { state } = useClaudeState()
  const cls = cn(
    'group flex h-8 items-center gap-2.5 rounded-md px-2.5 text-[13px] transition-colors',
    active
      ? 'bg-sidebar-accent font-medium text-sidebar-accent-foreground'
      : 'text-sidebar-foreground/80 hover:bg-sidebar-accent/60 hover:text-sidebar-accent-foreground'
  )
  const inner = (
    <>
      <item.icon
        className={cn('h-4 w-4 shrink-0', active ? 'text-foreground' : 'text-muted-foreground group-hover:text-foreground')}
        strokeWidth={1.75}
      />
      <span className="truncate">{item.label}</span>
      {item.href === '/claude' && <StatusDot state={state} className="ml-auto" />}
    </>
  )
  return item.external ? (
    <a href={item.href} className={cls} onClick={onNavigate}>
      {inner}
    </a>
  ) : (
    <Link to={item.href} className={cls} aria-current={active ? 'page' : undefined} onClick={onNavigate}>
      {inner}
    </Link>
  )
}

export function SidebarNav({ onNavigate }: { onNavigate?: () => void }) {
  const capabilities = useBrokerStore((s) => s.capabilities)
  return (
    <nav className="flex flex-col gap-5 px-3 pb-6">
      {sidebarGroups.map((group) => (
        <div key={group.label} className="flex flex-col gap-0.5">
          <div className="px-2.5 pb-1 text-[11px] font-medium text-muted-foreground/80">{group.label}</div>
          {group.items
            .filter((item) => !(item.href === '/holdings' && capabilities?.broker_type === 'crypto'))
            .map((item) => (
              <SidebarLink key={item.href} item={item} onNavigate={onNavigate} />
            ))}
        </div>
      ))}
    </nav>
  )
}

export function Sidebar() {
  return (
    <aside className="sticky top-0 hidden h-screen w-[232px] shrink-0 flex-col border-r bg-sidebar lg:flex">
      <div className="flex h-14 shrink-0 items-center px-5">
        <Link to="/dashboard" aria-label="Buckleson home">
          <BrandWordmark />
        </Link>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto pt-2">
        <SidebarNav />
      </div>
    </aside>
  )
}
