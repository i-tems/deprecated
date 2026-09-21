export function extractYouTubeId(url: string | null | undefined): string | null {
  if (!url) return null;
  try {
    const u = new URL(url);
    if (u.hostname.includes("youtu.be")) {
      return u.pathname.slice(1) || null;
    }
    if (u.hostname.includes("youtube.com")) {
      if (u.pathname === "/watch") return u.searchParams.get("v");
      if (u.pathname.startsWith("/embed/")) return u.pathname.split("/")[2] || null;
      if (u.pathname.startsWith("/shorts/")) return u.pathname.split("/")[2] || null;
    }
  } catch {
    return null;
  }
  return null;
}

// Accepts plain seconds ("90", "1.4"), MM:SS ("1:30", "1:30.5"), or HH:MM:SS.
// Returns null if input is empty or unparseable.
export function parseTimeToSeconds(input: string): number | null {
  const s = input.trim();
  if (s === "") return null;
  if (/^\d+(\.\d+)?$/.test(s)) return parseFloat(s);
  const parts = s.split(":");
  if (parts.length < 2 || parts.length > 3) return null;
  // Last part may have decimals; preceding parts must be integers.
  if (!parts.slice(0, -1).every((p) => /^\d+$/.test(p))) return null;
  if (!/^\d+(\.\d+)?$/.test(parts[parts.length - 1])) return null;
  const ints = parts.slice(0, -1).map((p) => parseInt(p, 10));
  const tail = parseFloat(parts[parts.length - 1]);
  if (parts.length === 2) {
    const [m] = ints;
    if (tail >= 60) return null;
    return m * 60 + tail;
  }
  const [h, m] = ints;
  if (m >= 60 || tail >= 60) return null;
  return h * 3600 + m * 60 + tail;
}

// Whole-seconds display (used for embed start/end and practice record list).
export function formatSeconds(total: number | null): string {
  if (total == null) return "";
  const t = Math.max(0, Math.floor(total));
  const h = Math.floor(t / 3600);
  const m = Math.floor((t % 3600) / 60);
  const s = t % 60;
  if (h > 0) {
    return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  }
  return `${m}:${String(s).padStart(2, "0")}`;
}

// Sub-second precision for measure-timestamp editing round-trip.
export function formatSecondsPrecise(total: number | null): string {
  if (total == null) return "";
  const safe = Math.max(0, total);
  const intPart = Math.floor(safe);
  const frac = safe - intPart;
  const h = Math.floor(intPart / 3600);
  const m = Math.floor((intPart % 3600) / 60);
  const sInt = intPart % 60;
  // Strip trailing zeros: "1.40" → "1.4", "1.00" → "1"
  const fracStr =
    frac > 0 ? frac.toFixed(2).replace(/^0\.?/, ".").replace(/0+$/, "") : "";
  const sStr = `${String(sInt).padStart(2, "0")}${fracStr}`;
  if (h > 0) {
    return `${h}:${String(m).padStart(2, "0")}:${sStr}`;
  }
  return `${m}:${sStr}`;
}

export function buildEmbedUrl(
  videoId: string,
  opts: { start?: number | null; end?: number | null; autoplay?: boolean } = {}
): string {
  const params = new URLSearchParams();
  if (opts.start != null && opts.start > 0) params.set("start", String(opts.start));
  if (opts.end != null && opts.end > 0) params.set("end", String(opts.end));
  if (opts.autoplay) params.set("autoplay", "1");
  const qs = params.toString();
  return `https://www.youtube.com/embed/${videoId}${qs ? `?${qs}` : ""}`;
}
