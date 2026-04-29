---
name: Log Intel Design System
colors:
  surface: '#f9f9ff'
  surface-dim: '#d8d9e3'
  surface-bright: '#f9f9ff'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#f2f3fd'
  surface-container: '#ecedf7'
  surface-container-high: '#e6e7f2'
  surface-container-highest: '#e1e2ec'
  on-surface: '#191b23'
  on-surface-variant: '#424754'
  inverse-surface: '#2e3038'
  inverse-on-surface: '#eff0fa'
  outline: '#727785'
  outline-variant: '#c2c6d6'
  surface-tint: '#005ac2'
  primary: '#0058be'
  on-primary: '#ffffff'
  primary-container: '#2170e4'
  on-primary-container: '#fefcff'
  inverse-primary: '#adc6ff'
  secondary: '#505f76'
  on-secondary: '#ffffff'
  secondary-container: '#d0e1fb'
  on-secondary-container: '#54647a'
  tertiary: '#924700'
  on-tertiary: '#ffffff'
  tertiary-container: '#b75b00'
  on-tertiary-container: '#fffbff'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#d8e2ff'
  primary-fixed-dim: '#adc6ff'
  on-primary-fixed: '#001a42'
  on-primary-fixed-variant: '#004395'
  secondary-fixed: '#d3e4fe'
  secondary-fixed-dim: '#b7c8e1'
  on-secondary-fixed: '#0b1c30'
  on-secondary-fixed-variant: '#38485d'
  tertiary-fixed: '#ffdcc6'
  tertiary-fixed-dim: '#ffb786'
  on-tertiary-fixed: '#311400'
  on-tertiary-fixed-variant: '#723600'
  background: '#f9f9ff'
  on-background: '#191b23'
  surface-variant: '#e1e2ec'
typography:
  headline-lg:
    fontFamily: Inter
    fontSize: 30px
    fontWeight: '700'
    lineHeight: 38px
    letterSpacing: -0.02em
  headline-md:
    fontFamily: Inter
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
    letterSpacing: -0.01em
  headline-sm:
    fontFamily: Inter
    fontSize: 18px
    fontWeight: '600'
    lineHeight: 26px
  body-lg:
    fontFamily: Inter
    fontSize: 16px
    fontWeight: '400'
    lineHeight: 24px
  body-md:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 20px
  label-md:
    fontFamily: Inter
    fontSize: 12px
    fontWeight: '600'
    lineHeight: 16px
    letterSpacing: 0.05em
  code-sm:
    fontFamily: monospace
    fontSize: 13px
    fontWeight: '400'
    lineHeight: 18px
rounded:
  sm: 0.125rem
  DEFAULT: 0.25rem
  md: 0.375rem
  lg: 0.5rem
  xl: 0.75rem
  full: 9999px
spacing:
  unit: 4px
  xs: 4px
  sm: 8px
  md: 16px
  lg: 24px
  xl: 40px
  gutter: 20px
  container-max: 1440px
---

## Brand & Style

The design system is engineered for technical clarity, precision, and rapid information synthesis. Designed for DevOps engineers and SREs interacting with Jenkins log data, the aesthetic prioritizes cognitive ease over decorative flair.

The brand personality is **Reliable, Analytical, and Lucid**. It utilizes a **Minimalist Modern** style characterized by significant white space to prevent data fatigue, subtle gradients to provide directional cues, and a rigid adherence to a structured grid. The interface should feel like a high-end laboratory instrument: sterile but powerful, quiet until action is required, and exceptionally organized.

## Colors

The palette is anchored by a high-clarity background (#F8FAFC) to reduce glare during long monitoring sessions. The 'Electric Blue' primary accent acts as a focal point for primary actions and navigational cues.

Status colors are strictly functional:
- **Success (Green):** Indicates healthy builds and resolved issues.
- **Running/Queued (Amber):** Suggests active processing or pending states.
- **Failed/Critical (Red):** Used sparingly to denote immediate blockers or errors.
- **Info (Blue):** Non-critical system metadata.
- **Idle (Gray):** Inactive pipelines or legacy logs.
- **Chaos (Purple):** Represents stochastic testing or randomized log patterns.

Subtle gradients are permitted only on primary buttons and progress indicators to provide a sense of depth without compromising the flat, modern architecture.

## Typography

This design system utilizes **Inter** for all UI elements to ensure maximum legibility across various pixel densities. A clear hierarchy is established by varying weights rather than aggressive size changes.

- **Headlines:** Use Semi-Bold and Bold weights with tighter letter spacing for a compact, professional look.
- **Body Text:** Standardized at 14px for optimal balance between density and readability.
- **Labels:** Set in uppercase with increased letter spacing for categorization and metadata tagging.
- **Log Data:** While the UI uses Inter, log output and terminal snippets must use a system monospace font to preserve character alignment and code structure.

## Layout & Spacing

The layout follows a **fluid grid system** that responds to the wide-screen displays typically used in operations centers. A 12-column grid provides the structural foundation, with a preference for 4-column cards or 12-column full-width tables.

The spacing rhythm is based on a **4px baseline**. Dashboards should utilize 'Ample' spacing (24px+) between major sections to prevent visual clutter, while data-heavy components like log viewers may use 'Condensed' spacing (8px) to maximize the information visible on a single screen.

## Elevation & Depth

The design system employs **Tonal Layering** supplemented by **Ambient Shadows** to create a discernible hierarchy without the "heaviness" of traditional skeuomorphism.

- **Base Layer (Level 0):** The #F8FAFC background.
- **Content Layer (Level 1):** Crisp white cards with a 1px border (#E2E8F0) and a very soft, diffused shadow (0px 4px 6px rgba(0, 0, 0, 0.02)).
- **Interactive Layer (Level 2):** Hovered states or dropdowns use a more pronounced shadow (0px 10px 15px rgba(0, 0, 0, 0.05)) to suggest "lift."

Depth is also communicated through color; interactive elements like buttons should feel physically separate from the static content cards.

## Shapes

The design system uses a **Soft** shape language. This provides a professional and modern look that is more approachable than sharp corners but more serious than highly rounded UI styles.

- **Standard Components:** Buttons, input fields, and badges use a 4px (0.25rem) radius.
- **Containers:** Cards and modal overlays use a 8px (0.5rem) radius.
- **Progress Bars:** Fully rounded ends (pill-shaped) to distinguish them from static structural elements.

## Components

### Cards
Cards are the primary container. They feature a white background, 8px corner radius, and a subtle light-gray border. Card headers should use `label-md` for titles to maintain a clean, professional hierarchy.

### Live Data Badges
Status indicators must be compact and high-contrast. Use a background-tint approach (e.g., Success is light green background with dark green text) for subtle presence, or solid color for critical failure alerts.

### Density-Controlled Tables
Tables are the heart of the system. Rows should have a hover state (#F1F5F9) and minimal vertical borders. Provide three density settings:
1. **Compact:** 4px padding (for log scanning).
2. **Standard:** 8px padding (default).
3. **Spacious:** 16px padding (for management views).

### Progress Bars
Bars should be 8px in height with a subtle gradient (Primary to a slightly lighter tint). For "Running" states, include a subtle animated pulse or shimmer effect to indicate live activity.

### Inputs & Buttons
Inputs should have a 1px border (#CBD5E1) that transitions to Electric Blue on focus. Buttons use a solid Electric Blue fill for primary actions and a ghost/outline style for secondary actions.