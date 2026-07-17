# Frontend Research and Decision Record (2026-07)

## Decision

The console needed an information-architecture update, not a visual reset. The previous page already had safe dry-run behavior, readable tokens, accessible form labels, and real Trace data. Its main weakness was that runtime status, reply simulation, and long Trace details lived on one continuous page. A stale or risk-controlled Worker was summarized as a generic authentication failure, so a new seller could not tell what failed or how to recover.

The implemented direction is a local operator workspace with three stable destinations:

- **Reply workspace**: dry-run input and result remain the primary task.
- **Decision records**: a searchable list-detail view exposes intent, route, guardrails, pricing, evidence, and raw Trace.
- **Runtime status**: verified API and Worker properties are separated from recovery guidance.

The URL hash preserves the active destination (`#workbench`, `#traces`, `#runtime`). Desktop uses a persistent sidebar; smaller screens use the same three destinations as a compact top navigation. No new framework or remote UI dependency was added.

## Source Project Review

The referenced article, [闲鱼监控工具 ai-goofish-monitor 火到 1.3 万星：我翻完代码，真正难的不是 AI](https://mp.weixin.qq.com/s/rHnfClbBW_3t4ZLIrGUnqg?scene=1), discusses [Usagi-org/ai-goofish-monitor](https://github.com/Usagi-org/ai-goofish-monitor). The repository and linked issues support three transferable lessons:

1. Deterministic collection, validation, deduplication, and task isolation must happen before model judgment.
2. Dirty inputs can corrupt later price or recommendation decisions even when the model rejects individual records.
3. Platform risk control and expired login state are operating conditions that need visible recovery paths, not hidden log messages.

Primary evidence:

- [Issue #479: irrelevant results pollute price trends](https://github.com/Usagi-org/ai-goofish-monitor/issues/479)
- [Issue #430: task data and prompt isolation problems](https://github.com/Usagi-org/ai-goofish-monitor/issues/430)
- [Issue #308: model compatibility is an operational dependency](https://github.com/Usagi-org/ai-goofish-monitor/issues/308)

The monitoring and scraping features were not copied because they solve a different job. GuardAgent remains a reply automation project. The relevant lesson was applied by surfacing the real `XianyuRiskControlError`, keeping dry-run prominent, and making Trace evidence filterable.

## Frontend Skills Survey

GitHub metadata was queried on 2026-07-17. Stars are a popularity signal, not a quality score.

| Repository | Stars at query time | Use in this project |
| --- | ---: | --- |
| [anthropics/skills](https://github.com/anthropics/skills) | 162,043 | Used as the general Agent Skills packaging reference, not as a dashboard design system. |
| [nextlevelbuilder/ui-ux-pro-max-skill](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill) | 106,906 | Applied adaptive navigation, deep linking, state preservation, 44px touch targets, explicit error recovery, and responsive checks. |
| [Leonxlnx/taste-skill](https://github.com/Leonxlnx/taste-skill) | 64,526 | Evaluated but not applied because its own scope explicitly excludes dashboards and multi-step product UI. |
| [pbakaus/impeccable](https://github.com/pbakaus/impeccable) | 47,547 | Applied the product register: restrained color, status-first hierarchy, progressive disclosure, stable components, and evidence-based browser verification. |
| [superdesigndev/superdesign-skill](https://github.com/superdesigndev/superdesign-skill) | 344 | Evaluated but not introduced because the existing HTML/CSS surface did not need an authenticated external design canvas or a new generated draft layer. |

This selection avoids the common mistake of combining every popular skill. Scope fit and verification requirements take priority over stars.

## Notion Pattern

The closest official Notion pattern is **Projects backed by database views, status properties, and item detail pages**:

- [Notion Projects](https://www.notion.com/product/projects)
- [Introduction to databases](https://www.notion.com/help/intro-to-databases)
- [Database views](https://www.notion.com/help/views)
- [Status property](https://www.notion.com/help/guides/status-property)

GuardAgent borrows the information model, not Notion branding:

- one stable object list with visible properties;
- search and intent filters over the same Trace collection;
- a selected record opens in a detail region without losing list context;
- runtime and safety states use explicit text properties;
- raw technical data remains available through progressive disclosure.

## Verification Contract

The frontend change is complete only when these checks pass:

- one and only one workspace view is visible at a time;
- browser back/forward and direct hashes preserve the active view;
- Trace search handles matches and a no-result state;
- a dry-run reply can open its newly generated Trace;
- the current risk-control error is visible with recovery steps;
- 1440px and 390px layouts have no horizontal overflow;
- visible mobile controls meet the 44px touch-target minimum;
- keyboard focus, reduced motion, API errors, and token recovery remain usable.
