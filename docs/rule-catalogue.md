
# ECN Checker Rule Catalogue — Version 1

| Rule ID | Rule | Why it exists | Severity |
|---|---|---|---|
| BOM-001 | Existing component must exist in released BOM | Prevents a change being applied to the wrong or obsolete BOM line | Blocker |
| BOM-002 | Added component should not already exist | Helps detect incorrect ADD actions where a quantity change may be intended | Warning |
| BOM-003 | Quantity must be greater than zero | Prevents invalid component quantities entering a BOM | Blocker |
| PART-001 | Proposed part must exist in part master | Ensures traceability and valid part data | Blocker |
| PART-004 | Proposed part must be ACTIVE | Prevents introduction of obsolete or blocked components | Blocker |
| REG-001 | Safety-critical change requires Quality approval | Ensures controlled review of higher-risk changes | Warning |

## Severity definitions

- **PASS:** The automated validation passed.
- **WARNING:** The ECN may need reviewer attention or additional evidence.
- **BLOCKER:** The ECN cannot proceed until corrected or formally waived.