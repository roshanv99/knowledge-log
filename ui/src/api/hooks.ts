import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from './client'
import type {
  Answer,
  Note,
  NoteReel,
  NoteScope,
  NotesList,
  NotesQuery,
  PipelineStatus,
  Settings,
} from './types'

const keys = {
  today: ['quiz', 'today'] as const,
  settings: ['settings'] as const,
  notes: ['notes'] as const,
  notesList: (query: NotesQuery) => ['notes', 'list', query] as const,
  noteItems: (id: number) => ['notes', id, 'items'] as const,
  pipeline: ['pipeline', 'status'] as const,
  reels: ['reels'] as const,
  activity: ['activity'] as const,
}

// Poll only while the pipeline is doing something (or about to): a run is active or requested.
const LIVE_POLL_MS = 5000

export function pipelineBusy(status: PipelineStatus | undefined): boolean {
  return !!status && (status.active_runs.length > 0 || status.open_requests.length > 0)
}

export function useToday() {
  return useQuery({ queryKey: keys.today, queryFn: api.today })
}

export function useSubmitAttempt(setId: number) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (answers: Answer[]) => api.submitAttempt(setId, answers),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: keys.today })
      client.invalidateQueries({ queryKey: keys.activity })
    },
  })
}

export function useActivity(days = 371) {
  return useQuery({ queryKey: keys.activity, queryFn: () => api.activity(days) })
}

export function useSettings() {
  return useQuery({ queryKey: keys.settings, queryFn: api.settings })
}

export function useUpdateSettings() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (patch: Partial<Settings>) => api.updateSettings(patch),
    onSuccess: (settings) => {
      client.setQueryData(keys.settings, settings)
      client.invalidateQueries({ queryKey: keys.today })
      client.invalidateQueries({ queryKey: keys.activity })
    },
  })
}

export function useNotes(query: NotesQuery, live = false) {
  return useQuery({
    queryKey: keys.notesList(query),
    queryFn: () => api.notes(query),
    refetchInterval: live ? LIVE_POLL_MS : false,
    placeholderData: keepPreviousData, // keep the old page on screen while the next one loads
  })
}

/** Put a PDF at a position in the pipeline order; resolves once the list has been refetched. */
export function useMoveNote() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, position }: { id: number; position: number }) => api.moveNote(id, position),
    onSuccess: () => client.invalidateQueries({ queryKey: ['notes', 'list'] }),
  })
}

/** Upload one PDF; `onProgress` gets the fraction sent so far. The list refetches afterwards. */
export function useUploadNote() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ file, folder, onProgress }: { file: File; folder: string; onProgress?: (f: number) => void }) =>
      api.uploadNote(file, folder, onProgress),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: keys.notes })
      client.invalidateQueries({ queryKey: keys.pipeline })
    },
  })
}

/** Delete a PDF's stored file; its questions and reels stay. */
export function useRemoveNoteFile() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (noteId: number) => api.removeNoteFile(noteId),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: keys.notes })
      client.invalidateQueries({ queryKey: keys.pipeline })
    },
  })
}

export function useReels() {
  return useQuery({ queryKey: keys.reels, queryFn: api.reels })
}

/** Count one watch of a reel; the cached feed takes the server's count. */
export function useRecordView() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (reelId: number) => api.recordView(reelId),
    onSuccess: ({ views }, reelId) => {
      client.setQueryData<{ reels: NoteReel[] }>(keys.reels, (data) =>
        data && { reels: data.reels.map((r) => (r.id === reelId ? { ...r, views } : r)) },
      )
      client.invalidateQueries({ queryKey: keys.activity })
    },
  })
}

export function usePipelineStatus() {
  return useQuery({
    queryKey: keys.pipeline,
    queryFn: api.pipelineStatus,
    refetchInterval: (query) => (pipelineBusy(query.state.data) ? LIVE_POLL_MS : false),
  })
}

export function useRetryTask() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (taskId: number) => api.retryTask(taskId),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: keys.notes })
      client.invalidateQueries({ queryKey: keys.pipeline })
    },
  })
}


export function useNoteItems(noteId: number, enabled: boolean) {
  return useQuery({ queryKey: keys.noteItems(noteId), queryFn: () => api.noteItems(noteId), enabled })
}

export function useUpdateScope(noteId: number) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (patch: Partial<NoteScope>) => api.updateScope(noteId, patch),
    onSuccess: ({ note }) => {
      // The saved note replaces its copy on every cached page; its position doesn't change.
      client.setQueriesData<NotesList>({ queryKey: ['notes', 'list'] }, (list) =>
        list && {
          ...list,
          notes: list.notes.map((n): Note => (n.id === note.id ? { ...note, position: n.position } : n)),
        },
      )
      client.invalidateQueries({ queryKey: ['notes', 'list'] }) // the summary counts may change
      client.invalidateQueries({ queryKey: keys.today })
    },
  })
}
