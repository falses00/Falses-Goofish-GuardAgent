---
name: Falses Goofish GuardAgent
description: A restrained local operator console for safe Xianyu agent decisions.
colors:
  background: "oklch(1 0 0)"
  surface: "oklch(0.978 0.004 180)"
  surface-strong: "oklch(0.948 0.007 185)"
  ink: "oklch(0.205 0.016 225)"
  ink-soft: "oklch(0.38 0.018 220)"
  muted: "oklch(0.48 0.016 215)"
  border: "oklch(0.885 0.009 205)"
  primary: "oklch(0.575 0.165 50)"
  primary-hover: "oklch(0.52 0.17 50)"
  primary-soft: "oklch(0.965 0.025 50)"
  status: "oklch(0.37 0.075 178)"
  status-soft: "oklch(0.955 0.022 178)"
  danger: "oklch(0.48 0.17 25)"
typography:
  headline:
    fontFamily: "system-ui, -apple-system, BlinkMacSystemFont, Segoe UI, Microsoft YaHei UI, sans-serif"
    fontSize: "1.25rem"
    fontWeight: 750
    lineHeight: 1.25
    letterSpacing: "0"
  title:
    fontFamily: "system-ui, -apple-system, BlinkMacSystemFont, Segoe UI, Microsoft YaHei UI, sans-serif"
    fontSize: "1rem"
    fontWeight: 700
    lineHeight: 1.35
    letterSpacing: "0"
  body:
    fontFamily: "system-ui, -apple-system, BlinkMacSystemFont, Segoe UI, Microsoft YaHei UI, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: "0"
  label:
    fontFamily: "system-ui, -apple-system, BlinkMacSystemFont, Segoe UI, Microsoft YaHei UI, sans-serif"
    fontSize: "0.75rem"
    fontWeight: 650
    lineHeight: 1.3
    letterSpacing: "0"
rounded:
  sm: "4px"
  md: "6px"
  lg: "8px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "20px"
  xxl: "24px"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.background}"
    rounded: "{rounded.md}"
    padding: "10px 14px"
    height: "42px"
  button-primary-hover:
    backgroundColor: "{colors.primary-hover}"
    textColor: "{colors.background}"
  button-secondary:
    backgroundColor: "{colors.background}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    padding: "10px 14px"
    height: "42px"
  input:
    backgroundColor: "{colors.background}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    padding: "10px 12px"
  status-badge:
    backgroundColor: "{colors.status-soft}"
    textColor: "{colors.status}"
    rounded: "{rounded.sm}"
    padding: "8px 10px"
---

# Design System: Falses Goofish GuardAgent

## Overview

**Creative North Star: "The Amber Guard Desk"**

The console should feel like a seller's well-organized guard desk in ordinary room light: quiet white surfaces, dark legible text, and one amber confirmation control that appears only where an action is required. Deep teal carries machine state and safety feedback without turning the page into a monitoring wall.

This is a dense product surface, not a campaign. It rejects the project's named anti-references: 炫技 AI 后台, 传统灰色管理系统, and 营销落地页. Familiar controls, explicit state text, and progressive disclosure keep the system usable for a new seller while preserving full Trace depth for debugging.

**Key Characteristics:**
- Status first, with worker health and dry-run mode visible before controls.
- Restrained color, with amber limited to primary actions and teal limited to state.
- Flat bordered surfaces, compact spacing, and no decorative elevation.
- Desktop split views that become one readable column at mobile widths.
- Technical details hidden behind native disclosure controls until requested.

## Colors

Pure white is the architectural background. The brand lives in sparse transaction amber and operational teal, while blue-green neutrals keep long sessions readable.

### Primary
- **Transaction Amber:** Used only for the single primary action in a task, such as generating a simulated reply. White text on this fill has a measured 4.63:1 contrast ratio.

### Secondary
- **Operational Teal:** Used for healthy connection state, selected Trace rows, safety badges, and non-destructive status feedback.

### Neutral
- **Clear White:** The page and panel background. It prevents the amber accent from becoming a brown or orange theme.
- **Guard Ink:** Primary text with a measured 17.84:1 contrast ratio on white.
- **Diagnostic Muted:** Secondary metadata with a measured 6.50:1 contrast ratio on white.
- **Cool Divider:** Thin borders and section dividers that organize density without shadow.

**The Ten Percent Rule.** Amber occupies less than ten percent of a screen and never decorates inactive content.

**The Written State Rule.** Success, warning, failure, and dry-run state always include readable words; color is never the only signal.

## Typography

**Display Font:** System UI sans-serif
**Body Font:** System UI sans-serif
**Label/Mono Font:** System UI sans-serif; browser monospace is reserved for raw JSON only

**Character:** One familiar system family keeps labels, Chinese text, metrics, and controls stable across Windows and mobile browsers. Hierarchy comes from weight and spacing, not display typography.

### Hierarchy
- **Headline** (750, 1.25rem, 1.25): Page and panel task headings.
- **Title** (700, 1rem, 1.35): Result blocks and Trace detail sections.
- **Body** (400, 0.875rem, 1.5): Explanations and generated replies, capped near 70 characters where prose is long.
- **Label** (650, 0.75rem, 1.3): Fields, status labels, metric captions, and metadata. Labels use normal case.

**The Task Scale Rule.** Product headings remain fixed and compact; viewport-driven hero typography is prohibited.

## Elevation

The interface is flat by default. Panels use one-pixel cool dividers and tonal backgrounds, never a border plus wide decorative shadow. A shadow is allowed only on the access-token dialog because it is physically above a modal backdrop.

**The Flat Guard Rule.** If a surface can be separated by spacing, tone, or a one-pixel border, it must not receive a shadow.

## Components

### Buttons
- **Shape:** Compact, gently curved controls (6px radius) with at least 44px width and 36px visible height on mobile.
- **Primary:** Transaction amber with white text, used once per task area.
- **Hover / Focus:** A darker amber hover and a clear three-pixel soft amber focus ring.
- **Secondary:** White with a cool structural border; labels use a verb and object.

### Chips
- **Style:** Pale teal fill, dark teal text, and a complete outline. Chips identify safe state, intent, or guardrails.
- **State:** Selected Trace rows use a full pale-teal background rather than a side stripe.

### Cards / Containers
- **Corner Style:** Restrained 8px maximum radius.
- **Background:** White for working panels and a pale cool surface for secondary list areas.
- **Shadow Strategy:** No shadow at rest.
- **Border:** One-pixel cool divider.
- **Internal Padding:** 16px to 20px on desktop, reduced on mobile.

### Inputs / Fields
- **Style:** White fill, visible one-pixel border, 6px radius, and persistent text labels.
- **Focus:** Stronger border plus a three-pixel soft focus ring.
- **Error / Disabled:** Error copy sits next to the field and is connected through `aria-describedby`; loading disables the submit action without hiding its label.

### Navigation
- **Style:** The page opens directly into the reply workspace. Desktop uses a persistent three-item task sidebar; smaller screens adapt the same hierarchy into a top navigation without introducing a second navigation model.
- **Destinations:** Reply workspace, decision records, and runtime status are stable URL-hash destinations. Navigation preserves filter and form state while changing views.
- **Status Bar:** API, Worker, and send mode stay visible above each destination. A verified runtime problem appears as an explicit recovery alert instead of a generic health badge.

### Trace Split View
- The list follows a database-style view: search, intent filter, explicit decision state, and a stable selected row.
- Desktop uses a bounded list beside a detailed decision view. Mobile stacks the list and detail, preserves full-width hit targets, and allows raw JSON only inside an explicit disclosure control.

## Do's and Don'ts

### Do:
- **Do** show API health, Worker state, and dry-run mode in text before the first action.
- **Do** keep primary amber rare and use operational teal for machine state.
- **Do** preserve keyboard focus, native dialog behavior, `aria-live` feedback, and reduced-motion fallbacks.
- **Do** use real API, runtime snapshot, memory, and Trace values instead of invented dashboard metrics.
- **Do** verify both 1440px desktop and 390px mobile layouts without horizontal overflow.

### Don't:
- **Don't** build a 炫技 AI 后台 with purple gradients, neon glow, glass cards, decorative charts, or unrelated animation.
- **Don't** reproduce a 传统灰色管理系统 with crowded tables, weak hierarchy, color-only state, or errors hidden in logs.
- **Don't** turn the console into a 营销落地页 with oversized headlines, product slogans, or a non-interactive first screen.
- **Don't** combine a one-pixel border with a wide soft shadow on panels.
- **Don't** use colored side stripes on cards, alerts, or selected Trace rows.
- **Don't** exceed an 8px card radius or introduce nested cards.
