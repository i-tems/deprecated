"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { apiGetJson } from "@/lib/api";
import { formatCompactKRW } from "@/lib/format";
import type { Company } from "@/lib/types";

type CompaniesResponse = { items: Company[] };

function SkeletonCard() {
  return (
    <div className="rounded-2xl border border-zinc-200 bg-white p-4">
      <div className="h-4 w-2/3 animate-pulse rounded bg-zinc-100" />
      <div className="mt-2 h-3 w-1/3 animate-pulse rounded bg-zinc-100" />
      <div className="mt-6 h-8 w-1/2 animate-pulse rounded bg-zinc-100" />
    </div>
  );
}

export default function Home() {
  const [items, setItems] = useState<Company[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        setError(null);
        const res = await apiGetJson<CompaniesResponse>("/companies");
        if (!cancelled) setItems(res.items);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const filtered = useMemo(() => {
    if (!items) return null;
    const q = query.trim().toLowerCase();
    if (!q) return items;
    return items.filter((c) => {
      return (
        c.name.toLowerCase().includes(q) || c.ticker.toLowerCase().includes(q)
      );
    });
  }, [items, query]);

  return (
    <main className="mx-auto max-w-6xl px-4 py-8">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">기업 목록</h1>
          <p className="mt-1 text-sm text-zinc-600">
            시가총액 내림차순 · 카드 클릭 시 디테일 페이지로 이동
          </p>
        </div>
        <div className="w-full sm:w-80">
          <label className="block text-xs font-medium text-zinc-600">
            검색(회사명/종목코드)
          </label>
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="예: 005930 또는 Samsung"
            className="mt-1 w-full rounded-xl border border-zinc-200 bg-white px-3 py-2 text-sm outline-none ring-0 focus:border-zinc-400"
          />
        </div>
      </div>

      {error && (
        <div className="mt-6 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800">
          API 오류: {error}
        </div>
      )}

      {/* Use grid (row-major) so market-cap sort shows left-to-right, then next row */}
      <div className="mt-8 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {items === null &&
          Array.from({ length: 8 }).map((_, i) => <SkeletonCard key={i} />)}

        {filtered?.map((c) => (
          <Link
            key={c.ticker}
            href={`/company/${encodeURIComponent(c.ticker)}`}
            className="block rounded-2xl border border-zinc-200 bg-white p-4 transition hover:border-zinc-400 hover:shadow-sm"
          >
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="text-sm font-semibold">{c.name}</div>
                <div className="mt-1 text-xs text-zinc-500">{c.ticker}</div>
              </div>
              <div className="rounded-lg bg-zinc-950 px-2 py-1 text-xs font-medium text-white">
                보기
              </div>
            </div>
            <div className="mt-6">
              <div className="text-xs text-zinc-500">시가총액</div>
              <div className="mt-1 text-lg font-semibold">
                {formatCompactKRW(c.marketCap)}{" "}
                <span className="text-xs font-medium text-zinc-500">
                  {c.currency}
                </span>
              </div>
            </div>
          </Link>
        ))}
      </div>

      {filtered && filtered.length === 0 && (
        <div className="mt-12 rounded-2xl border border-zinc-200 bg-white p-6 text-center">
          <div className="text-sm font-semibold">검색 결과 없음</div>
          <div className="mt-1 text-sm text-zinc-600">
            다른 키워드로 다시 시도해보세요.
          </div>
        </div>
      )}
    </main>
  );
}
