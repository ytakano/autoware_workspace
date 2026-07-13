#!/usr/bin/env python3
"""POT/GPD extreme-value analysis of the Profile-B warm samples (roadmap C2, stdlib-only).

Method (plan/ndt_timing_measurement_policy.md, "pWCET and EVT Policy"):
- Input: paper/data/wcet.json (pooled Profile-B warm samples). The pooled stream is split
  back into its per-session thirds (sessions were concatenated in order); the split is
  guarded against the recorded per_session_median. Fits are per session because the pooled
  stream is non-stationary across sessions (documented level shifts up to ~3%).
- Peaks-over-threshold with a 2-parameter generalized Pareto MLE (Nelder-Mead on
  (xi, log beta)); threshold sweep over the 90/92.5/95/97.5/99% empirical quantiles for
  parameter stability; the working threshold is the 95% quantile.
- Per-align exceedance quantiles follow directly from POT (no per-block conversion):
  q(p) = u + beta/xi * ((p/zeta)^(-xi) - 1), zeta = n_u/n. For xi < 0 the fitted tail is
  bounded with upper endpoint u - beta/xi.
- 95% CIs by seeded bootstrap over the exceedances (1000 draws).
- Diagnostics: lag-1..10 autocorrelation per session (independence), split-half p99
  agreement within sessions (stationarity within), cross-session spread of the fits
  (stationarity across), and a Gumbel/GEV block-maxima comparison at block sizes 10/25/50.

Outputs: tables/evt.tex + tables/evt_macros.tex. The script fails loudly if the per-session
split guard or an in-sample sanity check breaks (regenerate-or-break, like gen_tables.py).
"""

import json
import math
import pathlib
import random
import statistics
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = ROOT / "tables"

TAIL_FIXTURES = ["search_00", "legal_worst", "legal_osc"]
LABEL = {
    "search_00": r"\emph{search-00}",
    "legal_worst": r"\emph{legal-worst}$^\dagger$",
    "legal_osc": r"\emph{legal-osc}$^\dagger$",
}
N_SESSIONS = 3
WORK_Q = 0.95  # working threshold quantile
SWEEP_QS = [0.90, 0.925, 0.95, 0.975, 0.99]
BOOT = 1000
P_TARGETS = [1e-6, 1e-9]
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


def gpd_endpoint(u, xi, beta):
    return u - beta / xi if xi < 0 else None


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


def analyze(name, fx, eng, rng):
    rows = []
    for s_idx, xs in enumerate(per_session(fx, eng)):
        srt = sorted(xs)
        n = len(srt)
        # Threshold sweep for stability.
        sweep = []
        for q in SWEEP_QS:
            u = quantile(srt, q)
            ys = [x - u for x in srt if x > u]
            if len(ys) < 10:
                continue
            xi, beta, _ = fit_gpd(ys)
            sweep.append((q, u, len(ys), xi, beta))
        # Working fit at the 95% threshold.
        u = quantile(srt, WORK_Q)
        ys = [x - u for x in srt if x > u]
        xi, beta, _ = fit_gpd(ys)
        zeta = len(ys) / n
        # Bootstrap CIs over the exceedances.
        boots = []
        for _ in range(BOOT):
            sample = [ys[rng.randrange(len(ys))] for _ in ys]
            try:
                bxi, bbeta, _ = fit_gpd(sample)
            except (ValueError, OverflowError):
                continue
            boots.append((bxi, bbeta))
        boots_xi = sorted(b[0] for b in boots)
        q9s = sorted(gpd_quantile(u, b[0], b[1], zeta, 1e-9) for b in boots)
        ends = sorted(gpd_endpoint(u, b[0], b[1]) for b in boots if b[0] < 0)

        def ci(xs_sorted):
            return (xs_sorted[int(0.025 * len(xs_sorted))],
                    xs_sorted[int(0.975 * len(xs_sorted))]) if xs_sorted else (None, None)

        # In-sample sanity: the fitted quantile at the empirical p99.9 exceedance
        # probability must sit near the empirical value (within 3x the tail width).
        emp999 = quantile(srt, 0.999)
        fit999 = gpd_quantile(u, xi, beta, zeta, 0.001)
        tail_width = max(srt[-1] - u, 1e-9)
        if abs(fit999 - emp999) > 3.0 * tail_width:
            raise SystemExit(
                f"{name}/{eng}/s{s_idx + 1}: in-sample sanity failed "
                f"(fitted p99.9 {fit999:.3f} vs empirical {emp999:.3f})")
        rows.append({
            "session": s_idx + 1,
            "n": n, "u": u, "n_u": len(ys), "zeta": zeta,
            "xi": xi, "xi_ci": ci(boots_xi), "beta": beta,
            "q6": gpd_quantile(u, xi, beta, zeta, 1e-6),
            "q9": gpd_quantile(u, xi, beta, zeta, 1e-9),
            "q9_ci": ci(q9s),
            "endpoint": gpd_endpoint(u, xi, beta),
            "endpoint_ci": ci(ends),
            "max": srt[-1],
            "acf_max": max(abs(a) for a in acf(xs)),
            "split_half_p99": (quantile(sorted(xs[:n // 2]), 0.99),
                               quantile(sorted(xs[n // 2:]), 0.99)),
            "sweep_xi_range": (min(s[3] for s in sweep), max(s[3] for s in sweep)),
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
        raise SystemExit("wcet.json is not Profile-B data")
    rng = random.Random(0xE47E47)

    results = {}
    diag_acf_worst = 0.0
    diag_split_worst = 0.0
    diag_xi_sweep_worst = 0.0
    for name in TAIL_FIXTURES:
        for eng in ("cpp", "rust"):
            rows = analyze(name, fixtures[name], eng, rng)
            results[(name, eng)] = rows
            for r in rows:
                diag_acf_worst = max(diag_acf_worst, r["acf_max"])
                a, b = r["split_half_p99"]
                diag_split_worst = max(diag_split_worst, abs(b / a - 1.0) * 100.0)
                lo, hi = r["sweep_xi_range"]
                diag_xi_sweep_worst = max(diag_xi_sweep_worst, hi - lo)

    # Table: tail diagnostics per fixture x engine -- empirical tail + the two
    # diagnostics that gate extrapolation (serial dependence; fit instability).
    rows_tex = []
    ci_explode_worst = 0.0
    for name in TAIL_FIXTURES:
        for eng, lab in (("cpp", "C++"), ("rust", "Rust")):
            rs = results[(name, eng)]
            mx = max(r["max"] for r in rs)
            p50 = statistics.median(
                statistics.median([r["u"] for r in rs]) for _ in (0,))  # placeholder unused
            acf_lo = min(r["acf_max"] for r in rs)
            acf_hi = max(r["acf_max"] for r in rs)
            xi_lo = min(r["xi"] for r in rs)
            xi_hi = max(r["xi"] for r in rs)
            q9_hi = max(r["q9_ci"][1] for r in rs if r["q9_ci"][1] is not None)
            ci_explode_worst = max(ci_explode_worst, q9_hi)
            first = LABEL[name] if eng == "cpp" else ""
            rows_tex.append(
                f"{first} & {lab} & {fmt(mx)} & "
                f"{acf_lo:.2f}--{acf_hi:.2f} & "
                f"{xi_lo:.2f}..{xi_hi:.2f} & {fmt(q9_hi, 0)}"
            )

    # Gumbel/GEV block-maxima comparison on the pooled search_00 C++ stream.
    xs = fixtures["search_00"]["cpp"]["samples_ms"]
    gum = {b: gumbel_blocks(xs, b) for b in (10, 25, 50)}
    gum_q9_spread = max(g[2] for g in gum.values()) - min(g[2] for g in gum.values())

    lines = [
        "% AUTO-GENERATED by scripts/evt.py -- do not hand-edit.",
        r"\begin{table}[t]",
        r"\centering",
        r"\caption{Tail diagnostics on the Profile-B warm data (per-session POT/GPD MLE at"
        r" the 95\% threshold, $n{=}1000$/session, \evtBoot{} bootstrap draws)."
        r" The independence diagnostic (lag-1..10 autocorrelation of the sample series)"
        r" fails throughout, and the bootstrapped $q_{10^{-9}}$ upper CI ends diverge"
        r" accordingly --- extrapolated exceedance probabilities are therefore \emph{not}"
        r" claimed (Sec.~\ref{sec:eval-evt}). All times \si{ms}.}",
        r"\label{tab:evt}",
        r"\footnotesize",
        r"\setlength{\tabcolsep}{3pt}",
        r"\begin{tabular}{llrrrr}",
        r"\toprule",
        r"fixture & engine & max & $|\mathrm{ACF}|_{\max}$ & $\xi$ range"
        r" & $q_{10^{-9}}$ CI hi \\",
        r"\midrule",
    ]
    lines += [r + r" \\" for r in rows_tex]
    lines += [
        r"\bottomrule",
        r"\end{tabular}",
        r"\par\smallskip\footnotesize $|\mathrm{ACF}|_{\max}$: range over the three"
        r" sessions of the largest lag-1..10 autocorrelation magnitude (i.i.d.\ would give"
        r" ${\sim}0.03$ at $n{=}1000$). $\xi$ range: per-session MLE shapes at the working"
        r" threshold. Last column: the worst upper end of the bootstrapped per-align"
        r" $q_{10^{-9}}$ CIs --- since the bootstrap resamples serially dependent"
        r" exceedances, these are not valid confidence intervals; the column is retained"
        r" only as diagnostic evidence for why extrapolation is withheld.",
        r"\end{table}",
    ]
    (OUT / "evt.tex").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("wrote tables/evt.tex")

    # Prose macros.
    xi_max = max(r["xi"] for rs in results.values() for r in rs)
    s0 = results[("search_00", "cpp")]
    q9_med = statistics.median(r["q9"] for r in s0)
    mx = max(r["max"] for r in s0)
    macros = [
        "% AUTO-GENERATED by scripts/evt.py -- do not hand-edit.",
        rf"\newcommand{{\evtXiMax}}{{{xi_max:.2f}}}",
        rf"\newcommand{{\evtAcfWorst}}{{{diag_acf_worst:.2f}}}",
        rf"\newcommand{{\evtSplitWorstPct}}{{{diag_split_worst:.1f}}}",
        rf"\newcommand{{\evtXiSweepWorst}}{{{diag_xi_sweep_worst:.2f}}}",
        rf"\newcommand{{\evtCiExplodeS}}{{{ci_explode_worst / 1000.0:.0f}}}",
        rf"\newcommand{{\evtGumbelSpread}}{{{gum_q9_spread:.1f}}}",
        rf"\newcommand{{\evtGumbelQNine}}{{{gum[10][2]:.1f}}}",
        rf"\newcommand{{\evtGumbelExtraPct}}{{{100.0 * (gum[10][2] / mx - 1.0):.1f}}}",
        rf"\newcommand{{\evtBoot}}{{{BOOT}}}",
    ]
    (OUT / "evt_macros.tex").write_text("\n".join(macros) + "\n", encoding="utf-8")
    print("wrote tables/evt_macros.tex")

    # Console diagnostics summary.
    print(f"diagnostics: worst |ACF| lag1-10 = {diag_acf_worst:.3f}; "
          f"worst split-half p99 delta = {diag_split_worst:.2f}%; "
          f"worst xi sweep range = {diag_xi_sweep_worst:.2f}; "
          f"all xi < 0: {xi_max < 0}")
    print(f"search_00 cpp: q(1e-9) median {q9_med:.1f} ms vs max {mx:.1f} ms "
          f"({100 * (q9_med / mx - 1):+.1f}%)")
    print(f"gumbel comparison (search_00 cpp, pooled): "
          + ", ".join(f"block {b}: q9={g[2]:.1f} (n={g[3]})" for b, g in gum.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
