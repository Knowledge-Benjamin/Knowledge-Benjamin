#!/usr/bin/env python3
"""
generate_stats.py
─────────────────
Fetches live GitHub statistics via GraphQL + REST APIs and writes a
premium, dark-themed SVG card to disk.

Environment variables required:
  GITHUB_TOKEN     — personal access token (or GITHUB_TOKEN from Actions)
  GITHUB_USERNAME  — GitHub login (defaults to Knowledge-Benjamin)
  STATS_OUT        — output file path   (defaults to github-stats-card.svg)
"""

import os, sys, math, textwrap
import requests
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional

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
SRCH_HDR = {**REST_HDR,                          "Accept": "application/vnd.github.cloak-preview+json"}


# ── Helpers ────────────────────────────────────────────────────────────────────
def gql(query: str, variables: Dict = None) -> Dict:
    resp = requests.post(GQL_URL, json={"query": query, "variables": variables or {}},
                         headers=GQL_HDR, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if "errors" in data:
        print(f"[GraphQL] {data['errors']}", file=sys.stderr)
    return data.get("data", {})


def rest(path: str, params: Dict = None, extra_headers: Dict = None) -> Any:
    h = {**REST_HDR, **(extra_headers or {})}
    resp = requests.get(f"{REST_URL}{path}", params=params, headers=h, timeout=30)
    resp.raise_for_status()
    return resp.json()


def fmt(val: int) -> str:
    """Format large numbers (1234 → 1,234 / 12000 → 12K)."""
    if val >= 10_000:
        return f"{val // 1000}K"
    return f"{val:,}"


# ── GraphQL Queries ────────────────────────────────────────────────────────────
_PROFILE_Q = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    name
    login
    createdAt
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
}
"""

_REPOS_Q = """
query($login: String!, $after: String) {
  user(login: $login) {
    repositories(ownerAffiliations: OWNER, first: 100, after: $after) {
      pageInfo { hasNextPage endCursor }
      nodes {
        stargazerCount
        forkCount
        watchers { totalCount }
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name color } }
        }
      }
    }
  }
}
"""

_CONTRIBS_Q = """
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
}
"""


# ── Fetch All Stats ────────────────────────────────────────────────────────────
def fetch_stats() -> Dict:
    now      = datetime.now(timezone.utc)
    today_0  = now.replace(hour=0, minute=0, second=0, microsecond=0)
    ago_30   = now - timedelta(days=30)
    ago_365  = now - timedelta(days=365)

    # 1. Profile + yearly contributions
    p    = gql(_PROFILE_Q, {"login": USERNAME, "from": ago_365.isoformat(), "to": now.isoformat()})
    user = p.get("user", {})
    yearly = user.get("contributions", {})

    # 2. Last-30-day commits
    t30 = gql(_CONTRIBS_Q, {"login": USERNAME, "from": ago_30.isoformat(), "to": now.isoformat()})
    commits_30d = (t30.get("user", {})
                     .get("contributionsCollection", {})
                     .get("totalCommitContributions", 0))

    # 3. Today's commits + repos
    td  = gql(_CONTRIBS_Q, {"login": USERNAME, "from": today_0.isoformat(), "to": now.isoformat()})
    today_col       = td.get("user", {}).get("contributionsCollection", {})
    commits_today   = today_col.get("totalCommitContributions", 0)
    today_repos_raw = today_col.get("commitContributionsByRepository", [])
    today_public    = [r["repository"]["nameWithOwner"]
                       for r in today_repos_raw if not r["repository"]["isPrivate"]]
    today_private_n = sum(1 for r in today_repos_raw if r["repository"]["isPrivate"])

    # 4. All owned repos — paginate for accurate aggregate stats
    all_repos, cursor = [], None
    while True:
        rd = gql(_REPOS_Q, {"login": USERNAME, "after": cursor})
        page = rd.get("user", {}).get("repositories", {})
        all_repos.extend(page.get("nodes", []))
        pi = page.get("pageInfo", {})
        if not pi.get("hasNextPage"):
            break
        cursor = pi["endCursor"]

    stars    = sum(r.get("stargazerCount", 0)               for r in all_repos)
    forks    = sum(r.get("forkCount", 0)                    for r in all_repos)
    watchers = sum(r.get("watchers", {}).get("totalCount", 0) for r in all_repos)

    # 5. Language breakdown across all repos
    lang_map: Dict[str, Dict] = {}
    for repo in all_repos:
        for edge in repo.get("languages", {}).get("edges", []):
            n = edge["node"]["name"]
            c = edge["node"].get("color") or "#586069"
            s = edge.get("size", 0)
            if n not in lang_map:
                lang_map[n] = {"size": 0, "color": c}
            lang_map[n]["size"] += s

    total_sz = sum(v["size"] for v in lang_map.values()) or 1
    languages = sorted(
        [{"name": k, "color": v["color"],
          "pct": round(v["size"] / total_sz * 100, 1)}
         for k, v in lang_map.items()],
        key=lambda x: x["pct"], reverse=True
    )[:8]

    # 6. Issues closed — REST search
    try:
        ic = rest("/search/issues",
                  params={"q": f"type:issue author:{USERNAME} is:closed", "per_page": 1},
                  extra_headers=SRCH_HDR)
        issues_closed = ic.get("total_count", 0)
    except Exception as e:
        print(f"[WARN] issues_closed: {e}", file=sys.stderr)
        issues_closed = 0

    # 7. Parse join date
    created_raw = user.get("createdAt", "")
    try:
        joined = datetime.fromisoformat(
            created_raw.replace("Z", "+00:00")).strftime("%b %Y")
    except Exception:
        joined = "—"

    return {
        "name":              user.get("name") or USERNAME,
        "login":             user.get("login", USERNAME),
        "joined":            joined,
        "followers":         user.get("followers", {}).get("totalCount", 0),
        "following":         user.get("following", {}).get("totalCount", 0),
        "organizations":     user.get("organizations", {}).get("totalCount", 0),
        "total_repos":       user.get("allRepos", {}).get("totalCount", 0),
        "stars":             stars,
        "forks":             forks,
        "watchers":          watchers,
        "commits_year":      yearly.get("totalCommitContributions", 0),
        "commits_30d":       commits_30d,
        "commits_today":     commits_today,
        "prs_opened":        yearly.get("totalPullRequestContributions", 0),
        "prs_reviewed":      yearly.get("totalPullRequestReviewContributions", 0),
        "issues_opened":     yearly.get("totalIssueContributions", 0),
        "issues_closed":     issues_closed,
        "repos_contributed": yearly.get("totalRepositoriesWithContributedCommits", 0),
        "today_public":      today_public,
        "today_private_n":   today_private_n,
        "languages":         languages,
        "updated_at":        now.strftime("%b %d, %Y · %H:%M UTC"),
    }


# ── SVG Builder ────────────────────────────────────────────────────────────────
# Palette
BG, CARD = "#0D1117", "#161B22"
BORDER   = "#30363D"
T1, T2   = "#E6EDF3", "#8B949E"
ACC      = "#7957D5"
ACC2     = "#4F46E5"
GRN      = "#3FB950"
YLW      = "#D29922"
BLU      = "#58A6FF"


def esc(s: str) -> str:
    return (s.replace("&", "&amp;")
             .replace("<", "&lt;")
             .replace(">", "&gt;")
             .replace('"', "&quot;"))


def stat_card(x: float, y: float, w: float, h: float,
              label: str, value: str, sub: str = "",
              accent: str = ACC) -> str:
    """A single stat tile with label, big value, and optional sub-label."""
    mx = x + w / 2
    return (
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{CARD}" rx="8"/>\n'
        f'<rect x="{x}" y="{y}" width="3" height="{h}" fill="{accent}" rx="1.5"/>\n'
        f'<text x="{mx}" y="{y + 24}" text-anchor="middle" '
        f'font-size="11" fill="{T2}" font-family="monospace">{esc(label)}</text>\n'
        f'<text x="{mx}" y="{y + 50}" text-anchor="middle" '
        f'font-size="26" font-weight="700" fill="{T1}" letter-spacing="-0.5">{esc(value)}</text>\n'
        + (f'<text x="{mx}" y="{y + 66}" text-anchor="middle" '
           f'font-size="10" fill="{T2}">{esc(sub)}</text>\n' if sub else "")
    )


def lang_bar(x: float, y: float, bar_w: float, lang: Dict, bar_h: int = 7) -> str:
    fill = int(bar_w * lang["pct"] / 100)
    name = lang["name"][:16] + ("…" if len(lang["name"]) > 16 else "")
    color = lang["color"] or ACC
    return (
        f'<circle cx="{x + 6}" cy="{y + 7}" r="5" fill="{color}"/>\n'
        f'<text x="{x + 16}" y="{y + 12}" font-size="12" fill="{T1}" '
        f'font-family="\'Segoe UI\',sans-serif">{esc(name)}</text>\n'
        f'<text x="{x + bar_w + 90}" y="{y + 12}" font-size="11" fill="{T2}" '
        f'text-anchor="end">{lang["pct"]}%</text>\n'
        f'<rect x="{x}" y="{y + 18}" width="{bar_w}" height="{bar_h}" fill="{BORDER}" rx="3.5"/>\n'
        f'<rect x="{x}" y="{y + 18}" width="{max(fill, 4)}" height="{bar_h}" fill="{color}" rx="3.5"/>\n'
    )


def commit_bar(x: float, y: float, label: str, val: int,
               pct: float, bar_w: float = 340, bar_h: int = 8) -> str:
    fill = int(bar_w * min(pct, 100) / 100)
    return (
        f'<text x="{x}" y="{y + 12}" font-size="12" fill="{T2}" '
        f'font-family="\'Segoe UI\',sans-serif">{esc(label)}</text>\n'
        f'<text x="{x + 155}" y="{y + 12}" font-size="13" font-weight="600" '
        f'fill="{T1}" text-anchor="end">{esc(fmt(val))}</text>\n'
        f'<rect x="{x + 162}" y="{y + 4}" width="{bar_w}" height="{bar_h}" fill="{BORDER}" rx="4"/>\n'
        f'<rect x="{x + 162}" y="{y + 4}" width="{max(fill, 6)}" height="{bar_h}" '
        f'fill="url(#bar-grad)" rx="4"/>\n'
    )


def kv_row(x: float, y: float, label: str, value: str, color: str = T1) -> str:
    return (
        f'<text x="{x}" y="{y}" font-size="12" fill="{T2}" '
        f'font-family="\'Segoe UI\',sans-serif">{esc(label)}</text>\n'
        f'<text x="{x + 200}" y="{y}" font-size="12" font-weight="600" '
        f'fill="{color}" text-anchor="end">{esc(value)}</text>\n'
    )


def generate_svg(s: Dict) -> str:
    W   = 900
    PAD = 28
    GAP = 12

    # ── Section heights ────────────────────────────────────────────────────────
    HEADER_H   = 76
    PROFILE_H  = 108   # profile grid of 8 cards
    COMMIT_H   = 114
    PRISS_H    = 110   # PRs + issues
    TODAY_H    = 80 if s["commits_today"] == 0 else 96
    LANG_H     = len(s["languages"]) * 34 + 52
    FOOTER_H   = 32

    TOTAL_H = (
        HEADER_H + GAP
        + PROFILE_H + GAP
        + COMMIT_H + GAP
        + PRISS_H + GAP
        + TODAY_H + GAP
        + LANG_H + GAP
        + FOOTER_H + PAD
    )

    # ── Y cursors ──────────────────────────────────────────────────────────────
    yH  = 0
    yP  = yH + HEADER_H + GAP
    yCM = yP + PROFILE_H + GAP
    yPR = yCM + COMMIT_H + GAP
    yTD = yPR + PRISS_H + GAP
    yLG = yTD + TODAY_H + GAP
    yFT = yLG + LANG_H + GAP

    # ── Commit bars (normalise to year) ───────────────────────────────────────
    cy   = s["commits_year"]
    c30  = s["commits_30d"]
    ctd  = s["commits_today"]
    yr_pct = 100.0
    d30_pct = (c30 / cy * 100) if cy else (100.0 if c30 else 0.0)
    td_pct  = (ctd / cy * 100) if cy else (100.0 if ctd else 0.0)

    # ── Today's activity text ─────────────────────────────────────────────────
    if s["commits_today"] > 0:
        pub  = s["today_public"]
        priv = s["today_private_n"]
        total_repos_today = len(pub) + priv
        c_word = "commit" if ctd == 1 else "commits"
        r_word = "repo"   if total_repos_today == 1 else "repos"
        today_line1 = f'{fmt(ctd)} {c_word} across {total_repos_today} {r_word} today'
        parts = []
        if pub:
            shown = pub[:2]
            rest_n = len(pub) - len(shown)
            parts.append(", ".join(r.split("/")[-1] for r in shown)
                         + (f" +{rest_n} more" if rest_n else ""))
        if priv:
            parts.append(f"+{priv} private")
        today_line2 = "  ·  ".join(parts) if parts else ""
    else:
        today_line1 = "No commits today — rest is part of the process."
        today_line2 = ""

    # ── Profile cards (2 rows × 4) ────────────────────────────────────────────
    card_w = (W - 2 * PAD - 3 * GAP) / 4
    card_h = 78

    profile_cards = [
        ("TOTAL REPOS",   fmt(s["total_repos"]),   "owned",          ACC),
        ("STARS",         fmt(s["stars"]),          "across all repos", YLW),
        ("FORKS",         fmt(s["forks"]),          "across all repos", BLU),
        ("WATCHERS",      fmt(s["watchers"]),       "across all repos", GRN),
        ("FOLLOWERS",     fmt(s["followers"]),      "",               ACC),
        ("FOLLOWING",     fmt(s["following"]),      "",               ACC2),
        ("ORGANIZATIONS", fmt(s["organizations"]), "",               BLU),
        ("CONTRIBUTED TO", fmt(s["repos_contributed"]), "repos (past year)", GRN),
    ]

    cards_svg = ""
    for i, (lbl, val, sub, color) in enumerate(profile_cards):
        row, col = divmod(i, 4)
        cx = PAD + col * (card_w + GAP)
        cy_pos = yP + row * (card_h + GAP)
        cards_svg += stat_card(cx, cy_pos, card_w, card_h, lbl, val, sub, color)

    # ── Commit bars ───────────────────────────────────────────────────────────
    cm_left  = PAD
    cm_right = W / 2 + PAD / 2
    BAR_W    = W / 2 - PAD * 2 - 162 - 16

    commits_svg = (
        f'<rect x="{PAD}" y="{yCM}" width="{W - 2*PAD}" height="{COMMIT_H}" fill="{CARD}" rx="8"/>\n'
        f'<text x="{PAD + 16}" y="{yCM + 24}" font-size="12" font-weight="600" fill="{T2}" '
        f'font-family="monospace" letter-spacing="1">COMMIT ACTIVITY  ·  PAST 12 MONTHS</text>\n'
        + commit_bar(PAD + 16, yCM + 34, "Total commits",    cy,  yr_pct,  BAR_W)
        + commit_bar(PAD + 16, yCM + 62, "Last 30 days",     c30, d30_pct, BAR_W)
        + commit_bar(PAD + 16, yCM + 90, "Today",            ctd, td_pct,  BAR_W)
    )

    # ── PRs + Issues ──────────────────────────────────────────────────────────
    pr_x   = PAD
    iss_x  = W / 2 + PAD / 2
    half_w = W / 2 - PAD * 1.5

    pr_svg = (
        f'<rect x="{pr_x}" y="{yPR}" width="{half_w}" height="{PRISS_H}" fill="{CARD}" rx="8"/>\n'
        f'<text x="{pr_x + 16}" y="{yPR + 24}" font-size="12" font-weight="600" fill="{T2}" '
        f'font-family="monospace" letter-spacing="1">PULL REQUESTS</text>\n'
        + kv_row(pr_x + 16, yPR + 52, "PRs opened",   fmt(s["prs_opened"]),   GRN)
        + kv_row(pr_x + 16, yPR + 76, "PRs reviewed", fmt(s["prs_reviewed"]), BLU)
    )

    iss_svg = (
        f'<rect x="{iss_x}" y="{yPR}" width="{half_w}" height="{PRISS_H}" fill="{CARD}" rx="8"/>\n'
        f'<text x="{iss_x + 16}" y="{yPR + 24}" font-size="12" font-weight="600" fill="{T2}" '
        f'font-family="monospace" letter-spacing="1">ISSUES</text>\n'
        + kv_row(iss_x + 16, yPR + 52, "Issues opened", fmt(s["issues_opened"]), YLW)
        + kv_row(iss_x + 16, yPR + 76, "Issues closed", fmt(s["issues_closed"]), GRN)
    )

    # ── Today's activity ──────────────────────────────────────────────────────
    dot_color = GRN if s["commits_today"] > 0 else T2
    today_svg = (
        f'<rect x="{PAD}" y="{yTD}" width="{W - 2*PAD}" height="{TODAY_H}" fill="{CARD}" rx="8"/>\n'
        f'<circle cx="{PAD + 20}" cy="{yTD + 24}" r="5" fill="{dot_color}"/>\n'
        f'<text x="{PAD + 34}" y="{yTD + 29}" font-size="12" font-weight="600" fill="{T1}" '
        f'font-family="\'Segoe UI\',sans-serif">{esc(today_line1)}</text>\n'
        + (f'<text x="{PAD + 34}" y="{yTD + 53}" font-size="11" fill="{T2}" '
           f'font-family="\'Segoe UI\',sans-serif">{esc(today_line2)}</text>\n'
           if today_line2 else "")
    )

    # ── Language bars ─────────────────────────────────────────────────────────
    LANG_BAR_W = W - 2 * PAD - 100

    lang_header = (
        f'<rect x="{PAD}" y="{yLG}" width="{W - 2*PAD}" height="{LANG_H}" fill="{CARD}" rx="8"/>\n'
        f'<text x="{PAD + 16}" y="{yLG + 24}" font-size="12" font-weight="600" fill="{T2}" '
        f'font-family="monospace" letter-spacing="1">TOP LANGUAGES  ·  BY BYTES</text>\n'
    )

    lang_items = ""
    for i, lang in enumerate(s["languages"]):
        ly = yLG + 36 + i * 34
        lang_items += lang_bar(PAD + 16, ly, LANG_BAR_W, lang)

    # ── Footer ────────────────────────────────────────────────────────────────
    footer_svg = (
        f'<text x="{W / 2}" y="{yFT + 20}" text-anchor="middle" font-size="11" '
        f'fill="{T2}" font-family="monospace">Updated {esc(s["updated_at"])}'
        f'  ·  github.com/{esc(s["login"])}</text>\n'
    )

    # ── Assemble SVG ──────────────────────────────────────────────────────────
    header_svg = f"""
  <!-- HEADER -->
  <text x="{PAD}" y="{yH + 36}" font-size="22" font-weight="700" fill="{T1}"
        font-family="'-apple-system','Segoe UI',sans-serif">{esc(s["name"])}</text>
  <text x="{PAD}" y="{yH + 58}" font-size="12" fill="{T2}"
        font-family="monospace">github.com/{esc(s["login"])}
  </text>
  <text x="{W - PAD}" y="{yH + 36}" text-anchor="end" font-size="12" fill="{T2}"
        font-family="monospace">Member since {esc(s["joined"])}</text>
  <line x1="{PAD}" y1="{yH + 68}" x2="{W - PAD}" y2="{yH + 68}" stroke="{BORDER}" stroke-width="1"/>
"""

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg"
     width="{W}" height="{TOTAL_H}"
     viewBox="0 0 {W} {TOTAL_H}">
  <defs>
    <linearGradient id="bar-grad" x1="0%" y1="0%" x2="100%" y2="0%">
      <stop offset="0%"   stop-color="{ACC}"/>
      <stop offset="100%" stop-color="{ACC2}"/>
    </linearGradient>
    <linearGradient id="top-line" x1="0%" y1="0%" x2="100%" y2="0%">
      <stop offset="0%"   stop-color="{ACC}"/>
      <stop offset="100%" stop-color="{ACC2}"/>
    </linearGradient>
  </defs>

  <!-- Background -->
  <rect width="{W}" height="{TOTAL_H}" fill="{BG}" rx="12"/>

  <!-- Top accent line -->
  <rect x="0" y="0" width="{W}" height="3" fill="url(#top-line)" rx="1.5"/>

  {header_svg}

  <!-- Profile stat cards -->
  {cards_svg}

  <!-- Commit activity -->
  {commits_svg}

  <!-- Pull requests -->
  {pr_svg}

  <!-- Issues -->
  {iss_svg}

  <!-- Today's activity -->
  {today_svg}

  <!-- Languages -->
  {lang_header}{lang_items}

  <!-- Footer -->
  {footer_svg}
</svg>"""

    return svg


# ── Main ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"[stats] Fetching data for @{USERNAME} …")
    stats = fetch_stats()

    print(f"[stats] Generating SVG → {OUT_FILE}")
    svg = generate_svg(stats)

    with open(OUT_FILE, "w", encoding="utf-8") as f:
        f.write(svg)

    print(f"[stats] Done. ({len(svg):,} bytes)")
