#!/usr/bin/env python3
"""Advisory prose lint for the paper sources (stdlib-only; never fails the build).

Flags, per sections/*.tex line:
  bare-number   digits outside \\num/\\SI/macros/labels/refs/cites/math/tables --
                measurement numbers must come from generated macros (a hand-typed
                total once desynchronized from the data; this lint mechanizes the
                "no hand-typed measurement" rule)
  long-sentence sentences over 40 words
  weasel        vague intensifiers ("clearly", "obviously", "very", "significantly"
                without an accompanying statistic)

Exit code is always 0: findings are advisory and printed for human review.
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
WEASEL = re.compile(r"\b(clearly|obviously|very|extremely|significantly|substantially)\b", re.I)
# Strip constructs whose digits are legitimate before scanning for bare numbers.
STRIP = [
    re.compile(r"(?<!\\)%.*"),                       # comments
    re.compile(r"\\(?:num|SI|si|cite|ref|label|input|include|eqref)\*?(?:\[[^]]*\])?\{[^}]*\}"),
    re.compile(r"\\[A-Za-z@]+"),                     # control sequences (incl. macros)
    re.compile(r"\$[^$]*\$"),                        # inline math
    re.compile(r"\b(?:19|20)\d{2}\b"),               # years
]
ALLOW = re.compile(r"^\s*(?:\\|%|$)")                # skip pure-markup lines


def main() -> int:
    findings = 0
    for tex in sorted((ROOT / "sections").glob("*.tex")):
        text = tex.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), 1):
            if ALLOW.match(line):
                continue
            stripped = line
            for pat in STRIP:
                stripped = pat.sub(" ", stripped)
            for match in re.finditer(r"\d+(?:\.\d+)?", stripped):
                print(f"{tex.name}:{lineno}: bare-number '{match.group()}': {line.strip()[:80]}")
                findings += 1
            if WEASEL.search(stripped):
                print(f"{tex.name}:{lineno}: weasel: {line.strip()[:80]}")
                findings += 1
        # sentence length over the whole section (rough tokenization)
        prose = re.sub(r"\\[A-Za-z@]+(\[[^]]*\])?(\{[^}]*\})*", " X ", text)
        for sent in re.split(r"(?<=[.!?])\s+", prose):
            words = sent.split()
            if len(words) > 40:
                head = " ".join(words[:8])
                print(f"{tex.name}: long-sentence ({len(words)} words): {head} ...")
                findings += 1
    print(f"lint_prose: {findings} advisory finding(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
