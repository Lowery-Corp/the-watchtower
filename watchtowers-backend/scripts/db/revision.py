#!/usr/bin/env python3

import argparse
import subprocess
import sys


SERVICE_NAME = "api"


def run_command(command: list[str]) -> None:
    print(f"Running: {' '.join(command)}")
    subprocess.run(command, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create a new Alembic revision using autogenerate."
    )
    parser.add_argument(
        "message",
        help='Revision message, for example: "create users table"',
    )

    args = parser.parse_args()

    command = [
        "docker",
        "compose",
        "-f",
        "compose.dev.yaml",
        "run",
        "--rm",
        SERVICE_NAME,
        "alembic",
        "revision",
        "--autogenerate",
        "-m",
        args.message,
    ]

    try:
        run_command(command)
    except subprocess.CalledProcessError as error:
        print(f"Failed to create revision. Exit code: {error.returncode}", file=sys.stderr)
        return error.returncode

    print(f"Created Alembic revision: {args.message}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())