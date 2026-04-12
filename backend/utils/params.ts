/**
 * Parses a query param string to a non-negative integer.
 * Returns `defaultVal` if the input is missing, NaN, or negative.
 * Caps the result at `max`.
 */
export function parseNonNegativeInt(
  val: string | undefined,
  defaultVal?: number,
  max = 1000
): number | undefined {
  if (!val) return defaultVal;
  const n = parseInt(val, 10);
  if (isNaN(n) || n < 0) return defaultVal;
  return Math.min(n, max);
}
