import axios from "axios";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const api = axios.create({
  baseURL: API_BASE,
  headers: { "Content-Type": "application/json" },
});

// Attach JWT token to every request
api.interceptors.request.use((config) => {
  if (typeof window !== "undefined") {
    const token = localStorage.getItem("token");
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
  }
  return config;
});

// On 401, clear token and redirect to login
api.interceptors.response.use(
  (res) => res,
  (error) => {
    if (error.response?.status === 401 && typeof window !== "undefined") {
      localStorage.removeItem("token");
      if (window.location.pathname !== "/login") {
        window.location.href = "/login";
      }
    }
    return Promise.reject(error);
  }
);

// ---------- Config ----------
export interface BodyPartConfig {
  id: string;
  name: string;
  representative_exercise: string;
  strength_standards: Record<string, string>;
}

export interface AttributeConfig {
  id: string;
  name: string;
  description: string;
  levels: Record<string, string>;
}

export interface SkillConfig {
  id: string;
  name: string;
  description: string;
  levels: Record<string, string>;
}

export type RunningUnit = "time" | "distance";
export type RunningDirection = "lower" | "higher";

export interface RunningMetricConfig {
  id: string;
  name: string;
  description: string;
  unit: RunningUnit;
  direction: RunningDirection;
  level_standards: Record<string, string>;
}

export interface AppConfig {
  body_parts: BodyPartConfig[];
  attributes: AttributeConfig[];
  skills: SkillConfig[];
  running_metrics: RunningMetricConfig[];
}

export async function getConfig(): Promise<AppConfig> {
  const { data } = await api.get("/api/config");
  return data;
}

// ---------- Overview ----------
export interface PartScore {
  part_id: string;
  part_name: string;
  strength: number;
  development: number;
  mmc: number;
  best_5rm?: number | null;
  total: number;
}

export interface SkillScore {
  skill_id: string;
  skill_name: string;
  score: number;
}

export interface RunningScore {
  metric_id: string;
  metric_name: string;
  unit: RunningUnit;
  direction: RunningDirection;
  value: number | null;
  level: number;
  last_date: string | null;
}

export interface RecentChange {
  part_id: string;
  part_name: string;
  attribute: string;
  old_value: number;
  new_value: number;
  change: number;
}

export interface Overview {
  total_score: number;
  part_scores: PartScore[];
  skill_scores: SkillScore[];
  running_scores: RunningScore[];
  recent_changes: RecentChange[];
  weakest: { part_id: string; part_name: string; attribute: string; value: number }[];
  last_evaluation_date: string;
  last_running_date: string | null;
}

export async function getOverview(): Promise<Overview> {
  const { data } = await api.get("/api/overview");
  return data;
}

// ---------- Evaluations ----------
export interface Evaluation {
  id?: string;
  date: string;
  part_id: string;
  strength: number;
  development: number;
  mmc: number;
  best_5rm?: number | null;
}

export async function getEvaluations(params?: {
  from?: string;
  to?: string;
  part?: string;
}): Promise<Evaluation[]> {
  const { data } = await api.get("/api/evaluations", { params });
  return data;
}

export async function createEvaluation(
  evaluations: Omit<Evaluation, "id">[]
): Promise<void> {
  await api.post("/api/evaluations", evaluations);
}

// ---------- Skill Evaluations ----------
export interface SkillEvaluation {
  id?: string;
  date: string;
  skill_id: string;
  score: number;
}

export async function getSkillEvaluations(params?: {
  from?: string;
  to?: string;
}): Promise<SkillEvaluation[]> {
  const { data } = await api.get("/api/skill-evaluations", { params });
  return data;
}

export async function createSkillEvaluation(
  evaluations: Omit<SkillEvaluation, "id">[]
): Promise<void> {
  await api.post("/api/skill-evaluations", evaluations);
}

// ---------- Running Evaluations ----------
export interface RunningEvaluation {
  date: string;
  metric_id: string;
  level: number; // 1.0 ~ 5.0, primary signal
  value?: number | null; // optional raw PR (seconds for time, km for distance)
}

export async function getRunningEvaluations(params?: {
  from?: string;
  to?: string;
  metric?: string;
}): Promise<RunningEvaluation[]> {
  const { data } = await api.get("/api/running-evaluations", { params });
  return data;
}

export async function createRunningEvaluation(
  evaluations: RunningEvaluation[]
): Promise<void> {
  await api.post("/api/running-evaluations", evaluations);
}

// ---------- Running helpers (client-side level calc + format) ----------
/** Parse "h:mm:ss" / "mm:ss" / numeric string to seconds (for time metrics)
 *  or raw number (for distance metrics). Returns null if empty/invalid. */
export function parseRunningInput(
  raw: string,
  unit: RunningUnit
): number | null {
  const s = raw.trim();
  if (!s) return null;
  if (unit === "distance") {
    const n = parseFloat(s);
    return Number.isFinite(n) && n > 0 ? n : null;
  }
  if (s.includes(":")) {
    const parts = s.split(":").map((p) => parseFloat(p));
    if (parts.some((p) => !Number.isFinite(p))) return null;
    if (parts.length === 2) return parts[0] * 60 + parts[1];
    if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2];
    return null;
  }
  const n = parseFloat(s);
  return Number.isFinite(n) && n > 0 ? n : null;
}

/** Format a numeric running value back to display string. */
export function formatRunningValue(
  value: number | null | undefined,
  unit: RunningUnit
): string {
  if (value == null || !Number.isFinite(value)) return "-";
  if (unit === "distance") {
    return `${value.toFixed(value < 10 ? 1 : 0)}km`;
  }
  const total = Math.round(value);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const mm = String(m).padStart(2, "0");
  const ss = String(s).padStart(2, "0");
  if (h > 0) return `${h}:${mm}:${ss}`;
  return `${mm}:${ss}`;
}

/** Compute a 1.0~5.0 level from a raw value using a metric's level_standards.
 *  Mirrors the backend _compute_level logic so the UI can show a live hint. */
export function computeRunningLevel(
  metric: RunningMetricConfig,
  value: number | null
): number {
  if (value == null || !Number.isFinite(value)) return 0;
  const entries: { level: number; thr: number }[] = [];
  for (const [lvStr, thrRaw] of Object.entries(metric.level_standards ?? {})) {
    const lv = parseInt(lvStr, 10);
    if (!Number.isFinite(lv)) continue;
    const thr = parseRunningInput(String(thrRaw), metric.unit);
    if (thr == null) continue;
    entries.push({ level: lv, thr });
  }
  if (entries.length === 0) return 0;

  const isLower = metric.direction === "lower";
  const ordered = [...entries].sort((a, b) =>
    isLower ? b.thr - a.thr : a.thr - b.thr
  );
  const worst = ordered[0];
  const best = ordered[ordered.length - 1];

  const isBetterOrEq = (v: number, t: number) => (isLower ? v <= t : v >= t);
  const isBetterStrict = (v: number, t: number) => (isLower ? v < t : v > t);

  if (!isBetterOrEq(value, worst.thr)) return worst.level;
  if (isBetterStrict(value, best.thr) || value === best.thr) return best.level;

  for (let i = 0; i < ordered.length - 1; i++) {
    const a = ordered[i];
    const b = ordered[i + 1];
    const lo = Math.min(a.thr, b.thr);
    const hi = Math.max(a.thr, b.thr);
    if (value >= lo && value <= hi) {
      const span = b.thr - a.thr;
      const level = span === 0 ? b.level : a.level + ((value - a.thr) / span) * (b.level - a.level);
      return Math.round(level * 2) / 2;
    }
  }
  return worst.level;
}

// ---------- Profile ----------
export interface Profile {
  weight: number;
  height: number;
}

export async function getProfile(): Promise<Profile> {
  const { data } = await api.get("/api/profile");
  return data;
}

export async function updateProfile(profile: Profile): Promise<Profile> {
  const { data } = await api.put("/api/profile", profile);
  return data;
}
