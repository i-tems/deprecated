import { useRef, useState } from 'react'
import { ChevronDown } from 'lucide-react'
import { Popover } from '@/components/Popover'

export type ModelTier = 'high' | 'medium' | 'low'

const TIER_ORDER: ModelTier[] = ['high', 'medium', 'low']

const TIER_LABEL: Record<ModelTier, string> = {
  high: 'High (Opus)',
  medium: 'Medium (Sonnet)',
  low: 'Low (Haiku)',
}

const TIER_COLOR: Record<ModelTier, string> = {
  high: 'text-accent',
  medium: 'text-text',
  low: 'text-text-tertiary',
}

function ModelIcon({ tier, size = 14 }: { tier: ModelTier | null; size?: number }) {
  const bars = tier === 'high' ? 3 : tier === 'medium' ? 2 : 1
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" aria-hidden="true">
      {[0, 1, 2].map((i) => (
        <rect
          key={i}
          x={2 + i * 4}
          y={13 - (i + 1) * 3}
          width={2.5}
          height={(i + 1) * 3}
          rx={0.5}
          opacity={tier === null || i < bars ? 1 : 0.25}
          fill="currentColor"
        />
      ))}
    </svg>
  )
}

interface ModelPickerProps {
  /** 현재 issue.model ('high'|'medium'|'low'|null). null = 기본 tier(high). */
  value: string | null | undefined
  onChange: (model: ModelTier | null) => void
}

function toTier(value: string | null | undefined): ModelTier | null {
  if (value === 'high' || value === 'medium' || value === 'low') return value
  return null
}

export function ModelPicker({ value, onChange }: ModelPickerProps) {
  const [open, setOpen] = useState(false)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const current = toTier(value)

  const select = (tier: ModelTier | null) => {
    if (tier !== current) onChange(tier)
    setOpen(false)
  }

  const triggerColor = current === 'high' ? 'text-accent'
    : current === 'medium' ? 'text-text'
    : current === 'low' ? 'text-text-tertiary'
    : 'text-text-tertiary'

  const triggerLabel = current ? TIER_LABEL[current] : 'Default (Opus)'

  return (
    <div>
      <button
        ref={triggerRef}
        data-kb="model"
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full hover:bg-bg-hover transition-colors text-sm"
        title="Set model tier"
      >
        <span className={triggerColor}>
          <ModelIcon tier={current} size={14} />
        </span>
        <span>{triggerLabel}</span>
        <ChevronDown size={10} className="text-text-tertiary" />
      </button>

      <Popover
        open={open}
        anchorRef={triggerRef}
        onClose={() => setOpen(false)}
        className="w-56 rounded-md border border-border bg-bg shadow-lg overflow-hidden"
      >
        <div className="px-2 py-1.5 text-xs text-text-tertiary border-b border-border-subtle">
          Set model tier…
        </div>
        <ul className="py-1">
          <li>
            <button
              type="button"
              onClick={() => select(null)}
              className="w-full flex items-center gap-2 px-2 py-1.5 text-left text-sm hover:bg-bg-hover transition-colors"
            >
              <span className="text-text-tertiary">
                <ModelIcon tier={null} size={14} />
              </span>
              <span className="flex-1">Default (Opus)</span>
              {current === null && <span className="text-text-tertiary">✓</span>}
            </button>
          </li>
          {TIER_ORDER.map((tier) => {
            const isCurrent = tier === current
            return (
              <li key={tier}>
                <button
                  type="button"
                  onClick={() => select(tier)}
                  className="w-full flex items-center gap-2 px-2 py-1.5 text-left text-sm hover:bg-bg-hover transition-colors"
                >
                  <span className={TIER_COLOR[tier]}>
                    <ModelIcon tier={tier} size={14} />
                  </span>
                  <span className="flex-1">{TIER_LABEL[tier]}</span>
                  {isCurrent && <span className="text-text-tertiary">✓</span>}
                </button>
              </li>
            )
          })}
        </ul>
      </Popover>
    </div>
  )
}
