import { API_BASE_URL } from "@/lib/env";

export class ApiError extends Error {
  status: number;
  statusText: string;
  bodyText: string;

  constructor(status: number, statusText: string, bodyText: string) {
    super(`API ${status} ${statusText}: ${bodyText}`);
    this.name = "ApiError";
    this.status = status;
    this.statusText = statusText;
    this.bodyText = bodyText;
  }
}

export async function apiGetJson<T>(path: string): Promise<T> {
  const url = `${API_BASE_URL}${path}`;
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new ApiError(res.status, res.statusText, text);
  }
  return (await res.json()) as T;
}


