#!/usr/bin/env python3
"""Phase 4: CLI entry point for Thelawala Search Engine.

Usage:
    thelawala-search <query> [--top N]
    thelawala-search batch <input_file> --output <output_file> [--top N]

Arguments:
    <query>           Search query string
    <input_file>      Path to text file with one query per line (batch mode)
    <output_file>     Path to write JSONL output (batch mode)

Options:
    --top N, -n N     Number of results to return (default: 10)
    --help            Show this help message and exit
"""
import sys
import json
import argparse
import logging
import os
import traceback

# Ensure the project root (parent of src/) is on sys.path so that
# "from src.search import ..." works when running "python src/cli.py" directly.
# This is a standard Python pattern; do not remove.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from src.search import search_query, run_batch
from src.clean import assign_stock_state

# Configure logging to stderr for diagnostics
logging.basicConfig(
    format="%(levelname)s: %(message)s",
    level=logging.INFO,
    stream=sys.stderr,
)

logger = logging.getLogger("thelawala-search")


def main(argv=None):
    """Main entry point for the CLI."""
    parser = argparse.ArgumentParser(
        prog="thelawala-search",
        description="Thelawala Search Engine — search products by query.",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # --- Single query subcommand ---
    single_parser = subparsers.add_parser(
        "query", help="Search for a single query and print ranked results."
    )
    single_parser.add_argument(
        "query",
        metavar="QUERY",
        type=str,
        help="The search query string",
    )
    single_parser.add_argument(
        "--top", "-n",
        type=int,
        default=10,
        metavar="N",
        help="Number of results to return (default: 10)",
    )

    # --- Batch subcommand ---
    batch_parser = subparsers.add_parser(
        "batch", help="Run batch search on queries from a text file."
    )
    batch_parser.add_argument(
        "input_file",
        metavar="INPUT",
        type=str,
        help="Path to text file with one query per line",
    )
    batch_parser.add_argument(
        "--output", "-o",
        type=str,
        required=True,
        metavar="OUTPUT",
        help="Path to write results.jsonl",
    )
    batch_parser.add_argument(
        "--top", "-n",
        type=int,
        default=10,
        metavar="N",
        help="Number of results per query (default: 10)",
    )

    args = parser.parse_args(argv)

    if args.command == "query":
        run_single_query(args)
    elif args.command == "batch":
        run_batch_cli(args)
    else:
        parser.print_help()
        sys.exit(2)


def run_single_query(args):
    """Run a single search query and print results."""
    try:
        results = search_query(args.query, top_n=args.top)

        if not results:
            logger.info("No results found for query: %s", args.query)
            # Print nothing for machine-readable silence; could also print note
            sys.stdout.write("(no results)\\n")
            sys.exit(0)

        # Print one sku_id per line (human-readable) or JSON (machine-readable)
        # Per assignment: machine-readable JSONL preferred on stdout; diagnostics on stderr
        output = json.dumps({"query": args.query, "results": results})
        sys.stdout.write(output + "\n")
        sys.exit(0)

    except Exception as e:
        logger.error("Error during search: %s", e, exc_info=True)
        sys.stderr.write("Error: " + str(e) + "\n")
        sys.exit(2)


def run_batch_cli(args):
    """Run batch search from input file and write JSONL output."""
    input_path = args.input_file
    output_path = args.output
    top_n = args.top

    # Validate input file exists
    if not os.path.isfile(input_path):
        sys.stderr.write("Error: input file not found: " + input_path + "\n")
        sys.exit(2)

    # Validate output directory is writable
    output_dir = os.path.dirname(output_path)
    if output_dir and not os.path.isdir(output_dir):
        try:
            os.makedirs(output_dir, exist_ok=True)
        except OSError as e:
            sys.stderr.write("Error: cannot create output directory: " + str(e) + "\n")
            sys.exit(2)

    try:
        run_batch(input_path, output_path, top_n=top_n)

        # Verify output was written and is valid JSONL
        # Read back and validate
        with open(output_path, encoding="utf-8") as f:
            lines = [l.strip() for l in f if l.strip()]

        # Validate each line is valid JSON with required keys
        for i, line in enumerate(lines, 1):
            try:
                data = json.loads(line)
                if "query" not in data or "results" not in data:
                    raise ValueError(f"Line {i}: missing 'query' or 'results' key")
            except json.JSONDecodeError as e:
                sys.stderr.write(
                    f"Error: invalid JSON on line {i}: {e}\n"
                )
                sys.exit(2)

        logger.info("Batch complete: %d queries processed", len(lines))
        sys.exit(0)

    except Exception as e:
        logger.error("Batch search failed: %s", e, exc_info=True)
        sys.stderr.write("Error: " + str(e) + "\n")
        sys.exit(2)


# Allow running as: python -m thelawala_search or python src/cli.py
if __name__ == "__main__":
    main()