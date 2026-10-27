import type { Light, Metric } from "./types";

const WD_VI = ["Chủ nhật", "Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy"];
const WD_EN = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const MON_EN = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function parse(iso: string): Date | null {
  const d = new Date(iso.length === 10 ? `${iso}T00:00:00Z` : iso);
  return Number.isNaN(d.getTime()) ? null : d;
}

export function shortDate(iso: string): string {
  const d = parse(iso);
  if (!d) return iso;
  return `${String(d.getUTCDate()).padStart(2, "0")}/${String(d.getUTCMonth() + 1).padStart(2, "0")}`;
}

export function longDate(iso: string): { vi: string; en: string } {
  const d = parse(iso);
  if (!d) return { vi: iso, en: iso };
  return {
    vi: `${WD_VI[d.getUTCDay()]}, ${d.getUTCDate()}/${d.getUTCMonth() + 1}`,
    en: `${WD_EN[d.getUTCDay()]}, ${d.getUTCDate()} ${MON_EN[d.getUTCMonth()]}`,
  };
}

/** Time in Vietnam (UTC+7) for an ISO timestamp. */
export function vnTime(iso: string): string {
  const d = parse(iso);
  if (!d) return "";
  const t = new Date(d.getTime() + 7 * 3600_000);
  return `${String(t.getUTCHours()).padStart(2, "0")}:${String(t.getUTCMinutes()).padStart(2, "0")}`;
}

export const LIGHT_WORD: Record<Light, { vi: string; en: string }> = {
  green: { vi: "Bình thường", en: "As usual" },
  yellow: { vi: "Cần để ý", en: "Keep an eye" },
  red: { vi: "Cần quan tâm", en: "Needs attention" },
  gray: { vi: "Đang làm quen", en: "Learning" },
};

export const LIGHT_HINT: Record<Light, { vi: string; en: string }> = {
  green: { vi: "Trong khoảng thường ngày của chính người thân", en: "Within this person's own usual range" },
  yellow: { vi: "Lệch khỏi mức thường ngày vài ngày liền", en: "Off their usual range for several days" },
  red: { vi: "Thay đổi rõ, kéo dài. Nên gọi hôm nay", en: "A clear, lasting change. Call today" },
  gray: { vi: "Chưa đủ dữ liệu để so sánh", en: "Not enough data to compare yet" },
};

export const METRIC_META: Record<
  Metric,
  { vi: string; en: string; descVi: string; descEn: string; unitVi: string; unitEn: string; fmt: (v: number) => string }
> = {
  speech_rate_sps: {
    vi: "Nhịp nói",
    en: "Speaking pace",
    descVi: "Âm tiết mỗi giây. Thấp hơn là nói chậm hơn.",
    descEn: "Syllables per second. Lower means slower.",
    unitVi: "âm tiết/giây",
    unitEn: "syll/s",
    fmt: (v) => v.toFixed(2),
  },
  pause_ratio: {
    vi: "Khoảng ngừng",
    en: "Pauses",
    descVi: "Phần thời gian ngừng giữa câu. Cao hơn là ngập ngừng hơn.",
    descEn: "Share of speaking time spent paused. Higher means more hesitation.",
    unitVi: "%",
    unitEn: "%",
    fmt: (v) => `${(v * 100).toFixed(0)}%`,
  },
  filled_pause_rate: {
    vi: "Tiếng đệm",
    en: "Filler words",
    descVi: "Tỉ lệ “ờ, à, ừm”. Cao hơn là tìm từ khó hơn.",
    descEn: "Share of “ờ, à, ừm”. Higher means more word-finding effort.",
    unitVi: "%",
    unitEn: "%",
    fmt: (v) => `${(v * 100).toFixed(1)}%`,
  },
  mattr: {
    vi: "Độ phong phú từ ngữ",
    en: "Word variety",
    descVi: "MATTR: bao nhiêu từ khác nhau trong mỗi đoạn 40 từ. Thấp hơn là lặp từ nhiều hơn.",
    descEn: "MATTR: distinct words per 40-word window. Lower means more repetition.",
    unitVi: "",
    unitEn: "",
    fmt: (v) => v.toFixed(2),
  },
  recall_score: {
    vi: "Nhớ chuyện hôm trước",
    en: "Story recall",
    descVi: "Điểm 0–3 khi nhắc lại một chuyện đã kể 1–2 ngày trước: 3 = tự nhớ, thấp hơn = cần gợi ý, 0 = chưa nhớ ra.",
    descEn: "0–3 score for recalling something told 1–2 days ago: 3 = unprompted, lower = needed a cue, 0 = not recalled.",
    unitVi: "/3",
    unitEn: "/3",
    fmt: (v) => (Number.isInteger(v) ? `${v}` : v.toFixed(1)),
  },
};

export const MOOD_WORD: Record<number, { vi: string; en: string }> = {
  1: { vi: "rất buồn", en: "very low" },
  2: { vi: "hơi buồn", en: "low" },
  3: { vi: "bình thường", en: "okay" },
  4: { vi: "vui", en: "good" },
  5: { vi: "rất vui", en: "very good" },
};

export const SYMPTOM_WORD: Record<string, { vi: string; en: string }> = {
  pain: { vi: "đau nhức", en: "pain" },
  insomnia: { vi: "khó ngủ", en: "poor sleep" },
  skipped_meal: { vi: "bỏ bữa", en: "skipped a meal" },
  dizziness: { vi: "chóng mặt", en: "dizziness" },
  fall: { vi: "té ngã", en: "a fall" },
  sadness: { vi: "buồn", en: "feeling sad" },
  missed_medication: { vi: "quên thuốc", en: "missed medication" },
};

/** Kinship term the adult child uses for the elder (má / ba). */
export function kin(honorific?: string): { vi: string; en: string } {
  return honorific === "bà" ? { vi: "má", en: "Mom" } : { vi: "ba", en: "Dad" };
}
