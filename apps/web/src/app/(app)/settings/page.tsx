"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { MemoryPanel } from "@/components/MemoryPanel";
import { button, input, Loading, Notice, PageHeader, Panel } from "@/components/ui";
import {
  authMeOptions,
  authMeQueryKey,
  authUpdateSettingsMutation,
  searchesCreateMutation,
  searchesDeleteMutation,
  searchesListOptions,
  searchesListQueryKey,
} from "@/lib/api/@tanstack/react-query.gen";
import { errorMessage } from "@/lib/labels";

export default function Settings() {
  const me = useQuery(authMeOptions());
  return (
    <>
      <PageHeader title="Settings" />
      <div className="grid max-w-3xl gap-10">
        {me.isPending && <Loading what="your settings" />}
        {me.data && (
          <Panel title="Account">
            <p>{me.data.email}</p>
            <p className="text-slate">Marketplace account {me.data.account} on GigSim. Proposals are only ever sent after you approve them.</p>
          </Panel>
        )}
        {me.data && <RatesForm settings={me.data.settings} />}
        <SavedSearches />
        <MemoryPanel />
      </div>
    </>
  );
}

function RatesForm({ settings }: { settings: { hourly_rate_floor?: number | null; weekly_connects_budget?: number | null } }) {
  const [rate, setRate] = useState(String(settings.hourly_rate_floor ?? ""));
  const [budget, setBudget] = useState(String(settings.weekly_connects_budget ?? ""));
  const queryClient = useQueryClient();
  const save = useMutation({
    ...authUpdateSettingsMutation(),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: authMeQueryKey() }),
  });
  return (
    <Panel title="Rates and budget">
      <form className="flex flex-wrap items-end gap-4"
            onSubmit={(e) => {
              e.preventDefault();
              save.mutate({ body: {
                hourly_rate_floor: rate === "" ? null : Number(rate),
                weekly_connects_budget: budget === "" ? null : Number(budget),
              } });
            }}>
        <label className="flex flex-col gap-1">
          <span>Lowest hourly rate (USD)</span>
          <input className={`${input} tnum w-36`} type="number" min={0} value={rate} onChange={(e) => setRate(e.target.value)} />
        </label>
        <label className="flex flex-col gap-1">
          <span>Weekly Connects budget</span>
          <input className={`${input} tnum w-36`} type="number" min={0} value={budget} onChange={(e) => setBudget(e.target.value)} />
        </label>
        <button className={button.secondary} disabled={save.isPending}>Save rates</button>
        {save.isSuccess && <span role="status" className="text-evidence">Saved</span>}
      </form>
      {save.isError && <div className="mt-3"><Notice>{errorMessage(save.error)}</Notice></div>}
    </Panel>
  );
}

function SavedSearches() {
  const queryClient = useQueryClient();
  const searches = useQuery(searchesListOptions());
  const refresh = () => queryClient.invalidateQueries({ queryKey: searchesListQueryKey() });
  const create = useMutation({ ...searchesCreateMutation(), onSuccess: () => { setSkills(""); setQuery(""); refresh(); } });
  const remove = useMutation({ ...searchesDeleteMutation(), onSuccess: refresh });
  const [skills, setSkills] = useState("");
  const [query, setQuery] = useState("");
  const [every, setEvery] = useState("60");

  return (
    <Panel title="Saved searches">
      <p className="mb-3 text-slate">GigBid runs each search on its schedule and analyzes jobs that are new since the last run.</p>
      {searches.data?.length === 0 && <p className="mb-3">No saved searches yet.</p>}
      <ul className="mb-4 flex flex-col divide-y divide-line">
        {searches.data?.map((s) => (
          <li key={s.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
            <span>
              <strong>{[s.query, ...(s.skills ?? [])].filter(Boolean).join(", ")}</strong>
              <span className="text-slate"> every {s.every_minutes} minutes
                {s.last_run_at ? `, last run ${new Date(s.last_run_at).toLocaleString()}` : ", not run yet"}
                {!s.enabled && ", paused"}</span>
            </span>
            <button className="text-risk hover:underline" onClick={() => remove.mutate({ path: { search_id: s.id } })}>
              Delete
            </button>
          </li>
        ))}
      </ul>
      <form className="flex flex-wrap items-end gap-3"
            onSubmit={(e) => {
              e.preventDefault();
              create.mutate({ body: {
                query, every_minutes: Number(every),
                skills: skills.split(",").map((s) => s.trim()).filter(Boolean),
              } });
            }}>
        <label className="flex grow flex-col gap-1">
          <span>Skills</span>
          <input className={input} placeholder="dbt, Snowflake" value={skills} onChange={(e) => setSkills(e.target.value)} />
        </label>
        <label className="flex grow flex-col gap-1">
          <span>Keywords</span>
          <input className={input} placeholder="dashboard" value={query} onChange={(e) => setQuery(e.target.value)} />
        </label>
        <label className="flex flex-col gap-1">
          <span>Every</span>
          <select className={`${input} w-36`} value={every} onChange={(e) => setEvery(e.target.value)}>
            <option value="15">15 minutes</option>
            <option value="60">hour</option>
            <option value="360">6 hours</option>
            <option value="1440">day</option>
          </select>
        </label>
        <button className={button.secondary} disabled={create.isPending || (!skills.trim() && !query.trim())}>
          Add search
        </button>
      </form>
      {(create.isError || remove.isError) && (
        <div className="mt-3"><Notice>{errorMessage(create.error ?? remove.error)}</Notice></div>
      )}
    </Panel>
  );
}
