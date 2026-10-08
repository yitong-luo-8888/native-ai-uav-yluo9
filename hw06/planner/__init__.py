"""HW6 Human-on-the-Loop mission response planner.

mission/events -> PersonRegistry -> candidates -> DecisionSource -> Validator
-> Executor -> uav/<id>/command, with every verdict and execution state
reported back on mission/action_result and mission/behavior_status.
"""
