
## `docs/architecture.md`

```markdown
# ECN Checker Architecture — Version 1

## Current prototype architecture

```text
+----------------------------+
| CSV Sample Data            |
|----------------------------|
| parts.csv                  |
| master_bom.csv             |
| ecn_header.csv             |
| ecn_changes.csv            |
+-------------+--------------+
              |
              v
+----------------------------+
| Java ECN Checker           |
|----------------------------|
| - CSV readers              |
| - Part-master validation   |
| - BOM validation           |
| - Quantity validation      |
| - Quality/safety checks    |
| - Pass/Warning/Blocker     |
+-------------+--------------+
              |
              v
+----------------------------+
| Console Report             |
|----------------------------|
| PASS / WARNING / BLOCKER   |
| Final ECN decision         |
+----------------------------+



## Future Target Architecture

```text
+--------------------------+
| Windchill                |
| ECN / Part / BOM data    |
+------------+-------------+
             |
             | Approved API / SDK / service
             v
+--------------------------+
| Windchill Adapter        |
| Host-specific code only  |
+------------+-------------+
             |
             v
+--------------------------+
| ECN Checker Core         |
|--------------------------|
| BOM comparison           |
| Validation rules         |
| Risk / workflow checks   |
| Audit result generation  |
+------------+-------------+
             |
             v
+--------------------------+
| Checker Interface        |
|--------------------------|
| Windchill plugin tab,    |
| web page, or dashboard   |
+--------------------------+