// An in-progress pass through a quiz set: shuffled order, answers so far, and whether the
// current answer has been revealed. Saved to sessionStorage so switching apps mid-quiz
// on a phone doesn't lose progress.

import type { Answer, QuizSet } from '../../api/types'

export interface QuizRun {
  setId: number
  /** Question ids in the order they are asked. */
  order: number[]
  /** Per question: display position -> index into the stored options. */
  optionOrder: Record<number, number[]>
  index: number
  /** Per question: chosen index into the stored options. */
  choices: Record<number, number>
}

function shuffled<T>(items: T[]): T[] {
  const out = [...items]
  for (let i = out.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1))
    ;[out[i], out[j]] = [out[j], out[i]]
  }
  return out
}

export function newRun(quizSet: QuizSet): QuizRun {
  return {
    setId: quizSet.id,
    order: shuffled(quizSet.questions.map((q) => q.id)),
    optionOrder: Object.fromEntries(quizSet.questions.map((q) => [q.id, shuffled(q.options.map((_, i) => i))])),
    index: 0,
    choices: {},
  }
}

export function answered(run: QuizRun): number {
  return Object.keys(run.choices).length
}

export function toAnswers(run: QuizRun): Answer[] {
  return run.order.map((id) => ({ question_id: id, choice: run.choices[id] }))
}

const storageKey = (setId: number) => `kl.quiz-run.${setId}`

export function loadRun(quizSet: QuizSet): QuizRun | null {
  try {
    const raw = sessionStorage.getItem(storageKey(quizSet.id))
    if (!raw) return null
    const run = JSON.parse(raw) as QuizRun
    const ids = new Set(quizSet.questions.map((q) => q.id))
    // Discard a saved run if the set's questions changed underneath it.
    if (run.order.length !== ids.size || !run.order.every((id) => ids.has(id))) return null
    return run
  } catch {
    return null
  }
}

export function saveRun(run: QuizRun) {
  try {
    sessionStorage.setItem(storageKey(run.setId), JSON.stringify(run))
  } catch {
    // Storage unavailable (private mode, quota): the run still works in memory.
  }
}

export function clearRun(setId: number) {
  try {
    sessionStorage.removeItem(storageKey(setId))
  } catch {
    // Nothing to clear.
  }
}
