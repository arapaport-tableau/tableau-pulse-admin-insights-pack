# Pulse Admin Insights Pack — v1 Spec

Status: shipped (v1). Public repo: `arapaport-tableau/tableau-pulse-admin-insights-pack`.

## Purpose

A prebuilt, deploy-anywhere set of Tableau Pulse metric definitions built on the
standard Admin Insights data sources that ship with every Tableau Cloud site.

The goal is adoption and speed to value. Most customers struggle with the mindset
shift Pulse requires. Giving them a ready-made set of easy-to-understand metrics,
connected to real data they already care about (their own Tableau usage), lets them
experience Pulse the day they turn it on, with no data prep.

## Why Admin Insights

Admin Insights is auto-provisioned into a locked "Admin Insights" project on every
Cloud site, owned by the Tableau System Account. The schema is standardized across
all sites: same source names, same field names. That standardization is what makes
a portable pack possible. The definitions reference field names that resolve on any
site; the only per-site variable is each source's LUID, which the tool looks up by
name at deploy time.

Sources used in v1: **TS Events, Viz Load Times, Job Performance** — the three
append-style event logs that retain real history. Current-state snapshot sources
(TS Users, Site Content, Subscriptions, Groups, Permissions, Tokens) are held out;
see "Deferred" below.

## Design principles

- Easy above all. If a capability adds risk or a licensing dependency, it does not go in v1.
- REST API only. No MCP dependency. Runs on any site with a token.
- No secrets in the repo, ever.
- Safe against production: dry-run first, adopt-don't-duplicate creates, state-based uninstall.
- Only ever creates net-new Pulse definitions. Never touches data, content, or settings, and
  never edits a definition it did not create.

## Auth model

- PAT only. It is revocable, scoped to the user, and avoids SSO/MFA sign-in failures.
- Prompt-first: default flow prompts for PAT name, then secret via getpass (never echoed,
  never written to disk). This makes it impossible for a first-time user to commit a secret.
- Opt-in config for repeat runs: `config.json` (gitignored) or env vars. Ship `config.example.json`.
- Required inputs: server URL, site content-url, PAT name, PAT secret.
- Role: creating Pulse definitions may require Site Admin or a Creator/Explorer with the
  metric-creation site setting enabled. This varies by site config, so preflight detects and
  reports the running user's actual capability rather than asserting a fixed requirement.

## Version floor

Tableau Cloud 2024.2 (REST API 3.24) or newer. The Pulse definition/metric/subscription
endpoints the tool calls do not exist on older releases; preflight checks and stops with a
version hint if they are missing. VizQL Data Service must also be enabled (used for field
resolution and filter validation).

## Run model

Two front ends over one shared engine (`engine.py`):

- **`app.py`** — a local web GUI (the default front door for non-technical users). Binds to
  `127.0.0.1` only, holds the PAT secret in memory just long enough to sign in, gates every API
  call with a random per-launch token, runs long operations in a background thread, and reports
  progress via `/api/status` polling (no websockets). Double-click launchers (`Start Pulse
  Pack.command` / `.bat`) do a one-time venv+pip setup and open the browser. No credentials are
  ever stored; entered fresh each run.
- **`deploy.py`** — the command-line face. Everything is a flag on it — no separate scripts.

Both call the same `engine.py` functions (`sign_in`, `build_plan`, `validate_filters`,
`execute_deploy`, `uninstall_plan`, `execute_uninstall`), so behavior, defaults, safety
guarantees, and per-site state files are identical across the two. The engine never prints or
exits; it returns structured results, takes an optional `log` callback for progress, and raises
`EngineError` (plain-language message + hint) on anything a user should see.

The CLI flags:

- `deploy.py --dry-run` — sign in, preflight (site role, Pulse reachable, VDS enabled), resolve
  source LUIDs, resolve every field, match each metric against what already exists (by name **and**
  full specification), count the rows each `confirm:true` filter matches and flag any empties, and
  print the full plan. No writes.
- `deploy.py` — create the definitions. Idempotent by **spec signature**: a metric that already
  exists with the same specification is adopted rather than duplicated (a rename of one of ours
  still matches). On create the tool also sets the metric to week-to-date and writes the
  definition description. Writes per-site state to `manifest.<site_id>.json`.
- `deploy.py --group [NAME]` — create-or-reuse a group (default "Admin Insights Metrics") and
  batch-subscribe it to every metric. Group-follow is the recommended run for teams and doubles as
  the ownership marker for the pack. Onboarding a person becomes "add them to the group." The tool
  never adds members itself.
- `deploy.py --follow` — also subscribe the running user, so they see a live feed immediately.
- `deploy.py --on-conflict {skip,suffix}` — when a name exists with a **different** spec: skip it
  (default, never mutate a foreign definition) or create ours under a suffixed name.
- `deploy.py --uninstall [--dry-run]` — delete only what a prior run created (from per-site state),
  unfollow any it merely adopted, and delete the group only if the tool created it. A site-match
  guard prevents running against the wrong site (`--force` to override). If the state file is gone,
  it falls back to discovering the pack from the follow group and asks to confirm before deleting
  (`--yes` to skip the prompt), warning that in that mode it cannot distinguish created from adopted.

## Data source architecture decision

Pulse's cross-metric experience (related metrics, correlations, asking across metrics) is
scoped to metrics that share the same published data source. Our v1 metrics span three Admin
Insights sources, so out of the box they form three conversational clusters, not one.

Options considered:
- Multi-table / composed source: rejected. Mixed grains cause join fan-out and ambiguous
  aggregation, and relationship wiring cannot be done through the API (manual browser step).
- Prep flow building a unified fact: rejected for v1. Scheduling a refresh on Cloud needs
  Prep Conductor / Data Management, which not every customer licenses. Breaks "works everywhere."
- Tool-built single Hyper fact (Python aggregation, no Prep): rejected for v1. Freshness is the
  problem. A normal extract refresh cannot re-run the aggregation, so it only updates on re-run.

Decision for v1: cluster by native source, lead with adoption. The flagship adoption story is
entirely TS Events, so those five metrics already share one source and form one rich Pulse
conversation with zero data engineering. Performance and Reliability are each their own
single-source cluster. Conversation works within each theme; document that scope honestly.

A fully unified "one conversation across everything" source (scripted Hyper or a Prep flow for
Data Management customers) is deferred to an explicit advanced option in a later version, with
the freshness and licensing tradeoffs spelled out.

## Metrics (v1 MVP, basic specifications only)

Nine metrics, all basic-spec. Basic specs support definition filters on dimensions, so
"count where [dimension] = X" is fully supported and scriptable. No advanced expressions in v1.
All nine default to week-to-date (`GRANULARITY_BY_WEEK`, current partial period).

**MVP scope rule: event/activity-log sources only.** TS Events, Viz Load Times, and Job
Performance are append-style logs that retain real history, so every metric trends honestly
and compares period over period the day Pulse is turned on. Current-state snapshot sources
full-refresh daily and keep no history, so snapshot metrics cannot trend and cohort metrics
undercount older periods. Those are held for a later version (see "Deferred").

Adjustable dimensions are chosen **per metric**, not per cluster: each list is drawn from fields
that return real values for that metric, omits any dimension pinned by the metric's own filter,
and favors low/medium-cardinality categoricals. Distinct-count metrics (Active Users, Unique
Content Accessed) only break down cleanly on an attribute of the thing counted, so their lists
are deliberately narrow — see METRICS.md.

### A. Adoption — TS Events, time = Event Date (flagship single conversation)
1. Active Users — COUNT_DISTINCT [Actor User Name], no filter — up is good. Dims: Actor Site Role, Actor License Role.
2. Site Logins — COUNT [Event Id], filter Event Name = Login (verified) — up is good. Dims: Actor Site Role, Actor License Role.
3. Content Views — COUNT [Event Id], filter Item Type = View + Event Type = Access (verified) — up is good. Includes automated renders (subscriptions, alerts). Dims: Project Name, Workbook Name, Item Owner Email, Actor Site Role, Actor License Role.
4. Unique Content Accessed — COUNT_DISTINCT [Item LUID], filter Event Type = Access (verified) — up is good. Dims: Item Type, Project Name.
5. Assets Published — COUNT_DISTINCT [Item LUID], filter Event Type = Publish (verified) — up is good. Counts distinct assets (new or updated), not publish events. Dims: Item Type, Project Name, Item Owner Email, Actor Site Role, Actor License Role.

### B. Performance — Viz Load Times, time = Request Time
6. Average View Load Time — AVG [Duration], filter Status Code Type = Success (verified) — down is good. Successful loads only, so error responses don't skew the average. Dims: Project Name, Workbook Name, Item Type, Item Owner Email.
7. Load Errors — COUNT [Request ID], filter Status Code Type in (Client errors, Server errors) (confirm) — down is good. Dims: Status Code Type, Project Name, Workbook Name, Item Type, Item Owner Email.

### C. Reliability — Job Performance, time = Started At
8. Extract Refresh Failures — COUNT [Job ID], filter Final Job Result = Failed + Job Type in (RefreshExtracts, RefreshExtractsViaBridge) (confirmed — Admin Insights uses raw job-type enums; there is no "Extract Refresh" value. Final Job Result is a two-state field, so Failed captures every non-success) — down is good. Dims: Schedule Name, Item Name, Item Type, Owner Email, Was Manual Run, Parent Project Name.
9. Average Job Duration — AVG [Job Duration], filter Final Job Result = Succeeded (verified) — down is good. Successful runs only, so failures don't distort healthy-job runtime. Dims: Job Type, Schedule Name, Item Type, Owner Email, Parent Project Name.

Filter values marked (confirm) are set to the standard English Admin Insights values and are
row-count-validated in `--dry-run` against live data.

### Deferred (not in the MVP)

Cohort and snapshot metrics, cut for data-shape reasons, not lack of value. They sit on
current-state snapshot sources (TS Users, Site Content, Subscriptions) that full-refresh
daily: snapshot metrics have no source history to trend, and cohort metrics carry
survivorship bias. Better served as point-in-time readouts in the Admin Insights views.
Candidates for a later version, likely with a purpose-built fact source that banks daily
snapshots.
- New Users, Content Growth — cohort trends with survivorship bias
- New Subscriptions & Metric Follows, Subscriptions Delivered — Subscriptions shape can't count delivery over time (Last Sent is one timestamp per subscription)
- Occupied Licenses, Remaining Licenses, Average Days Since Last Login, Site Storage Used — snapshot state, no source history; license fields are FIXED site-level calcs Pulse may reject

Advanced-tier candidates need calculated expressions (thresholds / ratios): Slow Loads
(>10s), Inactive Users count (>90 days), Stale Content (>90 days), License Utilization %,
Refresh Success Rate %.

## Portability limits (v1)

- English field names only. Non-English sites may not resolve. Documented; locale map is future work.
- Admin Insights must be enabled (site setting). Preflight detects absence and links to the fix.
- Targets the `... (local)` Admin Insights sources; on a name collision the tool prefers the
  Admin Insights project and warns in the plan.
- MVP uses only event-log sources, so every metric has genuine back-history within the Admin
  Insights retention window (~90 days rolling). No snapshot metrics ship in v1, so there is no
  flat-line caveat. New metrics take a couple of minutes to index before they populate.

## Repo structure

```
<repo>/
  engine.py              # all logic: connect, preflight, plan, create, group, follow, uninstall
  deploy.py              # command-line face (thin CLI over engine.py)
  app.py                 # local web GUI face (Flask, 127.0.0.1 only)
  web/index.html         # the app's single-page UI (token injected at serve time)
  Start Pulse Pack.command / .bat   # double-click launchers (one-time venv+pip, then run app.py)
  metrics.manifest.json  # the metric definitions (intermediate representation the engine maps to Pulse)
  config.example.json    # server_url, site_name, pat_name (real config.json gitignored)
  requirements.txt       # tableauserverclient, requests, flask
  METRICS.md             # what each metric tells you and why it matters (mindset-shift doc)
  metrics-catalog.html   # visual catalog of the pack
  README.md              # app-first quickstart, safety notes, limits, disclaimer
  CLI.md                 # command-line guide and full flag reference
  LICENSE                # public repo
  .gitignore             # config.json, manifest.json, manifest.*.json, __pycache__, .venv
```

## Resolved decisions

- Single shared engine (`engine.py`) behind two faces (`deploy.py` CLI, `app.py` web GUI), single
  metric IR (`metrics.manifest.json`). No `definitions/` dir.
- The web app is the default front door for non-technical users: local-only (`127.0.0.1`),
  in-memory secret, per-launch token gate, polling for progress, no credential storage.
- `--group` is the headline recommended run; group-follow is also the ownership marker (no name prefix).
- Duplicate handling: adopt by spec signature; skip same-name-different-spec by default (`--on-conflict suffix` to override).
- Per-site state (`manifest.<site_id>.json`) with a site-match guard on uninstall; discovery-based uninstall as fallback.
- Filter string values confirmed against live data and revalidated in every `--dry-run`.
