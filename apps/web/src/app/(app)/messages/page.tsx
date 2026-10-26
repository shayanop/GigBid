"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";

import { button, Loading, Notice, PageHeader, StatusTag } from "@/components/ui";
import { messagesConversationsOptions, messagesRefreshMutation } from "@/lib/api/@tanstack/react-query.gen";
import { errorMessage, INTENT, LIVE_STATUSES, when } from "@/lib/labels";

export default function Messages() {
  const [checking, setChecking] = useState(false);
  const conversations = useQuery({
    ...messagesConversationsOptions(),
    refetchInterval: (q) =>
      checking || q.state.data?.some((c) => LIVE_STATUSES.has(c.status)) ? 2_000 : 30_000,
  });
  const refresh = useMutation({
    ...messagesRefreshMutation(),
    onSuccess: () => {
      setChecking(true);
      setTimeout(() => setChecking(false), 20_000); // poll fast while the check runs
    },
  });

  return (
    <>
      <PageHeader title="Messages">
        <button className={button.secondary} disabled={refresh.isPending || checking}
                onClick={() => refresh.mutate({})}>
          {checking ? "Checking…" : "Check for new messages"}
        </button>
      </PageHeader>
      {refresh.isError && <div className="mb-4"><Notice>{errorMessage(refresh.error)}</Notice></div>}
      {conversations.isPending && <Loading what="your conversations" />}
      {conversations.isError && <Notice>{errorMessage(conversations.error)}</Notice>}
      {conversations.data?.length === 0 && (
        <div className="border-t border-line py-12">
          <p className="font-bold">No client messages yet.</p>
          <p className="mt-1 text-slate">
            When a client writes to you, GigBid drafts a reply here for you to approve.
          </p>
        </div>
      )}
      <ul className="divide-y divide-line border-t border-line">
        {conversations.data?.map((c) => (
          <li key={c.id}>
            <Link href={`/messages/${c.id}`} data-testid="conversation-row"
                  className="grid gap-x-6 gap-y-1 py-4 hover:bg-surface md:grid-cols-[minmax(0,1fr)_auto]">
              <span>
                <span className="font-bold">{c.title ?? c.job_id}</span>
                {c.intent && <span className="ml-3 text-[14px] text-slate">{INTENT[c.intent] ?? c.intent}</span>}
                {c.last_message && (
                  <span className="mt-1 block max-w-[70ch] truncate text-slate">“{c.last_message}”</span>
                )}
              </span>
              <span className="flex items-center gap-3 md:flex-col md:items-end">
                <StatusTag status={c.status} />
                <span className="tnum text-[13px] text-slate">{when(c.updated_at)}</span>
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </>
  );
}
