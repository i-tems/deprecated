import { Link2, Hash, ClipboardCopy } from 'lucide-react'
import { useToast } from '@/components/ui/toast'

interface EntityActionsProps {
  entityId: string
  /** "Copy as prompt" 클릭 시 클립보드에 들어갈 markdown 문자열을 만들어주는 함수. */
  asPrompt: () => string
}

/** Linear-style entity 액션 toolbar. 우측 sidebar 첫 행에 가로 배치. */
export function EntityActions({ entityId, asPrompt }: EntityActionsProps) {
  const toast = useToast()
  const copy = async (text: string, label: string) => {
    try {
      await navigator.clipboard.writeText(text)
      toast.success(`Copied ${label}`)
    } catch {
      toast.error(`Copy failed`)
    }
  }
  return (
    <div className="flex items-center gap-0.5 justify-end">
      <ToolbarButton title="Copy link" onClick={() => copy(window.location.href, 'link')}>
        <Link2 size={14} />
      </ToolbarButton>
      <ToolbarButton title="Copy ID" onClick={() => copy(entityId, 'ID')}>
        <Hash size={14} />
      </ToolbarButton>
      <ToolbarButton title="Copy as prompt" onClick={() => copy(asPrompt(), 'prompt')}>
        <ClipboardCopy size={14} />
      </ToolbarButton>
    </div>
  )
}

function ToolbarButton({
  title, onClick, children,
}: {
  title: string
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      title={title}
      aria-label={title}
      onClick={onClick}
      className="p-1.5 text-text-tertiary hover:text-text rounded-md hover:bg-bg-hover transition-colors"
    >
      {children}
    </button>
  )
}
