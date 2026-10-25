#!/usr/bin/env python3 -I
"""Tab Tracker: snapshots your open Chrome tabs, joins them to Chrome history,
and writes data.js for the dashboard (index.html in this folder).

macOS + Google Chrome only. Everything stays on your Mac.

Run:  python3 -I tabtracker.py            refresh tabs, history, favicons, new previews
      python3 -I tabtracker.py --no-thumbs skip page previews
Read-only on Chrome: it copies Chrome's databases before reading them and never
closes, opens or changes a tab. If Chrome isn't running it does nothing, so
closed-tab history is never polluted by a quit browser.
"""
import json, os, re, sqlite3, subprocess, sys, shutil, tempfile, hashlib, datetime as dt
from collections import Counter
from urllib.parse import urlparse, parse_qs

APP = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(APP, "db.json")
CHROME_DIR = os.path.expanduser("~/Library/Application Support/Google/Chrome")
CHROME_BIN = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
NOW = dt.datetime.now()
ISO = "%Y-%m-%d %H:%M"

# ---------- categories (first match wins, matched on url + title, lower case)
CATEGORIES = [
    ("Email & accounts", ["mail.google", "outlook.", "mail.yahoo", "icloud.com/mail", "/billing", "api-key", "/settings",
                          "/account", "/login", "sign-in", "sign in", "auth."]),
    ("Docs & files", ["docs.google", "drive.google", "sheets", "dropbox", "onedrive", "sharepoint", "notion.", "airtable", ".pdf"]),
    ("AI chats & tools", ["claude.ai", "chatgpt.com", "chat.openai", "gemini.google", "perplexity", "huggingface", "midjourney"]),
    ("Video & audio", ["youtube.", "vimeo.", "spotify.", "soundcloud.", "twitch."]),
    ("Social", ["facebook.com", "instagram.com", "linkedin.com", "x.com", "twitter.com", "reddit.com", "tiktok.com", "threads.net"]),
    ("Shopping", ["amazon.", "ebay.", "aliexpress", "etsy.", "checkout", "/cart"]),
    ("Learning & courses", ["course", "skool.com", "udemy", "coursera", "thinkific", "teachable", "tutorial", "academy", "member"]),
    ("Dev & tools", ["github.com", "gitlab", "stackoverflow", "vercel", "netlify", "localhost", "127.0.0.1"]),
    ("Search", ["google.com/search", "bing.com/search", "duckduckgo.com"]),
]
def categorise(url, title):
    s = (url + " " + title).lower()
    for name, keys in CATEGORIES:
        if any(k in s for k in keys):
            return name
    return "Reading & research"

# ---------- previews: only pages that are safe to load logged out
SKIP_HOSTS = ["mail.", "outlook.", "icloud.com", "docs.google", "drive.google", "google.com", "notion.", "claude.ai",
              "chatgpt.com", "openai.com", "gemini.google", "facebook.com", "instagram.com", "linkedin.com", "x.com",
              "twitter.com", "paypal", "stripe.com", "bank", "dropbox", "onedrive", "sharepoint", "slack.com", "zoom.us"]
SKIP_PATH = ["checkout", "confirm", "paypal", "admin", "login", "signin", "sign-in", "auth", "billing", "api-key",
             "dashboard", "settings", "account", "member", "thank", "/ty", "download", "inbox", "courses/take"]
SKIP_QUERY = ["email", "phone", "firstname", "lastname", "name", "token", "key", "code", "session", "pid", "he", "_hsenc"]
def preview_block_reason(url):
    p = urlparse(url)
    if p.scheme not in ("http", "https"):
        return "local or extension page"
    host, path = p.netloc.lower(), p.path.lower()
    if any(h in host for h in SKIP_HOSTS):
        return "private or logged-in site"
    if any(k in path for k in SKIP_PATH):
        return "account, checkout or login page"
    q = {k.lower() for k in parse_qs(p.query)}
    if q & set(SKIP_QUERY):
        return "link carries personal details"
    return None

def chrome_running():
    return subprocess.run(["pgrep", "-x", "Google Chrome"], capture_output=True).returncode == 0

def open_tabs():
    js = ('const c=Application("Google Chrome");const o=[];c.windows().forEach((w,wi)=>w.tabs().forEach(t=>'
          'o.push({w:wi+1,title:t.title(),url:t.url()})));JSON.stringify(o)')
    try:
        out = subprocess.run(["osascript", "-l", "JavaScript", "-e", js], capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        sys.exit(NOW.strftime(ISO) + ": Chrome didn't answer. If macOS asked whether python3 may control Google Chrome, click Allow, then run this again.")
    if out.returncode != 0:
        sys.exit("Could not read Chrome tabs: " + out.stderr.strip())
    return json.loads(out.stdout)

def profiles():
    return [p for p in [os.path.join(CHROME_DIR, "Default")] +
            sorted(os.path.join(CHROME_DIR, d) for d in os.listdir(CHROME_DIR) if d.startswith("Profile "))
            if os.path.exists(os.path.join(p, "History"))]

def chrome_time(t):
    return (dt.datetime(1601, 1, 1) + dt.timedelta(microseconds=t)).replace(tzinfo=dt.timezone.utc).astimezone().replace(tzinfo=None)

def history_stats(urls, tmp):
    """last visit, visits in last 7 / 30 days, total visits, per url, across profiles."""
    stats = {u: {"last": None, "v7": 0, "v30": 0, "total": 0} for u in urls}
    utc = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    c7, c30 = (int((utc - dt.timedelta(days=d) - dt.datetime(1601, 1, 1)).total_seconds() * 1e6) for d in (7, 30))
    for i, prof in enumerate(profiles()):
        f = os.path.join(tmp, f"h{i}.db"); shutil.copy(os.path.join(prof, "History"), f)
        con = sqlite3.connect(f)
        rows = []
        for n in range(0, len(urls), 500):
            part = urls[n:n + 500]
            q = ("select u.url, u.last_visit_time, u.visit_count, "
                 "sum(v.visit_time>?), sum(v.visit_time>?) from urls u left join visits v on v.url=u.id "
                 "where u.url in (%s) group by u.id" % ",".join("?" * len(part)))
            rows += con.execute(q, [c7, c30, *part]).fetchall()
        for url, last, total, v7, v30 in rows:
            s = stats[url]
            lt = chrome_time(last) if last else None
            if lt and (not s["last"] or lt > s["last"]): s["last"] = lt
            s["total"] += total or 0; s["v7"] += v7 or 0; s["v30"] += v30 or 0
        con.close()
    return stats

def favicons(urls, tmp):
    found = {}
    for i, prof in enumerate(profiles()):
        src = os.path.join(prof, "Favicons")
        if not os.path.exists(src): continue
        f = os.path.join(tmp, f"f{i}.db"); shutil.copy(src, f)
        con = sqlite3.connect(f)
        for u in urls:
            if u in found: continue
            row = con.execute("select b.image_data from icon_mapping m join favicon_bitmaps b on b.icon_id=m.icon_id "
                              "where m.page_url=? order by abs(b.width-32) limit 1", (u,)).fetchone()
            if row and row[0]:
                name = hashlib.md5(row[0]).hexdigest()[:12] + ".png"
                path = os.path.join(APP, "favicons", name)
                if not os.path.exists(path):
                    open(path, "wb").write(row[0])
                found[u] = "favicons/" + name
        con.close()
    return found

def snap_preview(url, rec, tmp):
    """Logged-out headless Chrome in a throwaway profile: screenshot + meta description."""
    key = hashlib.md5(url.encode()).hexdigest()[:16]
    shot = os.path.join(tmp, key + ".png")
    prof = tempfile.mkdtemp(dir=tmp)
    base = [CHROME_BIN, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--mute-audio", "--no-first-run",
            "--disable-extensions", f"--user-data-dir={prof}", "--window-size=1280,800", "--virtual-time-budget=6000"]
    try:
        subprocess.run(base + [f"--screenshot={shot}", url], capture_output=True, timeout=45)
        if not rec.get("desc"):
            dom = subprocess.run(base + ["--dump-dom", url], capture_output=True, text=True, timeout=45).stdout
            m = (re.search(r'<meta[^>]+(?:name|property)="(?:og:)?description"[^>]+content="([^"]{10,300})"', dom, re.I)
                 or re.search(r'<meta[^>]+content="([^"]{10,300})"[^>]+(?:name|property)="(?:og:)?description"', dom, re.I))
            if m:
                import html
                rec["desc"] = html.unescape(m.group(1)).strip(); rec["desc_source"] = "page"
    except subprocess.TimeoutExpired:
        pass
    shutil.rmtree(prof, ignore_errors=True)
    if not os.path.exists(shot):
        return None
    out = os.path.join(APP, "thumbs", key + ".jpg")
    subprocess.run(["sips", "-Z", "640", "-s", "format", "jpeg", "-s", "formatOptions", "72", shot, "--out", out], capture_output=True)
    if not os.path.exists(out):
        return None
    return "thumbs/" + key + ".jpg"

def load_db():
    if os.path.exists(DB):
        return json.load(open(DB))
    return {"tabs": {}, "snapshots": [], "events": []}

def main():
    if not chrome_running():
        print("Chrome isn't running, nothing to record."); return
    db = load_db()
    for d in ("thumbs", "favicons"):
        os.makedirs(os.path.join(APP, d), exist_ok=True)
    tabs = open_tabs()
    now = NOW.strftime(ISO)
    cnt = Counter(t["url"] for t in tabs)
    first = {}
    for t in tabs: first.setdefault(t["url"], t)
    opened, closed = 0, 0
    for u, t in first.items():
        r = db["tabs"].get(u)
        if not r:
            r = db["tabs"][u] = {"url": u, "desc": "", "first_seen": now}; opened += 1
        elif not r.get("open"):
            r.pop("closed_on", None); r.pop("closed_reason", None); r["reopened"] = now
        r.update(open=True, title=t["title"] or r.get("title", ""), window=t["w"], open_count=cnt[u], last_seen_open=now)
    for u, r in db["tabs"].items():
        if r.get("open") and u not in first:
            r["open"] = False; r["open_count"] = 0; r["closed_on"] = now; closed += 1
    tmp = tempfile.mkdtemp()
    try:
        urls = list(db["tabs"])
        hs = history_stats(urls, tmp)
        fav = favicons(urls, tmp)
        for u, r in db["tabs"].items():
            s = hs[u]
            if s["last"]: r["last_visit"] = s["last"].strftime(ISO)
            r.update(v7=s["v7"], v30=s["v30"], visits=s["total"])
            if u in fav: r["favicon"] = fav[u]
            r["domain"] = urlparse(u).netloc.replace("www.", "") or ("local file" if u.startswith("file:") else "browser page")
            r["category"] = categorise(u, r.get("title", ""))
            q = parse_qs(urlparse(u).query)
            r["from_ad"] = bool({"fbclid", "utm_medium", "utm_source"} & set(q)) and any(
                k in u.lower() for k in ["paid", "fbclid", "fbads", "utm_source=fb", "utm_source=facebook", "utm_source=linkedin"])
        if "--no-thumbs" not in sys.argv:
            for u, r in db["tabs"].items():
                if not r.get("open") or r.get("thumb") or r.get("thumb_tried"): continue
                why = preview_block_reason(u)
                r["thumb_tried"] = now
                if why:
                    r["thumb_skip"] = why; continue
                r["thumb"] = snap_preview(u, r, tmp)
                if not r["thumb"]: r["thumb_skip"] = "page didn't load"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    db["snapshots"].append({"t": now, "open": len(tabs)})
    if len(db["snapshots"]) == 1:
        db["events"].append({"t": now, "text": f"Tracking started with {len(tabs)} open tabs"})
    elif opened or closed:
        db["events"].append({"t": now, "text": f"{opened} new, {closed} closed since the last check"})
    db["updated"] = now
    json.dump(db, open(DB, "w"), indent=1)
    with open(os.path.join(APP, "data.js"), "w") as f:
        f.write("window.TAB_DATA = " + json.dumps(db) + ";\n")
    print(f"{now}: {len(tabs)} tabs open, {opened} new, {closed} closed")

if __name__ == "__main__":
    main()
