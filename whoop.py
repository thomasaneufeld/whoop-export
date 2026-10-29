#!/usr/bin/env python3
"""WHOOP data export CLI. Usage: python whoop.py login | export [--start YYYY-MM-DD] [--end YYYY-MM-DD]"""

import argparse
import csv
import hmac
import json
import os
import secrets
import sys
import time
import webbrowser
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlencode, urlparse, parse_qs

import requests
from dotenv import load_dotenv

load_dotenv()

CLIENT_ID = os.environ.get("WHOOP_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("WHOOP_CLIENT_SECRET", "")
REDIRECT_URI = "http://localhost:3000/callback"
AUTH_URL = "https://api.prod.whoop.com/oauth/oauth2/auth"
TOKEN_URL = "https://api.prod.whoop.com/oauth/oauth2/token"
API_BASE = "https://api.prod.whoop.com/developer"
SCOPES = "offline read:recovery read:cycles read:sleep read:workout read:profile read:body_measurement"
TOKENS_FILE = Path(__file__).parent / "tokens.json"
DATA_DIR = Path(__file__).parent / "data"
TIMEZONE = os.environ.get("TIMEZONE", "America/Los_Angeles")
LOCAL_TZ = ZoneInfo(TIMEZONE)
MAX_RETRIES = 5


# --- Token management ---

def load_tokens():
    if not TOKENS_FILE.exists():
        print("No tokens found. Run 'python whoop.py login' first.")
        sys.exit(1)
    with open(TOKENS_FILE) as f:
        return json.load(f)


def save_tokens(tokens):
    with open(TOKENS_FILE, "w") as f:
        json.dump(tokens, f, indent=2)


def refresh_tokens(tokens):
    resp = requests.post(TOKEN_URL, data={
        "grant_type": "refresh_token",
        "refresh_token": tokens["refresh_token"],
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    })
    resp.raise_for_status()
    data = resp.json()
    tokens["access_token"] = data["access_token"]
    tokens["refresh_token"] = data["refresh_token"]
    tokens["expires_at"] = time.time() + data["expires_in"]
    save_tokens(tokens)
    return tokens


def ensure_fresh(tokens):
    if tokens.get("expires_at", 0) - time.time() < 300:
        print("Refreshing access token...")
        return refresh_tokens(tokens)
    return tokens


# --- API helpers ---

def api_get(endpoint, tokens, params=None):
    for attempt in range(MAX_RETRIES):
        tokens = ensure_fresh(tokens)
        headers = {"Authorization": f"Bearer {tokens['access_token']}"}
        resp = requests.get(f"{API_BASE}{endpoint}", headers=headers, params=params)

        if resp.status_code == 401 and attempt == 0:
            tokens = refresh_tokens(tokens)
            continue

        if resp.status_code == 429:
            wait = int(resp.headers.get("Retry-After", 2 ** (attempt + 1)))
            wait = min(wait, 120)
            print(f"  Rate limited, waiting {wait}s...")
            time.sleep(wait)
            continue

        if resp.status_code >= 500:
            wait = 2 ** (attempt + 1)
            print(f"  Server error {resp.status_code}, retrying in {wait}s...")
            time.sleep(wait)
            continue

        resp.raise_for_status()
        return resp.json(), tokens

    print(f"Failed after {MAX_RETRIES} retries for {endpoint}")
    sys.exit(1)


def fetch_all(endpoint, tokens, start=None, end=None):
    params = {"limit": "25"}
    if start:
        params["start"] = start
    if end:
        params["end"] = end

    all_records = []
    while True:
        data, tokens = api_get(endpoint, tokens, params)
        records = data.get("records", [])
        all_records.extend(records)
        next_token = data.get("next_token")
        if not next_token:
            break
        params["nextToken"] = next_token

    return all_records, tokens


# --- CSV flattening ---

def flatten(obj, prefix=""):
    out = {}
    if obj is None:
        return out
    for k, v in obj.items():
        key = f"{prefix}{k}" if not prefix else f"{prefix}_{k}"
        if isinstance(v, dict):
            out.update(flatten(v, key))
        else:
            out[key] = v
    return out


def write_csv(path, records):
    if not records:
        return
    flat = [flatten(r) for r in records]
    all_keys = []
    seen = set()
    for row in flat:
        for k in row:
            if k not in seen:
                all_keys.append(k)
                seen.add(k)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=all_keys, extrasaction="ignore")
        writer.writeheader()
        for row in flat:
            writer.writerow(row)


# --- Login command ---

def cmd_login(_args):
    if not CLIENT_ID or not CLIENT_SECRET:
        print("Set WHOOP_CLIENT_ID and WHOOP_CLIENT_SECRET in .env")
        sys.exit(1)

    state = secrets.token_hex(16)
    auth_params = urlencode({
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "state": state,
    })
    auth_link = f"{AUTH_URL}?{auth_params}"

    result = {}

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            qs = parse_qs(urlparse(self.path).query)
            returned_state = qs.get("state", [""])[0]
            code = qs.get("code", [""])[0]

            if not hmac.compare_digest(returned_state, state):
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"State mismatch.")
                return

            result["code"] = code
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<h3>Success! You can close this tab.</h3>")

        def log_message(self, *_args):
            pass

    server = HTTPServer(("127.0.0.1", 3000), CallbackHandler)
    print("Opening browser for WHOOP authorization...")
    try:
        chrome = webbrowser.get("C:/Program Files/Google/Chrome/Application/chrome.exe %s")
        chrome.open(auth_link)
    except webbrowser.Error:
        webbrowser.open(auth_link)
    print("Waiting for callback on http://localhost:3000/callback ...")

    while "code" not in result:
        server.handle_request()
    server.server_close()

    print("Got authorization code, exchanging for tokens...")
    resp = requests.post(TOKEN_URL,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "grant_type": "authorization_code",
            "code": result["code"],
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "redirect_uri": REDIRECT_URI,
        })
    if not resp.ok:
        print(f"Token exchange failed ({resp.status_code}): {resp.text}")
        sys.exit(1)
    data = resp.json()

    tokens = {
        "access_token": data["access_token"],
        "refresh_token": data["refresh_token"],
        "expires_at": time.time() + data["expires_in"],
    }
    save_tokens(tokens)
    print(f"Tokens saved to {TOKENS_FILE.name}. You're logged in.")


# --- Merge helpers ---

def record_key(record):
    """Return a unique key for deduplication."""
    return record.get("id") or record.get("cycle_id") or record.get("user_id")


def merge_records(json_path, new_records, paginated):
    """Merge new records into existing file, deduplicating by id."""
    if not paginated or not json_path.exists():
        return new_records

    with open(json_path, encoding="utf-8") as f:
        existing = json.load(f)

    seen = set()
    merged = []
    for r in new_records + existing:
        key = record_key(r)
        if key and key not in seen:
            seen.add(key)
            merged.append(r)
        elif not key:
            merged.append(r)

    merged.sort(key=lambda r: r.get("created_at") or r.get("start") or "", reverse=True)
    return merged


# --- Export command ---

DATASETS = [
    ("recovery",    "/v2/recovery",              True),
    ("cycles",      "/v2/cycle",                 True),
    ("sleep",       "/v2/activity/sleep",         True),
    ("workouts",    "/v2/activity/workout",       True),
    ("profile",     "/v2/user/profile/basic",     False),
    ("body",        "/v2/user/measurement/body",  False),
]


def cmd_export(args):
    tokens = load_tokens()

    first_run = not DATA_DIR.exists()
    pull_all = args.all or first_run

    if args.start:
        start = args.start + "T00:00:00.000Z"
    elif pull_all:
        start = None
    else:
        start = (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%dT00:00:00.000Z")

    if args.end:
        end = args.end + "T23:59:59.999Z"
    else:
        end = None

    if pull_all and not args.start:
        print("First run (or --all): pulling all history...")

    DATA_DIR.mkdir(exist_ok=True)
    summary = []

    for name, endpoint, paginated in DATASETS:
        print(f"Fetching {name}...")
        if paginated:
            new_records, tokens = fetch_all(endpoint, tokens, start=start, end=end)
        else:
            data, tokens = api_get(endpoint, tokens)
            new_records = [data]

        json_path = DATA_DIR / f"{name}.json"
        csv_path = DATA_DIR / f"{name}.csv"

        records = merge_records(json_path, new_records, paginated)

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(records, f, indent=2)

        write_csv(csv_path, records)
        count = len(records)
        summary.append((name, count))
        print(f"  {count} record(s) saved")

    print("\n--- Export Summary ---")
    for name, count in summary:
        print(f"  {name:12s}  {count:>5} records")
    print(f"\nFiles saved to {DATA_DIR}/")

    build_dashboard_data()


def utc_to_local_date(iso_str):
    """Convert a UTC ISO timestamp to a local date string (YYYY-MM-DD)."""
    dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    return dt.astimezone(LOCAL_TZ).strftime("%Y-%m-%d")


def build_dashboard_data():
    """Aggregate exported JSON into dashboard_data.json for the dashboard."""
    print(f"Building dashboard data (timezone: {TIMEZONE})...")
    from collections import Counter

    def load_json(name):
        with open(DATA_DIR / f"{name}.json", encoding="utf-8") as f:
            return json.load(f)

    recovery = load_json("recovery")
    cycles = load_json("cycles")
    sleep_data = load_json("sleep")
    workouts = load_json("workouts")
    profile = load_json("profile")
    body = load_json("body")

    rec_out = []
    for r in recovery:
        if r.get("score") and r.get("created_at"):
            s = r["score"]
            rec_out.append({
                "d": utc_to_local_date(r["created_at"]),
                "rs": round(s["recovery_score"], 1),
                "hrv": round(s["hrv_rmssd_milli"], 1),
                "rhr": round(s["resting_heart_rate"], 1),
                "spo2": round(s.get("spo2_percentage", 0), 1),
                "temp": round(s.get("skin_temp_celsius", 0), 1),
            })
    rec_out.sort(key=lambda x: x["d"])

    sleep_out = []
    for s in sleep_data:
        if s.get("score") and not s.get("nap"):
            sc = s["score"]
            ss = sc.get("stage_summary", {})
            sleep_out.append({
                "d": utc_to_local_date(s["start"]),
                "perf": sc.get("sleep_performance_percentage", 0),
                "eff": round(sc.get("sleep_efficiency_percentage", 0), 1),
                "cons": sc.get("sleep_consistency_percentage", 0),
                "rr": round(sc.get("respiratory_rate", 0), 1),
                "bed": round(ss.get("total_in_bed_time_milli", 0) / 3600000, 2),
                "rem": round(ss.get("total_rem_sleep_time_milli", 0) / 3600000, 2),
                "sws": round(ss.get("total_slow_wave_sleep_time_milli", 0) / 3600000, 2),
                "light": round(ss.get("total_light_sleep_time_milli", 0) / 3600000, 2),
                "awake": round(ss.get("total_awake_time_milli", 0) / 3600000, 2),
            })
    sleep_out.sort(key=lambda x: x["d"])

    strain_out = []
    for c in cycles:
        if c.get("score") and c.get("start"):
            strain_out.append({
                "d": utc_to_local_date(c["start"]),
                "strain": round(c["score"]["strain"], 1),
                "cal": round(c["score"]["kilojoule"] * 0.239006, 0),
                "avg_hr": c["score"]["average_heart_rate"],
                "max_hr": c["score"]["max_heart_rate"],
            })
    strain_out.sort(key=lambda x: x["d"])

    workout_out = []
    for w in workouts:
        if w.get("score") and w.get("start"):
            dur = 0
            if w.get("end"):
                s_dt = datetime.fromisoformat(w["start"].replace("Z", "+00:00"))
                e_dt = datetime.fromisoformat(w["end"].replace("Z", "+00:00"))
                dur = round((e_dt - s_dt).total_seconds() / 60)
            workout_out.append({
                "d": utc_to_local_date(w["start"]),
                "sport": w.get("sport_name", "unknown"),
                "strain": round(w["score"]["strain"], 1),
                "avg_hr": w["score"]["average_heart_rate"],
                "max_hr": w["score"]["max_heart_rate"],
                "cal": round(w["score"]["kilojoule"] * 0.239006, 0),
                "dur": dur,
            })
    workout_out.sort(key=lambda x: x["d"])

    # Fix stale cycle strain: use workout strain when it exceeds the cycle value
    workout_strain_by_date = {}
    for w in workout_out:
        workout_strain_by_date[w["d"]] = workout_strain_by_date.get(w["d"], 0) + w["strain"]
    for s in strain_out:
        ws = workout_strain_by_date.get(s["d"], 0)
        if ws > s["strain"]:
            s["strain"] = round(ws, 1)

    sports = dict(Counter(w["sport"] for w in workout_out).most_common())

    dashboard = {
        "profile": profile[0] if isinstance(profile, list) else profile,
        "body": body[0] if isinstance(body, list) else body,
        "recovery": rec_out,
        "sleep": sleep_out,
        "strain": strain_out,
        "workouts": workout_out,
        "sports": sports,
    }

    out_path = Path(__file__).parent / "dashboard_data.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(dashboard, f, separators=(",", ":"))
    print(f"Dashboard data updated ({out_path.name})")


# --- CLI ---

def main():
    parser = argparse.ArgumentParser(description="WHOOP data export CLI")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("login", help="Authorize with WHOOP via OAuth")

    export_p = sub.add_parser("export", help="Export WHOOP data to JSON and CSV")
    export_p.add_argument("--start", help="Start date (YYYY-MM-DD)")
    export_p.add_argument("--end", help="End date (YYYY-MM-DD)")
    export_p.add_argument("--all", action="store_true", help="Pull all history (no date filter)")

    args = parser.parse_args()
    if args.command == "login":
        cmd_login(args)
    elif args.command == "export":
        cmd_export(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
