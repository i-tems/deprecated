"use client";

import { useEffect, useRef, useState } from "react";

export interface MeasureRange {
  start: number;
  end: number;
}

interface Props {
  abc: string;
  value: MeasureRange | null;
  onChange: (range: MeasureRange | null) => void;
  // 페이지별 system 개수. 예: [6,7,7,6] = 4 페이지 (6+7+7+6=26 systems).
  // 합이 실제 system 수보다 작으면 남는 system 들은 마지막 페이지에 모인다.
  // 합이 더 크면 마지막 빈 페이지는 무시.
  // 비어 있거나 미지정이면 단일 SVG 로 기존 방식 그대로 렌더 (페이지 분할 없음).
  pageBreaks?: number[] | null;
}

// 기본(unselected) 노트는 검정(컨테이너 text-black 으로 currentColor 따름).
// 선택은 진한 파랑, pending 은 진한 주황 — 검정 위에서 대비 분명하고 시끄럽지 않게.
// fill 은 abcjs note 자식 path 가 자체 fill 가질 때 부모가 묻히는 문제 회피 위해
// style.setProperty('!important') + 자식까지 재귀로 적용.
const COLOR_SELECTED = "#1565c0";
const COLOR_PENDING = "#ef6c00";

// staffwidth 1000: op10 처럼 V:2 가 복잡한 곡은 자연폭이 ~940 까지 가서 650 으로
// 두면 짧은 system 은 stretch 되지 않아 줄 폭·음표 간격이 들쭉날쭉해진다. 1000 이면
// 모든 system 자연폭을 넘어 abcjs 가 균일하게 stretch. responsive:"resize" 가
// 컨테이너 폭에 맞춰 SVG 를 자동 fit 하므로 화면 폭에는 영향 없다.
const STAFF_WIDTH = 1000;

interface ParsedAbc {
  header: string;
  voices: { name: string; systems: string[] }[];
}

// 헤더(K: 까지 + 후속 V:N <decl> 라인) / V:N body 마커로 시작하는 본문을 분리.
// 본문은 `$` 로 system 분할. 단일 voice (V: marker 없음) 일 경우 voices 가
// [{name:"1", systems:[...]}] 로 한 개.
function parseAbc(abc: string): ParsedAbc | null {
  const lines = abc.split("\n");
  let keyIdx = -1;
  for (let i = 0; i < lines.length; i++) {
    if (/^K:/.test(lines[i])) {
      keyIdx = i;
      break;
    }
  }
  if (keyIdx < 0) return null;

  let headerEnd = keyIdx;
  for (let i = keyIdx + 1; i < lines.length; i++) {
    if (/^V:\S+\s+\S/.test(lines[i])) {
      headerEnd = i;
    } else {
      break;
    }
  }

  const header = lines.slice(0, headerEnd + 1).join("\n");

  const voices: ParsedAbc["voices"] = [];
  let curName: string | null = null;
  let curContent = "";
  const flush = () => {
    if (curName === null) return;
    const systems = curContent
      .split("$")
      .map((s) => s.trim())
      .filter((s) => s.length > 0);
    voices.push({ name: curName, systems });
    curName = null;
    curContent = "";
  };

  for (let i = headerEnd + 1; i < lines.length; i++) {
    const m = lines[i].match(/^V:(\S+)\s*$/);
    if (m) {
      flush();
      curName = m[1];
    } else if (curName !== null) {
      curContent += lines[i] + "\n";
    } else if (lines[i].trim().length > 0) {
      // 본문이 voice marker 없이 시작 — 기본 voice 1 로 흡수
      curName = "1";
      curContent = lines[i] + "\n";
    }
  }
  flush();

  return { header, voices };
}

function buildPageAbc(
  parsed: ParsedAbc,
  startSystem: number,
  endSystem: number,
): string {
  let abc = parsed.header + "\n";
  for (const v of parsed.voices) {
    abc += `V:${v.name}\n`;
    const chunk = v.systems.slice(startSystem, endSystem);
    // 마지막 system 뒤에 `$` 안 붙임 — 페이지 끝.
    abc += chunk.join("$\n") + "\n";
  }
  return abc;
}

function computePageRanges(
  totalSystems: number,
  pageBreaks: number[] | null | undefined,
): { start: number; end: number }[] {
  if (!pageBreaks || pageBreaks.length === 0) {
    return [{ start: 0, end: totalSystems }];
  }
  const ranges: { start: number; end: number }[] = [];
  let cursor = 0;
  for (const count of pageBreaks) {
    if (cursor >= totalSystems) break;
    const end = Math.min(cursor + count, totalSystems);
    if (end > cursor) ranges.push({ start: cursor, end });
    cursor = end;
  }
  if (cursor < totalSystems) ranges.push({ start: cursor, end: totalSystems });
  return ranges;
}

// 마디 1 부터 시작. 픽업(anacrusis)은 마디 1 로 합쳐 본다 — abcjs 의 의미론과
// 일치시키지 않고 우리 measure_timestamps 와 일관되게 "사용자가 보는 첫 마디 = 1"
// 로 단순화.
export function SheetMusicMeasurePicker({ abc, value, onChange, pageBreaks }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const measureSvgsRef = useRef<Map<number, SVGElement[]>>(new Map());
  const [pending, setPending] = useState<number | null>(null);
  const [ready, setReady] = useState(false);
  const [renderError, setRenderError] = useState<string | null>(null);
  const [pageCount, setPageCount] = useState(1);

  useEffect(() => {
    let mounted = true;
    setReady(false);
    setPending(null);
    setRenderError(null);
    measureSvgsRef.current = new Map();

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    import("abcjs").then((abcjsModule: any) => {
      if (!mounted || !ref.current) return;

      const parsed = parseAbc(abc);
      const totalSystems = parsed?.voices[0]?.systems.length ?? 0;
      const hasBreaks =
        !!pageBreaks && pageBreaks.length > 0 && parsed !== null && totalSystems > 0;
      const ranges = hasBreaks
        ? computePageRanges(totalSystems, pageBreaks)
        : [{ start: 0, end: totalSystems }];

      // 컨테이너 초기화 + 페이지마다 child div 생성
      ref.current.innerHTML = "";
      const pageContainers: HTMLDivElement[] = [];
      ranges.forEach((_r, idx) => {
        const wrapper = document.createElement("div");
        if (hasBreaks) {
          wrapper.className =
            "pb-3 mb-3 border-b border-dashed border-toss-gray-200 last:border-b-0 last:pb-0 last:mb-0";
          const label = document.createElement("div");
          label.className = "text-[11px] font-medium text-toss-gray-400 mb-1";
          label.textContent = `페이지 ${idx + 1} / ${ranges.length}`;
          wrapper.appendChild(label);
        }
        const inner = document.createElement("div");
        wrapper.appendChild(inner);
        ref.current!.appendChild(wrapper);
        pageContainers.push(inner);
      });

      const measureMap = new Map<number, SVGElement[]>();
      let measureOffset = 0;
      const warnings: string[] = [];

      const pushSvgs = (m: number, svgs: SVGElement[]) => {
        const cur = measureMap.get(m) ?? [];
        cur.push(...svgs);
        measureMap.set(m, cur);
      };

      try {
        for (let p = 0; p < ranges.length; p++) {
          const { start, end } = ranges[p];
          const pageAbc = hasBreaks ? buildPageAbc(parsed!, start, end) : abc;

          // 페이지 로컬 startChar → 전역 measure 매핑. clickListener 가 이 페이지에서
          // 발화한 elem.startChar 로 마디를 찾는다.
          const pageCharMap = new Map<number, number>();
          const offsetCapture = measureOffset;
          const lookupMeasure = (startChar: number): number | null => {
            if (pageCharMap.has(startChar)) return pageCharMap.get(startChar)!;
            let ans: number | null = null;
            let bestKey = -1;
            for (const [k, v] of pageCharMap) {
              if (k <= startChar && k > bestKey) {
                bestKey = k;
                ans = v;
              }
            }
            return ans;
          };

          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          const tunes: any = abcjsModule.renderAbc(pageContainers[p], pageAbc, {
            staffwidth: STAFF_WIDTH,
            responsive: "resize",
            linebreak: "$",
            stretchlast: true,
            add_classes: true,
            paddingtop: 8,
            paddingbottom: 16,
            paddingleft: 8,
            paddingright: 8,
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            warningCallback: (msg: string) => {
              warnings.push(msg);
            },
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            clickListener: (abcelem: any) => {
              if (typeof abcelem?.startChar !== "number") return;
              const m = lookupMeasure(abcelem.startChar);
              if (m == null) return;
              handleClickRef.current(m);
            },
          });

          if (!pageContainers[p].querySelector("svg")) {
            if (mounted)
              setRenderError(
                hasBreaks
                  ? `페이지 ${p + 1} 악보 렌더 결과가 비어 있습니다.`
                  : "악보 렌더 결과가 비어 있습니다 (ABC 호환성 문제 가능).",
              );
            return;
          }

          // tune 의 line 들을 순회하며 measure 카운트. 한 line 안의 V:1·V:2 voice
          // 가 같은 시점의 마디를 공유 하므로 voice 마다 line 시작 measure 부터 카운트
          // 하고 line 끝 = 최대값. 페이지 시작 = measureOffset + 1 (m 은 1-indexed).
          let lastLineEndMeasure = 1;
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          const tunesArr: any[] = Array.isArray(tunes) ? tunes : [];
          for (const tune of tunesArr) {
            let measureAtLineStart = 1;
            for (const line of tune?.lines ?? []) {
              let lineEndMeasure = measureAtLineStart;
              for (const staffEntry of line?.staff ?? []) {
                for (const voice of staffEntry?.voices ?? []) {
                  let m = measureAtLineStart;
                  // eslint-disable-next-line @typescript-eslint/no-explicit-any
                  for (const elem of voice as any[]) {
                    const isBar = elem?.el_type === "bar";
                    if (!isBar) {
                      const globalM = offsetCapture + m;
                      if (typeof elem?.startChar === "number") {
                        pageCharMap.set(elem.startChar, globalM);
                      }
                      const rawSet = elem?.abselem?.elemset;
                      const svgEls: SVGElement[] = Array.isArray(rawSet)
                        ? rawSet.filter(
                            (x: unknown): x is SVGElement => x instanceof Element,
                          )
                        : [];
                      if (svgEls.length > 0) pushSvgs(globalM, svgEls);
                    }
                    if (isBar) m++;
                  }
                  if (m > lineEndMeasure) lineEndMeasure = m;
                }
              }
              measureAtLineStart = lineEndMeasure;
            }
            if (measureAtLineStart > lastLineEndMeasure)
              lastLineEndMeasure = measureAtLineStart;
          }

          // 다음 페이지 offset = 현 offset + (이 페이지에서 카운트된 마디 수).
          // lastLineEndMeasure 는 "다음에 올 마디 번호" (m 이 bar 뒤 +1 됨) 이므로
          // 카운트된 마디 수 = lastLineEndMeasure - 1.
          measureOffset += lastLineEndMeasure - 1;
        }
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        // eslint-disable-next-line no-console
        console.error("[SheetMusicMeasurePicker] abcjs render failed:", e);
        if (mounted) setRenderError(`악보 렌더 실패: ${msg}`);
        return;
      }

      if (warnings.length > 0) {
        // eslint-disable-next-line no-console
        console.warn("[SheetMusicMeasurePicker] abcjs warnings:", warnings);
      }

      measureSvgsRef.current = measureMap;
      if (mounted) {
        setPageCount(ranges.length);
        setReady(true);
      }
    });

    return () => {
      mounted = false;
    };
  }, [abc, pageBreaks]);

  // handleClick 은 최신 pending/value 를 캡쳐해야 하므로 ref 로 보관 — clickListener 가
  // useEffect 의 stale closure 를 잡지 않도록.
  const handleClickRef = useRef<(m: number) => void>(() => {});
  handleClickRef.current = (measure: number) => {
    // value 가 설정된 상태에서 클릭하면 — 선택 해제만. 새 pending 시작 안 함.
    // (사용자가 의도와 무관하게 새 선택이 시작되어 풀기 어려운 문제 회피)
    if (value !== null) {
      setPending(null);
      onChange(null);
      return;
    }
    // pending 상태에서 같은 마디 다시 클릭 → pending 해제 (취소).
    if (pending === measure) {
      setPending(null);
      return;
    }
    // pending 없음 → 첫 클릭 (pending 설정).
    if (pending == null) {
      setPending(measure);
      return;
    }
    // pending 있음 + 다른 마디 → 범위 완성.
    const start = Math.min(pending, measure);
    const end = Math.max(pending, measure);
    setPending(null);
    onChange({ start, end });
  };

  useEffect(() => {
    if (!ready) return;
    const map = measureSvgsRef.current;
    const paint = (el: Element, color: string) => {
      if (el instanceof SVGElement) {
        if (color) {
          el.style.setProperty("fill", color, "important");
          el.style.setProperty("stroke", color, "important");
        } else {
          el.style.removeProperty("fill");
          el.style.removeProperty("stroke");
        }
      }
      for (const child of Array.from(el.children)) paint(child, color);
    };
    map.forEach((svgs, m) => {
      const inRange = value != null && m >= value.start && m <= value.end;
      const isPending = pending === m;
      const color = inRange ? COLOR_SELECTED : isPending ? COLOR_PENDING : "";
      for (const el of svgs) paint(el, color);
    });
  }, [value, pending, ready, pageCount]);

  const status = pending != null
    ? `시작 ${pending}마디 · 끝 마디 클릭하세요 (다시 ${pending}마디 누르면 취소)`
    : value
      ? `선택: ${value.start === value.end ? `${value.start}마디` : `${value.start}–${value.end}마디`} · 악보 아무 곳이나 누르면 해제`
      : "악보의 마디를 두 번 클릭해 범위를 선택하세요";

  return (
    <div className="space-y-2">
      <div
        ref={ref}
        className="border border-toss-gray-200 rounded-lg p-3 bg-white text-black overflow-x-auto [&_svg]:max-w-full [&_svg]:h-auto [&_g[data-name]]:cursor-pointer"
      />
      {renderError && (
        <p className="text-xs text-toss-red">{renderError}</p>
      )}
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs text-toss-gray-500 flex-1">{status}</span>
        {(pending != null || value != null) && (
          <button
            type="button"
            onClick={() => {
              setPending(null);
              onChange(null);
            }}
            className="text-xs font-medium text-toss-blue hover:text-toss-blue-dark px-3 h-8 rounded-md border border-toss-blue/40 hover:bg-toss-blue-light shrink-0"
          >
            선택 해제
          </button>
        )}
      </div>
    </div>
  );
}
