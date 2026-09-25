import { CheckIcon, XIcon } from '@phosphor-icons/react'
import { useNavigate } from 'react-router'

import { useToday } from '../../api/hooks'
import type { QuizSet, Today } from '../../api/types'
import { Button, ButtonLink } from '../../components/Button'
import { ErrorState } from '../../components/ErrorState'
import { ActivityTracker } from './ActivityTracker'
import { AnswerSheet } from './AnswerSheet'
import {
  documentName,
  longDate,
  marksFromAttempt,
  marksFromRun,
  neededToPass,
  pageRange,
  topicsOf,
} from './format'
import { answered, clearRun, loadRun, newRun, saveRun } from './run'

export function TodayPage() {
  const today = useToday()

  return (
    <div className="mx-auto max-w-[1040px] px-5 pt-8 pb-10 sm:px-8 lg:px-12 lg:pt-14">
      <ActivityTracker />
      {today.isPending ? (
        <TodaySkeleton />
      ) : today.isError ? (
        <ErrorState error={today.error} onRetry={() => today.refetch()} />
      ) : today.data.quiz_set ? (
        <TodayQuiz quizSet={today.data.quiz_set} passPct={today.data.pass_pct} />
      ) : (
        <NoQuiz reason={today.data.empty_reason} />
      )}
    </div>
  )
}

function TodayQuiz({ quizSet, passPct }: { quizSet: QuizSet; passPct: number }) {
  const navigate = useNavigate()
  const total = quizSet.questions.length
  const needed = neededToPass(passPct, total)
  const run = loadRun(quizSet)
  const lastAttempt = quizSet.attempts.at(-1)
  const isToday = quizSet.available_on === new Date().toLocaleDateString('en-CA')

  const marks = run
    ? marksFromRun(run, quizSet)
    : lastAttempt
      ? marksFromAttempt(lastAttempt, quizSet)
      : Array.from({ length: total }, () => 'empty' as const)

  function start(fresh: boolean) {
    if (fresh) {
      clearRun(quizSet.id)
      saveRun(newRun(quizSet))
    }
    navigate('/quiz/play')
  }

  let status: string | null
  let action: { label: string; fresh: boolean } | null
  if (run) {
    status = `${answered(run)} of ${total} answered so far.`
    action = { label: 'Resume quiz', fresh: false }
  } else if (quizSet.passed) {
    status = "Passed. That's today done. Want more? Practice with random questions from your notes."
    action = null
  } else if (lastAttempt) {
    status = `Last try: ${lastAttempt.correct} of ${total}. You need ${needed} to pass.`
    action = { label: 'Try again', fresh: true }
  } else {
    status = null
    action = { label: 'Start quiz', fresh: true }
  }

  return (
    <div className="grid gap-10 lg:grid-cols-[minmax(0,1fr)_300px] lg:gap-14">
      <section aria-labelledby="today-title">
        <p className="text-[15px] text-muted">{longDate(quizSet.available_on)}</p>
        <h1 id="today-title" className="mt-1 font-display text-[36px] leading-[1.05] font-semibold tracking-tight">
          {isToday ? "Today's quiz" : 'Unfinished quiz'}
        </h1>
        {!isToday && <p className="mt-2 max-w-[52ch] text-muted">This set carries over until you pass it.</p>}

        <div className="mt-7 rounded-[20px] border border-rule bg-sheet p-5 sm:p-7">
          <div className="flex items-baseline justify-between gap-4 border-b border-rule pb-4">
            <p className="font-display text-[17px] font-semibold">{total} questions</p>
            <p className="text-[15px] text-muted">
              Pass at <span className="font-display text-[17px] font-semibold text-graphite">{needed} of {total}</span>
            </p>
          </div>
          <div className="pt-5">
            <AnswerSheet marks={marks} />
          </div>
          {status && (
            <p className="mt-6 text-[15px] leading-relaxed" aria-live="polite">
              {status}
            </p>
          )}
          {action && (
            <Button className="mt-5 w-full sm:w-auto" onClick={() => start(action.fresh)}>
              {action.label}
            </Button>
          )}
          {quizSet.passed && !run && (
            <ButtonLink to="/quiz/practice" className="mt-5 w-full sm:w-auto">
              Practice more
            </ButtonLink>
          )}
        </div>
      </section>

      <div className="flex flex-col gap-10 lg:pt-[84px]">
        {quizSet.attempts.length > 0 && (
          <section aria-labelledby="attempts-title">
            <h2 id="attempts-title" className="font-display text-[20px] font-semibold">
              Attempts
            </h2>
            <ol className="mt-3 divide-y divide-rule border-y border-rule">
              {quizSet.attempts.map((attempt, i) => (
                <li key={attempt.id} className="flex items-center justify-between py-3 text-[15px]">
                  <span>Attempt {i + 1}</span>
                  <span className={`flex items-center gap-1.5 font-display text-[17px] font-semibold tabular-nums ${attempt.passed ? 'text-ink' : 'text-pen'}`}>
                    {attempt.passed ? <CheckIcon weight="bold" /> : <XIcon weight="bold" />}
                    {attempt.correct} of {attempt.total}
                  </span>
                </li>
              ))}
            </ol>
          </section>
        )}

        <section aria-labelledby="topics-title">
          <h2 id="topics-title" className="font-display text-[20px] font-semibold">
            In this set
          </h2>
          <ul className="mt-3 divide-y divide-rule border-y border-rule">
            {topicsOf(quizSet.questions).map((topic) => (
              <li key={topic.title} className="py-3">
                <p className="text-[15px] leading-snug">{topic.title}</p>
                <p className="mt-0.5 text-[13px] text-muted">
                  {documentName(topic.document)}, {pageRange(topic.pages)}
                </p>
              </li>
            ))}
          </ul>
        </section>
      </div>
    </div>
  )
}

const emptyCopy: Record<NonNullable<Today['empty_reason']>, { title: string; body: string; notes: boolean }> = {
  no_questions: {
    title: 'No questions yet',
    body: 'Questions appear once the pipeline has read some of your notes and they have been imported:',
    notes: false,
  },
  nothing_in_scope: {
    title: 'Nothing selected to quiz on',
    body: 'None of the PDFs and pages you picked have questions yet. Choose different notes, or widen the page range.',
    notes: true,
  },
  all_used: {
    title: "You've used every question",
    body: 'Every question from your selected pages has been in a quiz. Widen the page range, or generate more questions:',
    notes: true,
  },
}

function NoQuiz({ reason }: { reason: Today['empty_reason'] }) {
  const copy = emptyCopy[reason ?? 'no_questions']
  return (
    <section className="max-w-[56ch]">
      <h1 className="font-display text-[36px] leading-[1.05] font-semibold tracking-tight">{copy.title}</h1>
      <p className="mt-3 leading-relaxed text-muted">{copy.body}</p>
      {copy.notes && (
        <ButtonLink to="/notes" className="mt-5">
          Manage notes
        </ButtonLink>
      )}
      {reason !== 'nothing_in_scope' && (
        <pre className="mt-5 overflow-x-auto rounded-xl border border-rule bg-sheet p-4 font-code text-[13px]">
          {'cd pipeline && uv run kl mcq next\ncd backend && uv run manage.py import_pipeline'}
        </pre>
      )}
    </section>
  )
}

function TodaySkeleton() {
  return (
    <div aria-busy="true" aria-label="Loading today's quiz" className="animate-pulse motion-reduce:animate-none">
      <div className="h-4 w-40 rounded bg-rule" />
      <div className="mt-3 h-9 w-56 rounded bg-rule" />
      <div className="mt-7 h-[300px] max-w-[640px] rounded-[20px] border border-rule bg-sheet" />
    </div>
  )
}
