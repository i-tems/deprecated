import { useSearchParams } from 'react-router-dom'

export function useUrlState<T extends string>(key: string, defaultValue: T): [T, (value: T) => void] {
  const [searchParams, setSearchParams] = useSearchParams()
  const value = (searchParams.get(key) ?? defaultValue) as T
  const setValue = (newValue: T) => {
    setSearchParams(prev => {
      const next = new URLSearchParams(prev)
      if (newValue === defaultValue) {
        next.delete(key)
      } else {
        next.set(key, newValue)
      }
      return next
    }, { replace: true })
  }
  return [value, setValue]
}
