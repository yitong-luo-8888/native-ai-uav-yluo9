#!/usr/bin/env python3
"""
Full analysis for GPS / POSITION lab (ArduPilot DataFlash log).

Produces:
  - track_gps_pos_guip.png   horizontal track (GPS + POS + GUIP + home)
  - altitude.png             altitude vs time (GPS + POS + GUIP)
  - gps_quality.png          HDop, NSats, Status vs time

Prints numerical findings for each lab question.
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

# ==================================================================
# Load CSVs
# ==================================================================
gps  = pd.read_csv("GPS.csv")
pos  = pd.read_csv("POS.csv")
guip = pd.read_csv("GUIP.csv")

# Force int64 on TimeUS for merge_asof
for df in (gps, pos, guip):
    if "TimeUS" in df.columns:
        df["TimeUS"] = df["TimeUS"].astype("int64")

try:
    orgn = pd.read_csv("ORGN.csv")
except FileNotFoundError:
    orgn = None
    print("WARNING: ORGN.csv not found")

try:
    err = pd.read_csv("ERR.csv")
except FileNotFoundError:
    err = None

try:
    mode = pd.read_csv("MODE.csv")
except FileNotFoundError:
    mode = None

try:
    msg = pd.read_csv("MSG.csv")
except FileNotFoundError:
    msg = None

# ==================================================================
# Auto-detect scaling for GPS/POS
# ==================================================================
def detect_lat_scale(series):
    """If |lat| > 180, values are deg*1e7; otherwise degrees."""
    v = series.dropna().abs().max()
    return 1e7 if v > 180 else 1.0

def detect_hdop_scale(series):
    """If HDop > 5, values are *100."""
    v = series.dropna().max()
    return 100.0 if v > 5 else 1.0

LAT_SCALE  = detect_lat_scale(gps["Lat"])
HDOP_SCALE = detect_hdop_scale(gps["HDop"])
print(f"Detected scales -> lat: /{LAT_SCALE}, HDop: /{HDOP_SCALE}")

# ==================================================================
# Origins (EKF origin = ORGN Type 0)
# ==================================================================
if orgn is not None and len(orgn):
    ekf_rows  = orgn[orgn["Type"] == 0]
    home_rows = orgn[orgn["Type"] == 1]
    if len(ekf_rows):
        lat0 = ekf_rows.iloc[0]["Lat"] / LAT_SCALE
        lon0 = ekf_rows.iloc[0]["Lng"] / LAT_SCALE
    else:
        lat0 = gps["Lat"].iloc[0] / LAT_SCALE
        lon0 = gps["Lng"].iloc[0] / LAT_SCALE
else:
    ekf_rows = home_rows = None
    lat0 = gps["Lat"].iloc[0] / LAT_SCALE
    lon0 = gps["Lng"].iloc[0] / LAT_SCALE

print(f"EKF origin used: lat={lat0:.7f}, lon={lon0:.7f}")

# ==================================================================
# lat/lon -> metres N/E relative to EKF origin
# ==================================================================
def to_ned(lat_deg, lng_deg):
    north = (lat_deg - lat0) * 111320.0
    east  = (lng_deg - lon0) * 111320.0 * np.cos(np.radians(lat0))
    return north, east

gps_n, gps_e = to_ned(gps["Lat"] / LAT_SCALE, gps["Lng"] / LAT_SCALE)
pos_n, pos_e = to_ned(pos["Lat"] / LAT_SCALE, pos["Lng"] / LAT_SCALE)

# ==================================================================
# GUIP decode
#   pX = Lat * 1e5
#   pY = Lng * 1e5
#   pZ = altitude in cm, negative above origin
# ==================================================================
guip_pos = guip[(guip["pX"] != 0) | (guip["pY"] != 0)].copy()
print(f"\nGUIP rows: total={len(guip)}, non-zero targets={len(guip_pos)}")

if len(guip_pos) == 0:
    print("WARNING: no non-zero GUIP targets.")
    guip_n = guip_e = guip_alt = pd.Series([], dtype=float)
    t_guip = pd.Series([], dtype=float)
else:
    g_lat = guip_pos["pX"] / 1e7
    g_lng = guip_pos["pY"] / 1e7

    print(f"  decoded GUIP first: lat={g_lat.iloc[0]:.7f}, lng={g_lng.iloc[0]:.7f}")
    print(f"  decoded GUIP last : lat={g_lat.iloc[-1]:.7f}, lng={g_lng.iloc[-1]:.7f}")

    guip_n, guip_e = to_ned(g_lat, g_lng)

    pz_max = abs(guip_pos["pZ"]).max()
    if pz_max > 1000:
        guip_alt = -guip_pos["pZ"] / 100.0
        print(f"  pZ treated as cm (max |pZ| = {pz_max:.0f})")
    else:
        guip_alt = -guip_pos["pZ"]
        print(f"  pZ treated as metres (max |pZ| = {pz_max:.0f})")

    t_guip = guip_pos["t_s"] if "t_s" in guip_pos.columns else guip_pos["TimeUS"] / 1e6

# ==================================================================
# Time axes
# ==================================================================
def time_axis(df):
    return df["t_s"] if "t_s" in df.columns else df["TimeUS"] / 1e6

t_gps = time_axis(gps)
t_pos = time_axis(pos)

# ==================================================================
# PLOT 1 — Horizontal track
# ==================================================================
fig, ax = plt.subplots(figsize=(9, 9))
ax.plot(gps_n, gps_e, 'g-',  lw=1.5, label="GPS (actual)")
ax.plot(pos_n, pos_e, 'r--', lw=1.5, label="POS (EKF estimate)")
if len(guip_n):
    ax.plot(guip_n, guip_e, 'b:', lw=2, label="GUIP (commanded target)")
ax.scatter([0], [0], c='k', marker='x', s=120, label="EKF origin")

if home_rows is not None and len(home_rows):
    h_n, h_e = to_ned(home_rows.iloc[0]["Lat"] / LAT_SCALE,
                      home_rows.iloc[0]["Lng"] / LAT_SCALE)
    ax.scatter([h_n], [h_e], c='orange', marker='s', s=100, label="Home (ORGN Type 1)")

ax.set_xlabel("North (m)")
ax.set_ylabel("East (m)")
ax.set_title("Horizontal track: GPS vs POS vs GUIP")
ax.legend()
ax.axis('equal')
ax.grid(True, alpha=0.3)
plt.tight_layout()
plt.savefig("track_gps_pos_guip.png", dpi=150)
plt.close()
print("Saved track_gps_pos_guip.png")

# ==================================================================
# PLOT 2 — Altitude vs time
# ==================================================================
fig, ax = plt.subplots(figsize=(11, 4))
ax.plot(t_gps, gps["Alt"] - gps["Alt"].iloc[0], 'g-', lw=1.5,
        label="GPS alt (rel. start)")
if "RelHomeAlt" in pos.columns:
    ax.plot(t_pos, pos["RelHomeAlt"], 'r--', lw=1.5, label="POS RelHomeAlt")
if len(guip_alt):
    ax.plot(t_guip, guip_alt - guip_alt.iloc[0], 'b:', lw=1.5,
            label="GUIP target alt (rel. start)")
ax.set_xlabel("Time (s)")
ax.set_ylabel("Altitude (m)")
ax.set_title("Altitude vs time")
ax.legend()
ax.grid(True, alpha=0.3)
plt.tight_layout()
plt.savefig("altitude.png", dpi=150)
plt.close()
print("Saved altitude.png")

# ==================================================================
# PLOT 3 — GPS quality
# ==================================================================
fig, axes = plt.subplots(3, 1, figsize=(11, 8), sharex=True)
axes[0].plot(t_gps, gps["HDop"] / HDOP_SCALE, 'b-')
axes[0].axhline(1.5, color='r', ls='--', label='good threshold (1.5)')
axes[0].set_ylabel("HDop")
axes[0].legend()
axes[1].plot(t_gps, gps["NSats"], 'b-')
axes[1].set_ylabel("Num sats")
axes[2].plot(t_gps, gps["Status"], 'b-')
axes[2].set_ylabel("Fix status")
axes[2].set_xlabel("Time (s)")
for a in axes:
    a.grid(True, alpha=0.3)
plt.tight_layout()
plt.savefig("gps_quality.png", dpi=150)
plt.close()
print("Saved gps_quality.png")

# ==================================================================
# FINDINGS
# ==================================================================
print("\n" + "=" * 70)
print("FINDINGS")
print("=" * 70)

# --- GPS vs POS agreement ---
gps_s = gps[["TimeUS", "Lat", "Lng"]].rename(columns={"Lat": "Lat_g", "Lng": "Lng_g"})
pos_s = pos[["TimeUS", "Lat", "Lng"]].rename(columns={"Lat": "Lat_p", "Lng": "Lng_p"})
merged = pd.merge_asof(
    gps_s.sort_values("TimeUS"),
    pos_s.sort_values("TimeUS"),
    on="TimeUS",
    direction="nearest",
    tolerance=100000,
).dropna()

if len(merged):
    dlat = (merged["Lat_g"] - merged["Lat_p"]) / LAT_SCALE
    dlng = (merged["Lng_g"] - merged["Lng_p"]) / LAT_SCALE
    dn = dlat * 111320.0
    de = dlng * 111320.0 * np.cos(np.radians(lat0))
    horiz = np.hypot(dn, de)
    print(f"\n[GPS vs POS agreement]")
    print(f"  samples compared: {len(merged)}")
    print(f"  |GPS - POS| horizontal: mean={horiz.mean():.2f} m, max={horiz.max():.2f} m")
    if horiz.max() < 3.0:
        print("  -> GPS and POS AGREE. EKF position estimate is healthy.")
    else:
        print("  -> GPS and POS DIVERGE. Position estimate may be unreliable.")

# --- GUIP target vs actual ---
if len(guip_pos) and len(pos):
    last_t = guip_pos["TimeUS"].iloc[-1]
    pos_last = pos.iloc[(pos["TimeUS"] - last_t).abs().argsort().iloc[0]]
    p_n = (pos_last["Lat"] / LAT_SCALE - lat0) * 111320.0
    p_e = (pos_last["Lng"] / LAT_SCALE - lon0) * 111320.0 * np.cos(np.radians(lat0))
    g_n, g_e = guip_n.iloc[-1], guip_e.iloc[-1]
    offset = np.hypot(g_n - p_n, g_e - p_e)
    print(f"\n[GUIP target vs actual at end of log]")
    print(f"  GUIP target : N={g_n:.2f} m, E={g_e:.2f} m")
    print(f"  POS actual  : N={p_n:.2f} m, E={p_e:.2f} m")
    print(f"  offset      : {offset:.2f} m")

# --- GUIP range ---
if len(guip_n):
    print(f"\n[GUIP target range]")
    print(f"  pX : min={guip_n.min():.2f}, max={guip_n.max():.2f} m, "
          f"range={guip_n.max()-guip_n.min():.2f} m")
    print(f"  pY : min={guip_e.min():.2f}, max={guip_e.max():.2f} m, "
          f"range={guip_e.max()-guip_e.min():.2f} m")
    print(f"  alt: min={guip_alt.min():.2f}, max={guip_alt.max():.2f} m")

# --- ORGN distance ---
if ekf_rows is not None and len(ekf_rows) and len(home_rows):
    e = ekf_rows.iloc[0]
    h = home_rows.iloc[0]
    dlat = (h["Lat"] - e["Lat"]) / LAT_SCALE
    dlng = (h["Lng"] - e["Lng"]) / LAT_SCALE
    dn = dlat * 111320.0
    de = dlng * 111320.0 * np.cos(np.radians(e["Lat"] / LAT_SCALE))
    dalt = h.get("Alt", 0) - e.get("Alt", 0)
    dist = np.hypot(dn, de)
    print(f"\n[ORGN records]")
    print(f"  EKF origin (Type 0): lat={e['Lat']/LAT_SCALE:.7f}, "
          f"lon={e['Lng']/LAT_SCALE:.7f}, alt={e.get('Alt','n/a')}")
    print(f"  Home      (Type 1): lat={h['Lat']/LAT_SCALE:.7f}, "
          f"lon={h['Lng']/LAT_SCALE:.7f}, alt={h.get('Alt','n/a')}")
    print(f"  horizontal distance: {dist:.2f} m")
    print(f"  altitude difference: {dalt:.2f} m")
    if dist > 3.0:
        print(f"  -> ORGN records are FAR APART ({dist:.1f} m). "
              f"Likely reference-frame mismatch.")

# --- GPS quality ---
print(f"\n[GPS quality]")
print(f"  HDop  : min={gps['HDop'].min()/HDOP_SCALE:.2f}, "
      f"max={gps['HDop'].max()/HDOP_SCALE:.2f}, "
      f"mean={gps['HDop'].mean()/HDOP_SCALE:.2f}")
print(f"  NSats : min={gps['NSats'].min()}, max={gps['NSats'].max()}")
print(f"  Status: unique = {sorted(gps['Status'].unique().tolist())}")

# --- ERR ---
if err is not None:
    print(f"\n[ERR]  rows: {len(err)}")
    if len(err):
        print(err.to_string(index=False))
else:
    print(f"\n[ERR]  CSV not found — generate with:")
    print(f'       mavlogdump.py --types ERR --format csv "<bin>" > ERR.csv')

# --- MSG ---
if msg is not None:
    print(f"\n[MSG]  rows: {len(msg)}")
    if len(msg):
        print(msg.head(20).to_string(index=False))

# --- MODE ---
if mode is not None:
    print(f"\n[MODE]  changes:")
    print(mode.to_string(index=False))

print("\nDone.")