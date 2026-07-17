# Frontend Research and Decision Record (2026-07)

## Decision

The old console was replaced instead of reskinned. The new direction is a data-dense seller operations product with four stable destinations:

- **Operations dashboard**: real Worker health, Trace volume, guardrail totals, decision quality, intent distribution, recent activity, and the current operational focus.
- **Reply dry-run**: a safe message composer and decision inspector that never contacts a buyer and does not persist memory unless the operator opts in.
- **Decision database**: a searchable, status-aware list-detail view for routing, guardrails, pricing, knowledge evidence, memory, model state, and latency.
- **Runtime health**: verified snapshot fields, a recovery playbook, and raw evidence behind progressive disclosure.

The shell uses a persistent dark sidebar, compact global status bar, global search, four KPI cards, focused operational panels, and a responsive mobile drawer. URL hashes (`#dashboard`, `#workbench`, `#traces`, `#runtime`) preserve direct navigation. No remote font, CDN, framework, or runtime UI dependency was added, so the existing strict Content Security Policy remains intact.

## Reference Project Review

The visual and interaction reference was [Usagi-org/ai-goofish-monitor](https://github.com/Usagi-org/ai-goofish-monitor), especially its [Vue web UI](https://github.com/Usagi-org/ai-goofish-monitor/tree/master/web-ui/src). Its strongest transferable patterns are:

1. a persistent application shell with global search and machine status;
2. four compact operational metrics instead of a decorative hero;
3. an activity feed that explains what the system just did;
4. task and result views with filters, loading, error, and empty states;
5. a clear split between aggregate monitoring and inspectable records.

GuardAgent does not copy the monitor's scraping domain, component code, glass treatment, or rounded visual style. It adapts the product structure to reply automation: seller messages, Agent routing, evidence, pricing guardrails, memory, and Worker risk control.

The project was archived on 2026-06-09, so it is treated as a design reference rather than an upstream dependency. Its operational lessons still apply: platform risk control must be visible, model output needs deterministic validation, and polluted inputs must not silently influence later decisions.

## Notion Pattern

The connected Notion workspace was searched for customer support, operations dashboard, CRM, ticketing, and database templates. It contained no reusable matching page. The design therefore uses the closest official public Notion patterns:

- [Customer Ticketing & Support](https://www.notion.com/templates/customer-ticketing-support)
- [Customer Support Dashboard](https://www.notion.com/templates/customer-support-dashboard)
- [Work Dashboards](https://www.notion.com/templates/category/work-dashboards)
- [Database templates](https://www.notion.com/help/database-templates)

GuardAgent borrows the information model, not Notion branding:

- stable records with explicit status properties;
- multiple views over one decision collection;
- filters immediately above the collection;
- a selected item with full detail while list context remains visible;
- raw technical evidence disclosed only when requested.

## UI UX Pro Max Application

The `ui-ux-pro-max` design-system search was run for an AI customer-support operations dashboard. Its Real-Time / Operations and Data-Dense Dashboard guidance was applied with project-specific constraints:

- restrained blue primary action, semantic green/amber/red status colors, and cool neutral surfaces;
- system fonts for Chinese stability and CSP compatibility;
- 8px maximum card radius and minimal elevation;
- 44px mobile targets, visible keyboard focus, skip link, semantic headings, and reduced-motion support;
- responsive checks at 390, 1024, and 1440 pixels;
- no marketing hero, decorative gradient, glass card, external font, or invented metric.

The suggested palette was adapted into light and dark themes. Every dashboard value is derived from `/api/overview` or `/api/traces`; the UI does not manufacture business data.

## Implemented Interaction Contract

- Global search moves to the decision database and applies the same query there.
- The dashboard's recent rows open the corresponding Trace; the activity feed footer opens the full decision database.
- Reply dry-run preserves the existing `/api/reply` payload and explicit `persist_turn` behavior.
- Empty input, invalid structured fields, unauthorized access, request conflicts, and network failures keep actionable feedback.
- The newest dry-run result can open its Trace directly.
- Worker risk control remains visible on every view with official recovery steps.
- Theme choice persists locally; access tokens remain scoped to `sessionStorage`.
- Mobile navigation traps no page state and closes after a destination is selected.
- Mobile navigation applies modal semantics, makes the obscured workspace inert, and loops keyboard focus inside the drawer.

## Verification Contract

The redesign is complete only when all of the following are evidenced:

- exactly one workspace view is visible at a time;
- direct hashes and view navigation update the page title and heading;
- a real local dry-run generates a reply while `persist_turn` remains false;
- global search, intent filter, status filter, selected record, and no-result state work;
- the real risk-control error and recovery playbook remain visible;
- 1440x900, 1024x768, and 390x844 layouts have no page-level horizontal overflow;
- mobile drawer open/close state and `aria-expanded` agree;
- light and dark themes render with readable semantic state colors;
- browser console has no errors and the strict CSP remains unchanged;
- backend tests, replay smoke tests, and eval regression tests still pass.
