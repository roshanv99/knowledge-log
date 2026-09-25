import { motion, useReducedMotion } from 'motion/react'

// A loose, hand-drawn red-pen loop around the score: the one orchestrated moment in the app.
export function RedCircle({ className = '' }: { className?: string }) {
  const reduce = useReducedMotion()
  return (
    <svg viewBox="0 0 220 120" preserveAspectRatio="none" fill="none" aria-hidden className={`pointer-events-none absolute ${className}`}>
      <motion.path
        d="M160 14C124 2 52 6 24 30 2 49 8 86 44 102c38 17 116 16 150-6 26-17 22-52-8-70-22-13-60-18-96-12"
        stroke="var(--pen)"
        strokeWidth="4"
        vectorEffect="non-scaling-stroke"
        strokeLinecap="round"
        initial={reduce ? false : { pathLength: 0 }}
        animate={{ pathLength: 1 }}
        transition={{ duration: 0.7, ease: [0.65, 0, 0.35, 1], delay: 0.15 }}
      />
    </svg>
  )
}
