import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

/** Class names with Tailwind conflicts resolved (shadcn convention). */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}
