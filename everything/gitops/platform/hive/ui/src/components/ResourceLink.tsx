import { ExternalLink, FolderOpen, FileText } from 'lucide-react'

/**
 * 리소스 URI 렌더링.
 * - http(s): 외부 링크 (새 탭)
 * - 그 외: 링크 없이 텍스트 (파일/디렉토리 아이콘만)
 */
export function ResourceLink({ label, uri }: { label: string; uri: string }) {
  if (uri.startsWith('http')) {
    return (
      <a
        href={uri}
        target="_blank"
        rel="noopener noreferrer"
        className="text-xs font-medium text-accent hover:text-accent-text hover:underline transition-colors flex items-center gap-1 min-w-0"
      >
        <span className="truncate">{label}</span>
        <ExternalLink size={10} className="shrink-0" />
      </a>
    )
  }

  const lastSegment = uri.split('/').pop() || ''
  const isFile = lastSegment.includes('.')
  const Icon = isFile ? FileText : FolderOpen

  return (
    <span className="text-xs font-medium text-text-secondary flex items-center gap-1 min-w-0">
      <span className="truncate">{label}</span>
      <Icon size={10} className="shrink-0" />
    </span>
  )
}
