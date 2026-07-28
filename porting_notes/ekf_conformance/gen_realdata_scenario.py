#!/usr/bin/env python3
"""Build the real-data EKF conformance scenario.

Reconstructs the measurement/tick timeline from:
  - the frozen stack-replay pose trace (measurement_ns, obs_x, obs_y, obs_yaw and the 50 Hz
    tick timeline in current_ns): stack_replay_results_reinit/rust2/ekf_pose_updates.csv
  - the rosbag twist stream (100 Hz TwistWithCovarianceStamped, CDR-parsed from the sqlite3
    db3): /home/ytakano/autoware_ista_data/loc_bag/loc_bag_0.db3

The pose covariance is a fixed plausible NDT covariance (identical input to both sides —
the frozen trace does not record it). z/roll/pitch are 0 (the trace records planar pose).

Usage: gen_realdata_scenario.py [--duration 60] [--out realdata.scn]
"""

import argparse
import csv
import math
import sqlite3
import struct

POSE_TRACE = "/autoware_workspace/stack_replay_results_reinit/rust2/ekf_pose_updates.csv"
BAG = "/home/ytakano/autoware_ista_data/loc_bag/loc_bag_0.db3"
TWIST_TOPIC = "/localization/twist_estimator/twist_with_covariance"

# The bag's twist header stamps are in the original recording epoch (1723770873...s) while the
# frozen stack-replay trace (and the bag reception timestamps) are in the replay epoch
# (1726142404...s). A fixed offset (the median of reception - header over the stream, frozen
# here for determinism) maps the twist stamps onto the replay timeline with their original
# ~0-100 ms transport jitter preserved.
TWIST_EPOCH_OFFSET_NS = 2371531245000000

# Fixed pose covariance (row-major 6x6): NDT-like x/y/yaw + nominal z/roll/pitch.
POSE_COV = [0.0] * 36
POSE_COV[0] = 0.0225   # X_X
POSE_COV[7] = 0.0225   # Y_Y
POSE_COV[14] = 0.09    # Z_Z
POSE_COV[21] = 0.001   # ROLL_ROLL
POSE_COV[28] = 0.001   # PITCH_PITCH
POSE_COV[35] = 0.0064  # YAW_YAW


def parse_twist_cdr(blob):
    """CDR: 4B encapsulation; header (int32 sec, uint32 nanosec, string frame_id);
    twist 6 f64; covariance 36 f64. Alignment is relative to the payload start."""
    base = 4
    off = base
    sec, nsec = struct.unpack_from("<iI", blob, off)
    off += 8
    (slen,) = struct.unpack_from("<I", blob, off)
    off += 4 + slen  # includes the NUL terminator
    # align to 8 (relative to payload start) for the first double
    rel = off - base
    rel = (rel + 7) // 8 * 8
    off = base + rel
    vals = struct.unpack_from("<42d", blob, off)
    stamp_ns = sec * 10**9 + nsec
    return stamp_ns, vals[:6], vals[6:]


def yaw_quat(yaw):
    return (0.0, 0.0, math.sin(yaw / 2.0), math.cos(yaw / 2.0))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--duration", type=float, default=60.0, help="window length [s]")
    ap.add_argument("--out", default="realdata.scn")
    ap.add_argument("--pose-trace", default=POSE_TRACE)
    ap.add_argument("--bag", default=BAG)
    args = ap.parse_args()

    # --- pose trace: ticks + unique measurements (first tick each appears on) ---
    ticks = []
    seen_ticks = set()
    meas = {}  # measurement_ns -> (first_current_ns, obs_x, obs_y, obs_yaw)
    with open(args.pose_trace) as f:
        for row in csv.DictReader(f):
            cur = int(row["current_ns"])
            if cur not in seen_ticks:
                seen_ticks.add(cur)
                ticks.append(cur)
            m = int(row["measurement_ns"])
            if m not in meas:
                meas[m] = (cur, float(row["obs_x"]), float(row["obs_y"]),
                           float(row["obs_yaw"]))
    ticks.sort()
    t_start = ticks[0]
    t_end = t_start + int(args.duration * 1e9)
    ticks = [t for t in ticks if t <= t_end]

    # --- bag twists in the window ---
    con = sqlite3.connect(args.bag)
    tid = con.execute("SELECT id FROM topics WHERE name=?", (TWIST_TOPIC,)).fetchone()[0]
    twists = []
    for (blob,) in con.execute(
        "SELECT data FROM messages WHERE topic_id=? ORDER BY timestamp", (tid,)
    ):
        stamp_ns, tw, cov = parse_twist_cdr(blob)
        stamp_ns += TWIST_EPOCH_OFFSET_NS
        if t_start - 10**9 <= stamp_ns <= t_end:
            twists.append((stamp_ns, tw, cov))

    # --- assemble events: measurement arrival = just before its first tick; twist arrival =
    # just before the first tick with current_ns >= stamp (bag stamps are sensor times) ---
    events = []  # (sort_time, order, line)
    for m, (first_cur, x, y, yaw) in meas.items():
        if first_cur > t_end:
            continue
        q = yaw_quat(yaw)
        line = ("pose %d %.17g %.17g 0 %.17g %.17g %.17g %.17g " % (m, x, y, *q)
                + " ".join("%.17g" % c for c in POSE_COV))
        events.append((first_cur, 0, line))
    for stamp_ns, tw, cov in twists:
        line = ("twist %d %s %s" % (stamp_ns, " ".join("%.17g" % v for v in tw),
                                    " ".join("%.17g" % c for c in cov)))
        events.append((stamp_ns, 1, line))
    for t in ticks:
        events.append((t, 2, "tick %d" % t))
    events.sort(key=lambda e: (e[0], e[1]))

    # --- init from the first pose measurement ---
    first_m = min((v[0], k) for k, v in meas.items())[1]
    _, ix, iy, iyaw = meas[first_m]
    q = yaw_quat(iyaw)
    init_line = ("init %d %.17g %.17g 0 %.17g %.17g %.17g %.17g " % (first_m, ix, iy, *q)
                 + " ".join("%.17g" % c for c in POSE_COV))

    with open(args.out, "w") as f:
        f.write("# generated by gen_realdata_scenario.py (frozen stack replay + loc_bag)\n")
        f.write(init_line + "\n")
        for _, _, line in events:
            f.write(line + "\n")

    n_pose = sum(1 for e in events if e[2].startswith("pose"))
    n_twist = sum(1 for e in events if e[2].startswith("twist"))
    print(f"wrote {args.out}: {len(ticks)} ticks, {n_pose} poses, {n_twist} twists, "
          f"window {args.duration}s from {t_start}")


if __name__ == "__main__":
    main()
