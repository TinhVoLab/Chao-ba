"use client";
import { createContext, useContext } from "react";
import type { ElderProfile, FamilyMember } from "@/lib/types";

export type ScreenLang = "vi" | "en";
export const LangCtx = createContext<ScreenLang>("vi");
/** `t("Việt", "English")` picks the screen language (the elder screen shows one language at a time). */
export function useT() {
  const lang = useContext(LangCtx);
  return (vi: string, en: string) => (lang === "en" ? en : vi);
}

const HONORIFICS = ["bà", "ông", "chị", "anh", "cô", "chú", "dì", "cậu", "bác", "con", "cháu"];

/** "Bà Tư" -> "bà Tư" mid-sentence; "Lan" stays "Lan". */
function lowerHonorific(name: string): string {
  const [first, ...rest] = name.split(" ");
  return rest.length && HONORIFICS.includes(first.toLowerCase()) ? [first.toLowerCase(), ...rest].join(" ") : name;
}
function startsWithHonorific(name: string): boolean {
  const [first, ...rest] = name.split(" ");
  return rest.length > 0 && HONORIFICS.includes(first.toLowerCase());
}

export const isChild = (m: FamilyMember) => m.relation === "son" || m.relation === "daughter";

/** How the elder names this person: "con Lan", "bà Tư". */
export function elderCalls(m: FamilyMember): string {
  if (isChild(m)) return `con ${m.name}`;
  return lowerHonorific(m.name);
}

/** How Út Thương (speaking to the elder) names the family member: "chị Lan", "bà Tư". */
export function agentCalls(m: FamilyMember & { honorific?: string }): string {
  if (startsWithHonorific(m.name)) return lowerHonorific(m.name);
  return m.honorific ? `${m.honorific} ${m.name}` : m.name;
}

export function relationLabel(m: FamilyMember, en: boolean): string {
  const vi: Record<string, string> = { daughter: "Con gái", son: "Con trai", wife: "Vợ", husband: "Chồng",
    granddaughter: "Cháu gái", grandson: "Cháu trai", grandchild: "Cháu" };
  const enMap: Record<string, string> = { daughter: "Daughter", son: "Son", wife: "Wife", husband: "Husband",
    granddaughter: "Granddaughter", grandson: "Grandson", grandchild: "Grandchild" };
  return (en ? enMap : vi)[m.relation] ?? (en ? "Family" : "Người nhà");
}

/** The family member the big "Gọi …" button calls: the primary contact, else the first one. */
export function callTarget(p: ElderProfile): FamilyMember | null {
  const fam = p.family ?? [];
  return fam.find((f) => f.role === "primary") ?? fam[0] ?? null;
}

export function givenName(p: ElderProfile): string {
  return p.display_name.split(" ").slice(1).join(" ") || p.display_name;
}

/** "bà Hạnh" */
export function addressElder(p: ElderProfile): string {
  return `${p.honorific || "bà"} ${givenName(p)}`;
}

export const cap = (s: string) => (s ? s[0].toUpperCase() + s.slice(1) : s);

/** Strip a leading "Lan nhắn:" that family notes often start with. */
export function messageBody(text: string, author: string): string {
  const re = new RegExp(`^\\s*${author.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\s+nhắn\\s*:\\s*`, "i");
  const t = text.replace(re, "");
  return t ? t[0].toUpperCase() + t.slice(1) : t;
}

export function hueOf(name: string): number {
  let h = 0;
  for (const ch of name) h = (h * 31 + ch.charCodeAt(0)) % 360;
  return h;
}
