#!/usr/bin/env python3
"""
generate_stats.py
─────────────────
Fetches live GitHub statistics and renders a premium, dark-themed SVG dashboard.
Queries: GraphQL (profile, contributions, repos) + REST search (issues closed).
"""

import os, sys
import requests
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List

# ── Config ─────────────────────────────────────────────────────────────────────
TOKEN    = os.environ.get("GITHUB_TOKEN", "")
USERNAME = os.environ.get("GITHUB_USERNAME", "Knowledge-Benjamin")
OUT_FILE = os.environ.get("STATS_OUT", "github-stats-card.svg")

if not TOKEN:
    sys.exit("Error: GITHUB_TOKEN is not set.")

GQL_URL  = "https://api.github.com/graphql"
REST_URL = "https://api.github.com"
GQL_HDR  = {"Authorization": f"bearer {TOKEN}", "Content-Type": "application/json"}
REST_HDR = {"Authorization": f"token {TOKEN}",  "Accept": "application/vnd.github.v3+json"}
SRCH_HDR = {**REST_HDR, "Accept": "application/vnd.github.cloak-preview+json"}

# ── API Helpers ────────────────────────────────────────────────────────────────
def gql(query: str, variables: Dict = None) -> Dict:
    r = requests.post(GQL_URL, json={"query": query, "variables": variables or {}},
                      headers=GQL_HDR, timeout=30)
    r.raise_for_status()
    data = r.json()
    if "errors" in data:
        print(f"[gql warn] {data['errors']}", file=sys.stderr)
    return data.get("data", {})

def rest(path: str, params: Dict = None, hdrs: Dict = None) -> Any:
    h = {**REST_HDR, **(hdrs or {})}
    r = requests.get(f"{REST_URL}{path}", params=params, headers=h, timeout=30)
    r.raise_for_status()
    return r.json()

def fmt(v: int) -> str:
    if v >= 10_000: return f"{v // 1000}K"
    return f"{v:,}"

def esc(s: str) -> str:
    return str(s).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

# ── GraphQL Queries ────────────────────────────────────────────────────────────
_PROFILE = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    name login createdAt
    followers  { totalCount }
    following  { totalCount }
    organizations(first: 1) { totalCount }
    allRepos: repositories(ownerAffiliations: OWNER, first: 1) { totalCount }
    contributions: contributionsCollection(from: $from, to: $to) {
      totalCommitContributions
      totalPullRequestContributions
      totalPullRequestReviewContributions
      totalIssueContributions
      totalRepositoriesWithContributedCommits
    }
  }
}"""

_CONTRIBS = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      totalCommitContributions
      commitContributionsByRepository(maxRepositories: 25) {
        repository { nameWithOwner isPrivate }
        contributions { totalCount }
      }
    }
  }
}"""

_REPOS = """
query($login: String!, $after: String) {
  user(login: $login) {
    repositories(ownerAffiliations: OWNER, first: 100, after: $after) {
      pageInfo { hasNextPage endCursor }
      nodes {
        stargazerCount forkCount
        watchers { totalCount }
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name color } }
        }
      }
    }
  }
}"""

# ── Data Fetching ──────────────────────────────────────────────────────────────
def fetch_stats() -> Dict:
    now     = datetime.now(timezone.utc)
    today_0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    ago_30  = now - timedelta(days=30)
    ago_365 = now - timedelta(days=365)

    # Profile + yearly
    p    = gql(_PROFILE, {"login": USERNAME, "from": ago_365.isoformat(), "to": now.isoformat()})
    user = p.get("user", {})
    yr   = user.get("contributions", {})

    # 30-day commits
    t30     = gql(_CONTRIBS, {"login": USERNAME, "from": ago_30.isoformat(), "to": now.isoformat()})
    c30     = t30.get("user", {}).get("contributionsCollection", {}).get("totalCommitContributions", 0)

    # Today
    td_raw  = gql(_CONTRIBS, {"login": USERNAME, "from": today_0.isoformat(), "to": now.isoformat()})
    td_col  = td_raw.get("user", {}).get("contributionsCollection", {})
    c_today = td_col.get("totalCommitContributions", 0)
    repos_today = td_col.get("commitContributionsByRepository", [])
    pub_today   = [r["repository"]["nameWithOwner"] for r in repos_today if not r["repository"]["isPrivate"]]
    priv_n      = sum(1 for r in repos_today if r["repository"]["isPrivate"])

    # All repos (paginated)
    all_repos, cursor = [], None
    while True:
        rd   = gql(_REPOS, {"login": USERNAME, "after": cursor})
        page = rd.get("user", {}).get("repositories", {})
        all_repos.extend(page.get("nodes", []))
        pi = page.get("pageInfo", {})
        if not pi.get("hasNextPage"): break
        cursor = pi["endCursor"]

    stars    = sum(r.get("stargazerCount", 0)                for r in all_repos)
    forks    = sum(r.get("forkCount", 0)                     for r in all_repos)
    watchers = sum(r.get("watchers", {}).get("totalCount", 0) for r in all_repos)

    # Language map
    lang_map: Dict = {}
    for repo in all_repos:
        for edge in repo.get("languages", {}).get("edges", []):
            n = edge["node"]["name"]
            c = edge["node"].get("color") or "#586069"
            s = edge.get("size", 0)
            lang_map.setdefault(n, {"size": 0, "color": c})
            lang_map[n]["size"] += s

    total_sz = sum(v["size"] for v in lang_map.values()) or 1
    languages = sorted(
        [{"name": k, "color": v["color"], "pct": round(v["size"]/total_sz*100, 1)}
         for k, v in lang_map.items()],
        key=lambda x: x["pct"], reverse=True
    )[:8]

    # Issues closed
    try:
        ic = rest("/search/issues",
                  params={"q": f"type:issue author:{USERNAME} is:closed", "per_page": 1},
                  hdrs=SRCH_HDR)
        issues_closed = ic.get("total_count", 0)
    except Exception as e:
        print(f"[warn] issues_closed: {e}", file=sys.stderr)
        issues_closed = 0

    # Join date
    try:
        joined = datetime.fromisoformat(
            user.get("createdAt","").replace("Z","+00:00")).strftime("%b %Y")
    except Exception:
        joined = "—"

    return {
        "name":           user.get("name") or USERNAME,
        "login":          user.get("login", USERNAME),
        "joined":         joined,
        "followers":      user.get("followers", {}).get("totalCount", 0),
        "following":      user.get("following", {}).get("totalCount", 0),
        "organizations":  user.get("organizations", {}).get("totalCount", 0),
        "total_repos":    user.get("allRepos", {}).get("totalCount", 0),
        "stars":          stars,
        "forks":          forks,
        "watchers":       watchers,
        "commits_year":   yr.get("totalCommitContributions", 0),
        "commits_30d":    c30,
        "commits_today":  c_today,
        "prs_opened":     yr.get("totalPullRequestContributions", 0),
        "prs_reviewed":   yr.get("totalPullRequestReviewContributions", 0),
        "issues_opened":  yr.get("totalIssueContributions", 0),
        "issues_closed":  issues_closed,
        "repos_contributed": yr.get("totalRepositoriesWithContributedCommits", 0),
        "today_public":   pub_today,
        "today_private_n": priv_n,
        "languages":      languages,
        "updated_at":     now.strftime("%b %d, %Y  ·  %H:%M UTC"),
    }

# ── SVG Generation ─────────────────────────────────────────────────────────────
# Design tokens
W      = 860
PAD    = 28
GAP    = 12
BG     = "#0D1117"
CARD   = "#161B22"
BORDER = "#21262D"
T1     = "#E6EDF3"
T2     = "#8B949E"
T3     = "#6E7681"
ACC    = "#7C3AED"   # violet
ACC2   = "#4F46E5"   # indigo
GRN    = "#3FB950"   # green
YLW    = "#D29922"   # yellow/gold
BLU    = "#58A6FF"   # blue
ORG    = "#DB6D28"   # orange
FONT   = "system-ui,-apple-system,'Segoe UI',Roboto,sans-serif"
MONO   = "'SFMono-Regular',Consolas,'Liberation Mono',Menlo,monospace"


def card_block(cx: float, cy: float, cw: float, ch: float,
               top_color: str, value: str, label: str) -> str:
    mx = cx + cw / 2
    return (
        f'<rect x="{cx:.2f}" y="{cy:.2f}" width="{cw:.2f}" height="{ch:.2f}" '
        f'fill="{CARD}" rx="8" stroke="{BORDER}" stroke-width="1"/>\n'
        f'<rect x="{cx:.2f}" y="{cy:.2f}" width="{cw:.2f}" height="3" '
        f'fill="{top_color}" rx="1.5"/>\n'
        f'<text x="{mx:.2f}" y="{cy + ch*0.54:.2f}" text-anchor="middle" '
        f'font-size="26" font-weight="700" fill="{T1}" font-family="{FONT}" '
        f'letter-spacing="-0.5">{esc(value)}</text>\n'
        f'<text x="{mx:.2f}" y="{cy + ch*0.83:.2f}" text-anchor="middle" '
        f'font-size="10" fill="{T2}" font-family="{MONO}" letter-spacing="0.8">'
        f'{esc(label)}</text>\n'
    )


def section_card(cx: float, cy: float, cw: float, ch: float,
                 title: str, body_fn) -> str:
    out  = (f'<rect x="{cx:.2f}" y="{cy:.2f}" width="{cw:.2f}" height="{ch:.2f}" '
            f'fill="{CARD}" rx="8" stroke="{BORDER}" stroke-width="1"/>\n')
    out += (f'<text x="{cx+14:.2f}" y="{cy+20:.2f}" font-size="10" fill="{T3}" '
            f'font-family="{MONO}" letter-spacing="1.2">{esc(title)}</text>\n')
    out += (f'<line x1="{cx+14:.2f}" y1="{cy+28:.2f}" x2="{cx+cw-14:.2f}" y2="{cy+28:.2f}" '
            f'stroke="{BORDER}" stroke-width="1"/>\n')
    out += body_fn(cx, cy)
    return out


def commit_bar_row(cx: float, base_y: float, bar_w: float,
                   label: str, val: int, pct: float) -> str:
    fill = max(int(bar_w * min(pct, 100) / 100), 4)
    label_x  = cx + 14
    value_x  = cx + 170
    bar_x    = cx + 180
    return (
        f'<text x="{label_x:.2f}" y="{base_y:.2f}" font-size="12" fill="{T2}" font-family="{FONT}">'
        f'{esc(label)}</text>\n'
        f'<text x="{value_x:.2f}" y="{base_y:.2f}" font-size="13" font-weight="600" fill="{T1}" '
        f'text-anchor="end">{esc(fmt(val))}</text>\n'
        f'<rect x="{bar_x:.2f}" y="{base_y - 12:.2f}" width="{bar_w:.2f}" height="9" '
        f'fill="{BORDER}" rx="4.5"/>\n'
        f'<rect x="{bar_x:.2f}" y="{base_y - 12:.2f}" width="{fill}" height="9" '
        f'fill="url(#grad-bar)" rx="4.5"/>\n'
    )


def kv_row(x: float, y: float, label: str, val: int, color: str = T1,
           right_x: float = 0) -> str:
    rx = right_x if right_x else x + 220
    return (
        f'<text x="{x:.2f}" y="{y:.2f}" font-size="12" fill="{T2}" font-family="{FONT}">'
        f'{esc(label)}</text>\n'
        f'<text x="{rx:.2f}" y="{y:.2f}" font-size="13" font-weight="600" fill="{color}" '
        f'text-anchor="end">{esc(fmt(val))}</text>\n'
    )


def lang_row(cx: float, y: float, bw: float, lang: Dict) -> str:
    fill = max(int(bw * lang["pct"] / 100), 4)
    name = lang["name"]
    if len(name) > 18: name = name[:16] + "…"
    color = lang["color"]
    return (
        f'<circle cx="{cx+14+5:.2f}" cy="{y+8:.2f}" r="5" fill="{color}"/>\n'
        f'<text x="{cx+28:.2f}" y="{y+13:.2f}" font-size="12" fill="{T1}" font-family="{FONT}">'
        f'{esc(name)}</text>\n'
        f'<text x="{cx+bw+28+14:.2f}" y="{y+13:.2f}" font-size="11" fill="{T2}" '
        f'text-anchor="end">{lang["pct"]}%</text>\n'
        f'<rect x="{cx+14:.2f}" y="{y+20:.2f}" width="{bw:.2f}" height="7" '
        f'fill="{BORDER}" rx="3.5"/>\n'
        f'<rect x="{cx+14:.2f}" y="{y+20:.2f}" width="{fill}" height="7" '
        f'fill="{color}" rx="3.5" opacity="0.9"/>\n'
    )


def generate_svg(s: Dict) -> str:
    # ── Heights ────────────────────────────────────────────────────────────────
    H_HDR    = 62
    H_ROW1   = 94    # 5-card row:  repos, stars, forks, followers, following
    H_ROW2   = 94    # 4-card row:  orgs, repos-contributed, prs-reviewed, issues-closed
    H_MID    = 152   # 2-col:       commit-activity (left) | pr+issues (right)
    H_TODAY  = 74
    H_LANG   = len(s["languages"]) * 36 + 56
    H_FTR    = 34
    GAPS     = GAP * 6
    H_TOTAL  = PAD + H_HDR + GAP + H_ROW1 + GAP + H_ROW2 + GAP + H_MID + GAP + H_TODAY + GAP + H_LANG + GAP + H_FTR + PAD

    # ── Y positions ────────────────────────────────────────────────────────────
    yH   = PAD
    yR1  = yH  + H_HDR   + GAP
    yR2  = yR1 + H_ROW1  + GAP
    yMID = yR2 + H_ROW2  + GAP
    yTD  = yMID + H_MID  + GAP
    yLG  = yTD + H_TODAY + GAP
    yFT  = yLG + H_LANG  + GAP

    # ── Stat card rows ─────────────────────────────────────────────────────────
    row1_specs = [
        ("REPOS",     fmt(s["total_repos"]),    ACC),
        ("STARS",     fmt(s["stars"]),           YLW),
        ("FORKS",     fmt(s["forks"]),           BLU),
        ("FOLLOWERS", fmt(s["followers"]),       GRN),
        ("FOLLOWING", fmt(s["following"]),       ACC2),
    ]
    row2_specs = [
        ("ORGANIZATIONS",  fmt(s["organizations"]),    ORG),
        ("REPOS CONTRIBUTED", fmt(s["repos_contributed"]), GRN),
        ("PRs REVIEWED",   fmt(s["prs_reviewed"]),     BLU),
        ("ISSUES CLOSED",  fmt(s["issues_closed"]),    GRN),
    ]

    def render_card_row(specs, y_top, row_h):
        n  = len(specs)
        cw = (W - 2*PAD - (n-1)*GAP) / n
        out = ""
        for i, (label, value, color) in enumerate(specs):
            cx = PAD + i*(cw+GAP)
            out += card_block(cx, y_top, cw, row_h, color, value, label)
        return out

    row1_svg = render_card_row(row1_specs, yR1, H_ROW1)
    row2_svg = render_card_row(row2_specs, yR2, H_ROW2)

    # ── Commit activity section (left 60%) ────────────────────────────────────
    cm_w = (W - 2*PAD) * 0.60 - GAP//2
    cm_x = PAD
    bar_avail = cm_w - 180 - 14

    cy   = s["commits_year"]
    c30  = s["commits_30d"]
    ctd  = s["commits_today"]
    base = max(cy, 1)
    d30_pct = min(c30/base*100, 100)
    td_pct  = min(ctd/base*100, 100)

    def commit_body(cx, cy_top):
        return (
            commit_bar_row(cx, cy_top + 58,  bar_avail, "Past 12 months", cy, 100.0)
          + commit_bar_row(cx, cy_top + 96,  bar_avail, "Past 30 days",   c30, d30_pct)
          + commit_bar_row(cx, cy_top + 134, bar_avail, "Today",          ctd, td_pct)
        )

    commit_svg = section_card(cm_x, yMID, cm_w, H_MID, "COMMIT ACTIVITY", commit_body)

    # ── PR + Issues section (right 40%) ───────────────────────────────────────
    ri_w = W - 2*PAD - cm_w - GAP
    ri_x = W - PAD - ri_w

    def ri_body(rx, ry_top):
        kv_right = rx + ri_w - 14
        return (
            # PRs
            f'<text x="{rx+14:.2f}" y="{ry_top+48:.2f}" font-size="10" fill="{T3}" '
            f'font-family="{MONO}" letter-spacing="0.8">PULL REQUESTS</text>\n'
          + kv_row(rx+14, ry_top+68, "Opened",   s["prs_opened"],  GRN, kv_right)
          + kv_row(rx+14, ry_top+88, "Reviewed", s["prs_reviewed"], BLU, kv_right)
          + f'<line x1="{rx+14:.2f}" y1="{ry_top+102:.2f}" x2="{rx+ri_w-14:.2f}" y2="{ry_top+102:.2f}" '
            f'stroke="{BORDER}" stroke-width="1"/>\n'
          # Issues
          + f'<text x="{rx+14:.2f}" y="{ry_top+120:.2f}" font-size="10" fill="{T3}" '
            f'font-family="{MONO}" letter-spacing="0.8">ISSUES</text>\n'
          + kv_row(rx+14, ry_top+140, "Opened", s["issues_opened"], YLW, kv_right)
        )

    ri_svg = section_card(ri_x, yMID, ri_w, H_MID, "PR & ISSUES", ri_body)

    # ── Today's Activity ──────────────────────────────────────────────────────
    pub   = s["today_public"]
    priv  = s["today_private_n"]
    total_repos_today = len(pub) + priv
    active = ctd > 0
    dot_c  = GRN if active else T3

    if active:
        c_w = "commit" if ctd == 1 else "commits"
        r_w = "repo"   if total_repos_today == 1 else "repos"
        line1 = f"{fmt(ctd)} {c_w} across {total_repos_today} {r_w} today"
        parts = []
        if pub:
            names = ", ".join(n.split("/")[-1] for n in pub[:3])
            if len(pub) > 3: names += f" +{len(pub)-3} more"
            parts.append(names)
        if priv:
            parts.append(f"+{priv} private")
        line2 = "  ·  ".join(parts)
    else:
        line1 = "No commits yet today."
        line2 = "Rest is productive too."

    today_svg = (
        f'<rect x="{PAD}" y="{yTD}" width="{W-2*PAD}" height="{H_TODAY}" '
        f'fill="{CARD}" rx="8" stroke="{BORDER}" stroke-width="1"/>\n'
        f'<text x="{PAD+14}" y="{yTD+18}" font-size="10" fill="{T3}" '
        f'font-family="{MONO}" letter-spacing="1.2">TODAY\'S ACTIVITY</text>\n'
        f'<line x1="{PAD+14}" y1="{yTD+26}" x2="{W-PAD-14}" y2="{yTD+26}" '
        f'stroke="{BORDER}" stroke-width="1"/>\n'
        # Pulse dot
        f'<circle cx="{PAD+22:.2f}" cy="{yTD+47:.2f}" r="5" fill="{dot_c}" opacity="0.2"/>\n'
        f'<circle cx="{PAD+22:.2f}" cy="{yTD+47:.2f}" r="3" fill="{dot_c}"/>\n'
        f'<text x="{PAD+34:.2f}" y="{yTD+51:.2f}" font-size="13" font-weight="600" fill="{T1}" '
        f'font-family="{FONT}">{esc(line1)}</text>\n'
        + (f'<text x="{PAD+34:.2f}" y="{yTD+67:.2f}" font-size="11" fill="{T2}" '
           f'font-family="{FONT}">{esc(line2)}</text>\n' if line2 else "")
    )

    # ── Languages ─────────────────────────────────────────────────────────────
    lang_bw = W - 2*PAD - 28 - 60  # bar width inside the section card

    def lang_body(cx, cy_top):
        out = ""
        for i, lang in enumerate(s["languages"]):
            out += lang_row(cx, cy_top + 36 + i*36, lang_bw, lang)
        return out

    lang_svg = section_card(PAD, yLG, W-2*PAD, H_LANG, "TOP LANGUAGES  ·  BY BYTES WRITTEN", lang_body)

    # ── Header ────────────────────────────────────────────────────────────────
    hdr_svg = (
        # Name
        f'<text x="{PAD}" y="{yH+32}" font-size="21" font-weight="700" fill="{T1}" '
        f'font-family="{FONT}" letter-spacing="-0.3">{esc(s["name"])}</text>\n'
        # Handle
        f'<text x="{PAD}" y="{yH+52}" font-size="12" fill="{T2}" font-family="{MONO}">'
        f'@{esc(s["login"])}</text>\n'
        # Member since — right aligned
        f'<text x="{W-PAD}" y="{yH+32}" text-anchor="end" font-size="12" fill="{T2}" '
        f'font-family="{MONO}">Member since {esc(s["joined"])}</text>\n'
        # Divider
        f'<line x1="{PAD}" y1="{yH+H_HDR-2}" x2="{W-PAD}" y2="{yH+H_HDR-2}" '
        f'stroke="{BORDER}" stroke-width="1"/>\n'
    )

    # ── Footer ────────────────────────────────────────────────────────────────
    ftr_svg = (
        f'<text x="{W/2:.2f}" y="{yFT+20}" text-anchor="middle" font-size="11" fill="{T3}" '
        f'font-family="{MONO}">Updated {esc(s["updated_at"])}</text>\n'
    )

    # ── Full SVG ──────────────────────────────────────────────────────────────
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H_TOTAL}"
     viewBox="0 0 {W} {H_TOTAL}" role="img"
     aria-label="Knowledge Benjamin GitHub Stats">
  <defs>
    <linearGradient id="grad-bar" x1="0%" y1="0%" x2="100%" y2="0%">
      <stop offset="0%"   stop-color="{ACC}"/>
      <stop offset="100%" stop-color="{ACC2}"/>
    </linearGradient>
  </defs>

  <!-- Background -->
  <rect width="{W}" height="{H_TOTAL}" fill="{BG}" rx="12"/>
  <!-- Top gradient accent line -->
  <rect x="0" y="0" width="{W}" height="3" rx="1.5">
    <animate attributeName="width" values="{W};{W}" dur="1s" repeatCount="1"/>
  </rect>
  <defs>
    <linearGradient id="top-line" x1="0%" y1="0%" x2="100%" y2="0%">
      <stop offset="0%"   stop-color="{ACC}"/>
      <stop offset="60%"  stop-color="{ACC2}"/>
      <stop offset="100%" stop-color="{BLU}"/>
    </linearGradient>
  </defs>
  <rect x="0" y="0" width="{W}" height="3" fill="url(#top-line)" rx="1.5"/>

  {hdr_svg}
  {row1_svg}
  {row2_svg}
  {commit_svg}
  {ri_svg}
  {today_svg}
  {lang_svg}
  {ftr_svg}
</svg>"""


# ── Main ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"[stats] Fetching data for @{USERNAME} …")
    stats = fetch_stats()
    print(f"[stats] Generating SVG → {OUT_FILE}")
    svg = generate_svg(stats)
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        f.write(svg)
    print(f"[stats] Done. ({len(svg):,} bytes)")
