import axios from "axios";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const api = axios.create({
  baseURL: API_URL,
});

api.interceptors.request.use((config) => {
  if (typeof window !== "undefined") {
    const token = localStorage.getItem("token");
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
  }
  return config;
});

api.interceptors.response.use(
  (res) => res,
  (error) => {
    if (error.response?.status === 401 && typeof window !== "undefined") {
      localStorage.removeItem("token");
      window.location.href = "/";
    }
    return Promise.reject(error);
  }
);

export default api;

// Types
export interface User {
  id: string;
  email: string;
  name: string;
  avatar_url: string | null;
  is_admin: boolean;
}

export interface Song {
  id: string;
  title: string;
  composer: string;
  genre: string | null;
  difficulty: number;
  estimated_weeks: number | null;
  analysis_text: string | null;
  required_skills: Record<string, number> | null;
  practice_tips: string | null;
  reference_urls: { label: string; url: string }[] | null;
  sheet_snippets: { title: string; abc: string; description?: string }[] | null;
  full_abc: string | null;
  page_breaks: number[] | null;
  youtube_url: string | null;
  measure_timestamps: { measure: number; seconds: number }[] | null;
  created_at: string;
  updated_at: string;
}

export interface Evaluation {
  id: string;
  user_song_id: string;
  pitch_accuracy: number;
  rhythm: number;
  tempo_stability: number;
  dynamics: number;
  articulation: number;
  pedaling: number;
  phrasing: number;
  expressiveness: number;
  memorization: number;
  technical_fluency: number;
  comment: string | null;
  created_at: string;
}

export interface PracticeSession {
  id: string;
  user_song_id: string;
  metrics: string[];
  measure_start: number | null;
  measure_end: number | null;
  audio_start_seconds: number | null;
  audio_end_seconds: number | null;
  started_at: string;
  completed_at: string | null;
  duration_seconds: number | null;
  scores: Record<string, number> | null;
  comment: string | null;
  created_at: string;
}

export type SongStatus = "NOT_STARTED" | "PRACTICING" | "POLISHING" | "COMPLETED";

export interface UserSong {
  id: string;
  song: Song;
  status: SongStatus;
  notes: string | null;
  latest_evaluation: Evaluation | null;
  created_at: string;
  updated_at: string;
}

export interface Skill {
  id: string;
  name: string;
  category: string;
  description: string | null;
  levels: Record<string, string> | null;
  created_at: string;
  updated_at: string;
}

export interface SkillEvaluation {
  id: string;
  user_skill_id: string;
  level: number;
  comment: string | null;
  created_at: string;
}

export interface UserSkill {
  id: string;
  skill: Skill;
  latest_evaluation: SkillEvaluation | null;
  created_at: string;
  updated_at: string;
}

export interface Overview {
  total_songs: number;
  completed_songs: number;
  practicing_songs: number;
  average_scores: Record<string, number>;
  weakest_attribute: string | null;
  strongest_attribute: string | null;
  skill_levels: Record<string, number>;
  total_skills: number;
}

export type SightReadingEndedReason = "wrong" | "timeout";

export interface SightReadingSession {
  id: string;
  score: number;
  correct_count: number;
  average_reaction_ms: number | null;
  fastest_limit_ms: number;
  duration_seconds: number;
  ended_reason: SightReadingEndedReason;
  expected_note: string | null;
  actual_note: string | null;
  created_at: string;
}

export interface SightReadingNoteStat {
  note: string;
  midi: number;
  score: number;
  correct_count: number;
  wrong_count: number;
  total_count: number;
}

export interface SightReadingStats {
  total_sessions: number;
  best_score: number;
  average_score: number;
  average_reaction_ms: number | null;
  recent_average_score: number;
  previous_average_score: number | null;
  score_growth: number;
  recent_sessions: SightReadingSession[];
  weakest_notes: SightReadingNoteStat[];
  strongest_notes: SightReadingNoteStat[];
  all_notes: SightReadingNoteStat[];
}

export const ATTRIBUTES = [
  {
    key: "pitch_accuracy",
    label: "음정 정확도",
    description: "악보의 올바른 음(건반)을 틀리지 않고 짚는 정확도",
    criteria: {
      1: "악보를 보며 더듬더듬 짚는 단계. 틀린 음 빈번",
      2: "악보 보면서 대부분 맞추지만, 도약·변화음에서 실수",
      3: "느린 템포에서 틀린 음 거의 없음",
      4: "본 템포에서 틀린 음 거의 없음",
      5: "본 템포 연속 연주에서 음 실수 0에 수렴",
    },
  },
  {
    key: "rhythm",
    label: "리듬",
    description: "박자와 리듬 패턴을 악보대로 정확히 연주하는 정도",
    criteria: {
      1: "박자 구조를 아직 파악 중. 메트로놈 없이 흐름 유지 어려움",
      2: "메트로놈에 맞춰 기본 박자 유지 가능. 싱코페이션·복합 리듬에서 흔들림",
      3: "느린 템포에서 리듬 패턴 정확. 복합 리듬도 처리",
      4: "본 템포에서 리듬 안정. 의도적 루바토와 실수 구분 가능",
      5: "리듬이 음악적 의도를 정확히 전달. 자유로운 템포 조절 속에서도 구조 유지",
    },
  },
  {
    key: "tempo_stability",
    label: "템포 안정성",
    description: "곡 전체에서 의도치 않은 빨라짐·느려짐 없이 일정한 빠르기를 유지하는 정도",
    criteria: {
      1: "구간마다 템포 제각각. 어려운 부분에서 급격히 느려짐",
      2: "쉬운 구간은 안정적이나, 기술적 난이도 높은 구간에서 흔들림",
      3: "느린 템포(60-70%)에서 전곡 일관된 템포 유지",
      4: "본 템포에서 전곡 일관성 확보. 의도적 변화 외 흔들림 없음",
      5: "본 템포에서 감정 표현을 위한 템포 변화가 자연스럽고 제어됨",
    },
  },
  {
    key: "dynamics",
    label: "다이나믹스",
    description: "여린(p)~센(f) 셈여림을 구분해 표현하는 폭과 정교함",
    criteria: {
      1: "거의 단일 음량. 강약 미분화",
      2: "f/p 정도의 큰 대비는 인식하고 시도. 중간 단계(mp, mf) 미분화",
      3: "악보에 표기된 다이나믹을 느린 템포에서 대부분 실행",
      4: "본 템포에서 다이나믹 레인지 충분. pp~ff 자유자재",
      5: "다이나믹이 프레이징·감정과 유기적으로 통합. 미세한 그라데이션",
    },
  },
  {
    key: "articulation",
    label: "아티큘레이션",
    description: "레가토·스타카토 등 음을 잇고 끊는 터치 처리",
    criteria: {
      1: "레가토/스타카토 구분 없이 단순 타건",
      2: "레가토·스타카토 등 기본 아티큘레이션 의식적으로 시도",
      3: "느린 템포에서 악보 지시 아티큘레이션 대부분 구현",
      4: "본 템포에서 아티큘레이션 일관. 터치 컨트롤 안정",
      5: "곡의 성격에 맞는 아티큘레이션이 자연스럽게 체화",
    },
  },
  {
    key: "pedaling",
    label: "페달링",
    description: "페달로 울림과 음색을 깨끗하게 제어하는 정도",
    criteria: {
      1: "페달 미사용 또는 무분별 사용. 소리 뭉개짐",
      2: "기본 레가토 페달링 시도. 화성 전환 시 탁한 구간 존재",
      3: "화성 변화에 맞는 페달 체인지. 느린 템포에서 깨끗함",
      4: "본 템포에서 페달링 정확. 하프 페달 등 중간 기법 활용",
      5: "페달이 음색·공간감 표현 도구로 작동. 곡 전체에서 자연스러움",
    },
  },
  {
    key: "phrasing",
    label: "프레이징",
    description: "음악적 문장(프레이즈)을 호흡감 있게 만들어 부르듯 연주하는 정도",
    criteria: {
      1: "음표 단위로 연주. 문장 구조 미인식",
      2: "프레이즈 단위를 인식하고 호흡 위치를 의식",
      3: "느린 템포에서 프레이즈 시작-정점-마무리가 들림",
      4: "본 템포에서 프레이즈 흐름 자연스러움. 큰 구조(섹션 간) 연결도 의식",
      5: "프레이즈가 노래하듯 자연스럽고, 전곡의 서사가 느껴짐",
    },
  },
  {
    key: "expressiveness",
    label: "표현력",
    description: "곡의 감정과 해석 의도를 듣는 사람에게 전달하는 정도",
    criteria: {
      1: "음 나열 수준. 감정·의도 전달 없음",
      2: "곡의 분위기를 이해하고 부분적으로 표현 시도",
      3: "주요 감정 변화 지점에서 의도적 표현. 다소 기계적",
      4: "기술이 표현을 방해하지 않음. 자신만의 해석이 드러남",
      5: "듣는 사람에게 감정이 전달됨. 기술과 표현이 완전 통합",
    },
  },
  {
    key: "memorization",
    label: "암보",
    description: "악보 없이 끊김 없이 안정적으로 연주하는 정도",
    criteria: {
      1: "악보 없이 연주 불가",
      2: "일부 구간(주제부 등) 악보 없이 가능. 전환부에서 막힘",
      3: "전곡 암보 가능하나 불안정한 구간 존재. 막히면 복구 어려움",
      4: "전곡 암보 안정. 중간에 끊겨도 아무 지점에서 재진입 가능",
      5: "암보가 완전 체화. 연주 중 기억이 아닌 음악에 집중",
    },
  },
  {
    key: "technical_fluency",
    label: "기술적 유창성",
    description: "빠르고 어려운 패시지를 막힘 없이 매끄럽게 처리하는 정도",
    criteria: {
      1: "기술적 패시지에서 손가락이 따라가지 못함",
      2: "느린 템포에서 기술적 패시지 운지 가능. 빠르면 무너짐",
      3: "70% 템포에서 기술적 패시지 통과. 부분적 걸림",
      4: "본 템포에서 기술적 패시지 안정적 통과",
      5: "기술적 난이도를 느끼지 못할 정도로 자연스러움. 여유 있음",
    },
  },
] as const;

export const STATUS_LABELS: Record<SongStatus, string> = {
  NOT_STARTED: "시작 전",
  PRACTICING: "연습 중",
  POLISHING: "마무리",
  COMPLETED: "완성",
};

export const STATUS_COLORS: Record<SongStatus, string> = {
  NOT_STARTED: "bg-toss-gray-400",
  PRACTICING: "bg-toss-blue",
  POLISHING: "bg-toss-orange",
  COMPLETED: "bg-toss-green",
};
