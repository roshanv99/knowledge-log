import { XIcon } from '@phosphor-icons/react'
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import { useEffect, useState } from 'react'
import { Link, Navigate, useNavigate } from 'react-router'

import { useSubmitAttempt, useToday } from '../../api/hooks'
import type { QuizSet } from '../../api/types'
import { Button } from '../../components/Button'
import { ErrorState } from '../../components/ErrorState'
import { marksFromRun } from './format'
import { useAnswerKeys } from './answerKeys'
import { QuestionView } from './QuestionView'
import { clearRun, loadRun, newRun, saveRun, toAnswers, type QuizRun } from './run'

export function PlayPage() {
  const today = useToday()
  if (today.isPending) return <div className="min-h-dvh" aria-busy="true" />
  if (today.isError) {
    return (
      <div className="mx-auto max-w-[680px] px-5 pt-10">
        <ErrorState error={today.error} onRetry={() => today.refetch()} />
      </div>
    )
  }
  const quizSet = today.data.quiz_set
  if (!quizSet) return <Navigate to="/quiz" replace />
  return <Play key={quizSet.id} quizSet={quizSet} />
}

function Play({ quizSet }: { quizSet: QuizSet }) {
  const navigate = useNavigate()
  const reduce = useReducedMotion()
  const submit = useSubmitAttempt(quizSet.id)
  const [run, setRun] = useState<QuizRun>(() => loadRun(quizSet) ?? newRun(quizSet))

  const questions = new Map(quizSet.questions.map((q) => [q.id, q]))
  const total = run.order.length
  const question = questions.get(run.order[run.index])!
  const display = run.optionOrder[question.id]
  const choice = run.choices[question.id]
  const revealed = choice !== undefined
  const isLast = run.index === total - 1

  useEffect(() => saveRun(run), [run])

  function choose(stored: number) {
    if (revealed) return
    setRun((r) => ({ ...r, choices: { ...r.choices, [question.id]: stored } }))
  }

  function next() {
    if (!revealed) return
    if (!isLast) {
      setRun((r) => ({ ...r, index: r.index + 1 }))
      window.scrollTo({ top: 0 })
      return
    }
    submit.mutate(toAnswers(run), {
      onSuccess: (result) => {
        clearRun(quizSet.id)
        navigate('/quiz/result', { replace: true, state: { result } })
      },
    })
  }

  useAnswerKeys(display, choose, next)

  const progress = marksFromRun(run, quizSet)

  return (
    <div className="mx-auto flex min-h-dvh max-w-[680px] flex-col px-5 pt-[max(16px,env(safe-area-inset-top))] pb-[calc(112px+env(safe-area-inset-bottom))] sm:px-8">
      <header className="flex items-center gap-4 py-2">
        <Link
          to="/quiz"
          aria-label="Leave quiz (your answers are kept)"
          className="-ml-2 grid size-11 place-items-center rounded-full text-muted hover:bg-ink-soft hover:text-graphite"
        >
          <XIcon size={22} />
        </Link>
        <ol className="flex flex-1 items-center justify-center gap-1.5" aria-label="Progress">
          {progress.map((mark, i) => (
            <li
              key={i}
              className={`size-3 rounded-full border-[1.5px] ${
                mark === 'right'
                  ? 'border-ink bg-ink'
                  : mark === 'wrong'
                    ? 'border-pen bg-pen'
                    : mark === 'current'
                      ? 'border-graphite'
                      : 'border-ink/35'
              }`}
            />
          ))}
        </ol>
        <p className="w-11 text-right font-display text-[15px] font-semibold tabular-nums text-muted">
          {run.index + 1}/{total}
        </p>
      </header>

      <QuestionView question={question} display={display} choice={choice} onChoose={choose} />

      <AnimatePresence>
        {revealed && (
          <motion.div
            initial={reduce ? false : { y: 80 }}
            animate={{ y: 0 }}
            exit={reduce ? undefined : { y: 80 }}
            transition={{ type: 'spring', stiffness: 420, damping: 36 }}
            className="fixed inset-x-0 bottom-0 z-20 border-t border-rule bg-sheet px-5 pt-3 pb-[max(12px,env(safe-area-inset-bottom))]"
          >
            <div className="mx-auto flex max-w-[680px] flex-col gap-2 sm:px-3">
              {submit.isError && (
                <p role="alert" className="text-[14px] text-pen">
                  Couldn't save your answers. {submit.error.message}
                </p>
              )}
              <Button onClick={next} disabled={submit.isPending} className="w-full">
                {isLast ? (submit.isPending ? 'Scoring…' : 'See results') : 'Next question'}
              </Button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
