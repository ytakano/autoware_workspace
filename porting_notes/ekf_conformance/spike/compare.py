#!/usr/bin/env python3
"""Spike comparator: max relative error between the C++ and Rust golden dumps."""
import csv
import sys


def load(path):
    d = {}
    with open(path) as f:
        for row in csv.reader(f):
            d[(row[0], row[1], int(row[2]), int(row[3]))] = float(row[4])
    return d


a = load(sys.argv[1])
b = load(sys.argv[2])
assert set(a) == set(b), "key sets differ"

worst = (0.0, None)
per_case = {}
for k, va in a.items():
    vb = b[k]
    denom = max(abs(va), abs(vb))
    rel = 0.0 if denom == 0.0 else abs(va - vb) / denom
    case = k[0]
    per_case[case] = max(per_case.get(case, 0.0), rel)
    if rel > worst[0]:
        worst = (rel, k, va, vb)

for case in sorted(per_case):
    print(f"{case:24s} max_rel = {per_case[case]:.3e}")
print("WORST:", worst)
print("PASS" if worst[0] <= 1e-6 else "FAIL (stop condition rel > 1e-6)")
