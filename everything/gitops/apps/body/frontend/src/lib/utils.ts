import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function conditionColor(condition: string): string {
  switch (condition) {
    case "normal":
      return "bg-emerald-50 text-emerald-600 border-emerald-200";
    case "caution":
      return "bg-amber-50 text-amber-600 border-amber-200";
    case "limited":
      return "bg-red-50 text-red-600 border-red-200";
    default:
      return "bg-gray-50 text-gray-600 border-gray-200";
  }
}

export function conditionLabel(condition: string): string {
  switch (condition) {
    case "normal":
      return "정상";
    case "caution":
      return "주의";
    case "limited":
      return "제한";
    default:
      return condition;
  }
}

export function formatDate(dateStr: string): string {
  const d = new Date(dateStr);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export function getToday(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
