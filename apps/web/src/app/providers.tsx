"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";

import { client } from "@/lib/api/client.gen";

// Every call goes through the same-origin /api proxy, so the session cookie just works.
client.setConfig({ baseUrl: "/api" });

const PUBLIC_PATHS = ["/signin", "/onboarding"];

client.interceptors.response.use((response) => {
  const onPublicPage = PUBLIC_PATHS.some((p) => window.location.pathname.startsWith(p));
  if (response.status === 401 && !onPublicPage) {
    // Outside React, so no router; a full load also drops any cached data.
    // eslint-disable-next-line @next/next/no-location-assign-relative-destination
    window.location.assign("/signin");
  }
  return response;
});

export function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(
    () => new QueryClient({ defaultOptions: { queries: { retry: 1, staleTime: 2_000 } } }),
  );
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}
