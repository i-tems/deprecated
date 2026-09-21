import { cn } from '@/lib/utils'

export function Empty({
  icon,
  title,
  description,
  action,
  className,
}: {
  icon?: React.ReactNode
  title: string
  description?: string
  action?: React.ReactNode
  className?: string
}) {
  return (
    <div className={cn('flex flex-col items-center justify-center py-16 text-center', className)}>
      {icon && <div className="mb-3 text-text-tertiary">{icon}</div>}
      <p className="text-base font-medium text-text-secondary">{title}</p>
      {description && <p className="mt-1 text-xs text-text-tertiary max-w-sm">{description}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  )
}
