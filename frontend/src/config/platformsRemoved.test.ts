/**
 * T03: the TradingView, GoCharting, Chartink and Platforms pages and the
 * per-broker login forms are gone from the React app, with their routes, nav
 * entries, page titles and alert category. Kept: /broker and /broker/config,
 * Flow and Strategy-module webhooks (their pages may still name TradingView as
 * an alert source).
 */

import { describe, expect, it } from 'vitest'
import appSource from '@/App.tsx?raw'
import logoutDialogSource from '@/components/auth/LogoutConfirmDialog.tsx?raw'
import pageTitleSource from '@/hooks/usePageTitle.ts?raw'
import { makeFormatCurrency } from '@/lib/utils'
import utilsSource from '@/lib/utils.ts?raw'
import brokerSelectSource from '@/pages/BrokerSelect.tsx?raw'
import faqSource from '@/pages/Faq.tsx?raw'
import homeSource from '@/pages/Home.tsx?raw'
import profileSource from '@/pages/Profile.tsx?raw'
import alertStoreSource from '@/stores/alertStore.ts?raw'
import { navItems, profileMenuItems, sidebarGroups } from './navigation'

const deletedFiles = import.meta.glob([
  '../pages/BrokerTOTP.tsx',
  '../pages/SamcoAuth.tsx',
  '../pages/Platforms.tsx',
  '../pages/TradingView.tsx',
  '../pages/GoCharting.tsx',
  '../pages/chartink/**',
  '../api/chartink.ts',
  '../types/chartink.ts',
])

const PLATFORM = /chartink|gocharting|tradingview|BrokerTOTP|SamcoAuth|\/platforms/i

describe('removed platform and broker-form pages', () => {
  it('deletes the page, api and type files', () => {
    expect(Object.keys(deletedFiles)).toEqual([])
  })

  it('App.tsx routes none of them and keeps the broker pages', () => {
    expect(appSource).not.toMatch(PLATFORM)
    expect(appSource).not.toMatch(/path="\/:broker\/auth"/)
    expect(appSource).not.toMatch(/path="\/broker\/:broker\/totp"/)
    expect(appSource).toMatch(/path="\/broker"/)
    expect(appSource).toMatch(/path="\/broker\/config"/)
  })

  it('no nav entry points at a removed page', () => {
    const hrefs = [
      ...navItems.map((i) => i.href),
      ...profileMenuItems.map((i) => i.href),
      ...sidebarGroups.flatMap((g) => g.items.map((i) => i.href)),
    ]
    expect(hrefs.filter((h) => PLATFORM.test(h))).toEqual([])
  })

  it('the Automate group lists Strategies, Python and Flow only', () => {
    const automate = sidebarGroups.find((g) => g.label === 'Automate')
    expect(automate?.items.map((i) => i.label)).toEqual(['Strategies', 'Python', 'Flow'])
  })

  it('Strategies sits directly after Trading in the top nav', () => {
    const labels = navItems.map((i) => i.label)
    expect(labels).not.toContain('Platforms')
    expect(labels.indexOf('Strategies')).toBe(labels.indexOf('Trading') + 1)
  })

  it('page titles and the alert category forget the platforms', () => {
    expect(pageTitleSource).not.toMatch(PLATFORM)
    expect(alertStoreSource).not.toMatch(/chartink/i)
    expect(profileSource).not.toMatch(/chartink|gocharting|tradingview/i)
  })

  it('trader-facing copy names only Zerodha and the Sandbox', () => {
    expect(logoutDialogSource).not.toMatch(/tradingview|chartink/i)
    expect(logoutDialogSource).toContain('Webhook and REST API signals')
    expect(homeSource).not.toMatch(/chartink|gocharting|amibroker/i)
    expect(faqSource).not.toMatch(/36 broker|chartink|gocharting/i)
  })

  it('Select Broker carries no note for a removed broker', () => {
    expect(brokerSelectSource).not.toMatch(/\bdhan\b/i)
  })

  it('currency is always rupees now that the crypto broker is gone', () => {
    expect(utilsSource).not.toMatch(/deltaexchange/i)
    const format = makeFormatCurrency('deltaexchange')
    expect(format(1234.5)).toContain('₹')
  })
})
