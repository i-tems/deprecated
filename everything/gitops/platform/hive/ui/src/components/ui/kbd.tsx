import { cn } from '@/lib/utils'

export function Kbd({ className, children }: { className?: string; children: React.ReactNode }) {
  return (
    <kbd
      className={cn(
        'inline-flex items-center rounded-md border border-border bg-bg-hover px-1.5 py-0.5',
        'text-2xs font-medium text-text-tertiary font-mono',
        className,
      )}
    >
      {children}
    </kbd>
  )
}
