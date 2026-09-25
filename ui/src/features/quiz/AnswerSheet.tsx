import { Bubble, type BubbleMark } from '../../components/Bubble'

// The day's answer sheet: one numbered bubble per question, marked from an attempt or run.
export function AnswerSheet({ marks, size = 'md' }: { marks: BubbleMark[]; size?: 'sm' | 'md' }) {
  return (
    <ol className="grid grid-cols-5 gap-x-3 gap-y-4" aria-label="Answer sheet">
      {marks.map((mark, i) => (
        <li key={i} className="flex flex-col items-center gap-1.5">
          <span className="font-display text-[13px] font-medium text-muted tabular-nums">{i + 1}</span>
          <Bubble mark={mark} label="" size={size} />
          <span className="sr-only">
            Question {i + 1}: {mark === 'right' ? 'correct' : mark === 'wrong' ? 'wrong' : 'not answered'}
          </span>
        </li>
      ))}
    </ol>
  )
}
