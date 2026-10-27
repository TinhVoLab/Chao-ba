import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    id: "/",
    name: "Chào Bà · Gia đình",
    short_name: "Chào Bà",
    description: "Đèn xanh, vàng, đỏ mỗi ngày cho người thân lớn tuổi. A daily green/yellow/red light for your parent.",
    lang: "vi",
    start_url: "/",
    scope: "/",
    display: "standalone",
    orientation: "portrait",
    background_color: "#f7f3ec",
    theme_color: "#2f3a7a",
    categories: ["health", "lifestyle"],
    icons: [
      { src: "/icons/icon-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
      { src: "/icons/icon-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
      { src: "/icons/icon-maskable-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
      { src: "/icons/icon.svg", sizes: "any", type: "image/svg+xml", purpose: "any" },
    ],
    shortcuts: [
      { name: "Xu hướng / Trends", url: "/trends" },
      { name: "Cảnh báo / Alerts", url: "/alerts" },
    ],
  };
}
