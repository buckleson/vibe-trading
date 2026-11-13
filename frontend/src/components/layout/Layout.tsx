import { Menu } from 'lucide-react'
import { useState } from 'react'
import { Link, Navigate, Outlet, useLocation } from 'react-router'
import { BrandWordmark } from '@/components/brand/BrandMark'
import { ClaudePanel, ClaudeStatusPill, useClaudeStatusPolling } from '@/components/claude/ClaudePanel'
import { SocketProvider } from '@/components/socket/SocketProvider'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { isActiveSection, sidebarGroups } from '@/config/navigation'
import { isPreBrokerPath } from '@/lib/brokerProfiles'
import { useAuthStore } from '@/stores/authStore'
import { AccountControls } from './AccountControls'
import { MobileBottomNav } from './MobileBottomNav'
import { Sidebar, SidebarNav } from './Sidebar'

function useCrumb(): { group: string | null; label: string | null } {
  const { pathname } = useLocation()
  for (const group of sidebarGroups) {
    const hit = group.items.find((item) => isActiveSection(pathname, item.href))
    if (hit) return { group: group.label, label: hit.label }
  }
  return { group: null, label: null }
}

export function Topbar({ onMenu }: { onMenu?: () => void }) {
  const { group, label } = useCrumb()
  return (
    <header className="sticky top-0 z-30 flex h-14 shrink-0 items-center gap-3 border-b bg-background/85 px-4 backdrop-blur-md supports-[backdrop-filter]:bg-background/70 lg:px-6">
      {onMenu && (
        <button
          type="button"
          onClick={onMenu}
          className="-ml-1 flex h-9 w-9 items-center justify-center rounded-md text-muted-foreground hover:bg-accent lg:hidden"
          aria-label="Open navigation"
        >
          <Menu className="h-5 w-5" />
        </button>
      )}
      <Link to="/dashboard" className="lg:hidden" aria-label="Buckleson home">
        <BrandWordmark compact />
      </Link>
      {label && (
        <div className="hidden min-w-0 items-center gap-1.5 text-sm sm:flex">
          <span className="text-muted-foreground">{group}</span>
          <span className="text-muted-foreground/50">/</span>
          <span className="truncate font-medium">{label}</span>
        </div>
      )}
      <div className="ml-auto flex items-center gap-1.5">
        <ClaudeStatusPill />
        <AccountControls />
      </div>
    </header>
  )
}

export function Layout() {
  const { isAuthenticated, user } = useAuthStore()
  const { pathname } = useLocation()
  const [mobileOpen, setMobileOpen] = useState(false)
  useClaudeStatusPolling()

  const preBroker = Boolean(user?.username) && isPreBrokerPath(pathname)

  if (!isAuthenticated && !preBroker) {
    return <Navigate to="/login" replace />
  }
  if (!user?.broker && !preBroker) {
    return <Navigate to="/broker" replace />
  }

  return (
    <SocketProvider>
      <div className="flex min-h-screen bg-background">
        <Sidebar />
        <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
          <SheetContent side="left" className="w-72 overflow-y-auto bg-sidebar p-0">
            <SheetHeader className="h-14 justify-center px-5">
              <SheetTitle className="sr-only">Navigation</SheetTitle>
              <SheetDescription className="sr-only">Main navigation</SheetDescription>
              <BrandWordmark />
            </SheetHeader>
            <SidebarNav onNavigate={() => setMobileOpen(false)} />
          </SheetContent>
        </Sheet>
        <div className="flex min-w-0 flex-1 flex-col">
          <Topbar onMenu={() => setMobileOpen(true)} />
          <main className="mx-auto w-full max-w-[1440px] flex-1 px-4 py-6 pb-24 md:pb-8 lg:px-8">
            <Outlet />
          </main>
          <MobileBottomNav />
        </div>
        <ClaudePanel />
      </div>
    </SocketProvider>
  )
}

export function PublicLayout() {
  return (
    <div className="min-h-screen bg-background">
      <Outlet />
    </div>
  )
}
