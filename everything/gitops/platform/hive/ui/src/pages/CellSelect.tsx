import { useState } from 'react'
import { Shield, Check, ArrowRight, RefreshCw } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '@/contexts/AuthContext'
import { useCell } from '@/contexts/CellContext'
import { cellUpdate, type Cell } from '@/lib/api'

function parseEmails(input: string) {
  return Array.from(
    new Set(
      input
        .split(/[\s,]+/)
        .map((value) => value.trim().toLowerCase())
        .filter(Boolean),
    ),
  )
}

/** 첫 글자 + 단색 배경의 워크스페이스 칩. Linear 워크스페이스 아바타 패턴. */
function CellAvatar({ name, size = 36 }: { name: string; size?: number }) {
  const initial = (name[0] ?? '?').toUpperCase()
  return (
    <div
      className="rounded-md bg-accent-muted flex items-center justify-center font-medium text-accent-text shrink-0"
      style={{ width: size, height: size, fontSize: size * 0.42 }}
    >
      {initial}
    </div>
  )
}

export default function CellSelect() {
  const navigate = useNavigate()
  const { user } = useAuth()
  const { cells, currentCell, selectCell, refreshCells } = useCell()
  const [editingCellId, setEditingCellId] = useState<string | null>(null)
  const [editingInput, setEditingInput] = useState('')
  const [savingCellId, setSavingCellId] = useState<string | null>(null)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState('')

  const isAdmin = !!user?.is_admin

  async function handleRefresh() {
    setRefreshing(true)
    try {
      await refreshCells()
    } finally {
      setRefreshing(false)
    }
  }

  function handleSelect(cellId: string) {
    selectCell(cellId)
    navigate({ pathname: '/projects', search: `?cell=${encodeURIComponent(cellId)}` })
  }

  function startAccessEdit(cell: Cell) {
    setEditingCellId(cell.cell_id)
    setEditingInput(cell.allowed_emails.join(', '))
    setError('')
  }

  async function handleAccessSave(cellId: string) {
    setSavingCellId(cellId)
    setError('')
    try {
      await cellUpdate({ cell_id: cellId, allowed_emails: parseEmails(editingInput) })
      await refreshCells()
      setEditingCellId(null)
      setEditingInput('')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to save members.')
    } finally {
      setSavingCellId(null)
    }
  }

  return (
    <div className="max-w-3xl mx-auto px-4 py-8 md:px-6 md:py-12 space-y-8">
      {/* Header */}
      <div className="flex items-end justify-between gap-4">
        <div className="space-y-1">
          <h1 className="text-2xl font-semibold tracking-tight leading-tight">Cells</h1>
          <p className="text-sm text-text-secondary">Switch between cells or manage access.</p>
        </div>
        <button
          type="button"
          onClick={handleRefresh}
          disabled={refreshing}
          className="inline-flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1.5 text-xs text-text-secondary hover:bg-bg-hover hover:text-text disabled:opacity-50 transition-colors"
        >
          <RefreshCw size={13} className={refreshing ? 'animate-spin' : ''} />
          Refresh
        </button>
      </div>

      {/* Cells list */}
      {cells.length === 0 ? (
        <div className="rounded-lg border border-border bg-card shadow-card p-10 text-center text-sm text-text-tertiary">
          No active cells available.
        </div>
      ) : (
        <div className="rounded-lg border border-border bg-card shadow-card divide-y divide-border-subtle overflow-hidden">
          {cells.map((cell) => {
            const isActive = currentCell?.cell_id === cell.cell_id
            const isEditing = editingCellId === cell.cell_id
            return (
              <div key={cell.cell_id}>
                <div className="flex items-center gap-3 px-4 py-3 hover:bg-bg-hover/40 transition-colors group">
                  <CellAvatar name={cell.name} />
                  <button
                    type="button"
                    onClick={() => handleSelect(cell.cell_id)}
                    className="flex-1 min-w-0 text-left"
                  >
                    <div className="flex items-center gap-2">
                      <span className="text-[14px] font-medium text-text truncate">{cell.name}</span>
                      {isActive && <Check size={14} className="text-accent shrink-0" />}
                    </div>
                    {cell.description && (
                      <div className="text-xs text-text-secondary truncate">{cell.description}</div>
                    )}
                    <div className="text-xs font-mono text-text-tertiary truncate mt-0.5">{cell.cell_id}</div>
                  </button>
                  <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                    {isAdmin && (
                      <button
                        type="button"
                        onClick={() => (isEditing ? setEditingCellId(null) : startAccessEdit(cell))}
                        className="inline-flex items-center gap-1 px-2 py-1 text-xs text-text-tertiary hover:text-text rounded-md hover:bg-bg-hover transition-colors"
                        title="Manage access"
                      >
                        <Shield size={13} />
                        Access
                      </button>
                    )}
                    {!isActive && (
                      <button
                        type="button"
                        onClick={() => handleSelect(cell.cell_id)}
                        className="inline-flex items-center gap-1 px-2.5 py-1 text-xs text-accent hover:bg-bg-hover rounded-md transition-colors"
                      >
                        Open
                        <ArrowRight size={12} />
                      </button>
                    )}
                  </div>
                </div>

                {/* Inline access editor */}
                {isEditing && isAdmin && (
                  <div className="px-4 pb-3 pt-1 bg-bg-elevated/40 border-t border-border-subtle space-y-2">
                    <div className="flex items-center gap-1.5 text-xs font-medium text-text-tertiary uppercase tracking-wider pt-2">
                      <Shield size={12} />
                      Members
                    </div>
                    <input
                      type="text"
                      value={editingInput}
                      onChange={(e) => setEditingInput(e.target.value)}
                      placeholder="email1@example.com, email2@example.com"
                      className="w-full rounded-md border border-border bg-card px-3 py-2 text-sm text-text placeholder:text-text-quaternary focus:outline-none focus:border-accent transition-colors"
                    />
                    <div className="flex items-center justify-end gap-1.5">
                      <button
                        type="button"
                        onClick={() => { setEditingCellId(null); setEditingInput('') }}
                        className="px-2.5 py-1 text-xs text-text-tertiary hover:text-text rounded-md hover:bg-bg-hover transition-colors"
                      >
                        Cancel
                      </button>
                      <button
                        type="button"
                        onClick={() => handleAccessSave(cell.cell_id)}
                        disabled={savingCellId === cell.cell_id}
                        className="px-3 py-1 text-xs font-medium bg-accent text-white rounded-md hover:bg-accent/90 disabled:opacity-50 transition-colors"
                      >
                        {savingCellId === cell.cell_id ? 'Saving…' : 'Save'}
                      </button>
                    </div>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}

      {/* Cell 생성은 hub/scripts/create-cell.sh CLI 전용 (PAT/Secret 동기화 필요). */}
      {isAdmin && (
        <p className="text-xs text-text-tertiary text-center">
          Create new cells with <code className="font-mono text-xs">hub/scripts/create-cell.sh</code>.
        </p>
      )}

      {error && <p className="text-xs text-error">{error}</p>}
    </div>
  )
}
