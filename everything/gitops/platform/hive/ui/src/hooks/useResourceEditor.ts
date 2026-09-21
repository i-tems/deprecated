import { useState } from 'react'
import type { Resource, ResourceType } from '@/lib/types'

interface UseResourceEditorOptions {
  getResources: () => Resource[]
  updateResources: (resources: Resource[]) => Promise<void>
  onSuccess?: () => void
  onError?: (message: string) => void
}

export interface ResourceEditorState {
  newResLabel: string
  setNewResLabel: (v: string) => void
  newResUri: string
  setNewResUri: (v: string) => void
  newResType: ResourceType
  setNewResType: (v: ResourceType) => void
  newResDesc: string
  setNewResDesc: (v: string) => void
  editingResIndex: number | null
  setEditingResIndex: (v: number | null) => void
  editingRes: Resource
  setEditingRes: (v: Resource) => void
  isAdding: boolean
  startAdding: () => void
  cancelAdding: () => void
  handleAddResource: () => Promise<void>
  handleEditResource: (idx: number) => Promise<void>
  handleRemoveResource: (idx: number) => Promise<void>
}

export function useResourceEditor({
  getResources,
  updateResources,
  onSuccess,
  onError,
}: UseResourceEditorOptions): ResourceEditorState {
  const [newResLabel, setNewResLabel] = useState('')
  const [newResUri, setNewResUri] = useState('')
  const [newResType, setNewResType] = useState<ResourceType>('url')
  const [newResDesc, setNewResDesc] = useState('')
  const [editingResIndex, setEditingResIndex] = useState<number | null>(null)
  const [editingRes, setEditingRes] = useState<Resource>({ label: '', uri: '', type: 'url', description: '' })
  const [isAdding, setIsAdding] = useState(false)

  const startAdding = () => setIsAdding(true)
  const cancelAdding = () => {
    setIsAdding(false)
    setNewResLabel(''); setNewResUri(''); setNewResType('url'); setNewResDesc('')
  }

  const handleAddResource = async () => {
    if (!newResLabel.trim() || !newResUri.trim()) return
    const res: Resource = {
      label: newResLabel.trim(),
      uri: newResUri.trim(),
      type: newResType,
      description: newResDesc.trim() || null,
    }
    const updated = [...(getResources() || []), res]
    try {
      await updateResources(updated)
      setNewResLabel(''); setNewResUri(''); setNewResType('url'); setNewResDesc('')
      setIsAdding(false)
      onSuccess?.()
    } catch (e) {
      onError?.(`리소스 추가 실패: ${(e as Error).message}`)
    }
  }

  const handleEditResource = async (idx: number) => {
    if (!editingRes.label.trim() || !editingRes.uri.trim()) return
    const updated = (getResources() || []).map((r: Resource, i: number) =>
      i === idx
        ? { ...editingRes, label: editingRes.label.trim(), uri: editingRes.uri.trim(), description: editingRes.description?.trim() || null }
        : r,
    )
    try {
      await updateResources(updated)
      setEditingResIndex(null)
      onSuccess?.()
    } catch (e) {
      onError?.(`리소스 수정 실패: ${(e as Error).message}`)
    }
  }

  const handleRemoveResource = async (idx: number) => {
    const updated = (getResources() || []).filter((_: Resource, i: number) => i !== idx)
    try {
      await updateResources(updated)
      onSuccess?.()
    } catch (e) {
      onError?.(`리소스 삭제 실패: ${(e as Error).message}`)
    }
  }

  return {
    newResLabel, setNewResLabel,
    newResUri, setNewResUri,
    newResType, setNewResType,
    newResDesc, setNewResDesc,
    editingResIndex, setEditingResIndex,
    editingRes, setEditingRes,
    isAdding, startAdding, cancelAdding,
    handleAddResource,
    handleEditResource,
    handleRemoveResource,
  }
}
