import { CaretDownIcon, TrashIcon } from '@phosphor-icons/react'
import { type ReactNode, useId, useState } from 'react'

import { useNoteItems, useRemoveNoteFile, useRetryTask, useUpdateScope } from '../../api/hooks'
import type { ContentKind, Note, NoteScope, TodaysQuizOutcome } from '../../api/types'
import { Checkbox } from '../../components/Checkbox'
import { type Coverage, PageRange } from '../../components/PageRange'
import { RichText } from '../../components/RichText'
import { documentName, longDate, pageRange } from '../quiz/format'
import { activityText, capitalize, pagesText } from './pipelineText'

const outcomeText: Record<Exclude<TodaysQuizOutcome, null>, string> = {
  rebuilt: "Saved. Today's quiz now uses your new selection.",
  started: "Saved. Today's quiz is already under way, so this applies from tomorrow.",
  empty: 'Saved. Nothing you selected has questions yet, so there is no quiz today.',
}

// One PDF in Manage notes, as an accordion row: the header (selection, name, live status) is
// always visible; the page range, content types, failures and preview open on demand.
export function NoteCard({
  note,
  handle,
  expanded,
  onToggle,
}: {
  note: Note
  handle?: ReactNode
  expanded: boolean
  onToggle: () => void
}) {
  const bodyId = useId()
  const update = useUpdateScope(note.id)
  const remove = useRemoveNoteFile()
  const [confirming, setConfirming] = useState(false)
  const { scope } = note
  // Local copy of the range so the slider moves smoothly; it's saved when released.
  const [range, setRange] = useState<[number, number]>([scope.page_from, scope.page_to])
  const [synced, setSynced] = useState(scope)
  if (synced !== scope) {
    setSynced(scope)
    setRange([scope.page_from, scope.page_to])
  }

  function save(patch: Partial<NoteScope>) {
    update.mutate(patch)
  }

  function commitRange([from, to]: [number, number]) {
    if (from !== scope.page_from || to !== scope.page_to) save({ page_from: from, page_to: to })
  }

  const active = note.available && scope.selected
  const where = note.folder ? `${note.folder} · ` : ''
  const meta = !note.available
    ? 'Removed. Upload this PDF again to use it; its questions and reels are kept.'
    : !scope.selected
      ? `${where}${note.page_count} pages. Not used for quizzes or reels.`
      : `${where}${note.page_count} pages.`
  const stuck = note.progress.quiz.failed.length + note.progress.reel.failed.length

  // The kinds this PDF is used for; reels only once the reel pipeline has done something here.
  const kinds = (['quiz', 'reel'] as const).filter((kind) =>
    kind === 'quiz'
      ? scope.include_quiz
      : scope.include_reels && (note.progress.reel.done_ranges.length > 0 || !!note.progress.reel.active),
  )
  // A strip (and its legend) only once that kind has made something; the status line covers "nothing yet".
  const coverage: Coverage[] = kinds
    .filter((kind) => note.progress[kind].done_ranges.length > 0)
    .map((kind) =>
      kind === 'quiz'
        ? { label: 'Questions made', ranges: note.progress.quiz.done_ranges, pattern: 'stripes' }
        : { label: 'Reels made', ranges: note.progress.reel.done_ranges, pattern: 'dots' },
    )

  return (
    <article
      className={`rounded-[20px] border bg-sheet transition-colors ${active ? 'border-rule' : 'border-rule/70 bg-sheet/60'}`}
    >
      <div className="flex items-start justify-between gap-3 px-5 py-4 sm:px-7">
        <div className="min-w-0 flex-1">
          <Checkbox
            size="lg"
            checked={scope.selected}
            disabled={!note.available || update.isPending}
            onChange={(e) => save({ selected: e.target.checked })}
            label={
              <span className="font-display text-[21px] leading-tight font-semibold">{documentName(note.filename)}</span>
            }
            hint={meta}
          />
        </div>
        <div className="-mt-1 -mr-2 flex shrink-0 items-center">
          {handle}
          {note.available && (
            <button
              type="button"
              aria-label={`Remove ${documentName(note.filename)}`}
              title="Remove this PDF"
              aria-expanded={confirming}
              onClick={() => setConfirming((c) => !c)}
              className="grid size-11 place-items-center rounded-xl text-muted transition hover:bg-pen-soft hover:text-pen"
            >
              <TrashIcon weight="bold" className="size-5" aria-hidden />
            </button>
          )}
          {active && (
            <button
              type="button"
              aria-expanded={expanded}
              aria-controls={bodyId}
              aria-label={`${expanded ? 'Hide' : 'Show'} pages and settings for ${documentName(note.filename)}`}
              onClick={onToggle}
              className="grid size-11 place-items-center rounded-xl text-muted transition hover:bg-ink-soft hover:text-ink"
            >
              <CaretDownIcon
                weight="bold"
                aria-hidden
                className={`size-5 transition-transform motion-reduce:transition-none ${expanded ? 'rotate-180' : ''}`}
              />
            </button>
          )}
        </div>
      </div>

      {note.available && confirming && (
        <div
          role="group"
          aria-label={`Remove ${documentName(note.filename)}?`}
          className="mx-5 mb-4 flex flex-col gap-3 rounded-xl border border-pen/40 bg-pen-soft p-4 sm:mx-7 sm:flex-row sm:items-center sm:justify-between"
        >
          <p className="text-[14px] leading-snug">
            Remove this PDF? The pipeline stops using it. Its questions and reels are kept, and uploading it again
            brings it back.
          </p>
          <div className="flex shrink-0 gap-2">
            <button
              type="button"
              onClick={() => setConfirming(false)}
              className="inline-flex h-11 items-center rounded-xl border border-rule bg-sheet px-4 font-display text-[16px] font-semibold transition hover:border-ink/40"
            >
              Cancel
            </button>
            <button
              type="button"
              disabled={remove.isPending}
              onClick={() => remove.mutate(note.id, { onSuccess: () => setConfirming(false) })}
              className="inline-flex h-11 items-center rounded-xl bg-pen px-4 font-display text-[16px] font-semibold text-on-ink transition hover:brightness-110 disabled:opacity-50"
            >
              {remove.isPending ? 'Removing…' : 'Remove'}
            </button>
          </div>
        </div>
      )}
      {remove.isError && (
        <p className="px-5 pb-4 text-[14px] text-pen sm:px-7">Couldn't remove it. {remove.error.message}</p>
      )}

      {active && (kinds.length > 0 || stuck > 0) && (
        <ul aria-live="polite" className="-mt-1 flex max-w-[34rem] flex-col gap-1.5 px-5 pb-4 pl-[3.75rem] text-[14px] sm:pr-7 sm:pl-[4.25rem]">
          {kinds.map((kind) => (
            <PipelineLine key={kind} kind={kind} note={note} />
          ))}
          {stuck > 0 && !expanded && (
            <li className="text-pen">
              {stuck === 1 ? '1 part got stuck' : `${stuck} parts got stuck`}. Open to retry.
            </li>
          )}
        </ul>
      )}

      {active && expanded && (
        <div id={bodyId} className="flex flex-col gap-7 border-t border-rule px-5 py-6 sm:px-7">
          <PageRange
            pageCount={note.page_count}
            coverage={coverage}
            value={range}
            onChange={setRange}
            onCommit={commitRange}
          />

          <fieldset>
            <legend className="font-display text-[17px] font-semibold">Use these pages for</legend>
            <div className="mt-2 grid gap-1 sm:grid-cols-2">
              <Checkbox
                checked={scope.include_quiz}
                onChange={(e) => save({ include_quiz: e.target.checked })}
                label="Quiz"
                hint={
                  note.questions.total
                    ? `${note.questions.in_scope} of ${note.questions.total} questions in these pages`
                    : 'No questions made yet'
                }
              />
              <Checkbox
                checked={scope.include_reels}
                onChange={(e) => save({ include_reels: e.target.checked })}
                label="Reels"
                hint={
                  note.reels.total ? `${note.reels.in_scope} of ${note.reels.total} reels in these pages` : 'No reels made yet'
                }
              />
            </div>
          </fieldset>

          <Failures note={note} />

          {(note.questions.total > 0 || note.reels.total > 0) && <Preview note={note} range={range} />}
        </div>
      )}

      <p aria-live="polite" className="px-5 pb-4 text-[14px] empty:hidden sm:px-7">
        {update.isPending && <span className="text-muted">Saving…</span>}
        {update.isError && <span className="text-pen">Couldn't save. {update.error.message}</span>}
        {update.isSuccess && (
          <span className="text-ink">{update.data.todays_quiz ? outcomeText[update.data.todays_quiz] : 'Saved.'}</span>
        )}
      </p>
    </article>
  )
}

// "Writing questions for pages 29–32, round 2 of 3" while the pipeline works here, else how far it has got.
function PipelineLine({ kind, note }: { kind: ContentKind; note: Note }) {
  const p = note.progress[kind]
  const label = kind === 'quiz' ? 'Questions' : 'Reels'
  const pct = p.pages_in_range ? (p.pages_done / p.pages_in_range) * 100 : 0
  return (
    <li className="flex flex-col gap-1">
      <div className="grid grid-cols-[4.75rem_1fr_3.75rem] items-center gap-2.5">
        <span className="text-[13px] font-bold text-graphite">{label}</span>
        <div
          role="progressbar"
          aria-label={`${label}: ${p.pages_done} of ${p.pages_in_range} pages done`}
          aria-valuemin={0}
          aria-valuemax={p.pages_in_range}
          aria-valuenow={p.pages_done}
          className="h-2 overflow-hidden rounded-full bg-rule"
        >
          <div
            className={`h-full rounded-full transition-[width] duration-500 motion-reduce:transition-none ${
              kind === 'quiz' ? 'bg-ink' : 'bg-reel'
            }`}
            // A sliver even for a page or two, so "started" never looks like "nothing".
            style={{ width: p.pages_done ? `max(${pct}%, 6px)` : '0' }}
          />
        </div>
        <span className="text-right text-[13px] text-muted tabular-nums">
          {p.pages_done}/{p.pages_in_range}
        </span>
      </div>
      {p.active && (
        <span className={`flex items-center gap-2 text-[13px] font-bold ${kind === 'quiz' ? 'text-ink' : 'text-reel'}`}>
          <span
            aria-hidden
            className={`size-2 shrink-0 animate-pulse rounded-full motion-reduce:animate-none ${
              kind === 'quiz' ? 'bg-ink' : 'bg-reel'
            }`}
          />
          {activityText(kind, p.active.stage, p.active.pages, p.active.detail)}
        </span>
      )}
    </li>
  )
}

// Pages the pipeline gave up on, with the reason and a way to try again.
function Failures({ note }: { note: Note }) {
  const retry = useRetryTask()
  const failed = (['quiz', 'reel'] as const).flatMap((kind) => note.progress[kind].failed.map((f) => ({ ...f, kind })))
  if (failed.length === 0) return null
  return (
    <section aria-label="Failed pages">
      <h3 className="font-display text-[17px] font-semibold text-pen">
        {failed.length === 1 ? 'The pipeline got stuck on 1 part' : `The pipeline got stuck on ${failed.length} parts`}
      </h3>
      <ul className="mt-2 divide-y divide-rule border-y border-rule">
        {failed.map((f) => (
          <li key={f.task_id} className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 py-3">
            <p className="min-w-0 text-[15px] leading-snug">
              <span className="font-bold">{capitalize(pagesText(f.pages))}</span>
              {f.kind === 'reel' && <span className="text-muted"> (reel)</span>}
              <span className="block text-[13px] break-words text-muted">{f.error ?? 'No reason recorded.'}</span>
            </p>
            <button
              type="button"
              onClick={() => retry.mutate(f.task_id)}
              disabled={retry.isPending && retry.variables === f.task_id}
              className="inline-flex h-11 items-center rounded-xl border border-rule bg-sheet px-4 font-display text-[16px] font-semibold transition hover:border-ink/40 active:scale-[0.98] disabled:opacity-50"
            >
              {retry.isPending && retry.variables === f.task_id ? 'Retrying…' : 'Retry'}
            </button>
          </li>
        ))}
      </ul>
      {retry.isError && <p className="mt-2 text-[14px] text-pen">Couldn't retry. {retry.error.message}</p>}
    </section>
  )
}

// What's in the chosen pages, as two collapsible sections (Questions, Reels), each with the pages
// every item comes from. The items load when either section is first opened, and follow the
// slider live.
function Preview({ note, range: [from, to] }: { note: Note; range: [number, number] }) {
  const [opened, setOpened] = useState(false)
  const items = useNoteItems(note.id, opened)
  const inRange = (pages: number[]) => pages.length > 0 && pages.every((p) => p >= from && p <= to)
  const questions = items.data?.questions.filter((q) => inRange(q.source_pages))
  const reels = items.data?.reels.filter((r) => inRange(r.source_pages))
  const hidden = items.data && questions ? items.data.questions.length - questions.length : 0

  const body = (content: ReactNode) =>
    items.isPending ? (
      <p className="pb-3 text-muted">Loading…</p>
    ) : items.isError ? (
      <p className="pb-3 text-pen">Couldn't load what's in these pages. {items.error.message}</p>
    ) : (
      content
    )

  return (
    <div className="divide-y divide-rule border-y border-rule">
      {note.questions.total > 0 && (
        <ItemSection
          title="Questions"
          count={questions ? `${questions.length} in pages ${from}–${to}` : `${note.questions.total} made`}
          muted={!note.scope.include_quiz ? 'not used for quizzes' : null}
          onOpen={() => setOpened(true)}
        >
          {body(
            <>
              {questions?.length === 0 ? (
                <p className="pb-3 text-[15px] text-muted">No questions come only from these pages.</p>
              ) : (
                <ul className="divide-y divide-rule border-t border-rule">
                  {questions?.map((q) => (
                    <li key={q.id} className="py-3">
                      <p className="line-clamp-2 text-[15px] leading-snug">
                        <RichText text={q.stem} />
                      </p>
                      <p className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-[13px] text-muted">
                        <span className="font-bold text-graphite">{capitalize(pageRange(q.source_pages))}</span>
                        <span className="capitalize">{q.difficulty}</span>
                        {q.quiz_date && <span>In the quiz for {longDate(q.quiz_date)}</span>}
                      </p>
                    </li>
                  ))}
                </ul>
              )}
              {hidden > 0 && (
                <p className="pb-3 text-[13px] text-muted">
                  {hidden} more {hidden === 1 ? 'question comes' : 'questions come'} from pages outside this range.
                </p>
              )}
            </>,
          )}
        </ItemSection>
      )}
      {note.reels.total > 0 && (
        <ItemSection
          title="Reels"
          count={reels ? `${reels.length} in pages ${from}–${to}` : `${note.reels.total} made`}
          muted={!note.scope.include_reels ? 'not shown in Reels' : null}
          onOpen={() => setOpened(true)}
        >
          {body(
            reels?.length === 0 ? (
              <p className="pb-3 text-[15px] text-muted">No reels made from these pages yet.</p>
            ) : (
              <ul className="divide-y divide-rule border-t border-rule">
                {reels?.map((r) => (
                  <li key={r.id} className="py-3">
                    <p className="text-[15px] leading-snug">{r.title}</p>
                    <p className="mt-1 text-[13px] text-muted">
                      {capitalize(pageRange(r.source_pages))}
                      {r.duration_s ? ` · ${Math.round(r.duration_s)} s` : ''}
                    </p>
                  </li>
                ))}
              </ul>
            ),
          )}
        </ItemSection>
      )}
    </div>
  )
}

// A native disclosure, so it opens with the keyboard and screen readers announce its state.
function ItemSection({
  title,
  count,
  muted,
  onOpen,
  children,
}: {
  title: string
  count: string
  muted: string | null
  onOpen: () => void
  children: ReactNode
}) {
  return (
    <details onToggle={(e) => e.currentTarget.open && onOpen()} className={`group ${muted ? 'opacity-60' : ''}`}>
      <summary className="flex min-h-12 cursor-pointer list-none items-center gap-3 py-2 [&::-webkit-details-marker]:hidden">
        <CaretDownIcon
          weight="bold"
          aria-hidden
          className="size-4 shrink-0 -rotate-90 text-muted transition-transform group-open:rotate-0 motion-reduce:transition-none"
        />
        <span className="font-display text-[17px] font-semibold">{title}</span>
        <span className="ml-auto text-right text-[13px] text-muted">
          {count}
          {muted && <span className="block">{muted}</span>}
        </span>
      </summary>
      {children}
    </details>
  )
}
