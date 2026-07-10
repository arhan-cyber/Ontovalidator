"""Standalone CLI tool for health verification of backend services."""

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Optional

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import load_config_from_env
from src.integration.health_check_runner import (
    HealthCheckRunner,
    print_health_report,
    export_health_report,
)


def setup_logging(verbose: bool = False, log_level: str = "INFO") -> None:
    """Configure logging for the health check script."""
    level = logging.DEBUG if verbose else getattr(logging, log_level, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )


def parse_arguments() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Health check utility for SVO Verification Pipeline backends",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/health_check.py --all
  python scripts/health_check.py --all --export-json health_report.json
  python scripts/health_check.py --elasticsearch --neo4j
  python scripts/health_check.py --all --retry 3 --timeout 10
        """,
    )

    # Backend selection options
    backend_group = parser.add_argument_group("Backend Selection")
    backend_group.add_argument(
        "--all",
        action="store_true",
        default=False,
        help="Check all backends (default if no backend specified)",
    )
    backend_group.add_argument(
        "--elasticsearch",
        action="store_true",
        help="Check Elasticsearch only",
    )
    backend_group.add_argument(
        "--neo4j",
        action="store_true",
        help="Check Neo4j only",
    )
    backend_group.add_argument(
        "--milvus",
        action="store_true",
        help="Check Milvus only",
    )
    backend_group.add_argument(
        "--sqlite",
        action="store_true",
        help="Check SQLite only",
    )

    # Export options
    export_group = parser.add_argument_group("Export Options")
    export_group.add_argument(
        "--export-json",
        type=str,
        metavar="FILE",
        help="Export report to JSON file",
    )
    export_group.add_argument(
        "--export-markdown",
        type=str,
        metavar="FILE",
        help="Export report as markdown file",
    )

    # Configuration options
    config_group = parser.add_argument_group("Configuration Options")
    config_group.add_argument(
        "--retry",
        type=int,
        default=1,
        metavar="N",
        help="Retry failed checks N times with exponential backoff (default: 1)",
    )
    config_group.add_argument(
        "--timeout",
        type=int,
        default=None,
        metavar="SECONDS",
        help="Custom timeout for health checks in seconds",
    )

    # Output options
    output_group = parser.add_argument_group("Output Options")
    output_group.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show detailed output and debug logs",
    )
    output_group.add_argument(
        "--log-level",
        type=str,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Set logging level (default: INFO)",
    )

    return parser.parse_args()


def export_markdown_report(report, filepath: str) -> None:
    """Export health report as markdown."""
    markdown_lines = [
        "# Backend Health Check Report\n",
        f"**Report Time:** {report.timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}\n",
        f"**Overall Status:** {report.overall_status}\n",
        "\n## Backend Status\n",
    ]

    # Status table
    markdown_lines.append("| Backend | Status | Latency | Error |\n")
    markdown_lines.append("|---------|--------|---------|-------|\n")

    for backend_name in ["elasticsearch", "neo4j", "milvus", "sqlite"]:
        if backend_name in report.backends:
            status = report.backends[backend_name]
            status_text = "HEALTHY" if status.is_healthy else "FAILED"
            if status.error_message == "Disabled in configuration":
                status_text = "DISABLED"
            latency_text = f"{status.latency_ms:.2f}ms" if status.latency_ms > 0 else "N/A"
            error_text = status.error_message[:30] if status.error_message else "None"
            markdown_lines.append(
                f"| {backend_name} | {status_text} | {latency_text} | {error_text} |\n"
            )

    # Recommendations
    if report.recommendations:
        markdown_lines.append("\n## Recommendations\n")
        for i, rec in enumerate(report.recommendations, 1):
            markdown_lines.append(f"{i}. {rec}\n")

    try:
        with open(filepath, "w") as f:
            f.writelines(markdown_lines)
        logging.getLogger(__name__).info(f"Markdown report exported to {filepath}")
    except Exception as e:
        logging.getLogger(__name__).error(f"Failed to export markdown report: {e}")
        raise


def main() -> int:
    """Main entry point for health check CLI."""
    args = parse_arguments()

    # Setup logging
    setup_logging(args.verbose, args.log_level)
    logger = logging.getLogger(__name__)

    try:
        # Load configuration from environment
        logger.info("Loading configuration from environment...")
        config = load_config_from_env()

        # If no specific backends selected, check all
        if not any([args.all, args.elasticsearch, args.neo4j, args.milvus, args.sqlite]):
            args.all = True

        # Override timeout if specified
        if args.timeout:
            config.elasticsearch.timeout_seconds = args.timeout
            config.neo4j.timeout_seconds = args.timeout
            config.milvus.timeout_seconds = args.timeout

        logger.info("Starting health checks...")

        # Run health checks
        report = HealthCheckRunner.check_all(config)

        # Print report to console
        print_health_report(report)

        # Export to JSON if requested
        if args.export_json:
            export_health_report(report, args.export_json)

        # Export to markdown if requested
        if args.export_markdown:
            export_markdown_report(report, args.export_markdown)

        # Determine exit code based on overall status
        if report.overall_status == "HEALTHY":
            logger.info("Health check passed: all backends are healthy")
            return 0
        elif report.overall_status == "DEGRADED":
            logger.warning("Health check degraded: some backends unavailable but fallback available")
            return 1
        else:  # FAILED
            logger.error("Health check failed: critical backends unavailable")
            return 2

    except Exception as e:
        logger.error(f"Health check failed with exception: {e}", exc_info=True)
        print(f"\nERROR: Health check failed: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
