
# ECN Checker Rule Catalogue — Version 1

| Rule ID | Rule | Why it exists | Severity |
|---|---|---|---|
| BOM-001 | Existing component must exist in released BOM | Prevents a change being applied to the wrong or obsolete BOM line | Blocker |
| BOM-002 | Added component should not already exist | Helps detect incorrect ADD actions where a quantity change may be intended | Warning |
| BOM-003 | Quantity must be greater than zero | Prevents invalid component quantities entering a BOM | Blocker |
| R01 | ECN form must contain Description Of Change, Name of Change, Change Notice Number, Reason for Change | Ensures the configured ECN form headers are complete. `Name` maps to Name of Change; Engineering Change Number or `Number` maps to Change Notice Number. | Blocker |
| R02 | Part number must be exactly 5 or 6 digits | Keeps BOM part numbers in the required numeric format | Blocker |
| PART-001 | Proposed part must exist in part master | Ensures traceability and valid part data | Blocker |
| PART-004 | Proposed part must be ACTIVE | Prevents introduction of obsolete or blocked components | Blocker |
| REG-001 | Safety-critical change requires Quality approval | Ensures controlled review of higher-risk changes | Warning |
| ID-001 | Name of Change must be completed (marked with *) | Required to save and reserve an ECN/PCN number | Blocker |
| ID-002 | Avoid special characters `>, <, :, ", /, \, |, ?, *` in the Name of Change | Prevents system errors or file naming conflicts | Blocker |
| ID-003 | Project must be selected from the drop-down list | Makes it clear to Procurement and others which project is affected | Blocker |
| ID-004 | Product Group must be selected from the drop-down list | Identifies which product group is affected by the change | Blocker |
| ID-005 | Associated A3 field must be completed (Yes or No) | Ensures traceability of supporting A3 documents | Blocker |
| ID-006 | If Associated A3 is Yes, the A3 number(s) must be entered | Links the ECN/PCN to its supporting A3 document for traceability | Warning |


## Severity definitions

- **PASS:** The automated validation passed.
- **WARNING:** The ECN may need reviewer attention or additional evidence.
- **BLOCKER:** The ECN cannot proceed until corrected or formally waived.