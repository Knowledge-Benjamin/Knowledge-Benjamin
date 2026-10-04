#!/usr/bin/env python3
"""
generate_conquest.py
────────────────────
Generates the "Grid Conquest Dashboard" — tracking the user's contribution mastery.
"""

import os, sys
import requests
from datetime import datetime, timezone, timedelta

TOKEN = os.environ.get("GITHUB_TOKEN", "")
USERNAME = os.environ.get("GITHUB_USERNAME", "Knowledge-Benjamin")
OUT_FILE = "github-conquest-card.svg"

if not TOKEN:
    sys.exit("Error: GITHUB_TOKEN is not set.")

GQL_URL = "https://api.github.com/graphql"
GQL_HDR = {"Authorization": f"bearer {TOKEN}", "Content-Type": "application/json"}

_CALENDAR_Q = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      contributionCalendar {
        totalContributions
        weeks {
          contributionDays {
            contributionCount
            date
          }
        }
      }
    }
  }
}"""

def fetch_calendar():
    now = datetime.now(timezone.utc)
    ago_365 = now - timedelta(days=365)
    r = requests.post(GQL_URL, json={
        "query": _CALENDAR_Q, 
        "variables": {"login": USERNAME, "from": ago_365.isoformat(), "to": now.isoformat()}
    }, headers=GQL_HDR)
    r.raise_for_status()
    data = r.json().get("data", {}).get("user", {}).get("contributionsCollection", {}).get("contributionCalendar", {})
    return data

def build_svg(data):
    W, H = 860, 240
    PAD = 28
    BG, CARD = "#0D1117", "#161B22"
    BORDER = "#21262D"
    T1, T2, T3 = "#E6EDF3", "#8B949E", "#6E7681"
    
    weeks = data.get("weeks", [])
    total_days = 0
    active_days = 0
    
    for week in weeks:
        for day in week.get("contributionDays", []):
            total_days += 1
            if day.get("contributionCount", 0) > 0:
                active_days += 1
                
    pct = (active_days / total_days) * 100 if total_days > 0 else 0
    
    # Milestone logic
    milestones = [
        (25, "Bronze", "#D29922"),
        (50, "Silver", "#8B949E"),
        (75, "Gold", "#DB6D28"),
        (100, "Diamond", "#7C3AED")
    ]
    
    # Draw milestones
    ms_x = PAD
    ms_w = (W - 2*PAD - 3*12) / 4
    
    ms_svg = ""
    for i, (m_pct, m_name, m_color) in enumerate(milestones):
        unlocked = pct >= m_pct
        c_fill = CARD if not unlocked else f"{m_color}15"
        c_stroke = BORDER if not unlocked else m_color
        t_fill = T3 if not unlocked else m_color
        
        x = PAD + i * (ms_w + 12)
        ms_svg += f"""
        <rect x="{x}" y="80" width="{ms_w}" height="70" fill="{c_fill}" stroke="{c_stroke}" rx="8"/>
        <text x="{x + ms_w/2}" y="115" text-anchor="middle" font-size="20" font-weight="bold" fill="{t_fill}" font-family="sans-serif">{m_pct}%</text>
        <text x="{x + ms_w/2}" y="135" text-anchor="middle" font-size="12" fill="{t_fill}" font-family="monospace">{m_name} Mastery</text>
        """

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">
    <rect width="{W}" height="{H}" fill="{BG}" rx="12"/>
    <rect x="0" y="0" width="{W}" height="3" fill="#7C3AED" rx="1.5"/>
    
    <text x="{PAD}" y="45" font-size="20" font-weight="bold" fill="{T1}" font-family="sans-serif">Grid Conquest</text>
    <text x="{W-PAD}" y="45" text-anchor="end" font-size="14" fill="{T2}" font-family="monospace">Active Days: {active_days} / {total_days} ({pct:.1f}%)</text>
    
    <rect x="{PAD}" y="60" width="{W - 2*PAD}" height="8" fill="{BORDER}" rx="4"/>
    <rect x="{PAD}" y="60" width="{(W - 2*PAD) * (pct/100)}" height="8" fill="#7C3AED" rx="4"/>
    
    {ms_svg}
    
    <text x="{W/2}" y="195" text-anchor="middle" font-size="12" fill="{T3}" font-family="monospace">"The grid is your canvas. Paint it green."</text>
    <text x="{W/2}" y="215" text-anchor="middle" font-size="10" fill="{T3}" font-family="monospace">Updated automatically via GitHub Actions</text>
    </svg>"""
    return svg

if __name__ == "__main__":
    cal = fetch_calendar()
    svg = build_svg(cal)
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        f.write(svg)
    print("Generated github-conquest-card.svg")
