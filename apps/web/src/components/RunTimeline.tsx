import { NODE } from "@/lib/labels";

export type TraceEvent = {
  node: string;
  at: string;
  ms: number;
  tokens: number;
  calls: { kind: string; tool?: string; ok?: boolean; tokens?: number; ms?: number; prompt_version?: number }[];
};

/** One row per graph node run: when, how long, tokens, and the tools it called. */
export function RunTimeline({ events, live }: { events: TraceEvent[]; live: string[] }) {
  return (
    <ol className="relative border-l border-line pl-6">
      {events.map((e, i) => (
        <li key={`${e.node}-${i}`} className="mb-5">
          <span aria-hidden className="absolute -left-[5px] mt-1.5 h-2.5 w-2.5 rounded-full bg-evidence" />
          <div className="flex flex-wrap items-baseline gap-x-3">
            <span className="font-bold">{NODE[e.node] ?? e.node}</span>
            <span className="tnum text-[13px] text-slate">
              {new Date(e.at).toLocaleTimeString()}, {(e.ms / 1000).toFixed(1)} s
              {e.tokens > 0 && `, ${e.tokens.toLocaleString()} tokens`}
            </span>
          </div>
          {e.calls.filter((c) => c.kind === "tool").length > 0 && (
            <ul className="mt-1 flex flex-wrap gap-1 text-[13px]">
              {e.calls.filter((c) => c.kind === "tool").map((c, j) => (
                <li key={j} className={`rounded-sm px-1.5 ${c.ok ? "bg-paper text-slate" : "bg-risk-soft text-risk"}`}>
                  {c.tool}
                </li>
              ))}
            </ul>
          )}
        </li>
      ))}
      {live.map((node, i) => (
        <li key={`live-${node}-${i}`} className="mb-5" aria-live="polite">
          <span aria-hidden className="absolute -left-[5px] mt-1.5 h-2.5 w-2.5 animate-pulse rounded-full bg-action" />
          <span className="font-bold">{NODE[node] ?? node}</span>{" "}
          <span className="text-[13px] text-slate">finished just now</span>
        </li>
      ))}
    </ol>
  );
}
