import { CaretLeftIcon, CaretRightIcon, DotsSixVerticalIcon, MagnifyingGlassIcon } from '@phosphor-icons/react'
import { Reorder, useDragControls, useReducedMotion } from 'motion/react'
import { type ReactNode, useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router'

import { pipelineBusy, useMoveNote, useNotes, usePipelineStatus } from '../../api/hooks'
import type { Note, NotesList, NotesQuery } from '../../api/types'
import { ErrorState } from '../../components/ErrorState'
import { documentName } from '../quiz/format'
import { NoteCard } from './NoteCard'
import { PipelinePanel } from './PipelinePanel'
import { UploadPanel } from './UploadPanel'

const SEARCH_DEBOUNCE_MS = 250

// Filters and the page live in the URL, so back/forward and reloads keep the view.
function useNotesQuery(): [NotesQuery, (patch: Partial<NotesQuery>) => void] {
  const [params, setParams] = useSearchParams()
  const selected = params.get('selected')
  const query: NotesQuery = {
    page: Math.max(1, Number(params.get('page')) || 1),
    q: params.get('q') ?? '',
    folder: params.get('folder') ?? '',
    selected: selected === 'yes' || selected === 'no' ? selected : 'all',
  }
  function update(patch: Partial<NotesQuery>) {
    const next = { ...query, ...patch }
    // Changing a filter starts again from page 1.
    if (!('page' in patch)) next.page = 1
    const out = new URLSearchParams()
    if (next.page > 1) out.set('page', String(next.page))
    if (next.q) out.set('q', next.q)
    if (next.folder) out.set('folder', next.folder)
    if (next.selected !== 'all') out.set('selected', next.selected)
    setParams(out, { replace: !('page' in patch) })
  }
  return [query, update]
}

export function NotesPage() {
  const [query, setQuery] = useNotesQuery()
  const busy = pipelineBusy(usePipelineStatus().data)
  const notes = useNotes(query, busy)
  // When a run ends, fetch once more so the cards show its last results.
  const wasBusy = useRef(busy)
  const { refetch } = notes
  useEffect(() => {
    if (wasBusy.current && !busy) refetch()
    wasBusy.current = busy
  }, [busy, refetch])

  return (
    <div className="mx-auto max-w-[820px] px-5 pt-8 pb-10 sm:px-8 lg:px-12 lg:pt-14">
      <h1 className="font-display text-[36px] leading-[1.05] font-semibold tracking-tight">Manage notes</h1>
      <p className="mt-2 max-w-[56ch] leading-relaxed text-muted">
        Choose which PDFs and pages your quizzes and reels come from. Newest PDFs are at the top; new questions and reels
        are made from the bottom of the list up. Drag to change the order.
      </p>

      <PipelinePanel />

      {notes.isPending ? (
        <div aria-busy="true" aria-label="Loading notes" className="mt-8 flex flex-col gap-3">
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-24 animate-pulse rounded-[20px] border border-rule bg-sheet motion-reduce:animate-none" />
          ))}
        </div>
      ) : notes.isError ? (
        <div className="mt-8">
          <ErrorState error={notes.error} onRetry={() => notes.refetch()} />
        </div>
      ) : notes.data.summary.documents === 0 ? (
        <>
          <UploadPanel folders={[]} />
          <section className="mt-8 max-w-[56ch]">
            <h2 className="font-display text-[22px] font-semibold">No notes yet</h2>
            <p className="mt-2 leading-relaxed text-muted">
              Upload a PDF to get started. Quiz questions and reels are made from the PDFs you add here.
            </p>
          </section>
        </>
      ) : (
        <>
          <UploadPanel folders={notes.data.folders} />
          <NoteList list={notes.data} query={query} setQuery={setQuery} stale={notes.isPlaceholderData} />
        </>
      )}
    </div>
  )
}

function NoteList({
  list,
  query,
  setQuery,
  stale,
}: {
  list: NotesList
  query: NotesQuery
  setQuery: (patch: Partial<NotesQuery>) => void
  stale: boolean
}) {
  const move = useMoveNote()
  const [expanded, setExpanded] = useState<Set<number>>(new Set())
  const [announcement, setAnnouncement] = useState('')
  // The page's order while a card is dragged; kept until the saved order comes back.
  const [dragOrder, setDragOrder] = useState<number[] | null>(null)
  const dragged = useRef<number | null>(null)
  const top = useRef<HTMLDivElement>(null)

  const filtered = !!(query.q || query.folder || query.selected !== 'all')
  const stored = list.notes.filter((n) => n.available && n.position !== null)
  const missing = list.notes.filter((n) => !n.available)
  const byId = new Map(stored.map((n) => [n.id, n]))
  const shown = dragOrder ? dragOrder.map((id) => byId.get(id)).filter((n): n is Note => !!n) : stored
  // Reordering needs the whole list in view: a position inside a filtered list is ambiguous.
  const reorderable = !filtered && stored.length > 0
  const firstPosition = stored[0]?.position ?? 0
  const pages = Math.max(1, Math.ceil(list.total / list.page_size))
  const from = list.total === 0 ? 0 : (list.page - 1) * list.page_size + 1
  const to = Math.min(list.page * list.page_size, list.total)

  function toggle(id: number) {
    setExpanded((open) => {
      const next = new Set(open)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  async function moveTo(note: Note, position: number) {
    setAnnouncement(`${documentName(note.filename)} moved to position ${position + 1} of ${list.summary.documents}.`)
    try {
      await move.mutateAsync({ id: note.id, position })
    } finally {
      setDragOrder(null)
    }
  }

  function drop() {
    const id = dragged.current
    dragged.current = null
    if (id === null || !dragOrder) return
    const index = dragOrder.indexOf(id)
    const note = byId.get(id)
    if (!note || firstPosition + index === note.position) {
      setDragOrder(null)
      return
    }
    void moveTo(note, firstPosition + index)
  }

  function goTo(page: number) {
    setQuery({ page })
    top.current?.scrollIntoView({ block: 'start' })
  }

  return (
    <>
      <p className="mt-6 text-[15px]" aria-live="polite">
        <span className="font-display text-[17px] font-semibold">
          {list.summary.selected} of {list.summary.documents}
        </span>{' '}
        PDFs selected, with{' '}
        <span className="font-display text-[17px] font-semibold">{list.summary.questions_ready}</span> questions ready for
        quizzes.
      </p>

      <div ref={top} className="scroll-mt-4">
        <Toolbar list={list} query={query} setQuery={setQuery} />
      </div>

      <p className="sr-only" aria-live="assertive">
        {announcement}
      </p>
      {move.isError && <p className="mt-3 text-[14px] text-pen">Couldn't save the new order. {move.error.message}</p>}

      <div className={`mt-4 transition-opacity ${stale ? 'opacity-60' : ''}`} aria-busy={stale}>
        {list.total === 0 ? (
          <section className="rounded-[20px] border border-rule bg-sheet p-5 sm:px-7">
            <h2 className="font-display text-[19px] font-semibold">No PDFs match</h2>
            <button
              type="button"
              onClick={() => setQuery({ q: '', folder: '', selected: 'all' })}
              className="mt-2 font-bold text-ink underline underline-offset-2"
            >
              Clear the filters
            </button>
          </section>
        ) : (
          <>
            {filtered && stored.length > 1 && (
              <p className="mb-3 text-[13px] text-muted">Clear the search and filters to reorder.</p>
            )}
            {reorderable ? (
              <Reorder.Group
                axis="y"
                values={shown.map((n) => n.id)}
                onReorder={(ids: number[]) => setDragOrder(ids)}
                // No stray text selection while a card is being dragged.
                className={`flex flex-col gap-3 ${dragOrder ? 'select-none' : ''}`}
              >
                {shown.map((note) => (
                  <DraggableCard
                    key={note.id}
                    note={note}
                    total={list.summary.documents}
                    expanded={expanded.has(note.id)}
                    onToggle={() => toggle(note.id)}
                    onDragStart={() => {
                      dragged.current = note.id
                      setDragOrder(shown.map((n) => n.id))
                    }}
                    onDrop={drop}
                    onMove={(by) => {
                      const target = Math.min(Math.max((note.position ?? 0) + by, 0), list.summary.documents - 1)
                      if (target !== note.position) void moveTo(note, target)
                    }}
                  />
                ))}
              </Reorder.Group>
            ) : (
              <ul className="flex flex-col gap-3">
                {stored.map((note) => (
                  <li key={note.id}>
                    <NoteCard note={note} expanded={expanded.has(note.id)} onToggle={() => toggle(note.id)} />
                  </li>
                ))}
              </ul>
            )}
            {missing.length > 0 && (
              <section aria-label="Removed PDFs" className="mt-6">
                <h2 className="font-display text-[17px] font-semibold text-muted">Removed PDFs</h2>
                <ul className="mt-3 flex flex-col gap-3">
                  {missing.map((note) => (
                    <li key={note.id}>
                      <NoteCard note={note} expanded={false} onToggle={() => {}} />
                    </li>
                  ))}
                </ul>
              </section>
            )}
          </>
        )}
      </div>

      {list.total > 0 && (
        <nav aria-label="Pages of notes" className="mt-6 flex flex-wrap items-center justify-between gap-3">
          <p className="text-[14px] text-muted">
            {from}–{to} of {list.total}
          </p>
          {pages > 1 && (
            <div className="flex items-center gap-2">
              <PageButton label="Previous page" disabled={list.page <= 1} onClick={() => goTo(list.page - 1)}>
                <CaretLeftIcon weight="bold" className="size-5" aria-hidden />
              </PageButton>
              <span className="min-w-[7ch] text-center font-display text-[16px] font-semibold tabular-nums" aria-current="page">
                {list.page} / {pages}
              </span>
              <PageButton label="Next page" disabled={list.page >= pages} onClick={() => goTo(list.page + 1)}>
                <CaretRightIcon weight="bold" className="size-5" aria-hidden />
              </PageButton>
            </div>
          )}
        </nav>
      )}
    </>
  )
}

function Toolbar({
  list,
  query,
  setQuery,
}: {
  list: NotesList
  query: NotesQuery
  setQuery: (patch: Partial<NotesQuery>) => void
}) {
  // Typing updates the field at once; the list follows after a short pause.
  const [text, setText] = useState(query.q)
  const [synced, setSynced] = useState(query.q)
  if (synced !== query.q) {
    setSynced(query.q)
    setText(query.q)
  }
  const apply = useRef(setQuery)
  useEffect(() => {
    apply.current = setQuery
  })
  useEffect(() => {
    if (text === query.q) return
    const timer = setTimeout(() => apply.current({ q: text }), SEARCH_DEBOUNCE_MS)
    return () => clearTimeout(timer)
  }, [text, query.q])

  const field = 'h-11 rounded-xl border border-rule bg-sheet px-3 text-[15px] text-graphite'
  return (
    <div role="search" className="mt-6 grid grid-cols-2 gap-3 sm:flex sm:items-end">
      <label className="col-span-2 flex min-w-0 flex-1 flex-col gap-1">
        <span className="text-[13px] font-bold">Search</span>
        <span className="relative">
          <MagnifyingGlassIcon
            aria-hidden
            className="pointer-events-none absolute top-1/2 left-3 size-5 -translate-y-1/2 text-muted"
          />
          <input
            type="search"
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="PDF name"
            className={`${field} w-full pl-10`}
          />
        </span>
      </label>
      {list.folders.length > 1 && (
        <label className="flex min-w-0 flex-col gap-1">
          <span className="text-[13px] font-bold">Folder</span>
          <select value={query.folder} onChange={(e) => setQuery({ folder: e.target.value })} className={field}>
            <option value="">All folders</option>
            {list.folders.map((f) => (
              <option key={f} value={f}>
                {f || 'Top level'}
              </option>
            ))}
          </select>
        </label>
      )}
      <label className={`flex min-w-0 flex-col gap-1 ${list.folders.length > 1 ? '' : 'col-span-2 sm:col-span-1'}`}>
        <span className="text-[13px] font-bold">Show</span>
        <select
          value={query.selected}
          onChange={(e) => setQuery({ selected: e.target.value as NotesQuery['selected'] })}
          className={field}
        >
          <option value="all">All PDFs</option>
          <option value="yes">Selected</option>
          <option value="no">Not selected</option>
        </select>
      </label>
    </div>
  )
}

function PageButton({
  label,
  disabled,
  onClick,
  children,
}: {
  label: string
  disabled: boolean
  onClick: () => void
  children: ReactNode
}) {
  return (
    <button
      type="button"
      aria-label={label}
      disabled={disabled}
      onClick={onClick}
      className="grid size-11 place-items-center rounded-xl border border-rule bg-sheet transition hover:border-ink/40 active:scale-[0.98] disabled:pointer-events-none disabled:opacity-40"
    >
      {children}
    </button>
  )
}

// Dragged by its handle only, so the page-range slider inside the card still works. The handle
// also moves the card with the arrow keys, one place at a time, across pages too.
function DraggableCard({
  note,
  total,
  expanded,
  onToggle,
  onDragStart,
  onDrop,
  onMove,
}: {
  note: Note
  total: number
  expanded: boolean
  onToggle: () => void
  onDragStart: () => void
  onDrop: () => void
  onMove: (by: -1 | 1) => void
}) {
  const controls = useDragControls()
  const reduce = useReducedMotion()
  const name = documentName(note.filename)
  return (
    <Reorder.Item
      value={note.id}
      dragListener={false}
      dragControls={controls}
      onDragStart={onDragStart}
      onDragEnd={onDrop}
      transition={reduce ? { duration: 0 } : undefined}
      className="relative"
    >
      <NoteCard
        note={note}
        expanded={expanded}
        onToggle={onToggle}
        handle={
          <button
            type="button"
            aria-label={`Reorder ${name}, position ${(note.position ?? 0) + 1} of ${total}. Use the arrow keys to move it.`}
            title="Drag to reorder"
            onPointerDown={(e) => {
              e.preventDefault()
              controls.start(e)
            }}
            onKeyDown={(e) => {
              if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
                e.preventDefault()
                onMove(e.key === 'ArrowUp' ? -1 : 1)
              }
            }}
            className="grid size-11 shrink-0 cursor-grab touch-none place-items-center rounded-xl text-muted transition hover:bg-ink-soft hover:text-ink active:cursor-grabbing"
          >
            <DotsSixVerticalIcon weight="bold" className="size-6" aria-hidden />
          </button>
        }
      />
    </Reorder.Item>
  )
}
