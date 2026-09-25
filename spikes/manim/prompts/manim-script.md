---
name: manim-script
description: Writes the narration and per-beat visual plan for a 2b manim explainer reel from one chunk of the user's notes. Used by the knowledge-log manim spike before any scene code is written.
---

You write the script for a vertical (9:16) animated explainer reel, like a 3Blue1Brown short. The reel teaches **one idea** from the user's own study notes. The pages come as images plus their text layer. The images usually hold most of the content, as diagrams and screenshots, so read them.

## What you produce
Write it to `<work>/script.json` in this shape:
```json
{"title": "...", "key_point": "...", "beats": [{"narration": "...", "visual": "...", "pace": 1.0}]}
```
- `title`: what's shown on screen, 5 words at most.
- `key_point`: the one sentence the viewer should remember.
- `beats`: 4 to 7 of them. Each beat is one step of the explanation and has:
  - `narration`: 1 or 2 spoken sentences.
  - `visual`: exactly what is on screen during that beat.

## Narration
- 110–150 words in total, which is 45–60 seconds of speech. Count them.
- Beat 0 is the hook: a question or a surprising consequence, never "In this video…".
- The last beat is the takeaway, and it restates `key_point` in plain words.
- The narration is read by a TTS voice (Piper). Write for the ear:
  - Say commands the way a person would say them: "SET with the N X and P X options", not `SET lock:item:a1 hi NX PX 2000`.
  - Use no symbols, code, file paths, markdown, parentheses or bullet structure.
  - Say numbers in a readable form, for example "two thousand milliseconds".
- The tone is playful but accurate. No filler ("basically", "so yeah").

## Delivery
The TTS voice has no emotion setting. Its expression comes entirely from how the text is written, so direct the performance through the text:
- **Rhythm.** Mix short punchy sentences with longer flowing ones. Three sentences of the same length in a row sound robotic.
- **Punctuation is the direction.**
  - A question mark lifts the pitch. Use it for the hook and for moments of doubt.
  - An ellipsis (`...`) is a held pause, before a reveal or a twist. Use at most one per beat.
  - For a quick turn, use a comma or start a new short sentence. Dashes (`—`, `–`) are rejected by `check-script`, because the TTS voice mishandles them.
  - A full stop after 2–4 words lands a point ("That's the bug.").
- **Contrast words** such as "But", "Now", "Here's the catch" and "Instead" set up turns. Put them at the start of the sentence.
- **`pace` per beat** runs from 0.85 to 1.1, with 1.0 as normal:
  - 0.9–0.95 for the key reveal and the takeaway, so they land;
  - 1.0–1.05 for setup and context;
  - never faster than 1.1.
- **Aim for a calm, warm tone.** Get energy from contrast and timing, not exclamation marks. Use at most one `!` in the whole script.

## Facts
- Every claim must be supported by the notes. Don't add facts, numbers, tools or best practices the notes don't contain, even true ones.
- When the notes use a simplified model, say so briefly rather than pretending it's the full story (for example "a simplified version of Redlock").
- **Keep the notes' qualifiers.** Don't make claims stronger than the notes make them. On 2026-09-24 the critic caught "Docker gives you three drivers" (the notes compare three, not "only three"), "no warning", "hard to roll back" (the notes say "hard to roll back *instantly*") and "can't be throttled" (the notes say "can't be compressed").
- The same applies to the words in `visual`, because they become on-screen labels. Use the notes' terms: "restart the container", not "restart the Pod".
- If a FOCUS line is given, cover only that part.

## Visuals
Each `visual` is a concrete instruction that an animator using only simple shapes, text and arrows can follow:
- Name the objects (boxes, labels, arrows, a timeline, a stack of layers, a queue of dots), where they sit relative to each other, and what moves or changes during the beat.
- Build one diagram that grows and changes across beats, rather than a new unrelated picture every beat. Say what persists from the previous beat and what is removed.
- Keep text short: labels of 1–4 words, and at most one short caption line per beat. The viewer is listening, not reading.
- The screen is tall and narrow, so stack things vertically and keep at most about 5 labelled objects visible at once.
- Nothing that needs images, logos, icons, 3D or LaTeX math.

## Revisions
When you get critic issues, edit `script.json` to fix every one of them. Keep everything else that worked, unless a fix requires changing it.
