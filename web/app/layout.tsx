import type { Metadata, Viewport } from "next";
import { Be_Vietnam_Pro } from "next/font/google";
import { SwRegister } from "@/components/SwRegister";
import "./globals.css";

const font = Be_Vietnam_Pro({
  variable: "--font-vn",
  subsets: ["latin", "vietnamese"],
  weight: ["400", "500", "600", "700", "800"],
  display: "swap",
});

export const metadata: Metadata = {
  title: { default: "Chào Bà", template: "%s · Chào Bà" },
  description: "Mỗi sáng một cuộc gọi; mỗi ngày một đèn xanh, vàng, đỏ cho gia đình. / A daily call, a daily light for the family.",
  applicationName: "Chào Bà",
  appleWebApp: { capable: true, title: "Chào Bà", statusBarStyle: "default" },
  icons: { icon: "/icons/icon.svg", apple: "/apple-icon.png" },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f7f3ec" },
    { media: "(prefers-color-scheme: dark)", color: "#22201c" },
  ],
};

// Runs before paint: restores language + theme so there is no flash.
const boot = `(function(){try{var d=document.documentElement;var l=localStorage.getItem('cb-lang');if(l==='en'||l==='vi'){d.dataset.lang=l;d.lang=l}var t=localStorage.getItem('cb-theme');if(t==='dark'||t==='light'){d.dataset.theme=t}}catch(e){}})();`;

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="vi" data-lang="vi" className={font.variable} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: boot }} />
      </head>
      <body className="min-h-dvh">
        {children}
        <SwRegister />
      </body>
    </html>
  );
}
