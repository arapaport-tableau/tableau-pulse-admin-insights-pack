#!/usr/bin/env python3
"""
deploy.py — Pulse Admin Insights Starter Pack installer.

Creates a set of prebuilt Tableau Pulse metric definitions on the standard Admin Insights
data sources that ship with every Tableau Cloud site. No data prep. The metrics are authored
once in metrics.manifest.json using human-readable field captions; at deploy time this tool
resolves each caption to Pulse's internal fieldName via the VizQL Data Service (the same field
list the Pulse UI reads), so the pack is portable to any site regardless of that site's LUIDs.

Safe by design:
  - Only ever CREATES net-new Pulse definitions (and, optionally, a group + subscriptions).
    It never edits a definition it did not create, and never touches data or site settings.
  - Idempotent and collision-aware: metrics are matched by NAME and by full SPECIFICATION
    (Pulse dedups on spec, not name), so re-runs adopt what already exists instead of failing.
  - --dry-run makes no writes at all and validates filter values against live data.
  - --uninstall removes exactly what this tool created, and can rediscover its own metrics
    from the group that follows them when the local state file is gone.

Usage:
  ./.venv/bin/python deploy.py --dry-run          # show the full plan + validation, write nothing
  ./.venv/bin/python deploy.py                     # create the definitions (inert; nothing followed)
  ./.venv/bin/python deploy.py --group "Admin Insights Metrics"   # + create/reuse group, follow all
  ./.venv/bin/python deploy.py --follow            # + subscribe the running user to every metric
  ./.venv/bin/python deploy.py --uninstall --dry-run   # preview a cleanup
  ./.venv/bin/python deploy.py --uninstall         # remove exactly what a prior run created

Connection details come from (in order): CLI env vars, config.json (gitignored), then prompts.
The PAT secret is read via getpass, never echoed and never written to disk.

Run with the project venv (system python3 is 3.9 and incompatible with TSC 0.41):
    ./.venv/bin/python deploy.py [flags]
"""

import argparse
import getpass
import json
import os
import sys
from datetime import datetime, timezone

import requests
import tableauserverclient as TSC

HERE = os.path.dirname(os.path.abspath(__file__))
IR_PATH = os.path.join(HERE, "metrics.manifest.json")       # committed IR (the metric catalog)
LEGACY_STATE_PATH = os.path.join(HERE, "manifest.json")     # old single-site state (still readable)
CONFIG_PATH = os.path.join(HERE, "config.json")             # optional creds (gitignored)

GRANULARITIES = ["GRANULARITY_BY_DAY", "GRANULARITY_BY_WEEK", "GRANULARITY_BY_MONTH",
                 "GRANULARITY_BY_QUARTER", "GRANULARITY_BY_YEAR"]
DEFAULT_RANGE = "RANGE_CURRENT_PARTIAL"   # "to date": current, still-in-progress period
DEFAULT_GROUP_NAME = "Admin Insights Metrics"
ADMIN_INSIGHTS_PROJECT = "Admin Insights"
VND_CREATE = "application/vnd.tableau.metricqueryservice.v1.CreateDefinitionRequest+json"


def state_path(site_id):
    """Per-site runtime state file, so deploying to multiple sites never clobbers records."""
    return os.path.join(HERE, f"manifest.{site_id}.json")


# ── Connection ──────────────────────────────────────────────────────────────────
def load_connection():
    cfg = {}
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            cfg = json.load(f)

    def pick(env, key, prompt, default=None, secret=False):
        val = os.environ.get(env) or cfg.get(key)
        if val:
            return str(val).strip()
        if secret:
            return getpass.getpass(prompt).strip()
        entered = input(prompt).strip()
        return entered or (default or "")

    server_url = pick("SERVER_URL", "server_url",
                      "Server URL (e.g. https://10ax.online.tableau.com): ").rstrip("/")
    site_name = pick("SITE_NAME", "site_name", "Site content URL: ")
    pat_name = pick("PAT_NAME", "pat_name", "PAT name: ")
    pat_secret = pick("PAT_SECRET", "pat_secret", "PAT secret (hidden): ", secret=True)
    return server_url, site_name, pat_name, pat_secret


# ── Preflight ─────────────────────────────────────────────────────────────────────
def preflight(server, server_url, token):
    """Fail early with plain-language guidance rather than deep in the run."""
    # Site role: Admin Insights sources and Pulse creation normally need Site Administrator.
    try:
        me = server.users.get_by_id(server.user_id)
        role = getattr(me, "site_role", "") or ""
        if "Administrator" not in role:
            print(f"  Warning: your site role is '{role}'. Admin Insights sources and Pulse "
                  "metric creation usually require Site Administrator; the run may not resolve "
                  "sources or may be denied.")
    except Exception:
        pass  # role check is best-effort, never fatal

    # Pulse reachable / enabled.
    r = requests.get(f"{server_url}/api/-/pulse/definitions",
                     headers={"x-tableau-auth": token, "Accept": "application/json"},
                     params={"page_size": 1})
    if r.status_code == 404:
        sys.exit("  Pulse REST is not available on this site. Confirm Pulse is enabled and the "
                 "site is on a recent Tableau Cloud version (Pulse REST is ~3.24+).")
    r.raise_for_status()


# ── Field resolution (VizQL Data Service) ─────────────────────────────────────────
def read_vds_field_map(server_url, token, luid):
    """caption -> internal fieldName for every field on the datasource (columns AND calcs)."""
    r = requests.post(f"{server_url}/api/v1/vizql-data-service/read-metadata",
                      headers={"x-tableau-auth": token, "Content-Type": "application/json",
                               "Accept": "application/json"},
                      json={"datasource": {"datasourceLuid": luid}})
    if r.status_code in (403, 404):
        sys.exit("  Could not read datasource metadata. Confirm the VizQL Data Service is enabled "
                 f"on this site (Settings). ({r.status_code})")
    r.raise_for_status()
    return {f["fieldCaption"]: f["fieldName"] for f in r.json().get("data", []) if f.get("fieldCaption")}


def vds_filter_value_count(server_url, token, luid, caption, values):
    """Count rows where `caption` is in `values`. Used to validate confirm:true filters."""
    body = {"datasource": {"datasourceLuid": luid},
            "query": {"fields": [{"fieldCaption": caption, "function": "COUNT", "fieldAlias": "n"}],
                      "filters": [{"field": {"fieldCaption": caption}, "filterType": "SET",
                                   "values": values, "exclude": False}]}}
    r = requests.post(f"{server_url}/api/v1/vizql-data-service/query-datasource",
                      headers={"x-tableau-auth": token, "Content-Type": "application/json",
                               "Accept": "application/json"}, json=body)
    if not r.ok:
        return None  # validation is advisory; don't fail the run on a query hiccup
    data = r.json().get("data", [])
    return sum(row.get("n", 0) for row in data)


def resolve_source_luids(server, names):
    """Single scan of all datasources. Prefer the Admin Insights project on name collisions.
    Returns (name->luid, name->[(luid, project)] for any name that matched more than once)."""
    want = set(names)
    hits = {}
    for ds in TSC.Pager(server.datasources):
        if ds.name in want:
            hits.setdefault(ds.name, []).append((ds.id, getattr(ds, "project_name", "") or ""))
    luids, ambiguous = {}, {}
    for n in names:
        cands = hits.get(n, [])
        preferred = [c for c in cands if c[1] == ADMIN_INSIGHTS_PROJECT]
        pick = (preferred or cands or [None])[0]
        luids[n] = pick[0] if pick else None
        if len(cands) > 1:
            ambiguous[n] = cands
    return luids, ambiguous


# ── Payload construction + spec signatures ─────────────────────────────────────────
def resolve_metric(metric, fmap, defaults):
    """Translate a caption-authored manifest metric into a Pulse payload. Uses the native
    timezone-adjusted "(local)" calc for the time dimension. Returns (payload, missing_captions,
    unconfirmed_filters). unconfirmed_filters is a list of (caption, [values])."""
    missing = []

    def resolve(cap):
        fn = fmap.get(cap)
        if fn is None:
            missing.append(cap)
        return fn

    measure_field = resolve(metric["measure"]["field"])
    time_field = resolve(f'{metric["time_dimension"]} (local)')

    filters, unconfirmed = [], []
    for filt in metric.get("filters", []):
        ff = resolve(filt["field"])
        filters.append({
            "field": ff,
            "operator": "OPERATOR_EQUAL",
            "categorical_values": [{"string_value": v} for v in filt["include"]],
        })
        if filt.get("confirm"):
            unconfirmed.append((filt["field"], filt["include"]))

    dims = [resolve(d) for d in metric.get("adjustable_dimensions", [])]

    payload = {
        "name": metric["name"],
        "specification": {
            "datasource": {"id": metric["_luid"]},
            "basic_specification": {
                "measure": {"field": measure_field, "aggregation": metric["measure"]["aggregation"]},
                "time_dimension": {"field": time_field},
                "filters": filters,
            },
            "is_running_total": False,
        },
        "extension_options": {
            "allowed_dimensions": dims,
            "allowed_granularities": GRANULARITIES,
            "offset_from_today": defaults.get("offset_from_today", 1),
        },
        "representation_options": {
            "type": metric.get("number_format", "NUMBER_FORMAT_TYPE_NUMBER"),
            "sentiment_type": metric["sentiment"],
        },
        "insights_options": {"show_insights": defaults.get("show_insights", True)},
        "comparisons": {"comparisons": [
            {"compare_config": {"comparison": defaults.get("comparison", "TIME_COMPARISON_PREVIOUS_PERIOD")},
             "index": 0}
        ]},
        "datasource_goals": [],
    }
    if metric.get("temporality"):
        payload["specification"]["temporality"] = metric["temporality"]
    return payload, missing, unconfirmed


def _filter_values(f):
    cv = [c.get("string_value") for c in f.get("categorical_values", []) if c.get("string_value") is not None]
    if cv:
        return tuple(sorted(cv))
    return tuple(sorted(str(v) for v in f.get("values", [])))


def spec_signature(specification):
    """A comparable identity for a definition's spec. Pulse dedups on this, not on name."""
    ds = (specification.get("datasource") or {}).get("id")
    bs = specification.get("basic_specification") or {}
    measure = bs.get("measure") or {}
    time_dim = bs.get("time_dimension") or {}
    filters = tuple(sorted(
        (f.get("field"), f.get("operator"), _filter_values(f))
        for f in bs.get("filters", [])
    ))
    return (ds, measure.get("field"), measure.get("aggregation"), time_dim.get("field"), filters)


# ── Pulse read helpers ──────────────────────────────────────────────────────────
def list_existing_definitions(server_url, token):
    """Every Pulse definition on the site (all pages), with name, description, and signature."""
    out, page_token = [], None
    while True:
        params = {"page_size": 100, "view": "DEFINITION_VIEW_FULL"}
        if page_token:
            params["page_token"] = page_token
        r = requests.get(f"{server_url}/api/-/pulse/definitions",
                         headers={"x-tableau-auth": token, "Accept": "application/json"},
                         params=params)
        r.raise_for_status()
        body = r.json()
        for d in body.get("definitions", []):
            meta = d.get("metadata", {})
            out.append({"id": meta.get("id"), "name": meta.get("name"),
                        "description": meta.get("description", ""),
                        "signature": spec_signature(d.get("specification", {}))})
        page_token = body.get("next_page_token")
        if not page_token:
            return out


def read_all_subscriptions(server_url, token):
    out, page_token = [], None
    while True:
        params = {"page_size": 100}
        if page_token:
            params["page_token"] = page_token
        r = requests.get(f"{server_url}/api/-/pulse/subscriptions",
                         headers={"x-tableau-auth": token, "Accept": "application/json"},
                         params=params)
        r.raise_for_status()
        body = r.json()
        out.extend(body.get("subscriptions", []))
        page_token = body.get("next_page_token")
        if not page_token:
            return out


def default_metric_for_definition(server_url, token, def_id):
    """The full default metric dict for a definition (the one the group/user follows)."""
    r = requests.get(f"{server_url}/api/-/pulse/definitions/{def_id}/metrics",
                     headers={"x-tableau-auth": token, "Accept": "application/json"})
    r.raise_for_status()
    metrics = r.json().get("metrics", [])
    if not metrics:
        return None
    return next((m for m in metrics if m.get("is_default")), metrics[0])


def sibling_metric_with_period(server_url, token, def_id, granularity, range_):
    """A non-default metric on the definition that already sits on the target period, if any."""
    r = requests.get(f"{server_url}/api/-/pulse/definitions/{def_id}/metrics",
                     headers={"x-tableau-auth": token, "Accept": "application/json"})
    r.raise_for_status()
    for m in r.json().get("metrics", []):
        mp = m.get("specification", {}).get("measurement_period", {})
        if mp.get("granularity") == granularity and mp.get("range") == range_ \
                and not m.get("specification", {}).get("filters"):
            return m
    return None


def definition_id_for_metric(server_url, token, metric_id):
    r = requests.get(f"{server_url}/api/-/pulse/metrics/{metric_id}",
                     headers={"x-tableau-auth": token, "Accept": "application/json"})
    if not r.ok:
        return None
    return r.json().get("metric", {}).get("definition_id")


# ── Pulse write helpers ───────────────────────────────────────────────────────────
def set_definition_description(server_url, token, def_id, description):
    r = requests.patch(f"{server_url}/api/-/pulse/definitions/{def_id}",
                       headers={"x-tableau-auth": token, "Content-Type": "application/json",
                                "Accept": "application/json"},
                       params={"update_mask": "description"},
                       json={"description": description})
    return r.ok, ("" if r.ok else f"{r.status_code} {r.text[:120]}")


def set_metric_period(server_url, token, metric, granularity, range_):
    """PATCH a metric's measurement_period, preserving filters and comparison.
    Returns (ok, detail). No-op if already on target."""
    spec = metric.get("specification", {})
    cur = spec.get("measurement_period", {})
    if cur.get("granularity") == granularity and cur.get("range") == range_:
        return True, "already set"
    body = {"specification": {
        "filters": spec.get("filters", []),
        "measurement_period": {"granularity": granularity, "range": range_},
        "comparison": spec.get("comparison", {"comparison": "TIME_COMPARISON_PREVIOUS_PERIOD"}),
    }}
    r = requests.patch(f"{server_url}/api/-/pulse/metrics/{metric['id']}",
                       headers={"x-tableau-auth": token, "Content-Type": "application/json",
                                "Accept": "application/json"},
                       json=body)
    return r.ok, ("ok" if r.ok else f"{r.status_code} {r.text[:120]}")


def create_definition(server_url, token, payload):
    """Returns (definition_dict, status_code, validation_code, text)."""
    r = requests.post(f"{server_url}/api/-/pulse/definitions",
                      headers={"x-tableau-auth": token, "Accept": "application/json",
                               "Content-Type": VND_CREATE},
                      json=payload)
    if r.ok:
        return r.json().get("definition"), r.status_code, None, ""
    return None, r.status_code, r.headers.get("validation_code"), r.text[:160]


def subscribe(server_url, token, metric_id, follower):
    """follower is {"group_id": ...} or {"user_id": ...}. Returns (ok, subscription_id, detail)."""
    r = requests.post(f"{server_url}/api/-/pulse/subscriptions:batchCreate",
                      headers={"x-tableau-auth": token, "Content-Type": "application/json",
                               "Accept": "application/json"},
                      json={"metric_id": metric_id, "followers": [follower]})
    if not r.ok:
        return False, None, r.text[:160]
    subs = r.json().get("subscriptions", [])
    return True, (subs[0].get("id") if subs else None), ""


def delete_definition(server_url, token, def_id):
    r = requests.delete(f"{server_url}/api/-/pulse/definitions/{def_id}",
                        headers={"x-tableau-auth": token, "Accept": "application/json"})
    return r.status_code


def delete_subscription(server_url, token, sub_id):
    r = requests.delete(f"{server_url}/api/-/pulse/subscriptions/{sub_id}",
                        headers={"x-tableau-auth": token, "Accept": "application/json"})
    return r.status_code


def find_group(server, name):
    for g in TSC.Pager(server.groups):
        if g.name == name:
            return g
    return None


def create_or_reuse_group(server, name):
    """Returns (group_id, created_bool)."""
    g = find_group(server, name)
    if g:
        return g.id, False
    created = server.groups.create(TSC.GroupItem(name))
    return created.id, True


# ── Deploy ──────────────────────────────────────────────────────────────────────
def do_deploy(server, server_url, token, ir, args):
    metrics = ir["metrics"]
    defaults = ir["pack"].get("defaults", {})
    sources = sorted({m["source"] for m in metrics})

    preflight(server, server_url, token)

    print("\n[1/4] Resolving Admin Insights sources...")
    luids, ambiguous = resolve_source_luids(server, sources)
    for name in sources:
        print(f"      {name:18s} -> {luids[name] or 'NOT FOUND'}")
    for name, cands in ambiguous.items():
        print(f"      ! '{name}' matched {len(cands)} datasources; using the one in the "
              f"'{ADMIN_INSIGHTS_PROJECT}' project if present. Candidates: "
              + ", ".join(f"{cid} ({proj or 'no project'})" for cid, proj in cands))
    if not all(luids.values()):
        sys.exit("\n  Some sources did not resolve. Confirm Admin Insights is enabled and the "
                 "PAT user is a Site Admin.")

    print("\n[2/4] Reading field maps (VizQL Data Service)...")
    fmaps = {name: read_vds_field_map(server_url, token, luids[name]) for name in sources}
    for name in sources:
        print(f"      {name:18s} -> {len(fmaps[name])} fields")

    print("\n[3/4] Building plan...")
    existing = list_existing_definitions(server_url, token)
    by_name = {}
    for rec in existing:
        by_name.setdefault(rec["name"], []).append(rec)
    by_sig = {rec["signature"]: rec for rec in existing}

    plan, blocked = [], False
    for m in metrics:
        m["_luid"] = luids[m["source"]]
        payload, missing, unconfirmed = resolve_metric(m, fmaps[m["source"]], defaults)
        sig = spec_signature(payload["specification"])

        if missing:
            action, target = "UNRESOLVED", None
            blocked = True
        else:
            name_recs = by_name.get(m["name"], [])
            same_name_same_spec = next((r for r in name_recs if r["signature"] == sig), None)
            if same_name_same_spec:
                action, target = "adopt", same_name_same_spec        # our metric already present
            elif name_recs:
                action, target = "conflict", name_recs[0]            # our name, different spec
            elif sig in by_sig:
                action, target = "adopt-renamed", by_sig[sig]        # our spec under another name
            else:
                action, target = "create", None
        plan.append({"metric": m, "payload": payload, "action": action, "target": target,
                     "missing": missing, "unconfirmed": unconfirmed, "signature": sig})

        note = ""
        if missing:
            note = f"  !! unresolved captions: {', '.join(missing)}"
        elif action == "conflict":
            note = f"  !! name exists with a DIFFERENT spec ({target['id']}); will skip"
        elif action == "adopt-renamed":
            note = f"  (same spec already exists as '{target['name']}'; will adopt + follow)"
        elif action == "adopt":
            note = "  (already present; will adopt)"
        elif unconfirmed:
            note = "  (filter values to confirm: " + \
                   "; ".join(f"{c} in {v}" for c, v in unconfirmed) + ")"
        print(f"      [{action:13s}] {m['name']:26s} {m['source']}{note}")

    if blocked:
        sys.exit("\n  Some field captions did not resolve on this site (likely a non-English or "
                 "customized Admin Insights schema). Nothing was written. Fix the manifest or "
                 "map the captions for this locale before deploying.")

    conflicts = [p for p in plan if p["action"] == "conflict"]
    if conflicts and args.on_conflict == "skip":
        print(f"\n  Note: {len(conflicts)} name(s) already exist with a different spec and will be "
              "SKIPPED. Re-run with --on-conflict suffix to create those under a distinct name.")

    if args.dry_run:
        grans = sorted({m.get("default_granularity", "GRANULARITY_BY_WEEK") for m in metrics})
        print(f"\n  Followed metric period would be set to: {', '.join(grans)} + {DEFAULT_RANGE}.")
        # Validate confirm:true filter values against live data.
        checked = False
        for p in plan:
            for cap, vals in p["unconfirmed"]:
                checked = True
                n = vds_filter_value_count(server_url, token, p["metric"]["_luid"], cap, vals)
                flag = "  <-- 0 rows; this metric will read empty" if n == 0 else ""
                print(f"  filter check: {p['metric']['name']}: {cap} in {vals} -> "
                      f"{'?' if n is None else n} rows{flag}")
        if not checked:
            print("  (no confirm:true filters to validate)")
        print("\n  --dry-run: no writes made. Plan above is what a real run would do.")
        return

    # Prior ownership: only definitions this tool CREATED are ever edited or deleted later.
    prev = load_state(server.site_id)
    prev_owned = {r["name"]: r.get("created", False) for r in (prev or {}).get("definitions", [])}
    prev_group_created = bool(((prev or {}).get("group") or {}).get("created"))

    print("\n[4/4] Creating definitions...")
    records = []
    for p in plan:
        m, payload, action, target = p["metric"], p["payload"], p["action"], p["target"]
        if action == "conflict":
            if args.on_conflict == "suffix":
                payload = dict(payload, name=f'{m["name"]} (Admin Insights)')
                action = "create"
            else:
                print(f"      skip (conflict) {m['name']}")
                continue

        adopted = False
        if action == "create":
            definition, code, vc, text = create_definition(server_url, token, payload)
            if definition:
                def_id = definition["metadata"]["id"]
                created = True
                print(f"      created {payload['name']}  ({def_id})")
            elif code == 409 and p["signature"] in by_sig:
                # Spec already exists (possibly under a different name we hadn't matched). Adopt it.
                def_id = by_sig[p["signature"]]["id"]
                created, adopted = False, True
                print(f"      adopt (spec exists) {m['name']}  ({def_id})")
            else:
                print(f"      ERROR {m['name']}: {code} vc={vc} {text}")
                continue
        else:  # adopt / adopt-renamed
            def_id = target["id"]
            created = prev_owned.get(m["name"], False)
            adopted = not created
            print(f"      adopt {m['name']}  ({def_id})")

        owned = created or prev_owned.get(m["name"], False)

        # Only edit definitions this tool owns. Never mutate a customer's pre-existing metric.
        if owned and m.get("description"):
            cur_desc = (target or {}).get("description", "") if action != "create" else ""
            if m["description"] != cur_desc:
                ok, detail = set_definition_description(server_url, token, def_id, m["description"])
                if not ok:
                    print(f"        set description {m['name']}: {detail}")

        dm = default_metric_for_definition(server_url, token, def_id)
        metric_id = dm["id"] if dm else None
        gran = m.get("default_granularity")
        follow_metric_id = metric_id
        if owned and dm and gran:
            rng = m.get("default_range") or defaults.get("default_range", DEFAULT_RANGE)
            ok, detail = set_metric_period(server_url, token, dm, gran, rng)
            if not ok:
                # A sibling metric already holds the target period (spec dedup). Follow that one.
                sib = sibling_metric_with_period(server_url, token, def_id, gran, rng)
                if sib:
                    follow_metric_id = sib["id"]
                    print(f"        note {m['name']}: default stays monthly; following the "
                          f"existing {gran} metric instead")
                else:
                    print(f"        set period {m['name']}: {detail}")

        records.append({"key": m["key"], "name": m["name"], "source": m["source"],
                        "definition_id": def_id, "metric_id": follow_metric_id,
                        "created": created, "adopted": adopted, "group_subscription_id": None})

    group_record = None
    if args.group:
        print(f"\n[group] Create-or-reuse group '{args.group}'...")
        group_id, group_created = create_or_reuse_group(server, args.group)
        print(f"        group_id={group_id} ({'created' if group_created else 'reused'})")
        subbed = 0
        for rec in records:
            if not rec["metric_id"]:
                continue
            ok, sub_id, detail = subscribe(server_url, token, rec["metric_id"], {"group_id": group_id})
            if ok:
                subbed += 1
                rec["group_subscription_id"] = sub_id
            else:
                print(f"        subscribe {rec['name']}: FAILED {detail}")
        print(f"        group following {subbed}/{len(records)} metrics")
        group_record = {"name": args.group, "id": group_id,
                        "created": group_created or prev_group_created}

    if args.follow:
        user_id = server.user_id
        print(f"\n[follow] Subscribing running user ({user_id}) to all metrics...")
        subbed = 0
        for rec in records:
            if not rec["metric_id"]:
                continue
            ok, _sid, detail = subscribe(server_url, token, rec["metric_id"], {"user_id": user_id})
            subbed += 1 if ok else 0
            if not ok:
                print(f"        subscribe {rec['name']}: FAILED {detail}")
        print(f"        user following {subbed}/{len(records)} metrics")

    state = {
        "pack": ir["pack"]["name"],
        "version": ir["pack"]["version"],
        "server": server_url,
        "site": server.site_id,
        "site_name": args.site_name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "definitions": records,
        "group": group_record,
        "user_followed": server.user_id if args.follow else None,
    }
    save_state(server.site_id, state)
    print(f"\n  Wrote {state_path(server.site_id)}. Created "
          f"{sum(1 for r in records if r['created'])} new, "
          f"{sum(1 for r in records if r['adopted'])} adopted, "
          f"{len(conflicts) if args.on_conflict == 'skip' else 0} skipped (name conflict).")
    print("  Allow 2-3 minutes for Pulse to index new metrics before they populate.")


# ── State ───────────────────────────────────────────────────────────────────────
def load_state(site_id):
    path = state_path(site_id)
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    if os.path.exists(LEGACY_STATE_PATH):  # migrate old single-site file if it matches this site
        with open(LEGACY_STATE_PATH) as f:
            legacy = json.load(f)
        if legacy.get("site") == site_id:
            return legacy
    return None


def save_state(site_id, state):
    with open(state_path(site_id), "w") as f:
        json.dump(state, f, indent=2)


# ── Uninstall ─────────────────────────────────────────────────────────────────────
def do_uninstall(server, server_url, token, args):
    state = load_state(server.site_id)
    if state:
        if state.get("site") and state["site"] != server.site_id and not args.force:
            sys.exit(f"  Refusing to uninstall: state was recorded for site {state['site']} but "
                     f"you are signed in to {server.site_id}. Re-run with --force to override.")
        _uninstall_from_state(server, server_url, token, state, args)
    else:
        _uninstall_by_discovery(server, server_url, token, args)


def _uninstall_from_state(server, server_url, token, state, args):
    defs = state.get("definitions", [])
    to_delete = [r for r in defs if r.get("created")]
    to_unfollow = [r for r in defs if not r.get("created") and r.get("group_subscription_id")]
    grp = state.get("group")

    print("\n[uninstall] Plan (precise, from state file):")
    for r in to_delete:
        print(f"      delete definition  {r['name']}  ({r['definition_id']})")
    for r in to_unfollow:
        print(f"      unfollow (adopted) {r['name']}  (sub {r['group_subscription_id']})")
    for r in defs:
        if not r.get("created") and not r.get("group_subscription_id"):
            print(f"      keep (pre-existing) {r['name']}")
    if grp and grp.get("created"):
        print(f"      delete group '{grp['name']}'  ({grp['id']})")
    elif grp:
        print(f"      keep (pre-existing) group '{grp['name']}'")

    if args.dry_run:
        print("\n  --dry-run: no deletions made.")
        return

    removed = 0
    for r in to_delete:
        code = delete_definition(server_url, token, r["definition_id"])
        removed += 1 if code in (200, 204) else 0
        print(f"      delete {r['name']}: {code}")
    for r in to_unfollow:
        code = delete_subscription(server_url, token, r["group_subscription_id"])
        print(f"      unfollow {r['name']}: {code}")
    if grp and grp.get("created"):
        r = requests.delete(f"{server.baseurl}/sites/{server.site_id}/groups/{grp['id']}",
                            headers={"x-tableau-auth": token})
        print(f"      delete group '{grp['name']}': {r.status_code}")

    os.remove(state_path(server.site_id))
    print(f"\n  Removed {removed} definition(s). Deleting a definition also removes its metrics "
          "and subscriptions.")


def _uninstall_by_discovery(server, server_url, token, args):
    """No state file. Rediscover the pack from the group that follows its metrics."""
    name = args.group or DEFAULT_GROUP_NAME
    print(f"\n[uninstall] No state file for this site. Discovering via group '{name}'...")
    g = find_group(server, name)
    if not g:
        sys.exit(f"  Group '{name}' not found. Nothing to discover. If you installed without a "
                 "group, cleanup requires the original state file.")

    subs = [s for s in read_all_subscriptions(server_url, token)
            if (s.get("follower") or {}).get("group_id") == g.id]
    def_ids, sub_ids = {}, []
    for s in subs:
        sub_ids.append(s["id"])
        did = definition_id_for_metric(server_url, token, s["metric_id"])
        if did:
            def_ids[did] = s["metric_id"]

    print(f"  Group '{name}' follows {len(sub_ids)} metric(s) across {len(def_ids)} definition(s).")
    print("  WARNING: discovery cannot tell which definitions this tool created versus ones it "
          "merely adopted. Deleting will remove ALL definitions the group follows.")
    for did in def_ids:
        print(f"      would delete definition {did}")
    print(f"      would delete group '{name}' ({g.id})")

    if args.dry_run:
        print("\n  --dry-run: no deletions made.")
        return
    if not args.yes:
        ans = input("\n  Type 'delete' to remove the above, anything else to abort: ").strip()
        if ans != "delete":
            sys.exit("  Aborted. Nothing deleted.")

    for did in def_ids:
        print(f"      delete definition {did}: {delete_definition(server_url, token, did)}")
    r = requests.delete(f"{server.baseurl}/sites/{server.site_id}/groups/{g.id}",
                        headers={"x-tableau-auth": token})
    print(f"      delete group '{name}': {r.status_code}")
    print("\n  Discovery cleanup complete.")


# ── Main ────────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="Deploy the Pulse Admin Insights Starter Pack.")
    ap.add_argument("--dry-run", action="store_true", help="show the plan (and validate filters), write nothing")
    ap.add_argument("--follow", action="store_true", help="subscribe the running user to every metric")
    ap.add_argument("--group", metavar="NAME", nargs="?", const=DEFAULT_GROUP_NAME,
                    help=f"create-or-reuse this group and subscribe it to every metric "
                         f"(default name: '{DEFAULT_GROUP_NAME}')")
    ap.add_argument("--on-conflict", choices=["skip", "suffix"], default="skip",
                    help="when a name exists with a DIFFERENT spec: skip it (default) or create "
                         "ours under a suffixed name")
    ap.add_argument("--uninstall", action="store_true", help="delete only what a prior run created")
    ap.add_argument("--yes", action="store_true", help="skip the confirmation prompt on discovery uninstall")
    ap.add_argument("--force", action="store_true", help="override the site-match guard on uninstall")
    args = ap.parse_args()

    with open(IR_PATH) as f:
        ir = json.load(f)

    server_url, site_name, pat_name, pat_secret = load_connection()
    args.site_name = site_name
    print(f"\nSigning in to {server_url} / {site_name} ...")
    auth = TSC.PersonalAccessTokenAuth(pat_name, pat_secret, site_id=site_name)
    server = TSC.Server(server_url, use_server_version=True)
    try:
        server.auth.sign_in(auth)
    except Exception as e:
        sys.exit(f"  Sign-in failed: {e}\n  Check: PAT name is exact (case/spaces), the site "
                 "CONTENT URL (not display name), and the correct pod URL.")
    token = server.auth_token
    print(f"  Connected (REST {server.version}).")

    try:
        if args.uninstall:
            do_uninstall(server, server_url, token, args)
        else:
            do_deploy(server, server_url, token, ir, args)
    finally:
        server.auth.sign_out()


if __name__ == "__main__":
    main()
