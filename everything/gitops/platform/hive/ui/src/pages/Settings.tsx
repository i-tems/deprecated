import { useCallback, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { Settings as SettingsIcon, GitBranch, UserRound, Camera } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Spinner } from '@/components/ui/spinner'
import { ErrorState } from '@/components/ErrorState'
import { PageHeader } from '@/components/PageHeader'
import { useToast } from '@/components/ui/toast'
import { useTitle } from '@/hooks/useTitle'
import { useDirectory } from '@/contexts/DirectoryContext'
import { userSettingsGet, userSettingsUpdate, type UserSettings } from '@/lib/api'

/**
 * 사용자 설정. 섹션 단위로 확장한다 — 새 설정군은 <SettingsSection> 을 추가하면 된다.
 * 현재 섹션: Profile (닉네임/아바타), Git identity (sandbox 터미널 git author override).
 */

// 아바타는 오브젝트 스토리지 없이 data URI 로 저장하므로, 업로드 이미지를 브라우저에서
// 128px 정사각형으로 cover-crop·리사이즈해 webp data URL 로 만든다(보통 5~15KB).
const AVATAR_PX = 128

function fileToAvatarDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onerror = () => reject(new Error('파일을 읽지 못했습니다.'))
    reader.onload = () => {
      const img = new Image()
      img.onerror = () => reject(new Error('이미지를 해석하지 못했습니다.'))
      img.onload = () => {
        const canvas = document.createElement('canvas')
        canvas.width = AVATAR_PX
        canvas.height = AVATAR_PX
        const ctx = canvas.getContext('2d')
        if (!ctx) return reject(new Error('캔버스를 만들지 못했습니다.'))
        const scale = Math.max(AVATAR_PX / img.width, AVATAR_PX / img.height)
        const w = img.width * scale
        const h = img.height * scale
        ctx.drawImage(img, (AVATAR_PX - w) / 2, (AVATAR_PX - h) / 2, w, h)
        resolve(canvas.toDataURL('image/webp', 0.85))
      }
      img.src = reader.result as string
    }
    reader.readAsDataURL(file)
  })
}

function SettingsSection({
  icon: Icon,
  title,
  description,
  children,
}: {
  icon: typeof GitBranch
  title: string
  description: string
  children: ReactNode
}) {
  return (
    <section className="rounded-lg border border-border-subtle p-4 md:p-5 max-w-2xl">
      <div className="flex items-center gap-2 mb-1">
        <Icon size={15} className="text-text-tertiary shrink-0" />
        <h2 className="text-sm font-semibold">{title}</h2>
      </div>
      <p className="text-xs text-text-tertiary mb-4">{description}</p>
      {children}
    </section>
  )
}

function Field({
  label,
  hint,
  value,
  placeholder,
  onChange,
}: {
  label: string
  hint: string
  value: string
  placeholder: string
  onChange: (v: string) => void
}) {
  return (
    <label className="block">
      <span className="text-xs font-medium text-text-secondary">{label}</span>
      <Input
        className="mt-1"
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
      />
      <span className="mt-1 block text-[11px] text-text-tertiary">{hint}</span>
    </label>
  )
}

export default function Settings() {
  useTitle('Settings')
  const toast = useToast()
  const { refresh: refreshDirectory } = useDirectory()
  const fileInputRef = useRef<HTMLInputElement>(null)

  const [data, setData] = useState<UserSettings | null>(null)
  const [error, setError] = useState<Error | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)

  // 빈 문자열 = override 해제(계정 기본값 사용).
  const [gitName, setGitName] = useState('')
  const [gitEmail, setGitEmail] = useState('')
  const [displayName, setDisplayName] = useState('')
  // null = 변경 안 함(저장 시 보내지 않음), '' = 제거, data URI = 새 이미지.
  const [avatarDraft, setAvatarDraft] = useState<string | null>(null)

  // setState 를 동기로 부르지 않는다(usePolling 패턴) — effect 에서 호출해도
  // react-hooks/set-state-in-effect 를 트리거하지 않게 await 이후에만 set 한다.
  const load = useCallback(async () => {
    try {
      const s = await userSettingsGet()
      setData(s)
      setGitName(s.git_name ?? '')
      setGitEmail(s.git_email ?? '')
      setDisplayName(s.display_name ?? '')
      setAvatarDraft(null)
      setError(null)
    } catch (e) {
      setError(e as Error)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const retry = useCallback(() => {
    setError(null)
    setLoading(true)
    void load()
  }, [load])

  const gitDirty =
    !!data && (gitName !== (data.git_name ?? '') || gitEmail !== (data.git_email ?? ''))
  const profileDirty =
    !!data && (displayName !== (data.display_name ?? '') || avatarDraft !== null)
  const dirty = gitDirty || profileDirty

  const onPickAvatar = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0]
      e.target.value = '' // 같은 파일 다시 선택 가능하게 초기화
      if (!file) return
      if (!file.type.startsWith('image/')) {
        toast.error('이미지 파일을 선택하세요.')
        return
      }
      try {
        setAvatarDraft(await fileToAvatarDataUrl(file))
      } catch (err) {
        toast.error((err as Error).message)
      }
    },
    [toast],
  )

  // 페이지 전체를 한 번에 저장 — 바뀐 필드만 한 호출로 보낸다(섹션별 저장 버튼 제거).
  const save = useCallback(async () => {
    const email = gitEmail.trim()
    if (email && !email.includes('@')) {
      toast.error('유효한 Git 이메일이 필요합니다.')
      return
    }
    const params: {
      git_name?: string
      git_email?: string
      display_name?: string
      avatar?: string
    } = {}
    if (gitDirty) {
      params.git_name = gitName.trim()
      params.git_email = email
    }
    if (profileDirty) {
      params.display_name = displayName.trim()
      if (avatarDraft !== null) params.avatar = avatarDraft // '' = 제거, data URI = 교체
    }
    setSaving(true)
    try {
      const s = await userSettingsUpdate(params)
      setData(s)
      setGitName(s.git_name ?? '')
      setGitEmail(s.git_email ?? '')
      setDisplayName(s.display_name ?? '')
      setAvatarDraft(null)
      if (profileDirty) await refreshDirectory() // 목록·피드의 본인 표시 즉시 갱신
      toast.success(
        gitDirty
          ? '설정을 저장했습니다. Git 설정은 새로 만드는 터미널부터 적용됩니다.'
          : '설정을 저장했습니다.',
      )
    } catch (e) {
      toast.error(`저장 실패: ${(e as Error).message}`)
    } finally {
      setSaving(false)
    }
  }, [gitDirty, profileDirty, gitName, gitEmail, displayName, avatarDraft, refreshDirectory, toast])

  if (loading && !data) return <Spinner />
  if (error && !data) return <ErrorState error={error} onRetry={retry} />

  const d = data!
  // 미리보기: 새로 고른 이미지 > 저장된 아바타 > (없으면 이니셜)
  const previewAvatar = avatarDraft !== null ? avatarDraft || null : d.avatar
  const previewInitial = (displayName.trim()[0] || d.default_display_name[0] || '?').toUpperCase()

  return (
    <div className="space-y-5">
      <PageHeader title="Settings" icon={SettingsIcon} subtitle={d.email} />

      <SettingsSection
        icon={UserRound}
        title="Profile"
        description="hive 전체에서 보이는 표시 이름과 사진. 비워두면 Google 계정 값을 사용합니다. 사진은 128px 로 줄여 저장합니다."
      >
        <div className="space-y-4">
          <div className="flex items-center gap-4">
            {/* 아바타 원 자체가 변경 버튼 — 클릭 시 파일 선택, hover 시 카메라 오버레이 (Slack·Google 등 표준). */}
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              aria-label="프로필 사진 변경"
              title="클릭해서 사진 변경"
              className="group relative h-16 w-16 shrink-0 cursor-pointer overflow-hidden rounded-full border border-border-subtle focus:outline-none focus-visible:ring-2 focus-visible:ring-accent"
            >
              {previewAvatar ? (
                <img src={previewAvatar} alt="" className="h-full w-full object-cover" />
              ) : (
                <span className="flex h-full w-full items-center justify-center text-xl font-medium bg-bg-hover text-text-secondary">
                  {previewInitial}
                </span>
              )}
              <span className="absolute inset-0 flex items-center justify-center bg-black/45 text-white opacity-0 transition-opacity group-hover:opacity-100">
                <Camera size={18} />
              </span>
            </button>
            <input
              ref={fileInputRef}
              type="file"
              accept="image/*"
              className="hidden"
              onChange={(e) => void onPickAvatar(e)}
            />
            <div className="flex flex-col gap-1">
              <span className="text-[11px] text-text-tertiary">
                원을 클릭해 사진을 바꿉니다. JPG·PNG·WebP.
              </span>
              {previewAvatar && (
                <button
                  type="button"
                  onClick={() => setAvatarDraft('')}
                  className="cursor-pointer self-start rounded text-[11px] text-text-tertiary underline-offset-2 hover:text-text hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-accent"
                >
                  사진 제거
                </button>
              )}
            </div>
          </div>

          <Field
            label="표시 이름 (닉네임)"
            hint={`비우면 기본값: ${d.default_display_name}`}
            value={displayName}
            placeholder={d.default_display_name}
            onChange={setDisplayName}
          />
        </div>
      </SettingsSection>

      <SettingsSection
        icon={GitBranch}
        title="Git identity"
        description="Sandbox 터미널에서 만드는 커밋의 author. 비워두면 계정 이메일에서 자동 도출한 기본값을 사용합니다. push 인증은 cell 토큰으로 동작하므로 별도 토큰 입력은 필요 없습니다."
      >
        <div className="space-y-4">
          <Field
            label="Git user.name"
            hint={`비우면 기본값: ${d.default_git_name}`}
            value={gitName}
            placeholder={d.default_git_name}
            onChange={setGitName}
          />
          <Field
            label="Git user.email"
            hint={`비우면 기본값: ${d.default_git_email}`}
            value={gitEmail}
            placeholder={d.default_git_email}
            onChange={setGitEmail}
          />

          <div className="rounded-md bg-bg-hover px-3 py-2 text-[11px] text-text-secondary">
            적용 값 (effective):{' '}
            <span className="font-medium text-text">{d.effective_git_name}</span>{' '}
            &lt;<span className="font-medium text-text">{d.effective_git_email}</span>&gt;
          </div>
        </div>
      </SettingsSection>

      {/* 페이지 단일 저장 버튼 — 항상 표시하되 변경 없으면 비활성("버튼 없음=자동저장" 오해 방지). */}
      <div className="sticky bottom-0 z-10 flex max-w-2xl justify-end border-t border-border-subtle bg-bg/90 py-3 backdrop-blur">
        <Button variant="primary" onClick={() => void save()} disabled={saving || !dirty}>
          {saving ? '저장 중…' : '저장'}
        </Button>
      </div>
    </div>
  )
}
