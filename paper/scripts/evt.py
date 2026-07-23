#!/usr/bin/env python3
"""Tail-model diagnostics for the Isolated warm samples (stdlib-only).

Method (plan/ndt_timing_measurement_policy.md, "pWCET and EVT Policy"):
- Input: paper/data/wcet.json (pooled Isolated warm samples). The pooled stream is split
  back into its per-session thirds (sessions were concatenated in order); the split is
  guarded against the recorded per_session_median. Fits are per session because the pooled
  stream is non-stationary across sessions (documented level shifts up to ~3%).
- Peaks-over-threshold with a 2-parameter generalized Pareto MLE (Nelder-Mead on
  (xi, log beta)) at the 95% empirical quantile.
- Diagnostics: lag-1..10 autocorrelation per session, an in-sample p99.9 adequacy check,
  and a pooled Gumbel block-maxima comparison. These diagnostics document why no
  extrapolation is reported.

Outputs: tables/evt.tex + tables/evt_macros.tex. The script fails loudly if the per-session
split guard breaks. In-sample fit failures are reported as rejection diagnostics rather than
treated as pipeline errors.
"""

import json
import math
import pathlib
import statistics
import sys

from fixture_order import FIXTURE_LABELS as LABEL
from fixture_order import ordered_fixture_names

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = ROOT / "tables"

TAIL_FIXTURES = ordered_fixture_names(("search_00", "legal_worst", "legal_osc"))
N_SESSIONS = 3
WORK_Q = 0.95  # working threshold quantile
EULER_GAMMA = 0.5772156649015329


def quantile(sorted_xs, q):
    i = min(int(q * (len(sorted_xs) - 1)), len(sorted_xs) - 1)
    return sorted_xs[i]


# ---------------------------------------------------------------------------
# GPD MLE (Nelder-Mead over (xi, log beta))
# ---------------------------------------------------------------------------

def gpd_nll(params, ys):
    xi, logb = params
    if not (-5.0 < xi < 5.0) or not (-40.0 < logb < 40.0):
        return float("inf")
    beta = math.exp(logb)
    n = len(ys)
    if abs(xi) < 1e-9:
        return n * logb + sum(ys) / beta
    s = 0.0
    for y in ys:
        z = 1.0 + xi * y / beta
        if z <= 0.0:
            return float("inf")
        s += math.log(z)
    return n * logb + (1.0 + 1.0 / xi) * s


def nelder_mead(f, x0, args, steps=(0.1, 0.1), iters=400):
    n = len(x0)
    simplex = [list(x0)]
    for i in range(n):
        p = list(x0)
        p[i] += steps[i]
        simplex.append(p)
    vals = [f(p, args) for p in simplex]
    for _ in range(iters):
        order = sorted(range(n + 1), key=lambda i: vals[i])
        simplex = [simplex[i] for i in order]
        vals = [vals[i] for i in order]
        if abs(vals[-1] - vals[0]) < 1e-10:
            break
        centroid = [sum(p[i] for p in simplex[:-1]) / n for i in range(n)]
        refl = [centroid[i] + (centroid[i] - simplex[-1][i]) for i in range(n)]
        fr = f(refl, args)
        if vals[0] <= fr < vals[-2]:
            simplex[-1], vals[-1] = refl, fr
        elif fr < vals[0]:
            exp = [centroid[i] + 2.0 * (centroid[i] - simplex[-1][i]) for i in range(n)]
            fe = f(exp, args)
            if fe < fr:
                simplex[-1], vals[-1] = exp, fe
            else:
                simplex[-1], vals[-1] = refl, fr
        else:
            con = [centroid[i] + 0.5 * (simplex[-1][i] - centroid[i]) for i in range(n)]
            fc = f(con, args)
            if fc < vals[-1]:
                simplex[-1], vals[-1] = con, fc
            else:
                for i in range(1, n + 1):
                    simplex[i] = [(simplex[i][j] + simplex[0][j]) / 2.0 for j in range(n)]
                    vals[i] = f(simplex[i], args)
    best = min(range(n + 1), key=lambda i: vals[i])
    return simplex[best], vals[best]


def fit_gpd(ys):
    """MLE (xi, beta) for exceedances ys > 0."""
    mean = statistics.fmean(ys)
    var = statistics.pvariance(ys)
    # Method-of-moments start (falls back to exponential-ish if degenerate).
    if var > 0:
        xi0 = 0.5 * (1.0 - mean * mean / var)
        beta0 = 0.5 * mean * (mean * mean / var + 1.0)
    else:
        xi0, beta0 = -0.3, max(mean, 1e-9)
    beta0 = max(beta0, 1e-9)
    (xi, logb), nll = nelder_mead(gpd_nll, [xi0, math.log(beta0)], ys)
    return xi, math.exp(logb), nll


def gpd_quantile(u, xi, beta, zeta, p):
    """Per-align quantile at exceedance probability p (< zeta)."""
    if abs(xi) < 1e-9:
        return u + beta * math.log(zeta / p)
    return u + beta / xi * ((p / zeta) ** (-xi) - 1.0)


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------

def acf(xs, max_lag=10):
    n = len(xs)
    m = statistics.fmean(xs)
    denom = sum((x - m) ** 2 for x in xs)
    if denom == 0:
        return [0.0] * max_lag
    out = []
    for lag in range(1, max_lag + 1):
        num = sum((xs[i] - m) * (xs[i + lag] - m) for i in range(n - lag))
        out.append(num / denom)
    return out


# ---------------------------------------------------------------------------
# Main analysis
# ---------------------------------------------------------------------------

def per_session(fx, eng):
    xs = fx[eng]["samples_ms"]
    if len(xs) % N_SESSIONS != 0:
        raise SystemExit(f"sample count {len(xs)} not divisible by {N_SESSIONS}")
    k = len(xs) // N_SESSIONS
    sessions = [xs[i * k:(i + 1) * k] for i in range(N_SESSIONS)]
    recorded = fx.get("per_session_median", {}).get(eng)
    if recorded:
        for i, s in enumerate(sessions):
            # per_session_median is stored rounded to 3 decimals by integrate_campaign.py
            if abs(statistics.median(s) - recorded[i]) > 5e-4 + 1e-9:
                raise SystemExit(
                    f"per-session split guard failed (session {i + 1}: "
                    f"{statistics.median(s)} != recorded {recorded[i]})")
    return sessions


def analyze(fx, eng):
    rows = []
    for s_idx, xs in enumerate(per_session(fx, eng)):
        srt = sorted(xs)
        n = len(srt)
        # Working fit at the 95% threshold.
        u = quantile(srt, WORK_Q)
        ys = [x - u for x in srt if x > u]
        xi, beta, _ = fit_gpd(ys)
        zeta = len(ys) / n
        # In-sample sanity: the fitted quantile at the empirical p99.9 exceedance
        # probability must sit near the empirical value (within 3x the tail width).
        emp999 = quantile(srt, 0.999)
        fit999 = gpd_quantile(u, xi, beta, zeta, 0.001)
        tail_width = max(srt[-1] - u, 1e-9)
        sanity_error = abs(fit999 - emp999)
        rows.append({
            "session": s_idx + 1,
            "n": n, "u": u, "n_u": len(ys), "zeta": zeta,
            "xi": xi, "beta": beta,
            "max": srt[-1],
            "acf_max": max(abs(a) for a in acf(xs)),
            "sanity_ok": sanity_error <= 3.0 * tail_width,
            "sanity_error_widths": sanity_error / tail_width,
        })
    return rows


def gumbel_blocks(xs, block):
    maxima = [max(xs[i:i + block]) for i in range(0, len(xs) - block + 1, block)]
    n = len(maxima)
    m = statistics.fmean(maxima)
    s = math.sqrt(sum((x - m) ** 2 for x in maxima) / (n - 1))
    beta = s * math.sqrt(6.0) / math.pi
    mu = m - EULER_GAMMA * beta
    q9 = mu - beta * math.log(-math.log(1.0 - 1e-9))
    return mu, beta, q9, n


def fmt(x, nd=1):
    return f"{x:.{nd}f}" if x is not None else "--"


def main():
    doc = json.loads((DATA / "wcet.json").read_text())
    fixtures = doc["fixtures"]
    manifest = doc["meta"]["manifest"]
    if manifest.get("measurement_profile") != "B":
        raise SystemExit("wcet.json is not Isolated data")
    results = {}
    diag_acf_worst = 0.0
    for name in TAIL_FIXTURES:
        for eng in ("cpp", "rust"):
            rows = analyze(fixtures[name], eng)
            results[(name, eng)] = rows
            for r in rows:
                diag_acf_worst = max(diag_acf_worst, r["acf_max"])

    # Table: tail diagnostics per fixture x engine -- empirical tail + the two
    # diagnostics that gate extrapolation (serial dependence; fit instability).
    rows_tex = []
    fit_failures = 0
    fit_checks = 0
    fit_error_worst = 0.0
    for name in TAIL_FIXTURES:
        for eng, lab in (("cpp", "C++"), ("rust", "Rust")):
            rs = results[(name, eng)]
            mx = max(r["max"] for r in rs)
            acf_lo = min(r["acf_max"] for r in rs)
            acf_hi = max(r["acf_max"] for r in rs)
            xi_lo = min(r["xi"] for r in rs)
            xi_hi = max(r["xi"] for r in rs)
            failures = sum(not r["sanity_ok"] for r in rs)
            fit_failures += failures
            fit_checks += len(rs)
            fit_error_worst = max(fit_error_worst, *(r["sanity_error_widths"] for r in rs))
            first = LABEL[name] if eng == "cpp" else ""
            rows_tex.append(
                f"{first} & {lab} & {fmt(mx)} & "
                f"{acf_lo:.2f}--{acf_hi:.2f} & "
                f"{xi_lo:.2f}..{xi_hi:.2f} & {failures}/{len(rs)}"
            )

    # Gumbel/GEV block-maxima comparison on the pooled search_00 C++ stream.
    xs = fixtures["search_00"]["cpp"]["samples_ms"]
    gum = gumbel_blocks(xs, 10)

    lines = [
        "% AUTO-GENERATED by scripts/evt.py -- do not hand-edit.",
        r"\begin{table}[t]",
        r"\centering",
        r"\caption{Rejected per-session POT/GPD tail models ($n{=}1000$/session; 95\% threshold)."
        r" Dependence or in-sample fit failure invalidates extrapolation; values are diagnostic"
        r" outputs, not timing estimates. Times in \si{ms}.}",
        r"\label{tab:evt}",
        r"\footnotesize",
        r"\setlength{\tabcolsep}{3pt}",
        r"\begin{tabular}{llrrrr}",
        r"\toprule",
        r"fixture & engine & max & $|\mathrm{ACF}|_{\max}$ & $\xi$ range"
        r" & fit failures \\",
        r"\midrule",
    ]
    lines += [r + r" \\" for r in rows_tex]
    lines += [
        r"\bottomrule",
        r"\end{tabular}",
        r"\par\smallskip\footnotesize ACF: largest lag-1--10 magnitude over three sessions"
        r" (i.i.d.: ${\sim}0.03$). Fit failures count sessions whose fitted p99.9 differs"
        r" from the empirical p99.9 by more than three observed tail widths."
        r" \emph{geom-stress} uses production-contract"
        r" geometry with non-shipped $\epsilon$; \emph{shipped-osc} also fixes shipped"
        r" $\epsilon$.",
        r"\end{table}",
    ]
    (OUT / "evt.tex").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("wrote tables/evt.tex")

    # Prose macros.
    s0 = results[("search_00", "cpp")]
    mx = max(r["max"] for r in s0)
    macros = [
        "% AUTO-GENERATED by scripts/evt.py -- do not hand-edit.",
        rf"\newcommand{{\evtAcfWorst}}{{{diag_acf_worst:.2f}}}",
        rf"\newcommand{{\evtFitFailures}}{{{fit_failures}}}",
        rf"\newcommand{{\evtFitChecks}}{{{fit_checks}}}",
        rf"\newcommand{{\evtGumbelExtraPct}}{{{100.0 * (gum[2] / mx - 1.0):.1f}}}",
    ]
    (OUT / "evt_macros.tex").write_text("\n".join(macros) + "\n", encoding="utf-8")
    print("wrote tables/evt_macros.tex")

    # Console diagnostics summary.
    print(f"diagnostics: worst |ACF| lag1-10 = {diag_acf_worst:.3f}; "
          f"in-sample failures = {fit_failures}/{fit_checks}")
    print(f"gumbel comparison (search_00 cpp, block 10): "
          f"q9={gum[2]:.1f} (n={gum[3]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
