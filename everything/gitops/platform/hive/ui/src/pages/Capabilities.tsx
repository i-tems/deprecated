import { useCallback, useState } from 'react'
import { Blocks, Search } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { Empty } from '@/components/ui/empty'
import { PageHeader } from '@/components/PageHeader'
import { IconButton } from '@/components/IconButton'
import { usePollingGate } from '@/hooks/usePollingGate'
import { useTitle } from '@/hooks/useTitle'
import { capabilityList, healthCheck } from '@/lib/api'

interface DynamicCap {
  id: string
  path: string
  description: string | null
}

export default function Capabilities() {
  useTitle('Capabilities')
  const [search, setSearch] = useState('')
  const [showSearch, setShowSearch] = useState(false)

  const fetcher = useCallback(async () => {
    const [capabilities, health] = await Promise.all([capabilityList(), healthCheck()])
    return { capabilities, health }
  }, [])
  const { data, lastUpdated, gate } = usePollingGate(fetcher, 10000)

  if (gate) return gate
  const { capabilities, health } = data!

  const filtered = capabilities.filter(
    (c: DynamicCap) => !search || c.id.toLowerCase().includes(search.toLowerCase()),
  )

  // Group by domain (e.g. signal, action, project, issue)
  const grouped = filtered.reduce<Record<string, DynamicCap[]>>((acc, c: DynamicCap) => {
    const domain = c.id.split('.')[0]
    ;(acc[domain] ??= []).push(c)
    return acc
  }, {})

  const domains = Object.keys(grouped).sort()

  return (
    <div className="space-y-3">
      <PageHeader
        title="Capabilities"
        icon={Blocks}
        iconClass="text-text-tertiary"
        lastUpdated={lastUpdated}
        actions={
          <>
            <span className="text-xs text-text-tertiary tabular-nums">
              {health.service} <span className="text-text-quaternary">v{health.version}</span>
            </span>
            <span className={`inline-block w-1.5 h-1.5 rounded-full ${health.status === 'ok' ? 'bg-success' : 'bg-warning'} animate-pulse`} />
            <IconButton active={showSearch} onClick={() => setShowSearch((v) => !v)} icon={Search} title="검색" />
          </>
        }
      />

      {showSearch && (
        <div className="px-1">
          <Input
            placeholder="Search capabilities..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            autoFocus
            className="w-full"
          />
        </div>
      )}

      {domains.length === 0 ? (
        <Empty icon={<Blocks size={20} />} title="매칭되는 capability 없음" />
      ) : (
        <div className="space-y-4">
          {domains.map((domain) => (
            <div key={domain}>
              <div className="flex items-center gap-1.5 pl-1 pr-1 py-1 mb-0.5">
                <span className="text-xs font-medium text-text-tertiary uppercase tracking-wider">{domain}</span>
                <span className="text-xs text-text-quaternary tabular-nums">{grouped[domain].length}</span>
              </div>
              <div>
                {grouped[domain].map((c) => (
                  <div
                    key={c.id}
                    className="px-2 py-1.5 rounded-md hover:bg-bg-hover transition-colors"
                  >
                    <div className="flex items-baseline gap-2 min-w-0">
                      <span className="text-sm font-mono text-text truncate min-w-0">{c.id}</span>
                      <code className="ml-auto text-2xs font-mono text-text-quaternary shrink-0 truncate max-w-[40%]" title={c.path}>{c.path}</code>
                    </div>
                    {c.description && (
                      <p className="text-mini text-text-tertiary mt-0.5 leading-snug whitespace-pre-wrap break-words">
                        {c.description}
                      </p>
                    )}
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
