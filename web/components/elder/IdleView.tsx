"use client";
import { useEffect, useState, useSyncExternalStore } from "react";
import { Check, Droplets, MessageCircleHeart, Mic, Phone, Pill, Puzzle, Smile } from "lucide-react";
import type { ElderProfile, FamilyMember } from "@/lib/types";
import { Avatar } from "./Avatar";
import { Face } from "./Faces";
import { MaiScene, Portrait } from "./Portrait";
import type { MedToday, Mood, ScreenMessage } from "./data";
import { addressElder, cap, elderCalls, messageBody, relationLabel, useT } from "./util";
import s from "./classes";

const WD = ["Chủ nhật", "Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy"];
const WD_EN = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const MON_EN = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

function subscribeClock(cb: () => void) {
  const id = setInterval(cb, 1000);
  return () => clearInterval(id);
}
const clockSnapshot = () => {
  const d = new Date();
  return `${d.getHours()}|${d.getMinutes()}|${d.getDay()}|${d.getDate()}|${d.getMonth()}`;
};
/** [hours, minutes, weekday, date, month] or null before hydration. */
export function useClock(): number[] | null {
  const c = useSyncExternalStore(subscribeClock, clockSnapshot, () => "");
  return c ? c.split("|").map(Number) : null;
}

function hhmm(iso: string | null) {
  if (!iso) return "";
  const d = new Date(iso);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

export interface IdleProps {
  profile: ElderProfile;
  messages: ScreenMessage[];
  meds: MedToday[];
  mood: Mood | null;
  callee: FamilyMember | null;
  toast: string | null;
  onMed: (m: MedToday, status: "taken" | "not_yet") => void;
  onTalk: () => void;
  onVideo: () => void;
  onMood: () => void;
  onGame: () => void;
}

export function IdleView(p: IdleProps) {
  const t = useT();
  const clock = useClock();
  const fam = p.profile.family ?? [];
  const slides = fam.length + 1;
  const [slide, setSlide] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setSlide((x) => (x + 1) % slides), 8000);
    return () => clearInterval(id);
  }, [slides]);

  const [h, m, wd, dd, mo] = clock ?? [];
  const time = clock ? `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}` : "--:--";
  const part = !clock ? null : h < 4 ? ["buổi tối", "evening"] : h < 11 ? ["buổi sáng", "morning"] : h < 13 ? ["buổi trưa", "afternoon"] : h < 18 ? ["buổi chiều", "afternoon"] : ["buổi tối", "evening"];
  const greet = part ? t(`Chào ${part[0]}, ${addressElder(p.profile)}!`, `Good ${part[1]}, ${p.profile.name_en}!`) : " ";
  const date = clock ? t(`${WD[wd]}, ${dd} tháng ${mo + 1}`, `${WD_EN[wd]}, ${dd} ${MON_EN[mo]}`) : " ";

  const msg = p.messages[0];
  const timed = p.meds.filter((x) => x.timed);
  const untimed = p.meds.filter((x) => !x.timed);
  const nowMin = clock ? h * 60 + m : 0;
  const due = (x: MedToday) => {
    const [a, b] = x.time.split(":").map(Number);
    return nowMin >= a * 60 + b - 30;
  };
  const member = slide < fam.length ? fam[slide] : null;

  return (
    <div className={s.idle}>
      <header className={s.top}>
        <div>
          <p className={s.clock} aria-label={t(`Bây giờ là ${time}`, `It is ${time}`)} data-testid="clock">
            {time}
          </p>
          <p className={s.date}>{date}</p>
        </div>
        <button type="button" className={s.avatarBtn} onClick={p.onTalk} aria-label={t("Nói chuyện với Út Thương", "Talk to Út Thương")}>
          <Avatar state="idle" />
          <span>Út Thương</span>
        </button>
      </header>
      <p className={s.greet}>{greet}</p>

      <figure className={s.photo} aria-label={t("Ảnh gia đình", "Family photos")}>
        {fam.map((f, i) => (
          <div key={f.id} className={s.slide} data-on={slide === i}>
            <Portrait member={f} id={`pf-${f.id}`} />
          </div>
        ))}
        <div className={s.slide} data-on={slide === fam.length}>
          <MaiScene />
        </div>
        <figcaption>
          <span>
            {member
              ? member.relation === "son" || member.relation === "daughter"
                ? t(`${relationLabel(member, false)} ${member.name}`, `${relationLabel(member, true)} ${member.name}`)
                : member.name
              : t("Mai trước nhà", "Apricot blossoms at home")}
          </span>
          <span className={s.dots} aria-hidden>
            {Array.from({ length: slides }, (_, i) => (
              <i key={i} data-on={i === slide} />
            ))}
          </span>
        </figcaption>
      </figure>

      {msg && (
        <section className={s.message} aria-label={t("Lời nhắn của gia đình", "Family message")} data-testid="family-message">
          <MessageCircleHeart className={s.ico} aria-hidden />
          <div>
            <p className={s.msgFrom}>{t(`${cap(msg.author)} nhắn`, `Message from ${msg.author}`)}</p>
            <p className={s.msgText}>“{messageBody(msg.text, msg.author)}”</p>
          </div>
        </section>
      )}

      <section className={s.today} aria-label={t("Hôm nay", "Today")}>
        {timed.map((x) => (
          <div key={x.name} className={s.medRow} data-testid="med-row">
            <div className={s.medInfo}>
              <Pill className={s.ico} aria-hidden />
              <p>
                <b className="tnum">{x.time}</b> · {t("Uống thuốc", "Take")} {x.name}
                {x.status === "taken" ? (
                  <span className={s.medDone} data-testid="med-done">
                    <Check aria-hidden /> {t(`Đã uống lúc ${hhmm(x.answered_at)}`, `Taken at ${hhmm(x.answered_at)}`)}
                  </span>
                ) : x.status === "not_yet" ? (
                  <span className={s.medLater}>{t("Chưa uống, Út Thương sẽ nhắc lại", "Not yet; Út Thương will remind you")}</span>
                ) : !due(x) ? (
                  <span className={s.medLater}>{t("Chưa tới giờ", "Not time yet")}</span>
                ) : null}
              </p>
            </div>
            {x.status !== "taken" && (
              <div className={s.medBtns}>
                <button type="button" className={s.btnYes} onClick={() => p.onMed(x, "taken")}>
                  {t("Đã uống thuốc", "I took it")} <Check aria-hidden />
                </button>
                {x.status !== "not_yet" && (
                  <button type="button" className={s.btnGhost} onClick={() => p.onMed(x, "not_yet")}>
                    {t("Chưa", "Not yet")}
                  </button>
                )}
              </div>
            )}
          </div>
        ))}
        {untimed.map((x) => (
          <div key={x.name} className={s.line}>
            <Pill className={s.ico} aria-hidden />
            <p>{t(`Thuốc khi cần: ${x.name.replace(/\s*\(.*\)/, "")}`, `When needed: ${x.name.replace(/\s*\(.*\)/, "")}`)}</p>
          </div>
        ))}
        <div className={s.line}>
          <Droplets className={s.ico} aria-hidden />
          <p>{t("Nhớ uống một ly nước mỗi 2 tiếng", "A glass of water every 2 hours")}</p>
        </div>
      </section>

      <div className={s.tiles}>
        <button type="button" className={s.tile} onClick={p.onMood} data-testid="tile-mood">
          {p.mood ? (
            <span className={s.tileFace}>
              <Face mood={p.mood} />
            </span>
          ) : (
            <Smile className={s.tileIco} aria-hidden />
          )}
          <span>{p.mood ? t("Hôm nay đã chọn", "Mood noted") : t("Hôm nay thấy sao?", "How are you today?")}</span>
        </button>
        <button type="button" className={s.tile} onClick={p.onGame} data-testid="tile-game">
          <Puzzle className={s.tileIco} aria-hidden />
          <span>{t("Trò chơi ca dao", "Folk-verse game")}</span>
        </button>
      </div>

      {p.toast && (
        <p className={s.toast} role="status">
          {p.toast}
        </p>
      )}

      <div className={s.mainBtns}>
        <button type="button" className={s.btnTalk} onClick={p.onTalk} data-testid="btn-talk">
          <Mic aria-hidden />
          <span>{t("Nói chuyện với Út Thương", "Talk to Út Thương")}</span>
        </button>
        {p.callee && (
          <button type="button" className={s.btnCall} onClick={p.onVideo} data-testid="btn-video">
            <Phone aria-hidden />
            <span>{t(`Gọi ${elderCalls(p.callee)}`, `Call ${p.callee.name}`)}</span>
          </button>
        )}
      </div>
    </div>
  );
}
