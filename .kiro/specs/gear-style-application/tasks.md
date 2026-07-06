# Implementation Plan: GEAR Style Application

## Overview

Apply the GEAR App Style Guide to the GKIM Opportunity Finder v2 frontend by establishing design tokens in CSS custom properties, extending Tailwind config, loading brand fonts, adding section utility classes and button resets, creating logo assets, and updating sidebar branding. All changes are presentational — no data model or API modifications.

## Tasks

- [ ] 1. Establish GEAR design tokens and base styles in globals.css
  - [ ] 1.1 Add GEAR color, spacing, and layout CSS custom properties to `:root` in `frontend/app/globals.css`
    - Add all 14 GEAR custom properties (`--bg-dark`, `--bg-light`, `--bg-accent`, `--surface-white`, `--surface-dark`, `--text-on-dark`, `--text-on-dark-muted`, `--text-on-light`, `--text-on-light-muted`, `--border-on-dark`, `--border-on-light`, `--border-strong`, `--spacing-base`, `--container-max`)
    - Place the new `:root` block above the existing light/dark theme variables
    - _Requirements: 2.1, 2.2, 2.3, 4.2_

  - [ ] 1.2 Add hard-edge button reset and section color pattern classes to `frontend/app/globals.css`
    - Add `button, [role="button"] { border-radius: 0; }` inside `@layer base`
    - Add `.section-dark`, `.section-light`, `.section-warm` classes inside `@layer components`
    - Each section class sets both `background-color` and `color` to GEAR token values
    - _Requirements: 5.1, 6.1, 6.2, 6.3, 6.4, 6.5_

  - [ ] 1.3 Update the `.skip-to-content` class in `frontend/app/globals.css` to fixed bottom-left positioning
    - Change `absolute` to `fixed`, `top-4` to `bottom-4`
    - Change `-translate-y-full` to `translate-y-[200%]`
    - Change `focus:` to `focus-visible:` for keyboard-only reveal
    - Update colors to reference GEAR tokens
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5_

- [ ] 2. Extend Tailwind configuration with GEAR theme values
  - [ ] 2.1 Add GEAR colors, fonts, spacing, maxWidth, and borderRadius to `frontend/tailwind.config.ts`
    - Add `gear` color palette referencing CSS variables
    - Add `fontFamily` entries for `display`, `body`, `accent`
    - Add `spacing` scale (`gear-1` through `gear-24`)
    - Add `maxWidth.container` and `borderRadius.DEFAULT: "0"`
    - Preserve existing `brand` colors and `screens` config
    - _Requirements: 2.5, 3.4, 4.1, 5.2_

- [ ] 3. Set up font loading in layout.tsx
  - [ ] 3.1 Configure `next/font/google` for Figtree and Instrument Serif, add League Gothic `<link>` in `frontend/app/layout.tsx`
    - Import and configure `Figtree` with `variable: "--font-figtree"` and `display: "swap"`
    - Import and configure `Instrument_Serif` with `weight: "400"`, `variable: "--font-instrument-serif"`, `display: "swap"`
    - Add Google Fonts `<link>` for League Gothic in `<head>`
    - Apply font CSS variables to `<body>` className
    - Remove or replace the existing `Inter` font import
    - _Requirements: 3.1, 3.2, 3.3, 3.5_

- [ ] 4. Checkpoint - Verify tokens and fonts
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 5. Create logo directory and placeholder SVG assets
  - [ ] 5.1 Create `frontend/public/images/logos/` directory and add placeholder SVG files
    - Create `gkim-digital-dark.svg` (placeholder dark text logo)
    - Create `gkim-digital-white.svg` (placeholder white/inverted logo)
    - Create `gears-logo.svg` (placeholder gear icon with "GEARS" text)
    - Create `gkim-favicon.svg` (placeholder yellow G mark)
    - Each SVG should be a valid minimal placeholder with descriptive comment
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5_

- [ ] 6. Update Sidebar branding with GEARS™ logo
  - [ ] 6.1 Replace the logo/brand block in `frontend/components/layout/Sidebar.tsx` with GEARS™ `<Image>` component
    - Import `Image` from `next/image`
    - Replace the blue "G" square `<div>` and "GKIM Finder" `<span>` with `<Image src="/images/logos/gears-logo.svg">`
    - Add `alt="GEARS logo"`, `width={140}`, `height={32}`, `priority`
    - Add `onError` handler that hides `<Image>` and shows a hidden fallback `<span>` with "GEARS™" text
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5_

- [ ] 7. Write tests for correctness properties
  - [ ] 7.1 Set up testing framework (Vitest + Testing Library) in `frontend/`
    - Install `vitest`, `@testing-library/react`, `@testing-library/jest-dom`, `jsdom` as dev dependencies
    - Create `vitest.config.ts` with jsdom environment
    - Add `"test": "vitest --run"` script to package.json
    - _Requirements: 5.3, 6.4, 6.5_

  - [ ]* 7.2 Write property test for hard-edge button invariant
    - **Property 1: Hard-edge button invariant**
    - Install `fast-check` as dev dependency
    - Create test file that generates arbitrary button elements and asserts `border-radius` is `0px`
    - Test both `<button>` elements and elements with `role="button"`
    - **Validates: Requirements 5.1, 5.3**

  - [ ]* 7.3 Write property test for section class color mapping
    - **Property 2: Section class color mapping**
    - Create test file verifying that for any element with `section-dark`, `section-light`, or `section-warm` class, the computed styles match GEAR token values
    - `section-dark` → background `#0A0A09`, color `#FFFFFF`
    - `section-light` → background `#FFFFFF`, color `#202020`
    - `section-warm` → background `#FFDD00`, color `#202020`
    - **Validates: Requirements 6.1, 6.2, 6.3, 6.4, 6.5**

  - [ ]* 7.4 Write unit tests for skip-to-content link and sidebar branding
    - Test skip-link has `href="#main-content"` and correct positioning classes
    - Test Sidebar renders `<Image>` with `alt="GEARS logo"` and fallback span
    - _Requirements: 1.1, 1.4, 8.1, 8.3, 8.5_

- [ ] 8. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- Placeholder SVG files should be replaced with final brand assets from the design team
- The existing light/dark theme CSS variables are preserved for backward compatibility

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "5.1"] },
    { "id": 1, "tasks": ["1.2", "1.3", "2.1"] },
    { "id": 2, "tasks": ["3.1", "6.1"] },
    { "id": 3, "tasks": ["7.1"] },
    { "id": 4, "tasks": ["7.2", "7.3", "7.4"] }
  ]
}
```
