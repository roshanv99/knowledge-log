import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import { useEffect, useRef, useState } from 'react'

import { useRecordView } from '../../api/hooks'
import type { NoteReel } from '../../api/types'

/** A play-through counts as a watch once this share of the reel has actually been played. */
export const WATCHED_AT = 0.8
const RING_R = 18
const RING = 2 * Math.PI * RING_R
const BURST = 10

/**
 * Follows how much of the current play-through has really been watched: time only accrues while
 * the video plays forward, so skipping ahead doesn't count and seeking back doesn't double count.
 * Going back to the start begins a new play-through. Crossing WATCHED_AT counts one watch, once.
 */
function useWatchedShare(video: HTMLVideoElement | null, onWatched: () => void) {
  const [share, setShare] = useState(0)
  const [counted, setCounted] = useState(false)
  const state = useRef({ watched: 0, last: 0, counted: false })
  const watched = useRef(onWatched)
  useEffect(() => {
    watched.current = onWatched
  })

  useEffect(() => {
    if (!video) return
    const s = state.current
    const restart = () => {
      Object.assign(s, { watched: 0, counted: false })
      setShare(0)
      setCounted(false)
    }
    const onTime = () => {
      const t = video.currentTime
      const step = t - s.last
      if (t < 1 && s.last > 2) restart() // replayed from the start: a new play-through
      else if (!video.seeking && step > 0 && step <= 1.5 * Math.max(video.playbackRate, 1)) s.watched += step
      s.last = t
      if (!video.duration) return
      const next = Math.min(s.watched / video.duration, 1)
      setShare(next)
      if (next >= WATCHED_AT && !s.counted) {
        s.counted = true
        setCounted(true)
        watched.current()
      }
    }
    const onSeeked = () => {
      if (video.currentTime < 1 && s.last > 2) restart()
      s.last = video.currentTime
    }
    video.addEventListener('timeupdate', onTime)
    video.addEventListener('seeked', onSeeked)
    return () => {
      video.removeEventListener('timeupdate', onTime)
      video.removeEventListener('seeked', onSeeked)
    }
  }, [video])

  return { share, counted }
}

// Top-right corner of a reel: how many times it has been watched, inside a ring that fills as you
// watch. At 80% the ring turns green with a small burst, and the count goes up by one.
export function WatchCounter({ reel, video }: { reel: NoteReel; video: HTMLVideoElement | null }) {
  const record = useRecordView()
  const reduce = useReducedMotion()
  // Shown at once; dropped when the server answers, whose count then lands in the feed's cache.
  const [pending, setPending] = useState(0)
  const { share, counted } = useWatchedShare(video, () => {
    setPending((n) => n + 1)
    record.mutate(reel.id, { onSettled: () => setPending((n) => n - 1) })
  })
  const count = reel.views + pending
  const colour = counted ? 'var(--on-video-ink)' : 'rgb(255 255 255)'

  return (
    <div className="pointer-events-none absolute top-3 right-3 z-10">
      <p className="sr-only" aria-live="polite">
        {counted ? `Counted as watched. Watched ${count} ${count === 1 ? 'time' : 'times'}.` : ''}
      </p>
      <motion.div
        aria-hidden
        animate={counted && !reduce ? { scale: [1, 1.35, 0.95, 1] } : { scale: 1 }}
        transition={{ duration: 0.55, ease: 'easeOut' }}
        className="relative grid size-12 place-items-center rounded-full bg-black/45 backdrop-blur-sm"
      >
        <svg viewBox="0 0 44 44" className="absolute inset-0 size-full -rotate-90">
          <circle cx="22" cy="22" r={RING_R} fill="none" stroke="rgb(255 255 255 / 0.25)" strokeWidth="3" />
          <circle
            cx="22"
            cy="22"
            r={RING_R}
            fill="none"
            stroke={colour}
            strokeWidth="3"
            strokeLinecap="round"
            strokeDasharray={RING}
            strokeDashoffset={RING * (1 - share)}
            className="transition-[stroke] duration-300"
          />
        </svg>
        <span
          className="relative font-display text-[16px] leading-none font-semibold tabular-nums"
          style={{ color: counted ? 'var(--on-video-ink)' : 'white' }}
        >
          {count}
        </span>
        <AnimatePresence>
          {counted && !reduce && (
            <motion.span
              key="burst"
              className="absolute inset-0"
              initial={{ opacity: 1 }}
              animate={{ opacity: 0 }}
              transition={{ delay: 0.5, duration: 0.3 }}
            >
              {Array.from({ length: BURST }, (_, i) => {
                const angle = (i / BURST) * 2 * Math.PI
                return (
                  <motion.span
                    key={i}
                    className="absolute top-1/2 left-1/2 size-1.5 rounded-full"
                    style={{ backgroundColor: i % 2 ? 'var(--on-video-ink)' : 'white', marginLeft: -3, marginTop: -3 }}
                    // From the ring outwards, so the count in the middle stays readable.
                    initial={{ x: Math.cos(angle) * RING_R, y: Math.sin(angle) * RING_R, scale: 0.6 }}
                    animate={{ x: Math.cos(angle) * 36, y: Math.sin(angle) * 36, scale: [0.6, 1.2, 0.4] }}
                    transition={{ duration: 0.7, ease: 'easeOut' }}
                  />
                )
              })}
            </motion.span>
          )}
        </AnimatePresence>
      </motion.div>
    </div>
  )
}
