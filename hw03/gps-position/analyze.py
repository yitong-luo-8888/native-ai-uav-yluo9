#!/usr/bin/env python3
"""
analyze.py -- Track A, GPS / position failure (climb-out drift).

Question: during the initial climb-out, does the aircraft's actual position
(POS) match the guided-mode target it was given (GUIP)? If it tracked the
target accurately, a horizontal excursion is a problem with whatever *set*
the target, not with GPS/EKF. If it did not track the target, that points
the other way -- a control/estimate problem.

    cd lab/lesson3
    python bin2csv.py "gps-position/2025-09-04 10-23-55.bin" -t GPS,POS,GUIP,ORGN,MSG,ERR,MODE
    cd ../../hw03/gps-position
    python analyze.py "../../lab/lesson3/gps-position/2025-09-04 10-23-55"

Requires: pip install -r lab/lesson3/requirements.txt
"""
import csv
import os
import sys
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# --- thresholds --------------------------------------------------------------
LIFTOFF_ALT_M   = 0.3   # RelHomeAlt above this = airborne
CLIMB_WINDOW_S  = 30.0  # analyse this many seconds after liftoff -- the
                         # climb-out, where a "straight up" command is expected
HDOP_OK         = 1.5   # README's rule of thumb
NSATS_OK        = 6
DISP_NORMAL_M   = 5.0   # horizontal wander under this = noise, not a finding
TRACK_ERR_OK_M  = 5.0   # POS-vs-GUIP error under this = "tracked it"

CSV_DIR = sys.argv[1] if len(sys.argv) > 1 else "2025-09-04 10-23-55"
OUT_DIR = sys.argv[2] if len(sys.argv) > 2 else "."


def load(name):
    """Load <CSV_DIR>/<name>.csv into a dict of numpy columns, or None if absent/empty."""
    path = f"{CSV_DIR}/{name}.csv"
    if not os.path.exists(path):
        return None
    with open(path) as f:
        rows = list(csv.reader(f))
    if len(rows) < 2:
        return None
    hdr, data = rows[0], rows[1:]
    out = {}
    for i, h in enumerate(hdr):
        col = np.array([r[i] for r in data], dtype=object)
        try:
            out[h] = col.astype(float)
        except ValueError:
            out[h] = col
    return out


def to_ned(lat, lon, lat0, lon0):
    """Flat-earth lat/lon (deg) -> north/east metres from (lat0, lon0)."""
    north = (lat - lat0) * 111320.0
    east = (lon - lon0) * 111320.0 * np.cos(np.radians(lat0))
    return north, east


gps = load("GPS")
pos = load("POS")
guip = load("GUIP")
orgn = load("ORGN")
msg = load("MSG")
err = load("ERR")

if pos is None:
    print("VERDICT: can't tell -- no POS records in this log; nothing to check.")
    sys.exit(0)

# --- reference origin ---------------------------------------------------------
if orgn is not None and "Type" in orgn and np.any(orgn["Type"] == 0):
    i0 = np.argmax(orgn["Type"] == 0)  # first ekf_origin row
    lat0, lon0 = orgn["Lat"][i0], orgn["Lng"][i0]
    origin_src = "ORGN ekf_origin (Type 0)"
elif gps is not None:
    lat0, lon0 = gps["Lat"][0] / 1e7, gps["Lng"][0] / 1e7
    origin_src = "first GPS fix (no ORGN in this log)"
else:
    lat0, lon0 = pos["Lat"][0], pos["Lng"][0]
    origin_src = "first POS fix (no ORGN or GPS in this log)"

pos_n, pos_e = to_ned(pos["Lat"], pos["Lng"], lat0, lon0)
t_pos = pos["t_s"]
alt = pos["RelHomeAlt"]

# --- find liftoff and the climb-out window ------------------------------------
airborne = alt > LIFTOFF_ALT_M
if not np.any(airborne):
    print(f"VERDICT: can't tell -- RelHomeAlt never exceeds {LIFTOFF_ALT_M} m; "
          f"this log doesn't show a climb-out.")
    sys.exit(0)

i_lift = int(np.argmax(airborne))
t_lift = float(t_pos[i_lift])
win = (t_pos >= t_lift) & (t_pos <= t_lift + CLIMB_WINDOW_S)

n_w, e_w, t_w, alt_w = pos_n[win], pos_e[win], t_pos[win], alt[win]
n0, e0 = n_w[0], e_w[0]
disp = np.hypot(n_w - n0, e_w - e0)
i_dmax = int(np.argmax(disp))
d_max = float(disp[i_dmax])
t_dmax = float(t_w[i_dmax])
alt_at_dmax = float(alt_w[i_dmax])
alt_gain_win = float(alt_w[-1] - alt_w[0])

# --- GPS quality during the window --------------------------------------------
gps_issue = None
hdop_note = None
if gps is not None:
    gwin = (gps["t_s"] >= t_lift) & (gps["t_s"] <= t_lift + CLIMB_WINDOW_S)
    if np.any(gwin):
        hdop_max = float(gps["HDop"][gwin].max())
        nsats_min = float(gps["NSats"][gwin].min())
        status_min = float(gps["Status"][gwin].min())
        if hdop_max > HDOP_OK:
            gps_issue = f"HDop reached {hdop_max:.2f} (> {HDOP_OK}) during the climb-out"
        elif nsats_min < NSATS_OK:
            gps_issue = f"NSats dropped to {nsats_min:.0f} (< {NSATS_OK}) during the climb-out"
        elif status_min < 3:
            gps_issue = f"GPS Status dropped to {status_min:.0f} (< 3, no 3D fix) during the climb-out"
        else:
            hdop_note = f"HDop {gps['HDop'][gwin].min():.2f}-{hdop_max:.2f}, NSats {nsats_min:.0f}-{gps['NSats'][gwin].max():.0f}, Status {status_min:.0f} (3D fix) throughout"
    else:
        hdop_note = "no GPS rows found in this window"
else:
    hdop_note = "no GPS.csv for this log"

# --- ERR / MSG scan for anything relevant --------------------------------------
flagged_msgs = []
for rec, label in ((err, "ERR"), (msg, "MSG")):
    if rec is None:
        continue
    field = "Message" if "Message" in rec else None
    if field:
        for ts, m in zip(rec["t_s"], rec[field]):
            ml = str(m).lower()
            if any(k in ml for k in ("gps", "ekf", "glitch", "failsafe", "prearm")):
                flagged_msgs.append((float(ts), f"{label}: {m}"))

# --- commanded target (GUIP) comparison, if this log has one ------------------
guip_available = False
e_at_dmax = e_max_win = e_mean_win = None
gn_w = ge_w = gt_w = None
if guip is not None and "pX" in guip:
    valid = (guip["pX"] != 0) | (guip["pY"] != 0)
    if np.any(valid):
        gt = guip["t_s"][valid]
        glat = guip["pX"][valid] / 1e7
        glon = guip["pY"][valid] / 1e7
        gn, ge = to_ned(glat, glon, lat0, lon0)
        gwin_mask = (gt >= t_lift) & (gt <= t_lift + CLIMB_WINDOW_S)
        if np.count_nonzero(gwin_mask) >= 2:
            guip_available = True
            gt_w, gn_w, ge_w = gt[gwin_mask], gn[gwin_mask], ge[gwin_mask]
            order = np.argsort(gt_w)
            gt_w, gn_w, ge_w = gt_w[order], gn_w[order], ge_w[order]
            gn_i = np.interp(t_w, gt_w, gn_w)
            ge_i = np.interp(t_w, gt_w, ge_w)
            e_series = np.hypot(n_w - gn_i, e_w - ge_i)
            e_mean_win = float(e_series.mean())
            e_max_win = float(e_series.max())
            e_at_dmax = float(e_series[i_dmax])

# --- reference-frame sanity check (context only, not a verdict driver) --------
origin_note = None
if orgn is not None and "Type" in orgn and np.any(orgn["Type"] == 0) and np.any(orgn["Type"] == 1):
    i1 = np.argmax(orgn["Type"] == 1)
    hn, he = to_ned(orgn["Lat"][i1], orgn["Lng"][i1], lat0, lon0)
    origin_note = float(np.hypot(hn, he))

# --- verdict -------------------------------------------------------------------
print("=" * 72)
if gps_issue:
    print("VERDICT: GPS quality problem during the climb-out.")
    print(f"  {gps_issue}")
    verdict = "gps_quality"
elif d_max < DISP_NORMAL_M:
    print(f"VERDICT: no problem -- horizontal wander during the climb-out stayed "
          f"under {DISP_NORMAL_M:.0f} m.")
    verdict = "none"
elif not guip_available:
    print(f"VERDICT: can't tell (target vs. estimate) -- horizontal displacement "
          f"reached {d_max:.1f} m during the climb-out, above the {DISP_NORMAL_M:.0f} m "
          f"normal-wander line, but no guided-mode target (GUIP) is logged here to "
          f"compare against, so the log alone cannot say whether that displacement "
          f"was commanded or a tracking failure.")
    verdict = "cant_tell"
elif e_at_dmax < TRACK_ERR_OK_M and e_at_dmax < 0.4 * d_max:
    print(f"VERDICT: the aircraft accurately flew to a target that was itself in the "
          f"wrong place. It is NOT a GPS/EKF position-estimate problem.")
    verdict = "target_wrong"
else:
    print(f"VERDICT: the aircraft did not track its commanded target during the "
          f"climb-out -- points to a control/position-estimate problem, not the "
          f"commanded target.")
    verdict = "tracking_fail"
print("=" * 72)
print(f"  origin for N/E conversion: {origin_src}")
print(f"  liftoff (RelHomeAlt > {LIFTOFF_ALT_M} m) at t = {t_lift:.1f} s")
print(f"  climb-out window analysed: t = {t_lift:.1f} - {t_lift + CLIMB_WINDOW_S:.1f} s "
      f"(altitude {alt_w[0]:.1f} -> {alt_w[-1]:.1f} m, gain {alt_gain_win:+.1f} m)")
print(f"  peak horizontal displacement from the start of the window: {d_max:.1f} m "
      f"at t = {t_dmax:.1f} s (altitude there: {alt_at_dmax:.1f} m)")
if guip_available:
    print(f"  POS-vs-GUIP tracking error in this window: mean {e_mean_win:.1f} m, "
          f"max {e_max_win:.1f} m, at the displacement peak {e_at_dmax:.1f} m")
else:
    print("  no guided-mode target (GUIP) logged in this window -- tracking error "
          "cannot be computed")
print(f"  GPS quality: {hdop_note or gps_issue}")
if flagged_msgs:
    print("  MSG/ERR entries mentioning GPS/EKF/failsafe:")
    for ts, m in flagged_msgs:
        print(f"    t={ts:8.1f}  {m}")
else:
    print("  MSG/ERR: nothing mentioning GPS/EKF/failsafe/PreArm in this log")
if origin_note is not None:
    print(f"  (context only, not evidence of cause) ORGN ekf_origin and ahrs_home "
          f"are {origin_note:.1f} m apart -- can't tell from this log alone whether "
          f"that is related to the drift above.")
print("=" * 72)

# --- graph 1: horizontal track, POS vs GUIP, with the normal-wander circle ----
fig, ax = plt.subplots(figsize=(7, 7))
theta = np.linspace(0, 2 * np.pi, 100)
ax.plot(e0 + DISP_NORMAL_M * np.sin(theta), n0 + DISP_NORMAL_M * np.cos(theta),
        "--", color="#999999", lw=1.3, label=f"{DISP_NORMAL_M:.0f} m normal-wander line")
ax.plot(e_w, n_w, color="#d1620a", lw=2.2, label="POS (actual)")
if guip_available:
    ax.plot(ge_w, gn_w, color="#1f77b4", lw=1.6, ls="--", label="GUIP (commanded target)")
ax.plot(e0, n0, "ko", ms=7, label="liftoff")
ax.plot(e_w[i_dmax], n_w[i_dmax], "x", color="#c1121f", ms=10, mew=2.5,
        label=f"peak displacement ({d_max:.1f} m)")
ax.set_xlabel("east (m)")
ax.set_ylabel("north (m)")
ax.set_title(f"Climb-out horizontal track, t={t_lift:.0f}-{t_lift+CLIMB_WINDOW_S:.0f} s")
ax.axis("equal")
ax.grid(True, alpha=0.3)
ax.legend(loc="best", fontsize=9)
fig.tight_layout()
fig.savefig(f"{OUT_DIR}/fig1_horizontal_track.png", dpi=130)

# --- graph 2: displacement & tracking error vs time, thresholds marked -------
fig, ax = plt.subplots(figsize=(10, 5))
ax.plot(t_w - t_lift, disp, color="#d1620a", lw=2.2, label="horizontal displacement from liftoff")
if guip_available:
    e_series = np.hypot(n_w - np.interp(t_w, gt_w, gn_w), e_w - np.interp(t_w, gt_w, ge_w))
    ax.plot(t_w - t_lift, e_series, color="#1f77b4", lw=2, label="POS-vs-GUIP tracking error")
ax.axhline(DISP_NORMAL_M, color="#999999", ls="--", lw=1.4,
           label=f"{DISP_NORMAL_M:.0f} m normal-wander line")
ax.axvline(t_dmax - t_lift, color="#c1121f", ls=":", lw=1.5)
ax.set_xlabel("time since liftoff (s)")
ax.set_ylabel("metres")
ax.set_title("Displacement vs. commanded-target tracking error, climb-out window")
ax.legend(loc="best", fontsize=9)
ax.grid(True, alpha=0.3)
fig.tight_layout()
fig.savefig(f"{OUT_DIR}/fig2_displacement_vs_tracking.png", dpi=130)

print(f"\nwrote fig1_horizontal_track.png, fig2_displacement_vs_tracking.png to {OUT_DIR}/")
