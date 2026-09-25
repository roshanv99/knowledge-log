import type { ButtonHTMLAttributes } from 'react'
import { Link, type LinkProps } from 'react-router'

const base =
  'inline-flex h-12 items-center justify-center gap-2 rounded-xl px-6 font-display text-[17px] font-semibold whitespace-nowrap transition active:scale-[0.98] disabled:pointer-events-none disabled:opacity-50'
const variants = {
  primary: 'bg-ink text-on-ink hover:brightness-110',
  secondary: 'border border-rule bg-sheet text-graphite hover:border-ink/40',
}

type Variant = keyof typeof variants

export function Button({ variant = 'primary', className = '', ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  return <button className={`${base} ${variants[variant]} ${className}`} {...props} />
}

export function ButtonLink({ variant = 'primary', className = '', ...props }: LinkProps & { variant?: Variant }) {
  return <Link className={`${base} ${variants[variant]} ${className}`} {...props} />
}
