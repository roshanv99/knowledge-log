import { InfoIcon, PlayIcon } from '@phosphor-icons/react'
import { useReducedMotion } from 'motion/react'
import { type ReactNode, type RefObject, useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router'

import { useReels, useSocialVideos } from '../../api/hooks'
import type { NoteReel } from '../../api/types'
import { ErrorState } from '../../components/ErrorState'
import { capitalize } from '../notes/pipelineText'
import { documentName, pageRange } from '../quiz/format'
import { FollowingFeed } from './FollowingFeed'
import { SwipeDeck } from './SwipeDeck'
import { WatchCounter } from './WatchCounter'

const INFO_KEY = 'kl.reels.info'

type Tab = 'notes' | 'following'

// Two reel feeds, switched with a pill at the top: reels made from the learner's own notes, and
// reels/shorts from accounts they follow (backend/social/). Each is one item per screen, swipe
// or scroll to the next, like Instagram and TikTok.
export function ReelsPage() {
  const [tab, setTab] = useState<Tab>('notes')
  return (
    <>
      <h1 className="sr-only">Reels</h1>
      <TabSwitcher tab={tab} onChange={setTab} />
      {tab === 'notes' ? <NotesTab /> : <FollowingTab />}
    </>
  )
}

function TabSwitcher({ tab, onChange }: { tab: Tab; onChange: (tab: Tab) => void }) {
  return (
    <div className="fixed inset-x-0 top-0 z-20 flex justify-center pt-[max(12px,env(safe-area-inset-top))] lg:left-[240px]">
      <div role="tablist" aria-label="Reels source" className="flex gap-1 rounded-full bg-black/45 p-1 backdrop-blur-sm">
        <TabButton active={tab === 'notes'} onClick={() => onChange('notes')}>
          My Notes
        </TabButton>
        <TabButton active={tab === 'following'} onClick={() => onChange('following')}>
          Following
        </TabButton>
      </div>
    </div>
  )
}

function TabButton({ active, onClick, children }: { active: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      onClick={onClick}
      className={`rounded-full px-4 py-1.5 text-[14px] font-bold whitespace-nowrap transition ${
        active ? 'bg-white text-black' : 'text-white/80 hover:text-white'
      }`}
    >
      {children}
    </button>
  )
}

function NotesTab() {
  const reels = useReels()

  if (reels.data && reels.data.reels.length > 0) return <Feed reels={reels.data.reels} />

  return (
    <div className="mx-auto max-w-[520px] px-5 pt-24 pb-10 sm:px-8 lg:pt-24">
      <h2 className="font-display text-[36px] leading-[1.05] font-semibold tracking-tight">Reels</h2>
      <p className="mt-2 max-w-[52ch] leading-relaxed text-muted">Short explainers made from your own notes.</p>

      {reels.isPending ? (
        <div className="mt-8 aspect-[9/16] animate-pulse rounded-[20px] border border-rule bg-sheet motion-reduce:animate-none" />
      ) : reels.isError ? (
        <div className="mt-8">
          <ErrorState error={reels.error} onRetry={() => reels.refetch()} />
        </div>
      ) : (
        <section className="mt-8 max-w-[52ch]">
          <h3 className="font-display text-[22px] font-semibold">No reels yet</h3>
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

function FollowingTab() {
  const videos = useSocialVideos()

  if (videos.data && videos.data.videos.length > 0) return <FollowingFeed videos={videos.data.videos} />

  return (
    <div className="mx-auto max-w-[520px] px-5 pt-24 pb-10 sm:px-8 lg:pt-24">
      <h2 className="font-display text-[36px] leading-[1.05] font-semibold tracking-tight">Following</h2>
      <p className="mt-2 max-w-[52ch] leading-relaxed text-muted">Reels and shorts from accounts you choose.</p>

      {videos.isPending ? (
        <div className="mt-8 aspect-[9/16] animate-pulse rounded-[20px] border border-rule bg-sheet motion-reduce:animate-none" />
      ) : videos.isError ? (
        <div className="mt-8">
          <ErrorState error={videos.error} onRetry={() => videos.refetch()} />
        </div>
      ) : (
        <section className="mt-8 max-w-[52ch]">
          <h3 className="font-display text-[22px] font-semibold">No accounts followed yet</h3>
          <p className="mt-2 leading-relaxed text-muted">
            Add YouTube or Instagram accounts in{' '}
            <Link to="/settings" className="font-bold text-ink underline underline-offset-2">
              Settings
            </Link>
            , then run the discovery sweep (<code className="font-code text-[14px]">kl social discover</code>) to
            bring in their latest reels and shorts.
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

// The My Notes feed: the SwipeDeck shell plus video-specific playback (IntersectionObserver
// play/pause) and the ⓘ details toggle, remembered on this device.
function Feed({ reels }: { reels: NoteReel[] }) {
  const scroller = useRef<HTMLOListElement>(null)
  const { register, onPlay } = useFeedPlayback(reels, scroller)
  const [info, setInfo] = useState(readInfoPreference)

  function toggleInfo() {
    const next = !info
    setInfo(next)
    try {
      window.localStorage.setItem(INFO_KEY, next ? 'shown' : 'hidden')
    } catch {
      // Storage can be unavailable (private mode); the toggle still works for this visit.
    }
  }

  return (
    <SwipeDeck
      items={reels}
      keyOf={(reel) => reel.id}
      ariaLabel="Reels from your notes"
      scrollerRef={scroller}
      announce={(reel, index, count) => `Reel ${index + 1} of ${count}: ${reel.title}`}
      renderItem={(reel, { index, count }) => (
        <Reel
          reel={reel}
          index={index}
          count={count}
          info={info}
          onToggleInfo={toggleInfo}
          videoRef={register}
          onPlay={() => onPlay(reel.id)}
        />
      )}
    />
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
    // The reel's frame: the full screen on a phone, a centred 9:16 card on wider screens.
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
  )
}
