import { cn } from '@/lib/utils'

type Variant = 'default' | 'success' | 'warning' | 'error' | 'info' | 'accent' | 'ghost'

const variants: Record<Variant, string> = {
  default: 'bg-bg-hover text-text-secondary',
  success: 'bg-success-muted text-success',
  warning: 'bg-warning-muted text-warning',
  error: 'bg-error-muted text-error',
  info: 'bg-info-muted text-info',
  accent: 'bg-accent-muted text-accent-text',
  ghost: 'bg-transparent text-text-tertiary border border-border',
}

export function Badge({
  variant = 'default',
  className,
  children,
}: {
  variant?: Variant
  className?: string
  children: React.ReactNode
}) {
  return (
    <span
      className={cn(
        'inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium tracking-tight',
        variants[variant],
        className,
      )}
    >
      {children}
    </span>
  )
}
