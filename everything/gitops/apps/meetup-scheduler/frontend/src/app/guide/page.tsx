"use client";

import { AppShell } from "@/components/app-shell";
import { Calendar, Sparkles, Users, RotateCcw, ImagePlus, MessageSquareText } from "lucide-react";

const sections = [
  {
    icon: Calendar,
    title: "내 스케줄 등록",
    color: "#3182f6",
    items: [
      "달력에서 날짜를 눌러 근무 일정을 등록하세요",
      "근무하는 날만 등록합니다 (야간, 주간, 당직 등)",
      "휴무/비번은 등록하지 마세요 — 빈 날 = 만날 수 있는 날",
    ],
  },
  {
    icon: Sparkles,
    title: "AI로 한번에 등록",
    color: "#7c3aed",
    items: [
      "오른쪽 하단 ✨ 버튼을 눌러 AI 일정 관리를 열어요",
      "근무표 사진을 찍어 올리면 자동으로 일정을 인식합니다",
      "텍스트로 입력해도 OK — \"4/15~18 주간, 4/20 야간\"",
      "AI가 분석한 결과를 확인 후 선택하여 반영하세요",
      "휴무는 자동으로 제외됩니다",
    ],
  },
  {
    icon: RotateCcw,
    title: "교대근무 패턴",
    color: "#e65100",
    items: [
      "반복되는 교대근무가 있다면 패턴을 등록하세요",
      "예: 주간→주간→야간→야간→비번→비번",
      "시작일을 설정하면 앞으로의 근무가 자동 생성됩니다",
      "패턴 일정은 🔁 표시가 붙고, 개별 수정/삭제가 안 됩니다",
    ],
  },
  {
    icon: Users,
    title: "그룹으로 약속 잡기",
    color: "#059669",
    items: [
      "그룹을 만들고 친구를 초대하세요 (링크 공유)",
      "모두의 스케줄을 한눈에 — 초록색일수록 많이 가능한 날",
      "상단 멤버 칩을 눌러 특정 사람끼리 가능한 날을 필터링",
      "날짜에 마우스를 올리면 누가 어떤 근무인지 확인 가능",
    ],
  },
  {
    icon: MessageSquareText,
    title: "팁",
    color: "#f59e0b",
    items: [
      "일정 블록 = \"이 날은 바쁩니다\"라는 뜻입니다",
      "아무것도 등록 안 한 날 = 만날 수 있는 날",
      "그래서 휴무를 등록하면 오히려 \"바쁨\"으로 잘못 표시돼요",
    ],
  },
];

export default function GuidePage() {
  return (
    <AppShell>
      <div className="page-header">
        <h1 className="text-lg font-bold">사용법</h1>
        <p className="text-sm" style={{ color: "var(--text-sub)", marginTop: 4 }}>
          교대근무, 일반근무, 프리랜서 — 다 달라도 약속은 잡을 수 있어요
        </p>
      </div>

      <div style={{ padding: "0 16px 32px", maxWidth: 640 }}>
        {sections.map((section) => (
          <div key={section.title} style={{ marginBottom: 24 }}>
            <div className="flex items-center gap-2.5" style={{ marginBottom: 10 }}>
              <div
                className="flex items-center justify-center"
                style={{
                  width: 32, height: 32, borderRadius: 10,
                  background: `${section.color}18`,
                }}
              >
                <section.icon size={17} style={{ color: section.color }} />
              </div>
              <h2 className="text-base font-bold" style={{ color: "var(--text)" }}>
                {section.title}
              </h2>
            </div>
            <ul style={{ margin: 0, paddingLeft: 20 }}>
              {section.items.map((item, i) => (
                <li
                  key={i}
                  className="text-sm"
                  style={{
                    color: "var(--text-sub)",
                    lineHeight: 1.7,
                    paddingLeft: 4,
                  }}
                >
                  {item}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </AppShell>
  );
}
