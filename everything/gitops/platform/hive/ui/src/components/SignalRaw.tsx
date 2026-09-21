import { ChevronRight } from 'lucide-react'
import type { SignalRaw as SignalRawType } from '@/lib/types'


/**
 * signal-types.schema 의 detail.raw — 구조화 evidence/provenance.
 * SignalCard 의 raw 섹션. (Signal 전용 detail 페이지는 폐기 — list 의
 * SignalCard 가 모든 정보 표시.)
 * - target: 한 줄 (font-mono)
 * - evidence.sources: source · ref 외부 링크
 * - metadata: collapsible JSON pretty
 * - 그 외 raw key: collapsible 'more'
 */
export function SignalRaw({ raw }: { raw: SignalRawType }) {
  const { target, evidence, metadata, ...rest } = raw
  const sources = evidence?.sources ?? []
  const extras = Object.entries(rest).filter(
    ([k]) => !['target', 'evidence', 'metadata'].includes(k),
  )
  return (
    <div className="border-t border-border-subtle/60 pt-2 space-y-1.5 text-xs">
      {target && (
        <div className="flex gap-2">
          <span className="w-16 shrink-0 text-text-tertiary">target</span>
          <span className="text-text-secondary break-all font-mono">{target}</span>
        </div>
      )}
      {sources.length > 0 && (
        <div className="flex gap-2">
          <span className="w-16 shrink-0 text-text-tertiary">sources</span>
          <div className="flex flex-col gap-0.5 min-w-0">
            {sources.map((s, i) => (
              <div key={i} className="flex items-center gap-1.5 min-w-0">
                {s.source && <span className="text-text-tertiary">{s.source}</span>}
                {s.ref && (
                  <a
                    href={s.ref}
                    target="_blank"
                    rel="noreferrer"
                    onClick={(e) => e.stopPropagation()}
                    className="text-accent hover:underline truncate min-w-0"
                  >
                    {s.ref}
                  </a>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
      {metadata && Object.keys(metadata).length > 0 && (
        <details className="group">
          <summary className="text-text-tertiary cursor-pointer hover:text-text-secondary inline-flex items-center gap-1 select-none">
            <ChevronRight size={10} className="group-open:rotate-90 transition-transform" />
            metadata · {Object.keys(metadata).length}
          </summary>
          <pre className="mt-1 p-2 bg-bg-secondary rounded text-text-secondary overflow-x-auto font-mono text-[11px] leading-snug">
            {JSON.stringify(metadata, null, 2)}
          </pre>
        </details>
      )}
      {extras.length > 0 && (
        <details className="group">
          <summary className="text-text-tertiary cursor-pointer hover:text-text-secondary inline-flex items-center gap-1 select-none">
            <ChevronRight size={10} className="group-open:rotate-90 transition-transform" />
            more · {extras.length}
          </summary>
          <pre className="mt-1 p-2 bg-bg-secondary rounded text-text-secondary overflow-x-auto font-mono text-[11px] leading-snug">
            {JSON.stringify(Object.fromEntries(extras), null, 2)}
          </pre>
        </details>
      )}
    </div>
  )
}
