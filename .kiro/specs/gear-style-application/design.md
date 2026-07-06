# Design Document

## Overview

Apply the GEAR App Style Guide globally to the GKIM Opportunity Finder v2 Next.js frontend. This covers design token establishment (colors, typography, spacing), skip-to-content accessibility link relocation, hard-edge button reset, section color pattern classes, logo asset placement, and sidebar branding update.

## Architecture

This feature applies the GEAR App Style Guide globally to the existing Next.js 14+ App Router frontend. The changes span four layers:

1. **CSS Token Layer** — New `:root` custom properties in `globals.css` defining GEAR colors, spacing base, and section pattern classes.
2. **Tailwind Extension Layer** — `tailwind.config.ts` extended with GEAR colors, fonts, and spacing scale so utility classes map to tokens.
3. **Font Loading Layer** — `next/font/google` used for Figtree and Instrument Serif; League Gothic loaded via a Google Fonts `<link>` in `layout.tsx` `<head>` (League Gothic is available on Google Fonts).
4. **Component Layer** — Skip-to-content link repositioned via CSS; Sidebar branding replaced with the GEARS™ logo `<Image>` element.

Static logo assets are placed in `frontend/public/images/logos/` and served at `/images/logos/*`.

---

## Components and Interfaces

### 1. Skip-to-Content Link (layout.tsx + globals.css)

**Current state:** The `.skip-to-content` class uses `absolute left-4 top-4` positioning with a `-translate-y-full` hide / `focus:translate-y-0` reveal.

**Target state:** Fixed bottom-left, hidden via `translate-y-full` (push below viewport), revealed on `:focus-visible` with `translate-y-0`.

```css
/* globals.css — updated .skip-to-content */
.skip-to-content {
  @apply fixed left-4 bottom-4 z-[100] translate-y-[200%]
         bg-[var(--bg-accent)] px-4 py-2 text-sm font-semibold
         text-[var(--text-on-light)] transition-transform
         focus-visible:translate-y-0;
}
```

Key changes:
- `absolute` → `fixed` (viewport-anchored, survives scroll)
- `top-4` → `bottom-4`
- `-translate-y-full` → `translate-y-[200%]` (pushes below viewport edge)
- `:focus` → `:focus-visible` (only keyboard navigation triggers visibility)
- Colors switch to GEAR tokens

The `<a>` element in `layout.tsx` remains unchanged (same href, same text).

---

### 2. GEAR Design Tokens — globals.css

New `:root` block added **above** the existing light/dark theme variables (which remain for backward compatibility until full migration):

```css
:root {
  /* GEAR Colors */
  --bg-dark: #0A0A09;
  --bg-light: #F2F2F2;
  --bg-accent: #FFDD00;
  --surface-white: #FFFFFF;
  --surface-dark: #202020;
  --text-on-dark: #FFFFFF;
  --text-on-dark-muted: #D6D6D6;
  --text-on-light: #202020;
  --text-on-light-muted: #5C5C5C;
  --border-on-dark: #5C5C5C;
  --border-on-light: #D6D6D6;
  --border-strong: #333533;

  /* GEAR Spacing */
  --spacing-base: 4px;

  /* GEAR Layout */
  --container-max: 1120px;
}
```

---

### 3. Section Color Pattern Utility Classes — globals.css

Defined in the `@layer components` section:

```css
@layer components {
  .section-dark {
    background-color: var(--bg-dark);
    color: var(--text-on-dark);
  }

  .section-light {
    background-color: var(--surface-white);
    color: var(--text-on-light);
  }

  .section-warm {
    background-color: var(--bg-accent);
    color: var(--text-on-light);
  }
}
```

Each class sets both `background-color` and `color` so a developer only needs one class to establish the section's color context.

---

### 4. Hard-Edge Button Reset — globals.css

Added inside `@layer base`:

```css
button,
[role="button"] {
  border-radius: 0;
}
```

This global reset ensures every button element renders with square corners regardless of component library or Tailwind utility applied later (utilities can still override if needed, but the base is 0).

---

### 5. Tailwind Config Extensions — tailwind.config.ts

```typescript
import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./lib/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  darkMode: "class",
  theme: {
    extend: {
      screens: {
        mobile: "320px",
        tablet: "768px",
        desktop: "1200px",
      },
      colors: {
        gear: {
          dark: "var(--bg-dark)",
          light: "var(--bg-light)",
          accent: "var(--bg-accent)",
          "surface-white": "var(--surface-white)",
          "surface-dark": "var(--surface-dark)",
          "text-dark": "var(--text-on-dark)",
          "text-dark-muted": "var(--text-on-dark-muted)",
          "text-light": "var(--text-on-light)",
          "text-light-muted": "var(--text-on-light-muted)",
          "border-dark": "var(--border-on-dark)",
          "border-light": "var(--border-on-light)",
          "border-strong": "var(--border-strong)",
        },
        brand: {
          50: "#eff6ff",
          100: "#dbeafe",
          200: "#bfdbfe",
          300: "#93c5fd",
          400: "#60a5fa",
          500: "#3b82f6",
          600: "#2563eb",
          700: "#1d4ed8",
          800: "#1e40af",
          900: "#1e3a8a",
        },
      },
      fontFamily: {
        display: ['"League Gothic"', "sans-serif"],
        body: ['"Figtree"', "sans-serif"],
        accent: ['"Instrument Serif"', "serif"],
      },
      spacing: {
        "gear-1": "4px",
        "gear-2": "8px",
        "gear-3": "12px",
        "gear-4": "16px",
        "gear-5": "20px",
        "gear-6": "24px",
        "gear-8": "32px",
        "gear-10": "40px",
        "gear-12": "48px",
        "gear-16": "64px",
        "gear-20": "80px",
        "gear-24": "96px",
      },
      maxWidth: {
        container: "var(--container-max)",
      },
      borderRadius: {
        DEFAULT: "0",
      },
    },
  },
  plugins: [],
};

export default config;
```

Color utilities reference CSS variables so they stay in sync with the single source of truth in `globals.css`.

---

### 6. Font Loading — layout.tsx

**Approach:** Use `next/font/google` for Figtree and Instrument Serif (both available on Google Fonts). League Gothic is also on Google Fonts, so we use `next/font/google` for all three to get automatic font optimization and self-hosting.

```typescript
import { Figtree, Instrument_Serif } from "next/font/google";
import localFont from "next/font/local"; // fallback if needed

// next/font/google doesn't include League Gothic natively,
// so we load via a <link> in <head> for display font
const figtree = Figtree({
  subsets: ["latin"],
  variable: "--font-figtree",
  display: "swap",
});

const instrumentSerif = Instrument_Serif({
  subsets: ["latin"],
  weight: "400",
  variable: "--font-instrument-serif",
  display: "swap",
});
```

For League Gothic (not in `next/font/google` registry), a Google Fonts `<link>` tag is added to the `<head>`:

```tsx
<head>
  <link
    href="https://fonts.googleapis.com/css2?family=League+Gothic&display=swap"
    rel="stylesheet"
  />
  <script dangerouslySetInnerHTML={{ __html: themeInitScript }} />
</head>
<body className={`${figtree.variable} ${instrumentSerif.variable} font-body`}>
```

In `globals.css`, the body font-family defaults to Figtree:

```css
body {
  font-family: var(--font-figtree), "Figtree", sans-serif;
}
```

---

### 7. Logo File Placement

Directory structure to create:

```
frontend/public/images/logos/
├── gkim-digital-dark.svg
├── gkim-digital-white.svg
├── gears-logo.svg
└── gkim-favicon.svg
```

These are static SVG files served at runtime as `/images/logos/<filename>.svg`. The actual SVG content must be provided by the brand/design team; placeholder files are created during implementation and swapped for final assets.

---

### 8. Sidebar Branding Update — Sidebar.tsx

Replace the current logo/brand `<div>` block:

```tsx
import Image from "next/image";

{/* Logo / Brand */}
<div className="flex h-16 items-center gap-2 px-6 border-b border-[rgb(var(--sidebar-border))]">
  <Image
    src="/images/logos/gears-logo.svg"
    alt="GEARS logo"
    width={140}
    height={32}
    priority
    onError={(e) => {
      // Hide broken image, show fallback
      (e.currentTarget as HTMLImageElement).style.display = "none";
      const fallback = e.currentTarget.nextElementSibling;
      if (fallback) (fallback as HTMLElement).style.display = "inline";
    }}
  />
  <span className="text-lg font-semibold text-[rgb(var(--foreground))] hidden" aria-label="GEARS">
    GEARS™
  </span>
</div>
```

The fallback `<span>` is hidden by default and revealed via the `onError` handler if the image fails to load. The `alt` attribute provides screen reader accessibility.

---

## Data Models

No data model changes. This feature is purely presentational (CSS tokens, fonts, static assets, component markup).

---

## Error Handling

| Scenario | Handling |
|----------|----------|
| GEARS logo SVG fails to load | `onError` handler hides `<Image>`, reveals fallback text `<span>` |
| Google Font CDN unavailable (League Gothic) | `font-display: swap` ensures text remains visible in system sans-serif until font loads; Tailwind `font-display` class applied |
| CSS custom property undefined (older browser) | Literal fallback values can be added as second arg: `var(--bg-dark, #0A0A09)` |

---

## Interfaces

### CSS Custom Property Interface (globals.css :root)

| Property | Value | Category |
|----------|-------|----------|
| `--bg-dark` | `#0A0A09` | Color |
| `--bg-light` | `#F2F2F2` | Color |
| `--bg-accent` | `#FFDD00` | Color |
| `--surface-white` | `#FFFFFF` | Color |
| `--surface-dark` | `#202020` | Color |
| `--text-on-dark` | `#FFFFFF` | Color |
| `--text-on-dark-muted` | `#D6D6D6` | Color |
| `--text-on-light` | `#202020` | Color |
| `--text-on-light-muted` | `#5C5C5C` | Color |
| `--border-on-dark` | `#5C5C5C` | Color |
| `--border-on-light` | `#D6D6D6` | Color |
| `--border-strong` | `#333533` | Color |
| `--spacing-base` | `4px` | Spacing |
| `--container-max` | `1120px` | Layout |

### Tailwind Utility Classes

| Utility Pattern | Maps To |
|-----------------|---------|
| `bg-gear-dark` | `var(--bg-dark)` |
| `bg-gear-accent` | `var(--bg-accent)` |
| `text-gear-text-dark` | `var(--text-on-dark)` |
| `font-display` | League Gothic |
| `font-body` | Figtree |
| `font-accent` | Instrument Serif |
| `p-gear-4` | 16px |
| `max-w-container` | 1120px |

---

## Testing Strategy

- **Unit tests (example-based):** Verify that all GEAR CSS custom properties are defined with correct values, that Tailwind config contains the expected extensions, that the skip-link has proper attributes and positioning classes, and that the Sidebar renders the GEARS™ logo with accessible alt text and fallback behavior.
- **Property tests:** Validate the hard-edge button invariant (all buttons have `border-radius: 0`) and section class color mapping across arbitrarily constructed DOM elements.
- **Visual/manual checks:** Font rendering, logo appearance, and overall aesthetic alignment with the GEAR style guide require visual inspection.

---

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system — essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Hard-edge button invariant

For any button element or element with `role="button"` rendered in the application, its computed `border-radius` shall be `0px` (no rounded corners).

**Validates: Requirements 5.1, 5.3**

### Property 2: Section class color mapping

For any element with one of the section classes (`section-dark`, `section-light`, `section-warm`), the element's computed `background-color` and `color` properties shall match the GEAR token mapping:
- `section-dark` → background `#0A0A09`, color `#FFFFFF`
- `section-light` → background `#FFFFFF`, color `#202020`
- `section-warm` → background `#FFDD00`, color `#202020`

**Validates: Requirements 6.1, 6.2, 6.3, 6.4, 6.5**
