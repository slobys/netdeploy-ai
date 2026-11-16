---
version: 1
slug: "app-static-desktop-updates-js"
primary_target: "app/static/desktop-updates.js"
related_targets: ["app/static/desktop-updates.css"]
---

Scope: Extend the existing NetDeploy desktop version badge and shared modal; Operate mode.
Audience and job: Windows users discover a published update on launch or by clicking the version, choose when to install, and keep their data.
Direction: Preserve existing emerald identity, typography, window ratio, dashboard composition and shared dialog. Add a clear version comparison, plain release notes, one download-and-update action and a defer action.
First viewport: The existing top-right version badge remains recognizable and keyboard focusable. A new-release dialog immediately explains current/new version, package size and what the update preserves.
Signature interaction: Click version to check; after consent show byte/percent download progress with cancel, then backup/install/restart. Network errors retry; current version is explicit; automatic failures remain quiet and existing dialogs are not replaced.
Quality bar: No new dependencies; fixed GitHub release source and checksum verification; no arbitrary commands from the page; deployment-in-progress blocks installation; preserve VPS/jobs/auth/window state. Scope is this addition only, no whole dashboard redesign. No concept seed needed for a component extension.
