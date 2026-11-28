"""Evaluation harness: open-loop run and closed-loop runs on the simulated plant.

* :mod:`~ovenbird_sim.evaluate.openloop` — any controller over a recorded capture,
  never sending; decision records in a result database; open-loop metrics only;
* :mod:`~ovenbird_sim.evaluate.closedloop` — a controller against the simulated plant,
  with an optional plan-slice provider and the forecast view it reads
  (:mod:`~ovenbird_sim.evaluate.forecast`);
* :mod:`~ovenbird_sim.evaluate.plangate` — paired runs with and without a plan over
  weather replicas, and the three-valued gate on their differences;
* :mod:`~ovenbird_sim.evaluate.recorded`, :mod:`~ovenbird_sim.evaluate.sensors` —
  recorded and simulated inputs;
* :mod:`~ovenbird_sim.evaluate.kpi` — outcome KPIs of a run;
* :mod:`~ovenbird_sim.evaluate.resultdb`, :mod:`~ovenbird_sim.evaluate.meta`,
  :mod:`~ovenbird_sim.evaluate.report` — outputs and provenance.

CLI: ``python -m ovenbird_sim.evaluate open-loop --help``.
"""
