"""Evaluation harness: open-loop run and counterfactual replay (closed loop).

* :mod:`~ovenbird_sim.evaluate.openloop` — any controller over a recorded capture,
  never sending; decision records in a result database; open-loop metrics only;
* :mod:`~ovenbird_sim.evaluate.counterfactual` — ovenbird against the recorded
  setpoints on the fitted plant: baseline gate (the plant on the recorded setpoints
  against the measurements), paired differences over a parameter bootstrap,
  refuse-to-claim rules and term ablation;
* :mod:`~ovenbird_sim.evaluate.recorded`, :mod:`~ovenbird_sim.evaluate.closedloop`,
  :mod:`~ovenbird_sim.evaluate.sensors` — recorded and simulated inputs;
* :mod:`~ovenbird_sim.evaluate.kpi`, :mod:`~ovenbird_sim.evaluate.claims`,
  :mod:`~ovenbird_sim.evaluate.ablation`, :mod:`~ovenbird_sim.evaluate.ensemble` —
  outcomes, claims, attribution, uncertainty;
* :mod:`~ovenbird_sim.evaluate.resultdb`, :mod:`~ovenbird_sim.evaluate.meta`,
  :mod:`~ovenbird_sim.evaluate.report` — outputs and provenance.

CLI: ``python -m ovenbird_sim.evaluate {open-loop,counterfactual} --help``.
"""
