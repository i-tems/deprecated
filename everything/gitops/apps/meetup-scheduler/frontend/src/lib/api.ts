import axios from "axios";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8003";

const api = axios.create({
  baseURL: API_URL,
});

function redirectToLogin() {
  if (typeof window === "undefined") return;

  const currentPath = `${window.location.pathname}${window.location.search}${window.location.hash}`;
  if (currentPath && currentPath !== "/") {
    localStorage.setItem("redirect_after_login", currentPath);
  }

  localStorage.removeItem("token");
  window.location.href = "/";
}

api.interceptors.request.use((config) => {
  if (typeof window !== "undefined") {
    const token = localStorage.getItem("token");
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
  }
  return config;
});

api.interceptors.response.use(
  (res) => res,
  (error) => {
    const status = error.response?.status;
    const detail = error.response?.data?.detail;
    const isNotAuthenticated = typeof detail === "string" && detail === "Not authenticated";

    if (status === 401 || (status === 403 && isNotAuthenticated)) {
      redirectToLogin();
    }

    return Promise.reject(error);
  }
);

export default api;

// Types
export interface User {
  id: string;
  email: string;
  name: string;
  avatar_url: string | null;
}

export interface ScheduleBlock {
  id: string;
  user_id: string;
  title: string | null;
  date: string;
  pattern_id: string | null;
  created_at: string;
}

export interface ShiftPattern {
  id: string;
  user_id: string;
  name: string;
  pattern_data: {
    units: { name: string; is_working: boolean }[];
    sequence: number[];
  };
  start_date: string;
  created_at: string;
}

export interface GroupSummary {
  id: string;
  name: string;
  invite_code: string;
  created_by: string;
  created_at: string;
  member_count: number;
}

export interface GroupMember {
  id: string;
  user_id: string;
  role: "ADMIN" | "MEMBER";
  joined_at: string;
  user_name: string;
  user_email: string;
  user_avatar_url: string | null;
}

export interface GroupDetail {
  id: string;
  name: string;
  invite_code: string;
  created_by: string;
  created_at: string;
  members: GroupMember[];
}

export interface MemberSchedule {
  user_id: string;
  user_name: string;
  user_avatar_url: string | null;
  blocks: {
    id: string;
    title: string | null;
    date: string;
  }[];
}

export interface AvailabilitySlot {
  date: string;
  available_members: string[];
  available_count: number;
  total_members: number;
}

// Extract a user-facing error message from a thrown axios error.
// Surfaces FastAPI's {detail: string} when present, falls back to HTTP status text.
export function getErrorMessage(err: unknown, fallback = "요청 중 오류가 발생했습니다"): string {
  const e = err as { response?: { data?: { detail?: unknown }; status?: number; statusText?: string }; message?: string };
  const detail = e?.response?.data?.detail;
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail) && detail.length > 0) {
    const first = (detail[0] as { msg?: string })?.msg;
    if (first) return first;
  }
  if (e?.response?.status) return `${e.response.status} ${e.response.statusText ?? ""}`.trim();
  return e?.message || fallback;
}
