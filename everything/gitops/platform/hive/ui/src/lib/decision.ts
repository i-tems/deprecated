// description 사양에서 Outcome 헤드라인을 추출하는 helper — 상세 페이지의 Outcome pin 이 쓴다.
// 클라이언트측 파싱은 outcome 키 도입 전 검증용 임시 수단.

// description 사양의 `## Outcome` 섹션 본문만 추출 (다음 헤딩 전까지). 사양 라벨은 영어
// 'Outcome' (entity_slots.md 게이트 검증 항목). 못 찾으면 null — 호출부가 description 을
// 그대로 펼쳐 보인다(하위호환).
export function extractOutcome(description?: string | null): string | null {
  if (!description) return null
  const m = description.match(/(?:^|\n)#{1,6}[ \t]+Outcome\b[^\n]*\n([\s\S]*?)(?=\n#{1,6}[ \t]|$)/i)
  if (!m) return null
  const body = m[1].trim()
  return body || null
}
