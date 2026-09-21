import { useRef, useState } from 'react'
import { ChevronDown, User } from 'lucide-react'
import { OwnerAvatar } from '@/components/OwnerAvatar'
import { KbdHint } from '@/components/KbdHint'
import { Popover } from '@/components/Popover'
import { useAuth } from '@/contexts/AuthContext'
import { useCell } from '@/contexts/CellContext'

interface AssigneePickerProps {
  /** 현재 issue.owner (resolved 아닌 직접 owner) */
  owner: string | null | undefined
  /** 보조 표시용 — 상속 owner */
  resolvedOwner?: string | null
  onChange: (email: string | null) => void
}

export function AssigneePicker({ owner, resolvedOwner, onChange }: AssigneePickerProps) {
  const [open, setOpen] = useState(false)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const { user } = useAuth()
  const { currentCell } = useCell()

  // 셀의 allowed_emails를 멤버 목록으로. 현재 user는 항상 맨 위.
  const members = (() => {
    const set = new Set<string>()
    if (user?.email) set.add(user.email)
    for (const e of (currentCell?.allowed_emails ?? [])) set.add(e)
    return Array.from(set)
  })()

  const select = (email: string | null) => {
    if (email !== owner) onChange(email)
    setOpen(false)
  }

  const display = owner ?? resolvedOwner ?? null
  const isInherited = !owner && !!resolvedOwner

  return (
    <div>
      <button
        ref={triggerRef}
        data-kb="assignee"
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full hover:bg-bg-hover transition-colors text-sm"
        title="Assignee (a)"
      >
        {display ? (
          <OwnerAvatar email={display} size="xs" />
        ) : (
          <User size={13} className="text-text-tertiary" />
        )}
        <span>
          {display
            ? (user?.email === display ? 'Me' : display.split('@')[0])
            : 'Assign'}
          {isInherited && <span className="text-2xs text-text-tertiary ml-1">(inherited)</span>}
        </span>
        <ChevronDown size={10} className="text-text-tertiary" />
        <KbdHint k="a" />
      </button>

      <Popover
        open={open}
        anchorRef={triggerRef}
        onClose={() => setOpen(false)}
        className="w-64 rounded-md border border-border bg-bg shadow-lg overflow-hidden"
      >
        <div className="px-2 py-1.5 text-xs text-text-tertiary border-b border-border-subtle">
          Assign to…
        </div>
        <ul className="max-h-[300px] overflow-y-auto py-1">
          <li>
            <button
              type="button"
              onClick={() => select(null)}
              className="w-full flex items-center gap-2 px-2 py-1.5 text-left text-sm hover:bg-bg-hover transition-colors"
            >
              <User size={14} className="text-text-tertiary" />
              <span className="flex-1">No assignee</span>
              {!owner && <span className="text-text-tertiary">✓</span>}
            </button>
          </li>
          {members.length > 0 && (
            <>
              <li className="px-2 pt-2 pb-1 text-2xs text-text-tertiary uppercase tracking-wider">
                Team members
              </li>
              {members.map((email) => (
                <li key={email}>
                  <button
                    type="button"
                    onClick={() => select(email)}
                    className="w-full flex items-center gap-2 px-2 py-1.5 text-left text-sm hover:bg-bg-hover transition-colors"
                  >
                    <OwnerAvatar email={email} size="xs" />
                    <span className="flex-1 truncate">
                      {user?.email === email ? `${email.split('@')[0]} (me)` : email}
                    </span>
                    {owner === email && <span className="text-text-tertiary shrink-0">✓</span>}
                  </button>
                </li>
              ))}
            </>
          )}
        </ul>
      </Popover>
    </div>
  )
}
