import { UploadSimpleIcon } from '@phosphor-icons/react'
import { useId, useRef, useState } from 'react'

import { useUploadNote } from '../../api/hooks'
import type { UploadOutcome } from '../../api/types'

// Matches KL_MAX_NOTE_BYTES (backend/config/settings.py): Cloudflare refuses bigger uploads.
const MAX_MB = 95

type Row = { id: number; name: string } & (
  | { state: 'waiting' }
  | { state: 'sending'; progress: number }
  | { state: 'checking' }
  | { state: 'done'; outcome: UploadOutcome }
  | { state: 'failed'; message: string }
)

const outcomeText: Record<UploadOutcome, string> = {
  added: 'Added at the top of your notes.',
  restored: 'Back in your notes, with its questions, reels and progress.',
  exists: 'Already in your notes. Nothing changed.',
}

// Pick one or more PDFs; they upload one after another, each with its own status line.
export function UploadPanel({ folders }: { folders: string[] }) {
  const upload = useUploadNote()
  const input = useRef<HTMLInputElement>(null)
  const listId = useId()
  const [folder, setFolder] = useState('')
  const [rows, setRows] = useState<Row[]>([])
  const nextId = useRef(0)
  const busy = rows.some((r) => r.state === 'waiting' || r.state === 'sending' || r.state === 'checking')

  function set(id: number, row: Partial<Row> & Pick<Row, 'state'>) {
    setRows((all) => all.map((r) => (r.id === id ? ({ ...r, ...row } as Row) : r)))
  }

  async function start(files: File[]) {
    const queued = files.map((file) => ({ file, id: nextId.current++ }))
    setRows(queued.map(({ file, id }) => ({ id, name: file.name, state: 'waiting' })))
    for (const { file, id } of queued) {
      if (!file.name.toLowerCase().endsWith('.pdf')) {
        set(id, { state: 'failed', message: 'Only PDF files can be uploaded.' })
        continue
      }
      if (file.size > MAX_MB * 1024 * 1024) {
        set(id, { state: 'failed', message: `PDFs can be up to ${MAX_MB} MB.` })
        continue
      }
      set(id, { state: 'sending', progress: 0 })
      try {
        const result = await upload.mutateAsync({
          file,
          folder,
          // Once every byte is sent, the server still checks and stores the file.
          onProgress: (f) => set(id, f < 1 ? { state: 'sending', progress: f } : { state: 'checking' }),
        })
        set(id, { state: 'done', outcome: result.outcome })
      } catch (e) {
        set(id, { state: 'failed', message: e instanceof Error ? e.message : 'The upload failed.' })
      }
    }
  }

  const field = 'h-11 rounded-xl border border-rule bg-sheet px-3 text-[15px] text-graphite'
  return (
    <section aria-labelledby={`${listId}-title`} className="mt-6 rounded-[20px] border border-rule bg-sheet p-5 sm:px-7">
      <h2 id={`${listId}-title`} className="font-display text-[19px] font-semibold">
        Add PDFs
      </h2>
      <p className="mt-1 text-[14px] text-muted">
        Up to {MAX_MB} MB each. Uploading a PDF you removed brings back everything made from it.
      </p>
      <div className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-end">
        <label className="flex min-w-0 flex-1 flex-col gap-1">
          <span className="text-[13px] font-bold">Folder (optional)</span>
          <input
            type="text"
            value={folder}
            onChange={(e) => setFolder(e.target.value)}
            list={`${listId}-folders`}
            maxLength={200}
            placeholder="e.g. Tech"
            disabled={busy}
            className={`${field} w-full`}
          />
          <datalist id={`${listId}-folders`}>
            {folders.filter(Boolean).map((f) => (
              <option key={f} value={f} />
            ))}
          </datalist>
        </label>
        <input
          ref={input}
          type="file"
          accept="application/pdf,.pdf"
          multiple
          className="sr-only"
          tabIndex={-1}
          aria-hidden
          onChange={(e) => {
            const files = Array.from(e.target.files ?? [])
            e.target.value = '' // picking the same file again still fires onChange
            if (files.length) void start(files)
          }}
        />
        <button
          type="button"
          disabled={busy}
          onClick={() => input.current?.click()}
          className="inline-flex h-11 items-center justify-center gap-2 rounded-xl bg-ink px-5 font-display text-[16px] font-semibold text-on-ink transition hover:brightness-110 active:scale-[0.98] disabled:pointer-events-none disabled:opacity-50"
        >
          <UploadSimpleIcon weight="bold" className="size-5" aria-hidden />
          {busy ? 'Uploading…' : 'Upload PDFs'}
        </button>
      </div>

      {rows.length > 0 && (
        <ul aria-live="polite" className="mt-4 flex flex-col gap-2 border-t border-rule pt-4 text-[14px]">
          {rows.map((row) => (
            <li key={row.id} className="flex flex-col gap-1">
              <span className="font-bold break-words text-graphite">{row.name}</span>
              {row.state === 'waiting' && <span className="text-muted">Waiting…</span>}
              {row.state === 'sending' && (
                <div
                  role="progressbar"
                  aria-label={`Uploading ${row.name}`}
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-valuenow={Math.round(row.progress * 100)}
                  className="h-2 overflow-hidden rounded-full bg-rule"
                >
                  <div
                    className="h-full rounded-full bg-ink transition-[width] motion-reduce:transition-none"
                    style={{ width: `${Math.round(row.progress * 100)}%` }}
                  />
                </div>
              )}
              {row.state === 'checking' && <span className="text-muted">Checking and saving…</span>}
              {row.state === 'done' && <span className="text-ink">{outcomeText[row.outcome]}</span>}
              {row.state === 'failed' && <span className="text-pen">{row.message}</span>}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
