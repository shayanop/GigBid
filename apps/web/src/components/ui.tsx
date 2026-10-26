import Link from "next/link";

import { STATUS, flagLabel, percent, type Tone } from "@/lib/labels";

const TONE: Record<Tone, string> = {
  quiet: "text-slate border-line",
  action: "text-action border-action",
  caution: "text-caution border-caution",
  muted: "text-slate border-transparent",
  evidence: "text-evidence border-evidence",
  risk: "text-risk border-risk",
};

export function StatusTag({ status }: { status: string }) {
  const s = STATUS[status] ?? { label: status, tone: "quiet" as Tone };
  return (
    <span className={`inline-block whitespace-nowrap rounded-sm border px-1.5 py-px text-[13px] ${TONE[s.tone]}`}>
      {s.label}
    </span>
  );
}

/** Fit as a thin bar plus the number; the bar is decoration, the number is the value. */
export function FitMeter({ score }: { score?: number | null }) {
  const width = score ? Math.round(score * 100) : 0;
  return (
    <span className="inline-flex items-center gap-2" title="Portfolio fit">
      <span aria-hidden className="h-1.5 w-12 overflow-hidden rounded-full bg-line">
        <span className="block h-full bg-evidence" style={{ width: `${width}%` }} />
      </span>
      <span className="tnum w-7 text-right font-bold">{percent(score)}</span>
    </span>
  );
}

export function RiskFlags({ flags }: { flags?: string[] | null }) {
  if (!flags?.length) return <span className="text-slate">None found</span>;
  return (
    <span className="flex flex-wrap gap-1">
      {flags.map((f) => (
        <span key={f} className="rounded-sm bg-risk-soft px-1.5 py-px text-[13px] text-risk">
          {flagLabel(f)}
        </span>
      ))}
    </span>
  );
}

export function PageHeader({ title, children }: { title: string; children?: React.ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <h1 className="text-[28px] font-extrabold leading-tight tracking-[-0.01em]">{title}</h1>
      {children}
    </div>
  );
}

export function Notice({ tone = "risk", children }: { tone?: "risk" | "caution"; children: React.ReactNode }) {
  const style = tone === "risk" ? "bg-risk-soft text-risk" : "bg-caution-soft text-caution";
  return <p role="alert" className={`rounded-sm px-3 py-2 ${style}`}>{children}</p>;
}

export function Loading({ what }: { what: string }) {
  return <p className="text-slate" aria-live="polite">Loading {what}…</p>;
}

export function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="border-t border-line pt-3">
      <h2 className="mb-2 font-bold">{title}</h2>
      {children}
    </section>
  );
}

export const button = {
  primary:
    "inline-flex items-center justify-center whitespace-nowrap rounded-sm bg-action px-4 py-2 font-bold text-white hover:bg-action-strong disabled:cursor-not-allowed disabled:opacity-50",
  secondary:
    "inline-flex items-center justify-center whitespace-nowrap rounded-sm border border-ink/30 bg-surface px-4 py-2 font-bold hover:border-ink disabled:cursor-not-allowed disabled:opacity-50",
  danger:
    "inline-flex items-center justify-center whitespace-nowrap rounded-sm border border-risk px-4 py-2 font-bold text-risk hover:bg-risk-soft disabled:cursor-not-allowed disabled:opacity-50",
};

export const input =
  "w-full rounded-sm border border-line bg-surface px-3 py-2 placeholder:text-slate/70 focus-visible:border-action";

export function TextLink({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <Link href={href} className="font-bold text-action underline-offset-4 hover:underline">
      {children}
    </Link>
  );
}
