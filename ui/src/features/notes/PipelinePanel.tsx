import { usePipelineStatus, useSettings } from '../../api/hooks'
import type { ContentKind, PipelineStatus } from '../../api/types'
import { documentName } from '../quiz/format'
import { activityText, ago, clock, stopReasonText, useNow } from './pipelineText'

// The runner polls every 5 minutes; after three missed polls, say so.
const RUNNER_QUIET_MS = 15 * 60 * 1000

const KINDS: { kind: ContentKind; making: string; made: (n: number) => string }[] = [
  { kind: 'quiz', making: 'Making questions', made: (n) => `${n} ${n === 1 ? 'question' : 'questions'}` },
  { kind: 'reel', making: 'Making a reel', made: (n) => `${n} ${n === 1 ? 'reel' : 'reels'}` },
]

// What the pipeline is doing for each kind. Runs are started from Claude Code (the /mcq-generation and
// /reel-generation skills) or by the Mac's runner, not from here.
// Questions and reels run side by side, each in its own Claude Code session.
export function PipelinePanel() {
  const status = usePipelineStatus()
  const settings = useSettings()
  const now = useNow()

  if (status.isPending) {
    return <div className="mt-6 h-32 animate-pulse rounded-[20px] border border-rule bg-sheet motion-reduce:animate-none" />
  }
  if (status.isError) {
    return (
      <p className="mt-6 text-[14px] text-muted" role="status">
        Pipeline status unavailable. {status.error.message}
      </p>
    )
  }
  const enabled = settings.data?.pipeline_enabled ?? true
  return (
    <section aria-label="Pipeline" aria-live="polite" className="mt-6 rounded-[20px] border border-rule bg-sheet">
      <ul className="divide-y divide-rule">
        {KINDS.map((k) => (
          <KindRow key={k.kind} {...k} status={status.data} now={now} />
        ))}
      </ul>
      <div className="border-t border-rule px-5 py-3 sm:px-7">
        {!enabled && <p className="text-[14px] text-pen">The pipeline is switched off in Settings.</p>}
        {status.data.failed_tasks.length > 0 && (
          <p className="text-[14px] text-pen">
            {status.data.failed_tasks.length === 1 ? '1 part needs' : `${status.data.failed_tasks.length} parts need`} a
            retry. See the cards below.
          </p>
        )}
        <RunnerLine status={status.data} now={now} />
      </div>
    </section>
  )
}

function KindRow({
  kind,
  making,
  made,
  status,
  now,
}: (typeof KINDS)[number] & { status: PipelineStatus; now: number }) {
  const run = status.active_runs.find((r) => r.kind === kind)
  const waiting = status.open_requests.find((r) => r.kind === kind)
  const last = status.recent_runs.find((r) => r.kind === kind)
  const count = (r: { questions_made: number; reels_made: number }) => (kind === 'quiz' ? r.questions_made : r.reels_made)

  let headline: string
  let body: string
  let meta: string | null = null
  if (run) {
    const task = run.tasks[0]
    headline = making
    body = task
      ? `${documentName(task.document)}: ${activityText(task.kind, task.stage, task.pages, task.detail)}.`
      : 'Choosing the next pages…'
    meta = `Started ${clock(run.started_at)} · ${run.tasks_done} ${run.tasks_done === 1 ? 'part' : 'parts'} done · ${made(count(run))} made`
  } else if (waiting) {
    headline = `${kind === 'quiz' ? 'Questions' : 'Reel'} requested`
    body = `Asked ${ago(waiting.created_at, now)}. Your Mac starts it on its next check, within 5 minutes.`
  } else {
    headline = kind === 'quiz' ? 'Questions' : 'Reels'
    body = last?.finished_at
      ? `Last run ${ago(last.finished_at, now)}: stopped because ${stopReasonText(last.stop_reason)}. ${made(count(last))} made.`
      : 'No runs yet.'
  }
  const { made: reelsMade, limit } = status.reels
  const atLimit = kind === 'reel' && limit > 0 && reelsMade >= limit
  if (kind === 'reel' && limit > 0) {
    meta = [meta, atLimit ? `${reelsMade} of ${limit} reels made: the limit in Settings is reached.` : `${reelsMade} of ${limit} reels made.`]
      .filter(Boolean)
      .join(' · ')
  }

  return (
    <li className="flex flex-col gap-3 p-5 sm:flex-row sm:items-start sm:justify-between sm:px-7">
      <div className="min-w-0">
        <h2 className="flex items-center gap-2 font-display text-[19px] font-semibold">
          {run && (
            <span aria-hidden className="size-2.5 shrink-0 animate-pulse rounded-full bg-ink motion-reduce:animate-none" />
          )}
          {headline}
        </h2>
        <p className="mt-1 text-[15px] leading-snug">{body}</p>
        {meta && <p className="mt-1 text-[13px] text-muted">{meta}</p>}
      </div>
    </li>
  )
}

function RunnerLine({ status, now }: { status: PipelineStatus; now: number }) {
  const seen = status.runners
    .map((r) => r.last_seen_at)
    .filter((t): t is string => !!t)
    .sort()
    .at(-1)
  if (status.runners.length === 0) {
    return <p className="text-[13px] text-muted">No runner is set up on your Mac yet.</p>
  }
  if (!seen) return <p className="text-[13px] text-muted">Your Mac's runner hasn't checked in yet.</p>
  const quiet = now - new Date(seen).getTime() > RUNNER_QUIET_MS
  // Only worth flagging when something is waiting on the runner.
  const waiting = status.open_requests.length > 0 || status.active_runs.length > 0
  return (
    <p className={`text-[13px] ${quiet && waiting ? 'text-pen' : 'text-muted'}`}>
      Your Mac's runner last checked in {ago(seen, now)}
      {quiet && waiting ? '. Is the Mac awake?' : '.'}
    </p>
  )
}
