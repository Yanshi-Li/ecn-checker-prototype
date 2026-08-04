# ECN Checker Test Scenarios — Version 1

## Initial failure scenario

The supplied `ecn_changes.csv` intentionally includes invalid data.

| Line | ECN action | Test scenario | Expected result |
|---:|---|---|---|
| 1 | REPLACE | Replace active C-200 with obsolete C-250 | PART-004 Blocker |
| 2 | REMOVE | Remove C-999, which is not in released BOM | BOM-001 Blocker |
| 3 | ADD | Add C-100, which already exists in BOM | BOM-002 Warning |
| 3 | ADD | Add safety-critical C-100 without Quality approval | REG-001 Warning |
| 4 | CHANGE_QUANTITY | Change C-300 quantity from 4 to 0 | BOM-003 Blocker |
| 5 | ADD | Add active C-400 with quantity 2 | Pass |

Expected final decision:

```text
FINAL DECISION: ECN cannot proceed.