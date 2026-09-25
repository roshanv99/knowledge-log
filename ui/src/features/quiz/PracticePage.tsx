import { XIcon } from '@phosphor-icons/react'
import { useQuery } from '@tanstack/react-query'
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import { useRef, useState } from 'react'
import { Link } from 'react-router'

import { api } from '../../api/client'
import type { Question } from '../../api/types'
import { Button, ButtonLink } from '../../components/Button'
import { ErrorState } from '../../components/ErrorState'
import { useAnswerKeys } from './answerKeys'
import { QuestionView } from './QuestionView'

// Recently seen questions aren't asked again until the pool runs dry.
const RECENT = 20

function shuffledOptions(question: Question): number[] {
  const order = question.options.map((_, i) => i)
  for (let i = order.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1))
    ;[order[i], order[j]] = [order[j], order[i]]
  }
  return order
}

type Round = { question: Question | null; display: number[]; pool: number }

// Extra practice after today's quiz: one random question at a time from the ticked notes (Quiz
// ticked, pages in range). Nothing is recorded; the tally lasts only as long as the page.
export function PracticePage() {
  const reduce = useReducedMotion()
  const [round, setRound] = useState(0)
  const recent = useRef<number[]>([])
  const practice = useQuery({
    queryKey: ['practice', round],
    queryFn: async (): Promise<Round> => {
      const { question, pool } = await api.practice(recent.current)
      return { question, pool, display: question ? shuffledOptions(question) : [] }
    },
    staleTime: Infinity,
    gcTime: 0,
  })
  const current = practice.data?.question ? practice.data : null
  const question = current?.question ?? null
  // The answer belongs to one question, so a new question starts unanswered.
  const [answer, setAnswer] = useState<{ id: number; stored: number } | null>(null)
  const choice = question && answer?.id === question.id ? answer.stored : undefined
  const [tally, setTally] = useState({ answered: 0, right: 0 })

  function choose(stored: number) {
    if (!question || choice !== undefined) return
    setAnswer({ id: question.id, stored })
    setTally((t) => ({ answered: t.answered + 1, right: t.right + (stored === question.correct_index ? 1 : 0) }))
  }

  function next() {
    if (!question || choice === undefined) return
    recent.current = [question.id, ...recent.current].slice(0, RECENT)
    setRound((r) => r + 1)
    window.scrollTo({ top: 0 })
  }

  useAnswerKeys(current?.display ?? [], choose, next)

  return (
    <div className="mx-auto flex min-h-dvh max-w-[680px] flex-col px-5 pt-[max(16px,env(safe-area-inset-top))] pb-[calc(112px+env(safe-area-inset-bottom))] sm:px-8">
      <header className="flex items-center gap-4 py-2">
        <Link
          to="/quiz"
          aria-label="Stop practising"
          className="-ml-2 grid size-11 place-items-center rounded-full text-muted hover:bg-ink-soft hover:text-graphite"
        >
          <XIcon size={22} />
        </Link>
        <p className="flex-1 text-center font-display text-[17px] font-semibold">Practice</p>
        <p className="min-w-11 text-right text-[14px] text-muted tabular-nums" aria-live="polite">
          {tally.answered > 0 ? `${tally.right}/${tally.answered} right` : ''}
        </p>
      </header>

      {practice.isError ? (
        <div className="pt-10">
          <ErrorState error={practice.error} onRetry={() => practice.refetch()} />
        </div>
      ) : practice.data && !practice.data.question ? (
        <section className="pt-10">
          <h1 className="font-display text-[28px] leading-tight font-semibold">Nothing to practise</h1>
          <p className="mt-3 max-w-[52ch] leading-relaxed text-muted">
            Practice uses questions from the PDFs ticked in Manage notes, with Quiz ticked and pages in range.
          </p>
          <ButtonLink to="/notes" variant="secondary" className="mt-5">
            Manage notes
          </ButtonLink>
        </section>
      ) : current && question ? (
        <>
          <p className="pt-4 text-[13px] text-muted">
            Random questions from your ticked notes ({current.pool} in the pool). Not recorded.
          </p>
          <QuestionView question={question} display={current.display} choice={choice} onChoose={choose} />
        </>
      ) : (
        <div className="pt-10" aria-busy="true" aria-label="Loading a question" />
      )}

      <AnimatePresence>
        {choice !== undefined && (
          <motion.div
            initial={reduce ? false : { y: 80 }}
            animate={{ y: 0 }}
            exit={reduce ? undefined : { y: 80 }}
            transition={{ type: 'spring', stiffness: 420, damping: 36 }}
            className="fixed inset-x-0 bottom-0 z-20 border-t border-rule bg-sheet px-5 pt-3 pb-[max(12px,env(safe-area-inset-bottom))]"
          >
            <div className="mx-auto flex max-w-[680px] gap-3 sm:px-3">
              <ButtonLink to="/quiz" variant="secondary" className="flex-1">
                Done
              </ButtonLink>
              <Button onClick={next} className="flex-[2]">
                Next question
              </Button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
