// triage snooze — 항목을 시한부로 큐에서 숨기는 헬퍼. 데이터 표현은
// metadata.snooze_until (ISO 시각). 만료 판정은 read 시점(client-side) —
// Triage 폴링 사이클에서 자동 재노출되므로 server cron 불필요.
//
// hold 와 직교: hold=worker 픽업 차단 (status 무관, 무기한),
// snooze=Triage 노출 숨김 (status 무관, 시한부).

const KEY = 'snooze_until'

export function getSnoozeUntil(meta?: Record<string, unknown> | null): Date | null {
  const raw = meta?.[KEY]
  if (typeof raw !== 'string' || !raw) return null
  const d = new Date(raw)
  return Number.isNaN(d.getTime()) ? null : d
}

export function isSnoozeActive(
  meta?: Record<string, unknown> | null,
  now: number = Date.now(),
): boolean {
  const until = getSnoozeUntil(meta)
  return until !== null && until.getTime() > now
}

/** Picker 가 metadata patch 로 보내는 페이로드. null=해제. */
export function snoozeMetadataPatch(until: Date | null): Record<string, unknown> {
  return { [KEY]: until ? until.toISOString() : null }
}

/** SnoozePicker 가 active 판정에 사용. Date.now() 호출을 컴포넌트 render 밖으로 격리. */
export function isFutureDate(d: Date | null, now: number = Date.now()): boolean {
  return d !== null && d.getTime() > now
}

/** 현재 시점 기준 d 까지 남은 시간을 한국어로. 음수면 '만료됨'. */
export function formatRemaining(d: Date, now: number = Date.now()): string {
  const ms = d.getTime() - now
  if (ms <= 0) return '만료됨'
  const mins = Math.round(ms / 60000)
  if (mins < 60) return `${mins}분 후`
  const hours = Math.round(mins / 60)
  if (hours < 24) return `${hours}시간 후`
  const days = Math.round(hours / 24)
  return `${days}일 후`
}

/** 현재 시점에서 addMs 후의 Date. SnoozePicker preset 핸들러에서 사용. */
export function dateAfter(addMs: number): Date {
  return new Date(Date.now() + addMs)
}
