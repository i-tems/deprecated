export interface MeasureAnchor {
  measure: number;
  seconds: number;
}

// Pads the selected measure start by 1 measure (앞 1마디 lead-in) and resolves
// to audio start seconds. End is left open — playback continues past the range
// so the user keeps hearing context after the practiced segment. Returns null
// when anchors are insufficient.
export function paddedMeasureStartToAudio(
  measureStart: number,
  anchors: MeasureAnchor[] | null | undefined
): number | null {
  if (!anchors || anchors.length === 0) return null;
  const padStart = Math.max(1, measureStart - 1);
  return measureToSeconds(padStart, anchors);
}

// Linear interpolation between sorted anchors. Extrapolates using the
// nearest two anchors if `measure` is outside the anchor range.
// Returns null when anchors don't define a slope (fewer than 2 distinct anchors).
export function measureToSeconds(
  measure: number,
  anchorsInput: MeasureAnchor[] | null | undefined
): number | null {
  if (!anchorsInput || anchorsInput.length < 2) return null;
  const anchors = [...anchorsInput].sort((a, b) => a.measure - b.measure);

  // Exact match
  for (const a of anchors) {
    if (a.measure === measure) return a.seconds;
  }

  // Inside range — interpolate between bracket anchors
  for (let i = 0; i < anchors.length - 1; i++) {
    const lo = anchors[i];
    const hi = anchors[i + 1];
    if (measure > lo.measure && measure < hi.measure) {
      const t = (measure - lo.measure) / (hi.measure - lo.measure);
      return lo.seconds + t * (hi.seconds - lo.seconds);
    }
  }

  // Extrapolate before the first anchor using the first two
  if (measure < anchors[0].measure) {
    const [a, b] = anchors;
    const slope = (b.seconds - a.seconds) / (b.measure - a.measure);
    return a.seconds + slope * (measure - a.measure);
  }

  // Extrapolate after the last anchor using the last two
  const a = anchors[anchors.length - 2];
  const b = anchors[anchors.length - 1];
  const slope = (b.seconds - a.seconds) / (b.measure - a.measure);
  return b.seconds + slope * (measure - b.measure);
}
