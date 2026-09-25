import { Navigate, useLocation, useNavigate } from 'react-router'

import { useToday } from '../../api/hooks'
import type { AttemptResult } from '../../api/types'
import { Button, ButtonLink } from '../../components/Button'
import { RedCircle } from '../../components/RedCircle'
import { RichText } from '../../components/RichText'
import { documentName, neededToPass, pageRange } from './format'
import { newRun, saveRun } from './run'

export function ResultPage() {
  const { state } = useLocation() as { state: { result?: AttemptResult } | null }
  const today = useToday()
  const navigate = useNavigate()
  const result = state?.result
  if (!result) return <Navigate to="/quiz" replace />

  const quizSet = today.data?.quiz_set
  const questions = new Map(quizSet?.questions.map((q) => [q.id, q]))
  const missed = result.results.filter((r) => !r.is_correct)
  const needed = neededToPass(result.pass_pct, result.total)

  function tryAgain() {
    if (!quizSet) return
    saveRun(newRun(quizSet))
    navigate('/quiz/play', { replace: true })
  }

  return (
    <div className="mx-auto max-w-[720px] px-5 pt-10 pb-12 sm:px-8 lg:pt-16">
      <section aria-labelledby="result-title">
        <div className="relative inline-flex items-baseline gap-3 px-10 pt-9 pb-7">
          <RedCircle className="inset-0 size-full" />
          <span className="font-display text-[104px] leading-[0.9] font-semibold tabular-nums">{result.correct}</span>
          <span className="font-display text-[28px] font-medium text-muted">of {result.total}</span>
        </div>

        <h1 id="result-title" className="mt-6 font-display text-[36px] leading-[1.05] font-semibold tracking-tight">
          {result.passed ? 'Passed' : 'Not yet'}
        </h1>
        <p className="mt-2 max-w-[52ch] text-[17px] leading-relaxed text-muted">
          {result.passed
            ? `You needed ${needed} of ${result.total}. The next set arrives tomorrow.`
            : `You need ${needed} of ${result.total} to pass. The questions come back in a new order.`}
        </p>

        <div className="mt-7">
          {result.passed ? (
            <ButtonLink to="/quiz" className="w-full sm:w-auto">
              Back to today
            </ButtonLink>
          ) : (
            <Button onClick={tryAgain} disabled={!quizSet} className="w-full sm:w-auto">
              Try again
            </Button>
          )}
        </div>
      </section>

      <section aria-labelledby="review-title" className="mt-14">
        <h2 id="review-title" className="font-display text-[22px] font-semibold">
          {missed.length ? `Questions you missed (${missed.length})` : 'Every answer right'}
        </h2>
        <ol className="mt-4 divide-y divide-rule border-y border-rule">
          {missed.map((r) => {
            const q = questions.get(r.question_id)
            if (!q) return null
            return (
              <li key={r.question_id} className="py-5">
                <p className="text-[16px] leading-snug font-bold">
                  <RichText text={q.stem} />
                </p>
                <dl className="mt-3 grid gap-2 text-[15px] leading-snug">
                  <div className="grid grid-cols-[92px_1fr] gap-3">
                    <dt className="text-muted">You chose</dt>
                    <dd className="text-pen line-through decoration-pen/60">
                      <RichText text={q.options[r.choice]} />
                    </dd>
                  </div>
                  <div className="grid grid-cols-[92px_1fr] gap-3">
                    <dt className="text-muted">Answer</dt>
                    <dd className="font-bold text-ink">
                      <RichText text={q.options[r.correct_index]} />
                    </dd>
                  </div>
                </dl>
                <p className="mt-3 max-w-[65ch] text-[15px] leading-relaxed text-muted">
                  <RichText text={q.explanation} /> ({documentName(q.document)}, {pageRange(q.source_pages)})
                </p>
              </li>
            )
          })}
        </ol>
      </section>
    </div>
  )
}
