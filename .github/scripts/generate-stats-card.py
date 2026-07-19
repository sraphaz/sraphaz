#!/usr/bin/env python3
"""Generate a GitHub stats SVG using split GraphQL queries.

The upstream github-readme-stats mega-query can hit GitHub's
"Resource limits for this query exceeded" for active accounts.
Fetching fields in smaller queries avoids that failure mode.
"""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys
from pathlib import Path


USERNAME = os.environ.get("STATS_USERNAME") or os.environ.get("GITHUB_REPOSITORY_OWNER") or "sraphaz"
OUTPUT = Path(os.environ.get("STATS_OUTPUT", "profile/stats.svg"))

TITLE_COLOR = "6e5494"
ICON_COLOR = "c9d1d9"
TEXT_COLOR = "a9fef7"
BG_COLOR = "0d1117"

ICON_STAR = (
    "M8 .25a.75.75 0 01.673.418l1.882 3.815 4.21.612a.75.75 0 01.416 1.279l-3.046 "
    "2.97.719 4.192a.75.75 0 01-1.088.791L8 12.347l-3.766 1.98a.75.75 0 "
    "01-1.088-.79l.72-4.194L.818 6.374a.75.75 0 01.416-1.28l4.21-.611L7.327.668A.75.75 "
    "0 018 .25zm0 2.445L6.615 5.5a.75.75 0 01-.564.41l-3.097.45 2.24 2.184a.75.75 0 "
    "01.216.664l-.528 3.084 2.769-1.456a.75.75 0 01.698 0l2.77 1.456-.53-3.084a.75.75 "
    "0 01.216-.664l2.24-2.183-3.096-.45a.75.75 0 01-.564-.41L8 2.694v.001z"
)
ICON_COMMIT = (
    "M1.643 3.143L.427 1.927A.25.25 0 000 2.104V5.75c0 .138.112.25.25.25h3.646a.25.25 "
    "0 00.177-.427L2.715 4.215a6.5 6.5 0 11-1.18 4.458.75.75 0 10-1.493.154 8.001 "
    "8.001 0 101.6-5.684zM7.75 4a.75.75 0 01.75.75v2.992l2.028.812a.75.75 0 "
    "01-.557 1.392l-2.5-1A.75.75 0 017 8.25v-3.5A.75.75 0 017.75 4z"
)
ICON_PR = (
    "M7.177 3.073L9.573.677A.25.25 0 0110 .854v4.792a.25.25 0 01-.427.177L7.177 "
    "3.427a.25.25 0 010-.354zM3.75 2.5a.75.75 0 100 1.5.75.75 0 000-1.5zm-2.25.75a2.25 "
    "2.25 0 113 2.122v5.256a2.251 2.251 0 11-1.5 0V5.372A2.25 2.25 0 011.5 3.25zM11 "
    "2.5h-1V4h1a1 1 0 011 1v5.628a2.251 2.251 0 101.5 0V5A2.5 2.5 0 0011 2.5zm1 "
    "10.25a.75.75 0 111.5 0 .75.75 0 01-1.5 0zM3.75 12a.75.75 0 100 1.5.75.75 0 "
    "000-1.5z"
)
ICON_ISSUE = (
    "M8 1.5a6.5 6.5 0 100 13 6.5 6.5 0 000-13zM0 8a8 8 0 1116 0A8 8 0 010 8zm9 3a1 1 "
    "0 11-2 0 1 1 0 012 0zm-.25-6.25a.75.75 0 00-1.5 0v3.5a.75.75 0 001.5 0v-3.5z"
)
ICON_CONTRIB = (
    "M2 2.5A2.5 2.5 0 014.5 0h8.75a.75.75 0 01.75.75v12.5a.75.75 0 01-.75.75h-2.5a.75.75 "
    "0 110-1.5h1.75v-2h-8a1 1 0 00-.714 1.7.75.75 0 01-1.072 1.05A2.495 2.495 0 012 "
    "11.5v-9zm10.5-1V9h-8c-.356 0-.694.074-1 .208V2.5a1 1 0 011-1h8zM5 12.25v3.25a.25.25 "
    "0 00.4.2l1.45-1.087a.25.25 0 01.3 0L8.6 15.7a.25.25 0 00.4-.2v-3.25a.25.25 0 "
    "00-.25-.25h-3.5a.25.25 0 00-.25.25z"
)


def gh_graphql(query: str) -> dict:
    result = subprocess.run(
        ["gh", "api", "graphql", "-f", f"query={query}"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"GraphQL failed:\n{result.stderr or result.stdout}")
    payload = json.loads(result.stdout)
    if payload.get("errors"):
        messages = "; ".join(err.get("message", str(err)) for err in payload["errors"])
        raise RuntimeError(f"GraphQL errors: {messages}")
    return payload["data"]


def format_number(value: int) -> str:
    if value >= 1000:
        scaled = value / 1000
        text = f"{scaled:.1f}".rstrip("0").rstrip(".")
        return f"{text}k"
    return str(value)


def exponential_cdf(x: float) -> float:
    return 1 - 2 ** -x


def log_normal_cdf(x: float) -> float:
    return x / (1 + x)


def calculate_rank(
    *,
    commits: int,
    prs: int,
    issues: int,
    reviews: int,
    stars: int,
    followers: int,
) -> tuple[str, float]:
    # Compatible with github-readme-stats calculateRank.js (last-year commits).
    commits_median, commits_weight = 250, 2
    prs_median, prs_weight = 50, 3
    issues_median, issues_weight = 25, 1
    reviews_median, reviews_weight = 2, 1
    stars_median, stars_weight = 50, 4
    followers_median, followers_weight = 10, 1

    total_weight = (
        commits_weight
        + prs_weight
        + issues_weight
        + reviews_weight
        + stars_weight
        + followers_weight
    )
    thresholds = [1, 12.5, 25, 37.5, 50, 62.5, 75, 87.5, 100]
    levels = ["S", "A+", "A", "A-", "B+", "B", "B-", "C+", "C"]

    rank = 1 - (
        commits_weight * exponential_cdf(commits / commits_median)
        + prs_weight * exponential_cdf(prs / prs_median)
        + issues_weight * exponential_cdf(issues / issues_median)
        + reviews_weight * exponential_cdf(reviews / reviews_median)
        + stars_weight * log_normal_cdf(stars / stars_median)
        + followers_weight * log_normal_cdf(followers / followers_median)
    ) / total_weight

    percentile = rank * 100
    level = levels[next(i for i, threshold in enumerate(thresholds) if percentile <= threshold)]
    return level, percentile


def fetch_stats(username: str) -> dict:
    # Split queries intentionally — a single mega-query can exceed GitHub resource limits.
    basic = gh_graphql(
        f"""
        query {{
          user(login: "{username}") {{
            name
            login
            followers {{ totalCount }}
            pullRequests {{ totalCount }}
            openIssues: issues(states: OPEN) {{ totalCount }}
            closedIssues: issues(states: CLOSED) {{ totalCount }}
          }}
        }}
        """
    )["user"]

    contributions = gh_graphql(
        f"""
        query {{
          user(login: "{username}") {{
            contributionsCollection {{
              totalCommitContributions
              restrictedContributionsCount
              totalPullRequestReviewContributions
            }}
          }}
        }}
        """
    )["user"]["contributionsCollection"]

    contributed_to = gh_graphql(
        f"""
        query {{
          user(login: "{username}") {{
            repositoriesContributedTo(
              first: 1
              contributionTypes: [COMMIT, ISSUE, PULL_REQUEST, REPOSITORY]
            ) {{
              totalCount
            }}
          }}
        }}
        """
    )["user"]["repositoriesContributedTo"]["totalCount"]

    repositories = gh_graphql(
        f"""
        query {{
          user(login: "{username}") {{
            repositories(ownerAffiliations: OWNER, isFork: false, first: 100) {{
              nodes {{
                stargazers {{ totalCount }}
              }}
            }}
          }}
        }}
        """
    )["user"]["repositories"]["nodes"]

    stars = sum(node["stargazers"]["totalCount"] for node in repositories)
    commits = (
        contributions["totalCommitContributions"]
        + contributions["restrictedContributionsCount"]
    )
    issues = basic["openIssues"]["totalCount"] + basic["closedIssues"]["totalCount"]
    prs = basic["pullRequests"]["totalCount"]
    reviews = contributions["totalPullRequestReviewContributions"]
    followers = basic["followers"]["totalCount"]
    display_name = basic["name"] or basic["login"]
    level, percentile = calculate_rank(
        commits=commits,
        prs=prs,
        issues=issues,
        reviews=reviews,
        stars=stars,
        followers=followers,
    )

    return {
        "name": display_name,
        "stars": stars,
        "commits": commits,
        "prs": prs,
        "issues": issues,
        "contribs": contributed_to,
        "reviews": reviews,
        "followers": followers,
        "rank": level,
        "percentile": percentile,
    }


def render_stat_row(y: int, delay_ms: int, icon_path: str, label: str, test_id: str, value: str) -> str:
    return f"""<g transform="translate(0, {y})">
    <g class="stagger" style="animation-delay: {delay_ms}ms" transform="translate(25, 0)">
    <svg data-testid="icon" class="icon" viewBox="0 0 16 16" version="1.1" width="16" height="16">
      <path fill-rule="evenodd" d="{icon_path}"/>
    </svg>
      <text class="stat  bold" x="25" y="12.5">{label}</text>
      <text
        class="stat  bold"
        x="219.01"
        y="12.5"
        data-testid="{test_id}"
      >{value}</text>
    </g>
  </g>"""


def render_svg(stats: dict) -> str:
    circumference = 2 * math.pi * 40
    # Match github-readme-stats: circle progress reflects 100 - percentile.
    progress = max(0.0, min(100.0, 100.0 - stats["percentile"]))
    dash_offset = circumference - (circumference * progress) / 100

    stars = format_number(stats["stars"])
    commits = format_number(stats["commits"])
    prs = format_number(stats["prs"])
    issues = format_number(stats["issues"])
    contribs = format_number(stats["contribs"])
    rank = stats["rank"]
    name = stats["name"]

    rows = "\n".join(
        [
            render_stat_row(0, 450, ICON_STAR, "Total Stars Earned:", "stars", stars),
            render_stat_row(25, 600, ICON_COMMIT, "Total Commits (last year):", "commits", commits),
            render_stat_row(50, 750, ICON_PR, "Total PRs:", "prs", prs),
            render_stat_row(75, 900, ICON_ISSUE, "Total Issues:", "issues", issues),
            render_stat_row(100, 1050, ICON_CONTRIB, "Contributed to (last year):", "contribs", contribs),
        ]
    )

    return f"""
      <svg
        width="467"
        height="195"
        viewBox="0 0 467 195"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        role="img"
        aria-labelledby="descId"
      >
        <title id="titleId">{name}'s GitHub Stats, Rank: {rank}</title>
        <desc id="descId">Total Stars Earned: {stats['stars']}, Total Commits  (last year) : {stats['commits']}, Total PRs: {stats['prs']}, Total Issues: {stats['issues']}, Contributed to (last year): {stats['contribs']}</desc>
        <style>
          .header {{
            font: 600 18px 'Segoe UI', Ubuntu, Sans-Serif;
            fill: #{TITLE_COLOR};
            animation: fadeInAnimation 0.8s ease-in-out forwards;
          }}
          @supports(-moz-appearance: auto) {{
            .header {{ font-size: 15.5px; }}
          }}

    .stat {{
      font: 600 14px 'Segoe UI', Ubuntu, "Helvetica Neue", Sans-Serif; fill: #{TEXT_COLOR};
    }}
    @supports(-moz-appearance: auto) {{
      .stat {{ font-size:12px; }}
    }}
    .stagger {{
      opacity: 0;
      animation: fadeInAnimation 0.3s ease-in-out forwards;
    }}
    .rank-text {{
      font: 800 24px 'Segoe UI', Ubuntu, Sans-Serif; fill: #{TEXT_COLOR};
      animation: scaleInAnimation 0.3s ease-in-out forwards;
    }}
    .bold {{ font-weight: 700 }}
    .icon {{
      fill: #{ICON_COLOR};
      display: block;
    }}

    .rank-circle-rim {{
      stroke: #{TITLE_COLOR};
      fill: none;
      stroke-width: 6;
      opacity: 0.2;
    }}
    .rank-circle {{
      stroke: #{TITLE_COLOR};
      stroke-dasharray: {circumference};
      fill: none;
      stroke-width: 6;
      stroke-linecap: round;
      opacity: 0.8;
      transform-origin: -10px 8px;
      transform: rotate(-90deg);
      animation: rankAnimation 1s forwards ease-in-out;
    }}

    @keyframes rankAnimation {{
      from {{
        stroke-dashoffset: {circumference};
      }}
      to {{
        stroke-dashoffset: {dash_offset};
      }}
    }}

      @keyframes scaleInAnimation {{
        from {{
          transform: translate(-5px, 5px) scale(0);
        }}
        to {{
          transform: translate(-5px, 5px) scale(1);
        }}
      }}
      @keyframes fadeInAnimation {{
        from {{
          opacity: 0;
        }}
        to {{
          opacity: 1;
        }}
      }}
        </style>

        <rect
          data-testid="card-bg"
          x="0.5"
          y="0.5"
          rx="4.5"
          height="99%"
          stroke="#e4e2e2"
          width="466"
          fill="#{BG_COLOR}"
          stroke-opacity="0"
        />

      <g
        data-testid="card-title"
        transform="translate(25, 35)"
      >
        <g transform="translate(0, 0)">
      <text
        x="0"
        y="0"
        class="header"
        data-testid="header"
      >{name}'s GitHub Stats</text>
    </g>
      </g>

        <g
          data-testid="main-card-body"
          transform="translate(0, 55)"
        >
    <g data-testid="rank-circle"
          transform="translate(390.5, 47.5)">
        <circle class="rank-circle-rim" cx="-10" cy="8" r="40" />
        <circle class="rank-circle" cx="-10" cy="8" r="40" />
        <g class="rank-text">
        <text x="-5" y="3" alignment-baseline="central" dominant-baseline="central" text-anchor="middle" data-testid="level-rank-icon">
          {rank}
        </text>
        </g>
      </g>
    <svg x="0" y="0">
      {rows}
    </svg>
        </g>
      </svg>
"""


def looks_like_error_svg(content: str) -> bool:
    markers = (
        "Something went wrong",
        "Resource limits for this query exceeded",
        "Maximum retries exceeded",
    )
    return any(marker in content for marker in markers)


def main() -> int:
    print(f"Generating stats card for {USERNAME} -> {OUTPUT}")
    stats = fetch_stats(USERNAME)
    svg = render_svg(stats)
    if looks_like_error_svg(svg):
        raise RuntimeError("Refusing to write an error SVG")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(svg, encoding="utf-8")
    print(
        "OK:",
        {
            "stars": stats["stars"],
            "commits": stats["commits"],
            "prs": stats["prs"],
            "issues": stats["issues"],
            "contribs": stats["contribs"],
            "rank": stats["rank"],
            "percentile": round(stats["percentile"], 2),
        },
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001 - surface clear CI failure
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
