"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  BarChart3,
  BookOpen,
  Clock,
  History,
  Play,
  RotateCcw,
  Sparkles,
  Target,
  TrendingUp,
  Trophy,
  Zap,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import api, {
  type SightReadingNoteStat,
  type SightReadingStats,
} from "@/lib/api";
import { cn } from "@/lib/utils";

type Clef = "treble" | "bass";
type WhiteLetter = "C" | "D" | "E" | "F" | "G" | "A" | "B";
type PitchName =
  | "C"
  | "C#"
  | "D"
  | "D#"
  | "E"
  | "F"
  | "F#"
  | "G"
  | "G#"
  | "A"
  | "A#"
  | "B";

type Note = {
  name: PitchName;
  letter: WhiteLetter;
  accidental?: "#";
  octave: number;
  midi: number;
  clef: Clef;
};

type GameState = "idle" | "running" | "gameover";
type Result = {
  type: "correct" | "wrong" | "timeout";
  expected: string;
  expectedMidi: number;
  actual?: string;
  actualMidi?: number;
};

const WHITE_KEY_LETTERS: WhiteLetter[] = ["C", "D", "E", "F", "G", "A", "B"];
const PITCHES: Array<{
  name: PitchName;
  letter: WhiteLetter;
  accidental?: "#";
}> = [
  { name: "C", letter: "C" },
  { name: "C#", letter: "C", accidental: "#" },
  { name: "D", letter: "D" },
  { name: "D#", letter: "D", accidental: "#" },
  { name: "E", letter: "E" },
  { name: "F", letter: "F" },
  { name: "F#", letter: "F", accidental: "#" },
  { name: "G", letter: "G" },
  { name: "G#", letter: "G", accidental: "#" },
  { name: "A", letter: "A" },
  { name: "A#", letter: "A", accidental: "#" },
  { name: "B", letter: "B" },
];
const NOTE_LABELS: Record<PitchName, string> = {
  C: "도",
  "C#": "도#",
  D: "레",
  "D#": "레#",
  E: "미",
  F: "파",
  "F#": "파#",
  G: "솔",
  "G#": "솔#",
  A: "라",
  "A#": "라#",
  B: "시",
};

const INITIAL_LIMIT_MS = 5000;
const OPTION_COUNT = 3;
const ALL_NOTES = createChromaticNotes(36, 83);
const INITIAL_NOTE = ALL_NOTES.find((note) => note.midi === 60) ?? ALL_NOTES[0];
const INITIAL_OPTIONS = createInitialOptions(INITIAL_NOTE);

function createChromaticNotes(minMidi: number, maxMidi: number) {
  const notes: Note[] = [];
  for (let midi = minMidi; midi <= maxMidi; midi += 1) {
    const pitch = PITCHES[midi % 12];
    notes.push({
      ...pitch,
      octave: Math.floor(midi / 12) - 1,
      midi,
      clef: midi < 60 ? "bass" : "treble",
    });
  }
  return notes;
}

function createInitialOptions(target: Note) {
  return createOptions(target);
}

function randomIndex(length: number) {
  if (typeof window !== "undefined" && window.crypto?.getRandomValues) {
    const value = new Uint32Array(1);
    window.crypto.getRandomValues(value);
    return value[0] % length;
  }
  return Math.floor(Math.random() * length);
}

function shuffle<T>(items: T[]) {
  const next = [...items];
  for (let i = next.length - 1; i > 0; i -= 1) {
    const j = randomIndex(i + 1);
    [next[i], next[j]] = [next[j], next[i]];
  }
  return next;
}

function noteWeight(stat: SightReadingNoteStat | undefined) {
  if (!stat) return 1;
  return Math.max(0.2, 1 + stat.wrong_count * 1.5 - stat.correct_count * 0.3);
}

function pickWeightedNote(
  statsByMidi: Map<number, SightReadingNoteStat>,
  previous?: Note
) {
  const candidates = previous
    ? ALL_NOTES.filter((note) => note.midi !== previous.midi)
    : ALL_NOTES;
  const weights = candidates.map((note) =>
    noteWeight(statsByMidi.get(pitchClassMidi(note.midi)))
  );
  const total = weights.reduce((sum, w) => sum + w, 0);
  if (total <= 0) return candidates[randomIndex(candidates.length)];

  const value = new Uint32Array(1);
  if (typeof window !== "undefined" && window.crypto?.getRandomValues) {
    window.crypto.getRandomValues(value);
  } else {
    value[0] = Math.floor(Math.random() * 0xffffffff);
  }
  let target = (value[0] / 0x100000000) * total;
  for (let i = 0; i < candidates.length; i += 1) {
    target -= weights[i];
    if (target <= 0) return candidates[i];
  }
  return candidates[candidates.length - 1];
}

function createOptions(target: Note) {
  const targetIdx = PITCHES.findIndex((p) => p.name === target.name);
  const offsets = shuffle([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]);
  const selected = new Map<PitchName, Note>([[target.name, target]]);

  for (const offset of offsets) {
    const idx = (targetIdx + offset) % 12;
    const pitch = PITCHES[idx];
    if (selected.has(pitch.name)) continue;
    const candidate: Note = {
      ...pitch,
      octave: target.octave,
      midi: target.midi - (target.midi % 12) + idx,
      clef: target.clef,
    };
    selected.set(pitch.name, candidate);
    if (selected.size === OPTION_COUNT) break;
  }

  return shuffle([...selected.values()]);
}

function noteName(note: Note) {
  return note.name;
}

function pitchClassMidi(midi: number) {
  return 60 + (midi % 12);
}

function koreanNoteName(note: Note) {
  return NOTE_LABELS[note.name];
}

function readableNoteName(note: Note) {
  return `${noteName(note)} (${koreanNoteName(note)})`;
}

function signedScore(score: number) {
  return score > 0 ? `+${score}` : `${score}`;
}

function diatonicIndex(note: Pick<Note, "letter" | "octave">) {
  return note.octave * 7 + WHITE_KEY_LETTERS.indexOf(note.letter);
}

function ordinal(value: number) {
  return `${value}번째`;
}

function staffPositionDescription(note: Note) {
  const reference =
    note.clef === "treble"
      ? ({ letter: "E", octave: 4 } as const)
      : ({ letter: "G", octave: 2 } as const);
  const steps = diatonicIndex(note) - diatonicIndex(reference);

  if (steps >= 0 && steps <= 8) {
    if (steps % 2 === 0) {
      return `오선 아래부터 ${ordinal(steps / 2 + 1)} 줄`;
    }
    return `오선 아래부터 ${ordinal((steps + 1) / 2)} 칸`;
  }

  if (steps > 8) {
    const above = steps - 8;
    if (above % 2 === 0) {
      return `오선 위 ${ordinal(above / 2)} 보조선`;
    }
    return `오선 위 ${ordinal((above + 1) / 2)} 보조칸`;
  }

  const below = Math.abs(steps);
  if (below % 2 === 0) {
    return `오선 아래 ${ordinal(below / 2)} 보조선`;
  }
  return `오선 아래 ${ordinal((below + 1) / 2)} 보조칸`;
}

function explainNote(note: Note) {
  const clefLabel = note.clef === "treble" ? "높은음자리표" : "낮은음자리표";
  const lines: string[] = [
    `${clefLabel}에서 이 음표 머리는 ${staffPositionDescription(note)}에 있습니다.`,
    `줄과 칸을 한 칸씩 오를 때마다 C-D-E-F-G-A-B 순서로 읽으면 ${note.letter} 자리입니다.`,
  ];

  lines.push(
    note.accidental
      ? `앞에 #이 붙어 ${note.letter}에서 반음 올라간 ${note.name}입니다.`
      : `앞에 #이 없어서 ${note.letter} 그대로, ${note.name}입니다.`
  );

  return lines;
}

function Staff({ note }: { note: Note }) {
  const bottomLineY = 140;
  const lineGap = 20;
  const halfStep = lineGap / 2;
  const noteX = 242;
  const clefLabel = note.clef === "treble" ? "높은음자리표" : "낮은음자리표";
  const clefSymbol = note.clef === "treble" ? "𝄞" : "𝄢";
  const clefX = note.clef === "treble" ? 76 : 78;
  const clefY = note.clef === "treble" ? 103 : 106;
  const clefSize = note.clef === "treble" ? 78 : 64;
  const reference =
    note.clef === "treble"
      ? ({ letter: "E", octave: 4 } as const)
      : ({ letter: "G", octave: 2 } as const);
  const y =
    bottomLineY - (diatonicIndex(note) - diatonicIndex(reference)) * halfStep;
  const staffTop = bottomLineY - lineGap * 4;
  const ledgerLines: number[] = [];

  for (let ledgerY = bottomLineY + lineGap; ledgerY <= y + 1; ledgerY += lineGap) {
    ledgerLines.push(ledgerY);
  }
  for (let ledgerY = staffTop - lineGap; ledgerY >= y - 1; ledgerY -= lineGap) {
    ledgerLines.push(ledgerY);
  }

  const minY = Math.min(0, staffTop - 36, y - 56);
  const maxY = Math.max(220, bottomLineY + 36, y + 56);

  return (
    <svg
      viewBox={`0 ${minY} 420 ${maxY - minY}`}
      role="img"
      aria-label={`${clefLabel} ${readableNoteName(note)}`}
      className="h-full max-h-[300px] w-full"
    >
      <rect x="0" y={minY} width="420" height={maxY - minY} rx="18" fill="#14151A" />
      <rect
        x="48"
        y={minY + 12}
        width="96"
        height="24"
        rx="12"
        fill="#1E2030"
      />
      <text
        x="96"
        y={minY + 28}
        fill="#5E6AD2"
        fontSize="12"
        fontWeight="700"
        fontFamily="ui-sans-serif, system-ui"
        textAnchor="middle"
      >
        {clefLabel}
      </text>
      {[0, 1, 2, 3, 4].map((line) => (
        <line
          key={line}
          x1="58"
          x2="374"
          y1={staffTop + line * lineGap}
          y2={staffTop + line * lineGap}
          stroke="#6E7178"
          strokeWidth="2"
          strokeLinecap="round"
        />
      ))}
      <text
        x={clefX}
        y={clefY}
        fill="#C8CBD1"
        fontSize={clefSize}
        fontFamily='"Noto Music", "Bravura", "Apple Symbols", "Segoe UI Symbol", serif'
        dominantBaseline="middle"
      >
        {clefSymbol}
      </text>
      {ledgerLines.map((ledgerY) => (
        <line
          key={ledgerY}
          x1={noteX - 25}
          x2={noteX + 25}
          y1={ledgerY}
          y2={ledgerY}
          stroke="#6E7178"
          strokeWidth="2"
          strokeLinecap="round"
        />
      ))}
      {note.accidental && (
        <text
          x={noteX - 58}
          y={y + 12}
          fill="#C8CBD1"
          fontSize="34"
          fontWeight="700"
          fontFamily="ui-sans-serif, system-ui"
        >
          #
        </text>
      )}
      <ellipse
        cx={noteX}
        cy={y}
        rx="16"
        ry="11"
        fill="#C8CBD1"
        transform={`rotate(-18 ${noteX} ${y})`}
      />
      <line
        x1={noteX + 14}
        x2={noteX + 14}
        y1={y}
        y2={y < 104 ? y + 70 : y - 70}
        stroke="#C8CBD1"
        strokeWidth="4"
        strokeLinecap="round"
      />
    </svg>
  );
}

function AnswerGrid({
  options,
  onAnswer,
  disabled,
  result,
}: {
  options: Note[];
  onAnswer: (note: Note) => void;
  disabled: boolean;
  result: Result | null;
}) {
  return (
    <div className="grid grid-cols-3 gap-2">
      {options.map((option, index) => {
        const optionMidi = pitchClassMidi(option.midi);
        const isExpected = result && optionMidi === result.expectedMidi;
        const isWrongPick =
          result?.type === "wrong" && optionMidi === result.actualMidi;

        return (
          <button
            key={noteName(option)}
            type="button"
            disabled={disabled}
            onClick={() => onAnswer(option)}
            className={cn(
              "relative h-20 rounded-xl border bg-card text-left border border-border transition hover:-translate-y-0.5 hover:border-toss-blue hover:bg-toss-blue-light active:scale-[0.99] disabled:pointer-events-none",
              result ? "opacity-100" : "border-toss-gray-200 disabled:opacity-60",
              isExpected && "border-toss-green bg-emerald-50 ring-1 ring-toss-green/30",
              isWrongPick && "border-toss-red bg-red-50 ring-1 ring-toss-red/25"
            )}
            aria-label={`${readableNoteName(option)} 선택`}
          >
            <kbd className="absolute right-3 top-3 rounded-md bg-toss-gray-100 px-2 py-0.5 text-xs font-semibold text-toss-gray-500">
              {index + 1}
            </kbd>
            <span className="block px-4 text-xl font-semibold text-toss-gray-900">
              {noteName(option)}
            </span>
            <span className="block px-4 text-xs font-semibold text-toss-gray-400">
              {koreanNoteName(option)}
            </span>
          </button>
        );
      })}
    </div>
  );
}

export default function SightReadingPage() {
  const queryClient = useQueryClient();
  const { data: stats } = useQuery<SightReadingStats>({
    queryKey: ["sight-reading-stats"],
    queryFn: () => api.get("/api/my/sight-reading/stats").then((r) => r.data),
  });
  const [currentNote, setCurrentNote] = useState<Note>(INITIAL_NOTE);
  const [options, setOptions] = useState<Note[]>(INITIAL_OPTIONS);
  const [gameState, setGameState] = useState<GameState>("idle");
  const [locked, setLocked] = useState(false);
  const [roundLimit, setRoundLimit] = useState(INITIAL_LIMIT_MS);
  const [remainingMs, setRemainingMs] = useState(INITIAL_LIMIT_MS);
  const [score, setScore] = useState(0);
  const [bestScore, setBestScore] = useState(0);
  const [streak, setStreak] = useState(0);
  const [reactionTimes, setReactionTimes] = useState<number[]>([]);
  const [lastResult, setLastResult] = useState<Result | null>(null);
  const [recordingError, setRecordingError] = useState(false);
  const roundStartedAt = useRef(0);
  const sessionStartedAt = useRef(0);
  const nextRoundTimer = useRef<number | null>(null);

  const averageReaction =
    reactionTimes.length === 0
      ? 0
      : Math.round(
          reactionTimes.reduce((sum, time) => sum + time, 0) /
            reactionTimes.length
        );
  const progress = Math.max(0, Math.min(100, (remainingMs / roundLimit) * 100));
  const isDanger = gameState === "running" && progress <= 35;
  const boardState =
    lastResult?.type === "correct"
      ? "correct"
      : gameState === "gameover"
        ? "gameover"
        : "normal";
  const speedLabel = `${(roundLimit / 1000).toFixed(1)}초`;
  const savedBestScore = Math.max(bestScore, stats?.best_score ?? 0, score);
  const growthLabel =
    stats?.previous_average_score === null
      ? "기록 대기"
      : `${stats && stats.score_growth > 0 ? "+" : ""}${stats?.score_growth.toFixed(1) ?? "0.0"}`;

  const noteStatsByMidi = useMemo(() => {
    const map = new Map<number, SightReadingNoteStat>();
    for (const note of stats?.all_notes ?? []) {
      map.set(note.midi, note);
    }
    return map;
  }, [stats?.all_notes]);

  const currentNoteStat = noteStatsByMidi.get(pitchClassMidi(currentNote.midi));

  const prepareRound = useCallback(
    (limit: number, previous?: Note) => {
      const next = pickWeightedNote(noteStatsByMidi, previous);
      setCurrentNote(next);
      setOptions(createOptions(next));
      setRoundLimit(limit);
      setRemainingMs(limit);
      setLastResult(null);
      setLocked(false);
    },
    [noteStatsByMidi]
  );

  const resetSession = useCallback(() => {
    if (nextRoundTimer.current) {
      window.clearTimeout(nextRoundTimer.current);
      nextRoundTimer.current = null;
    }
    setGameState("idle");
    setLocked(false);
    setRoundLimit(INITIAL_LIMIT_MS);
    setRemainingMs(INITIAL_LIMIT_MS);
    setScore(0);
    setStreak(0);
    setReactionTimes([]);
    setLastResult(null);
    setRecordingError(false);
    sessionStartedAt.current = 0;
    setCurrentNote(INITIAL_NOTE);
    setOptions(INITIAL_OPTIONS);
  }, []);

  const startSession = useCallback(() => {
    if (nextRoundTimer.current) {
      window.clearTimeout(nextRoundTimer.current);
      nextRoundTimer.current = null;
    }
    setScore(0);
    setStreak(0);
    setReactionTimes([]);
    setLastResult(null);
    setRecordingError(false);
    sessionStartedAt.current = Date.now();
    setGameState("running");
    prepareRound(INITIAL_LIMIT_MS);
  }, [prepareRound]);

  const scheduleNextRound = useCallback(
    (nextLimit: number) => {
      nextRoundTimer.current = window.setTimeout(() => {
        prepareRound(nextLimit, currentNote);
        nextRoundTimer.current = null;
      }, 520);
    },
    [currentNote, prepareRound]
  );

  const recordSession = useCallback(
    async (result: Result) => {
      const endedReason = result.type === "timeout" ? "timeout" : "wrong";
      const durationSeconds = sessionStartedAt.current
        ? Math.max(0, Math.round((Date.now() - sessionStartedAt.current) / 1000))
        : 0;
      const averageReactionMs =
        reactionTimes.length === 0
          ? null
          : Math.round(
              reactionTimes.reduce((sum, time) => sum + time, 0) /
                reactionTimes.length
            );

      try {
        await api.post("/api/my/sight-reading/sessions", {
          score,
          correct_count: score,
          average_reaction_ms: averageReactionMs,
          fastest_limit_ms: roundLimit,
          duration_seconds: durationSeconds,
          ended_reason: endedReason,
          expected_note: result.expected,
          actual_note: result.actual ?? null,
        });
        await queryClient.invalidateQueries({
          queryKey: ["sight-reading-stats"],
        });
      } catch {
        setRecordingError(true);
      }
    },
    [queryClient, reactionTimes, roundLimit, score]
  );

  const recordAttempt = useCallback(
    async ({
      expected,
      actual,
      wasCorrect,
      reactionMs,
    }: {
      expected: Note;
      actual?: Note;
      wasCorrect: boolean;
      reactionMs: number | null;
    }) => {
      try {
        await api.post("/api/my/sight-reading/attempts", {
          expected_note: readableNoteName(expected),
          expected_midi: pitchClassMidi(expected.midi),
          actual_note: actual ? readableNoteName(actual) : null,
          actual_midi: actual ? pitchClassMidi(actual.midi) : null,
          was_correct: wasCorrect,
          reaction_ms: reactionMs,
        });
        await queryClient.invalidateQueries({
          queryKey: ["sight-reading-stats"],
        });
      } catch {
        setRecordingError(true);
      }
    },
    [queryClient]
  );

  const finishGame = useCallback(
    (result: Result) => {
      if (nextRoundTimer.current) {
        window.clearTimeout(nextRoundTimer.current);
        nextRoundTimer.current = null;
      }
      setBestScore((value) => Math.max(value, score));
      setGameState("gameover");
      setRemainingMs(0);
      setLastResult(result);
      setLocked(true);
      void recordSession(result);
    },
    [recordSession, score]
  );

  const handleMiss = useCallback(() => {
    if (gameState !== "running" || locked) return;

    void recordAttempt({
      expected: currentNote,
      wasCorrect: false,
      reactionMs: null,
    });
    finishGame({
      type: "timeout",
      expected: readableNoteName(currentNote),
      expectedMidi: currentNote.midi,
    });
  }, [currentNote, finishGame, gameState, locked, recordAttempt]);

  useEffect(() => {
    if (gameState !== "running" || locked) return;

    const startedAt = Date.now();
    roundStartedAt.current = startedAt;

    const interval = window.setInterval(() => {
      setRemainingMs(Math.max(0, roundLimit - (Date.now() - startedAt)));
    }, 50);
    const timeout = window.setTimeout(handleMiss, roundLimit);

    return () => {
      window.clearInterval(interval);
      window.clearTimeout(timeout);
    };
  }, [currentNote, gameState, handleMiss, locked, roundLimit]);

  useEffect(() => {
    return () => {
      if (nextRoundTimer.current) {
        window.clearTimeout(nextRoundTimer.current);
      }
    };
  }, []);

  const handleAnswer = useCallback((selected: Note) => {
    if (gameState !== "running" || locked) return;

    const correct = selected.name === currentNote.name;
    const reactionMs = Date.now() - roundStartedAt.current;
    setLocked(true);

    if (!correct) {
      void recordAttempt({
        expected: currentNote,
        actual: selected,
        wasCorrect: false,
        reactionMs,
      });
      finishGame({
        type: "wrong",
        expected: readableNoteName(currentNote),
        expectedMidi: pitchClassMidi(currentNote.midi),
        actual: readableNoteName(selected),
        actualMidi: pitchClassMidi(selected.midi),
      });
      return;
    }

    void recordAttempt({
      expected: currentNote,
      actual: selected,
      wasCorrect: true,
      reactionMs,
    });
    setScore((value) => value + 1);
    setStreak((value) => value + 1);
    setReactionTimes((value) => [...value, reactionMs]);
    setLastResult({
      type: "correct",
      expected: readableNoteName(currentNote),
      expectedMidi: pitchClassMidi(currentNote.midi),
      actual: readableNoteName(selected),
      actualMidi: pitchClassMidi(selected.midi),
    });
    scheduleNextRound(roundLimit);
  }, [currentNote, finishGame, gameState, locked, recordAttempt, roundLimit, scheduleNextRound]);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const isTyping =
        target?.tagName === "INPUT" ||
        target?.tagName === "TEXTAREA" ||
        target?.isContentEditable;

      if (isTyping || event.metaKey || event.ctrlKey || event.altKey) return;

      if (gameState === "running") {
        const optionIndex = Number(event.key) - 1;
        if (optionIndex >= 0 && optionIndex < options.length) {
          event.preventDefault();
          handleAnswer(options[optionIndex]);
        }
        return;
      }

      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        startSession();
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [gameState, handleAnswer, options, startSession]);

  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-toss-gray-900">
            악보 리딩 훈련
          </h1>
          <p className="mt-1 text-sm text-toss-gray-500">
            틀리면 끝. 5초 안에 음 이름을 고르는 악보 읽기 게임입니다
          </p>
        </div>
        <Button
          type="button"
          onClick={gameState === "running" ? resetSession : startSession}
          className="h-10 bg-toss-blue px-4 text-white hover:bg-toss-blue-dark"
        >
          {gameState === "running" ? (
            <RotateCcw className="size-4" />
          ) : (
            <Play className="size-4" />
          )}
          {gameState === "running" ? "재시작" : "게임 시작"}
        </Button>
      </div>

      <section
        className={cn(
          "rounded-xl bg-card p-4 border border-border transition-all duration-300 sm:p-5",
          boardState === "correct" && "ring-2 ring-toss-green/40",
          boardState === "gameover" && "ring-2 ring-toss-red/30",
          gameState === "running" && "shadow-md"
        )}
      >
        <div className="mb-3 flex items-center justify-between gap-3">
          <div className="text-sm font-semibold text-toss-gray-500">
            현재 속도 {speedLabel}
          </div>
          <div className="text-sm font-semibold text-toss-gray-900">
            {gameState === "running" ? `${(remainingMs / 1000).toFixed(1)}초` : "대기"}
          </div>
        </div>
        <div className="h-2 overflow-hidden rounded-full bg-toss-gray-100">
          <div
            className={cn(
              "h-full rounded-full transition-[width] duration-75",
              isDanger
                ? "animate-pulse bg-toss-red"
                : "bg-gradient-to-r from-toss-blue to-toss-green"
            )}
            style={{ width: `${gameState === "running" ? progress : 100}%` }}
          />
        </div>

        <div
          className={cn(
            "relative mt-4 flex h-[300px] items-center justify-center overflow-hidden rounded-xl bg-toss-gray-50 p-3 transition-colors sm:h-[340px]",
            boardState === "correct" && "bg-emerald-50",
            isDanger && "bg-red-50"
          )}
        >
          <div className="absolute right-3 top-3 flex gap-1.5">
            <span className="rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-semibold text-toss-green">
              정답 {currentNoteStat?.correct_count ?? 0}
            </span>
            <span className="rounded-full bg-red-50 px-2.5 py-1 text-xs font-semibold text-toss-red">
              오답 {currentNoteStat?.wrong_count ?? 0}
            </span>
          </div>
          <Staff note={currentNote} />
        </div>

        <div
          className={cn(
            "mt-3 rounded-xl px-4 py-3 text-sm font-semibold",
            lastResult?.type === "correct"
              ? "bg-emerald-50 text-toss-green"
              : lastResult
                ? "bg-red-50 text-toss-red"
                : "bg-toss-blue-light text-toss-blue"
          )}
        >
          {lastResult
            ? lastResult.type === "correct"
              ? `정답 ${lastResult.expected}`
              : lastResult.type === "timeout"
                ? `시간 초과. 정답은 ${lastResult.expected}`
                : `${lastResult.actual} 선택. 정답은 ${lastResult.expected}`
            : gameState === "running"
              ? "3개 중 하나를 고르세요"
              : "음 이름만 맞추면 정답, 검은건반 포함"}
        </div>
        {gameState === "gameover" && (
          <div className="mt-3 rounded-xl bg-toss-gray-50 px-4 py-3">
            <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
              <div>
                <div className="text-xs font-semibold text-toss-gray-500">
                  GAME OVER · {score}점 · 최고 기록 {savedBestScore}
                </div>
                <div className="mt-0.5 text-sm font-semibold text-toss-gray-900">
                  방금 나온 음표 그대로 복습: 정답 {lastResult?.expected}
                </div>
              </div>
              <Button
                type="button"
                onClick={startSession}
                className="h-10 bg-toss-gray-900 px-5 text-white hover:bg-toss-gray-800"
              >
                <Play className="size-4" />
                다시 도전
              </Button>
            </div>
            <div className="mt-3 rounded-lg bg-card px-3 py-3">
              <div className="text-xs font-semibold text-toss-gray-500">
                왜 정답인가
              </div>
              <div className="mt-2 space-y-1.5 text-sm font-medium leading-5 text-toss-gray-700">
                {explainNote(currentNote).map((line) => (
                  <div key={line}>{line}</div>
                ))}
              </div>
            </div>
          </div>
        )}
        {recordingError && (
          <div className="mt-3 rounded-xl bg-red-50 px-4 py-3 text-sm font-semibold text-toss-red">
            이번 기록 저장에 실패했습니다. 네트워크 상태를 확인한 뒤 다시 시도하세요.
          </div>
        )}
      </section>

      <AnswerGrid
        options={options}
        disabled={gameState !== "running" || locked}
        onAnswer={handleAnswer}
        result={gameState === "gameover" ? lastResult : null}
      />

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div className="rounded-xl bg-card p-4 border border-border">
          <div className="flex items-center gap-2 text-xs font-semibold text-toss-gray-500">
            <Target className="size-4" />
            점수
          </div>
          <div className="mt-1 text-2xl font-semibold text-toss-blue">{score}</div>
        </div>
        <div className="rounded-xl bg-card p-4 border border-border">
          <div className="flex items-center gap-2 text-xs font-semibold text-toss-gray-500">
            <Zap className="size-4" />
            속도
          </div>
          <div className="mt-1 text-2xl font-semibold text-toss-orange">
            {speedLabel}
          </div>
        </div>
        <div className="rounded-xl bg-card p-4 border border-border">
          <div className="flex items-center gap-2 text-xs font-semibold text-toss-gray-500">
            <Trophy className="size-4" />
            최고
          </div>
          <div className="mt-1 text-2xl font-semibold text-toss-green">
            {savedBestScore}
          </div>
        </div>
        <div className="rounded-xl bg-card p-4 border border-border">
          <div className="flex items-center gap-2 text-xs font-semibold text-toss-gray-500">
            <Sparkles className="size-4" />
            콤보
          </div>
          <div className="mt-1 text-2xl font-semibold text-toss-gray-900">
            {streak}
          </div>
          {averageReaction > 0 && (
            <div className="mt-0.5 text-xs text-toss-gray-400">
              평균 {(averageReaction / 1000).toFixed(1)}초
            </div>
          )}
        </div>
      </div>

      <section className="rounded-xl bg-card p-4 border border-border sm:p-5">
        <div className="mb-4 flex items-center justify-between gap-3">
          <div>
            <h2 className="text-base font-semibold text-toss-gray-900">
              기본 읽는 법
            </h2>
            <p className="mt-0.5 text-sm text-toss-gray-500">
              음 이름만 빠르게 맞추면 됩니다 (옥타브는 무시)
            </p>
          </div>
          <BookOpen className="size-5 text-toss-gray-400" />
        </div>

        <div className="rounded-xl bg-toss-gray-50 p-3">
          <div className="text-sm font-semibold text-toss-gray-900">
            음 이름
          </div>
          <div className="mt-2 grid grid-cols-7 gap-1.5">
            {[
              ["C", "도"],
              ["D", "레"],
              ["E", "미"],
              ["F", "파"],
              ["G", "솔"],
              ["A", "라"],
              ["B", "시"],
            ].map(([letter, label]) => (
              <div
                key={letter}
                className="rounded-lg bg-card px-2 py-2 text-center"
              >
                <div className="text-sm font-semibold text-toss-gray-900">
                  {letter}
                </div>
                <div className="text-xs font-semibold text-toss-gray-500">
                  {label}
                </div>
              </div>
            ))}
          </div>
          <div className="mt-2 space-y-2 text-sm font-medium leading-5 text-toss-gray-600">
            <div>
              오선에서 한 줄 또는 한 칸씩 올라갈 때마다 C-D-E-F-G-A-B 순서로
              반복됩니다.
            </div>
            <div>
              <span className="font-semibold text-toss-gray-900">#</span>은 샵입니다.
              원래 음보다 오른쪽 검은건반으로 반음 높게 칩니다. 예: C#은 도#.
            </div>
            <div>
              <span className="font-semibold text-toss-gray-900">b</span>은 플랫입니다.
              원래 음보다 왼쪽 검은건반으로 반음 낮게 칩니다. 예: Bb은 시b.
            </div>
          </div>
        </div>

      </section>

      <section className="rounded-xl bg-card p-4 border border-border sm:p-5">
        <div className="mb-4 flex items-center justify-between gap-3">
          <div>
            <h2 className="text-base font-semibold text-toss-gray-900">
              성장 기록
            </h2>
            <p className="mt-0.5 text-sm text-toss-gray-500">
              게임이 끝날 때마다 로그인한 사용자 기준으로 저장됩니다
            </p>
          </div>
          <History className="size-5 text-toss-gray-400" />
        </div>

        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <div className="rounded-xl bg-toss-gray-50 p-3">
            <div className="flex items-center gap-1.5 text-xs font-semibold text-toss-gray-500">
              <BarChart3 className="size-3.5" />
              누적
            </div>
            <div className="mt-1 text-xl font-semibold text-toss-gray-900">
              {stats?.total_sessions ?? 0}회
            </div>
          </div>
          <div className="rounded-xl bg-toss-gray-50 p-3">
            <div className="flex items-center gap-1.5 text-xs font-semibold text-toss-gray-500">
              <Target className="size-3.5" />
              전체 평균
            </div>
            <div className="mt-1 text-xl font-semibold text-toss-blue">
              {stats?.average_score.toFixed(1) ?? "0.0"}
            </div>
          </div>
          <div className="rounded-xl bg-toss-gray-50 p-3">
            <div className="flex items-center gap-1.5 text-xs font-semibold text-toss-gray-500">
              <TrendingUp className="size-3.5" />
              최근 성장
            </div>
            <div
              className={cn(
                "mt-1 text-xl font-semibold",
                (stats?.score_growth ?? 0) >= 0
                  ? "text-toss-green"
                  : "text-toss-red"
              )}
            >
              {growthLabel}
            </div>
          </div>
          <div className="rounded-xl bg-toss-gray-50 p-3">
            <div className="flex items-center gap-1.5 text-xs font-semibold text-toss-gray-500">
              <Clock className="size-3.5" />
              평균 반응
            </div>
            <div className="mt-1 text-xl font-semibold text-toss-orange">
              {stats?.average_reaction_ms
                ? `${(stats.average_reaction_ms / 1000).toFixed(1)}초`
                : "-"}
            </div>
          </div>
        </div>

        <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-2">
          <div className="rounded-xl border border-toss-gray-100 p-3">
            <div className="mb-2 text-sm font-semibold text-toss-gray-900">
              약한 음
            </div>
            {stats?.weakest_notes.length ? (
              <div className="space-y-2">
                {stats.weakest_notes.slice(0, 5).map((note) => (
                  <div
                    key={`weak-${note.midi}`}
                    className="flex items-center justify-between gap-3"
                  >
                    <div className="min-w-0">
                      <div className="truncate text-sm font-semibold text-toss-gray-900">
                        {note.note}
                      </div>
                      <div className="text-xs text-toss-gray-500">
                        정답 {note.correct_count}회 · 오답 {note.wrong_count}회
                      </div>
                    </div>
                    <div
                      className={cn(
                        "shrink-0 text-lg font-semibold",
                        note.score < 0 ? "text-toss-red" : "text-toss-gray-600"
                      )}
                    >
                      {signedScore(note.score)}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="rounded-lg bg-toss-gray-50 px-3 py-5 text-center text-sm text-toss-gray-500">
                라운드 기록이 쌓이면 표시됩니다
              </div>
            )}
          </div>

          <div className="rounded-xl border border-toss-gray-100 p-3">
            <div className="mb-2 text-sm font-semibold text-toss-gray-900">
              강한 음
            </div>
            {stats?.strongest_notes.length ? (
              <div className="space-y-2">
                {stats.strongest_notes.slice(0, 5).map((note) => (
                  <div
                    key={`strong-${note.midi}`}
                    className="flex items-center justify-between gap-3"
                  >
                    <div className="min-w-0">
                      <div className="truncate text-sm font-semibold text-toss-gray-900">
                        {note.note}
                      </div>
                      <div className="text-xs text-toss-gray-500">
                        정답 {note.correct_count}회 · 오답 {note.wrong_count}회
                      </div>
                    </div>
                    <div
                      className={cn(
                        "shrink-0 text-lg font-semibold",
                        note.score > 0 ? "text-toss-green" : "text-toss-gray-600"
                      )}
                    >
                      {signedScore(note.score)}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="rounded-lg bg-toss-gray-50 px-3 py-5 text-center text-sm text-toss-gray-500">
                라운드 기록이 쌓이면 표시됩니다
              </div>
            )}
          </div>
        </div>

        {stats?.recent_sessions.length ? (
          <div className="mt-4 space-y-2">
            {stats.recent_sessions.slice(0, 5).map((session) => (
              <div
                key={session.id}
                className="flex items-center justify-between rounded-xl border border-toss-gray-100 px-3 py-2"
              >
                <div>
                  <div className="text-sm font-semibold text-toss-gray-900">
                    {session.score}점
                  </div>
                  <div className="text-xs text-toss-gray-500">
                    {session.expected_note}
                    {session.actual_note ? ` · 선택 ${session.actual_note}` : ""}
                  </div>
                </div>
                <div className="text-right text-xs text-toss-gray-500">
                  <div>
                    {new Date(session.created_at).toLocaleDateString("ko-KR", {
                      month: "short",
                      day: "numeric",
                    })}
                  </div>
                  <div>
                    {session.average_reaction_ms
                      ? `${(session.average_reaction_ms / 1000).toFixed(1)}초`
                      : "반응 기록 없음"}
                  </div>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="mt-4 rounded-xl bg-toss-gray-50 px-4 py-6 text-center text-sm text-toss-gray-500">
            아직 저장된 훈련 기록이 없습니다
          </div>
        )}
      </section>
    </div>
  );
}
