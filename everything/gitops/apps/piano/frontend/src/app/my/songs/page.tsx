"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api, {
  ATTRIBUTES,
  STATUS_LABELS,
  STATUS_COLORS,
  type UserSong,
  type Song,
} from "@/lib/api";
import { MiniRadarChart } from "@/components/radar-chart";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import Link from "next/link";

export default function MySongsPage() {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");

  const { data: mySongs = [] } = useQuery<UserSong[]>({
    queryKey: ["my-songs"],
    queryFn: () => api.get("/api/my/songs").then((r) => r.data),
  });

  const { data: catalog } = useQuery<{ items: Song[]; total: number }>({
    queryKey: ["songs-catalog", search],
    queryFn: () =>
      api.get("/api/songs", { params: { search, size: 50 } }).then((r) => r.data),
    enabled: open,
  });

  const addSong = useMutation({
    mutationFn: (songId: string) =>
      api.post("/api/my/songs", { song_id: songId }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["my-songs"] });
      queryClient.invalidateQueries({ queryKey: ["overview"] });
    },
  });

  const deleteSong = useMutation({
    mutationFn: (userSongId: string) =>
      api.delete(`/api/my/songs/${userSongId}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["my-songs"] });
      queryClient.invalidateQueries({ queryKey: ["overview"] });
    },
  });

  const mySongIds = new Set(mySongs.map((us) => us.song.id));

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-toss-gray-900">내 곡 목록</h1>
          <p className="text-sm text-toss-gray-500 mt-1">
            {mySongs.length}곡 등록됨
          </p>
        </div>
        <Dialog open={open} onOpenChange={setOpen}>
          <Button
            className="bg-toss-blue hover:bg-toss-blue-dark text-white rounded-md h-9 px-4 text-sm font-medium"
            onClick={() => setOpen(true)}
          >
            <svg
              className="w-4 h-4 mr-1.5"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={2}
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M12 4.5v15m7.5-7.5h-15"
              />
            </svg>
            곡 추가
          </Button>
          <DialogContent className="max-w-lg max-h-[80vh] overflow-y-auto">
            <DialogHeader>
              <DialogTitle>카탈로그에서 곡 추가</DialogTitle>
            </DialogHeader>
            <Input
              placeholder="곡 이름 또는 작곡가 검색..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="mb-4"
            />
            <div className="space-y-2">
              {catalog?.items.map((song) => {
                const added = mySongIds.has(song.id);
                return (
                  <div
                    key={song.id}
                    className="flex items-center justify-between p-3.5 rounded-xl bg-toss-gray-50 hover:bg-toss-gray-100 transition-colors"
                  >
                    <div>
                      <div className="font-medium text-toss-gray-900">{song.title}</div>
                      <div className="text-sm text-toss-gray-500">
                        {song.composer} · 난이도 {song.difficulty}/10
                      </div>
                    </div>
                    <Button
                      size="sm"
                      variant={added ? "secondary" : "default"}
                      disabled={added || addSong.isPending}
                      onClick={() => addSong.mutate(song.id)}
                      className={
                        added
                          ? "rounded-lg"
                          : "bg-toss-blue hover:bg-toss-blue-dark text-white rounded-lg"
                      }
                    >
                      {added ? "추가됨" : "추가"}
                    </Button>
                  </div>
                );
              })}
              {catalog?.items.length === 0 && (
                <div className="text-center text-toss-gray-400 py-8 text-sm">
                  검색 결과가 없습니다
                </div>
              )}
            </div>
          </DialogContent>
        </Dialog>
      </div>

      {mySongs.length === 0 ? (
        <div className="bg-card rounded-xl py-16 text-center text-toss-gray-400 border border-border text-sm">
          아직 등록한 곡이 없습니다. 카탈로그에서 곡을 추가해보세요.
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-3">
          {mySongs.map((us) => {
            const eval_ = us.latest_evaluation;
            const scores: Record<string, number> = {};
            let avg = 0;
            if (eval_) {
              ATTRIBUTES.forEach((a) => {
                scores[a.key] = eval_[a.key as keyof typeof eval_] as number;
              });
              avg =
                ATTRIBUTES.reduce(
                  (sum, a) =>
                    sum + (eval_[a.key as keyof typeof eval_] as number),
                  0
                ) / ATTRIBUTES.length;
            }

            return (
              <div
                key={us.id}
                className="bg-card rounded-xl border border-border transition-shadow"
              >
                <div className="p-4 flex items-center gap-4">
                  <Link href={`/my/songs/${us.id}`} className="shrink-0">
                    {eval_ ? (
                      <MiniRadarChart scores={scores} />
                    ) : (
                      <div className="w-[100px] h-[100px] flex items-center justify-center text-toss-gray-300 text-xs bg-toss-gray-50 rounded-xl">
                        미평가
                      </div>
                    )}
                  </Link>
                  <Link
                    href={`/my/songs/${us.id}`}
                    className="flex-1 min-w-0"
                  >
                    <div className="font-semibold text-lg text-toss-gray-900 truncate">
                      {us.song.title}
                    </div>
                    <div className="text-sm text-toss-gray-500">
                      {us.song.composer} · 난이도 {us.song.difficulty}/10
                    </div>
                    <div className="flex items-center gap-3 mt-2">
                      <Badge
                        className={`${STATUS_COLORS[us.status]} text-white text-xs`}
                      >
                        {STATUS_LABELS[us.status]}
                      </Badge>
                      {eval_ && (
                        <span className="text-sm text-toss-gray-500">
                          평균 {avg.toFixed(1)} / 5.0
                        </span>
                      )}
                    </div>
                  </Link>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="text-toss-gray-400 hover:text-toss-red hover:bg-red-50 shrink-0"
                    onClick={() => {
                      if (confirm("이 곡을 목록에서 제거할까요?")) {
                        deleteSong.mutate(us.id);
                      }
                    }}
                  >
                    <svg
                      className="w-4 h-4"
                      fill="none"
                      viewBox="0 0 24 24"
                      stroke="currentColor"
                      strokeWidth={1.5}
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        d="m14.74 9-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0"
                      />
                    </svg>
                  </Button>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
