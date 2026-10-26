"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";

import { Loading, Notice, PageHeader } from "@/components/ui";
import { jobsInboxOptions } from "@/lib/api/@tanstack/react-query.gen";
import { errorMessage, usd } from "@/lib/labels";

// Proposal stages. Viewed, replied, interview, hired and lost come from client activity
// on the marketplace and fill in once conversations are connected.
const STAGES: { name: string; statuses: string[] }[] = [
  { name: "Drafted", statuses: ["awaiting_approval", "processing"] },
  { name: "Submitted", statuses: ["submitted"] },
  { name: "Viewed", statuses: ["viewed"] },
  { name: "Replied", statuses: ["replied"] },
  { name: "Interview", statuses: ["interview"] },
  { name: "Hired", statuses: ["hired"] },
  { name: "Lost", statuses: ["lost"] },
];

export default function Pipeline() {
  const jobs = useQuery({ ...jobsInboxOptions({ query: { limit: 200 } }), refetchInterval: 15_000 });
  if (jobs.isPending) return <Loading what="your pipeline" />;
  if (jobs.isError) return <Notice>{errorMessage(jobs.error)}</Notice>;

  return (
    <>
      <PageHeader title="Pipeline" />
      <div className="-mx-4 flex snap-x gap-4 overflow-x-auto px-4 pb-4">
        {STAGES.map((stage) => {
          const items = jobs.data.filter((j) => stage.statuses.includes(j.status));
          return (
            <section key={stage.name} aria-label={stage.name}
                     className="w-64 shrink-0 snap-start border-t-2 border-ink pt-2">
              <h2 className="mb-3 flex justify-between font-bold">
                {stage.name}<span className="tnum font-normal text-slate">{items.length}</span>
              </h2>
              <ul className="flex flex-col gap-2">
                {items.map((j) => (
                  <li key={j.thread_id}>
                    <Link href={j.status === "awaiting_approval" ? `/studio/${j.thread_id}` : `/jobs/${j.thread_id}`}
                          className="block rounded-sm bg-surface px-3 py-2 hover:outline hover:outline-line">
                      <span className="block font-bold leading-snug">{j.title}</span>
                      <span className="tnum text-[13px] text-slate">{usd(j.price)}, {j.connects_cost ?? "–"} Connects</span>
                    </Link>
                  </li>
                ))}
                {items.length === 0 && <li className="text-[14px] text-slate">None yet</li>}
              </ul>
            </section>
          );
        })}
      </div>
    </>
  );
}
