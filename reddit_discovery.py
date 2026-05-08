#!/usr/bin/env python3
"""
Reddit Vibe-Coded App Discovery Tool

Searches Reddit for recently-launched apps built with AI/vibe-coding tools
that already have traction — potential clients for professional dev services.

What is vibe coding?
  "Vibe coding" (term coined by Andrej Karpathy, Jan 2025) is the practice of
  building software almost entirely through AI prompts, with little or no
  traditional coding. The developer describes what they want and the AI writes
  the code. It's fast, accessible, but often produces brittle, unscalable apps
  — which is exactly the opportunity: these makers need real engineers.

Key vibe-coding platforms:
  • Cursor         https://cursor.sh          — AI-first code editor (most popular)
  • Lovable        https://lovable.dev        — "Build apps with AI" (React/Supabase)
  • Bolt            https://bolt.new           — StackBlitz AI full-stack builder
  • v0              https://v0.dev             — Vercel's AI UI generator
  • Replit          https://replit.com         — AI coding + hosting platform
  • Windsurf       https://codeium.com/windsurf — Codeium's AI editor
  • GitHub Copilot https://github.com/features/copilot — the OG AI pair programmer

Notable people in this space:
  • Andrej Karpathy (@karpathy)  — coined "vibe coding", ex-OpenAI/Tesla
  • Pieter Levels  (@levelsio)   — prolific indie hacker, ships fast, ~$4M ARR
  • Marc Lou       (@marc_louvion)— ships a new SaaS every month, 10k+ MRR
  • Theo Browne    (@t3dotgg)    — popular dev influencer, covers AI tools
  • Ben Tossell    (@bentossell) — no-code/AI builder, founder of Makerpad

The pitch: "You built something people love with AI. Let's make it production-ready."
"""

import argparse
import csv
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE_URL = "https://www.reddit.com/r/{subreddit}/search.json"
USER_AGENT = "reddit-app-discovery/1.0 (research tool; outreach for dev services)"
REQUEST_DELAY = 2.0   # seconds between requests (Reddit courtesy rate limit)
REQUEST_TIMEOUT = 15  # seconds before giving up on a request

DEFAULT_SUBREDDITS = [
    "SideProject",
    "startups",
    "IndieHackers",
    "webdev",
    "entrepreneur",
]

DEFAULT_KEYWORDS = [
    "vibe code",
    "vibe coded",
    "vibe coding",
    "built with cursor",
    "built with lovable",
    "built with bolt",
    "built with copilot",
    "built with v0",
    "built with replit",
]

# Pairs where BOTH terms must appear in the post text
COMBO_KEYWORDS = [
    ("no code", "just launched"),
    ("no code", "just shipped"),
    ("made with AI", "launch"),
    ("made with AI", "shipped"),
    ("AI generated", "launched"),
]

DEFAULT_DAYS = 30
DEFAULT_MIN_SCORE = 10
DEFAULT_MIN_COMMENTS = 5
MAX_PAGES = 3          # 3 pages x 100 posts = 300 posts per query max


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Find vibe-coded apps with traction on Reddit — potential clients.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--subreddits", nargs="+", default=DEFAULT_SUBREDDITS,
        metavar="SUB",
        help=f"Subreddits to search (default: {' '.join(DEFAULT_SUBREDDITS)})",
    )
    p.add_argument(
        "--keywords", nargs="+", default=None,
        metavar="KW",
        help="Override default keyword list",
    )
    p.add_argument(
        "--days", type=int, default=DEFAULT_DAYS,
        help=f"How many days back to look (default: {DEFAULT_DAYS}; Reddit reliably covers ~30)",
    )
    p.add_argument(
        "--min-score", type=int, default=DEFAULT_MIN_SCORE, dest="min_score",
        help=f"Minimum post score/upvotes (default: {DEFAULT_MIN_SCORE})",
    )
    p.add_argument(
        "--min-comments", type=int, default=DEFAULT_MIN_COMMENTS, dest="min_comments",
        help=f"Minimum number of comments (default: {DEFAULT_MIN_COMMENTS})",
    )
    p.add_argument(
        "--output-csv", default=None, dest="output_csv",
        metavar="FILE",
        help="Also save results to a CSV file (e.g. results.csv)",
    )
    args = p.parse_args()
    if args.days > 365:
        print(
            "Warning: Reddit search only reliably returns ~30 days of data "
            "regardless of --days value. Results beyond ~30 days may be sparse.",
            file=sys.stderr,
        )
    if args.days < 1:
        p.error("--days must be at least 1")
    return args


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def build_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT})
    return s


def fetch_posts(
    session: requests.Session,
    subreddit: str,
    query: str,
    after: str | None = None,
) -> list[dict]:
    """Single paginated GET. Returns list of raw Reddit post dicts."""
    params: dict = {
        "q": query,
        "sort": "new",
        "limit": 100,
        "restrict_sr": 1,
        "t": "month",
    }
    if after:
        params["after"] = after

    url = BASE_URL.format(subreddit=subreddit)
    for attempt in range(2):
        try:
            resp = session.get(url, params=params, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 429:
                wait = 6 if attempt == 0 else 0
                if wait:
                    print(f"  Rate limited on r/{subreddit}, waiting {wait}s...", file=sys.stderr)
                    time.sleep(wait)
                    continue
                print(f"  Still rate limited on r/{subreddit}, skipping.", file=sys.stderr)
                return []
            if resp.status_code == 403:
                print(f"  r/{subreddit} is private or quarantined, skipping.", file=sys.stderr)
                return []
            if resp.status_code != 200:
                print(f"  HTTP {resp.status_code} for r/{subreddit} query '{query}'", file=sys.stderr)
                return []
            data = resp.json()
            return data.get("data", {}).get("children", [])
        except (requests.exceptions.RequestException, ValueError) as exc:
            print(f"  Request error for r/{subreddit}: {exc}", file=sys.stderr)
            return []
    return []


def fetch_all_posts_for_query(
    session: requests.Session,
    subreddit: str,
    query: str,
) -> list[dict]:
    """Paginate up to MAX_PAGES pages for one subreddit+query pair."""
    results: list[dict] = []
    after: str | None = None

    for page in range(MAX_PAGES):
        page_data = fetch_posts(session, subreddit, query, after)
        if not page_data:
            break
        results.extend(page_data)
        last = page_data[-1].get("data", {})
        after = last.get("name")  # e.g. "t3_abc123"
        if len(page_data) < 100:
            break
        if page < MAX_PAGES - 1:
            time.sleep(REQUEST_DELAY)

    return results


# ---------------------------------------------------------------------------
# Data normalization
# ---------------------------------------------------------------------------

def normalize_post(raw: dict) -> dict | None:
    """Flatten Reddit's nested post dict. Returns None for deleted/missing posts."""
    try:
        author = raw.get("author", "[deleted]")
        if author in ("[deleted]", "AutoModerator", None):
            return None

        selftext = raw.get("selftext", "")
        if selftext == "[removed]":
            selftext = "[Post content removed]"

        return {
            "id":           raw["id"],
            "title":        raw["title"],
            "subreddit":    raw["subreddit"],
            "score":        int(raw.get("score", 0)),
            "num_comments": int(raw.get("num_comments", 0)),
            "url":          "https://reddit.com" + raw["permalink"],
            "author":       author,
            "created_utc":  datetime.fromtimestamp(raw["created_utc"], tz=timezone.utc),
            "excerpt":      selftext[:400].strip(),
        }
    except (KeyError, TypeError, ValueError):
        return None


def compute_traction_score(post: dict) -> float:
    # Comments weighted 2.5× — they signal real engagement, not just passive upvotes
    return post["score"] + post["num_comments"] * 2.5


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------

def is_within_days(post: dict, days: int) -> bool:
    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=days)
    return post["created_utc"] >= cutoff


def matches_combo_keyword(post: dict, pair: tuple[str, str]) -> bool:
    text = (post["title"] + " " + post["excerpt"]).lower()
    return pair[0].lower() in text and pair[1].lower() in text


# ---------------------------------------------------------------------------
# Main search orchestration
# ---------------------------------------------------------------------------

def search_reddit(
    session: requests.Session,
    subreddits: list[str],
    keywords: list[str],
    days: int,
    min_score: int,
    min_comments: int,
) -> list[dict]:
    seen_ids: set[str] = set()
    all_posts: list[dict] = []
    total_queries = len(subreddits) * (len(keywords) + len(COMBO_KEYWORDS))
    done = 0

    for subreddit in subreddits:
        # Single-keyword searches
        for keyword in keywords:
            done += 1
            print(
                f"\r  [{done}/{total_queries}] r/{subreddit}: '{keyword}' ...    ",
                end="",
                flush=True,
            )
            raw_posts = fetch_all_posts_for_query(session, subreddit, keyword)
            time.sleep(REQUEST_DELAY)

            for raw in raw_posts:
                post = normalize_post(raw.get("data", {}))
                if post is None or post["id"] in seen_ids:
                    continue
                if not is_within_days(post, days):
                    continue
                if post["score"] < min_score or post["num_comments"] < min_comments:
                    continue
                post["traction_score"] = compute_traction_score(post)
                seen_ids.add(post["id"])
                all_posts.append(post)

        # Combo-keyword searches (both terms must appear in post text)
        for combo in COMBO_KEYWORDS:
            done += 1
            print(
                f"\r  [{done}/{total_queries}] r/{subreddit}: '{combo[0]}' + '{combo[1]}' ...",
                end="",
                flush=True,
            )
            raw_posts = fetch_all_posts_for_query(session, subreddit, combo[0])
            time.sleep(REQUEST_DELAY)

            for raw in raw_posts:
                post = normalize_post(raw.get("data", {}))
                if post is None or post["id"] in seen_ids:
                    continue
                if not matches_combo_keyword(post, combo):
                    continue
                if not is_within_days(post, days):
                    continue
                if post["score"] < min_score or post["num_comments"] < min_comments:
                    continue
                post["traction_score"] = compute_traction_score(post)
                seen_ids.add(post["id"])
                all_posts.append(post)

    print()  # newline after progress line
    return sorted(all_posts, key=lambda p: p["traction_score"], reverse=True)


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def format_post(post: dict, rank: int) -> str:
    date_str = post["created_utc"].strftime("%Y-%m-%d")
    lines = [
        "=" * 80,
        (
            f"#{rank}  |  r/{post['subreddit']}  |  "
            f"Score: {post['score']}  |  Comments: {post['num_comments']}  |  "
            f"Traction: {post['traction_score']:.0f}"
        ),
        f"Title:  {post['title']}",
        f"Author: u/{post['author']}   |   Posted: {date_str}",
        f"URL:    {post['url']}",
    ]
    if post["excerpt"] and post["excerpt"] != "[Post content removed]":
        excerpt = post["excerpt"].replace("\n", " ")
        lines += ["---", f'"{excerpt[:300]}{"..." if len(post["excerpt"]) > 300 else ""}"']
    return "\n".join(lines)


def print_results(posts: list[dict], args: argparse.Namespace) -> None:
    print("\n" + "=" * 80)
    print("  REDDIT VIBE-CODED APP DISCOVERY")
    print("=" * 80)
    print(f"  Found:     {len(posts)} posts matching your criteria")
    print(f"  Subreddits: {', '.join('r/' + s for s in args.subreddits)}")
    print(f"  Time range: last {args.days} days")
    print(f"  Filters:   score >= {args.min_score}, comments >= {args.min_comments}")
    print("=" * 80)
    print()
    print("  WHAT IS VIBE CODING?")
    print("  Coined by Andrej Karpathy (Jan 2025): building software entirely through")
    print("  AI prompts with little/no traditional coding. Fast and fun, but the apps")
    print("  often break under load, have security holes, or hit walls when scaling.")
    print("  That's your opening — offer to make it production-ready.")
    print()
    print("  KEY PLATFORMS YOUR PROSPECTS USED:")
    print("  Cursor https://cursor.sh | Lovable https://lovable.dev | Bolt https://bolt.new")
    print("  v0 https://v0.dev | Replit https://replit.com | Windsurf https://codeium.com/windsurf")
    print()
    print("  NOTABLE PEOPLE TO FOLLOW FOR CONTEXT:")
    print("  @karpathy (coined vibe coding) | @levelsio (Pieter Levels, indie hacker)")
    print("  @marc_louvion (Marc Lou, serial SaaS) | @t3dotgg (Theo, dev influencer)")
    print("=" * 80)

    if not posts:
        print("\n  No results found. Try lowering --min-score or --min-comments.")
        return

    print()
    for i, post in enumerate(posts, 1):
        print(format_post(post, i))
        print()

    print("=" * 80)
    print(f"  Total: {len(posts)} potential leads | Sorted by traction score (score + comments×2.5)")
    print("=" * 80)


def save_csv(posts: list[dict], path: str) -> None:
    fieldnames = [
        "rank", "title", "subreddit", "score", "num_comments",
        "traction_score", "author", "url", "date_posted", "excerpt",
    ]
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for rank, post in enumerate(posts, 1):
            writer.writerow({
                "rank":           rank,
                "title":          post["title"],
                "subreddit":      post["subreddit"],
                "score":          post["score"],
                "num_comments":   post["num_comments"],
                "traction_score": f"{post['traction_score']:.1f}",
                "author":         post["author"],
                "url":            post["url"],
                "date_posted":    post["created_utc"].strftime("%Y-%m-%d"),
                "excerpt":        post["excerpt"],
            })
    print(f"\n  Saved {len(posts)} results to: {path}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    args = parse_args()
    keywords = args.keywords or DEFAULT_KEYWORDS

    print()
    print("Searching Reddit for vibe-coded apps with traction...")
    print(f"Subreddits: {', '.join(args.subreddits)}")
    print(f"Keywords:   {', '.join(keywords)}")
    print(f"Plus {len(COMBO_KEYWORDS)} combo-keyword pairs")
    print("(This may take a few minutes due to rate-limit courtesy delays)")
    print()

    session = build_session()
    start = time.time()

    posts = search_reddit(
        session=session,
        subreddits=args.subreddits,
        keywords=keywords,
        days=args.days,
        min_score=args.min_score,
        min_comments=args.min_comments,
    )

    elapsed = time.time() - start
    print(f"  Completed in {elapsed:.0f}s")

    print_results(posts, args)

    if args.output_csv:
        save_csv(posts, args.output_csv)


if __name__ == "__main__":
    main()
