import type { InitiativeStatus } from './types'
import { CONTAINER_STATUSES, CONTAINER_STATUS_LABEL } from './status'

// Initiative status 는 이제 Project 과 동일한 container 모델(backlog|active|done|archive).
// 사람 수동 전이만 (자동 전이 없음 — 자식 Project 이 모두 done 되어도 자동 변경 안 함).
// 정본: ~/hive/.claude/specs/model.
export const INITIATIVE_STATUSES: InitiativeStatus[] = CONTAINER_STATUSES
export const INITIATIVE_STATUS_LABEL: Record<InitiativeStatus, string> = CONTAINER_STATUS_LABEL
