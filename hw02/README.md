Before each test run, reset drone positions:

```bash
python reset_drones.py

Visualize Drone Positions
python gui_tracker.py

# From hw02/ directory
source ../.venv/bin/activate
python start_tests.py <workload.json> <min-separation-m>