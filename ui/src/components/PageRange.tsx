import { useId } from 'react'

/** Pages the pipeline has handled for one content kind, drawn as a strip under the track. */
export interface Coverage {
  label: string
  ranges: [number, number][]
  pattern: 'stripes' | 'dots'
}

// Told apart by colour and texture: ink stripes for questions, indigo dots for reels.
const patterns = {
  stripes: 'bg-[repeating-linear-gradient(135deg,var(--ink)_0_2px,transparent_2px_4px)] opacity-60',
  dots: 'bg-[radial-gradient(circle,var(--reel)_1px,transparent_1.5px)] bg-[length:4px_4px]',
}

// Two native range inputs stacked on one track (keyboard and screen readers work as usual),
// plus number fields for exact pages. Under the track, one strip per content kind shows which
// pages the pipeline has already handled.
export function PageRange({
  pageCount,
  coverage,
  value: [from, to],
  disabled,
  onChange,
  onCommit,
}: {
  pageCount: number
  coverage: Coverage[]
  value: [number, number]
  disabled?: boolean
  onChange: (range: [number, number]) => void
  onCommit: (range: [number, number]) => void
}) {
  const id = useId()
  const pct = (page: number) => (pageCount <= 1 ? 0 : ((page - 1) / (pageCount - 1)) * 100)
  const clamp = (n: number) => Math.min(Math.max(Math.round(n) || 1, 1), pageCount)
  // A covered page spans half a step either side of its thumb position, so single pages still show.
  const edge = (page: number, side: -1 | 1) =>
    Math.min(Math.max(pct(page) + (side * 50) / Math.max(pageCount - 1, 1), 0), 100)

  function setFrom(n: number, commit = false) {
    const range: [number, number] = [Math.min(clamp(n), to), to]
    onChange(range)
    if (commit) onCommit(range)
  }
  function setTo(n: number, commit = false) {
    const range: [number, number] = [from, Math.max(clamp(n), from)]
    onChange(range)
    if (commit) onCommit(range)
  }
  const commitOnRelease = { onPointerUp: () => onCommit([from, to]), onKeyUp: () => onCommit([from, to]) }

  return (
    <fieldset disabled={disabled} className="disabled:opacity-50">
      <legend className="sr-only">Pages to use</legend>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <p className="font-display text-[17px] font-semibold">Pages</p>
        <div className="flex items-center gap-2 text-[15px]">
          <label htmlFor={`${id}-from`} className="text-muted">
            From
          </label>
          <PageInput id={`${id}-from`} value={from} max={pageCount} onCommit={(n) => setFrom(n, true)} />
          <label htmlFor={`${id}-to`} className="text-muted">
            to
          </label>
          <PageInput id={`${id}-to`} value={to} max={pageCount} onCommit={(n) => setTo(n, true)} />
        </div>
      </div>

      <div className="relative mt-3 h-11">
        <div className="absolute inset-x-[14px] top-1/2 h-2 -translate-y-1/2 overflow-hidden rounded-full bg-rule">
          <div className="absolute inset-y-0 bg-ink/80" style={{ left: `${pct(from)}%`, right: `${100 - pct(to)}%` }} />
        </div>
        <input
          type="range"
          aria-label="First page"
          min={1}
          max={pageCount}
          value={from}
          onChange={(e) => setFrom(Number(e.target.value))}
          {...commitOnRelease}
          className="page-range-thumb"
        />
        <input
          type="range"
          aria-label="Last page"
          min={1}
          max={pageCount}
          value={to}
          onChange={(e) => setTo(Number(e.target.value))}
          {...commitOnRelease}
          className="page-range-thumb"
        />
      </div>

      {coverage.length > 0 && (
        // Under the track, not on it, so neither the selection band nor the thumbs hide it.
        <div aria-hidden className="relative mx-[14px] mt-1 flex flex-col gap-[3px]">
          {coverage.map((c) => (
            <div key={c.label} className="relative h-1">
              {c.ranges.map(([first, last]) => (
                <div
                  key={first}
                  className={`absolute inset-y-0 rounded-full ${patterns[c.pattern]}`}
                  style={{ left: `${edge(first, -1)}%`, right: `${100 - edge(last, 1)}%` }}
                />
              ))}
            </div>
          ))}
        </div>
      )}

      <div className="mt-1.5 flex justify-between text-[13px] text-muted">
        <span>1</span>
        <span>{pageCount}</span>
      </div>
      {coverage.length > 0 && (
        <ul className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-[13px] text-muted">
          {coverage.map((c) => (
            <li key={c.label} className="flex items-center gap-1.5">
              <span aria-hidden className={`inline-block h-2 w-4 rounded-full ${patterns[c.pattern]}`} />
              {c.label}
            </li>
          ))}
        </ul>
      )}
    </fieldset>
  )
}

function PageInput({ id, value, max, onCommit }: { id: string; value: number; max: number; onCommit: (n: number) => void }) {
  return (
    <input
      id={id}
      // Re-mount when the slider moves so the field shows the current page.
      key={value}
      type="number"
      inputMode="numeric"
      min={1}
      max={max}
      defaultValue={value}
      onBlur={(e) => onCommit(Number(e.target.value))}
      onKeyDown={(e) => e.key === 'Enter' && e.currentTarget.blur()}
      className="h-11 w-[4.5rem] rounded-xl border border-rule bg-sheet px-2 text-center font-display text-[17px] font-semibold tabular-nums"
    />
  )
}
