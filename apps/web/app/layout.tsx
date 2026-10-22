import type { Metadata } from "next";
import { Geist_Mono, Public_Sans } from "next/font/google";

import { AppHeader } from "@/components/shell/app-header";
import { ClockProvider } from "@/components/shell/clock-provider";
import { PersonaProvider } from "@/components/shell/persona-provider";
import { SideNav } from "@/components/shell/side-nav";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";

import "./globals.css";

const sans = Public_Sans({
  variable: "--font-sans",
  subsets: ["latin", "latin-ext", "vietnamese"],
});

const mono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
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
    <html lang="en" className={`${sans.variable} ${mono.variable} h-full antialiased`}>
      <body className="min-h-full">
        <TooltipProvider delayDuration={150}>
          <PersonaProvider>
            <ClockProvider>
              <div className="grid min-h-dvh grid-cols-[15rem_minmax(0,1fr)] grid-rows-[auto_1fr]">
                <AppHeader />
                <aside className="sticky top-16 h-[calc(100dvh-4rem)] overflow-y-auto border-r bg-sidebar">
                  <SideNav />
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
          <Toaster position="bottom-right" />
        </TooltipProvider>
      </body>
    </html>
  );
}
