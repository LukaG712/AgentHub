#!/usr/bin/env python3
"""Fake agent script for testing. Simulates various agent behaviors."""

import argparse
import json
import sys
import time


def main():
    parser = argparse.ArgumentParser(description="Fake agent for testing")
    parser.add_argument("--task", type=str, default="")
    parser.add_argument("--project", type=str, default="")
    parser.add_argument("--output-format", type=str, default="json")
    parser.add_argument("--delay", type=float, default=0, help="Delay in seconds before responding")
    parser.add_argument("--simulate-429", action="store_true", help="Simulate 429 rate limit")
    parser.add_argument("--fail", action="store_true", help="Exit with error code")
    parser.add_argument("--hang", action="store_true", help="Hang indefinitely")
    args = parser.parse_args()

    if args.hang:
        # Hang forever
        time.sleep(999999)
        return

    if args.delay:
        time.sleep(args.delay)

    if args.simulate_429:
        print(json.dumps({"error": "429 Too Many Requests", "message": "RESOURCE_EXHAUSTED"}))
        sys.exit(0)

    if args.fail:
        print(json.dumps({"error": "Something went wrong"}))
        sys.exit(1)

    # Normal response
    response = {
        "answer": f"Completed task: {args.task}",
        "text": f"Agent processed task '{args.task}' in project '{args.project}'",
        "status": "ok",
    }
    print(json.dumps(response))
    sys.exit(0)


if __name__ == "__main__":
    main()
