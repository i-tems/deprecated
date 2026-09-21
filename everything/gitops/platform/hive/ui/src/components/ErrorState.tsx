import { AlertTriangle } from 'lucide-react'
import { Button } from '@/components/ui/button'

export function ErrorState({ error, onRetry }: { error: Error; onRetry?: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-center">
      <AlertTriangle size={20} className="mb-3 text-error" />
      <p className="text-base font-medium text-text-secondary">문제가 발생했습니다</p>
      <p className="mt-1 text-xs text-text-tertiary max-w-sm">{error.message}</p>
      {onRetry && (
        <Button variant="secondary" size="sm" className="mt-4" onClick={onRetry}>
          다시 시도
        </Button>
      )}
    </div>
  )
}
