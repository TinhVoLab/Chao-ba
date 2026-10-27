// "Nhớ ca dao": finish a well-known Vietnamese folk verse (ca dao / tục ngữ) from three big choices.
// Gentle by design: no score, no "wrong"; a miss simply shows the verse and moves on.
export interface CaDao {
  id: string;
  lead: string; // shown in full
  stem: string; // second line up to the blank
  answer: string;
  others: [string, string];
  en: string; // gloss for the English demo view
}

export const CA_DAO: CaDao[] = [
  { id: "cong_cha", lead: "Công cha như núi Thái Sơn,", stem: "Nghĩa mẹ như", answer: "nước trong nguồn chảy ra",
    others: ["trăng sáng giữa trời", "hoa nở mùa xuân"], en: "A father's merit is like Mount Thai Son; a mother's love like water flowing from the spring." },
  { id: "bau_bi", lead: "Bầu ơi thương lấy bí cùng,", stem: "Tuy rằng khác giống nhưng", answer: "chung một giàn",
    others: ["chung một nhà", "cùng một sông"], en: "Gourd, love the squash: different kinds, but the same trellis." },
  { id: "mot_cay", lead: "Một cây làm chẳng nên non,", stem: "Ba cây chụm lại nên", answer: "hòn núi cao",
    others: ["rừng xanh tươi", "bóng mát to"], en: "One tree is no mountain; three trees together make a high hill." },
  { id: "nhieu_dieu", lead: "Nhiễu điều phủ lấy giá gương,", stem: "Người trong một nước phải", answer: "thương nhau cùng",
    others: ["nhớ nhau luôn", "giúp nhau thôi"], en: "Red silk covers the mirror stand; people of one country should love one another." },
  { id: "gio_dua", lead: "Gió đưa cây cải về trời,", stem: "Rau răm ở lại chịu", answer: "lời đắng cay",
    others: ["mưa nắng hoài", "cảnh đơn côi"], en: "The wind blows the mustard plant to the sky; the knotweed stays to bear the bitter words." },
  { id: "bat_com", lead: "Ai ơi bưng bát cơm đầy,", stem: "Dẻo thơm một hạt,", answer: "đắng cay muôn phần",
    others: ["ngọt bùi trăm năm", "no ấm cả nhà"], en: "Holding a full bowl of rice: each fragrant grain, a thousand hardships." },
  { id: "an_qua", lead: "Ăn quả nhớ kẻ trồng cây,", stem: "Uống nước nhớ", answer: "nguồn",
    others: ["sông", "mưa"], en: "Eating fruit, remember who planted the tree; drinking water, remember its source." },
  { id: "ra_dong", lead: "Trâu ơi ta bảo trâu này,", stem: "Trâu ra ngoài ruộng,", answer: "trâu cày với ta",
    others: ["trâu nghỉ bóng cây", "trâu về với ta"], en: "Buffalo, listen: out in the field, you plough with me." },
];

/** Three verses for one round, starting at a rotating offset so each round feels new. */
export function pickRound(seed: number, n = 3): CaDao[] {
  const start = ((seed % CA_DAO.length) + CA_DAO.length) % CA_DAO.length;
  return Array.from({ length: n }, (_, i) => CA_DAO[(start + i * 3) % CA_DAO.length]);
}

export function shuffledChoices(item: CaDao, seed: number): string[] {
  const all = [item.answer, ...item.others];
  const k = ((seed % 3) + 3) % 3;
  return [...all.slice(k), ...all.slice(0, k)];
}
