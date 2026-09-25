import '@fontsource/atkinson-hyperlegible-next/400.css'
import '@fontsource/atkinson-hyperlegible-next/700.css'
import '@fontsource/barlow-semi-condensed/500.css'
import '@fontsource/barlow-semi-condensed/600.css'
import '@fontsource/jetbrains-mono/400.css'
import './index.css'

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { createBrowserRouter, Navigate, RouterProvider } from 'react-router'

import { AppShell } from './components/AppShell'
import { NotesPage } from './features/notes/NotesPage'
import { PlayPage } from './features/quiz/PlayPage'
import { PracticePage } from './features/quiz/PracticePage'
import { ResultPage } from './features/quiz/ResultPage'
import { TodayPage } from './features/quiz/TodayPage'
import { ReelsPage } from './features/reels/ReelsPage'
import { SettingsPage } from './features/settings/SettingsPage'

const router = createBrowserRouter([
  {
    element: <AppShell />,
    children: [
      { index: true, element: <Navigate to="/quiz" replace /> },
      { path: 'quiz', element: <TodayPage /> },
      { path: 'reels', element: <ReelsPage /> },
      { path: 'notes', element: <NotesPage /> },
      { path: 'settings', element: <SettingsPage /> },
    ],
  },
  // Answering and results are focus mode: no navigation chrome.
  { path: 'quiz/play', element: <PlayPage /> },
  { path: 'quiz/practice', element: <PracticePage /> },
  { path: 'quiz/result', element: <ResultPage /> },
])

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
)
