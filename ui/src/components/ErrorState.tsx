import { ApiError } from '../api/client'
import { Button } from './Button'

export function ErrorState({ error, onRetry }: { error: Error; onRetry: () => void }) {
  const unreachable = error instanceof ApiError && error.status === 0
  return (
    <section role="alert" className="max-w-[56ch]">
      <h1 className="font-display text-[28px] leading-tight font-semibold">
        {unreachable ? "Can't reach the quiz server" : 'Something went wrong loading this'}
      </h1>
      <p className="mt-3 leading-relaxed text-muted">
        {unreachable ? 'Start the API, then try again:' : error.message}
      </p>
      {unreachable && (
        <pre className="mt-4 overflow-x-auto rounded-xl border border-rule bg-sheet p-4 font-code text-[13px]">
          cd backend && uv run manage.py runserver 8010
        </pre>
      )}
      <Button variant="secondary" className="mt-5" onClick={onRetry}>
        Retry
      </Button>
    </section>
  )
}
