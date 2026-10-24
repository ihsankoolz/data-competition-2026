import type { Metadata } from "next";
import { IBM_Plex_Mono, Plus_Jakarta_Sans } from "next/font/google";

import { AppHeader } from "@/components/shell/app-header";
import { ClockProvider } from "@/components/shell/clock-provider";
import { PersonaProvider } from "@/components/shell/persona-provider";
import { SideNav } from "@/components/shell/side-nav";
import { ToastRouteGuard } from "@/components/shell/toast-route-guard";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { THEME_PREVIEW_SCRIPT, THEME_VARIANT } from "@/lib/theme";
import { TOAST_DURATION_MS } from "@/lib/toasts";

import "./globals.css";

// Sage theme type pair (D-021): Plus Jakarta Sans for UI text, IBM Plex Mono for codes and IDs.
// Both ship Vietnamese glyphs (hospital names such as "Chợ Rẫy").
const sans = Plus_Jakarta_Sans({
  variable: "--font-sans",
  subsets: ["latin", "latin-ext", "vietnamese"],
});

const mono = IBM_Plex_Mono({
  variable: "--font-mono",
  weight: ["400", "500", "600"],
  subsets: ["latin", "latin-ext", "vietnamese"],
});

export const metadata: Metadata = {
  title: {
    template: "%s | Lives Group Master Data",
    default: "Lives Group Master Data",
  },
  description:
    "Messy requests and emails in, one clean customer and product record out, published to SAP Business One.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    // The variant comes from one constant (lib/theme.ts). suppressHydrationWarning: the preview
    // script may change these two attributes before React hydrates.
    <html
      lang="en"
      data-variant={THEME_VARIANT}
      className={`${sans.variable} ${mono.variable} h-full antialiased`}
      suppressHydrationWarning
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_PREVIEW_SCRIPT }} />
      </head>
      <body className="min-h-full">
        <TooltipProvider delayDuration={150}>
          <PersonaProvider>
            <ClockProvider>
              <div className="grid min-h-dvh grid-cols-[15rem_minmax(0,1fr)] grid-rows-[auto_1fr]">
                <AppHeader />
                {/* The column runs the full page height; the nav inside it stays in view. */}
                <aside className="border-r bg-sidebar" data-testid="sidebar">
                  <div className="sticky top-16 max-h-[calc(100dvh-4rem)] overflow-y-auto">
                    <SideNav />
                  </div>
                </aside>
                <div className="flex min-w-0 flex-col">
                  <main className="flex-1 px-10 py-8">{children}</main>
                  <footer className="border-t px-10 py-4 text-xs text-muted-foreground">
                    All data is synthetic. Hospital names are real for realism; all IDs,
                    transactions, contacts and amounts are fictional.
                  </footer>
                </div>
              </div>
            </ClockProvider>
          </PersonaProvider>
          {/* Bottom-left, inside the sidebar column (15rem wide, empty below the nav): a toast
              never covers page content such as the revenue bridge or a request's history, nor
              the notifications bell. About 3 s each, cleared on page change (D-022 #5). */}
          <Toaster
            position="bottom-left"
            visibleToasts={3}
            duration={TOAST_DURATION_MS}
            offset={{ left: 12, bottom: 16 }}
            width="calc(15rem - 24px)"
          />
          <ToastRouteGuard />
        </TooltipProvider>
      </body>
    </html>
  );
}
