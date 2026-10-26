"use client";

import { useQuery } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { Fragment, useState } from "react";

import { ApprovalPanel } from "@/components/ApprovalPanel";
import { EvidenceHover } from "@/components/EvidenceHover";
import { Loading, Notice, Panel, StatusTag, TextLink } from "@/components/ui";
import { approvalsReviewOptions, jobsDetailOptions } from "@/lib/api/@tanstack/react-query.gen";
import type { ClaimOut } from "@/lib/api/types.gen";
import { errorMessage, flagLabel, LIVE_STATUSES, SUPPORT, usd } from "@/lib/labels";

const CITATION = /\s*\(?\[[\w./-]+#\d+\](?:\s*,\s*\[[\w./-]+#\d+\])*\)?/g;
const norm = (s: string) => s.replace(/\[[^\]]*\]/g, " ").replace(/\W+/g, " ").trim().toLowerCase();

export default function Studio() {
  const { id } = useParams<{ id: string }>();
  const [active, setActive] = useState<number | null>(null);
  const [editing, setEditing] = useState(false);
  const job = useQuery({
    ...jobsDetailOptions({ path: { thread_id: id } }),
    refetchInterval: (q) => (q.state.data && LIVE_STATUSES.has(q.state.data.status) ? 2_000 : false),
  });
  const waiting = job.data?.status === "awaiting_approval";
  const review = useQuery({ ...approvalsReviewOptions({ path: { thread_id: id } }), enabled: waiting });

  if (job.isPending) return <Loading what="the proposal" />;
  if (job.isError) return <Notice>{errorMessage(job.error)}</Notice>;
  if (!waiting) {
    return (
      <div className="max-w-xl">
        <h1 className="text-[28px] font-extrabold leading-tight">{job.data.title}</h1>
        <p className="mt-3 flex items-center gap-3">
          <StatusTag status={job.data.status} />
          {job.data.status === "processing" && <span className="text-slate">Applying your decision…</span>}
        </p>
        {job.data.attention && <div className="mt-4"><Notice>{job.data.attention}</Notice></div>}
        <p className="mt-6"><TextLink href={`/jobs/${id}`}>Back to the job</TextLink></p>
      </div>
    );
  }
  if (review.isPending) return <Loading what="the proposal" />;
  if (review.isError) return <Notice>{errorMessage(review.error)}</Notice>;

  const { draft, claims, risk, price, compliance, preview } = review.data.request;
  const kept = claims.filter((c) => c.label !== "unsupported");
  const footnotes = numberEvidence(kept);
  const critique = job.data.critique;

  return (
    <article>
      <header className="mb-8">
        <p className="text-[14px] text-slate">Proposal for</p>
        <h1 className="text-[28px] font-extrabold leading-tight">{review.data.title}</h1>
      </header>
      <div className="grid gap-10 lg:grid-cols-[minmax(0,1fr)_340px]">
        <section aria-label="Draft cover letter" className={editing ? "opacity-40" : undefined}>
          <div className="max-w-[68ch] rounded-sm bg-surface px-6 py-8 font-serif text-[18px] leading-[1.7] shadow-[0_1px_0_var(--color-line)] sm:px-10">
            {draft.cover_letter.split(/\n+/).filter(Boolean).map((paragraph, p) => (
              <p key={p} className="mb-4 last:mb-0">
                {sentences(paragraph).map((sentence, s) => {
                  const ci = kept.findIndex((c) => norm(c.sentence) && norm(sentence).includes(norm(c.sentence)));
                  const text = sentence.replace(CITATION, "");
                  const marks = ci >= 0 ? kept[ci].evidence_ids.map((e) => footnotes.get(e)).filter(Boolean) : [];
                  return (
                    <Fragment key={s}>
                      {ci >= 0 ? (
                        <span tabIndex={0} className="claim" data-label={kept[ci].label}
                              data-active={active === ci} onMouseEnter={() => setActive(ci)}
                              onFocus={() => setActive(ci)}>
                          {text}
                          <sup className="ml-0.5 font-sans text-[12px] text-evidence">{marks.join(",")}</sup>
                        </span>
                      ) : text}{" "}
                    </Fragment>
                  );
                })}
              </p>
            ))}
            {draft.screening_answers?.map((a) => (
              <div key={a.question} className="mt-6 border-t border-line pt-4">
                <p className="font-sans font-bold">{a.question}</p>
                <p className="mt-1">{a.answer.replace(CITATION, "")}</p>
              </div>
            ))}
          </div>
          <p className="mt-3 max-w-[68ch] text-[14px] text-slate">
            Underlined sentences are claims about your work: green is backed by your portfolio, dashed
            amber only partly. Evidence ids are for you; the client sees the letter without them.
          </p>
        </section>

        <aside aria-label="Notes" className="flex flex-col gap-6">
          <Panel title="Evidence for each claim">
            {kept.length === 0 && <p className="text-slate">The letter makes no claims about past work.</p>}
            <ol className="flex flex-col gap-3">
              {kept.map((c, i) => (
                <li key={i} onMouseEnter={() => setActive(i)}
                    className={`rounded-sm px-2 py-1 ${active !== i ? "" : c.label === "supported" ? "bg-evidence-soft" : "bg-caution-soft"}`}>
                  <p className={`text-[13px] ${c.label === "supported" ? "text-evidence" : "text-caution"}`}>
                    {c.evidence_ids.map((e) => footnotes.get(e)).join(", ")} {SUPPORT[c.label]}
                  </p>
                  <p className="text-[14px]">{c.claim.replace(CITATION, "")}</p>
                  <span className="mt-1 flex flex-wrap gap-1">
                    {c.evidence.map((e) => <EvidenceHover key={e.id} evidence={e} />)}
                  </span>
                </li>
              ))}
            </ol>
            {claims.length > kept.length && (
              <p className="mt-3 text-[14px] text-slate">
                {claims.length - kept.length === 1
                  ? "1 claim with no evidence was removed before you saw this draft."
                  : `${claims.length - kept.length} claims with no evidence were removed before you saw this draft.`}
              </p>
            )}
          </Panel>
          <Panel title="Critic">
            {critique?.approve ? <p className="text-slate">No issues left.</p> : (
              <ul className="list-disc pl-5 text-[14px]">{critique?.issues.map((i) => <li key={i}>{i}</li>)}</ul>
            )}
          </Panel>
          <Panel title="Compliance">
            {compliance.violations.length
              ? <ul className="list-disc pl-5 text-[14px]">{compliance.violations.map((v) => <li key={v}>{flagLabel(v)}</li>)}</ul>
              : <p className="text-slate">Passes the marketplace rules.</p>}
          </Panel>
          <Panel title="What will be sent">
            <dl className="tnum grid grid-cols-[auto_1fr] gap-x-4 text-[14px]">
              <dt className="text-slate">Bid</dt><dd>{usd(price.amount)} {price.budget_type === "hourly" ? "per hour" : "fixed"}</dd>
              <dt className="text-slate">Cost</dt><dd>{preview.connects_cost} Connects</dd>
              <dt className="text-slate">Balance after</dt><dd>{preview.connects_balance - preview.connects_cost} Connects</dd>
              <dt className="text-slate">Client risk</dt><dd>{Math.round(risk.score * 100)} / 100</dd>
            </dl>
            <details className="mt-2 text-[14px]">
              <summary className="cursor-pointer text-action">Exact message the client receives</summary>
              <p className="mt-2 whitespace-pre-wrap font-serif">{String(preview.payload.cover_letter ?? "")}</p>
            </details>
          </Panel>
        </aside>
      </div>
      <ApprovalPanel threadId={id} letter={draft.cover_letter} connectsCost={preview.connects_cost}
                     onEditing={setEditing} />
    </article>
  );
}

function sentences(paragraph: string): string[] {
  return paragraph.split(/(?<=[.!?])\s+/).filter(Boolean);
}

/** Numbers each cited evidence id in order of first use, like footnotes. */
function numberEvidence(claims: ClaimOut[]): Map<string, number> {
  const numbers = new Map<string, number>();
  for (const c of claims) for (const e of c.evidence_ids) if (!numbers.has(e)) numbers.set(e, numbers.size + 1);
  return numbers;
}
