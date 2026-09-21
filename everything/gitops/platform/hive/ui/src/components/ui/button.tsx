import { forwardRef } from 'react'
import { cn } from '@/lib/utils'

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger'
type Size = 'sm' | 'md' | 'lg'

const variantStyles: Record<Variant, string> = {
  primary: 'bg-accent text-white hover:bg-accent-hover',
  secondary: 'bg-bg-hover text-text hover:bg-bg-active',
  ghost: 'bg-transparent text-text-secondary hover:bg-bg-hover hover:text-text',
  danger: 'bg-error-muted text-error hover:bg-error/20',
}

const sizeStyles: Record<Size, string> = {
  sm: 'h-9 md:h-7 px-3 md:px-2.5 text-xs gap-1.5',
  md: 'h-10 md:h-8 px-3 text-sm gap-2',
  lg: 'h-11 md:h-9 px-4 text-sm gap-2',
}

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  size?: Size
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ variant = 'secondary', size = 'md', className, ...props }, ref) => (
    <button
      ref={ref}
      className={cn(
        'inline-flex items-center justify-center rounded-lg font-medium transition-colors cursor-pointer',
        'disabled:opacity-40 disabled:pointer-events-none',
        variantStyles[variant],
        sizeStyles[size],
        className,
      )}
      {...props}
    />
  ),
)
Button.displayName = 'Button'
