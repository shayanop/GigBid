"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Loading, Notice, Panel } from "@/components/ui";
import {
  memoryForgetOutcomesMutation,
  memoryForgetPreferenceMutation,
  memoryLearnedOptions,
  memoryLearnedQueryKey,
} from "@/lib/api/@tanstack/react-query.gen";
import type { Preference } from "@/lib/api/types.gen";
import { errorMessage } from "@/lib/labels";

/** What GigBid has learned from you, the evidence for it, and the controls to forget it. */
export function MemoryPanel() {
  const queryClient = useQueryClient();
  const memory = useQuery(memoryLearnedOptions());
  const refresh = () => queryClient.invalidateQueries({ queryKey: memoryLearnedQueryKey() });
  const forgetPreference = useMutation({ ...memoryForgetPreferenceMutation(), onSuccess: refresh });
  const forgetOutcomes = useMutation({ ...memoryForgetOutcomesMutation(), onSuccess: refresh });
  const forget = (key: string) => forgetPreference.mutate({ path: { key } });

  if (memory.isPending) return <Loading what="what GigBid has learned" />;
  if (memory.isError) return <Notice>{errorMessage(memory.error)}</Notice>;
  const m = memory.data;

  return (
    <>
      <Panel title="What GigBid learned from your edits">
        <p className="mb-3 text-slate">
          When you edit a draft, GigBid notes what you changed. A change you make in {m.style_min_support} separate
          edits becomes a preference the writing agents follow. Forgetting one also discards its evidence.
        </p>
        {m.preferences.length === 0 && m.learning.length === 0 && (
          <p>Nothing yet. Edit a draft before approving it and GigBid starts learning.</p>
        )}
        {m.preferences.length > 0 && (
          <ul className="flex flex-col divide-y divide-line">
            {m.preferences.map((p) => (
              <PreferenceRow key={p.key} p={p} onForget={() => forget(p.key)}
                             detail={p.rule ?? `Learned from ${p.edits} edits`} />
            ))}
          </ul>
        )}
        {m.learning.length > 0 && (
          <>
            <h3 className="mb-1 mt-5 font-bold">Still learning</h3>
            <ul className="flex flex-col divide-y divide-line" data-testid="still-learning">
              {m.learning.map((p) => (
                <PreferenceRow key={p.key} p={p} onForget={() => forget(p.key)}
                               detail={`${p.edits} of ${m.style_min_support} edits so far; not used yet`} />
              ))}
            </ul>
          </>
        )}
      </Panel>

      <Panel title="How your proposals did, by skill">
        {m.outcomes.length === 0 ? (
          <p className="text-slate">Outcomes appear after your first submitted proposal.</p>
        ) : (
          <>
            <table className="tnum w-full border-collapse text-left text-[14px]">
              <thead className="text-slate">
                <tr className="border-b border-line">
                  <th scope="col" className="py-2 pr-4 font-normal">Skill</th>
                  <th scope="col" className="py-2 pr-4 text-right font-normal">Proposals</th>
                  <th scope="col" className="py-2 pr-4 text-right font-normal">Replies</th>
                  <th scope="col" className="py-2 pr-4 text-right font-normal">Interviews</th>
                  <th scope="col" className="py-2 pr-4 font-normal">Used by agents</th>
                  <th scope="col" className="py-2"><span className="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody>
                {m.outcomes.map((o) => (
                  <tr key={o.skill} className="border-b border-line">
                    <td className="py-2 pr-4 font-bold">{o.skill}</td>
                    <td className="py-2 pr-4 text-right">{o.submitted}</td>
                    <td className="py-2 pr-4 text-right">
                      {o.replied}{o.reply_rate != null && <span className="text-slate"> ({Math.round(o.reply_rate * 100)}%)</span>}
                    </td>
                    <td className="py-2 pr-4 text-right">{o.interview}</td>
                    <td className="py-2 pr-4">{o.shown_to_agents ? "Yes" : <span className="text-slate">Not yet</span>}</td>
                    <td className="py-2 text-right">
                      <button className="text-risk hover:underline"
                              onClick={() => forgetOutcomes.mutate({ path: { skill: o.skill } })}>
                        Forget
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="mt-2 text-[14px] text-slate">
              The bid decision cites a skill&apos;s reply rate once it has {m.outcomes_min_samples} proposals.
            </p>
          </>
        )}
      </Panel>
    </>
  );
}

function PreferenceRow({ p, detail, onForget }: { p: Preference; detail: string; onForget: () => void }) {
  return (
    <li className="flex flex-wrap items-start justify-between gap-3 py-3">
      <div className="min-w-0 max-w-[60ch]">
        <p className="font-bold">{p.statement}</p>
        <p className="text-[14px] text-slate">{detail}</p>
        <details className="mt-1 text-[14px]">
          <summary className="cursor-pointer text-action">Evidence</summary>
          <ul className="mt-1 list-disc pl-5 text-slate">
            {p.examples.map((e, i) => <li key={i}>{e}</li>)}
          </ul>
        </details>
      </div>
      <button className="text-risk hover:underline" onClick={onForget}>Forget</button>
    </li>
  );
}
