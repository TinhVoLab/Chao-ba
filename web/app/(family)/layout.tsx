import { Suspense } from "react";
import Link from "next/link";
import Image from "next/image";
import { LangToggle, ThemeToggle } from "@/components/Controls";
import { Nav } from "@/components/Nav";

export default function FamilyLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-dvh lg:pl-56">
      <div className="sticky top-0 z-20 lg:z-40 border-b border-line/70 bg-bg/90 backdrop-blur-sm lg:fixed lg:inset-x-0 lg:left-0 lg:w-56 lg:border-b-0 lg:bg-transparent lg:backdrop-blur-none">
        <div className="mx-auto flex h-14 max-w-xl items-center justify-between px-4 lg:h-24 lg:flex-col lg:items-start lg:justify-center lg:gap-2">
          <Link href="/" className="flex items-center gap-2 font-extrabold tracking-tight text-lg">
            <Image src="/icons/icon.svg" alt="" width={28} height={28} unoptimized className="rounded-lg" />
            Chào Bà
          </Link>
          <div className="flex items-center gap-2">
            <LangToggle />
            <ThemeToggle />
          </div>
        </div>
      </div>
      <main className="mx-auto w-full max-w-xl px-4 pb-32 pt-3 lg:max-w-5xl lg:px-10 lg:pb-16 lg:pt-10">{children}</main>
      <Suspense fallback={null}>
        <Nav />
      </Suspense>
    </div>
  );
}
