"use client";

import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { getProfile, updateProfile } from "@/lib/api";
import { Save, Check } from "lucide-react";
import Card from "@/components/card";

export default function SettingsPage() {
  const queryClient = useQueryClient();
  const [weight, setWeight] = useState("");
  const [height, setHeight] = useState("");
  const [saved, setSaved] = useState(false);

  const { data: profile } = useQuery({
    queryKey: ["profile"],
    queryFn: getProfile,
  });

  useEffect(() => {
    if (profile) {
      setWeight(profile.weight.toString());
      setHeight(profile.height.toString());
    }
  }, [profile]);

  const mutation = useMutation({
    mutationFn: updateProfile,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["profile"] });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    },
  });

  const handleSave = () => {
    const w = parseFloat(weight);
    const h = parseFloat(height);
    if (isNaN(w) || isNaN(h)) return;
    mutation.mutate({ weight: w, height: h });
  };

  const bmi =
    weight && height
      ? (
          parseFloat(weight) /
          ((parseFloat(height) / 100) * (parseFloat(height) / 100))
        ).toFixed(1)
      : "-";

  return (
    <div className="space-y-6 max-w-lg mx-auto">
      <h1 className="text-[22px] font-bold text-text-primary">설정</h1>

      <Card padding="lg">
        <h2 className="text-[15px] font-semibold text-text-primary mb-5">
          신체 정보
        </h2>

        <div className="space-y-4">
          <div>
            <label className="block text-[13px] text-text-secondary font-medium mb-1.5">
              체중 (kg)
            </label>
            <input
              type="number"
              step="0.1"
              value={weight}
              onChange={(e) => setWeight(e.target.value)}
              placeholder="75.0"
              className="w-full px-3 py-2.5 rounded-xl bg-surface-secondary border border-border text-text-primary text-sm focus:outline-none focus:ring-2 focus:ring-brand/20 focus:border-brand"
            />
          </div>

          <div>
            <label className="block text-[13px] text-text-secondary font-medium mb-1.5">
              키 (cm)
            </label>
            <input
              type="number"
              step="0.1"
              value={height}
              onChange={(e) => setHeight(e.target.value)}
              placeholder="175.0"
              className="w-full px-3 py-2.5 rounded-xl bg-surface-secondary border border-border text-text-primary text-sm focus:outline-none focus:ring-2 focus:ring-brand/20 focus:border-brand"
            />
          </div>

          <div className="flex items-center gap-3 px-4 py-3 rounded-xl bg-surface-secondary border border-border">
            <span className="text-[13px] text-text-secondary">BMI</span>
            <span className="text-[18px] font-bold text-brand">{bmi}</span>
          </div>

          <button
            onClick={handleSave}
            disabled={mutation.isPending}
            className={`w-full py-3 rounded-2xl font-semibold text-[14px] flex items-center justify-center gap-2 transition-all active:scale-[0.98] ${
              saved
                ? "bg-brand-dark text-white"
                : "bg-brand hover:bg-brand-dark text-white shadow-md shadow-brand/20"
            }`}
          >
            {saved ? (
              <>
                <Check className="w-4 h-4" /> 저장 완료!
              </>
            ) : mutation.isPending ? (
              "저장 중..."
            ) : (
              <>
                <Save className="w-4 h-4" /> 저장
              </>
            )}
          </button>
        </div>
      </Card>

      <Card>
        <h2 className="text-[15px] font-semibold text-text-primary mb-3">
          앱 정보
        </h2>
        <div className="space-y-2.5">
          <div className="flex justify-between text-[13px]">
            <span className="text-text-tertiary">버전</span>
            <span className="text-text-primary font-medium">0.1.0</span>
          </div>
          <div className="flex justify-between text-[13px]">
            <span className="text-text-tertiary">백엔드</span>
            <span className="text-text-secondary font-mono text-[12px]">
              {process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}
            </span>
          </div>
        </div>
      </Card>
    </div>
  );
}
