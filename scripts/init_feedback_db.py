"""Create (or inspect) the feedback database used to record verdict corrections."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import load_config_from_env
from src.feedback import FeedbackDashboard, FeedbackRecorder


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db-path",
        default=None,
        help="Feedback database path (default: ONTO_FEEDBACK_DB_PATH or feedback.db)",
    )
    parser.add_argument("--show-stats", action="store_true", help="Print current feedback metrics")
    parser.add_argument("--days", type=int, default=30, help="Window for --show-stats (default: 30)")
    args = parser.parse_args()

    db_path = args.db_path or load_config_from_env().feedback_db_path
    recorder = FeedbackRecorder(db_path)
    print(f"Feedback database ready: {db_path}")

    if args.show_stats:
        print(json.dumps(FeedbackDashboard(recorder).compute_metrics(args.days), indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
