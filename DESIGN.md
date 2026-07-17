---
name: Falses Goofish GuardAgent
description: A data-dense local operations console for safe Xianyu reply automation.
colors:
  canvas: "#f4f7fb"
  surface: "#ffffff"
  surface-subtle: "#f7f9fc"
  ink: "#0f172a"
  ink-soft: "#334155"
  muted: "#64748b"
  border: "#dbe2ea"
  primary: "#2563eb"
  primary-hover: "#1d4ed8"
  success: "#07875f"
  warning: "#b45309"
  danger: "#d13c4b"
  sidebar: "#151922"
typography:
  family: "system-ui, -apple-system, BlinkMacSystemFont, Segoe UI, Microsoft YaHei UI, sans-serif"
  pageTitle: "1.55rem-2rem / 780 / 1.2"
  panelTitle: "1rem / 750 / 1.35"
  body: "0.78rem / 400 / 1.55"
  label: "0.66rem / 720 / 1.35"
rounded:
  sm: "4px"
  md: "6px"
  lg: "8px"
spacing:
  unit: "4px"
  panel: "14px-22px"
---

# Design System: Falses Goofish GuardAgent

## Product Direction

**North star: Seller Agent Operations.**

The first screen is the working product, not a landing page. It should let an operator answer four questions within seconds: Is the Worker usable? What did the Agent decide? Did a guardrail intervene? What should I do next?

The interface combines the application shell and live monitoring structure of `ai-goofish-monitor` with Notion's database list-detail model. It stays specific to reply automation: no scraping metrics, fake revenue charts, decorative AI imagery, or copied component code.

## Information Architecture

1. **Operations dashboard** is the default view. It summarizes real health, decision volume, guardrails, intent mix, recent decisions, activity, and current risk.
2. **Reply dry-run** is the main creation flow. It keeps safety guarantees close to the form and inspects the generated decision beside it.
3. **Decision database** is the audit surface. Search, intent, and safety status filter one collection while the selected Trace stays readable.
4. **Runtime health** separates evidence from recovery guidance.

Desktop uses a 238px persistent sidebar and a compact sticky top bar. Screens at 960px and below use a modal drawer while preserving the same destinations and URL hashes.

## Visual System

- **Canvas:** cool light gray with white working surfaces; dark mode uses near-black canvas and charcoal surfaces.
- **Primary:** blue is reserved for selected navigation, links, and the primary task action.
- **Status:** green means safe/healthy, amber means review/risk, red means blocked/error. Every color is paired with written state.
- **Sidebar:** fixed dark neutral, giving the product a stable operational frame without making all content dark.
- **Shape:** cards and controls use 4-8px radii. No pills except true compact status badges.
- **Elevation:** one-pixel borders and small shadows only. The token dialog and primary action may receive stronger elevation.
- **Typography:** system UI fonts only. Chinese text, metrics, and controls must remain stable without a network request.

## Component Rules

### Global Shell

- Global search accepts messages, conversation IDs, Agent names, and guardrails.
- API, Worker, and Dry-run status remain visible on desktop and collapse before they can crowd tablet layouts.
- Icon-only theme, refresh, and menu controls have tooltips or accessible names.

### Dashboard

- Four KPI cards use only real `/api/overview` and `/api/traces` values.
- Decision quality and intent distribution use the same latest-50 Trace window as the overview guardrail sample.
- Recent decisions use a compact table on desktop and a horizontally contained table on mobile.
- Recent activity and operational focus explain the current risk instead of repeating raw counts.

### Reply Dry-run

- The primary message is visible immediately; structured context lives in progressive disclosure.
- Safety copy states that no buyer is contacted and memory persistence is opt-in.
- Loading, empty, result, API error, and field validation states occupy stable regions.

### Decision Database

- Filters sit directly above the collection.
- Desktop preserves list and detail context; mobile stacks them without removing evidence.
- Raw model, policy, and Trace JSON stays behind native disclosure controls.

### Runtime Health

- Snapshot values and recovery steps are separate panels.
- A stale or risk-controlled Worker must never be presented as healthy.
- Recovery guidance prioritizes official platform verification, refreshed login state, Dry-run validation, then restart.

## Accessibility And Responsive Rules

- All interactive mobile targets are at least 44px.
- Keyboard focus remains visible on controls; programmatically focused headings retain semantics without a decorative outline.
- A skip link, semantic heading order, `aria-live` feedback, dialog semantics, and reduced-motion fallback are mandatory.
- Text wraps before it shrinks. Tables scroll inside their own container; the page itself must not overflow horizontally.
- Verify at 390x844, 1024x768, and 1440x900 in both themes where relevant.

## Prohibited Patterns

- No marketing hero, oversized slogan, decorative orb, glass panel, bokeh, or one-hue gradient theme.
- No invented analytics, fake online status, or color-only meaning.
- No external font/CDN requirement that weakens the current CSP or offline-first behavior.
- No card radius above 8px, nested decorative cards, or entire sections floating without purpose.
- No hidden recovery path for platform risk control, authentication failure, or stale Worker state.
