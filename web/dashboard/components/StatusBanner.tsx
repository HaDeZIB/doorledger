"use client";

import type { Banner, BannerIcon, BannerTone } from "@/lib/banner";
import { IconAlert, IconCheck, IconClock, IconPackage, IconSnow, IconUrgent, IconUser } from "./icons";
import { cx } from "./ui";

const ICON: Record<BannerIcon, React.ComponentType<{ size?: number }>> = {
  check: IconCheck,
  alert: IconAlert,
  user: IconUser,
  package: IconPackage,
  snow: IconSnow,
  clock: IconClock,
};

const STYLE: Record<BannerTone, string> = {
  ok: "bg-ok-soft border-ok-bar/30 text-ok",
  calm: "bg-brand-soft border-brand/25 text-brand-strong",
  warn: "bg-warn-soft border-warn-bar/40 text-warn",
  crit: "bg-crit-soft border-crit-bar/40 text-crit",
};

/** Spoken/visible severity word, so the tone is never carried by color alone. */
const TONE_WORD: Record<BannerTone, string> = {
  ok: "OK",
  calm: "Update",
  warn: "Needs attention",
  crit: "Urgent",
};

/**
 * One sentence that answers "is Mom OK right now?" before anything else. The wording is
 * derived by the pure `deriveBanner()` (lib/banner.ts); this component only renders it.
 * Not an aria-live region itself: the sub line ticks every minute. Headline changes are
 * announced by <Announcer/>.
 */
export function StatusBanner({ banner }: { banner: Banner }) {
  const Icon = banner.icon === "alert" && banner.tone === "crit" ? IconUrgent : ICON[banner.icon];
  const { tone } = banner;
  return (
    <section aria-label="Right now" className={cx("flex items-start gap-4 rounded-3xl border px-5 py-4 transition-colors duration-500 sm:items-center sm:px-6 lg:py-3 xl:py-2.5", STYLE[tone])}>
      <span className="relative mt-0.5 flex h-11 w-11 xl:h-10 xl:w-10 shrink-0 items-center justify-center rounded-2xl bg-surface/80 sm:mt-0">
        <Icon size={24} />
        {(tone === "warn" || tone === "crit") && <span className="absolute -right-0.5 -top-0.5 h-3 w-3 rounded-full bg-current animate-pulse-ring" aria-hidden />}
      </span>
      <div className="min-w-0">
        <p className="text-sm font-semibold uppercase tracking-[0.08em] lg:sr-only">
          Right now<span className="sr-only"> · {TONE_WORD[tone]}</span>
        </p>
        <p key={banner.head} className="animate-enter text-xl font-semibold leading-snug text-ink sm:text-2xl lg:text-[1.4rem] xl:text-[1.3rem]">
          {(tone === "warn" || tone === "crit") && (
            <span className="mr-2 inline-block rounded-md border border-current px-1.5 py-0.5 align-[0.2em] text-[0.7rem] font-bold uppercase leading-none tracking-wide text-current">
              {TONE_WORD[tone]}
            </span>
          )}
          {banner.head}
        </p>
        <p className="mt-0.5 text-ink-2 xl:text-[0.97rem]">{banner.sub}</p>
      </div>
    </section>
  );
}
