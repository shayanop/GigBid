"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { button, FitMeter, input, Loading, Notice, PageHeader, RiskFlags, StatusTag } from "@/components/ui";
import { jobsAnalyzeMutation, jobsInboxOptions, jobsInboxQueryKey } from "@/lib/api/@tanstack/react-query.gen";
import type { JobSummary } from "@/lib/api/types.gen";
import { errorMessage, LIVE_STATUSES, usd } from "@/lib/labels";

const FILTERS: { label: string; status?: string }[] = [
  { label: "All" },
  { label: "Needs your approval", status: "awaiting_approval" },
  { label: "Watching", status: "watching" },
  { label: "Needs attention", status: "needs_attention" },
  { label: "Skipped", status: "skipped" },
];

export default function Inbox() {
  const [status, setStatus] = useState<string | undefined>();
  const jobs = useQuery({
    ...jobsInboxOptions({ query: { status, limit: 200 } }),
    // Keep polling while any job is still being worked on.
    refetchInterval: (q) => (q.state.data?.some((j) => LIVE_STATUSES.has(j.status)) ? 3_000 : false),
  });

  return (
    <>
      <PageHeader title="Inbox">
        <AnalyzeForm />
      </PageHeader>
      <div role="tablist" aria-label="Filter by status" className="mb-4 flex flex-wrap gap-1">
        {FILTERS.map((f) => (
          <button key={f.label} role="tab" aria-selected={status === f.status}
                  onClick={() => setStatus(f.status)}
                  className={`rounded-sm px-3 py-1 ${status === f.status ? "bg-ink text-white" : "text-slate hover:text-ink"}`}>
            {f.label}
          </button>
        ))}
      </div>
      {jobs.isPending && <Loading what="your jobs" />}
      {jobs.isError && <Notice>{errorMessage(jobs.error, "Could not load your inbox.")}</Notice>}
      {jobs.data?.length === 0 && (
        <div className="border-t border-line py-12">
          <p className="font-bold">{status ? "No jobs with this status." : "Your inbox is empty."}</p>
          {!status && (
            <p className="mt-1 text-slate">
              Analyze a job by its id above, or add a saved search in Settings and GigBid will bring jobs here.
            </p>
          )}
        </div>
      )}
      {!!jobs.data?.length && <Ledger jobs={jobs.data} />}
    </>
  );
}

function Ledger({ jobs }: { jobs: JobSummary[] }) {
  const router = useRouter();
  return (
    <table className="w-full border-collapse text-left">
      <thead className="text-[14px] text-slate max-md:sr-only">
        <tr className="border-b border-line">
          <th scope="col" className="py-2 pr-4 font-normal">Fit</th>
          <th scope="col" className="py-2 pr-4 font-normal">Job</th>
          <th scope="col" className="py-2 pr-4 font-normal">Status</th>
          <th scope="col" className="py-2 pr-4 font-normal">Risk</th>
          <th scope="col" className="py-2 text-right font-normal">Bid</th>
        </tr>
      </thead>
      <tbody>
        {jobs.map((job) => (
          <tr key={job.thread_id} data-testid="inbox-row"
              onClick={() => router.push(`/jobs/${job.thread_id}`)}
              className="cursor-pointer border-b border-line align-top hover:bg-surface max-md:grid max-md:grid-cols-[auto_1fr] max-md:gap-x-3 max-md:py-3">
            <td className="py-3 pr-4 max-md:row-span-3 max-md:py-0"><FitMeter score={job.fit} /></td>
            <td className="py-3 pr-4 max-md:py-0">
              <Link href={`/jobs/${job.thread_id}`} onClick={(e) => e.stopPropagation()}
                    className="font-bold hover:underline">{job.title}</Link>
              <span className="block text-[13px] text-slate">{job.job_id}</span>
              {job.attention && <span className="mt-1 block text-[13px] text-risk">{job.attention}</span>}
            </td>
            <td className="py-3 pr-4 max-md:py-1"><StatusTag status={job.status} /></td>
            <td className="py-3 pr-4 max-md:py-0">
              {job.risk != null ? <RiskFlags flags={job.flags} /> : <span className="text-slate">–</span>}
            </td>
            <td className="tnum py-3 text-right max-md:col-start-2 max-md:py-1 max-md:text-left">
              {job.price != null ? <>{usd(job.price)}<span className="block text-[13px] text-slate">{job.connects_cost} Connects</span></> : "–"}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function AnalyzeForm() {
  const [jobId, setJobId] = useState("");
  const queryClient = useQueryClient();
  const analyze = useMutation({
    ...jobsAnalyzeMutation(),
    onSuccess: () => {
      setJobId("");
      queryClient.invalidateQueries({ queryKey: jobsInboxQueryKey().slice(0, 1) });
    },
  });
  return (
    <form className="flex flex-col gap-1"
          onSubmit={(e) => { e.preventDefault(); analyze.mutate({ body: { job_id: jobId.trim() } }); }}>
      <div className="flex gap-2">
        <label className="sr-only" htmlFor="job-id">Marketplace job id</label>
        <input id="job-id" className={`${input} w-44`} placeholder="job_00012" required
               pattern="[\w\-]{1,64}" value={jobId} onChange={(e) => setJobId(e.target.value)} />
        <button className={button.primary} disabled={analyze.isPending}>Analyze job</button>
      </div>
      {analyze.isError && (
        <span role="alert" className="text-[14px] text-risk">{errorMessage(analyze.error)}</span>
      )}
    </form>
  );
}
