"use client";

import { useMutation } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { button, input, Notice } from "@/components/ui";
import {
  authSignupMutation,
  authUpdateSettingsMutation,
  searchesCreateMutation,
} from "@/lib/api/@tanstack/react-query.gen";
import { errorMessage } from "@/lib/labels";

// GigSim accounts; live mode replaces this with the marketplace's own sign-in.
const ACCOUNTS = [
  { id: "fr_ml", label: "AI/ML engineer", who: "Sana Iqbal" },
  { id: "fr_fs", label: "Full-stack developer", who: "Daniel Okafor" },
  { id: "fr_da", label: "Data analyst", who: "Mei Lin" },
];
const STEPS = ["Account", "Rates and budget", "First saved search"];

export default function Onboarding() {
  const [step, setStep] = useState(0);
  const router = useRouter();
  return (
    <main className="mx-auto min-h-dvh max-w-xl px-4 py-12">
      <p className="text-xl font-extrabold tracking-[-0.02em]">GigBid</p>
      <ol className="mt-8 flex flex-wrap gap-x-6 gap-y-1 text-[14px]" aria-label="Setup steps">
        {STEPS.map((name, i) => (
          <li key={name} aria-current={i === step ? "step" : undefined}
              className={i === step ? "font-bold" : "text-slate"}>
            {i + 1}. {name}
          </li>
        ))}
      </ol>
      {step === 0 && <AccountStep onDone={() => setStep(1)} />}
      {step === 1 && <RatesStep onDone={() => setStep(2)} />}
      {step === 2 && <SearchStep onDone={() => router.push("/inbox")} />}
    </main>
  );
}

function AccountStep({ onDone }: { onDone: () => void }) {
  const [form, setForm] = useState({ email: "", password: "", account: "fr_ml" });
  const signup = useMutation({ ...authSignupMutation(), onSuccess: onDone });
  return (
    <form className="mt-6 flex flex-col gap-4"
          onSubmit={(e) => { e.preventDefault(); signup.mutate({ body: form }); }}>
      <h1 className="text-[28px] font-extrabold leading-tight">Create your account</h1>
      <label className="flex flex-col gap-1">
        <span className="font-bold">Email</span>
        <input className={input} type="email" autoComplete="email" required value={form.email}
               onChange={(e) => setForm({ ...form, email: e.target.value })} />
      </label>
      <label className="flex flex-col gap-1">
        <span className="font-bold">Password</span>
        <input className={input} type="password" autoComplete="new-password" required minLength={12}
               value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
        <span className="text-[14px] text-slate">At least 12 characters.</span>
      </label>
      <fieldset className="flex flex-col gap-2">
        <legend className="mb-1 font-bold">Marketplace account</legend>
        {ACCOUNTS.map((a) => (
          <label key={a.id} className="flex items-center gap-3 rounded-sm border border-line bg-surface px-3 py-2 has-checked:border-action">
            <input type="radio" name="account" value={a.id} checked={form.account === a.id}
                   onChange={() => setForm({ ...form, account: a.id })} />
            <span><strong>{a.label}</strong> <span className="text-slate">({a.who}, GigSim)</span></span>
          </label>
        ))}
      </fieldset>
      {signup.isError && <Notice>{errorMessage(signup.error, "Could not create the account.")}</Notice>}
      <button className={button.primary} disabled={signup.isPending}>Create account</button>
    </form>
  );
}

function RatesStep({ onDone }: { onDone: () => void }) {
  const [rate, setRate] = useState("40");
  const [budget, setBudget] = useState("80");
  const save = useMutation({ ...authUpdateSettingsMutation(), onSuccess: onDone });
  return (
    <form className="mt-6 flex flex-col gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate({ body: { hourly_rate_floor: Number(rate), weekly_connects_budget: Number(budget) } });
          }}>
      <h1 className="text-[28px] font-extrabold leading-tight">Rates and budget</h1>
      <label className="flex flex-col gap-1">
        <span className="font-bold">Lowest hourly rate you accept (USD)</span>
        <input className={`${input} tnum max-w-40`} type="number" min={0} required value={rate}
               onChange={(e) => setRate(e.target.value)} />
      </label>
      <label className="flex flex-col gap-1">
        <span className="font-bold">Connects you will spend per week</span>
        <input className={`${input} tnum max-w-40`} type="number" min={0} required value={budget}
               onChange={(e) => setBudget(e.target.value)} />
        <span className="text-[14px] text-slate">GigBid refuses approvals that would go over this.</span>
      </label>
      {save.isError && <Notice>{errorMessage(save.error)}</Notice>}
      <button className={button.primary} disabled={save.isPending}>Save and continue</button>
    </form>
  );
}

function SearchStep({ onDone }: { onDone: () => void }) {
  const [skills, setSkills] = useState("");
  const [query, setQuery] = useState("");
  const create = useMutation({ ...searchesCreateMutation(), onSuccess: onDone });
  return (
    <form className="mt-6 flex flex-col gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            const list = skills.split(",").map((s) => s.trim()).filter(Boolean);
            create.mutate({ body: { query, skills: list, every_minutes: 60 } });
          }}>
      <h1 className="text-[28px] font-extrabold leading-tight">What should GigBid look for?</h1>
      <p className="text-slate">GigBid checks this search every hour and analyzes new jobs that match.</p>
      <label className="flex flex-col gap-1">
        <span className="font-bold">Skills, separated by commas</span>
        <input className={input} placeholder="LangGraph, RAG" value={skills}
               onChange={(e) => setSkills(e.target.value)} />
      </label>
      <label className="flex flex-col gap-1">
        <span className="font-bold">Keywords (optional)</span>
        <input className={input} placeholder="chatbot" value={query} onChange={(e) => setQuery(e.target.value)} />
      </label>
      {create.isError && <Notice>{errorMessage(create.error)}</Notice>}
      <div className="flex flex-wrap gap-3">
        <button className={button.primary} disabled={create.isPending || (!skills.trim() && !query.trim())}>
          Save search and finish
        </button>
        <button type="button" className={button.secondary} onClick={onDone}>Skip for now</button>
      </div>
    </form>
  );
}
