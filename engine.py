#!/usr/bin/env python3
"""
engine.py — shared logic for the Pulse Admin Insights Starter Pack.

Both front ends use this module:
  - deploy.py  (command line)
  - app.py     (local web GUI)

Design:
  - No printing and no sys.exit in here. Functions return structured results and raise
    EngineError (with a plain-language message) on anything the caller should surface to a user.
  - Progress is reported through an optional `log(msg)` callback so a CLI can print it and the
    web app can stream it. Defaults to a no-op.
  - The safety guarantees live here, so both front ends inherit them identically: only ever
    CREATE net-new definitions, never edit a definition this tool didn't create, match by name
    AND full specification (Pulse dedups on spec), dry-run writes nothing, uninstall removes only
    what a prior run created.
"""

import json
import os
from datetime import datetime, timezone

import requests
import tableauserverclient as TSC

HERE = os.path.dirname(os.path.abspath(__file__))
IR_PATH = os.path.join(HERE, "metrics.manifest.json")       # committed IR (the metric catalog)
LEGACY_STATE_PATH = os.path.join(HERE, "manifest.json")     # old single-site state (still readable)

GRANULARITIES = ["GRANULARITY_BY_DAY", "GRANULARITY_BY_WEEK", "GRANULARITY_BY_MONTH",
                 "GRANULARITY_BY_QUARTER", "GRANULARITY_BY_YEAR"]
DEFAULT_RANGE = "RANGE_CURRENT_PARTIAL"   # "to date": current, still-in-progress period
DEFAULT_GROUP_NAME = "Admin Insights Metrics"
ADMIN_INSIGHTS_PROJECT = "Admin Insights"
VND_CREATE = "application/vnd.tableau.metricqueryservice.v1.CreateDefinitionRequest+json"

# Every network call carries this so a stalled connection surfaces as a real error
# instead of hanging the deploy thread forever. (connect timeout, read timeout)
HTTP_TIMEOUT = (10, 30)


def _noop(_msg):
    pass


class EngineError(Exception):
    """A user-facing failure. `message` is plain language; `hint` is optional next-step guidance."""
    def __init__(self, message, hint=""):
        super().__init__(message)
        self.message = message
        self.hint = hint


def state_path(site_id):
    """Per-site runtime state file, so deploying to multiple sites never clobbers records."""
    return os.path.join(HERE, f"manifest.{site_id}.json")


def load_ir():
    with open(IR_PATH) as f:
        return json.load(f)


# ── Connection ──────────────────────────────────────────────────────────────────
def sign_in(server_url, site_name, pat_name, pat_secret):
    """Sign in with a PAT. Returns a signed-in TSC.Server. Raises EngineError on failure."""
    server_url = (server_url or "").strip().rstrip("/")
    site_name = (site_name or "").strip()
    auth = TSC.PersonalAccessTokenAuth(pat_name.strip(), pat_secret.strip(), site_id=site_name)
    server = TSC.Server(server_url, use_server_version=True)
    try:
        server.auth.sign_in(auth)
    except Exception as e:
        raise EngineError(
            "Sign-in failed. " + str(e),
            hint="Check three things: the token name matches exactly what you typed in Tableau "
                 "(capitals and spaces count), the site name is the word after /site/ in your "
                 "Tableau web address (not the display name), and the web address is your real pod "
                 "(the part ending in .online.tableau.com). Tokens also expire after a period of no "
                 "use; if in doubt, create a fresh one.")
    return server


# ── Preflight ─────────────────────────────────────────────────────────────────────
def preflight(server, server_url, token, log=_noop):
    """Returns a list of non-fatal warning strings. Raises EngineError if Pulse is unavailable."""
    warnings = []
    try:
        me = server.users.get_by_id(server.user_id)
        role = getattr(me, "site_role", "") or ""
        if "Administrator" not in role:
            warnings.append(
                f"Your site role is '{role}'. Admin Insights sources and Pulse metric creation "
                "usually require Site Administrator; the run may not resolve sources or may be denied.")
    except Exception:
        pass  # role check is best-effort, never fatal

    r = requests.get(f"{server_url}/api/-/pulse/definitions",
                     headers={"x-tableau-auth": token, "Accept": "application/json"},
                     params={"page_size": 1}, timeout=HTTP_TIMEOUT)
    if r.status_code == 404:
        raise EngineError(
            "Tableau Pulse is not available on this site.",
            hint="Confirm Pulse is enabled for the site (Settings). If it is enabled and you still "
                 "see this, the site may be on an older version than Pulse's API requires.")
    r.raise_for_status()
    for w in warnings:
        log("Warning: " + w)
    return warnings


# ── Field resolution (VizQL Data Service) ─────────────────────────────────────────
def read_vds_field_map(server_url, token, luid):
    """caption -> internal fieldName for every field on the datasource (columns AND calcs)."""
    r = requests.post(f"{server_url}/api/v1/vizql-data-service/read-metadata",
                      headers={"x-tableau-auth": token, "Content-Type": "application/json",
                               "Accept": "application/json"},
                      json={"datasource": {"datasourceLuid": luid}}, timeout=HTTP_TIMEOUT)
    if r.status_code in (403, 404):
        raise EngineError(
            "Could not read the data source fields.",
            hint="Confirm the VizQL Data Service is enabled on this site (Settings), then try again.")
    r.raise_for_status()
    return {f["fieldCaption"]: f["fieldName"] for f in r.json().get("data", []) if f.get("fieldCaption")}


def vds_filter_value_count(server_url, token, luid, caption, values):
    """Count rows where `caption` is in `values`. Used to validate confirm:true filters.
    Returns an int, or None if the query itself hiccuped (validation is advisory)."""
    body = {"datasource": {"datasourceLuid": luid},
            "query": {"fields": [{"fieldCaption": caption, "function": "COUNT", "fieldAlias": "n"}],
                      "filters": [{"field": {"fieldCaption": caption}, "filterType": "SET",
                                   "values": values, "exclude": False}]}}
    r = requests.post(f"{server_url}/api/v1/vizql-data-service/query-datasource",
                      headers={"x-tableau-auth": token, "Content-Type": "application/json",
                               "Accept": "application/json"}, json=body, timeout=HTTP_TIMEOUT)
    if not r.ok:
        return None
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
    """Translate a caption-authored manifest metric into a Pulse payload. Returns
    (payload, missing_captions, unconfirmed_filters). unconfirmed is a list of (caption, [values])."""
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
                         params=params, timeout=HTTP_TIMEOUT)
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
                         params=params, timeout=HTTP_TIMEOUT)
        r.raise_for_status()
        body = r.json()
        out.extend(body.get("subscriptions", []))
        page_token = body.get("next_page_token")
        if not page_token:
            return out


def default_metric_for_definition(server_url, token, def_id):
    """The full default metric dict for a definition (the one the group/user follows)."""
    r = requests.get(f"{server_url}/api/-/pulse/definitions/{def_id}/metrics",
                     headers={"x-tableau-auth": token, "Accept": "application/json"}, timeout=HTTP_TIMEOUT)
    r.raise_for_status()
    metrics = r.json().get("metrics", [])
    if not metrics:
        return None
    return next((m for m in metrics if m.get("is_default")), metrics[0])


def sibling_metric_with_period(server_url, token, def_id, granularity, range_):
    """A non-default metric on the definition that already sits on the target period, if any."""
    r = requests.get(f"{server_url}/api/-/pulse/definitions/{def_id}/metrics",
                     headers={"x-tableau-auth": token, "Accept": "application/json"}, timeout=HTTP_TIMEOUT)
    r.raise_for_status()
    for m in r.json().get("metrics", []):
        mp = m.get("specification", {}).get("measurement_period", {})
        if mp.get("granularity") == granularity and mp.get("range") == range_ \
                and not m.get("specification", {}).get("filters"):
            return m
    return None


def definition_id_for_metric(server_url, token, metric_id):
    r = requests.get(f"{server_url}/api/-/pulse/metrics/{metric_id}",
                     headers={"x-tableau-auth": token, "Accept": "application/json"}, timeout=HTTP_TIMEOUT)
    if not r.ok:
        return None
    return r.json().get("metric", {}).get("definition_id")


# ── Pulse write helpers ───────────────────────────────────────────────────────────
def set_definition_description(server_url, token, def_id, description):
    r = requests.patch(f"{server_url}/api/-/pulse/definitions/{def_id}",
                       headers={"x-tableau-auth": token, "Content-Type": "application/json",
                                "Accept": "application/json"},
                       params={"update_mask": "description"},
                       json={"description": description}, timeout=HTTP_TIMEOUT)
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
                       json=body, timeout=HTTP_TIMEOUT)
    return r.ok, ("ok" if r.ok else f"{r.status_code} {r.text[:120]}")


def create_definition(server_url, token, payload):
    """Returns (definition_dict, status_code, validation_code, text)."""
    r = requests.post(f"{server_url}/api/-/pulse/definitions",
                      headers={"x-tableau-auth": token, "Accept": "application/json",
                               "Content-Type": VND_CREATE},
                      json=payload, timeout=HTTP_TIMEOUT)
    if r.ok:
        return r.json().get("definition"), r.status_code, None, ""
    return None, r.status_code, r.headers.get("validation_code"), r.text[:160]


def subscribe(server_url, token, metric_id, follower):
    """follower is {"group_id": ...} or {"user_id": ...}. Returns (ok, subscription_id, detail)."""
    r = requests.post(f"{server_url}/api/-/pulse/subscriptions:batchCreate",
                      headers={"x-tableau-auth": token, "Content-Type": "application/json",
                               "Accept": "application/json"},
                      json={"metric_id": metric_id, "followers": [follower]}, timeout=HTTP_TIMEOUT)
    if not r.ok:
        return False, None, r.text[:160]
    subs = r.json().get("subscriptions", [])
    return True, (subs[0].get("id") if subs else None), ""


def delete_definition(server_url, token, def_id):
    r = requests.delete(f"{server_url}/api/-/pulse/definitions/{def_id}",
                        headers={"x-tableau-auth": token, "Accept": "application/json"}, timeout=HTTP_TIMEOUT)
    return r.status_code


def delete_subscription(server_url, token, sub_id):
    r = requests.delete(f"{server_url}/api/-/pulse/subscriptions/{sub_id}",
                        headers={"x-tableau-auth": token, "Accept": "application/json"}, timeout=HTTP_TIMEOUT)
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


# ── Plan (read-only) ──────────────────────────────────────────────────────────────
def build_plan(server, server_url, token, ir, log=_noop):
    """Resolve sources and fields, then classify every metric as create / adopt / adopt-renamed /
    conflict / UNRESOLVED. Read-only: makes no writes. Returns a plan dict the caller can display
    and hand to execute_deploy(). Raises EngineError on a blocking problem."""
    metrics = ir["metrics"]
    defaults = ir["pack"].get("defaults", {})
    sources = sorted({m["source"] for m in metrics})

    warnings = preflight(server, server_url, token, log=log)

    log("Resolving Admin Insights sources...")
    luids, ambiguous = resolve_source_luids(server, sources)
    for name in sources:
        log(f"  {name:18s} -> {luids[name] or 'NOT FOUND'}")
    ambiguities = []
    for name, cands in ambiguous.items():
        ambiguities.append({"name": name,
                            "candidates": [{"id": cid, "project": proj or ""} for cid, proj in cands]})
        log(f"  ! '{name}' matched {len(cands)} datasources; using the one in the "
            f"'{ADMIN_INSIGHTS_PROJECT}' project if present.")
    if not all(luids.values()):
        raise EngineError(
            "Some Admin Insights data sources could not be found on this site.",
            hint="Confirm Admin Insights is enabled for the site, and that the signed-in user is a "
                 "Site Administrator so the sources are visible.")

    log("Reading field maps (VizQL Data Service)...")
    fmaps = {name: read_vds_field_map(server_url, token, luids[name]) for name in sources}
    field_counts = {name: len(fmaps[name]) for name in sources}

    log("Building plan...")
    existing = list_existing_definitions(server_url, token)
    by_name = {}
    for rec in existing:
        by_name.setdefault(rec["name"], []).append(rec)
    by_sig = {rec["signature"]: rec for rec in existing}

    items, blocked = [], False
    for m in metrics:
        m["_luid"] = luids[m["source"]]
        payload, missing, unconfirmed = resolve_metric(m, fmaps[m["source"]], defaults)
        sig = spec_signature(payload["specification"])

        target = None
        if missing:
            action = "UNRESOLVED"
            blocked = True
        else:
            name_recs = by_name.get(m["name"], [])
            same = next((r for r in name_recs if r["signature"] == sig), None)
            if same:
                action, target = "adopt", same
            elif name_recs:
                action, target = "conflict", name_recs[0]
            elif sig in by_sig:
                action, target = "adopt-renamed", by_sig[sig]
            else:
                action = "create"

        items.append({
            "key": m["key"], "name": m["name"], "source": m["source"],
            "cluster": m.get("cluster", ""), "why": m.get("why", ""),
            "description": m.get("description", ""),
            "action": action,
            "target_id": (target or {}).get("id"),
            "target_name": (target or {}).get("name"),
            "target_description": (target or {}).get("description", ""),
            "missing": missing,
            "unconfirmed": [{"field": c, "values": v} for c, v in unconfirmed],
            "luid": m["_luid"],
            # internal (not for JSON serialization to a browser):
            "_payload": payload, "_signature": sig, "_metric": m,
        })
        log(f"  [{action:13s}] {m['name']}")

    return {
        "sources": [{"name": n, "luid": luids[n]} for n in sources],
        "ambiguities": ambiguities,
        "field_counts": field_counts,
        "items": items,
        "blocked": blocked,
        "warnings": warnings,
        "granularities": sorted({m.get("default_granularity", "GRANULARITY_BY_WEEK") for m in metrics}),
        "default_range": DEFAULT_RANGE,
        # internal:
        "_by_sig": by_sig,
    }


def validate_filters(server_url, token, plan, log=_noop):
    """Run the confirm:true filter row-count checks. Returns a list of result dicts."""
    results = []
    for it in plan["items"]:
        for uc in it["unconfirmed"]:
            n = vds_filter_value_count(server_url, token, it["luid"], uc["field"], uc["values"])
            empty = (n == 0)
            results.append({"metric": it["name"], "field": uc["field"], "values": uc["values"],
                            "rows": n, "empty": empty})
            flag = "  <-- 0 rows; this metric will read empty" if empty else ""
            log(f"  filter check: {it['name']}: {uc['field']} in {uc['values']} -> "
                f"{'?' if n is None else n} rows{flag}")
    return results


# ── Execute deploy ──────────────────────────────────────────────────────────────
def execute_deploy(server, server_url, token, ir, plan, *,
                   group=None, follow=False, on_conflict="skip", site_name="", log=_noop):
    """Create the definitions per `plan`, optionally create/reuse a follow group and subscribe the
    user, set descriptions and the week-to-date period on OWNED definitions only, and write state.
    Returns a summary dict. `plan` must come from build_plan() on the same connection."""
    defaults = ir["pack"].get("defaults", {})
    by_sig = plan["_by_sig"]

    if plan["blocked"]:
        raise EngineError(
            "Some field names could not be resolved on this site.",
            hint="This usually means a non-English or customized Admin Insights schema. Nothing was "
                 "written. The affected metrics are marked UNRESOLVED in the plan.")

    prev = load_state(server.site_id)
    prev_owned = {r["name"]: r.get("created", False) for r in (prev or {}).get("definitions", [])}
    prev_group_created = bool(((prev or {}).get("group") or {}).get("created"))

    log("Creating definitions...")
    records, skipped = [], 0
    for it in plan["items"]:
        m, payload, action, sig = it["_metric"], it["_payload"], it["action"], it["_signature"]

        if action == "conflict":
            if on_conflict == "suffix":
                payload = dict(payload, name=f'{m["name"]} (Admin Insights)')
                action = "create"
            else:
                skipped += 1
                log(f"  skip (name conflict) {m['name']}")
                continue

        adopted = False
        if action == "create":
            definition, code, vc, text = create_definition(server_url, token, payload)
            if definition:
                def_id = definition["metadata"]["id"]
                created = True
                log(f"  created {payload['name']}")
            elif code == 409 and sig in by_sig:
                def_id = by_sig[sig]["id"]
                created, adopted = False, True
                log(f"  reused existing {m['name']}")
            else:
                log(f"  ERROR {m['name']}: {code} {text}")
                continue
        else:  # adopt / adopt-renamed
            def_id = it["target_id"]
            created = prev_owned.get(m["name"], False)
            adopted = not created
            log(f"  reused existing {m['name']}")

        owned = created or prev_owned.get(m["name"], False)

        if owned and m.get("description"):
            cur_desc = it.get("target_description", "") if action != "create" else ""
            if m["description"] != cur_desc:
                log(f"  setting description for {m['name']}...")
                ok, detail = set_definition_description(server_url, token, def_id, m["description"])
                if not ok:
                    log(f"    (could not set description for {m['name']}: {detail})")

        log(f"  fetching default metric for {m['name']}...")
        dm = default_metric_for_definition(server_url, token, def_id)
        metric_id = dm["id"] if dm else None
        gran = m.get("default_granularity")
        follow_metric_id = metric_id
        if owned and dm and gran:
            log(f"  setting period for {m['name']}...")
            rng = m.get("default_range") or defaults.get("default_range", DEFAULT_RANGE)
            ok, detail = set_metric_period(server_url, token, dm, gran, rng)
            if not ok:
                sib = sibling_metric_with_period(server_url, token, def_id, gran, rng)
                if sib:
                    follow_metric_id = sib["id"]

        records.append({"key": m["key"], "name": m["name"], "source": m["source"],
                        "definition_id": def_id, "metric_id": follow_metric_id,
                        "created": created, "adopted": adopted, "group_subscription_id": None})

    group_record = None
    group_followed = 0
    if group:
        log(f"Setting up group '{group}'...")
        group_id, group_created = create_or_reuse_group(server, group)
        for rec in records:
            if not rec["metric_id"]:
                continue
            ok, sub_id, detail = subscribe(server_url, token, rec["metric_id"], {"group_id": group_id})
            if ok:
                group_followed += 1
                rec["group_subscription_id"] = sub_id
            else:
                log(f"  (could not subscribe group to {rec['name']}: {detail})")
        log(f"  group '{group}' now following {group_followed} metric(s)")
        group_record = {"name": group, "id": group_id, "created": group_created or prev_group_created}

    user_followed = 0
    if follow:
        uid = server.user_id
        for rec in records:
            if not rec["metric_id"]:
                continue
            ok, _sid, _d = subscribe(server_url, token, rec["metric_id"], {"user_id": uid})
            user_followed += 1 if ok else 0
        log(f"  you are now following {user_followed} metric(s)")

    state = {
        "pack": ir["pack"]["name"],
        "version": ir["pack"]["version"],
        "server": server_url,
        "site": server.site_id,
        "site_name": site_name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "definitions": records,
        "group": group_record,
        "user_followed": server.user_id if follow else None,
    }
    save_state(server.site_id, state)

    return {
        "created": sum(1 for r in records if r["created"]),
        "adopted": sum(1 for r in records if r["adopted"]),
        "skipped": skipped,
        "group": group_record,
        "group_followed": group_followed,
        "user_followed": user_followed,
        "records": records,
        "state_file": os.path.basename(state_path(server.site_id)),
    }


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
def uninstall_plan(server, server_url, token, *, group=None, force=False, log=_noop):
    """Return a structured plan of what an uninstall would do. Read-only.
    mode == 'state'     : precise, from the per-site state file.
    mode == 'discovery' : no state file; rediscovered from the follow group (cannot tell created
                          from adopted, so it warns and requires explicit confirmation to execute)."""
    state = load_state(server.site_id)
    if state:
        if state.get("site") and state["site"] != server.site_id and not force:
            raise EngineError(
                f"This saved record is for a different site ({state['site']}), but you are signed in "
                f"to {server.site_id}.",
                hint="Sign in to the matching site, or force the uninstall only if you are certain.")
        defs = state.get("definitions", [])
        grp = state.get("group")
        to_delete = [{"name": r["name"], "definition_id": r["definition_id"]}
                     for r in defs if r.get("created")]
        to_unfollow = [{"name": r["name"], "subscription_id": r["group_subscription_id"]}
                       for r in defs if not r.get("created") and r.get("group_subscription_id")]
        to_keep = [{"name": r["name"]} for r in defs
                   if not r.get("created") and not r.get("group_subscription_id")]
        group_action = None
        if grp and grp.get("created"):
            group_action = {"name": grp["name"], "id": grp["id"], "action": "delete"}
        elif grp:
            group_action = {"name": grp["name"], "id": grp["id"], "action": "keep"}
        for r in to_delete:
            log(f"  delete definition  {r['name']}")
        for r in to_unfollow:
            log(f"  unfollow (reused)  {r['name']}")
        return {"mode": "state", "to_delete": to_delete, "to_unfollow": to_unfollow,
                "to_keep": to_keep, "group": group_action, "needs_confirmation": False}

    # Discovery
    name = group or DEFAULT_GROUP_NAME
    g = find_group(server, name)
    if not g:
        raise EngineError(
            f"No saved record for this site, and the group '{name}' was not found.",
            hint="If you installed without a group, precise cleanup needs the original saved record "
                 f"(manifest.<site>.json). Otherwise remove the metrics from the Pulse page directly.")
    subs = [s for s in read_all_subscriptions(server_url, token)
            if (s.get("follower") or {}).get("group_id") == g.id]
    def_ids = {}
    sub_ids = []
    for s in subs:
        sub_ids.append(s["id"])
        did = definition_id_for_metric(server_url, token, s["metric_id"])
        if did:
            def_ids[did] = s["metric_id"]
    to_delete = [{"name": None, "definition_id": did} for did in def_ids]
    return {"mode": "discovery", "to_delete": to_delete, "to_unfollow": [], "to_keep": [],
            "group": {"name": name, "id": g.id, "action": "delete"},
            "needs_confirmation": True,
            "warning": "Discovery cannot tell which definitions this tool created versus ones it "
                       "merely reused. Removing will delete ALL definitions this group follows."}


def execute_uninstall(server, server_url, token, uplan, log=_noop):
    """Perform the deletions described by uninstall_plan(). Returns a summary dict."""
    removed = 0
    for r in uplan["to_delete"]:
        code = delete_definition(server_url, token, r["definition_id"])
        removed += 1 if code in (200, 204) else 0
        log(f"  removed {r.get('name') or r['definition_id']}: {code}")
    for r in uplan["to_unfollow"]:
        code = delete_subscription(server_url, token, r["subscription_id"])
        log(f"  unfollowed {r['name']}: {code}")
    grp = uplan.get("group")
    if grp and grp.get("action") == "delete":
        resp = requests.delete(f"{server.baseurl}/sites/{server.site_id}/groups/{grp['id']}",
                               headers={"x-tableau-auth": token}, timeout=HTTP_TIMEOUT)
        log(f"  removed group '{grp['name']}': {resp.status_code}")
    if uplan["mode"] == "state":
        path = state_path(server.site_id)
        if os.path.exists(path):
            os.remove(path)
    return {"removed": removed, "unfollowed": len(uplan["to_unfollow"]),
            "group_removed": bool(grp and grp.get("action") == "delete")}
