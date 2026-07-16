#!/usr/bin/env python3

"""Deterministically balance unittest files while keeping the slow suites apart."""

import argparse
from pathlib import Path


N_SHARDS = 4
EXCLUDED = {"test_examples.py"}  # Runs once, with plotting enabled, in its own CI job.
HEAVY = {
    "test_rs.py":      0,
    "test_ldpc.py":    1,
    "test_viterbi.py": 2,
}


def assignments():
    files = sorted(Path("test").glob("test_*.py"))
    shards = [[] for _ in range(N_SHARDS)]
    regular = [p for p in files if p.name not in EXCLUDED and p.name not in HEAVY]
    for index, path in enumerate(regular):
        shards[index % N_SHARDS].append(path)
    for path in files:
        if path.name in HEAVY:
            shards[HEAVY[path.name]].append(path)

    assigned = [p for shard in shards for p in shard]
    expected = [p for p in files if p.name not in EXCLUDED]
    if sorted(assigned) != expected or len(set(assigned)) != len(assigned):
        raise RuntimeError("test shard assignment is incomplete or contains duplicates")
    return [sorted(shard) for shard in shards]


def module_name(path):
    return ".".join(path.with_suffix("").parts)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("shard", nargs="?", type=int, choices=range(N_SHARDS))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    shards = assignments()
    if args.check:
        print(" ".join(str(len(shard)) for shard in shards))
        return
    if args.shard is None:
        parser.error("a shard number is required unless --check is used")
    print(" ".join(module_name(path) for path in shards[args.shard]))


if __name__ == "__main__":
    main()
