import type { ReactNode } from "react";

interface StatCardProps {
  title: string;
  value: string | number;
  subtitle?: string;
  icon?: ReactNode;
  className?: string;
}

export default function StatCard({
  title,
  value,
  subtitle,
  icon,
  className = "",
}: StatCardProps) {
  return (
    <div
      className={`bg-white rounded-2xl border border-border p-5 ${className}`}
    >
      <div className="flex items-start justify-between mb-2">
        <p className="text-[13px] text-text-secondary font-medium">{title}</p>
        {icon && <div className="text-text-tertiary">{icon}</div>}
      </div>
      <p className="text-2xl font-bold text-text-primary tracking-tight">
        {value}
      </p>
      {subtitle && (
        <p className="text-[12px] text-text-tertiary mt-1">{subtitle}</p>
      )}
    </div>
  );
}
