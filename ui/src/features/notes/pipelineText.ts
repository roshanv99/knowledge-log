import { useEffect, useState } from 'react'

import type { ContentKind } from '../../api/types'

const noun: Record<ContentKind, string> = { quiz: 'questions', reel: 'reels' }

export function pagesText([first, last]: [number, number]): string {
  return first === last ? `page ${first}` : `pages ${first}–${last}`
}

export function capitalize(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1)
}

/** "Writing questions for pages 29–32, round 2 of 3" / "Animating pages 33–36, scene fix 1 of 3" */
export function activityText(kind: ContentKind, stage: string | null, pages: [number, number], detail: string | null) {
  const where = pagesText(pages)
  const doing: Record<string, string> = {
    read: `Reading ${where}`,
    write: `Writing ${noun[kind]} for ${where}`,
    critique: `Reviewing ${noun[kind]} for ${where}`,
    script: `Writing the reel script for ${where}`,
    script_review: `Reviewing the reel script for ${where}`,
    tts: `Recording narration for ${where}`,
    scene: `Animating ${where}`,
    render: `Rendering the reel for ${where}`,
    visual: `Checking the reel for ${where}`,
  }
  const text = (stage && doing[stage]) || `Starting on ${where}`
  return detail ? `${text}, ${detail}` : text
}

const reasons: Record<string, string> = {
  range_done: 'everything selected is done',
  nothing_selected: 'nothing was selected',
  all_failed: 'only failed pages were left',
  run_cap: 'it reached its task limit',
  disabled: 'the pipeline was switched off',
  reel_limit: 'the reel limit was reached',
  usage_limit: 'the Claude usage limit was reached',
  abandoned: 'the runner stopped responding',
  interrupted: 'it was interrupted',
  closed_by_server: 'the server closed it',
  page_budget_done: 'it used its page budget',
  stopped: 'it was stopped',
}

export function stopReasonText(reason: string | null): string {
  if (!reason) return 'unknown'
  return reasons[reason] ?? reason.replaceAll('_', ' ')
}

export function ago(iso: string, now: number): string {
  const minutes = Math.round((now - new Date(iso).getTime()) / 60000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes} min ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours} h ago`
  const days = Math.round(hours / 24)
  return `${days} ${days === 1 ? 'day' : 'days'} ago`
}

export function clock(iso: string): string {
  return new Date(iso).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
}

/** The current time, refreshed every `everyMs`, so "3 min ago" labels stay honest. */
export function useNow(everyMs = 30_000): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), everyMs)
    return () => clearInterval(timer)
  }, [everyMs])
  return now
}
