import { useState } from 'react'

import { useSettings, useUpdateSettings } from '../../api/hooks'
import type { Settings } from '../../api/types'
import { Button } from '../../components/Button'
import { Checkbox } from '../../components/Checkbox'
import { ErrorState } from '../../components/ErrorState'
import { neededToPass } from '../quiz/format'

export function SettingsPage() {
  const settings = useSettings()
  return (
    <div className="mx-auto max-w-[720px] px-5 pt-8 pb-10 sm:px-8 lg:px-12 lg:pt-14">
      <h1 className="font-display text-[36px] leading-[1.05] font-semibold tracking-tight">Settings</h1>
      {settings.isPending ? (
        <div className="mt-8 h-40 animate-pulse rounded-[20px] border border-rule bg-sheet motion-reduce:animate-none" />
      ) : settings.isError ? (
        <div className="mt-8">
          <ErrorState error={settings.error} onRetry={() => settings.refetch()} />
        </div>
      ) : (
        <>
          <PassMarkForm initial={settings.data} />
          <DailyGoals settings={settings.data} />
          <PipelineSwitches settings={settings.data} />
        </>
      )}
    </div>
  )
}

function PassMarkForm({ initial }: { initial: Settings }) {
  const update = useUpdateSettings()
  const [passPct, setPassPct] = useState(initial.pass_pct)
  const total = initial.questions_per_set
  const dirty = passPct !== initial.pass_pct

  return (
    <form
      className="mt-8 rounded-[20px] border border-rule bg-sheet p-5 sm:p-7"
      onSubmit={(e) => {
        e.preventDefault()
        update.mutate({ pass_pct: passPct })
      }}
    >
      <label htmlFor="pass-pct" className="font-display text-[20px] font-semibold">
        Pass mark
      </label>
      <p id="pass-pct-help" className="mt-1 text-[15px] leading-relaxed text-muted">
        A quiz repeats until you score at least this much.
      </p>

      <div className="mt-6 flex items-baseline gap-3">
        <output htmlFor="pass-pct" className="font-display text-[48px] leading-none font-semibold tabular-nums">
          {passPct}%
        </output>
        <span className="text-[15px] text-muted">
          {neededToPass(passPct, total)} of {total} correct
        </span>
      </div>

      <input
        id="pass-pct"
        type="range"
        min={50}
        max={100}
        step={10}
        value={passPct}
        aria-describedby="pass-pct-help"
        onChange={(e) => setPassPct(Number(e.target.value))}
        className="mt-5 h-11 w-full cursor-pointer accent-[var(--ink)]"
      />
      <div className="flex justify-between text-[13px] text-muted" aria-hidden>
        <span>50%</span>
        <span>100%</span>
      </div>

      <div className="mt-6 flex flex-wrap items-center gap-4">
        <Button type="submit" disabled={!dirty || update.isPending}>
          {update.isPending ? 'Saving…' : 'Save pass mark'}
        </Button>
        <p aria-live="polite" className="text-[15px]">
          {update.isSuccess && !dirty && <span className="text-ink">Pass mark saved.</span>}
          {update.isError && <span className="text-pen">Couldn't save. {update.error.message}</span>}
        </p>
      </div>
    </form>
  )
}

// Saved on each change. The pipeline itself runs on the Mac; these tell its runner what it may do.
function PipelineSwitches({ settings }: { settings: Settings }) {
  const update = useUpdateSettings()
  return (
    <section aria-labelledby="pipeline-heading" className="mt-6 rounded-[20px] border border-rule bg-sheet p-5 sm:p-7">
      <h2 id="pipeline-heading" className="font-display text-[20px] font-semibold">
        Question pipeline
      </h2>
      <p className="mt-1 text-[15px] leading-relaxed text-muted">
        Claude makes new questions on your Mac, from the pages chosen in Manage notes.
      </p>
      <div className="mt-4 flex flex-col gap-1">
        <Checkbox
          checked={settings.pipeline_enabled}
          disabled={update.isPending}
          onChange={(e) => update.mutate({ pipeline_enabled: e.target.checked })}
          label="Pipeline on"
          hint="Off stops new runs from starting. A run already going finishes its current part."
        />
        <Checkbox
          checked={settings.pipeline_auto}
          disabled={update.isPending || !settings.pipeline_enabled}
          onChange={(e) => update.mutate({ pipeline_auto: e.target.checked })}
          label="Start runs by itself"
          hint={`Off: only when you press "Make questions now". On: whenever pages are waiting, up to ${settings.max_runs_per_day} runs a day.`}
        />
      </div>
      <ReelLimit settings={settings} onSave={(reel_limit) => update.mutate({ reel_limit })} saving={update.isPending} />
      <p aria-live="polite" className="mt-2 text-[14px] empty:hidden">
        {update.isError && <span className="text-pen">Couldn't save. {update.error.message}</span>}
      </p>
    </section>
  )
}

// Reels cost far more Claude usage than questions, so they have a total cap.
function ReelLimit({ settings, onSave, saving }: { settings: Settings; onSave: (n: number) => void; saving: boolean }) {
  const [value, setValue] = useState(String(settings.reel_limit))
  const parsed = Number(value)
  const valid = value.trim() !== '' && Number.isInteger(parsed) && parsed >= 0 && parsed <= 1000
  return (
    <form
      className="mt-4 flex flex-wrap items-end gap-3"
      onSubmit={(e) => {
        e.preventDefault()
        if (valid && parsed !== settings.reel_limit) onSave(parsed)
      }}
    >
      <label className="flex flex-col gap-1">
        <span className="font-bold">Reels to make</span>
        <span className="text-[13px] text-muted">In total. 0 means no limit.</span>
        <input
          type="number"
          inputMode="numeric"
          min={0}
          max={1000}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          aria-invalid={!valid}
          className="h-11 w-24 rounded-xl border border-rule bg-sheet px-2 text-center font-display text-[17px] font-semibold tabular-nums"
        />
      </label>
      <Button type="submit" variant="secondary" disabled={!valid || saving || parsed === settings.reel_limit}>
        Save
      </Button>
    </form>
  )
}

// The daily targets the Quiz page tracker measures against. Changing them updates today, not past days.
function DailyGoals({ settings }: { settings: Settings }) {
  const update = useUpdateSettings()
  const [questions, setQuestions] = useState(String(settings.daily_questions_goal))
  const [reels, setReels] = useState(String(settings.daily_reels_goal))
  const q = Number(questions)
  const r = Number(reels)
  const valid = Number.isInteger(q) && q >= 1 && q <= 500 && Number.isInteger(r) && r >= 1 && r <= 100
  const dirty = q !== settings.daily_questions_goal || r !== settings.daily_reels_goal
  const field =
    'h-11 w-24 rounded-xl border border-rule bg-sheet px-2 text-center font-display text-[17px] font-semibold tabular-nums'

  return (
    <form
      aria-labelledby="goals-heading"
      className="mt-6 rounded-[20px] border border-rule bg-sheet p-5 sm:p-7"
      onSubmit={(e) => {
        e.preventDefault()
        if (valid && dirty) update.mutate({ daily_questions_goal: q, daily_reels_goal: r })
      }}
    >
      <h2 id="goals-heading" className="font-display text-[20px] font-semibold">
        Daily goals
      </h2>
      <p className="mt-1 text-[15px] leading-relaxed text-muted">
        Hit these to fill in today on the Quiz page tracker. Changes apply from today; past days keep their goals.
      </p>
      <div className="mt-5 flex flex-wrap gap-6">
        <label className="flex flex-col gap-1">
          <span className="flex items-center gap-2 font-bold">
            <span aria-hidden className="size-2.5 rounded-full bg-ink" />
            Quiz questions
          </span>
          <span className="text-[13px] text-muted">Different questions answered</span>
          <input
            type="number"
            inputMode="numeric"
            min={1}
            max={500}
            value={questions}
            onChange={(e) => setQuestions(e.target.value)}
            aria-invalid={!(Number.isInteger(q) && q >= 1 && q <= 500)}
            className={field}
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="flex items-center gap-2 font-bold">
            <span aria-hidden className="size-2.5 rounded-full bg-reel" />
            Reels watched
          </span>
          <span className="text-[13px] text-muted">Watched past 80%, rewatches count</span>
          <input
            type="number"
            inputMode="numeric"
            min={1}
            max={100}
            value={reels}
            onChange={(e) => setReels(e.target.value)}
            aria-invalid={!(Number.isInteger(r) && r >= 1 && r <= 100)}
            className={field}
          />
        </label>
      </div>
      <div className="mt-6 flex flex-wrap items-center gap-4">
        <Button type="submit" disabled={!valid || !dirty || update.isPending}>
          {update.isPending ? 'Saving…' : 'Save goals'}
        </Button>
        <p aria-live="polite" className="text-[15px]">
          {update.isSuccess && !dirty && <span className="text-ink">Goals saved.</span>}
          {update.isError && <span className="text-pen">Couldn't save. {update.error.message}</span>}
        </p>
      </div>
    </form>
  )
}
