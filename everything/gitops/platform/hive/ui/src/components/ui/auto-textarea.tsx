import { useRef, useEffect, type TextareaHTMLAttributes } from 'react'

type AutoTextareaProps = Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, 'style'> & {
  minRows?: number
}

export function AutoTextarea({ minRows = 2, value, onChange, ...props }: AutoTextareaProps) {
  const ref = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    const el = ref.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${el.scrollHeight}px`
  }, [value])

  return (
    <textarea
      ref={ref}
      value={value}
      onChange={onChange}
      rows={minRows}
      style={{ overflow: 'hidden' }}
      {...props}
    />
  )
}
