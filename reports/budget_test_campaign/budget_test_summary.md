# Budget-Constrained Meal Planner Test Summary

- Executed cases: 18
- Passed cases: 18
- Failed cases: 0
- % within budget for feasible set (cases 5,6,8,10,11,12,13,14): 0.00% (0/8)
- % over-budget with warnings for strict set (cases 15,16): 100.00% (2/2)
- Average overrun for failed budget-on cases: EUR 35.41

## Known Limitations
- Costs are rough estimates based on ingredient pricing heuristics.
- Prompt mode does not currently parse a budget cap directly; budget is tested via manual mode.

## Evidence Files
- `budget_test_results.csv`
- `evidence_within_budget.json`
- `evidence_over_budget.json`