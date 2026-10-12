export type AttemptFilters = {
  ecn_number: string;
  source_status: string;
  decision: string;
};

/** Build the canonical query contract shared by tester and admin attempt lists. */
export function buildAttemptFilterParams(filters: AttemptFilters): URLSearchParams {
  return new URLSearchParams({
    ecn_number: filters.ecn_number,
    source_status: filters.source_status,
    decision: filters.decision,
  });
}
