"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { button, input, Notice } from "@/components/ui";
import { approvalsDecideMutation, messagesDecideMutation } from "@/lib/api/@tanstack/react-query.gen";
import { errorMessage } from "@/lib/labels";

type Mode = "review" | "edit" | "reject";
type Decision = { action: "approve" | "edit" | "reject"; text?: string; reason?: string; answers?: string[] };
type Answer = { question: string; answer: string };

const COPY = {
  proposal: { edit: "Edit the cover letter", editButton: "Edit draft" },
  message: { edit: "Edit the reply", editButton: "Edit reply" },
};

/** Approve, edit or reject. Nothing reaches the marketplace without the first button. */
export function ApprovalPanel({ kind, threadId, text, answers = [], approveLabel, onEditing }: {
  kind: "proposal" | "message";
  threadId: string;
  text: string;
  answers?: Answer[];
  approveLabel: string;
  onEditing: (editing: boolean) => void;
}) {
  const [mode, setMode] = useState<Mode>("review");
  const [edited, setEdited] = useState(text);
  const [editedAnswers, setEditedAnswers] = useState(answers.map((a) => a.answer));
  const answersChanged = editedAnswers.some((a, i) => a !== answers[i]?.answer);
  const [reason, setReason] = useState("");
  const queryClient = useQueryClient();
  const onSuccess = () => {
    switchTo("review");
    queryClient.invalidateQueries();
  };
  const proposal = useMutation({ ...approvalsDecideMutation(), onSuccess });
  const message = useMutation({ ...messagesDecideMutation(), onSuccess });
  const decide = kind === "proposal" ? proposal : message;

  function switchTo(next: Mode) {
    setMode(next);
    onEditing(next === "edit");
    if (next === "edit") {
      setEdited(text);
      setEditedAnswers(answers.map((a) => a.answer));
    }
  }
  const send = (body: Decision) =>
    kind === "proposal"
      ? proposal.mutate({ path: { thread_id: threadId }, body })
      : message.mutate({ path: { conversation_id: threadId }, body });

  return (
    <div className="sticky bottom-0 -mx-4 mt-10 border-t border-line bg-surface/95 px-4 py-4 backdrop-blur">
      {mode === "edit" && (
        <label className="mb-3 flex flex-col gap-1">
          <span className="font-bold">{COPY[kind].edit}</span>
          <textarea className={`${input} min-h-56 font-serif text-[17px] leading-relaxed`} value={edited}
                    onChange={(e) => setEdited(e.target.value)} />
          <span className="text-[14px] text-slate">
            Your edit goes back through the Compliance Guard before you approve it.
          </span>
        </label>
      )}
      {mode === "edit" && answers.map((a, i) => (
        <label key={a.question} className="mb-3 flex flex-col gap-1">
          <span className="font-bold">{a.question}</span>
          <textarea className={`${input} min-h-20`} value={editedAnswers[i]}
                    onChange={(e) => setEditedAnswers(editedAnswers.map((v, j) => (j === i ? e.target.value : v)))} />
        </label>
      ))}
      {mode === "reject" && (
        <label className="mb-3 flex flex-col gap-1">
          <span className="font-bold">Why are you rejecting it?</span>
          <input className={input} value={reason} required placeholder="I will answer this myself"
                 onChange={(e) => setReason(e.target.value)} />
          <span className="text-[14px] text-slate">The reason is saved with the {kind}.</span>
        </label>
      )}
      {decide.isError && <div className="mb-3"><Notice>{errorMessage(decide.error)}</Notice></div>}
      <div className="flex flex-wrap gap-3">
        {mode === "review" && (
          <>
            <button className={button.primary} disabled={decide.isPending} onClick={() => send({ action: "approve" })}>
              {approveLabel}
            </button>
            <button className={button.secondary} onClick={() => switchTo("edit")}>{COPY[kind].editButton}</button>
            <button className={button.danger} onClick={() => switchTo("reject")}>Reject</button>
          </>
        )}
        {mode === "edit" && (
          <>
            <button className={button.primary} disabled={decide.isPending || !edited.trim() || (edited === text && !answersChanged)}
                    onClick={() => send({ action: "edit", text: edited, ...(answers.length ? { answers: editedAnswers } : {}) })}>
              Save edit
            </button>
            <button className={button.secondary} onClick={() => switchTo("review")}>Cancel</button>
          </>
        )}
        {mode === "reject" && (
          <>
            <button className={button.danger} disabled={decide.isPending || !reason.trim()}
                    onClick={() => send({ action: "reject", reason: reason.trim() })}>
              Reject {kind}
            </button>
            <button className={button.secondary} onClick={() => switchTo("review")}>Cancel</button>
          </>
        )}
      </div>
    </div>
  );
}
