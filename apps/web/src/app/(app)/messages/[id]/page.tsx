"use client";

import { useQuery } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { useState } from "react";

import { ApprovalPanel } from "@/components/ApprovalPanel";
import { Loading, Notice, Panel, StatusTag, TextLink } from "@/components/ui";
import { messagesConversationOptions } from "@/lib/api/@tanstack/react-query.gen";
import { errorMessage, flagLabel, INTENT, LIVE_STATUSES, when, whenUtc } from "@/lib/labels";

export default function Conversation() {
  const { id } = useParams<{ id: string }>();
  const [editing, setEditing] = useState(false);
  const conv = useQuery({
    ...messagesConversationOptions({ path: { conversation_id: id } }),
    refetchInterval: (q) => (q.state.data && LIVE_STATUSES.has(q.state.data.status) ? 2_000 : false),
  });
  if (conv.isPending) return <Loading what="the conversation" />;
  if (conv.isError) return <Notice>{errorMessage(conv.error, "Could not load this conversation.")}</Notice>;
  const c = conv.data;
  const pending = c.approval_request;

  return (
    <article>
      <header className="mb-8">
        <p className="text-[14px] text-slate">Conversation about</p>
        <h1 className="text-[28px] font-extrabold leading-tight">{c.title ?? c.job_id}</h1>
        <p className="mt-2 flex flex-wrap items-center gap-3">
          <StatusTag status={c.status} />
          <TextLink href={`/runs/${id}`}>See how the reply was drafted</TextLink>
        </p>
      </header>
      {c.attention && <div className="mb-6"><Notice>{c.attention}</Notice></div>}

      <div className="grid gap-10 lg:grid-cols-[minmax(0,1fr)_320px]">
        <section aria-label="Conversation" className={editing ? "opacity-40" : undefined}>
          <ol className="flex flex-col gap-5">
            {(c.messages ?? []).map((m) => (
              <li key={m.id} className={m.sender === "freelancer" ? "sm:pl-12" : "sm:pr-12"}>
                <p className="text-[13px] text-slate">
                  <strong className="text-ink">{m.sender === "client" ? "Client" : "You"}</strong>, {when(m.sent_at)}
                </p>
                <p className="mt-1 whitespace-pre-wrap">{m.body}</p>
              </li>
            ))}
          </ol>
          {pending && (
            <div className="mt-8">
              <h2 className="mb-2 font-bold">Your drafted reply</h2>
              <p className="max-w-[68ch] whitespace-pre-wrap rounded-sm bg-surface px-6 py-5 font-serif text-[17px] leading-relaxed shadow-[0_1px_0_var(--color-line)]">
                {pending.reply}
              </p>
            </div>
          )}
        </section>

        <aside aria-label="Notes" className="flex flex-col gap-6">
          {c.intent_detail && (
            <Panel title="What the client wants">
              <p className="font-bold">{INTENT[c.intent_detail.intent] ?? c.intent_detail.intent}</p>
              <p className="text-slate">{c.intent_detail.summary}</p>
              {c.intent_detail.intent === "scam_signal" && (
                <p className="mt-2 text-[14px] text-risk">
                  This looks like an attempt to move off the platform. The reply keeps the conversation here.
                </p>
              )}
              {c.intent_detail.injection_detected && (
                <p className="mt-2 text-[14px] text-caution">The message contains instructions aimed at AI assistants. They were ignored.</p>
              )}
            </Panel>
          )}
          {pending && pending.slots.length > 0 && (
            <Panel title="Interview times offered">
              <ul className="tnum">{pending.slots.map((s) => <li key={s.start}>{whenUtc(s.start)} UTC</li>)}</ul>
              <p className="mt-2 text-[14px] text-slate">
                Approving sends the reply and holds these times on your calendar until the client picks one.
              </p>
            </Panel>
          )}
          {pending && (
            <Panel title="Compliance">
              {pending.compliance.violations.length
                ? <ul className="list-disc pl-5 text-[14px]">{pending.compliance.violations.map((v) => <li key={v}>{flagLabel(v)}</li>)}</ul>
                : <p className="text-slate">Passes the marketplace rules.</p>}
            </Panel>
          )}
        </aside>
      </div>
      {pending && (
        <ApprovalPanel kind="message" threadId={id} text={pending.reply} approveLabel="Approve and send"
                       onEditing={setEditing} />
      )}
    </article>
  );
}
