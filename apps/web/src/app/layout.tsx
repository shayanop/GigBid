import type { Metadata } from "next";
import { Atkinson_Hyperlegible_Next, Source_Serif_4 } from "next/font/google";

import { Providers } from "./providers";
import "./globals.css";

// Next has no metric overrides for this font, so it cannot build an adjusted fallback.
const sans = Atkinson_Hyperlegible_Next({ subsets: ["latin"], variable: "--font-atkinson", adjustFontFallback: false });
const serif = Source_Serif_4({ subsets: ["latin"], variable: "--font-source-serif" });

export const metadata: Metadata = {
  title: "GigBid",
  description: "Find, judge and answer freelance jobs with evidence, and approve every send.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${sans.variable} ${serif.variable} antialiased`}>
      <body className="min-h-dvh">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
