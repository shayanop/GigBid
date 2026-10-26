"use client";

import { useQuery } from "@tanstack/react-query";
import { useParams } from "next/navigation";

import { EvidenceHover } from "@/components/EvidenceHover";
import { button, FitMeter, Loading, Notice, Panel, RiskFlags, StatusTag, TextLink } from "@/components/ui";
import { jobsDetailOptions } from "@/lib/api/@tanstack/react-query.gen";
import { errorMessage, LIVE_STATUSES, percent, usd } from "@/lib/labels";
import Link from "next/link";

const STRENGTH: Record<string, string> = {
  strong: "text-evidence",
  partial: "text-caution",
  none: "text-risk",
};

export default function JobDetail() {
  const { id } = useParams<{ id: string }>();
  const job = useQuery({
    ...jobsDetailOptions({ path: { thread_id: id } }),
    refetchInterval: (q) => (q.state.data && LIVE_STATUSES.has(q.state.data.status) ? 3_000 : false),
  });
  if (job.isPending) return <Loading what="the job" />;
  if (job.isError) return <Notice>{errorMessage(job.error, "Could not load this job.")}</Notice>;
  const j = job.data;
  const evidence = new Map((j.evidence ?? []).map((e) => [e.id, e]));

  return (
    <article>
      <header className="mb-8 flex flex-wrap items-start justify-between gap-4">
        <div className="max-w-3xl">
          <p className="text-[14px] text-slate">{j.job_id}</p>
          <h1 className="text-[28px] font-extrabold leading-tight">{j.title}</h1>
          <div className="mt-2 flex flex-wrap items-center gap-3">
            <StatusTag status={j.status} />
            <TextLink href={`/runs/${id}`}>See how the agents decided</TextLink>
          </div>
        </div>
        {j.status === "awaiting_approval" && (
          <Link href={`/studio/${id}`} className={button.primary}>Review proposal</Link>
        )}
      </header>

      {j.attention && <div className="mb-6"><Notice>{j.attention}</Notice></div>}

      {j.decision_detail && (
        <section className="mb-8 max-w-3xl">
          <h2 className="font-bold">
            Decision: {{ bid: "Bid", watch: "Watch", skip: "Skip" }[j.decision_detail.action]}
          </h2>
          <ul className="mt-1 list-disc pl-5 text-slate">
            {j.decision_detail.reasons.map((r) => <li key={r}>{r}</li>)}
          </ul>
        </section>
      )}

      <div className="grid gap-10 lg:grid-cols-[minmax(0,1fr)_320px]">
        <section aria-labelledby="matrix">
          <div className="mb-3 flex items-center justify-between gap-4">
            <h2 id="matrix" className="font-bold">What the job needs, and your proof</h2>
            <FitMeter score={j.fit} />
          </div>
          {j.fit_report ? (
            <table className="w-full border-collapse text-left">
              <thead className="text-[14px] text-slate">
                <tr className="border-b border-line">
                  <th scope="col" className="py-2 pr-4 font-normal">Requirement</th>
                  <th scope="col" className="py-2 pr-4 font-normal">Coverage</th>
                  <th scope="col" className="py-2 font-normal">Evidence</th>
                </tr>
              </thead>
              <tbody>
                {j.fit_report.matches.map((m) => (
                  <tr key={m.requirement} className="border-b border-line align-top">
                    <td className="py-3 pr-4">{m.requirement}</td>
                    <td className={`py-3 pr-4 font-bold ${STRENGTH[m.strength]}`}>{m.strength}</td>
                    <td className="py-3">
                      <span className="flex flex-wrap gap-1">
                        {m.evidence_ids.length
                          ? m.evidence_ids.map((eid) => <EvidenceHover key={eid} evidence={evidence.get(eid)} />)
                          : <span className="text-slate">Nothing in your portfolio</span>}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="text-slate">{LIVE_STATUSES.has(j.status) ? "The Fit Matcher is still working." : "No fit report."}</p>
          )}
          {j.spec && (
            <div className="mt-8 grid gap-6 sm:grid-cols-2">
              <Panel title="Deliverables">
                <ul className="list-disc pl-5">{j.spec.deliverables.map((d) => <li key={d}>{d}</li>)}</ul>
              </Panel>
              <Panel title="Unstated needs">
                {j.spec.implicit_needs?.length
                  ? <ul className="list-disc pl-5">{j.spec.implicit_needs.map((d) => <li key={d}>{d}</li>)}</ul>
                  : <p className="text-slate">None spotted.</p>}
              </Panel>
              <Panel title="Timeline"><p>{j.spec.timeline}</p></Panel>
              <Panel title="Budget as posted"><p>{j.spec.budget}</p></Panel>
            </div>
          )}
        </section>

        <aside className="flex flex-col gap-6">
          <Panel title="Risk">
            {j.risk_report ? (
              <>
                <p className="tnum text-[22px] font-extrabold">{percent(j.risk_report.score)}<span className="text-[14px] font-normal text-slate"> / 100</span></p>
                <div className="mt-1"><RiskFlags flags={j.risk_report.flags} /></div>
                {j.risk_report.injection_detected && (
                  <p className="mt-2 text-[14px] text-caution">
                    This post contains instructions aimed at AI assistants. GigBid ignored them.
                  </p>
                )}
                <p className="mt-2 text-slate">{j.risk_report.summary}</p>
              </>
            ) : <p className="text-slate">Not assessed yet.</p>}
          </Panel>
          <Panel title="Suggested bid">
            {j.price_quote ? (
              <>
                <p className="tnum text-[22px] font-extrabold">
                  {usd(j.price_quote.amount)}
                  <span className="text-[14px] font-normal text-slate">
                    {j.price_quote.budget_type === "hourly" ? " per hour" : " fixed"}
                  </span>
                </p>
                <p className="tnum text-[14px]">{j.price_quote.connects_cost} Connects to apply</p>
                <p className="mt-2 text-[14px] text-slate">{j.price_quote.rationale}</p>
              </>
            ) : <p className="text-slate">Priced only for jobs worth bidding on.</p>}
          </Panel>
        </aside>
      </div>
    </article>
  );
}
