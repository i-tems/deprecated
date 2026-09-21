import { useAuth } from '@/contexts/AuthContext'
import { useDirectory } from '@/contexts/DirectoryContext'

const COLORS = [
  'bg-indigo-100 text-indigo-700 dark:bg-indigo-900 dark:text-indigo-300',
  'bg-emerald-100 text-emerald-700 dark:bg-emerald-900 dark:text-emerald-300',
  'bg-amber-100 text-amber-700 dark:bg-amber-900 dark:text-amber-300',
  'bg-rose-100 text-rose-700 dark:bg-rose-900 dark:text-rose-300',
  'bg-cyan-100 text-cyan-700 dark:bg-cyan-900 dark:text-cyan-300',
  'bg-violet-100 text-violet-700 dark:bg-violet-900 dark:text-violet-300',
]

function hashColor(str: string) {
  let hash = 0
  for (let i = 0; i < str.length; i++) hash = str.charCodeAt(i) + ((hash << 5) - hash)
  return COLORS[Math.abs(hash) % COLORS.length]
}

function getInitial(label: string) {
  return (label.trim()[0] || '?').toUpperCase()
}

export function OwnerAvatar({
  email,
  size = 'sm',
  showName = false,
  inherited = false,
}: {
  email: string
  size?: 'xs' | 'sm'
  showName?: boolean
  inherited?: boolean
}) {
  const { user } = useAuth()
  const { lookup } = useDirectory()
  const isMe = user?.email === email
  const dim = size === 'xs' ? 'h-4 w-4 text-[8px]' : 'h-5 w-5 text-2xs'

  // 디렉토리 override(저장 시 갱신) 우선 → 본인 auth 값 폴백 → 이니셜. 디렉토리를 앞에
  // 두면 저장 직후 새로고침으로 본인 표시도 즉시 반영된다.
  const entry = lookup(email)
  const avatar = entry?.avatar || (isMe ? user?.picture : undefined) || undefined
  const displayName = entry?.display_name || (isMe ? user?.name : undefined) || email.split('@')[0]

  return (
    <span className="inline-flex items-center gap-1 shrink-0" title={email}>
      {avatar ? (
        <img src={avatar} alt="" className={`${dim} rounded-full object-cover`} referrerPolicy="no-referrer" />
      ) : (
        <span className={`${dim} rounded-full flex items-center justify-center font-medium ${hashColor(email)}`}>
          {getInitial(displayName)}
        </span>
      )}
      {showName && (
        <span className="text-xs text-text-tertiary truncate max-w-[120px]">
          {isMe ? 'Me' : displayName}
          {inherited && <span className="opacity-50 ml-0.5">(inherited)</span>}
        </span>
      )}
    </span>
  )
}
