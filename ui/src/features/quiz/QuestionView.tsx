import { CheckIcon, XIcon } from '@phosphor-icons/react'
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import { useEffect, useRef } from 'react'

import type { Question } from '../../api/types'
import { Bubble, type BubbleMark } from '../../components/Bubble'
import { RichText } from '../../components/RichText'
import { LETTERS } from './answerKeys'
import { documentName, pageRange } from './format'

// One question with its four options (in `display` order) and, once answered, whether it was right
// and why. Shared by the daily quiz and practice.
export function QuestionView({
  question,
  display,
  choice,
  onChoose,
}: {
  question: Question
  display: number[]
  choice: number | undefined
  onChoose: (stored: number) => void
}) {
  const reduce = useReducedMotion()
  const feedbackRef = useRef<HTMLDivElement>(null)
  const revealed = choice !== undefined
  const isRight = choice === question.correct_index
  const choose = onChoose

  useEffect(() => {
    if (revealed) feedbackRef.current?.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'nearest' })
  }, [revealed, reduce])

  function optionMark(stored: number): BubbleMark {
    if (!revealed) return 'empty'
    if (stored === choice) return isRight ? 'right' : 'wrong'
    if (stored === question.correct_index) return 'answer'
    return 'empty'
  }

  return (
      <AnimatePresence mode="wait" initial={false}>
        <motion.article
          key={question.id}
          initial={reduce ? false : { opacity: 0, x: 24 }}
          animate={{ opacity: 1, x: 0 }}
          exit={reduce ? undefined : { opacity: 0, x: -24 }}
          transition={{ duration: 0.18, ease: 'easeOut' }}
          className="pt-6"
        >
          <div className="flex items-center gap-3 text-[13px]">
            <span className="rounded-full border border-rule px-2.5 py-0.5 font-bold text-muted capitalize">
              {question.difficulty}
            </span>
            <span className="line-clamp-1 text-muted">{question.topic}</span>
          </div>

          <h1 className="mt-4 text-[20px] leading-[1.5] sm:text-[22px]">
            <RichText text={question.stem} />
          </h1>

          <div role="radiogroup" aria-label="Answer options" className="mt-6 flex flex-col gap-3">
            {display.map((stored, pos) => {
              const mark = optionMark(stored)
              const tone =
                mark === 'right'
                  ? 'border-ink bg-ink-soft'
                  : mark === 'wrong'
                    ? 'border-pen bg-pen-soft'
                    : mark === 'answer'
                      ? 'border-ink'
                      : revealed
                        ? 'border-rule opacity-55'
                        : 'border-rule bg-sheet hover:border-ink/50 active:scale-[0.99]'
              return (
                <button
                  key={stored}
                  type="button"
                  role="radio"
                  aria-checked={stored === choice}
                  aria-disabled={revealed}
                  onClick={() => choose(stored)}
                  className={`flex w-full items-start gap-4 rounded-xl border-[1.5px] px-4 py-3.5 text-left text-[16px] leading-snug transition ${tone}`}
                >
                  <Bubble mark={mark} label={LETTERS[pos]} />
                  <span className="pt-[7px]">
                    <RichText text={question.options[stored]} />
                  </span>
                </button>
              )
            })}
          </div>

          <div ref={feedbackRef} aria-live="polite" className="scroll-mb-32">
            {revealed && (
              <motion.div
                initial={reduce ? false : { opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.2, ease: 'easeOut' }}
                className="mt-7 border-t border-rule pt-5"
              >
                <p className={`flex items-center gap-2 font-display text-[22px] font-semibold ${isRight ? 'text-ink' : 'text-pen'}`}>
                  {isRight ? <CheckIcon weight="bold" /> : <XIcon weight="bold" />}
                  {isRight ? 'Right' : 'Not quite'}
                </p>
                <p className="mt-2 max-w-[65ch] text-[16px] leading-relaxed">
                  <RichText text={question.explanation} />
                </p>
                <p className="mt-3 text-[13px] text-muted">
                  From {documentName(question.document)}, {pageRange(question.source_pages)}
                </p>
              </motion.div>
            )}
          </div>
        </motion.article>
      </AnimatePresence>
  )
}
