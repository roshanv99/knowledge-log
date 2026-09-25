import { CaretDownIcon, CaretUpIcon, InfoIcon, PlayIcon } from '@phosphor-icons/react'
import { useReducedMotion } from 'motion/react'
import { type ReactNode, type RefObject, useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router'

import { useReels } from '../../api/hooks'
import type { NoteReel } from '../../api/types'
import { ErrorState } from '../../components/ErrorState'
import { capitalize } from '../notes/pipelineText'
import { documentName, pageRange } from '../quiz/format'
import { WatchCounter } from './WatchCounter'

const INFO_KEY = 'kl.reels.info'
const WHEEL_STEP_PX = 40 // scroll this far in one gesture to move a reel
const WHEEL_QUIET_MS = 220 // a gesture ends after this long without wheel events

// Reels made from the learner's notes, newest first, one per screen: swipe or scroll to the next,
// like Instagram and TikTok. Only reels whose pages are in the current Manage notes scope appear.
// Following (YouTube/Instagram) arrives in a later phase.
export function ReelsPage() {
  const reels = useReels()

  if (reels.data && reels.data.reels.length > 0) {
    return (
      <>
        <h1 className="sr-only">Reels</h1>
        <Feed reels={reels.data.reels} />
      </>
    )
  }
  return (
    <div className="mx-auto max-w-[520px] px-5 pt-8 pb-10 sm:px-8 lg:pt-14">
      <h1 className="font-display text-[36px] leading-[1.05] font-semibold tracking-tight">Reels</h1>
      <p className="mt-2 max-w-[52ch] leading-relaxed text-muted">Short explainers made from your own notes.</p>

      {reels.isPending ? (
        <div className="mt-8 aspect-[9/16] animate-pulse rounded-[20px] border border-rule bg-sheet motion-reduce:animate-none" />
      ) : reels.isError ? (
        <div className="mt-8">
          <ErrorState error={reels.error} onRetry={() => reels.refetch()} />
        </div>
      ) : (
        <section className="mt-8 max-w-[52ch]">
          <h2 className="font-display text-[22px] font-semibold">No reels yet</h2>
          <p className="mt-2 leading-relaxed text-muted">
            Reels are made from your notes by the reel pipeline (start it with /reel-generation in Claude Code). They
            only show here while their pages are selected in{' '}
            <Link to="/notes" className="font-bold text-ink underline underline-offset-2">
              Manage notes
            </Link>
            .
          </p>
        </section>
      )}
    </div>
  )
}

function details(reel: NoteReel): string {
  return `${documentName(reel.document)} · ${capitalize(pageRange(reel.source_pages))}${
    reel.duration_s ? ` · ${Math.round(reel.duration_s)} s` : ''
  }`
}

/**
 * Plays the reel in view and pauses the rest. Once the learner has started one reel, scrolling to
 * the next plays it (not with reduced motion). `root` is the scrolling element.
 */
function useFeedPlayback(reels: NoteReel[], root: RefObject<HTMLElement | null>) {
  const videos = useRef(new Map<number, HTMLVideoElement>())
  const watching = useRef(false)
  const reduce = useReducedMotion()

  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          const video = entry.target as HTMLVideoElement
          if (!entry.isIntersecting) video.pause()
          else if (watching.current && !reduce) void video.play().catch(() => {})
        }
      },
      { root: root.current, threshold: 0.7 },
    )
    videos.current.forEach((v) => observer.observe(v))
    return () => observer.disconnect()
  }, [reels, reduce, root])

  return {
    register: (id: number) => (el: HTMLVideoElement | null) => {
      if (el) videos.current.set(id, el)
      else videos.current.delete(id)
    },
    onPlay: (id: number) => {
      watching.current = true
      videos.current.forEach((v, other) => other !== id && v.pause())
    },
  }
}

/**
 * The reel's <video> element as state (for the watch counter) plus a stable ref callback that also
 * registers it with the feed. Stable matters: an inline ref callback re-runs on every render, and
 * setting state from it would render again, forever.
 */
function useVideoElement(id: number, register: (id: number) => (el: HTMLVideoElement | null) => void) {
  const [element, setElement] = useState<HTMLVideoElement | null>(null)
  const registerRef = useRef(register)
  useEffect(() => {
    registerRef.current = register
  })
  const ref = useCallback(
    (el: HTMLVideoElement | null) => {
      setElement(el)
      registerRef.current(id)(el)
    },
    [id],
  )
  return [element, ref] as const
}

function readInfoPreference(): boolean {
  try {
    return window.localStorage.getItem(INFO_KEY) !== 'hidden'
  } catch {
    return true
  }
}

// One reel per screen, snapping as you swipe (phones) or scroll (trackpad, mouse wheel). On wider
// screens each reel is a centred 9:16 frame with ↑/↓ buttons beside it, and the arrow keys (or J/K)
// move between reels too. The details overlay the video; ⓘ shows or hides them for every reel
// (remembered on this device).
function Feed({ reels }: { reels: NoteReel[] }) {
  const scroller = useRef<HTMLOListElement>(null)
  const { register, onPlay } = useFeedPlayback(reels, scroller)
  const reduce = useReducedMotion()
  const [info, setInfo] = useState(readInfoPreference)
  const [current, setCurrent] = useState(0)

  function toggleInfo() {
    const next = !info
    setInfo(next)
    try {
      window.localStorage.setItem(INFO_KEY, next ? 'shown' : 'hidden')
    } catch {
      // Storage can be unavailable (private mode); the toggle still works for this visit.
    }
  }

  // Every reel is exactly one screen tall, so the one in view is the scroll position over the height.
  function onScroll() {
    const el = scroller.current
    if (el) setCurrent(Math.round(el.scrollTop / Math.max(el.clientHeight, 1)))
  }

  const go = useCallback(
    (to: number) => {
      const el = scroller.current
      if (!el) return
      const target = Math.min(Math.max(to, 0), reels.length - 1)
      el.scrollTo({ top: target * el.clientHeight, behavior: reduce ? 'auto' : 'smooth' })
    },
    [reels.length, reduce],
  )

  const goRef = useRef(go)
  const currentRef = useRef(current)
  useEffect(() => {
    goRef.current = go
    currentRef.current = current
  })

  // Wheel and trackpad: one gesture moves one reel, as on TikTok and Instagram web. A trackpad sends
  // a burst of small deltas with a momentum tail, so after a move the rest of that gesture is
  // ignored until it goes quiet. (Touch swipes use the browser's own snapping.)
  useEffect(() => {
    const el = scroller.current
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
  }, [])

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
        ref={scroller}
        onScroll={onScroll}
        aria-label="Reels from your notes"
        className="h-full snap-y snap-mandatory overflow-y-auto overscroll-contain [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
      >
        {reels.map((reel, i) => (
          <Reel
            key={reel.id}
            reel={reel}
            index={i}
            count={reels.length}
            info={info}
            onToggleInfo={toggleInfo}
            videoRef={register}
            onPlay={() => onPlay(reel.id)}
          />
        ))}
      </ol>

      {/* Wider screens: previous / next beside the reel. Swipe and scroll still work. */}
      <div className="absolute top-1/2 right-4 hidden -translate-y-1/2 flex-col gap-3 sm:flex lg:right-8">
        <NavButton label="Previous reel" disabled={current <= 0} onClick={() => go(current - 1)}>
          <CaretUpIcon weight="bold" className="size-6" aria-hidden />
        </NavButton>
        <NavButton label="Next reel" disabled={current >= reels.length - 1} onClick={() => go(current + 1)}>
          <CaretDownIcon weight="bold" className="size-6" aria-hidden />
        </NavButton>
      </div>
      <p className="sr-only" aria-live="polite">
        Reel {current + 1} of {reels.length}: {reels[current]?.title}
      </p>
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

function Reel({
  reel,
  index,
  count,
  info,
  onToggleInfo,
  videoRef,
  onPlay,
}: {
  reel: NoteReel
  index: number
  count: number
  info: boolean
  onToggleInfo: () => void
  videoRef: (id: number) => (el: HTMLVideoElement | null) => void
  onPlay: () => void
}) {
  const [video, ref] = useVideoElement(reel.id, videoRef)
  const [playing, setPlaying] = useState(false)
  const [progress, setProgress] = useState(0)
  const infoId = `reel-info-${reel.id}`

  function togglePlay() {
    if (!video) return
    if (video.paused) void video.play().catch(() => {})
    else video.pause()
  }

  return (
    <li className="flex h-full snap-start snap-always items-center justify-center sm:py-4">
      {/* The reel's frame: the full screen on a phone, a centred 9:16 card on wider screens. */}
      <div className="relative h-full w-full sm:aspect-[9/16] sm:w-auto sm:max-w-full sm:overflow-hidden sm:rounded-2xl">
        <video
          ref={ref}
          src={reel.url}
          poster={reel.poster ?? undefined}
          playsInline
          preload={index < 2 ? 'metadata' : 'none'}
          onPlay={() => {
            setPlaying(true)
            onPlay()
          }}
          onPause={() => setPlaying(false)}
          onEnded={() => setPlaying(false)}
          onTimeUpdate={(e) => {
            const v = e.currentTarget
            setProgress(v.duration ? v.currentTime / v.duration : 0)
          }}
          aria-hidden
          className="h-full w-full bg-black object-contain"
        />

        <WatchCounter reel={reel} video={video} />

        {/* The whole reel is the play/pause control. */}
        <button
          type="button"
          onClick={togglePlay}
          aria-label={`${playing ? 'Pause' : 'Play'} ${reel.title}, reel ${index + 1} of ${count}`}
          className="absolute inset-0 grid place-items-center focus-visible:outline-offset-[-4px]"
        >
          {!playing && (
            <span aria-hidden className="grid size-16 place-items-center rounded-full bg-black/45 text-white backdrop-blur-sm">
              <PlayIcon weight="fill" className="size-8 translate-x-0.5" />
            </span>
          )}
        </button>

        {info && (
          <div
            id={infoId}
            className="pointer-events-none absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/85 via-black/55 to-transparent px-4 pt-16 pr-16 pb-5 text-white"
          >
            <h2 className="font-display text-[22px] leading-tight font-semibold [text-shadow:0_1px_2px_rgb(0_0_0/0.5)]">
              {reel.title}
            </h2>
            {reel.key_point && <p className="mt-1 line-clamp-3 text-[15px] leading-snug text-white/90">{reel.key_point}</p>}
            <p className="mt-1.5 text-[13px] text-white/75">{details(reel)}</p>
          </div>
        )}

        <button
          type="button"
          onClick={onToggleInfo}
          aria-pressed={info}
          aria-controls={info ? infoId : undefined}
          aria-label={info ? 'Hide details' : 'Show details'}
          className={`absolute right-3 bottom-4 grid size-11 place-items-center rounded-full backdrop-blur-sm transition-colors ${
            info ? 'bg-white text-black' : 'bg-black/45 text-white'
          }`}
        >
          <InfoIcon weight="bold" className="size-6" aria-hidden />
        </button>

        <div aria-hidden className="absolute inset-x-0 bottom-0 h-[3px] bg-white/20">
          <div className="h-full bg-white" style={{ width: `${progress * 100}%` }} />
        </div>
      </div>
    </li>
  )
}
