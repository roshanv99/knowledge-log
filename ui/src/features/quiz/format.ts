import type { Attempt, Question, QuizSet } from '../../api/types'
import type { BubbleMark } from '../../components/Bubble'
import { answered, type QuizRun } from './run'

export function longDate(isoDate: string): string {
  return new Date(`${isoDate}T00:00:00`).toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long' })
}

export function neededToPass(passPct: number, total: number): number {
  return Math.ceil((passPct * total) / 100)
}

export function pageRange(pages: number[]): string {
  const min = Math.min(...pages)
  const max = Math.max(...pages)
  return min === max ? `page ${min}` : `pages ${min}–${max}`
}

export function documentName(filename: string): string {
  return filename.replace(/\.pdf$/i, '')
}

/** Topics covered by a set, in question order, with the pages they come from. */
export function topicsOf(questions: Question[]) {
  const topics = new Map<string, { title: string; document: string; pages: number[] }>()
  for (const q of questions) {
    const title = q.topic ?? 'Untitled topic'
    const entry = topics.get(title) ?? { title, document: q.document, pages: [] }
    entry.pages.push(...q.source_pages)
    topics.set(title, entry)
  }
  return [...topics.values()]
}

export function marksFromRun(run: QuizRun, quizSet: QuizSet): BubbleMark[] {
  const byId = new Map(quizSet.questions.map((q) => [q.id, q]))
  return run.order.map((id, i) => {
    const choice = run.choices[id]
    if (choice === undefined) return i === answered(run) ? 'current' : 'empty'
    return choice === byId.get(id)?.correct_index ? 'right' : 'wrong'
  })
}

export function marksFromAttempt(attempt: Attempt, quizSet: QuizSet): BubbleMark[] {
  const byId = new Map(quizSet.questions.map((q) => [q.id, q]))
  return attempt.answers.map((a) => (a.choice === byId.get(a.question_id)?.correct_index ? 'right' : 'wrong'))
}
