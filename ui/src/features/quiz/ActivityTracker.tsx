import { type KeyboardEvent, useEffect, useRef, useState } from 'react'

import { useActivity } from '../../api/hooks'
import type { ActivityDay, ActivitySummary } from '../../api/types'

const WEEKS = 53
const CELL = 12
const GAP = 3
const LABELS = 28 // weekday label column, which stays put while the grid scrolls
const TOP = 16 // month labels
const DAY_MS = 86_400_000
const WEEKDAYS = ['Mon', '', 'Wed', '', 'Fri', '', '']

// Dates are handled as UTC midnights of the learner's calendar days, so no time zone shifts them.
const parse = (iso: string) => {
  const [y, m, d] = iso.split('-').map(Number)
  return Date.UTC(y, m - 1, d)
}
const iso = (t: number) => new Date(t).toISOString().slice(0, 10)
const mondayIndex = (t: number) => (new Date(t).getUTCDay() + 6) % 7
const label = (t: number, options: Intl.DateTimeFormatOptions) =>
  new Date(t).toLocaleDateString('en-GB', { timeZone: 'UTC', ...options })

/** Opacity for a day's share of its goal: nothing, under half, over half, goal met. */
function level(count: number, goal: number): number {
  if (count <= 0) return 0
  const share = count / goal
  return share >= 1 ? 1 : share >= 0.5 ? 0.65 : 0.35
}

function describe(t: number, day: ActivityDay | undefined): string {
  const when = label(t, { weekday: 'short', day: 'numeric', month: 'short' })
  if (!day) return `${when}: no activity.`
  const part = (n: number, goal: number, met: boolean, noun: string) =>
    `${n} of ${goal} ${noun}${met ? ', goal met' : ''}`
  return `${when}: ${part(day.questions, day.questions_goal, day.questions_met, 'questions')} · ${part(
    day.reels,
    day.reels_goal,
    day.reels_met,
    'reels',
  )}.`
}

// Daily goals as a GitHub-style year grid. Each day is one square split diagonally: quiz in the
// top-left half (ink), reels in the bottom-right (indigo); the fuller the colour, the closer to
// that day's goal.
export function ActivityTracker() {
  const activity = useActivity()
  if (activity.isPending) {
    return (
      <div className="mb-10 h-48 animate-pulse rounded-[20px] border border-rule bg-sheet motion-reduce:animate-none" />
    )
  }
  if (activity.isError) {
    return <p className="mb-10 text-[14px] text-muted">The daily tracker is unavailable. {activity.error.message}</p>
  }
  return <Tracker data={activity.data} />
}

function Tracker({ data }: { data: ActivitySummary }) {
  const today = parse(data.today)
  const start = today - (mondayIndex(today) + (WEEKS - 1) * 7) * DAY_MS
  const byDate = new Map(data.days.map((d) => [d.date, d]))
  const [selected, setSelected] = useState(today)
  const scroller = useRef<HTMLDivElement>(null)

  // On a narrow screen the grid scrolls sideways; start at today, on the right.
  useEffect(() => {
    const el = scroller.current
    if (el) el.scrollLeft = el.scrollWidth
  }, [])

  const width = WEEKS * (CELL + GAP)
  const height = TOP + 7 * (CELL + GAP)
  const cells = []
  const months = []
  for (let week = 0; week < WEEKS; week++) {
    const monday = start + week * 7 * DAY_MS
    const x = week * (CELL + GAP)
    // A month label where a month starts within this column (or the first column).
    const firstOfMonth = Array.from({ length: 7 }, (_, r) => monday + r * DAY_MS).find(
      (t) => t <= today && new Date(t).getUTCDate() === 1,
    )
    if (firstOfMonth || week === 0) {
      months.push(
        <text key={`m${week}`} x={x} y={10} className="fill-muted text-[10px]">
          {label(firstOfMonth ?? monday, { month: 'short' })}
        </text>,
      )
    }
    // The first column's label only if the next month's is far enough away not to collide.
    if (firstOfMonth && months.length === 2 && week < 3) months.shift()
    for (let row = 0; row < 7; row++) {
      const t = monday + row * DAY_MS
      if (t > today) continue
      const day = byDate.get(iso(t))
      const quiz = day ? level(day.questions, day.questions_goal) : 0
      const reels = day ? level(day.reels, day.reels_goal) : 0
      cells.push(
        <g
          key={t}
          transform={`translate(${x} ${TOP + row * (CELL + GAP)})`}
          onClick={() => setSelected(t)}
          className="cursor-pointer"
        >
          <g clipPath="url(#tracker-cell)">
            <rect width={CELL} height={CELL} fill="var(--rule)" />
            {quiz > 0 && <polygon points={`0,0 ${CELL},0 0,${CELL}`} fill="var(--ink)" opacity={quiz} />}
            {reels > 0 && <polygon points={`${CELL},0 ${CELL},${CELL} 0,${CELL}`} fill="var(--reel)" opacity={reels} />}
          </g>
          {t === selected && (
            <rect
              x={-1.5}
              y={-1.5}
              width={CELL + 3}
              height={CELL + 3}
              rx={3.5}
              fill="none"
              stroke="var(--graphite)"
              strokeWidth={1.5}
            />
          )}
        </g>,
      )
    }
  }

  function onKeyDown(e: KeyboardEvent) {
    const step = { ArrowUp: -1, ArrowDown: 1, ArrowLeft: -7, ArrowRight: 7 }[e.key]
    if (step === undefined) return
    e.preventDefault()
    setSelected((t) => Math.min(Math.max(t + step * DAY_MS, start), today))
  }

  const { goals, today_progress: now, streaks } = data
  return (
    <section aria-labelledby="tracker-heading" className="mb-10 rounded-[20px] border border-rule bg-sheet p-5 sm:p-7">
      <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-2">
        <h2 id="tracker-heading" className="font-display text-[22px] font-semibold">
          Daily goals
        </h2>
        <p className="text-[14px] text-muted">
          {streaks.questions > 0 || streaks.reels > 0
            ? [
                streaks.questions > 0 && `${streaks.questions}-day quiz streak`,
                streaks.reels > 0 && `${streaks.reels}-day reel streak`,
              ]
                .filter(Boolean)
                .join(' · ')
            : 'No streak yet. Meet a goal today to start one.'}
        </p>
      </div>

      <ul className="mt-3 flex flex-wrap gap-x-6 gap-y-2 text-[15px]">
        <TodayGoal colour="bg-ink" label="questions" done={now.questions} goal={goals.questions} />
        <TodayGoal colour="bg-reel" label="reels" done={now.reels} goal={goals.reels} />
      </ul>

      <div className="mt-5 flex">
        <svg width={LABELS} height={height} aria-hidden className="block shrink-0">
          {WEEKDAYS.map(
            (d, r) =>
              d && (
                <text key={d} x={0} y={TOP + r * (CELL + GAP) + CELL - 2} className="fill-muted text-[10px]">
                  {d}
                </text>
              ),
          )}
        </svg>
        <div ref={scroller} className="min-w-0 overflow-x-auto pb-1">
          <div
            role="group"
            tabIndex={0}
            aria-label="Daily activity for the last year. Use the arrow keys to move between days."
            aria-describedby="tracker-day"
            onKeyDown={onKeyDown}
            className="w-max rounded-md"
          >
            <svg width={width} height={height} aria-hidden className="block">
              <defs>
                <clipPath id="tracker-cell">
                  <rect width={CELL} height={CELL} rx={2.5} />
                </clipPath>
              </defs>
              {months}
              {cells}
            </svg>
          </div>
        </div>
      </div>

      <p id="tracker-day" aria-live="polite" className="mt-3 min-h-[1.5em] text-[14px]">
        {describe(selected, byDate.get(iso(selected)))}
      </p>

      <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-2 text-[13px] text-muted">
        <span className="flex items-center gap-2">
          <svg width={CELL} height={CELL} aria-hidden>
            <polygon points={`0,0 ${CELL},0 0,${CELL}`} fill="var(--ink)" />
            <polygon points={`${CELL},0 ${CELL},${CELL} 0,${CELL}`} fill="var(--reel)" />
          </svg>
          Quiz top-left, reels bottom-right
        </span>
        <span className="flex items-center gap-1.5">
          Less
          {[0.35, 0.65, 1].map((o) => (
            <span key={o} className="flex">
              <span aria-hidden className="size-2.5 rounded-sm bg-ink" style={{ opacity: o }} />
              <span aria-hidden className="size-2.5 rounded-sm bg-reel" style={{ opacity: o }} />
            </span>
          ))}
          Goal met
        </span>
      </div>
    </section>
  )
}

function TodayGoal({ colour, label: noun, done, goal }: { colour: string; label: string; done: number; goal: number }) {
  const met = done >= goal
  return (
    <li className="flex items-center gap-2">
      <span aria-hidden className={`size-2.5 rounded-full ${colour}`} />
      <span>
        Today{' '}
        <span className="font-bold tabular-nums">
          {Math.min(done, 9999)}/{goal}
        </span>{' '}
        {noun}
        {met && <span className="font-bold text-ink"> · done</span>}
      </span>
    </li>
  )
}
