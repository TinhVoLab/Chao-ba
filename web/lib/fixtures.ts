// Offline demo data: snapshots of the real API (web/scripts/snapshot-fixtures.mjs).
import elders from "@/fixtures/elders.json";
import hanh from "@/fixtures/hanh.json";
import tu from "@/fixtures/tu.json";
import control from "@/fixtures/control.json";
import type { Alert, Dmaic, ElderProfile, ElderSummary, Note, Privacy, Timeline, Today } from "./types";

export interface FixtureBundle {
  profile: ElderProfile;
  today: Today;
  timeline: Timeline;
  alerts: Alert[];
  dmaic: Dmaic;
  notes: Note[];
  privacy: Privacy;
}

const bundles = { hanh, tu, control } as unknown as Record<string, FixtureBundle>;

export const fixtureElders = elders as unknown as ElderSummary[];

export function fixtureFor(id: string): FixtureBundle {
  return bundles[id] ?? bundles.hanh;
}
