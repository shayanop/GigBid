"use client";

import { useId, useState } from "react";

export type EvidenceItem = { id: string; type: string; source: string; text: string };

const TYPE: Record<string, string> = {
  case_study: "Case study",
  code: "Code",
  repo_readme: "Repository",
  review: "Client review",
  proposal: "Past proposal",
  cv: "CV",
};

/** An evidence id that reveals its source text on hover or keyboard focus. */
export function EvidenceHover({ evidence }: { evidence?: EvidenceItem }) {
  const [open, setOpen] = useState(false);
  const tipId = useId();
  if (!evidence) return null;
  return (
    <span className="relative inline-block" onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)}>
      <button type="button" aria-describedby={open ? tipId : undefined}
              onFocus={() => setOpen(true)} onBlur={() => setOpen(false)}
              onKeyDown={(e) => e.key === "Escape" && setOpen(false)}
              className="rounded-sm bg-evidence-soft px-1.5 py-px text-[13px] text-evidence">
        {TYPE[evidence.type] ?? evidence.type}: {evidence.id.split("#")[0]}
      </button>
      {open && (
        <span role="tooltip" id={tipId}
              className="absolute left-0 top-full z-20 mt-1 block w-80 max-w-[80vw] rounded-sm border border-line bg-surface p-3 text-left text-[14px] shadow-[0_6px_20px_-8px_rgb(24_34_45/0.35)]">
          <span className="block text-[13px] text-slate">{evidence.source}</span>
          <span className="mt-1 block max-h-48 overflow-auto whitespace-pre-wrap">{evidence.text.trim()}</span>
        </span>
      )}
    </span>
  );
}
