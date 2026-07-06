import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { ThemeProvider } from "@/components/providers/ThemeProvider";
import { WebSocketProvider } from "@/components/providers/WebSocketProvider";
import { Sidebar } from "@/components/layout/Sidebar";
import { MobileNav } from "@/components/layout/MobileNav";
import { ConnectionStatus } from "@/components/layout/ConnectionStatus";
import { themeInitScript } from "@/lib/theme";

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "GKIM Opportunity Finder v2",
  description: "Schema-driven opportunity discovery, scoring, and outreach platform",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        {/* Inline theme init to prevent flash of wrong theme */}
        <script dangerouslySetInnerHTML={{ __html: themeInitScript }} />
      </head>
      <body className={inter.className}>
        <ThemeProvider>
          <WebSocketProvider>
            {/* Skip to content link — WCAG 2.1 AA (Req 16.4) */}
            <a href="#main-content" className="skip-to-content">
              Skip to main content
            </a>

            <div className="flex min-h-screen">
              {/* Desktop/Tablet sidebar */}
              <Sidebar />

              {/* Mobile navigation */}
              <MobileNav />

              {/* Main content area */}
              <main
                id="main-content"
                className="flex-1 pt-14 tablet:pt-0"
                role="main"
                tabIndex={-1}
              >
                {/* Connection status indicator — aria-live for real-time updates */}
                <div className="fixed bottom-4 right-4 z-50">
                  <ConnectionStatus />
                </div>
                <div className="mx-auto max-w-7xl px-4 py-6 tablet:px-6 desktop:px-8">
                  {children}
                </div>
              </main>
            </div>
          </WebSocketProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
