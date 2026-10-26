// Plain-language names for what the backend calls statuses, flags and graph nodes.

export const STATUS: Record<string, { label: string; tone: Tone }> = {
  queued: { label: "Queued", tone: "quiet" },
  analyzing: { label: "Analyzing", tone: "quiet" },
  drafting: { label: "Drafting", tone: "quiet" },
  processing: { label: "Sending", tone: "quiet" },
  awaiting_approval: { label: "Needs your approval", tone: "action" },
  watching: { label: "Watching", tone: "caution" },
  skipped: { label: "Skipped", tone: "muted" },
  submitted: { label: "Submitted", tone: "evidence" },
  rejected: { label: "Rejected by you", tone: "muted" },
  needs_attention: { label: "Needs attention", tone: "risk" },
  sent: { label: "Sent", tone: "evidence" },
  idle: { label: "Nothing to answer", tone: "muted" },
};

export const INTENT: Record<string, string> = {
  question: "Question",
  negotiation: "Negotiation",
  interview: "Interview request",
  scam_signal: "Possible scam",
  other: "Other",
};

export type Tone = "quiet" | "action" | "caution" | "muted" | "evidence" | "risk";

export const LIVE_STATUSES = new Set(["queued", "analyzing", "drafting", "processing"]);

const DATE_TIME = { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" } as const;

/** In the viewer's time zone. */
export const when = (iso: string) => new Date(iso).toLocaleString("en-GB", DATE_TIME);

/** In UTC, matching the times written into replies to clients. */
export const whenUtc = (iso: string) => new Date(iso).toLocaleString("en-GB", { ...DATE_TIME, timeZone: "UTC" });

const FLAGS: Record<string, string> = {
  off_platform_contact: "Off-platform contact",
  off_platform_payment: "Off-platform payment",
  free_work: "Free work",
  sensitive_data: "Asks for personal data",
  prompt_injection: "Hidden instructions",
  unverified_client: "Unverified payment",
  no_spend_history: "No hiring history",
};

export const flagLabel = (flag: string) => FLAGS[flag] ?? flag.replaceAll("_", " ");

export const NODE: Record<string, string> = {
  scout: "Load job",
  analyst: "Job Analyst",
  risk: "Risk Assessor",
  matcher: "Fit Matcher",
  decide: "Bid decision",
  pricing: "Pricing Strategist",
  writer: "Proposal Writer",
  verifier: "Claim Verifier",
  critic: "Critic",
  compliance: "Compliance Guard",
  approval: "Your approval",
  submit: "Submit to marketplace",
  read: "Read the conversation",
  classify: "Classify the message",
  slots: "Find interview times",
  liaison: "Client Liaison",
  check: "Compliance Guard",
  send: "Send and hold times",
};

export const SUPPORT: Record<string, string> = {
  supported: "Supported",
  partly_supported: "Partly supported",
  unsupported: "Removed: no evidence",
};

export const percent = (score?: number | null) =>
  score === null || score === undefined ? "–" : `${Math.round(score * 100)}`;

export const usd = (amount?: number | null) =>
  amount === null || amount === undefined
    ? "–"
    : amount.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });

export function errorMessage(error: unknown, fallback = "Something went wrong. Try again.") {
  const detail = (error as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail[0]?.msg) return String(detail[0].msg);
  return fallback;
}
