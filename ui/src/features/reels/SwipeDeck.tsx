import { CaretDownIcon, CaretUpIcon } from '@phosphor-icons/react'
import { useReducedMotion } from 'motion/react'
import { type ReactNode, type RefObject, useCallback, useEffect, useRef, useState } from 'react'

const WHEEL_STEP_PX = 40 // scroll this far in one gesture to move an item
const WHEEL_QUIET_MS = 220 // a gesture ends after this long without wheel events

/**
 * One item per screen, snapping as you swipe (phones) or scroll (trackpad, mouse wheel), with
 * ↑/↓ buttons on wider screens and arrow/J-K keyboard navigation. The scrolling/gesture shell for
 * both reel feeds (ReelsPage's My Notes feed and FollowingFeed); what's inside each screen is up
 * to `renderItem` — a <video> for one, an <iframe> embed for the other.
 */
export function SwipeDeck<T>({
  items,
  keyOf,
  ariaLabel,
  scrollerRef,
  onCurrentChange,
  renderItem,
  announce,
}: {
  items: T[]
  keyOf: (item: T) => number | string
  ariaLabel: string
  scrollerRef: RefObject<HTMLOListElement | null>
  onCurrentChange?: (index: number) => void
  renderItem: (item: T, ctx: { index: number; count: number; active: boolean }) => ReactNode
  announce?: (item: T, index: number, count: number) => string
}) {
  const reduce = useReducedMotion()
  const [current, setCurrent] = useState(0)

  // Every item is exactly one screen tall, so the one in view is the scroll position over the height.
  function onScroll() {
    const el = scrollerRef.current
    if (!el) return
    const next = Math.round(el.scrollTop / Math.max(el.clientHeight, 1))
    setCurrent(next)
    onCurrentChange?.(next)
  }

  const go = useCallback(
    (to: number) => {
      const el = scrollerRef.current
      if (!el) return
      const target = Math.min(Math.max(to, 0), items.length - 1)
      el.scrollTo({ top: target * el.clientHeight, behavior: reduce ? 'auto' : 'smooth' })
    },
    [items.length, reduce, scrollerRef],
  )

  const goRef = useRef(go)
  const currentRef = useRef(current)
  useEffect(() => {
    goRef.current = go
    currentRef.current = current
  })

  // Wheel and trackpad: one gesture moves one item, as on TikTok and Instagram web. A trackpad sends
  // a burst of small deltas with a momentum tail, so after a move the rest of that gesture is
  // ignored until it goes quiet. (Touch swipes use the browser's own snapping.)
  useEffect(() => {
    const el = scrollerRef.current
    if (!el) return
    let sum = 0
    let locked = false
    let quiet: ReturnType<typeof setTimeout> | undefined
    function onWheel(e: WheelEvent) {
      if (e.ctrlKey || Math.abs(e.deltaX) > Math.abs(e.deltaY)) return // pinch-zoom, sideways scroll
      e.preventDefault()
      clearTimeout(quiet)
      quiet = setTimeout(() => {
        locked = false
        sum = 0
      }, WHEEL_QUIET_MS)
      if (locked) return
      sum += e.deltaMode === 1 ? e.deltaY * 16 : e.deltaY // lines to pixels
      if (Math.abs(sum) >= WHEEL_STEP_PX) {
        locked = true
        goRef.current(currentRef.current + Math.sign(sum))
        sum = 0
      }
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => {
      el.removeEventListener('wheel', onWheel)
      clearTimeout(quiet)
    }
  }, [scrollerRef])

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.metaKey || e.ctrlKey || e.altKey) return
      const target = e.target as HTMLElement | null
      if (target && /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName)) return
      const by = { ArrowDown: 1, j: 1, PageDown: 1, ArrowUp: -1, k: -1, PageUp: -1 }[e.key]
      if (by === undefined) return
      e.preventDefault()
      go(current + by)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [current, go])

  return (
    // Fills the space beside the side rail (desktop) or above the tab bar (phones).
    <div className="fixed inset-x-0 top-0 bottom-[calc(64px+env(safe-area-inset-bottom))] bg-black lg:bottom-0 lg:left-[240px]">
      <ol
        ref={scrollerRef}
        onScroll={onScroll}
        aria-label={ariaLabel}
        className="h-full snap-y snap-mandatory overflow-y-auto overscroll-contain [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
      >
        {items.map((item, i) => (
          <li key={keyOf(item)} className="flex h-full snap-start snap-always items-center justify-center sm:py-4">
            {renderItem(item, { index: i, count: items.length, active: i === current })}
          </li>
        ))}
      </ol>

      {/* Wider screens: previous / next beside the item. Swipe and scroll still work. */}
      <div className="absolute top-1/2 right-4 hidden -translate-y-1/2 flex-col gap-3 sm:flex lg:right-8">
        <NavButton label="Previous" disabled={current <= 0} onClick={() => go(current - 1)}>
          <CaretUpIcon weight="bold" className="size-6" aria-hidden />
        </NavButton>
        <NavButton label="Next" disabled={current >= items.length - 1} onClick={() => go(current + 1)}>
          <CaretDownIcon weight="bold" className="size-6" aria-hidden />
        </NavButton>
      </div>
      {announce && items[current] && (
        <p className="sr-only" aria-live="polite">
          {announce(items[current], current, items.length)}
        </p>
      )}
    </div>
  )
}

function NavButton({
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
      title={label}
      disabled={disabled}
      onClick={onClick}
      className="grid size-12 place-items-center rounded-full bg-white/15 text-white backdrop-blur-sm transition hover:bg-white/25 active:scale-95 disabled:pointer-events-none disabled:opacity-30"
    >
      {children}
    </button>
  )
}
