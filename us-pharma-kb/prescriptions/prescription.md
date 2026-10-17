---
type: Process
title: Prescription
description: A prescriber's order specifying drug, strength, quantity, directions, refills and DAW; identified at the pharmacy by Rx number + fill number.
tags:
- rx
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
relations:
- predicate: generates_data
  target: /data-assets/rx-audit/iqvia-xponent.md
- predicate: implements
  target: /data-model/entities/prescription.md
---
# Definition
A prescriber's order specifying drug, strength, quantity, directions, refills and DAW; identified at the pharmacy by Rx number + fill number.

# Where it is recorded
1. EHR order (prescriber side)
2. e-prescribing network message log
3. Pharmacy management system (system of record for dispensing)
4. PBM/payer claim
Data vendors buy (3) and (4); Xponent and LAAD are built from them.

# Relationships
* **generates_data** → [IQVIA Xponent (Prescriber-Level Rx)](/data-assets/rx-audit/iqvia-xponent.md)
* **implements** → [Prescription](/data-model/entities/prescription.md)

