# The metrics, and why each one matters

Nine metrics, all trends on event-log data that keeps real history. Each one answers a question
an admin or a program owner actually asks. Adjustable dimensions let anyone break a metric down
without building anything.

## Adoption — TS Events

The flagship story. All five share one source, so Pulse can relate them and you can ask across
them in one conversation.

**Active Users** — distinct people doing anything on the site over the period. The single clearest
adoption signal. Up is good.
Break down by: Actor Site Role, Actor License Role. (Only user attributes split a distinct-user
count cleanly. Splitting by item, event type, or project double-counts people who do more than one
thing, and buckets logins and admin events into an empty "no item / no project" pile.)

**Site Logins** — how often people sign in. Shows whether Tableau is part of the daily routine or
an occasional visit. Up is good.
Break down by: Actor Site Role, Actor License Role. (Login events aren't tied to content, so
project and item breakdowns would be empty.)

**Content Views** — how much content is actually being consumed. The core value-delivered metric.
Up is good. Counts all access events, including automated renders from subscriptions and alerts, so
it reflects total views served rather than human views only.
Break down by: Project Name, Workbook Name, Item Owner Email, Actor Site Role, Actor License Role.

**Unique Content Accessed** — how many distinct pieces of content get used. Breadth, not just
volume. A high view count concentrated on a shrinking set of content tells a different story than
broad use. Up is good.
Break down by: Item Type, Project Name. (This counts distinct content, so only attributes of the
content split it cleanly. Splitting by the accessing user's role counts the same item once per
role that touched it.)

**Assets Published** — distinct pieces of content published in the period, counting each asset once
no matter how many times it was republished. Shows whether the community is producing, not just
consuming. Includes both new content and updates to existing content (the event log has no
first-publish flag to separate them). Up is good.
Break down by: Item Type, Project Name, Item Owner Email, Actor Site Role, Actor License Role.

## Performance — Viz Load Times

**Average View Load Time** — the experience users actually feel. Slow loads are the fastest way to
lose the adoption you just built. Down is good. Counts only successful loads (Status Code Type =
Success), so fast-returning error responses don't drag the average down.
Break down by: Project Name, Workbook Name, Item Type, Item Owner Email.

**Load Errors** — requests that failed instead of rendering. A reliability signal separate from
speed. Down is good.
Break down by: Status Code Type, Project Name, Workbook Name, Item Type, Item Owner Email.

## Reliability — Job Performance

**Extract Refresh Failures** — failed refreshes mean stale dashboards. The most actionable admin
health metric, because each failure points at a specific schedule or item to fix. Down is good.
Break down by: Schedule Name, Item Name, Item Type, Owner Email, Was Manual Run, Parent Project Name.

**Average Job Duration** — rising durations signal capacity pressure before it turns into
failures. An early-warning metric. Down is good. Measures only jobs that completed successfully
(Final Job Result = Succeeded), so aborted or hung failures don't distort the average.
Break down by: Job Type, Schedule Name, Item Type, Owner Email, Parent Project Name.

## What was deliberately left out of v1

Metrics on current-state snapshot sources (user counts, content counts, license utilization,
storage) were cut on purpose. Those sources full-refresh daily and keep no history, so they can't
trend or compare period over period, and cohort versions carry survivorship bias as users and
content get deleted. They're better read as point-in-time numbers in the Admin Insights views.
Threshold and ratio metrics (slow-load counts over 10s, refresh success rate, inactive users over
90 days) need calculated expressions and are planned for a later, advanced tier.
