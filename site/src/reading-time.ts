const WORDS_PER_MINUTE = 220;

/** Estimate reading time in whole minutes from a markdown body. */
export function readingTime(body = ''): number {
  const words = body.split(/\s+/).filter(Boolean).length;
  return Math.max(1, Math.round(words / WORDS_PER_MINUTE));
}
