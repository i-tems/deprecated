// user-level (cell-agnostic) 경로 — aggregate 응답을 보여주는 페이지들.
// CellGate (cell 미선택 게이트), CellQuerySync (?cell 자동주입), CellContext
// (selectCell 의 경로 결정) 세 곳이 모두 이 set 을 참조한다.
export const USER_LEVEL_PATHS = new Set(['/workspace', '/inbox', '/deck'])

export function isUserLevelPath(pathname: string): boolean {
  return USER_LEVEL_PATHS.has(pathname)
}
