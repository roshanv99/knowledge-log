// Shapes returned by the Django API (backend/quiz/serializers.py).

export type Difficulty = 'easy' | 'medium' | 'hard'

export interface Question {
  id: number
  stem: string
  options: string[]
  correct_index: number
  explanation: string
  source_pages: number[]
  difficulty: Difficulty
  topic: string | null
  document: string
}

export interface Answer {
  question_id: number
  /** Index into the question's stored `options` (not the shuffled display order). */
  choice: number
}

export interface Attempt {
  id: number
  correct: number
  total: number
  score_pct: number
  pass_pct: number
  passed: boolean
  answers: Answer[]
  created_at: string
}

export interface QuestionResult extends Answer {
  correct_index: number
  is_correct: boolean
}

export interface AttemptResult extends Attempt {
  results: QuestionResult[]
}

export interface QuizSet {
  id: number
  available_on: string
  passed: boolean
  questions: Question[]
  attempts: Attempt[]
}

export interface Today {
  quiz_set: QuizSet | null
  pass_pct: number
  /** Set when there is no quiz: nothing generated yet, nothing in scope, or every in-scope question used. */
  empty_reason: 'no_questions' | 'nothing_in_scope' | 'all_used' | null
}

export interface Settings {
  pass_pct: number
  questions_per_set: number
  /** The pipeline kill switch. */
  pipeline_enabled: boolean
  /** Off: runs start only from "Run now". On: the runner also starts one whenever work is waiting. */
  pipeline_auto: boolean
  max_tasks_per_run: number
  max_runs_per_day: number
  /** Total reels to make; 0 means no limit. */
  reel_limit: number
  /** Daily goals for the tracker on the Quiz page. */
  daily_questions_goal: number
  daily_reels_goal: number
}

export interface NoteScope {
  selected: boolean
  page_from: number
  page_to: number
  include_quiz: boolean
  include_reels: boolean
  /** Position in Manage notes (drag to reorder); the pipeline works through PDFs in this order. */
  priority: number
}

export type ContentKind = 'quiz' | 'reel'

/** What the pipeline has done for one content kind of one PDF (backend content/notes.py `progress`). */
export interface KindProgress {
  pages_in_range: number
  pages_done: number
  /** Handled pages across the whole PDF, as inclusive [first, last] ranges. */
  done_ranges: [number, number][]
  failed: { task_id: number; pages: [number, number]; error: string | null }[]
  active: { task_id: number; pages: [number, number]; stage: string | null; detail: string | null; since: string } | null
}

export interface Note {
  id: number
  filename: string
  /** The folder it was uploaded into ('' for none). */
  folder: string
  /** False once the PDF has been removed; its questions and reels stay. */
  available: boolean
  page_count: number
  /** Every page up to here has been read by the generation pipeline. */
  processed_to: number
  scope: NoteScope
  /** 0-based place in the pipeline order among stored PDFs; null for a removed one. */
  position: number | null
  progress: Record<ContentKind, KindProgress>
  questions: { total: number; in_scope: number }
  reels: { total: number; in_scope: number }
}

export interface NotesList {
  /** One page of PDFs, in pipeline order, after filtering. */
  notes: Note[]
  /** How many PDFs match the filters (across all pages). */
  total: number
  page: number
  page_size: number
  /** Folders that hold PDFs, for the folder filter. */
  folders: string[]
  /** Across every PDF, ignoring filters. */
  summary: { documents: number; selected: number; questions_ready: number }
}

export interface NotesQuery {
  page: number
  q: string
  folder: string
  selected: 'all' | 'yes' | 'no'
}

/** How saving a scope change affected today's quiz (null when the change can't affect it). */
export type TodaysQuizOutcome = 'rebuilt' | 'started' | 'empty' | null

export interface ScopeUpdate {
  note: Note
  todays_quiz: TodaysQuizOutcome
}

export interface NoteItems {
  questions: {
    id: number
    stem: string
    difficulty: Difficulty
    topic: string | null
    source_pages: number[]
    quiz_date: string | null
  }[]
  reels: {
    id: number
    title: string
    kind: string
    topic: string | null
    source_pages: number[]
    duration_s: number | null
  }[]
}

// The pipeline (backend/pipeline/views.py).

export interface PipelineTask {
  id: number
  kind: ContentKind
  document_id: number
  document: string
  pages: [number, number]
  status: string
  stage: string | null
  detail: string | null
  attempts: number
  error: string | null
  since: string | null
  finished_at: string | null
}

export interface PipelineRun {
  id: number
  kind: ContentKind
  runner: string
  started_at: string
  last_seen_at: string
  finished_at: string | null
  stop_reason: string | null
  tasks_done: number
  questions_made: number
  reels_made: number
}

export interface PipelineStatus {
  active_runs: (PipelineRun & { tasks: PipelineTask[] })[]
  recent_runs: PipelineRun[]
  failed_tasks: PipelineTask[]
  open_requests: { id: number; kind: ContentKind; created_at: string }[]
  runners: { name: string; kind: string; last_seen_at: string | null }[]
  reels: { made: number; limit: number }
}

// My Notes reels (backend content/views.py `reels`).

export interface NoteReel {
  id: number
  title: string
  key_point: string | null
  kind: string
  duration_s: number | null
  document: string
  topic: string | null
  source_pages: number[]
  /** Same-origin URL of the MP4 (served with byte ranges). */
  url: string
  /** A still of the first beat, or null for reels made before posters existed. */
  poster: string | null
  created_at: string
  /** Times the learner watched at least 80% of it. */
  views: number
}

// The daily tracker (backend quiz/activity.py).

export interface ActivityDay {
  /** YYYY-MM-DD in the learner's time zone. */
  date: string
  questions: number
  reels: number
  /** The goals in force that day. */
  questions_goal: number
  reels_goal: number
  questions_met: boolean
  reels_met: boolean
}

export interface ActivitySummary {
  today: string
  goals: { questions: number; reels: number }
  today_progress: { questions: number; reels: number }
  streaks: { questions: number; reels: number }
  /** Only days with activity; others are empty. */
  days: ActivityDay[]
}

/** added: a new PDF. restored: a removed PDF is back, with its progress. exists: already there. */
export type UploadOutcome = 'added' | 'restored' | 'exists'

export interface UploadResult {
  note: Note
  outcome: UploadOutcome
}
