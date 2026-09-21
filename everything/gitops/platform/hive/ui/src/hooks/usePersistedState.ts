import { useState, useEffect } from 'react'

// storage='session' 은 탭/창 단위(sessionStorage) — 새로고침은 살아남지만 새 창은
// 빈 상태로 시작한다. 기본 'local'(localStorage)은 모든 탭/창이 공유한다.
type StorageKind = 'local' | 'session'

export function usePersistedState<T>(
  key: string,
  defaultValue: T,
  storage: StorageKind = 'local',
): [T, React.Dispatch<React.SetStateAction<T>>] {
  const store = () => (storage === 'session' ? window.sessionStorage : window.localStorage)

  const [value, setValue] = useState<T>(() => {
    try {
      const saved = store().getItem(key)
      return saved !== null ? JSON.parse(saved) : defaultValue
    } catch {
      return defaultValue
    }
  })

  useEffect(() => {
    store().setItem(key, JSON.stringify(value))
  }, [key, value, storage])

  return [value, setValue]
}
