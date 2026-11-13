import { FlaskConical, Moon, Radio, Sun } from 'lucide-react'
import { useNavigate } from 'react-router'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { useProfileMenuItems } from '@/hooks/useProfileMenuItems'
import { cn } from '@/lib/utils'
import { useAuthStore } from '@/stores/authStore'
import { useThemeStore } from '@/stores/themeStore'
import { showToast } from '@/utils/toast'

/**
 * The account end of the app's header: the broker, which mode the platform is
 * in, the switch between Live and Analyze, light or dark, and the profile menu.
 *
 * One component in two places. The navbar shows it on every page, and the
 * charting terminal, which gives the whole viewport to the chart and has no
 * navbar, shows it at the end of its toolbar row. Both run the same mode
 * switch, the same warnings and the same logout, so the terminal cannot drift
 * into a second idea of what switching mode means.
 *
 * `variant` changes metrics only. The navbar keeps its own spacing and the
 * breakpoints its fit test holds it to; the toolbar sizes everything to the
 * terminal's 28px controls.
 */
export function AccountControls({ variant = 'navbar' }: { variant?: 'navbar' | 'toolbar' }) {
  const navigate = useNavigate()
  const { mode, appMode, toggleMode, toggleAppMode, isTogglingMode } = useThemeStore()
  const { user } = useAuthStore()
  const toolbar = variant === 'toolbar'

  // Profile menu filtered by broker capabilities (shared hook, issue #1480)
  const filteredProfileMenuItems = useProfileMenuItems()

  const handleModeToggle = async () => {
    const result = await toggleAppMode()
    if (result.success) {
      const newMode = useThemeStore.getState().appMode
      showToast.success(`Switched to ${newMode === 'live' ? 'Live' : 'Sandbox'} mode`)

      // Show warning toast when enabling analyzer mode (like old UI)
      if (newMode === 'analyzer') {
        setTimeout(() => {
          showToast.warning('Sandbox mode: every order is simulated', undefined, {
            duration: 10000,
          })
        }, 2000)
      }
    } else {
      showToast.error(result.message || 'Failed to toggle mode')
    }
  }

  // The toolbar's quiet button: its glyph on the toolbar surface, a fill on hover.
  const iconButton = toolbar
    ? 'h-7 w-7 rounded-md text-foreground/80 hover:bg-accent hover:text-foreground dark:hover:bg-accent'
    : 'h-8 w-8'
  const glyph = 'h-4 w-4'
  const modeLabel = appMode === 'live' ? 'Live' : 'Sandbox'

  return (
    <>
      {/* Broker badge: hidden below lg to keep the bar within narrow
          (portrait/small-laptop) widths */}
      {user?.broker && user.broker !== 'paper' && (
        <Badge
          variant="outline"
          className={cn(
            'hidden lg:flex',
            toolbar ? 'h-6 px-2 text-[11px] font-medium text-muted-foreground' : 'text-xs'
          )}
        >
          {user.broker}
        </Badge>
      )}

      {/* Mode Badge: amber for Sandbox, red for Live. */}
      <span
        className={cn(
          'inline-flex items-center gap-1.5 rounded-full border font-medium',
          toolbar ? 'h-6 px-2 text-[11px]' : 'h-7 px-2.5 text-xs',
          appMode === 'live'
            ? 'border-red-500/30 bg-red-500/10 text-red-600 dark:text-red-400'
            : 'border-sandbox/30 bg-sandbox/10 text-sandbox'
        )}
        title={appMode === 'live' ? 'Orders go to your broker' : 'Orders are simulated with sandbox capital'}
      >
        <span className={cn('h-1.5 w-1.5 rounded-full', appMode === 'live' ? 'bg-red-500' : 'bg-sandbox')} />
        {modeLabel}
      </span>

      {/* Mode Toggle */}
      <Button
        variant="ghost"
        size="icon"
        className={iconButton}
        onClick={handleModeToggle}
        disabled={isTogglingMode}
        title={`Switch to ${appMode === 'live' ? 'Sandbox' : 'Live'} mode`}
        aria-label={`Switch to ${appMode === 'live' ? 'Sandbox' : 'Live'} mode`}
      >
        {isTogglingMode ? (
          <div className="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" />
        ) : appMode === 'live' ? (
          <FlaskConical className={glyph} />
        ) : (
          <Radio className={glyph} />
        )}
      </Button>

      {/* Theme Toggle */}
      <Button
        variant="ghost"
        size="icon"
        className={iconButton}
        onClick={toggleMode}
        disabled={appMode !== 'live'}
        title={mode === 'light' ? 'Switch to dark mode' : 'Switch to light mode'}
        aria-label={mode === 'light' ? 'Switch to dark mode' : 'Switch to light mode'}
      >
        {mode === 'light' ? <Sun className={glyph} /> : <Moon className={glyph} />}
      </Button>

      {/* Profile Dropdown */}
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            variant="ghost"
            size="icon"
            className={cn(
              'rounded-full bg-secondary text-foreground border',
              toolbar
                ? 'ml-0.5 h-7 w-7 hover:bg-accent'
                : 'h-8 w-8'
            )}
            aria-label="Open user menu"
          >
            <span className={toolbar ? 'text-[13px] font-semibold' : 'text-sm font-medium'}>
              {user?.username?.[0]?.toUpperCase() || 'B'}
            </span>
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-56">
          {filteredProfileMenuItems.map((item) =>
            item.external ? (
              <DropdownMenuItem key={item.href} asChild className="cursor-pointer">
                <a href={item.href} className="flex items-center">
                  <item.icon className="h-4 w-4 mr-2" />
                  {item.label}
                </a>
              </DropdownMenuItem>
            ) : (
              <DropdownMenuItem
                key={item.href}
                onSelect={() => navigate(item.href)}
                className="cursor-pointer"
              >
                <item.icon className="h-4 w-4 mr-2" />
                {item.label}
              </DropdownMenuItem>
            )
          )}
        </DropdownMenuContent>
      </DropdownMenu>

    </>
  )
}
