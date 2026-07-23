#!/usr/bin/env python3

import subprocess
import sys


SERVICE_NAME = "the-watchtower-api-1"


def run_command(command: list[str]) -> None:
    print(f"Running: {' '.join(command)}")
    subprocess.run(command, check=True)


def alembic_command(*args: str) -> list[str]:
    return [
        "docker",
        "compose",
        "-f",
        "compose.dev.yaml",
        "run",
        "--rm",
        SERVICE_NAME,
        "alembic",
        *args,
    ]


def main() -> int:
    try:
        print("Current migration:")
        run_command(alembic_command("current"))

        print("\nRunning migrations...")
        run_command(alembic_command("upgrade", "head"))

        print("\nCurrent migration after upgrade:")
        run_command(alembic_command("current"))

    except subprocess.CalledProcessError as error:
        print(f"Migration failed. Exit code: {error.returncode}", file=sys.stderr)
        return error.returncode

    return 0


if __name__ == "__main__":
    raise SystemExit(main())