#!/bin/bash

if [ -z "$1" ]; then
  echo "Usage: $0 <input-json-file>"
  exit 1
fi

jq -r '
  . as $root |
  "Summary Report in USD",
  "-----------------------------",
  "Total Detected Resources: \($root.summary.totalDetectedResources)",
  "Total Supported Resources: \($root.summary.totalSupportedResources)",
  "Total Unsupported Resources: \($root.summary.totalUnsupportedResources)",
  "Total Usage-Based Resources: \($root.summary.totalUsageBasedResources)",
  "Total No-Price Resources: \($root.summary.totalNoPriceResources)",
  "Unsupported Resource Counts: \($root.summary.unsupportedResourceCounts | to_entries | map("\(.key): \(.value)") | join(", "))",
  "No-Price Resource Counts: \($root.summary.noPriceResourceCounts | to_entries | map("\(.key): \(.value)") | join(", "))",
  "",
  "Costs",
  "-----------------------------",
  "Total Hourly Cost: $\($root.totalHourlyCost | tonumber | . * 100 | floor / 100) / hour",
  "Total Monthly Cost: $\($root.totalMonthlyCost | tonumber | . * 100 | floor / 100)",
  "Past Total Hourly Cost: $\($root.pastTotalHourlyCost | tonumber | . * 100 | floor / 100) / hour",
  "Past Total Monthly Cost: $\($root.pastTotalMonthlyCost | tonumber | . * 100 | floor / 100)",
  "Diff Total Hourly Cost: $\($root.diffTotalHourlyCost | tonumber | . * 100 | floor / 100) / hour",
  "Diff Total Monthly Cost: $\($root.diffTotalMonthlyCost | tonumber | . * 100 | floor / 100)"
' "$1"
