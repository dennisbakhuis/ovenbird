# ovenbird-sim

Development tooling: the simulated plant and HeishaMon board, open-loop runs of the
controller against recorded captures, closed-loop runs on the simulated plant (with an
optional plan-slice provider and a forecast view) and the paired-replica gate that judges
them. Depends on `ovenbird-core` and the capture package.

To turn a recording into an ovenbird `history.db` for the Replay tab, see
`ovenbird_harness.convert` (harness package; `make convert-capture`, `dev/README.md`).
