// Who is using the family app. The prototype has no login, so the app identifies the demo viewer to the API with
// X-Actor / X-Role headers (the access log records them). The viewer is the elder's primary family carer, e.g. Lan
// for Bà Hạnh. Header values must be ASCII, so the name is percent-encoded (the API decodes it).
const DEMO_VIEWERS: Record<string, { name: string; role: string; memberId: string }> = {
  hanh: { name: "Lan", role: "primary", memberId: "lan" },
  tu: { name: "Bà Tư", role: "primary", memberId: "ba_tu" },
  control: { name: "Thảo", role: "primary", memberId: "thao" },
};

export function viewerFor(elderId?: string) {
  return DEMO_VIEWERS[elderId ?? ""] ?? DEMO_VIEWERS.hanh;
}

export function actorHeaders(elderId?: string): Record<string, string> {
  const v = viewerFor(elderId);
  return { "X-Actor": encodeURIComponent(v.name), "X-Role": v.role };
}
