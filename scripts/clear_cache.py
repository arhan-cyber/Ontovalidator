"""Cache maintenance: drop expired entries, or purge the cache entirely."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.cache import CacheEngine
from src.config import load_config_from_env

ENTRY_TYPES = ("embedding", "retrieval", "verdict", "feedback_verdict")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db-path",
        default=None,
        help="Cache database path (default: ONTO_CACHE_DB_PATH or cache.db)",
    )
    parser.add_argument("--all", action="store_true", help="Delete every entry, not just expired ones")
    parser.add_argument(
        "--type",
        choices=ENTRY_TYPES,
        help="Restrict --all to a single entry type",
    )
    parser.add_argument("--stats", action="store_true", help="Print cache statistics and exit")
    args = parser.parse_args()

    cache = CacheEngine(args.db_path or load_config_from_env().cache_db_path)

    if args.stats:
        print(json.dumps(cache.get_stats(), indent=2))
        return 0

    if args.all:
        removed = cache.clear_all(args.type)
        scope = args.type or "all types"
        print(f"Removed {removed} cache entries ({scope}).")
    else:
        removed = cache.clear_expired()
        print(f"Removed {removed} expired cache entries.")

    print(json.dumps(cache.get_stats(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
