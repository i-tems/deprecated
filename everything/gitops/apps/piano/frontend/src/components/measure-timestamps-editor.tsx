"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  parseTimeToSeconds,
  formatSecondsPrecise,
} from "@/lib/youtube";
import type { MeasureAnchor } from "@/lib/measure-timing";

interface Row {
  measure: string;
  seconds: string;
}

interface Props {
  songId: string;
  initial: MeasureAnchor[] | null;
  onDone: () => void;
}

function toRow(a: MeasureAnchor): Row {
  return { measure: String(a.measure), seconds: formatSecondsPrecise(a.seconds) };
}

export function MeasureTimestampsEditor({ songId, initial, onDone }: Props) {
  const queryClient = useQueryClient();
  const [rows, setRows] = useState<Row[]>(() =>
    initial && initial.length > 0
      ? [...initial].sort((a, b) => a.measure - b.measure).map(toRow)
      : [{ measure: "1", seconds: "0" }]
  );
  const [bulkInput, setBulkInput] = useState("");

  const parsed: ({ measure: number; seconds: number } | null)[] = rows.map(
    (r) => {
      const m = r.measure.trim();
      const s = r.seconds.trim();
      if (m === "" || s === "") return null;
      const mi = Number(m);
      if (!Number.isInteger(mi) || mi < 1) return null;
      const si = parseTimeToSeconds(s);
      if (si === null || si < 0) return null;
      return { measure: mi, seconds: si };
    }
  );

  const dupCheck = (() => {
    const seen = new Set<number>();
    for (const p of parsed) {
      if (p === null) continue;
      if (seen.has(p.measure)) return true;
      seen.add(p.measure);
    }
    return false;
  })();

  const allValid =
    rows.length > 0 && parsed.every((p) => p !== null) && !dupCheck;

  const saveMut = useMutation({
    mutationFn: (anchors: MeasureAnchor[] | null) =>
      api.put(`/api/admin/songs/${songId}`, {
        measure_timestamps: anchors,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["song", songId] });
      onDone();
    },
  });

  const handleSave = () => {
    if (!allValid) return;
    const anchors = (parsed as { measure: number; seconds: number }[]).sort(
      (a, b) => a.measure - b.measure
    );
    saveMut.mutate(anchors.length > 0 ? anchors : null);
  };

  const handleClear = () => saveMut.mutate(null);

  const handleBulkApply = () => {
    // Accept lines like "1 0:00", "1 0", "1, 0:00", "1\t0:00"
    const lines = bulkInput.split(/\r?\n/);
    const next: Row[] = [];
    for (const line of lines) {
      const trimmed = line.trim();
      if (trimmed === "") continue;
      const parts = trimmed.split(/[\s,]+/);
      if (parts.length < 2) continue;
      next.push({ measure: parts[0], seconds: parts[1] });
    }
    if (next.length > 0) {
      setRows(next);
      setBulkInput("");
    }
  };

  return (
    <div className="space-y-3">
      <div className="max-h-96 overflow-y-auto border border-toss-gray-200 rounded-lg">
        <table className="w-full text-sm">
          <thead className="bg-toss-gray-50 sticky top-0">
            <tr>
              <th className="text-left px-3 py-2 text-xs font-medium text-toss-gray-600 w-20">
                마디
              </th>
              <th className="text-left px-3 py-2 text-xs font-medium text-toss-gray-600">
                시간 (MM:SS 또는 초)
              </th>
              <th className="w-12" />
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => {
              const valid = parsed[i] !== null;
              return (
                <tr key={i} className="border-t border-toss-gray-100">
                  <td className="px-2 py-1">
                    <Input
                      type="number"
                      inputMode="numeric"
                      min={1}
                      value={r.measure}
                      onChange={(e) =>
                        setRows((prev) =>
                          prev.map((row, idx) =>
                            idx === i ? { ...row, measure: e.target.value } : row
                          )
                        )
                      }
                      className={`h-8 ${!valid && r.measure !== "" ? "border-toss-red" : ""}`}
                    />
                  </td>
                  <td className="px-2 py-1">
                    <Input
                      type="text"
                      value={r.seconds}
                      onChange={(e) =>
                        setRows((prev) =>
                          prev.map((row, idx) =>
                            idx === i ? { ...row, seconds: e.target.value } : row
                          )
                        )
                      }
                      className={`h-8 ${!valid && r.seconds !== "" ? "border-toss-red" : ""}`}
                    />
                  </td>
                  <td className="px-2 py-1 text-right">
                    <button
                      type="button"
                      onClick={() =>
                        setRows((prev) => prev.filter((_, idx) => idx !== i))
                      }
                      className="text-xs text-toss-gray-400 hover:text-toss-red px-2"
                    >
                      ×
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="flex items-center gap-2">
        <Button
          size="sm"
          variant="outline"
          className="rounded-md border-toss-gray-200 text-toss-gray-700"
          onClick={() => {
            const lastMeasure = rows.length
              ? Number(rows[rows.length - 1].measure) || 0
              : 0;
            setRows((prev) => [
              ...prev,
              { measure: String(lastMeasure + 1), seconds: "" },
            ]);
          }}
        >
          + 행 추가
        </Button>
        {dupCheck && (
          <span className="text-xs text-toss-red">중복 마디</span>
        )}
      </div>

      <details className="text-xs">
        <summary className="cursor-pointer text-toss-gray-500">
          여러 줄 붙여넣기
        </summary>
        <div className="mt-2 space-y-2">
          <textarea
            value={bulkInput}
            onChange={(e) => setBulkInput(e.target.value)}
            placeholder={"1 0:00\n2 0:01.4\n3 0:02.7\n..."}
            className="w-full h-32 text-xs font-mono border border-toss-gray-200 rounded-md p-2"
          />
          <Button
            size="sm"
            variant="outline"
            className="rounded-md"
            onClick={handleBulkApply}
            disabled={bulkInput.trim() === ""}
          >
            붙여넣기 적용 (기존 행 교체)
          </Button>
        </div>
      </details>

      <div className="flex gap-2">
        <Button
          size="sm"
          className="bg-toss-blue hover:bg-toss-blue-dark text-white rounded-md"
          onClick={handleSave}
          disabled={!allValid || saveMut.isPending}
        >
          {saveMut.isPending ? "저장 중..." : "저장"}
        </Button>
        <Button
          size="sm"
          variant="outline"
          className="rounded-md border-toss-gray-200 text-toss-gray-600"
          onClick={onDone}
          disabled={saveMut.isPending}
        >
          취소
        </Button>
        {initial && initial.length > 0 && (
          <Button
            size="sm"
            variant="outline"
            className="rounded-md border-toss-red text-toss-red ml-auto"
            onClick={handleClear}
            disabled={saveMut.isPending}
          >
            전체 제거
          </Button>
        )}
      </div>
    </div>
  );
}
