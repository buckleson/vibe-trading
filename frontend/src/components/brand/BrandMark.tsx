import { cn } from '@/lib/utils'

/**
 * The Buckleson mark and wordmark.
 *
 * To use your own artwork, replace frontend/public/logo.svg (and logo.png /
 * favicon.ico) and set USE_IMAGE_LOGO to true: the image is then shown
 * everywhere this component is used.
 */
const USE_IMAGE_LOGO = false

export function BrandMark({ className }: { className?: string }) {
  if (USE_IMAGE_LOGO) {
    return <img src="/logo.svg" alt="Buckleson" className={cn('h-7 w-7', className)} />
  }
  return (
    <svg
      viewBox="0 0 32 32"
      className={cn('h-7 w-7 shrink-0', className)}
      role="img"
      aria-label="Buckleson"
    >
      <rect width="32" height="32" rx="8" className="fill-foreground" />
      <path
        fillRule="evenodd"
        className="fill-background"
        d="M10 7.5h7.1a4.3 4.3 0 0 1 3.05 7.33A4.6 4.6 0 0 1 17.6 24.5H10Zm3.1 3v3.25h3.7a1.62 1.62 0 0 0 0-3.25Zm0 6.1v4.9h4.35a2.45 2.45 0 0 0 0-4.9Z"
      />
      <circle cx="23.2" cy="23.2" r="1.9" className="fill-brand" />
    </svg>
  )
}

export function BrandWordmark({ className, compact = false }: { className?: string; compact?: boolean }) {
  return (
    <span className={cn('flex items-center gap-2.5', className)}>
      <BrandMark />
      {!compact && (
        <span className="text-[15px] font-semibold tracking-[-0.02em] text-foreground">Buckleson</span>
      )}
    </span>
  )
}
