#!/usr/bin/env python3
"""
app.py — local web GUI for the Pulse Admin Insights Starter Pack.

The friendly front door for people who don't live in a terminal. Double-click a launcher and a
small web page opens in the browser. Type in four things, review the plan, click Create. Under the
hood it calls the same engine.py the command line uses, so it behaves identically: same defaults,
same safety guarantees, same per-site state files.

Runs entirely on your own computer:
  - Binds to 127.0.0.1 only. Nothing is exposed to the network.
  - The PAT secret is held in memory only for the moment it takes to sign in, then dropped. It is
    never written to disk and never logged.
  - Every API call is gated by a random token minted at launch, so no other local program can
    drive it.
  - No credentials are ever stored. You enter them fresh each time you run it.

Run:
    ./.venv/bin/python app.py         (the launchers do this for you)
"""

import os
import secrets
import threading
import webbrowser

from flask import Flask, jsonify, request, Response

import engine

HERE = os.path.dirname(os.path.abspath(__file__))
INDEX_PATH = os.path.join(HERE, "web", "index.html")

app = Flask(__name__)
SESSION_TOKEN = secrets.token_urlsafe(24)   # minted per launch; the page must echo it back

# Single local user, so plain module-level state is fine.
STATE = {"server": None, "server_url": None, "token": None, "ir": engine.load_ir(),
         "plan": None, "uplan": None, "site_name": ""}
JOB = {"running": False, "done": False, "error": None, "log": [], "summary": None, "kind": None}
JOB_LOCK = threading.Lock()


def _require_token():
    if request.headers.get("X-Session-Token") != SESSION_TOKEN:
        return jsonify({"error": "This request did not come from the app window. Reload the page."}), 403
    return None


def _job_log(msg):
    with JOB_LOCK:
        JOB["log"].append(msg)


def _reset_job(kind):
    with JOB_LOCK:
        JOB.update({"running": True, "done": False, "error": None, "log": [], "summary": None, "kind": kind})


def _display_item(it):
    """The browser-safe subset of a plan item (no payloads, no tuple signatures)."""
    return {"name": it["name"], "cluster": it["cluster"], "source": it["source"],
            "why": it["why"], "action": it["action"],
            "already_there": it["action"] in ("adopt", "adopt-renamed"),
            "conflict": it["action"] == "conflict",
            "unresolved": it["action"] == "UNRESOLVED"}


# ── Pages ────────────────────────────────────────────────────────────────────────
@app.get("/")
def index():
    with open(INDEX_PATH, encoding="utf-8") as f:
        html = f.read().replace("__SESSION_TOKEN__", SESSION_TOKEN)
    return Response(html, mimetype="text/html")


# ── Connect + plan ────────────────────────────────────────────────────────────
@app.post("/api/connect")
def connect():
    guard = _require_token()
    if guard:
        return guard
    body = request.get_json(force=True)
    server_url = (body.get("server_url") or "").strip()
    site_name = (body.get("site_name") or "").strip()
    pat_name = (body.get("pat_name") or "").strip()
    pat_secret = (body.get("pat_secret") or "").strip()
    if not all([server_url, pat_name, pat_secret]):
        return jsonify({"error": "Please fill in the server address, token name, and token secret."}), 400

    try:
        server = engine.sign_in(server_url, site_name, pat_name, pat_secret)
        # pat_secret goes out of scope here; the signed-in token lives in the server object.
        plan = engine.build_plan(server, server_url, server.auth_token, STATE["ir"])
        filters = engine.validate_filters(server_url, server.auth_token, plan)
    except engine.EngineError as e:
        return jsonify({"error": e.message, "hint": e.hint}), 400
    except Exception as e:
        return jsonify({"error": "Something went wrong talking to Tableau.", "hint": str(e)}), 500

    STATE.update({"server": server, "server_url": server_url,
                  "token": server.auth_token, "plan": plan, "site_name": site_name})

    empty = [f for f in filters if f.get("empty")]
    return jsonify({
        "connected": True,
        "version": str(server.version),
        "items": [_display_item(it) for it in plan["items"]],
        "counts": {
            "new": sum(1 for it in plan["items"] if it["action"] == "create"),
            "already": sum(1 for it in plan["items"] if it["action"] in ("adopt", "adopt-renamed")),
            "conflict": sum(1 for it in plan["items"] if it["action"] == "conflict"),
        },
        "blocked": plan["blocked"],
        "warnings": plan["warnings"],
        "ambiguities": [a["name"] for a in plan["ambiguities"]],
        "empty_filters": [{"metric": f["metric"], "field": f["field"]} for f in empty],
        "default_group_name": engine.DEFAULT_GROUP_NAME,
    })


# ── Create ────────────────────────────────────────────────────────────────────
@app.post("/api/create")
def create():
    guard = _require_token()
    if guard:
        return guard
    if not STATE["server"] or not STATE["plan"]:
        return jsonify({"error": "Not connected yet. Go back and connect first."}), 400
    body = request.get_json(force=True)
    make_group = bool(body.get("make_group"))
    group_name = (body.get("group_name") or engine.DEFAULT_GROUP_NAME).strip() or engine.DEFAULT_GROUP_NAME
    follow = bool(body.get("follow"))

    _reset_job("create")

    def run():
        try:
            summary = engine.execute_deploy(
                STATE["server"], STATE["server_url"], STATE["token"], STATE["ir"], STATE["plan"],
                group=(group_name if make_group else None), follow=follow,
                on_conflict="skip", site_name=STATE["site_name"], log=_job_log)
            with JOB_LOCK:
                JOB["summary"] = {"created": summary["created"], "adopted": summary["adopted"],
                                  "skipped": summary["skipped"], "group": summary["group"],
                                  "group_followed": summary["group_followed"],
                                  "user_followed": summary["user_followed"]}
        except engine.EngineError as e:
            with JOB_LOCK:
                JOB["error"] = e.message + (("  " + e.hint) if e.hint else "")
        except Exception as e:
            with JOB_LOCK:
                JOB["error"] = str(e)
        finally:
            with JOB_LOCK:
                JOB["running"] = False
                JOB["done"] = True

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"started": True})


# ── Remove (uninstall) ──────────────────────────────────────────────────────────
@app.post("/api/remove-plan")
def remove_plan():
    guard = _require_token()
    if guard:
        return guard
    if not STATE["server"]:
        return jsonify({"error": "Not connected yet."}), 400
    try:
        uplan = engine.uninstall_plan(STATE["server"], STATE["server_url"], STATE["token"])
    except engine.EngineError as e:
        return jsonify({"error": e.message, "hint": e.hint}), 400
    STATE["uplan"] = uplan
    removed_names = [r.get("name") or r["definition_id"] for r in uplan["to_delete"]]
    kept = [r["name"] for r in uplan["to_keep"]] + [r["name"] for r in uplan["to_unfollow"]]
    grp = uplan.get("group")
    return jsonify({
        "mode": uplan["mode"],
        "to_remove": removed_names,
        "to_keep": kept,
        "group": (grp["name"] if grp and grp["action"] == "delete" else None),
        "needs_confirmation": uplan["needs_confirmation"],
        "warning": uplan.get("warning", ""),
    })


@app.post("/api/remove")
def remove():
    guard = _require_token()
    if guard:
        return guard
    if not STATE.get("uplan"):
        return jsonify({"error": "Nothing to remove yet."}), 400
    _reset_job("remove")

    def run():
        try:
            summary = engine.execute_uninstall(STATE["server"], STATE["server_url"],
                                               STATE["token"], STATE["uplan"], log=_job_log)
            with JOB_LOCK:
                JOB["summary"] = summary
        except Exception as e:
            with JOB_LOCK:
                JOB["error"] = str(e)
        finally:
            with JOB_LOCK:
                JOB["running"] = False
                JOB["done"] = True

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"started": True})


@app.get("/api/status")
def status():
    guard = _require_token()
    if guard:
        return guard
    with JOB_LOCK:
        return jsonify(dict(JOB))


def _open_browser(url):
    try:
        webbrowser.open(url)
    except Exception:
        pass


def main():
    from werkzeug.serving import make_server
    port = int(os.environ.get("PORT", "5137"))
    # Bind to loopback only. Try the preferred port, then a couple of fallbacks.
    server = None
    for p in [port, port + 1, port + 2, 0]:
        try:
            server = make_server("127.0.0.1", p, app, threaded=True)
            port = server.server_port
            break
        except OSError:
            continue
    if server is None:
        raise SystemExit("Could not bind a local port. Is another copy already running?")
    url = f"http://127.0.0.1:{port}/"
    print(f"\n  Pulse Admin Insights Starter Pack is running at {url}")
    print("  Your browser should open automatically. Leave this window open while you use the app.")
    print("  When you're done, close the browser tab and press Ctrl+C here to stop.\n")
    threading.Timer(0.8, _open_browser, args=[url]).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Stopped.")


if __name__ == "__main__":
    main()
