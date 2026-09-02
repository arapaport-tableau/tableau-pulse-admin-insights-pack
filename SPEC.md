# Pulse Admin Insights Pack — v1 Spec (planning)

Status: planning. Nothing built yet. Repo name and final location TBD.

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

Sources used: TS Events, Viz Load Times, Job Performance, Subscriptions, TS Users,
Site Content. (Also present but unused in v1: Groups, Permissions, Tokens.)

## Design principles

- Easy above all. If a capability adds risk or a licensing dependency, it does not go in v1.
- REST API only. No MCP dependency. Runs on any site with a token.
- No secrets in the repo, ever.
- Safe against production: dry-run first, idempotent creates, manifest-based uninstall.
- Only ever creates net-new Pulse definitions. Never touches data, content, or settings.

## Auth model

- PAT only. It is revocable, scoped to the user, and avoids SSO/MFA sign-in failures.
- Prompt-first: default flow prompts for PAT name, then secret via getpass (never echoed,
  never written to disk). This makes it impossible for a first-time user to commit a secret.
- Opt-in config for repeat runs: `config.json` (gitignored) or env vars. Ship `config.example.json`.
- Required inputs: server URL, site content-url, PAT name, PAT secret.
- Role: creating Pulse definitions may require Site Admin or a Creator/Explorer with the
  metric-creation site setting enabled. This varies by site config, so preflight detects and
  reports the running user's actual capability rather than asserting a fixed requirement.

## Run model (CLI)

- `deploy.py --dry-run` — sign in, confirm Admin Insights is enabled, resolve source LUIDs,
  confirm required fields exist, check for name collisions, print the full plan. No writes.
- `deploy.py` — create the definitions. Idempotent: skip any that already exist by name so
  re-running is safe. Write `manifest.json` recording every created ID.
- `deploy.py --with-metrics --follow` — also seed a default metric per definition and subscribe
  the running user, so they see a live feed immediately. Off by default (base run is inert).
- `deploy.py --group "Name"` — create-or-reuse a group and batch-subscribe it to every metric.
  Onboarding a person becomes "add them to the group." Recommended run for teams.
- `deploy.py --uninstall` — read the manifest and delete only what the tool created. Clean rollback.

## Data source architecture decision

Pulse's cross-metric experience (related metrics, correlations, asking across metrics) is
scoped to metrics that share the same published data source. Our metrics span six Admin
Insights sources, so out of the box they form six conversational clusters, not one.

Options considered:
- Multi-table / composed source: rejected. Mixed grains cause join fan-out and ambiguous
  aggregation, and relationship wiring cannot be done through the API (manual browser step).
- Prep flow building a unified fact: rejected for v1. Scheduling a refresh on Cloud needs
  Prep Conductor / Data Management, which not every customer licenses. Breaks "works everywhere."
- Tool-built single Hyper fact (Python aggregation, no Prep): rejected for v1. Freshness is the
  problem. A normal extract refresh cannot re-run the aggregation, so it only updates on re-run.

Decision for v1: cluster by native source, lead with adoption. The flagship adoption story is
almost entirely TS Events, so those metrics already share one source and form one rich Pulse
conversation with zero data engineering. Performance, Reliability, and Licensing are each their
own single-source cluster. Conversation works within each theme; document that scope honestly.

A fully unified "one conversation across everything" source (scripted Hyper or a Prep flow for
Data Management customers) is deferred to an explicit advanced option in a later version, with
the freshness and licensing tradeoffs spelled out.

## Metrics (v1 MVP, basic specifications only)

Nine metrics, all basic-spec. Basic specs support definition filters on dimensions, so
"count where [dimension] = X" is fully supported and scriptable. No advanced expressions in v1.

**MVP scope rule: event/activity-log sources only.** TS Events, Viz Load Times, and Job
Performance are append-style logs that retain real history, so every metric trends honestly
and compares period over period the day Pulse is turned on. Current-state snapshot sources
(TS Users, Site Content, Subscriptions) full-refresh daily and keep no history, so snapshot
metrics cannot trend and cohort metrics undercount older periods. Those are held for a later
version (see "Deferred" below), which keeps the MVP defensible to any Tableau Cloud admin.

Filter string values marked (confirm) must be verified against live data at build time
via query-datasource (exact Event Name / Event Type / Job Type / Status Code Type strings).

### A. Adoption — TS Events, time = Event Date (flagship single conversation)
Adjustable dims: Project Name, Actor Site Role, Actor License Role, Item Type.
1. Active Users — COUNT_DISTINCT [Actor User Name] — up is good — trend
2. Site Logins — SUM [Number of Events], filter Event Name = Login (verified live) — up is good — trend
3. Content Views — SUM [Number of Events], filter Item Type = View + Event Type = Access (verified live) — up is good — trend
4. Unique Content Accessed — COUNT_DISTINCT [Item LUID], filter Event Type = Access (verified live) — up is good — trend
5. New Content Published — SUM [Number of Events], filter Event Type = Publish (verified live; Create is admin object creation, not content) — up is good — trend

### B. Performance — Viz Load Times, time = Request Time
Adjustable dims: Project Name, Item Type, Workbook Name.
6. Average View Load Time — AVG [Duration] — down is good — trend
7. Load Errors — COUNT [Request ID], filter Status Code Type in (Client errors, Server errors) (confirm) — down is good — trend

### C. Reliability — Job Performance, time = Started At
Adjustable dims: Job Type, Final Job Result, Schedule Name.
8. Extract Refresh Failures — COUNT [Job ID], filter Final Job Result = Failed + Job Type = Extract Refresh (confirm) — down is good — trend
9. Average Job Duration — AVG [Job Duration] — down is good — trend

### Deferred (not in the MVP)

Cohort and snapshot metrics, cut for data-shape reasons, not lack of value. They sit on
current-state snapshot sources (TS Users, Site Content, Subscriptions) that full-refresh
daily: snapshot metrics have no source history to trend, and cohort metrics carry
survivorship bias. Better served as point-in-time readouts in the Admin Insights views.
Candidates for a later version, likely with a purpose-built fact source that banks daily
snapshots.
- Data Source Connections (TS Events) — narrower governed-data signal, second-tier for adoption
- New Users, Content Growth — cohort trends with survivorship bias
- New Subscriptions & Metric Follows, Subscriptions Delivered — Subscriptions shape can't count delivery over time (Last Sent is one timestamp per subscription)
- Occupied Licenses, Remaining Licenses, Average Days Since Last Login, Site Storage Used — snapshot state, no source history; license fields are FIXED site-level calcs Pulse may reject

Advanced-tier candidates need calculated expressions (thresholds / ratios): Slow Loads
(>10s), Inactive Users count (>90 days), Stale Content (>90 days), License Utilization %,
Refresh Success Rate %.

## Portability limits (v1)

- English field names only. Non-English sites may not resolve. Documented; locale map is future work.
- Admin Insights must be enabled (site setting). Preflight detects absence and links to the fix.
- MVP uses only event-log sources, so every metric has genuine back-history within the Admin
  Insights retention window. No snapshot metrics ship in v1, so there is no flat-line caveat.

## Repo structure

```
<repo>/
  deploy.py              # sign in, preflight, create, seed, group, uninstall
  definitions/           # one JSON per metric (portable spec)
  config.example.json    # server_url, site_name, pat_name, pat_secret (real one gitignored)
  requirements.txt       # tableauserverclient, requests
  METRICS.md             # what each metric tells you and why it matters (mindset-shift doc)
  README.md              # prereqs, quickstart, safety notes, trend-vs-snapshot caveat, disclaimer
  LICENSE                # MIT (public repo)
  .gitignore             # config.json, manifest.json, __pycache__
```

## Open items

- Repo name and final location.
- Advanced-definition probe (deferred; only needed if we build the advanced tier).
- Confirm filter string values against live data at build time.
- Whether `--group` or `--with-metrics --follow` is the headline recommended run in the README.
- Public unofficial-tool disclaimer wording.
