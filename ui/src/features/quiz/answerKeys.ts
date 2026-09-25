import { useEffect } from 'react'

export const LETTERS = ['A', 'B', 'C', 'D']

/** Keyboard: 1-4 or A-D picks an option, Enter moves on. */
export function useAnswerKeys(display: number[], choose: (stored: number) => void, next: () => void) {
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.metaKey || e.ctrlKey || e.altKey) return
      const key = e.key.toUpperCase()
      const pos = '1234'.includes(key) ? Number(key) - 1 : LETTERS.indexOf(key)
      if (pos >= 0 && pos < display.length) choose(display[pos])
      else if (e.key === 'Enter') next()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })
}
