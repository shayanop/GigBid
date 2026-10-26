"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { RunTimeline, type TraceEvent } from "@/components/RunTimeline";
import { Loading, Notice, PageHeader, StatusTag, TextLink } from "@/components/ui";
import { runsTraceOptions, runsTraceQueryKey } from "@/lib/api/@tanstack/react-query.gen";
import { errorMessage } from "@/lib/labels";

export default function RunViewer() {
  const { id } = useParams<{ id: string }>();
  const queryClient = useQueryClient();
  const trace = useQuery(runsTraceOptions({ path: { thread_id: id } }));
  const [live, setLive] = useState<string[]>([]);
  const [connected, setConnected] = useState(false);

  // Live progress: node events arrive over SSE; the full trace is refetched when a run
  // pauses or ends.
  useEffect(() => {
    const source = new EventSource(`/api/runs/${id}/events`);
    const refresh = () => {
      setLive([]);
      queryClient.invalidateQueries({ queryKey: runsTraceQueryKey({ path: { thread_id: id } }) });
    };
    source.addEventListener("open", () => setConnected(true));
    source.addEventListener("node", (e) => {
      const node = JSON.parse((e as MessageEvent).data).node as string;
      if (node !== "__interrupt__") setLive((nodes) => [...nodes, node]);
    });
    source.addEventListener("interrupt", refresh);
    source.addEventListener("done", refresh);
    source.addEventListener("error", () => setConnected(false));
    return () => source.close();
  }, [id, queryClient]);

  if (trace.isPending) return <Loading what="the run" />;
  if (trace.isError) return <Notice>{errorMessage(trace.error)}</Notice>;
  const { status, usage } = trace.data;

  return (
    <>
      <PageHeader title="Agent run">
        <TextLink href={`/jobs/${id}`}>Back to the job</TextLink>
      </PageHeader>
      <p className="mb-6 flex flex-wrap items-center gap-3">
        {status && <StatusTag status={status} />}
        <span className="tnum text-slate">
          {String(usage.steps ?? 0)} steps, {Number(usage.tokens ?? 0).toLocaleString()} tokens
        </span>
        {connected && <span className="text-[13px] text-evidence">Live</span>}
      </p>
      {trace.data.trace.length === 0 && live.length === 0
        ? <p className="text-slate">The run has not started yet. It appears here as soon as the worker picks it up.</p>
        : <RunTimeline events={trace.data.trace as unknown as TraceEvent[]} live={live} />}
    </>
  );
}
