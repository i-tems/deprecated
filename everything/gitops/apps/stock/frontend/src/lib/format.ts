export function formatNumber(n: number): string {
  return new Intl.NumberFormat("ko-KR").format(n);
}

export function formatCompactKRW(n: number): string {
  // quick KRW-friendly compact formatting (조/억 단위)
  const abs = Math.abs(n);
  const sign = n < 0 ? "-" : "";
  const jo = 1_0000_0000_0000; // 1조 = 10^12
  const eok = 1_0000_0000; // 1억 = 10^8

  if (abs >= jo) return `${sign}${(abs / jo).toFixed(2)}조`;
  if (abs >= eok) return `${sign}${(abs / eok).toFixed(2)}억`;
  return `${sign}${formatNumber(abs)}`;
}

export function formatPct(p: number | null): string {
  if (p === null || Number.isNaN(p)) return "—";
  const s = p >= 0 ? "+" : "";
  return `${s}${p.toFixed(1)}%`;
}


