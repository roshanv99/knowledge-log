import { CheckIcon, XIcon } from '@phosphor-icons/react'
import { motion, useReducedMotion } from 'motion/react'

// One answer-sheet bubble. `pencil` is a filled-in choice before marking; `right`/`wrong`
// are marked; `answer` rings the correct option the learner didn't pick.
export type BubbleMark = 'empty' | 'current' | 'pencil' | 'right' | 'wrong' | 'answer'

const sizes = {
  sm: 'size-7 text-[13px]',
  md: 'size-9 text-[15px]',
}

export function Bubble({ mark, label, size = 'md' }: { mark: BubbleMark; label: string; size?: keyof typeof sizes }) {
  const reduce = useReducedMotion()
  const filled = mark === 'pencil' || mark === 'right'
  const ring = {
    empty: 'border-ink/55 text-muted',
    current: 'border-graphite text-graphite border-[2.5px]',
    pencil: 'border-graphite text-on-ink',
    right: 'border-ink text-on-ink',
    wrong: 'border-pen bg-pen-soft text-pen',
    answer: 'border-ink border-[2.5px] bg-ink-soft text-ink',
  }[mark]

  return (
    <span
      aria-hidden
      className={`relative grid shrink-0 place-items-center overflow-hidden rounded-full border-[1.5px] font-display font-semibold ${sizes[size]} ${ring}`}
    >
      {filled && (
        <motion.span
          className={`absolute inset-0 rounded-full ${mark === 'right' ? 'bg-ink' : 'bg-graphite'}`}
          initial={reduce ? false : { scale: 0.2, opacity: 0.4 }}
          animate={{ scale: 1, opacity: 1 }}
          transition={{ duration: 0.16, ease: 'easeOut' }}
        />
      )}
      <span className="relative">
        {mark === 'right' ? (
          <CheckIcon weight="bold" className="size-[0.95em]" />
        ) : mark === 'wrong' ? (
          <XIcon weight="bold" className="size-[0.95em]" />
        ) : (
          label
        )}
      </span>
    </span>
  )
}
