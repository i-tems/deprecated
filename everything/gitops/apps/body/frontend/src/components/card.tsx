import type { ReactNode } from "react";

interface CardProps {
  children: ReactNode;
  className?: string;
  padding?: "sm" | "md" | "lg";
}

export default function Card({
  children,
  className = "",
  padding = "md",
}: CardProps) {
  const pad = { sm: "p-4", md: "p-5", lg: "p-6" }[padding];
  return (
    <div
      className={`bg-white rounded-2xl border border-border ${pad} ${className}`}
    >
      {children}
    </div>
  );
}
