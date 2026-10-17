import { clsx, type ClassValue } from "clsx"
import { extendTailwindMerge } from "tailwind-merge"

// The design system's type scale (text-k-*) and surface colours are custom
// theme keys; tell tailwind-merge which group each belongs to, or it reads
// "text-k-body" as a colour and drops it when "text-ink" follows.
const twMerge = extendTailwindMerge({
  extend: {
    classGroups: {
      "font-size": [{ text: ["k-meta", "k-caption", "k-body", "k-title", "k-h1", "k-stat"] }],
    },
  },
})

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}
