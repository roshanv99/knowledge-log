import { CheckIcon } from '@phosphor-icons/react'
import type { InputHTMLAttributes, ReactNode } from 'react'

// A native checkbox drawn as a filled square, so it reads as "ticked" rather than an answer bubble.
export function Checkbox({ label, hint, size = 'md', ...props }: Omit<InputHTMLAttributes<HTMLInputElement>, 'size'> & {
  label: ReactNode
  hint?: ReactNode
  size?: 'md' | 'lg'
}) {
  const box = size === 'lg' ? 'size-7 rounded-lg' : 'size-6 rounded-md'
  return (
    <label className="group inline-flex min-h-11 cursor-pointer items-center gap-3 has-disabled:cursor-not-allowed has-disabled:opacity-50">
      <span className="relative grid shrink-0 place-items-center">
        <input
          type="checkbox"
          className={`peer appearance-none border-[1.5px] border-ink/55 bg-sheet transition checked:border-ink checked:bg-ink ${box}`}
          {...props}
        />
        <CheckIcon
          weight="bold"
          aria-hidden
          className="pointer-events-none absolute size-[60%] text-on-ink opacity-0 peer-checked:opacity-100"
        />
      </span>
      <span className="flex flex-col">
        <span className="leading-snug">{label}</span>
        {hint && <span className="text-[13px] text-muted">{hint}</span>}
      </span>
    </label>
  )
}
