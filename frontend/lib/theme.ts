"use client";

export type Theme = "light" | "dark";

const STORAGE_KEY = "gkim-theme-preference";

/**
 * Get the user's theme preference.
 * Priority: localStorage > OS preference > light
 */
export function getThemePreference(): Theme {
  if (typeof window === "undefined") return "light";

  // Check localStorage first
  const stored = localStorage.getItem(STORAGE_KEY);
  if (stored === "light" || stored === "dark") {
    return stored;
  }

  // Fall back to OS preference
  if (window.matchMedia("(prefers-color-scheme: dark)").matches) {
    return "dark";
  }

  return "light";
}

/**
 * Persist theme preference to localStorage.
 */
export function setThemePreference(theme: Theme): void {
  if (typeof window === "undefined") return;
  localStorage.setItem(STORAGE_KEY, theme);
}

/**
 * Apply the theme to the document root element.
 */
export function applyTheme(theme: Theme): void {
  if (typeof document === "undefined") return;

  const root = document.documentElement;
  if (theme === "dark") {
    root.classList.add("dark");
  } else {
    root.classList.remove("dark");
  }
}

/**
 * Initialize theme on page load — prevents flash of wrong theme.
 * This script should be inlined in <head> for immediate execution.
 */
export const themeInitScript = `
  (function() {
    var stored = localStorage.getItem('${STORAGE_KEY}');
    var theme = stored || (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    if (theme === 'dark') {
      document.documentElement.classList.add('dark');
    }
  })();
`;
