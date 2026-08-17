"""Compare Python regex, grep, and the complete session-commit guard.

Run from the repository root, for example:

    uv run python benchmark_session_commit_guard.py --files 2000 --repeats 10
"""

from __future__ import annotations

import argparse
import random
import statistics
import subprocess
import tempfile
import time
from pathlib import Path

from pre_commits.session_commit_guard.hook import (
    COMMIT_CALL_RE,
    GREP_COMMIT_PATTERN,
    check_files,
)


def _clean_source(rng: random.Random, line_count: int) -> str:
    lines = []
    for line in range(line_count):
        name = "value_" + "x" * rng.randint(1, 80) + str(line)
        padding = " " * rng.randint(0, 12)
        number = rng.randint(-(10**12), 10**12)
        lines.append(f"{name}{padding} = {number}")
    return "\n".join(lines) + "\n"


def build_files(
    directory: Path,
    count: int,
    rng: random.Random,
    min_lines: int,
    max_lines: int,
    huge_files: int,
    huge_lines: int,
    bad_files: int,
) -> list[Path]:
    paths = []
    clean_files = count - bad_files
    huge_indexes = set(rng.sample(range(clean_files), min(huge_files, clean_files)))
    for index in range(clean_files):
        line_count = (
            huge_lines if index in huge_indexes else rng.randint(min_lines, max_lines)
        )
        path = directory / f"module_{index}.py"
        path.write_text(_clean_source(rng, line_count))
        paths.append(path)

    for index in range(bad_files):
        violating = directory / f"violating_{index}.py"
        violating.write_text(
            f"async def route_{index}(session):\n    await session.commit()\n"
        )
        paths.append(violating)
    return paths


def python_regex(paths: list[Path]) -> int:
    matches = 0
    for path in paths:
        if COMMIT_CALL_RE.search(path.read_text()):
            matches += 1
    return matches


def grep_regex(paths: list[Path]) -> int:
    result = subprocess.run(
        [
            "grep",
            "-nH",
            "-E",
            GREP_COMMIT_PATTERN,
            "--",
            *(str(path) for path in paths),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode not in (0, 1):
        raise RuntimeError(result.stderr.strip() or "grep failed")
    return len(result.stdout.splitlines())


def full_guard(paths: list[Path]) -> int:
    return len(check_files(paths))


def benchmark(name: str, function, paths: list[Path], repeats: int) -> list[float]:
    for _ in range(2):
        function(paths)
    samples = []
    for _ in range(repeats):
        start = time.perf_counter()
        result = function(paths)
        samples.append(time.perf_counter() - start)
    print(
        f"{name:16} result={result:<5} "
        f"min={min(samples) * 1000:8.2f} ms "
        f"median={statistics.median(samples) * 1000:8.2f} ms "
        f"mean={statistics.mean(samples) * 1000:8.2f} ms"
    )
    return samples


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--files", type=int, default=1000)
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--bad-files", type=int, help="Number of files containing commit() calls."
    )
    group.add_argument(
        "--clean-files",
        type=int,
        help="Number of clean files; derives bad-files from --files.",
    )
    parser.add_argument("--min-lines", type=int, default=1)
    parser.add_argument("--max-lines", type=int, default=200)
    parser.add_argument(
        "--huge-files",
        type=int,
        default=3,
        help="Number of clean files using --huge-lines.",
    )
    parser.add_argument("--huge-lines", type=int, default=50_000)
    parser.add_argument("--seed", type=int, default=20260814)
    parser.add_argument("--repeats", type=int, default=7)
    args = parser.parse_args()
    bad_files = (
        args.files - args.clean_files
        if args.clean_files is not None
        else args.bad_files
        if args.bad_files is not None
        else 1
    )
    if (
        args.files < 1
        or bad_files < 1
        or bad_files >= args.files
        or args.min_lines < 1
        or args.max_lines < args.min_lines
        or args.huge_files < 0
        or args.huge_lines < 1
        or args.repeats < 1
    ):
        parser.error("invalid file-count, line-count, huge-file, or repeat argument")

    rng = random.Random(args.seed)
    with tempfile.TemporaryDirectory(prefix="session-commit-bench-") as raw_dir:
        paths = build_files(
            Path(raw_dir),
            args.files,
            rng,
            args.min_lines,
            args.max_lines,
            args.huge_files,
            args.huge_lines,
            bad_files,
        )
        print(
            f"seed={args.seed}, files={len(paths)}, "
            f"clean_files={len(paths) - bad_files}, "
            f"huge_files={min(args.huge_files, len(paths) - bad_files)}, "
            f"huge_lines={args.huge_lines}, bad_files={bad_files}"
        )
        benchmark("python regex", python_regex, paths, args.repeats)
        benchmark("grep", grep_regex, paths, args.repeats)
        benchmark("full guard", full_guard, paths, args.repeats)


if __name__ == "__main__":
    main()
