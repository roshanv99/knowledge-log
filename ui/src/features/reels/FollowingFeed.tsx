import { PlayIcon } from '@phosphor-icons/react'
import { useEffect, useRef } from 'react'

import { useRecordSocialView } from '../../api/hooks'
import type { SocialVideo } from '../../api/types'
import { SwipeDeck } from './SwipeDeck'

// How long a Following item has to stay in view before it counts as watched. There's no
// timeupdate-style signal from a cross-origin embed (see WatchCounter for the My Notes
// equivalent), so this is a dwell timer instead of "80% actually played".
const DWELL_MS = 4000

// Reels/shorts from accounts the learner follows, one per screen like the My Notes feed. Each
// screen embeds the video through its platform's own public embed (youtube-nocookie.com, or
// Instagram's tokenless /embed) rather than downloading or re-hosting it.
export function FollowingFeed({ videos }: { videos: SocialVideo[] }) {
  const scroller = useRef<HTMLOListElement>(null)
  return (
    <SwipeDeck
      items={videos}
      keyOf={(video) => video.id}
      ariaLabel="Reels from accounts you follow"
      scrollerRef={scroller}
      announce={(video, index, count) => `Video ${index + 1} of ${count}: ${video.title || video.account_handle}`}
      renderItem={(video, { active }) => <FollowingItem video={video} active={active} />}
    />
  )
}

/** Starts a watch on this item once it's been the active screen for DWELL_MS, at most once. */
function useDwellView(video: SocialVideo, active: boolean) {
  const record = useRecordSocialView()
  const mutate = useRef(record.mutate)
  const counted = useRef(false)
  useEffect(() => {
    mutate.current = record.mutate
  })
  useEffect(() => {
    if (!active || counted.current) return
    const timer = setTimeout(() => {
      counted.current = true
      mutate.current(video.id)
    }, DWELL_MS)
    return () => clearTimeout(timer)
  }, [active, video.id])
}

function FollowingItem({ video, active }: { video: SocialVideo; active: boolean }) {
  useDwellView(video, active)
  // Mounted only while active: this is both the play/pause control (an unmounted iframe can't
  // keep playing off-screen) and how YouTube's autoplay param gets a fresh start each time.
  const src = active
    ? `${video.embed_url}${video.embed_url.includes('?') ? '&' : '?'}autoplay=1&mute=1&playsinline=1`
    : undefined

  return (
    <div className="relative h-full w-full bg-black sm:aspect-[9/16] sm:w-auto sm:max-w-full sm:overflow-hidden sm:rounded-2xl">
      {src ? (
        <iframe
          src={src}
          title={video.title || `${video.platform} reel from ${video.account_handle}`}
          allow="autoplay; encrypted-media; picture-in-picture"
          allowFullScreen
          className="h-full w-full border-0"
        />
      ) : (
        <div className="grid h-full w-full place-items-center text-white/30">
          <PlayIcon weight="fill" className="size-10" aria-hidden />
        </div>
      )}

      <div className="pointer-events-none absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/85 via-black/55 to-transparent px-4 pt-16 pb-5 text-white">
        <p className="text-[13px] font-bold tracking-wide text-white/70 uppercase">
          @{video.account_handle} · {video.platform}
        </p>
        {video.title && (
          <h2 className="mt-1 line-clamp-3 font-display text-[18px] leading-snug font-semibold [text-shadow:0_1px_2px_rgb(0_0_0/0.5)]">
            {video.title}
          </h2>
        )}
      </div>

      <div
        aria-hidden
        className="pointer-events-none absolute top-3 right-3 z-10 grid size-12 place-items-center rounded-full bg-black/45 text-white backdrop-blur-sm"
      >
        <span className="font-display text-[16px] leading-none font-semibold tabular-nums">{video.views}</span>
      </div>
    </div>
  )
}
