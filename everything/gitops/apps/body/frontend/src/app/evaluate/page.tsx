"use client";

import EvaluationForm from "@/components/evaluation-form";

export default function EvaluatePage() {
  return (
    <div className="space-y-5 max-w-2xl mx-auto">
      <div>
        <h1 className="text-[22px] font-bold text-text-primary">평가 입력</h1>
        <p className="text-[13px] text-text-secondary mt-1">
          오늘 운동한 부위를 선택하고 평가하세요
        </p>
      </div>
      <EvaluationForm />
    </div>
  );
}
