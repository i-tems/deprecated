// handoff/halt/done comment_payload.options 파싱·실행 helper — FeedBlocks 의
// OptionsRow 와 ActivityFeed 의 단축키 hook 이 공유. react-refresh 가 component 파일에서
// non-component export 를 싫어해 별 파일로 분리.

import { eventAdd, issueUpdate, projectCreate, issueCreate } from '@/lib/api'
import type {
  AnyStatus, CommentSubtype, HandoffOption, HandoffOptionAction,
} from '@/lib/types'

export function parseOptions(raw: unknown): HandoffOption[] {
  if (!Array.isArray(raw)) return []
  const out: HandoffOption[] = []
  for (const item of raw) {
    if (!item || typeof item !== 'object') continue
    const r = item as Record<string, unknown>
    const label = typeof r.label === 'string' ? r.label : null
    const action = r.action as Record<string, unknown> | undefined
    if (!label || !action || typeof action !== 'object') continue
    const t = action.type
    if (t === 'transition' && typeof action.status === 'string') {
      out.push({
        label,
        key: typeof r.key === 'string' ? r.key.toLowerCase() : undefined,
        tone: (r.tone === 'primary' || r.tone === 'danger') ? r.tone : 'default',
        action: {
          type: 'transition',
          status: action.status as AnyStatus,
          comment: typeof action.comment === 'string' ? action.comment : undefined,
        },
      })
    } else if (t === 'reply' && typeof action.text === 'string') {
      out.push({
        label,
        key: typeof r.key === 'string' ? r.key.toLowerCase() : undefined,
        tone: (r.tone === 'primary' || r.tone === 'danger') ? r.tone : 'default',
        action: {
          type: 'reply',
          text: action.text,
          subtype: action.subtype === 'progress' || action.subtype === 'discussion'
            ? action.subtype as CommentSubtype : undefined,
        },
      })
    } else if (t === 'create'
      && (action.entity === 'project' || action.entity === 'issue')
      && action.draft && typeof action.draft === 'object') {
      out.push({
        label,
        key: typeof r.key === 'string' ? r.key.toLowerCase() : undefined,
        tone: (r.tone === 'primary' || r.tone === 'danger') ? r.tone : 'default',
        action: {
          type: 'create',
          entity: action.entity,
          draft: action.draft as Record<string, unknown>,
        },
      })
    }
  }
  return out
}

export async function runHandoffAction(
  action: HandoffOptionAction,
  ctx: { entityType: 'project' | 'issue' | 'initiative'; entityId: string; parentEventId: string },
): Promise<void> {
  if (action.type === 'transition') {
    if (ctx.entityType !== 'issue') {
      throw new Error(`transition option 은 issue 만 지원 (entityType=${ctx.entityType})`)
    }
    await issueUpdate({
      issue_id: ctx.entityId,
      status: action.status,
      ...(action.comment ? { comment: action.comment, comment_subtype: 'transition' } : {}),
    })
  } else if (action.type === 'create') {
    if (action.entity === 'project') {
      await projectCreate(action.draft)
    } else {
      await issueCreate(action.draft)
    }
  } else {
    await eventAdd({
      entity_type: ctx.entityType,
      entity_id: ctx.entityId,
      parent_event_id: ctx.parentEventId,
      text: action.text,
      subtype: action.subtype ?? 'discussion',
    })
  }
}
