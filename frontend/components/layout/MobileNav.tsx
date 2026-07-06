"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { ThemeToggle } from "./ThemeToggle";
import { navigationItems } from "./Sidebar";

export function MobileNav() {
  const [isOpen, setIsOpen] = useState(false);
  const pathname = usePathname();

  // Close menu on route change
  useEffect(() => {
    setIsOpen(false);
  }, [pathname]);

  // Prevent body scroll when menu is open
  useEffect(() => {
    if (isOpen) {
      document.body.style.overflow = "hidden";
    } else {
      document.body.style.overflow = "";
    }
    return () => {
      document.body.style.overflow = "";
    };
  }, [isOpen]);

  // Close on Escape key
  const handleKeyDown = useCallback((e: KeyboardEvent) => {
    if (e.key === "Escape") {
      setIsOpen(false);
    }
  }, []);

  useEffect(() => {
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [handleKeyDown]);

  return (
    <div className="tablet:hidden">
      {/* Mobile header bar */}
      <header className="fixed top-0 left-0 right-0 z-40 flex h-14 items-center justify-between
                         border-b border-[rgb(var(--border))]
                         bg-[rgb(var(--background))] px-4">
        {/* Hamburger button - 44x44 touch target */}
        <button
          onClick={() => setIsOpen(!isOpen)}
          className="flex h-11 w-11 items-center justify-center rounded-lg
                     text-[rgb(var(--foreground))] transition-colors
                     hover:bg-[rgb(var(--muted))]
                     focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[rgb(var(--accent))]"
          aria-expanded={isOpen}
          aria-controls="mobile-nav-menu"
          aria-label={isOpen ? "Close menu" : "Open menu"}
        >
          {isOpen ? (
            <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          ) : (
            <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25h16.5" />
            </svg>
          )}
        </button>

        {/* Brand */}
        <span className="text-base font-semibold text-[rgb(var(--foreground))]">
          GKIM Finder
        </span>

        {/* Theme toggle */}
        <ThemeToggle />
      </header>

      {/* Overlay */}
      {isOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/50 backdrop-blur-sm"
          onClick={() => setIsOpen(false)}
          aria-hidden="true"
        />
      )}

      {/* Slide-out menu */}
      <nav
        id="mobile-nav-menu"
        className={`fixed top-14 left-0 bottom-0 z-50 w-72 transform
                    border-r border-[rgb(var(--border))]
                    bg-[rgb(var(--background))] transition-transform duration-200 ease-in-out
                    ${isOpen ? "translate-x-0" : "-translate-x-full"}`}
        aria-label="Mobile navigation"
        role="navigation"
      >
        <ul className="space-y-1 px-3 py-4" role="list">
          {navigationItems.map((item) => {
            const isActive = pathname === item.href || pathname.startsWith(`${item.href}/`);
            return (
              <li key={item.id}>
                <Link
                  href={item.href}
                  className={`sidebar-link min-h-[44px] ${isActive ? "sidebar-link-active" : ""}`}
                  aria-current={isActive ? "page" : undefined}
                >
                  {item.icon}
                  <span>{item.label}</span>
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>
    </div>
  );
}
