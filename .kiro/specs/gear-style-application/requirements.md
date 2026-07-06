# Requirements Document

## Introduction

Apply the GEAR App Style Guide globally across the GKIM Opportunity Finder v2 frontend. This includes relocating the skip-to-content accessibility link, establishing GEAR design tokens (colors, typography, spacing), adding brand logo assets, and replacing the sidebar header branding with the official GEARS™ gear logo and wordmark. No separate top header bar is needed — all branding lives in the sidebar.

## Glossary

- **Application**: The GKIM Opportunity Finder v2 Next.js frontend application
- **Skip_Link**: The "Skip to main content" anchor element used for keyboard accessibility navigation
- **Design_Tokens**: CSS custom properties defining colors, typography families, and spacing scale per the GEAR style guide
- **Globals_CSS**: The `frontend/app/globals.css` stylesheet that defines base CSS custom properties and utility layers
- **Tailwind_Config**: The `frontend/tailwind.config.ts` file that extends Tailwind CSS with project-specific theme values
- **Logo_Directory**: The `frontend/public/images/logos/` directory containing brand logo image assets
- **Sidebar**: The `frontend/components/layout/Sidebar.tsx` component providing primary navigation and branding
- **GEAR_Tokens**: The set of design values from the GEAR App Style Guide including colors, fonts, and spacing
- **Hard_Edge_Button**: A button element styled with border-radius of 0 (no rounded corners)

## Requirements

### Requirement 1: Skip-to-Content Link Relocation

**User Story:** As a keyboard user, I want the skip-to-content link positioned at the bottom-left corner so that it does not visually interfere with the logo area when focused.

#### Acceptance Criteria

1. THE Application SHALL render the Skip_Link with fixed positioning in the bottom-left corner of the viewport.
2. WHILE the Skip_Link does not have keyboard focus, THE Application SHALL keep the Skip_Link visually hidden (translated off-screen).
3. WHEN the Skip_Link receives keyboard focus via Tab, THE Application SHALL make the Skip_Link visible at the fixed bottom-left position.
4. THE Skip_Link SHALL retain the href value of "#main-content" and the text "Skip to main content".
5. THE Skip_Link SHALL have a z-index of 100 or higher to appear above all other page content when visible.

### Requirement 2: GEAR Design Tokens — Colors

**User Story:** As a developer, I want GEAR brand colors defined as CSS custom properties so that all pages use consistent color values from the style guide.

#### Acceptance Criteria

1. THE Globals_CSS SHALL define the custom property `--bg-dark` with the value `#0A0A09`.
2. THE Globals_CSS SHALL define the custom property `--bg-accent` with the value `#FFDD00`.
3. THE Globals_CSS SHALL define custom properties for all GEAR color tokens including dark background, accent yellow, and any supporting neutral or section colors specified by the style guide.
4. THE Globals_CSS SHALL define a dark section color pattern, a light section color pattern, and a warm section color pattern as distinct sets of custom properties.
5. THE Tailwind_Config SHALL extend the Tailwind color palette to include GEAR token color values accessible via utility classes.

### Requirement 3: GEAR Design Tokens — Typography

**User Story:** As a developer, I want GEAR brand typography configured so that display headings, body text, and accent text use the correct font families.

#### Acceptance Criteria

1. THE Application SHALL load the League Gothic font family for display-level headings.
2. THE Application SHALL load the Figtree font family for body text.
3. THE Application SHALL load the Instrument Serif font family for accent or decorative text.
4. THE Tailwind_Config SHALL define font-family utility classes mapping to League Gothic (display), Figtree (body), and Instrument Serif (accent).
5. THE Globals_CSS SHALL set Figtree as the default body font family.

### Requirement 4: GEAR Design Tokens — Spacing

**User Story:** As a developer, I want a consistent spacing scale based on a 4px base unit so that all layout spacing aligns to the GEAR grid.

#### Acceptance Criteria

1. THE Tailwind_Config SHALL define a spacing scale based on a 4px base unit (4, 8, 12, 16, 20, 24, 32, 40, 48, 64, 80, 96 pixels).
2. THE Globals_CSS SHALL define a `--spacing-base` custom property with the value `4px`.

### Requirement 5: Hard-Edge Buttons

**User Story:** As a designer, I want all buttons to have zero border-radius so that the UI matches the GEAR hard-edge aesthetic.

#### Acceptance Criteria

1. THE Globals_CSS SHALL apply a base style setting `border-radius: 0` to all button elements and elements with `role="button"`.
2. THE Tailwind_Config SHALL set the default border-radius for button components to 0.
3. WHEN a button is rendered anywhere in the Application, THE button SHALL display with square corners (no rounded edges).

### Requirement 6: Dark/Light/Warm Section Color Patterns

**User Story:** As a developer, I want predefined dark, light, and warm section classes so that page sections can adopt distinct GEAR color patterns without ad-hoc styling.

#### Acceptance Criteria

1. THE Globals_CSS SHALL define a `.section-dark` class applying the GEAR dark background (`--bg-dark`) with light foreground text.
2. THE Globals_CSS SHALL define a `.section-light` class applying a light/white background with dark foreground text.
3. THE Globals_CSS SHALL define a `.section-warm` class applying the GEAR accent yellow (`--bg-accent`) background with dark foreground text.
4. WHEN a section element uses the `.section-dark` class, THE section SHALL render with background color `#0A0A09` and light-colored text.
5. WHEN a section element uses the `.section-warm` class, THE section SHALL render with background color `#FFDD00` and dark-colored text.

### Requirement 7: Logo Assets

**User Story:** As a developer, I want all required brand logo files placed in the public images directory so that components can reference them via static paths.

#### Acceptance Criteria

1. THE Application SHALL include a GKIM Digital dark logo file at the path `frontend/public/images/logos/gkim-digital-dark.svg` (dark text on transparent background).
2. THE Application SHALL include a GKIM Digital white/inverted logo file at the path `frontend/public/images/logos/gkim-digital-white.svg` (white text for dark backgrounds).
3. THE Application SHALL include a GEARS™ gear logo file at the path `frontend/public/images/logos/gears-logo.svg` (gear icon with "GEARS" text).
4. THE Application SHALL include a GKIM "G" icon/favicon file at the path `frontend/public/images/logos/gkim-favicon.svg` (yellow G mark).
5. THE Logo_Directory SHALL exist at `frontend/public/images/logos/` and contain all four logo assets.

### Requirement 8: Sidebar Branding Update

**User Story:** As a user, I want the sidebar header to display the official GEARS™ gear logo and proper wordmark so that the application branding matches the style guide.

#### Acceptance Criteria

1. THE Sidebar SHALL display the GEARS™ gear logo image from `frontend/public/images/logos/gears-logo.svg` in the header area.
2. THE Sidebar SHALL remove the previous placeholder blue "G" square element and "GKIM Finder" text.
3. THE Sidebar header logo image SHALL have an accessible alt attribute describing the logo (e.g., "GEARS logo").
4. THE Sidebar SHALL not include or depend on a separate top header bar for branding — all branding lives within the Sidebar component.
5. WHEN the GEARS™ logo image fails to load, THE Sidebar SHALL display fallback text identifying the brand name.
