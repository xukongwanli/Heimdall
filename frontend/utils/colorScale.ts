/**
 * Maps a normalized value (0–1) to a hex color on a blue→green→orange→red gradient.
 * Returns null fill color for undefined/null values.
 */

interface ColorStop {
  pos: number
  r: number
  g: number
  b: number
}

const STOPS: ColorStop[] = [
  { pos: 0, r: 10, g: 132, b: 255 },   // #0a84ff blue
  { pos: 0.33, r: 50, g: 215, b: 75 },  // #32d74b green
  { pos: 0.66, r: 255, g: 159, b: 10 }, // #ff9f0a orange
  { pos: 1, r: 255, g: 69, b: 58 },     // #ff453a red
]

function lerp(a: number, b: number, t: number): number {
  return Math.round(a + (b - a) * t)
}

function toHex(n: number): string {
  return n.toString(16).padStart(2, '0')
}

export function valueToColor(value: number | null | undefined, min: number, max: number): string {
  if (value == null || min === max) return '#161b22'

  const t = Math.max(0, Math.min(1, (value - min) / (max - min)))

  let lower = STOPS[0]
  let upper = STOPS[STOPS.length - 1]
  for (let i = 0; i < STOPS.length - 1; i++) {
    if (t >= STOPS[i].pos && t <= STOPS[i + 1].pos) {
      lower = STOPS[i]
      upper = STOPS[i + 1]
      break
    }
  }

  const segmentT = (t - lower.pos) / (upper.pos - lower.pos)
  const r = lerp(lower.r, upper.r, segmentT)
  const g = lerp(lower.g, upper.g, segmentT)
  const b = lerp(lower.b, upper.b, segmentT)

  return `#${toHex(r)}${toHex(g)}${toHex(b)}`
}

export function computeBounds(values: (number | null | undefined)[]): { min: number; max: number } {
  const valid = values.filter((v): v is number => v != null)
  if (valid.length === 0) return { min: 0, max: 0 }
  return { min: Math.min(...valid), max: Math.max(...valid) }
}
