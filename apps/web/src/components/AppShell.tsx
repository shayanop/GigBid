"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

import { authLogoutMutation, authMeOptions, marketplaceStatusOptions } from "@/lib/api/@tanstack/react-query.gen";

const NAV = [
  { href: "/inbox", label: "Inbox" },
  { href: "/pipeline", label: "Pipeline" },
  { href: "/settings", label: "Settings" },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const me = useQuery(authMeOptions());
  const market = useQuery({ ...marketplaceStatusOptions(), refetchInterval: 30_000 });
  const router = useRouter();
  const queryClient = useQueryClient();
  const logout = useMutation({
    ...authLogoutMutation(),
    onSuccess: () => {
      queryClient.clear(); // no data from this account survives sign-out
      router.push("/signin");
    },
  });
  const degraded = market.data?.available === false;

  return (
    <div className="min-h-dvh">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-2 focus:z-10 focus:bg-surface focus:px-3 focus:py-1">
        Skip to content
      </a>
      <header className="border-b border-line bg-surface">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-8 gap-y-2 px-4 py-3">
          <Link href="/inbox" className="text-xl font-extrabold tracking-[-0.02em]">
            GigBid
          </Link>
          <nav aria-label="Main" className="flex gap-1">
            {NAV.map((item) => {
              const current = path.startsWith(item.href);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  aria-current={current ? "page" : undefined}
                  className={`rounded-sm px-3 py-1.5 ${current ? "bg-paper font-bold" : "text-slate hover:text-ink"}`}
                >
                  {item.label}
                </Link>
              );
            })}
          </nav>
          <div className="ml-auto flex items-center gap-4 text-[14px]">
            {market.data?.connects != null && (
              <span className="tnum" title="Connects available on the marketplace">
                <strong>{market.data.connects}</strong> Connects
              </span>
            )}
            {me.data && <span className="hidden text-slate sm:inline">{me.data.email}</span>}
            <button type="button" className="text-slate hover:text-ink" onClick={() => logout.mutate({})}>
              Sign out
            </button>
          </div>
        </div>
      </header>
      {degraded && (
        <div role="status" data-testid="degraded-banner" className="bg-caution-soft text-caution">
          <p className="mx-auto max-w-6xl px-4 py-2">
            <strong>Marketplace unavailable.</strong> Analyses and approved proposals wait in the queue
            and continue when it is back. Nothing is lost.
          </p>
        </div>
      )}
      <main id="main" className="mx-auto max-w-6xl px-4 py-8">
        {children}
      </main>
    </div>
  );
}
