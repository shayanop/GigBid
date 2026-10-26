import { Suspense } from "react";

import { AppShell } from "@/components/AppShell";

// The shell reads the URL (active nav item, route params), which only exists at request
// time; Cache Components needs that behind a Suspense boundary.
export default function AppLayout({ children }: LayoutProps<"/">) {
  return (
    <Suspense fallback={<p className="px-4 py-8 text-slate">Loading…</p>}>
      <AppShell>{children}</AppShell>
    </Suspense>
  );
}
