"use client";

import { useMutation } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { button, input, Notice, TextLink } from "@/components/ui";
import { authLoginMutation } from "@/lib/api/@tanstack/react-query.gen";
import { errorMessage } from "@/lib/labels";

export default function SignIn() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const router = useRouter();
  const login = useMutation({ ...authLoginMutation(), onSuccess: () => router.push("/inbox") });

  return (
    <main className="mx-auto flex min-h-dvh max-w-sm flex-col justify-center px-4 py-12">
      <p className="text-xl font-extrabold tracking-[-0.02em]">GigBid</p>
      <h1 className="mt-6 text-[28px] font-extrabold leading-tight">Sign in</h1>
      <p className="mt-2 text-slate">Your agents find jobs and draft proposals. Nothing is sent until you approve it.</p>
      <form
        className="mt-8 flex flex-col gap-4"
        onSubmit={(e) => {
          e.preventDefault();
          login.mutate({ body: { email, password } });
        }}
      >
        <label className="flex flex-col gap-1">
          <span className="font-bold">Email</span>
          <input className={input} type="email" autoComplete="email" required value={email}
                 onChange={(e) => setEmail(e.target.value)} />
        </label>
        <label className="flex flex-col gap-1">
          <span className="font-bold">Password</span>
          <input className={input} type="password" autoComplete="current-password" required value={password}
                 onChange={(e) => setPassword(e.target.value)} />
        </label>
        {login.isError && <Notice>{errorMessage(login.error, "Could not sign in.")}</Notice>}
        <button className={button.primary} disabled={login.isPending}>
          {login.isPending ? "Signing in…" : "Sign in"}
        </button>
      </form>
      <p className="mt-6 text-slate">
        New here? <TextLink href="/onboarding">Create an account</TextLink>
      </p>
    </main>
  );
}
