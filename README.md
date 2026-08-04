# ECN Checker Prototype — Version 1

A standalone Java prototype that validates Engineering Change Notice (ECN)
change lines against simulated master part and released Bill of Materials (BOM)
data.

## Purpose

The prototype demonstrates ECN checks before an ECN is submitted, approved,
implemented, or completed.

This Version 1 prototype does not require Windchill access. It uses CSV files
to simulate data that may later be retrieved from Windchill, a PLM, or an ERP.

## AI usage

This version uses **no AI models**.

It is a deterministic, rules-based checker:

```text
ECN CSV + Master BOM CSV + Part Master CSV
                ↓
          Java validation rules
                ↓
      PASS / WARNING / BLOCKER report
