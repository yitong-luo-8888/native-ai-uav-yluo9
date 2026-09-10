<<<<<<< HEAD
# uav-native-ai

**CSE 40701 — Native AI Software and Systems Engineering for UAVs.**

This repo is both the course website (published via GitHub Pages) and the
runnable infrastructure code students work with. If you're looking for the
syllabus, schedule, or lesson materials, the published site is easier to
read than browsing markdown source here:

**Course site:** https://janeclelandhuang.github.io/uav-native-ai/

## Layout

```
uav-native-ai/
  index.md, syllabus.md, schedule.md   <- course site pages (Jekyll source)
  lessons/                             <- one page per lesson
  _layouts/, _config.yml, assets/      <- site scaffolding/theme
  .venv/                               <- course-wide Python venv, see lab/SETUP.md Step 3
  lab/                                 <- runnable UAV infrastructure
                                           (ArduPilot SITL, MQTT backend,
                                           matplotlib viewer), added to as
                                           the course proceeds -- see
                                           lab/ARCHITECTURE.md. This is the
                                           part vendored into the student
                                           homework template repo, so it
                                           contains only student-facing
                                           material.
  instructor/                          <- instructor-only notes and tooling
                                           (SITL image publishing, lesson
                                           planning) -- see
                                           instructor/INSTRUCTOR.md
```

## Local development (site)

```
bundle exec jekyll serve
```

## Local development (lab infra)

See `lab/SETUP.md` and `lab/ARCHITECTURE.md`.
=======
# Native AI Software Engineering for UAV Disaster Response
## Fall 2026

**Course site (syllabus, schedule, lessons):** https://janeclelandhuang.github.io/uav-native-ai/

This repository is your individual workspace for the course.

## Environment setup

This repo includes `lab/` — the same UAV simulation environment (ArduPilot
SITL, MQTT backend) used throughout the course, and the one most homework
assignments run against. Requires Docker and Python 3.12+; see
[`lab/SETUP.md`](lab/SETUP.md) for one-time setup and
[`lab/ARCHITECTURE.md`](lab/ARCHITECTURE.md) for how it's put together.

`lab/` is updated periodically as the course proceeds — if you get a commit
from your instructor touching only `lab/`, that's an infra update; just
`git pull`.

## Multi-Vehicle GUI (`gui/`)

`gui/` is a second viewer, alongside `lab/client/matplotlib_view.py` — a
graphical, multi-vehicle GUI (map view, per-drone panels, simulated camera
feeds) instead of `matplotlib_view.py`'s single-vehicle plot. It's a
standalone app: get `lab/`'s simulation environment running first (see
[`lab/SETUP.md`](lab/SETUP.md)), with `UPDATE_DRONE` set in your `.env` —
already the case if you copied `.env-copy` or `.env-copy-multi` as
`SETUP.md` Step 3 has you do.

Install its dependencies and launch it from the repo root:

```bash
pip install -r gui/requirements.txt
python gui/dronemap.py
```

**WSL2 users:** see [`gui/readme-wsl.txt`](gui/readme-wsl.txt) for a
required system dependency (a missing Qt/xcb library) before the app will
open a window.

## Individual Assignments

Place each homework assignment in its corresponding directory:

- `hw01/`
- `hw02/`
- `hw03/`
- `hw04/`
- `hw05/`
- `hw06/`
- `hw07/`

## Submitting Your Work

There is no separate code submission.

For each homework assignment:

1. Complete your work in the appropriate `hwXX/` directory.
2. Commit your changes.
3. Push your changes to GitHub before the assignment deadline.

For example:

    git add .
    git commit -m "Complete HW01"
    git push

The version of your work present in this repository at the assignment
deadline will be treated as your submission.

You are encouraged to commit and push regularly while working rather
than making a single commit at the deadline.

## Use of AI

This is a Native AI software engineering course. Use of approved AI
tools is expected as part of the software engineering process.

You are responsible for understanding, evaluating, testing, and being
able to explain all work that you submit.
>>>>>>> target/main
