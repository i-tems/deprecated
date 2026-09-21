import { useEffect, useRef, useState } from 'react'
import {
  ChevronDown, ChevronRight, Plus, Pencil, Trash2,
  GitPullRequest, ExternalLink, Link2, FileText, Globe,
} from 'lucide-react'
import { Modal } from '@/components/ui/modal'
import { ResourceLink } from '@/components/ResourceLink'
import type { Resource, PrInfo, Artifact, Deployment } from '@/lib/types'
import { prStatus, type PrLiveState } from '@/lib/api'
import type { ResourceEditorState } from '@/hooks/useResourceEditor'

const RES_LIMIT = 5
const ART_LIMIT = 5

interface ResourcesPanelProps {
  resources: Resource[] | undefined
  prs: PrInfo[] | undefined
  artifacts?: Artifact[] | undefined
  deployments?: Deployment[] | undefined
  editor: ResourceEditorState
  defaultOpen?: boolean
}

/** Linear-style: 헤더 plain, 각 항목은 개별 카드, 추가는 modal로 link만. */
export function ResourcesPanel({ resources, prs, artifacts, deployments, editor, defaultOpen = true }: ResourcesPanelProps) {
  const [open, setOpen] = useState(defaultOpen)
  const [showAll, setShowAll] = useState(false)
  const [showAllArt, setShowAllArt] = useState(false)
  const ownRes = resources ?? []
  const prList = prs ?? []
  const artList = artifacts ?? []
  const deployList = deployments ?? []
  const total = ownRes.length + prList.length + artList.length + deployList.length
  const totalHidden = Math.max(0, ownRes.length - RES_LIMIT)
  const artHidden = Math.max(0, artList.length - ART_LIMIT)
  const visibleRes = showAll ? ownRes : ownRes.slice(0, RES_LIMIT)
  const visibleArt = showAllArt ? artList : artList.slice(0, ART_LIMIT)

  return (
    <div className="space-y-2">
      <div className="flex items-center px-1">
        <button
          type="button"
          onClick={() => setOpen(!open)}
          className="flex items-center gap-1 text-sm font-medium text-text-secondary hover:text-text transition-colors"
        >
          {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
          <span>Resources</span>
          {total > 0 && <span className="ml-1 text-xs text-text-tertiary">{total}</span>}
        </button>
        {open && (
          <button
            type="button"
            onClick={editor.startAdding}
            className="ml-auto inline-flex items-center justify-center w-6 h-6 rounded-full border border-border-subtle bg-bg text-text-tertiary hover:text-text hover:border-border transition-colors"
            title="Add link"
            aria-label="Add link"
          >
            <Plus size={12} />
          </button>
        )}
      </div>

      {open && (
        <>
          {/* Editable resources */}
          {visibleRes.map((res, i) => (
            <ResourceCard key={i} res={res} idx={i} editor={editor} />
          ))}

          {/* PR items */}
          {prList.map((pr) => (
            <PrCard key={pr.url} pr={pr} />
          ))}

          {/* Show more (resources) */}
          {totalHidden > 0 && (
            <button
              onClick={() => setShowAll(!showAll)}
              className="text-xs text-accent hover:text-accent/80 px-1"
            >
              {showAll ? 'Show less' : `Show ${totalHidden} more`}
            </button>
          )}

          {/* Deployments (derived — read-only, meta live 배포 URL) */}
          {deployList.length > 0 && (
            <div className="pt-2">
              <div className="px-1 mb-1 flex items-center gap-1 text-xs font-medium text-text-tertiary">
                <Globe size={11} />
                <span>Deployments</span>
                <span className="text-text-tertiary">{deployList.length}</span>
              </div>
              {deployList.map((d) => (
                <DeploymentCard key={`${d.app}/${d.env}`} dep={d} />
              ))}
            </div>
          )}

          {/* Artifacts (derived — read-only, cell repo space 자동 스캔 결과) */}
          {artList.length > 0 && (
            <div className="pt-2">
              <div className="px-1 mb-1 flex items-center gap-1 text-xs font-medium text-text-tertiary">
                <FileText size={11} />
                <span>Artifacts</span>
                <span className="text-text-tertiary">{artList.length}</span>
              </div>
              {visibleArt.map((a) => (
                <ArtifactCard key={a.path} art={a} />
              ))}
              {artHidden > 0 && (
                <button
                  onClick={() => setShowAllArt(!showAllArt)}
                  className="text-xs text-accent hover:text-accent/80 px-1"
                >
                  {showAllArt ? 'Show less' : `Show ${artHidden} more`}
                </button>
              )}
            </div>
          )}

          {/* Empty state */}
          {total === 0 && (
            <p className="px-1 text-xs text-text-tertiary">No resources</p>
          )}
        </>
      )}

      {/* Add link modal */}
      <AddLinkModal open={editor.isAdding} editor={editor} />

      {/* Edit modal — uses same form for editing existing resource */}
      <EditLinkModal editor={editor} />
    </div>
  )
}

function ResourceCard({ res, idx, editor }: { res: Resource; idx: number; editor: ResourceEditorState }) {
  return (
    <div className="rounded-md border border-border-subtle bg-bg group">
      <div className="px-3 py-2.5 flex items-center gap-2 min-w-0">
        <Link2 size={13} className="text-text-tertiary shrink-0" />
        <div className="flex-1 min-w-0">
          <ResourceLink label={res.label} uri={res.uri} />
          {res.description && (
            <p className="text-xs text-text-tertiary mt-0.5 truncate">{res.description}</p>
          )}
        </div>
        <div className="flex items-center gap-0.5 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity">
          <button
            onClick={() => { editor.setEditingResIndex(idx); editor.setEditingRes({ ...res, description: res.description || '' }) }}
            className="p-1 text-text-tertiary hover:text-text rounded hover:bg-bg-hover transition-colors"
            title="Edit"
          ><Pencil size={12} /></button>
          <button
            onClick={() => editor.handleRemoveResource(idx)}
            className="p-1 text-text-tertiary hover:text-error rounded hover:bg-bg-hover transition-colors"
            title="Remove"
          ><Trash2 size={12} /></button>
        </div>
      </div>
    </div>
  )
}

function ArtifactCard({ art }: { art: Artifact }) {
  // path 의 마지막 segment 만 라벨로 (디렉토리는 description 으로 노출)
  const segs = art.path.split('/')
  const name = segs[segs.length - 1] || art.path
  const dir = segs.slice(0, -1).join('/')
  return (
    <a
      href={art.blob_url}
      target="_blank"
      rel="noopener noreferrer"
      className="block rounded-md border border-border-subtle bg-bg hover:border-border transition-colors group"
    >
      <div className="px-3 py-2.5 flex items-center gap-2 min-w-0">
        <FileText size={13} className="text-text-tertiary shrink-0" />
        <div className="flex-1 min-w-0">
          <span className="text-sm text-text truncate block">{name}</span>
          {dir && <p className="text-xs text-text-tertiary mt-0.5 truncate">{dir}</p>}
        </div>
        <ExternalLink size={11} className="text-text-tertiary opacity-0 group-hover:opacity-100 transition-opacity shrink-0" />
      </div>
    </a>
  )
}

function DeploymentCard({ dep }: { dep: Deployment }) {
  const ready = dep.phase === 'Ready'
  return (
    <a
      href={dep.url}
      target="_blank"
      rel="noopener noreferrer"
      className="block rounded-md border border-border-subtle bg-bg hover:border-border transition-colors group"
    >
      <div className="px-3 py-2.5 flex items-center gap-2 min-w-0">
        <Globe size={13} className="text-text-tertiary shrink-0" />
        <div className="flex-1 min-w-0">
          <span className="text-sm text-text truncate block">
            {dep.app} <span className="text-text-tertiary text-xs">{dep.env}</span>
          </span>
          <p className="text-xs text-text-tertiary mt-0.5 truncate">{dep.url.replace(/^https?:\/\//, '')}</p>
        </div>
        {!ready && <span className="text-xs text-text-tertiary shrink-0">{dep.phase}</span>}
        <ExternalLink size={11} className="text-text-tertiary opacity-0 group-hover:opacity-100 transition-opacity shrink-0" />
      </div>
    </a>
  )
}

function PrCard({ pr }: { pr: PrInfo }) {
  // 실제 PR 상태는 GitHub 이 정본 — mount 시 hub `pr.status` 로 derive-on-read.
  // 로딩 중·실패 시 "…" / "Unknown" 으로 회색 표시 (예전 "Failed" 폴백 제거).
  const [state, setState] = useState<PrLiveState | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let cancelled = false
    setState(null)
    setFailed(false)
    prStatus(pr.url)
      .then((r) => { if (!cancelled) setState(r.state) })
      .catch(() => { if (!cancelled) setFailed(true) })
    return () => { cancelled = true }
  }, [pr.url])

  const { stateLabel, stateColor } = (() => {
    if (failed) return { stateLabel: 'Unknown', stateColor: 'text-text-tertiary' }
    if (state === null) return { stateLabel: '…', stateColor: 'text-text-tertiary' }
    if (state === 'merged') return { stateLabel: 'Merged', stateColor: 'text-accent' }
    if (state === 'open') return { stateLabel: 'Open', stateColor: 'text-success' }
    if (state === 'draft') return { stateLabel: 'Draft', stateColor: 'text-text-tertiary' }
    if (state === 'closed') return { stateLabel: 'Closed', stateColor: 'text-text-tertiary' }
    return { stateLabel: 'Unknown', stateColor: 'text-text-tertiary' }
  })()

  return (
    <a
      href={pr.url}
      target="_blank"
      rel="noopener noreferrer"
      className="block rounded-md border border-border-subtle bg-bg hover:border-border transition-colors group"
    >
      <div className="px-3 py-2.5 flex items-center gap-2 min-w-0">
        <GitPullRequest size={14} className="text-text-tertiary shrink-0" />
        <span className="text-sm text-text truncate flex-1">
          {pr.repo} <span className="text-text-tertiary text-xs">#{pr.pr_number}</span>
        </span>
        <span className={`inline-flex items-center gap-1 text-xs ${stateColor} shrink-0`}>
          <GitPullRequest size={12} />
          {stateLabel}
        </span>
        <ExternalLink size={11} className="text-text-tertiary opacity-0 group-hover:opacity-100 transition-opacity shrink-0" />
      </div>
    </a>
  )
}

interface AddLinkModalProps {
  open: boolean
  editor: ResourceEditorState
}

function AddLinkModal({ open, editor }: AddLinkModalProps) {
  const urlRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (open && urlRef.current) {
      urlRef.current.focus()
    }
  }, [open])

  // 모달 열릴 때 type=url로 고정
  useEffect(() => {
    if (open) editor.setNewResType('url')
  }, [open]) // eslint-disable-line react-hooks/exhaustive-deps

  const submit = () => {
    if (!editor.newResUri.trim()) return
    // label이 비면 URL을 그대로 표시 라벨로 사용
    if (!editor.newResLabel.trim()) editor.setNewResLabel(editor.newResUri.trim())
    setTimeout(() => editor.handleAddResource(), 0)
  }

  return (
    <Modal open={open} onClose={editor.cancelAdding} title="Add link">
      <div className="space-y-4">
        <div>
          <label className="block text-xs font-medium text-text-secondary mb-1.5">URL</label>
          <input
            ref={urlRef}
            type="url"
            placeholder="https://…"
            value={editor.newResUri}
            onChange={(e) => editor.setNewResUri(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && (e.metaKey || e.ctrlKey) && submit()}
            className="w-full rounded-md border border-accent bg-bg px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-accent"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-text-secondary mb-1.5">
            Title <span className="text-text-tertiary font-normal">(optional)</span>
          </label>
          <input
            type="text"
            value={editor.newResLabel}
            onChange={(e) => editor.setNewResLabel(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && (e.metaKey || e.ctrlKey) && submit()}
            className="w-full rounded-md border border-border-subtle bg-bg px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-accent focus:border-accent"
          />
        </div>
        <div className="flex justify-end gap-2 pt-1">
          <button
            type="button"
            onClick={editor.cancelAdding}
            className="px-4 py-1.5 rounded-full border border-border-subtle text-sm text-text hover:bg-bg-hover transition-colors"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={submit}
            disabled={!editor.newResUri.trim()}
            className="px-4 py-1.5 rounded-full bg-accent text-white text-sm font-medium hover:bg-accent/90 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            Add link
          </button>
        </div>
      </div>
    </Modal>
  )
}

interface EditLinkModalProps {
  editor: ResourceEditorState
}

function EditLinkModal({ editor }: EditLinkModalProps) {
  const isOpen = editor.editingResIndex !== null
  const urlRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (isOpen && urlRef.current) urlRef.current.focus()
  }, [isOpen])

  const close = () => editor.setEditingResIndex(null)
  const submit = () => {
    if (editor.editingResIndex === null) return
    if (!editor.editingRes.uri.trim()) return
    if (!editor.editingRes.label.trim()) {
      editor.setEditingRes({ ...editor.editingRes, label: editor.editingRes.uri.trim() })
    }
    setTimeout(() => editor.handleEditResource(editor.editingResIndex!), 0)
  }

  return (
    <Modal open={isOpen} onClose={close} title="Edit link">
      <div className="space-y-4">
        <div>
          <label className="block text-xs font-medium text-text-secondary mb-1.5">URL</label>
          <input
            ref={urlRef}
            type="url"
            placeholder="https://…"
            value={editor.editingRes.uri}
            onChange={(e) => editor.setEditingRes({ ...editor.editingRes, uri: e.target.value })}
            onKeyDown={(e) => e.key === 'Enter' && (e.metaKey || e.ctrlKey) && submit()}
            className="w-full rounded-md border border-accent bg-bg px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-accent"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-text-secondary mb-1.5">
            Title <span className="text-text-tertiary font-normal">(optional)</span>
          </label>
          <input
            type="text"
            value={editor.editingRes.label}
            onChange={(e) => editor.setEditingRes({ ...editor.editingRes, label: e.target.value })}
            onKeyDown={(e) => e.key === 'Enter' && (e.metaKey || e.ctrlKey) && submit()}
            className="w-full rounded-md border border-border-subtle bg-bg px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-accent focus:border-accent"
          />
        </div>
        <div className="flex justify-end gap-2 pt-1">
          <button
            type="button"
            onClick={close}
            className="px-4 py-1.5 rounded-full border border-border-subtle text-sm text-text hover:bg-bg-hover transition-colors"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={submit}
            disabled={!editor.editingRes.uri.trim()}
            className="px-4 py-1.5 rounded-full bg-accent text-white text-sm font-medium hover:bg-accent/90 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            Save
          </button>
        </div>
      </div>
    </Modal>
  )
}
