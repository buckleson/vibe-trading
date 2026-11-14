import {
  Activity,
  BarChart3,
  Bell,
  BellRing,
  BookOpen,
  Bot,
  Boxes,
  CandlestickChart,
  ClipboardList,
  Code2,
  Database,
  FileBarChart,
  FileStack,
  FileText,
  FlaskConical,
  Gauge,
  Key,
  Layers,
  LayoutDashboard,
  LineChart,
  type LucideIcon,
  Search,
  Settings,
  Sparkles,
  TrendingUp,
  User,
  Workflow,
  Wrench,
  Zap,
} from 'lucide-react'

export interface NavItem {
  href: string
  label: string
  icon: LucideIcon
  /** Served by Flask (not a React route): render as a full-page link. */
  external?: boolean
  /**
   * Desktop navbar only: below this Tailwind breakpoint the item leaves the
   * bar and is listed under More instead. Items without it always stay.
   */
  collapseBelow?: 'lg' | 'xl'
}

// Main navigation items shown in desktop navbar
export const navItems: NavItem[] = [
  { href: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { href: '/orderbook', label: 'Orderbook', icon: ClipboardList },
  { href: '/tradebook', label: 'Tradebook', icon: FileText, collapseBelow: 'lg' },
  { href: '/positions', label: 'Positions', icon: TrendingUp },
  { href: '/trading', label: 'Trading', icon: CandlestickChart, collapseBelow: 'lg' },
  { href: '/strategy', label: 'Strategies', icon: Boxes, collapseBelow: 'xl' },
  { href: '/logs', label: 'Logs', icon: FileBarChart, collapseBelow: 'xl' },
  { href: '/tools', label: 'Tools', icon: Wrench, collapseBelow: 'xl' },
]

// Items shown in mobile bottom navigation
export const bottomNavItems: NavItem[] = [
  { href: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { href: '/orderbook', label: 'Orderbook', icon: ClipboardList },
  { href: '/tradebook', label: 'Tradebook', icon: FileText },
  { href: '/positions', label: 'Positions', icon: TrendingUp },
]

// Paths in bottom nav (for filtering mobile sheet items)
const bottomNavPaths = bottomNavItems.map((item) => item.href)

// Secondary items for mobile sheet (items not in bottom nav)
export const mobileSheetItems = navItems.filter((item) => !bottomNavPaths.includes(item.href))

// Profile dropdown menu items
export const profileMenuItems: NavItem[] = [
  { href: '/profile', label: 'Profile', icon: User },
  { href: '/apikey', label: 'API Key', icon: Key },
  // Action Center stays immediately after API Key. It was moved here out of the
  // main navbar on that understanding and a test pins the adjacency, so a new
  // entry goes after it rather than between the two.
  { href: '/action-center', label: 'Action Center', icon: Bell },
  // Agent Config is NOT here. It lives under /admin with the other
  // configuration surfaces. The chat header carries its own settings control,
  // so a configured /agent still has a route back to its settings without this
  // menu holding one.
  { href: '/agent', label: 'Agent', icon: Bot },
  { href: '/master-contract', label: 'Master Contract', icon: FileStack },
  // One entry for every alert channel. /alerts links to the Telegram,
  // WhatsApp, Slack and Discord pages, so none needs an entry of its own.
  { href: '/alerts', label: 'Alerts', icon: BellRing },
  { href: '/holdings', label: 'Holdings', icon: ClipboardList },
  { href: '/flow', label: 'Flow Editor', icon: Workflow },
  { href: '/scalping', label: 'Scalping', icon: Zap },
  { href: '/python', label: 'Python Strategies', icon: Code2 },
  { href: '/pnl-tracker', label: 'PnL Tracker', icon: BarChart3 },
  { href: '/historify', label: 'Historify', icon: Database },
  { href: '/search/token', label: 'Search', icon: Search },
  { href: '/sandbox', label: 'Sandbox', icon: FlaskConical },
  { href: '/leverage', label: 'Leverage', icon: Gauge },
  { href: '/admin', label: 'Admin', icon: Settings },
]

// Sidebar: the main shell's grouped navigation.
export interface NavGroup {
  label: string
  items: NavItem[]
}

export const sidebarGroups: NavGroup[] = [
  {
    label: 'Desk',
    items: [
      { href: '/dashboard', label: 'Overview', icon: LayoutDashboard },
      { href: '/claude', label: 'Claude', icon: Sparkles },
      { href: '/positions', label: 'Positions', icon: TrendingUp },
      { href: '/orderbook', label: 'Orders', icon: ClipboardList },
      { href: '/tradebook', label: 'Trades', icon: FileText },
      { href: '/holdings', label: 'Holdings', icon: Layers },
      { href: '/sandbox/mypnl', label: 'Sandbox P&L', icon: LineChart },
    ],
  },
  {
    label: 'Trade',
    items: [
      { href: '/trading', label: 'Chart terminal', icon: CandlestickChart, external: true },
      { href: '/scalping', label: 'Scalping', icon: Zap },
      { href: '/optionchain', label: 'Option chain', icon: Activity },
      { href: '/search/token', label: 'Symbols', icon: Search },
    ],
  },
  {
    label: 'Automate',
    items: [
      { href: '/strategy', label: 'Strategies', icon: Boxes },
      { href: '/python', label: 'Python', icon: Code2 },
      { href: '/flow', label: 'Flow', icon: Workflow },
    ],
  },
  {
    label: 'Research',
    items: [
      { href: '/tools', label: 'Tools', icon: Wrench },
      { href: '/historify', label: 'Historify', icon: Database },
      { href: '/pnl-tracker', label: 'P&L tracker', icon: BarChart3 },
    ],
  },
  {
    label: 'System',
    items: [
      { href: '/sandbox', label: 'Sandbox settings', icon: FlaskConical },
      { href: '/logs', label: 'Logs', icon: FileBarChart },
      { href: '/alerts', label: 'Alerts', icon: BellRing },
      { href: '/apikey', label: 'API key', icon: Key },
      { href: '/admin', label: 'Admin', icon: Settings },
    ],
  },
]

// External links
export const externalLinks = {
  docs: { href: 'https://docs.openalgo.in', label: 'Docs', icon: BookOpen },
}

// Shared utility to check if a route is active.
// Every nav item is a leaf route, so an exact match is all that is needed.
export function isActiveRoute(pathname: string, href: string): boolean {
  return pathname === href
}

// Sidebar matching: a section stays highlighted on its child pages.
export function isActiveSection(pathname: string, href: string): boolean {
  if (pathname === href) return true
  if (href === '/dashboard' || href === '/sandbox') return false
  return pathname.startsWith(`${href}/`)
}
