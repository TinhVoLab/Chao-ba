// Offline demo data: snapshots of the real API (web/scripts/snapshot-fixtures.mjs).
import elders from "@/fixtures/elders.json";
import hanh from "@/fixtures/hanh.json";
import tu from "@/fixtures/tu.json";
import control from "@/fixtures/control.json";
import family from "@/fixtures/family.json";
import community from "@/fixtures/community.json";
import type {
  Alert,
  Community,
  Dmaic,
  ElderProfile,
  ElderSummary,
  FamilyOverview,
  FamilyTimeline,
  Note,
  Privacy,
  Timeline,
  Today,
} from "./types";
import { viewerFor } from "./viewer";

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

// Family coordination snapshots: one per care-circle member (scripts/snapshot-family-fixtures.mjs).
const familyBundles = family as unknown as Record<string, Record<string, { overview: FamilyOverview; timeline: FamilyTimeline }>>;

export function familyFixture(id: string, memberId?: string | null) {
  const byMember = familyBundles[id] ?? familyBundles.hanh;
  const m = viewerFor(id in familyBundles ? id : "hanh", memberId).memberId;
  return byMember[m] ?? Object.values(byMember)[0];
}

export const fixtureCommunity = community as unknown as Community;
