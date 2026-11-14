import argparse
import sys

from . import core


def main(argv=None):
    p = argparse.ArgumentParser(prog="reddit-search", description="Search Reddit via Arctic Shift")
    sp = p.add_subparsers(dest="cmd", required=True)
    s = sp.add_parser("subreddits", help="find subreddits by name prefix")
    s.add_argument("prefix"); s.add_argument("--limit", type=int, default=15)
    for name in ("search", "comments"):
        s = sp.add_parser(name, help="search posts" if name == "search" else "search comments")
        s.add_argument("subreddit"); s.add_argument("query")
        s.add_argument("--limit", type=int, default=25)
        s.add_argument("--after"); s.add_argument("--before")
        s.add_argument("--sort", choices=["asc", "desc"], default="desc")
    s = sp.add_parser("thread", help="show a post and its comments")
    s.add_argument("post"); s.add_argument("--max-comments", type=int, default=100)
    a = p.parse_args(argv)
    try:
        if a.cmd == "subreddits":
            out = core.find_subreddits(a.prefix, a.limit)
        elif a.cmd == "search":
            out = core.search_posts(a.subreddit, a.query, a.limit, a.after, a.before, a.sort)
        elif a.cmd == "comments":
            out = core.search_comments(a.subreddit, a.query, a.limit, a.after, a.before, a.sort)
        else:
            out = core.get_thread(a.post, a.max_comments)
    except core.RedditSearchError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
