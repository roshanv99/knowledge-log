// Plain fetch client with no React dependency, so a future mobile app can reuse it.

import type {
  ActivitySummary,
  Answer,
  AttemptResult,
  NoteItems,
  NoteReel,
  NoteScope,
  NotesList,
  NotesQuery,
  PipelineStatus,
  PipelineTask,
  Question,
  ScopeUpdate,
  Settings,
  Today,
  UploadResult,
} from './types'

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

export function createApi(baseUrl: string) {
  async function request<T>(path: string, init?: RequestInit): Promise<T> {
    let response: Response
    try {
      response = await fetch(`${baseUrl}${path}`, {
        ...init,
        headers: { 'Content-Type': 'application/json', ...init?.headers },
      })
    } catch {
      throw new ApiError(0, 'The quiz server is not reachable.')
    }
    const body = await response.json().catch(() => null)
    if (!response.ok) {
      const detail = body && typeof body.detail === 'string' ? body.detail : `Request failed (${response.status}).`
      throw new ApiError(response.status, detail)
    }
    return body as T
  }

  // XMLHttpRequest rather than fetch: fetch can't report upload progress.
  function uploadNote(file: File, folder: string, onProgress?: (fraction: number) => void): Promise<UploadResult> {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest()
      xhr.open('PUT', `${baseUrl}/notes/upload?${new URLSearchParams({ filename: file.name, folder })}`)
      xhr.setRequestHeader('Content-Type', 'application/pdf')
      xhr.responseType = 'json'
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) onProgress?.(e.loaded / e.total)
      }
      xhr.onload = () => {
        const body = xhr.response
        if (xhr.status >= 200 && xhr.status < 300 && body) resolve(body as UploadResult)
        else if (xhr.status === 413 && !(body && typeof body.detail === 'string'))
          reject(new ApiError(413, 'This PDF is too large to upload.'))
        else
          reject(
            new ApiError(
              xhr.status,
              body && typeof body.detail === 'string' ? body.detail : `Upload failed (${xhr.status}).`,
            ),
          )
      }
      xhr.onerror = () =>
        reject(new ApiError(0, "The upload didn't reach the server. Check your connection and try again."))
      xhr.send(file)
    })
  }

  return {
    today: () => request<Today>('/quiz/today'),
    practice: (exclude: number[]) =>
      request<{ question: Question | null; pool: number }>(`/quiz/practice?exclude=${exclude.join(',')}`),
    submitAttempt: (setId: number, answers: Answer[]) =>
      request<AttemptResult>(`/quiz/sets/${setId}/attempts`, {
        method: 'POST',
        body: JSON.stringify({ answers }),
      }),
    settings: () => request<Settings>('/settings'),
    activity: (days: number) => request<ActivitySummary>(`/activity?days=${days}`),
    updateSettings: (patch: Partial<Settings>) =>
      request<Settings>('/settings', { method: 'PUT', body: JSON.stringify(patch) }),
    notes: ({ page, q, folder, selected }: NotesQuery, pageSize = 20) =>
      request<NotesList>(
        `/notes?${new URLSearchParams({ page: String(page), page_size: String(pageSize), q, folder, selected })}`,
      ),
    updateScope: (noteId: number, patch: Partial<NoteScope>) =>
      request<ScopeUpdate>(`/notes/${noteId}`, { method: 'PATCH', body: JSON.stringify(patch) }),
    noteItems: (noteId: number) => request<NoteItems>(`/notes/${noteId}/items`),
    uploadNote,
    removeNoteFile: (noteId: number) => request<null>(`/notes/${noteId}/file`, { method: 'DELETE' }),
    moveNote: (noteId: number, position: number) =>
      request<{ id: number; position: number }>(`/notes/${noteId}/position`, {
        method: 'PUT',
        body: JSON.stringify({ position }),
      }),
    pipelineStatus: () => request<PipelineStatus>('/pipeline/status'),
    reels: () => request<{ reels: NoteReel[] }>('/reels'),
    recordView: (reelId: number) =>
      request<{ views: number; counted: boolean }>(`/reels/${reelId}/views`, { method: 'POST' }),
    retryTask: (taskId: number) => request<PipelineTask>(`/pipeline/tasks/${taskId}/retry`, { method: 'POST' }),
  }
}

export const api = createApi(import.meta.env.VITE_API_BASE ?? '/api')
