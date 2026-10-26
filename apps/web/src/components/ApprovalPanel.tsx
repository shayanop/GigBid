"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { button, input, Notice } from "@/components/ui";
import { approvalsDecideMutation } from "@/lib/api/@tanstack/react-query.gen";
import { errorMessage } from "@/lib/labels";

type Mode = "review" | "edit" | "reject";

/** Approve, edit or reject. Nothing reaches the marketplace without the first button. */
export function ApprovalPanel({ threadId, letter, connectsCost, onEditing }: {
  threadId: string;
  letter: string;
  connectsCost: number;
  onEditing: (editing: boolean) => void;
}) {
  const [mode, setMode] = useState<Mode>("review");
  const [text, setText] = useState(letter);
  const [reason, setReason] = useState("");
  const queryClient = useQueryClient();
  const decide = useMutation({
    ...approvalsDecideMutation(),
    onSuccess: () => {
      switchTo("review");
      queryClient.invalidateQueries();
    },
  });

  function switchTo(next: Mode) {
    setMode(next);
    onEditing(next === "edit");
    if (next === "edit") setText(letter);
  }
  const send = (body: { action: "approve" | "edit" | "reject"; text?: string; reason?: string }) =>
    decide.mutate({ path: { thread_id: threadId }, body });

  return (
    <div className="sticky bottom-0 -mx-4 mt-10 border-t border-line bg-surface/95 px-4 py-4 backdrop-blur">
      {mode === "edit" && (
        <label className="mb-3 flex flex-col gap-1">
          <span className="font-bold">Edit the cover letter</span>
          <textarea className={`${input} min-h-56 font-serif text-[17px] leading-relaxed`} value={text}
                    onChange={(e) => setText(e.target.value)} />
          <span className="text-[14px] text-slate">
            Your edit goes back through the Compliance Guard before you approve it.
          </span>
        </label>
      )}
      {mode === "reject" && (
        <label className="mb-3 flex flex-col gap-1">
          <span className="font-bold">Why are you rejecting it?</span>
          <input className={input} value={reason} required placeholder="Not my niche"
                 onChange={(e) => setReason(e.target.value)} />
          <span className="text-[14px] text-slate">The reason is saved with the job.</span>
        </label>
      )}
      {decide.isError && <div className="mb-3"><Notice>{errorMessage(decide.error)}</Notice></div>}
      <div className="flex flex-wrap gap-3">
        {mode === "review" && (
          <>
            <button className={button.primary} disabled={decide.isPending} onClick={() => send({ action: "approve" })}>
              Approve and submit ({connectsCost} Connects)
            </button>
            <button className={button.secondary} onClick={() => switchTo("edit")}>Edit draft</button>
            <button className={button.danger} onClick={() => switchTo("reject")}>Reject</button>
          </>
        )}
        {mode === "edit" && (
          <>
            <button className={button.primary} disabled={decide.isPending || !text.trim() || text === letter}
                    onClick={() => send({ action: "edit", text })}>
              Save edit
            </button>
            <button className={button.secondary} onClick={() => switchTo("review")}>Cancel</button>
          </>
        )}
        {mode === "reject" && (
          <>
            <button className={button.danger} disabled={decide.isPending || !reason.trim()}
                    onClick={() => send({ action: "reject", reason: reason.trim() })}>
              Reject proposal
            </button>
            <button className={button.secondary} onClick={() => switchTo("review")}>Cancel</button>
          </>
        )}
      </div>
    </div>
  );
}
