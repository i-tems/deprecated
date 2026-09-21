import { useRef, useState } from 'react'
import { Smile } from 'lucide-react'
import EmojiPicker, { EmojiStyle, Theme, type EmojiClickData } from 'emoji-picker-react'
import { Popover } from '@/components/Popover'

type Size = 'sm' | 'md' | 'lg'

interface IconPickerButtonProps {
  icon?: string | null
  onChange: (next: string | null) => void | Promise<void>
  size?: Size
  /** title attribute override (기본: "Add icon" / "Change icon"). */
  title?: string
}

const SIZE_CLASS: Record<Size, string> = {
  sm: 'text-sm w-6 h-6',
  md: 'text-base w-7 h-7',
  lg: 'text-2xl w-10 h-10',
}

const PLACEHOLDER_SIZE: Record<Size, number> = {
  sm: 12,
  md: 14,
  lg: 18,
}

/** 클릭 가능한 entity icon (이모지) — popover 안에 emoji-picker-react 의 Picker. icon 없으면 placeholder smile. */
export function IconPickerButton({ icon, onChange, size = 'md', title }: IconPickerButtonProps) {
  const [open, setOpen] = useState(false)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const hasIcon = !!icon
  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={`shrink-0 rounded transition-colors leading-none flex items-center justify-center hover:bg-bg-hover ${SIZE_CLASS[size]}`}
        title={title ?? (hasIcon ? 'Change icon' : 'Add icon')}
      >
        {hasIcon ? icon : <Smile size={PLACEHOLDER_SIZE[size]} className="text-text-quaternary" />}
      </button>
      <Popover
        open={open}
        anchorRef={triggerRef}
        onClose={() => setOpen(false)}
        className="rounded-lg overflow-hidden shadow-xl border border-border bg-bg-elevated animate-in fade-in slide-in-from-top-1 duration-150"
      >
        <EmojiPicker
          theme={Theme.AUTO}
          emojiStyle={EmojiStyle.NATIVE}
          onEmojiClick={async (data: EmojiClickData) => {
            await onChange(data.emoji)
            setOpen(false)
          }}
          width={320}
          height={380}
          previewConfig={{ showPreview: false }}
          lazyLoadEmojis
        />
        {hasIcon && (
          <button
            type="button"
            onClick={async () => {
              await onChange(null)
              setOpen(false)
            }}
            className="w-full text-xs text-text-tertiary hover:bg-bg-hover py-2 border-t border-border"
          >
            Remove icon
          </button>
        )}
      </Popover>
    </>
  )
}
