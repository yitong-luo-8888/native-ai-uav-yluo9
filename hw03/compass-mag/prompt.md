# Compass Health Failure — Diagnostic Prompt

You are analysing an ArduPilot DataFlash log that has already been converted to
CSV. I will paste (or you will find in the working directory) a set of CSVs, one
per log message type. Your job is to determine, in a single response, **whether
one of the onboard compasses is unhealthy — and if so, which one and why.**

Do not ask me follow-up questions. Do not ask me to run anything. Inspect the
files, run whatever code you need to answer, and produce the final answer in the
format specified below.

---

## 1. Input

You are given one CSV per message type, extracted from an ArduPilot `.bin` log
by a tool such as `mavlogdump.py --format csv --types <TYPES>`. Each CSV has a
header row. Relevant files and columns:

| File | Required columns | Notes |
|------|------------------|-------|
| `MAG.csv` | `TimeUS`, `I`, `MagX`, `MagY`, `MagZ`, `OfsX`, `OfsY`, `OfsZ`, `MOX`, `MOY`, `MOZ`, `Health` | `I` = compass instance. Multiple instances in one file. |
| `CTUN.csv` | `TimeUS`, `ThO` | Throttle output (0–1). |
| `BAT.csv` | `TimeUS`, `Curr` | Battery current (A). |
| `MSG.csv` | `TimeUS`, `Message` | Autopilot text messages. |
| `ERR.csv` | `TimeUS`, `Subsys`, `ECode` | Error events. May be empty or missing. |

If a file is missing, note it in the final answer but do not abort. If a column
is missing, treat that specific diagnostic as "not enough data".

The user's extraction tool writes **two header rows**: row 1 is column names,
row 2 is units (strings). When you load, skip the units row if `TimeUS` in the
first data row is non-numeric.

---

## 2. Diagnostic logic

For each compass instance `i` in `MAG.csv` (split on column `I`):

### Signal A — Field magnitude

```
mag_raw(t) = sqrt(MagX^2 + MagY^2 + MagZ^2)
mag(t)     = rolling_mean(mag_raw, window=5)
```

Report per instance: mean, std, peak-to-peak (`ptp = max - min`).

- **Nominal** if `mean` is roughly 200–600 mG and `ptp < 80 mG`.
- **Suspect** if `mean > 600 mG` OR `ptp > 80 mG`.

### Signal B — Hard-iron offsets

```
ofs_mag(t) = sqrt(OfsX^2 + OfsY^2 + OfsZ^2)
```

Report mean and peak-to-peak per instance. A healthy compass has stable offsets.
Large ptp suggests the calibration is being re-estimated in flight, which
usually means the field is being disturbed.

### Signal C — Motor-compensation offsets (throttle-coupled field)

```
mot_mag(t) = sqrt(MOX^2 + MOY^2 + MOZ^2)
```

Report mean and ptp. `ptp > 20 mG` means the system is actively correcting a
field that changes with throttle — a classic sign of power-wiring interference.

### Signal D — Peer comparison

Compare each instance's mean against the median of the other instances:

```
median_others = median(mean of all j != i)
delta_i       = mean_i - median_others
```

- **Peer-consistent** if `|delta_i| < 60 mG`.
- **Peer-deviant** if `|delta_i| >= 60 mG`.

### Signal E — Load correlation

Resample `CTUN.ThO` (×100 for percent) and `BAT.Curr` onto each compass's
timeline using nearest-neighbour interpolation. Compute Pearson correlation:

```
r_tho[i]  = corr(mag_i, ThO)
r_curr[i] = corr(mag_i, Curr)
```

- **Coupled to load** if `|r| > 0.5`.
- **Decoupled** if `|r| <= 0.5`.

### Signal F — Health flag

If `MAG.Health` exists, report its mean per instance.
- **Healthy** if `mean >= 0.9`.
- **Degraded** if `mean < 0.9`.

### Suspect score

For each instance, compute:

```
score_i = |mean_i - median(all means)| + std_i
```

The highest-scoring instance is the **prime suspect**.

---

## 3. Verdict logic

Answer **exactly one** of these:

1. **"Compass N is unhealthy"** — the prime suspect fails at least two of:
   Signal A (magnitude out of range), Signal D (peer-deviant), Signal E
   (correlated with throttle or current), Signal F (Health < 0.9). State which
   two.
2. **"Compass N is marginal"** — the prime suspect fails exactly one signal.
   State which one and how far out of range it is.
3. **"No compass problem detected"** — all instances pass all signals.
4. **"Not enough data to decide"** — `MAG.csv` is missing or has fewer than 2
   instances, or fewer than 100 samples in total. State which signal(s) blocked
   the verdict.

Priority: (1) beats (2). If (1) applies, do not also claim (2).

---

## 4. Output format (strict)

Respond with **exactly** these sections, in this order:

### VERDICT
One sentence. Start with one of the four labels above, then a plain-English
summary. Example: *"Compass 1 is unhealthy — its field magnitude swings 180 mG
peak-to-peak and correlates with throttle at r = +0.72, indicating magnetic
coupling to the power system."*

### GRAPH
Render the following two plots inline (matplotlib, save to files
`prompt_compass_magnitudes.png` and `prompt_suspect_vs_load.png`, and display
them):

1. **Compass magnitudes over flight** — one line per instance. Horizontal
   reference lines at 500 mG (nominal) and 600 mG (suspect threshold). Axis
   labels, legend, grid.

2. **Suspect compass vs load** — suspect magnitude on the left axis; ThO ×100
   (throttle %) and Curr (A) on the right axis, both on the same timeline.

State in one sentence what the reader should look at in the graph.

### EVIDENCE
Bulleted list. Each bullet must contain a **specific number**. Cover:

- Per-instance magnitude: mean, std, ptp (one line per compass).
- Per-instance offsets: |Ofs| mean, |MO| mean and ptp (one line per compass).
- Peer comparison: delta vs median of others for each instance.
- Correlations: `r_tho` and `r_curr` for the suspect.
- Health flag: mean per instance (or "no Health column").
- Any relevant `MSG` lines (quote them).

### CONFIDENCE
One of **High / Medium / Low**, with a one-sentence justification. Use High
when all required CSVs are present and at least two independent signals agree.
Medium when one signal is missing or weak. Low when the verdict rests on a
single signal.

### WHAT THE DATA CANNOT ESTABLISH
Bulleted list of at least three things the log does not tell you, and for each,
say where that information would have to come from instead. Always include:

- Whether the magnetic interference is from wiring, a motor, or an external
  source. → Requires physical inspection, a compass swing test, or bench
  measurement with the motors running.
- Whether the compass calibration is stale or was performed with the vehicle
  in a bad location. → Requires the `PARM` compass calibration values and a
  fresh calibration attempt.
- Whether the EKF was actually affected. → Requires `XKF1`/`XKF4` (EKF state)
  and `ATT` (attitude) messages, which may not be in this extraction.

---

## 5. Rules

- Do not ask clarifying questions. Decide based on the data present.
- Do not invent numbers. Every value in EVIDENCE must be computed from the CSVs.
- Do not conflate "compass exists" with "compass is fine". A degraded compass
  can still return values — the signals above are what matter.
- If you must write code to answer, write it, run it, and discard it. The user
  does not maintain your code.
- Keep the total response under ~400 words of prose (graphs and tables excluded).