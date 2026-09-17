#!/usr/bin/env python3
"""
Compass health analyzer for ArduPilot logs.

Reads MAG.csv (all instances in one file, split on I column),
CTUN.csv (throttle), BAT.csv (current).

- Computes sqrt(MagX^2 + MagY^2 + MagZ^2) per compass instance
- Plots all compass magnitudes on one chart
- Picks the suspect compass and plots it vs throttle/current
- Correlates magnitude with throttle and current
- Uses Ofs* (hard-iron offsets), MO* (motor-comp offsets), Health
- Saves PNGs next to this script by default
"""

import os
import glob
import argparse
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")  # headless-safe; comment out if you want interactive popups
import matplotlib.pyplot as plt


# ---------- IO ----------

def find_file(log_dir, prefix):
    """Find a CSV whose basename starts with prefix (case-insensitive)."""
    for f in glob.glob(os.path.join(log_dir, "*.csv")):
        base = os.path.basename(f).upper()
        if base.startswith(prefix.upper()):
            return f
    return None


def load_csv(path):
    """ArduPilot per-message CSV: line 1 = header, line 2 = units (strings).
    Read with header from line 1, then drop the units row if it's non-numeric."""
    with open(path, "r", errors="ignore") as fh:
        header = fh.readline().strip().split(",")

    df = pd.read_csv(path, skiprows=1, names=header, low_memory=False)

    # Drop units row if TimeUS isn't numeric
    if len(df) > 0:
        try:
            float(df.iloc[0]["TimeUS"])
        except (ValueError, KeyError):
            df = df.iloc[1:].reset_index(drop=True)

    for c in df.columns:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["TimeUS"]).reset_index(drop=True)
    return df


# ---------- helpers ----------

def rolling_mean(y, win=5):
    if win <= 1 or len(y) < win:
        return y
    return pd.Series(y).rolling(win, center=True, min_periods=1).mean().values


def resample_to(t_src, y_src, t_target):
    return np.interp(t_target, t_src, y_src)


# ---------- main ----------

def analyze(log_dir, out_dir=None):
    if out_dir is None:
        out_dir = os.path.dirname(os.path.abspath(__file__))
    os.makedirs(out_dir, exist_ok=True)

    mag_path = find_file(log_dir, "MAG")
    ctun_path = find_file(log_dir, "CTUN")
    bat_path = find_file(log_dir, "BAT")

    if not mag_path:
        print("No MAG.csv found.")
        return

    mag = load_csv(mag_path)
    print(f"Loaded {mag_path}: {len(mag)} rows")
    if "I" not in mag.columns:
        print("MAG file has no 'I' (instance) column — cannot split instances.")
        return

    instances = sorted(mag["I"].dropna().unique().astype(int))
    print(f"Instances found: {instances}")

    # Per-instance data
    compasses = {}
    for inst in instances:
        sub = mag[mag["I"] == inst].sort_values("TimeUS").reset_index(drop=True)
        if len(sub) < 10:
            continue

        x, y, z = sub["MagX"].values, sub["MagY"].values, sub["MagZ"].values
        magraw = np.sqrt(x * x + y * y + z * z)
        mags = rolling_mean(magraw, win=5)

        t = sub["TimeUS"].values / 1e6

        # Offset diagnostics
        ofs_mag = np.sqrt(sub["OfsX"].values ** 2 +
                          sub["OfsY"].values ** 2 +
                          sub["OfsZ"].values ** 2)
        mot_mag = np.sqrt(sub["MOX"].values ** 2 +
                          sub["MOY"].values ** 2 +
                          sub["MOZ"].values ** 2)

        compasses[inst] = {
            "t": t,
            "mag_raw": magraw,
            "mag": mags,
            "mean": float(np.nanmean(magraw)),
            "std": float(np.nanstd(magraw)),
            "ptp": float(np.nanmax(magraw) - np.nanmin(magraw)),
            "ofs_mean": float(np.nanmean(ofs_mag)),
            "ofs_ptp": float(np.nanmax(ofs_mag) - np.nanmin(ofs_mag)),
            "mot_mean": float(np.nanmean(mot_mag)),
            "mot_ptp": float(np.nanmax(mot_mag) - np.nanmin(mot_mag)),
            "health": float(np.nanmean(sub["Health"].values)) if "Health" in sub else np.nan,
            "n": len(sub),
        }
        c = compasses[inst]
        print(f"  Compass {inst}: n={c['n']}  mag mean={c['mean']:.1f} mG  "
              f"std={c['std']:.1f}  ptp={c['ptp']:.1f}  |  "
              f"Ofs|={c['ofs_mean']:.1f}  |MO|={c['mot_mean']:.1f} "
              f"(ptp {c['mot_ptp']:.1f})  health={c['health']:.2f}")

    if not compasses:
        print("No usable compass data.")
        return

    # Load throttle & current
    throttle_t = throttle = None
    curr_t = curr = None

    if ctun_path:
        ctun = load_csv(ctun_path)
        if "ThO" in ctun.columns:
            throttle_t = ctun["TimeUS"].values / 1e6
            throttle = ctun["ThO"].values
            print(f"CTUN: {len(ctun)} rows, ThO range "
                  f"{np.nanmin(throttle):.2f}..{np.nanmax(throttle):.2f}")
    if bat_path:
        bat = load_csv(bat_path)
        if "Curr" in bat.columns:
            curr_t = bat["TimeUS"].values / 1e6
            curr = bat["Curr"].values
            print(f"BAT:  {len(bat)} rows, Curr range "
                  f"{np.nanmin(curr):.2f}..{np.nanmax(curr):.2f}")

    # ---------- Chart 1: all compass magnitudes ----------
    fig1, ax1 = plt.subplots(figsize=(12, 5))
    for inst, d in compasses.items():
        ax1.plot(d["t"], d["mag"],
                 label=f"Compass {inst} (mean {d['mean']:.0f} mG, "
                       f"std {d['std']:.1f}, ptp {d['ptp']:.0f})",
                 linewidth=1.2)
    ax1.axhline(500, color="grey", linestyle="--", linewidth=0.8,
                label="~500 mG nominal")
    ax1.axhline(600, color="red", linestyle=":", linewidth=0.8,
                label="600 mG suspect threshold")
    ax1.set_xlabel("Time (s)")
    ax1.set_ylabel("Field magnitude (mG)")
    ax1.set_title("Compass field magnitude over flight")
    ax1.legend(loc="best", fontsize=8)
    ax1.grid(alpha=0.3)
    fig1.tight_layout()
    out1 = os.path.join(out_dir, "compass_magnitudes.png")
    fig1.savefig(out1, dpi=140)
    plt.close(fig1)
    print(f"\nSaved {out1}")

    # ---------- Pick suspect ----------
    insts = list(compasses.keys())
    means = np.array([compasses[i]["mean"] for i in insts])
    stds = np.array([compasses[i]["std"] for i in insts])

    med_mean = np.median(means)
    dev = np.abs(means - med_mean)
    score = dev + stds
    suspect = insts[int(np.argmax(score))]
    print(f"\nSuspect compass: {suspect} "
          f"(mean={compasses[suspect]['mean']:.1f}, "
          f"std={compasses[suspect]['std']:.1f}, "
          f"dev-from-median={compasses[suspect]['mean'] - med_mean:+.1f})")

    # ---------- Chart 2: suspect vs load ----------
    corr_tho = np.nan
    corr_curr = np.nan

    if throttle_t is not None or curr_t is not None:
        fig2, ax2 = plt.subplots(figsize=(12, 5))
        d = compasses[suspect]
        ax2.plot(d["t"], d["mag"], color="C3", linewidth=1.2,
                 label=f"Compass {suspect} magnitude")
        ax2.set_xlabel("Time (s)")
        ax2.set_ylabel("Suspect compass magnitude (mG)", color="C3")
        ax2.tick_params(axis="y", labelcolor="C3")
        ax2.grid(alpha=0.3)

        ax2b = ax2.twinx()
        if throttle_t is not None:
            th = resample_to(throttle_t, throttle, d["t"])
            ax2b.plot(d["t"], th * 100, color="C0", alpha=0.6, linewidth=1.0,
                      label="Throttle output (%)")
        if curr_t is not None:
            cc = resample_to(curr_t, curr, d["t"])
            ax2b.plot(d["t"], cc, color="C2", alpha=0.6, linewidth=1.0,
                      label="Current (A)")
        ax2b.set_ylabel("Throttle % / Current A", color="C0")
        ax2b.tick_params(axis="y", labelcolor="C0")

        l1, la1 = ax2.get_legend_handles_labels()
        l2, la2 = ax2b.get_legend_handles_labels()
        ax2.legend(l1 + l2, la1 + la2, loc="best", fontsize=8)
        ax2.set_title(f"Suspect compass (instance {suspect}) vs throttle / current")
        fig2.tight_layout()
        out2 = os.path.join(out_dir, "suspect_vs_load.png")
        fig2.savefig(out2, dpi=140)
        plt.close(fig2)
        print(f"Saved {out2}")

        # Correlations
        print("\nCorrelation of suspect magnitude with load:")
        d_mag = d["mag"]
        if throttle_t is not None:
            th = resample_to(throttle_t, throttle, d["t"])
            m = np.isfinite(d_mag) & np.isfinite(th)
            if m.sum() > 10:
                corr_tho = float(np.corrcoef(d_mag[m], th[m])[0, 1])
                print(f"  vs ThO   : r = {corr_tho:+.3f}")
        if curr_t is not None:
            cc = resample_to(curr_t, curr, d["t"])
            m = np.isfinite(d_mag) & np.isfinite(cc)
            if m.sum() > 10:
                corr_curr = float(np.corrcoef(d_mag[m], cc[m])[0, 1])
                print(f"  vs Curr  : r = {corr_curr:+.3f}")

    # ---------- Peer comparison ----------
    print("\nDeviation of each compass from the median of the others:")
    for i in insts:
        others = [compasses[o]["mean"] for o in insts if o != i]
        if not others:
            continue
        med_others = np.median(others)
        dd = compasses[i]["mean"] - med_others
        flag = "  <-- offset >60 mG from peers" if abs(dd) > 60 else ""
        print(f"  Compass {i}: mean={compasses[i]['mean']:.1f}  "
              f"diff vs peers={dd:+.1f}{flag}")

    # ---------- Verdict ----------
    print("\n" + "=" * 60)
    print("VERDICT")
    print("=" * 60)
    s = compasses[suspect]
    reasons = []
    if s["ptp"] > 80:
        reasons.append(f"magnitude swings {s['ptp']:.0f} mG peak-to-peak")
    if s["mean"] > 600:
        reasons.append(f"mean offset {s['mean']:.0f} mG (>600)")
    if abs(s["mean"] - med_mean) > 60:
        reasons.append(f"offset {s['mean'] - med_mean:+.0f} mG from peer median")
    if not np.isnan(corr_tho) and abs(corr_tho) > 0.5:
        reasons.append(f"magnitude correlates with throttle (r={corr_tho:+.2f})")
    if not np.isnan(corr_curr) and abs(corr_curr) > 0.5:
        reasons.append(f"magnitude correlates with current (r={corr_curr:+.2f})")
    if s["mot_ptp"] > 20:
        reasons.append(f"motor-comp offsets swing {s['mot_ptp']:.0f} mG "
                       f"(system is actively correcting a throttle-coupled field)")
    if not np.isnan(s["health"]) and s["health"] < 0.9:
        reasons.append(f"logged Health={s['health']:.2f} (<1.0)")

    if reasons:
        print(f"  Compass {suspect} is SUSPECT:")
        for r in reasons:
            print(f"    - {r}")
        print("  Do NOT trust this compass for heading.")
        print("  Likely cause: magnetic coupling to power wiring / nearby ferrous mass.")
    else:
        print(f"  No compass looks clearly bad.")

    print(f"\nPNGs written to: {out_dir}")


# ---------- entry ----------

if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="Analyze ArduPilot compass health from CSVs.")
    ap.add_argument("log_dir",
                    help="Directory containing MAG.csv, CTUN.csv, BAT.csv")
    ap.add_argument("--out", default=None,
                    help="Output dir for PNGs (default: script's own directory)")
    args = ap.parse_args()
    analyze(args.log_dir, args.out)