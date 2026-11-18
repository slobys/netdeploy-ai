---
version: 1
slug: "app-static-ui-refinement-css"
primary_target: "app/static/ui-refinement.css"
related_targets: ["app/static/theme.css","app/static/index.html","app/static/app.js"]
---

Scope: NetDeploy app UI hierarchy and repeated card alignment; Operate mode across dashboard, servers, projects, tasks and dialogs.
Audience/job: A desktop user manages several VPS and needs to distinguish cards and information groups at a glance.
Direction: Preserve established green logo, six accent choices, clear typography and 1500x1000 landscape window/memory. Recompose surfaces with a cool gray page, solid primary content cards, tinted nested information and a distinct raised dialog. Remove decorative hover glows and broad gradients where they blur boundaries.
First viewport: VPS cards align in a shared grid, with complete IPv6 details and aligned footers. Add VPS is available both beside the heading and as a full grid card at the end of the list, sharing the row height instead of a narrow orphan tile. Title, server group, compact metrics, project choices and task rows remain easy to scan.
Signature interaction: Hovered cards and controls use a tinted surface and accent edge without changing position. Keyboard focus uses an additional outline. The host delete action highlights independently, and the deletion dialog stacks identity, consent and actions with space between them. Long content wraps and toolbar actions can flow onto a new row at narrow widths.
Quality bar: Same structure on dashboard/server page; proper page heading before content; light/dark and all accents retain contrast; no clipped credentials/addresses, missing actions, new runtime dependencies or deployment changes. Validate 0/1/2/5 hosts, long content, 1500/1200/900/600 widths and large reading text. User data and window preferences are preserved. This is an incumbent identity refinement, not a brand replacement.
