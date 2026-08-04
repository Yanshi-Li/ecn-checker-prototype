import java.io.IOException;
import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/*
 * ECN Checker Prototype - Version 1
 *
 * Purpose:
 * - Simulate ECN validation against a released master BOM and part master.
 * - Uses CSV files only; no Windchill integration and no AI model.
 *
 * Compile:
 *   javac -d out src/EcnCheckerSimulation.java
 *
 * Run:
 *   java -cp out EcnCheckerSimulation
 */
public class EcnCheckerSimulation {

    private static final Path DATA_FOLDER = Path.of("data");

    public static void main(String[] args) {
        try {
            Map<String, Part> parts = loadParts(DATA_FOLDER.resolve("parts.csv"));
            List<BomLine> releasedBom = loadBom(DATA_FOLDER.resolve("master_bom.csv"));
            List<EcnHeader> ecnHeaders = loadEcnHeaders(DATA_FOLDER.resolve("ecn_header.csv"));
            List<EcnChangeLine> changes = loadEcnChanges(DATA_FOLDER.resolve("ecn_changes.csv"));

            System.out.println("==================================================");
            System.out.println("          ECN CHECKER PROTOTYPE - VERSION 1      ");
            System.out.println("==================================================");
            System.out.println("Source: CSV simulation data");
            System.out.println("AI model used: No");
            System.out.println();

            List<EcnDashboardView> dashboardReports = new ArrayList<>();

            for (EcnHeader ecn : ecnHeaders) {
                List<CheckResult> results = runChecks(ecn, changes, releasedBom, parts);
                printReport(ecn, results);
                dashboardReports.add(buildDashboardReport(ecn, results));
            }

            writeDashboardOutputs(dashboardReports);

        } catch (IOException e) {
            System.err.println("ERROR: Could not read a CSV input file.");
            System.err.println("Reason: " + e.getMessage());
            System.err.println("Run the program from the repository root folder.");
            System.exit(1);
        } catch (Exception e) {
            System.err.println("ERROR: Unexpected program error.");
            e.printStackTrace();
            System.exit(1);
        }
    }

    private static List<CheckResult> runChecks(
            EcnHeader ecn,
            List<EcnChangeLine> allChanges,
            List<BomLine> releasedBom,
            Map<String, Part> parts) {

        List<CheckResult> results = new ArrayList<>();

        // ECN-001: The affected assembly must exist in the part master.
        Part assembly = parts.get(ecn.affectedAssembly());

        if (assembly == null) {
            results.add(blocker(
                    "ECN-001",
                    "Affected assembly does not exist in the part master: "
                            + ecn.affectedAssembly(),
                    "Correct the affected assembly before submitting the ECN."
            ));
            return results;
        }

        results.add(pass(
                "ECN-001",
                "Affected assembly exists in the part master: " + ecn.affectedAssembly()
        ));

        List<EcnChangeLine> ecnChanges = allChanges.stream()
                .filter(change -> change.ecnId().equals(ecn.ecnId()))
                .sorted(Comparator.comparingInt(change -> Integer.parseInt(change.lineNumber())))
                .toList();

        // ECN-002: An ECN must contain at least one change line.
        if (ecnChanges.isEmpty()) {
            results.add(blocker(
                    "ECN-002",
                    "No ECN change lines were found for " + ecn.ecnId(),
                    "Add at least one BOM change line."
            ));
            return results;
        }

        results.add(pass(
                "ECN-002",
                "ECN contains " + ecnChanges.size() + " change line(s)."
        ));

        for (EcnChangeLine line : ecnChanges) {
            checkParentAssemblyMatchesEcn(ecn, line, results);
            checkExistingPartInReleasedBom(ecn, line, releasedBom, results);
            checkNewPartExistsAndIsActive(line, parts, results);
            checkAddedPartIsNotAlreadyInBom(ecn, line, releasedBom, results);
            checkQuantity(line, results);
            checkSafetyCriticalApproval(ecn, line, parts, results);
        }

        return results;
    }

    // ECN-003: Each change line must use the ECN affected assembly.
    private static void checkParentAssemblyMatchesEcn(
            EcnHeader ecn,
            EcnChangeLine line,
            List<CheckResult> results) {

        if (!line.parentPartNumber().equals(ecn.affectedAssembly())) {
            results.add(blocker(
                    "ECN-003",
                    "Line " + line.lineNumber() + ": Parent assembly "
                            + line.parentPartNumber() + " does not match ECN affected assembly "
                            + ecn.affectedAssembly() + ".",
                    "Correct the parent assembly or create a separate ECN."
            ));
        } else {
            results.add(pass(
                    "ECN-003",
                    "Line " + line.lineNumber() + ": Parent assembly matches ECN."
            ));
        }
    }

    /*
     * BOM-001:
     * REMOVE, REPLACE, and CHANGE_QUANTITY require the old part
     * to exist in the released BOM.
     */
    private static void checkExistingPartInReleasedBom(
            EcnHeader ecn,
            EcnChangeLine line,
            List<BomLine> releasedBom,
            List<CheckResult> results) {

        boolean requiresExistingPart =
                line.action() == ChangeAction.REMOVE
                        || line.action() == ChangeAction.REPLACE
                        || line.action() == ChangeAction.CHANGE_QUANTITY;

        if (!requiresExistingPart) {
            return;
        }

        boolean exists = releasedBom.stream().anyMatch(bom ->
                bom.parentPartNumber().equals(ecn.affectedAssembly())
                        && bom.componentPartNumber().equals(line.oldPartNumber())
                        && bom.status().equals("RELEASED")
        );

        if (!exists) {
            results.add(blocker(
                    "BOM-001",
                    "Existing component must exist in the released BOM",
                    "Line " + line.lineNumber() + ": Existing component '"
                            + line.oldPartNumber() + "' was not found in released BOM.",
                    "Searched released BOM for parent=" + ecn.affectedAssembly()
                            + ", component=" + line.oldPartNumber()
                            + ". No matching RELEASED record was found.",
                    "An ECN cannot remove, replace, or change quantity for a component "
                            + "that is not in the current released BOM.",
                    "Correct the old part number or select a component from the released BOM."
            ));
        } else {
            results.add(pass(
                    "BOM-001",
                    "Existing component must exist in the released BOM",
                    "Line " + line.lineNumber() + ": Existing component '"
                            + line.oldPartNumber() + "' exists in the released BOM.",
                    "Released BOM record found: parent=" + ecn.affectedAssembly()
                            + ", component=" + line.oldPartNumber()
                            + ", status=RELEASED.",
                    "The ECN change refers to a valid currently released BOM component."
            ));
        }
    }

    /*
     * PART-001: New component must exist in part master.
     * PART-004: New component lifecycle status must be ACTIVE.
     */
    private static void checkNewPartExistsAndIsActive(
            EcnChangeLine line,
            Map<String, Part> parts,
            List<CheckResult> results) {

        boolean requiresNewPart =
                line.action() == ChangeAction.ADD
                        || line.action() == ChangeAction.REPLACE;

        if (!requiresNewPart) {
            return;
        }

        if (line.newPartNumber().isBlank()) {
            results.add(blocker(
                    "PART-001",
                    "Line " + line.lineNumber() + ": New part number is missing.",
                    "Enter a proposed new part number."
            ));
            return;
        }

        Part newPart = parts.get(line.newPartNumber());

        if (newPart == null) {
            results.add(blocker(
                    "PART-001",
                    "Line " + line.lineNumber() + ": Proposed part '"
                            + line.newPartNumber() + "' does not exist in the part master.",
                    "Create/select a valid approved part."
            ));
            return;
        }

        results.add(pass(
                "PART-001",
                "Line " + line.lineNumber() + ": Proposed part '"
                        + line.newPartNumber() + "' exists in part master."
        ));

        if (!newPart.lifecycleStatus().equals("ACTIVE")) {
            results.add(blocker(
        "PART-004",
        "Proposed added or replacement part must have ACTIVE lifecycle status",
        "Line " + line.lineNumber() + ": Proposed part '"
                + line.newPartNumber() + "' has lifecycle status "
                + newPart.lifecycleStatus() + ".",
        "Part master record: partNumber=" + newPart.partNumber()
                + ", lifecycleStatus=" + newPart.lifecycleStatus(),
        "The ECN attempts to add or replace a BOM component with a part "
                + "that is not active. This could create supply, design, "
                + "or production risk.",
        "Select an ACTIVE part or obtain a controlled waiver."
));
        } else {
            results.add(pass(
        "PART-004",
        "Proposed added or replacement part must have ACTIVE lifecycle status",
        "Line " + line.lineNumber() + ": Proposed part '"
                + line.newPartNumber() + "' has lifecycle status ACTIVE.",
        "Part master record: partNumber=" + newPart.partNumber()
                + ", lifecycleStatus=ACTIVE",
        "The proposed part is active and is eligible for further ECN review."
));
        }
    }

    /*
     * BOM-002:
     * ADD should not add a component already in the released BOM.
     * A warning is used because the requester may have intended a quantity change.
     */
    private static void checkAddedPartIsNotAlreadyInBom(
            EcnHeader ecn,
            EcnChangeLine line,
            List<BomLine> releasedBom,
            List<CheckResult> results) {

        if (line.action() != ChangeAction.ADD) {
            return;
        }

        boolean alreadyExists = releasedBom.stream().anyMatch(bom ->
                bom.parentPartNumber().equals(ecn.affectedAssembly())
                        && bom.componentPartNumber().equals(line.newPartNumber())
                        && bom.status().equals("RELEASED")
        );

        if (alreadyExists) {
            results.add(warning(
                    "BOM-002",
                    "Line " + line.lineNumber() + ": Proposed ADD part '"
                            + line.newPartNumber() + "' already exists in the released BOM.",
                    "Confirm whether this should be CHANGE_QUANTITY instead of ADD."
            ));
        } else {
            results.add(pass(
                    "BOM-002",
                    "Line " + line.lineNumber() + ": Proposed ADD part is not already in BOM."
            ));
        }
    }

    /*
     * BOM-003:
     * ADD, REPLACE, and CHANGE_QUANTITY must have a new quantity > 0.
     */
    private static void checkQuantity(
            EcnChangeLine line,
            List<CheckResult> results) {

        boolean quantityRequired =
                line.action() == ChangeAction.ADD
                        || line.action() == ChangeAction.REPLACE
                        || line.action() == ChangeAction.CHANGE_QUANTITY;

        if (!quantityRequired) {
            return;
        }

        if (line.newQuantity().compareTo(BigDecimal.ZERO) <= 0) {
            results.add(blocker(
                    "BOM-003",
                    "Proposed BOM quantity must be greater than zero",
                    "Line " + line.lineNumber() + ": Proposed quantity is "
                            + line.newQuantity() + " " + line.uom() + ".",
                    "ECN change line: action=" + line.action()
                            + ", oldQuantity=" + line.oldQuantity()
                            + ", newQuantity=" + line.newQuantity()
                            + ", uom=" + line.uom(),
                    "ADD, REPLACE, and CHANGE_QUANTITY actions require a positive "
                            + "proposed quantity. A zero quantity is invalid.",
                    "Enter a quantity greater than zero, or use REMOVE if the component "
                            + "should be deleted."
            ));
        } else {
            results.add(pass(
                    "BOM-003",
                    "Proposed BOM quantity must be greater than zero",
                    "Line " + line.lineNumber() + ": Proposed quantity is valid: "
                            + line.newQuantity() + " " + line.uom() + ".",
                    "ECN change line: action=" + line.action()
                            + ", newQuantity=" + line.newQuantity()
                            + ", uom=" + line.uom(),
                    "The proposed quantity is greater than zero and is valid for this action."
            ));
        }
    }

    /*
     * REG-001:
     * New safety-critical parts require Quality approval.
     */
    private static void checkSafetyCriticalApproval(
            EcnHeader ecn,
            EcnChangeLine line,
            Map<String, Part> parts,
            List<CheckResult> results) {

        boolean hasNewPart =
                line.action() == ChangeAction.ADD
                        || line.action() == ChangeAction.REPLACE;

        if (!hasNewPart || line.newPartNumber().isBlank()) {
            return;
        }

        Part newPart = parts.get(line.newPartNumber());

        if (newPart != null && newPart.safetyCritical() && !ecn.qualityApproval()) {
            results.add(warning(
                    "REG-001",
                    "Line " + line.lineNumber() + ": Proposed part '"
                            + line.newPartNumber()
                            + "' is safety critical, but Quality approval is false.",
                    "Obtain and record Quality approval before ECN completion."
            ));
        } else if (newPart != null && newPart.safetyCritical()) {
            results.add(pass(
                    "REG-001",
                    "Line " + line.lineNumber()
                            + ": Safety-critical part has Quality approval."
            ));
        }
    }

    private static EcnDashboardView buildDashboardReport(EcnHeader ecn, List<CheckResult> results) {
        int passes = 0;
        int warnings = 0;
        int blockers = 0;

        for (CheckResult result : results) {
            switch (result.severity()) {
                case "PASS" -> passes++;
                case "WARNING" -> warnings++;
                case "BLOCKER" -> blockers++;
                default -> { }
            }
        }

        String decision = blockers > 0
                ? "BLOCKER"
                : warnings > 0 ? "REVIEW" : "APPROVE";

        List<DashboardResultView> dashboardResults = results.stream()
                .map(result -> new DashboardResultView(
                        result.severity(),
                        result.ruleId(),
                        result.ruleDescription(),
                        result.message(),
                        result.evidence(),
                        result.reason(),
                        result.requiredAction()))
                .toList();

        return new EcnDashboardView(
                ecn.ecnId(),
                ecn.title(),
                ecn.status(),
                ecn.affectedAssembly(),
                ecn.effectiveDate(),
                ecn.qualityApproval(),
                passes,
                warnings,
                blockers,
                decision,
                dashboardResults);
    }

    private static void writeDashboardOutputs(List<EcnDashboardView> reports) throws IOException {
        Path outputDir = Path.of("out");
        Files.createDirectories(outputDir);

        Path jsonPath = outputDir.resolve("ecn-dashboard.json");
        Path htmlPath = outputDir.resolve("ecn-dashboard.html");

        Files.writeString(jsonPath, buildDashboardJson(reports), StandardCharsets.UTF_8);
        Files.writeString(htmlPath, buildDashboardHtml(reports), StandardCharsets.UTF_8);

        System.out.println();
        System.out.println("Reviewer dashboard generated at: " + htmlPath.toAbsolutePath());
        System.out.println("Structured data exported to: " + jsonPath.toAbsolutePath());
    }

    private static String buildDashboardJson(List<EcnDashboardView> reports) {
        StringBuilder builder = new StringBuilder();
        builder.append("{\n  \"ecns\": [\n");

        for (int i = 0; i < reports.size(); i++) {
            EcnDashboardView report = reports.get(i);
            builder.append("    {\n");
            builder.append("      \"ecnId\": \"").append(escapeJson(report.ecnId())).append("\",\n");
            builder.append("      \"title\": \"").append(escapeJson(report.title())).append("\",\n");
            builder.append("      \"status\": \"").append(escapeJson(report.status())).append("\",\n");
            builder.append("      \"affectedAssembly\": \"").append(escapeJson(report.affectedAssembly())).append("\",\n");
            builder.append("      \"effectiveDate\": \"").append(escapeJson(report.effectiveDate())).append("\",\n");
            builder.append("      \"qualityApproval\": ").append(report.qualityApproval()).append(",\n");
            builder.append("      \"passCount\": ").append(report.passCount()).append(",\n");
            builder.append("      \"warningCount\": ").append(report.warningCount()).append(",\n");
            builder.append("      \"blockerCount\": ").append(report.blockerCount()).append(",\n");
            builder.append("      \"decision\": \"").append(escapeJson(report.decision())).append("\",\n");
            builder.append("      \"results\": [\n");

            List<DashboardResultView> resultViews = report.results();
            for (int j = 0; j < resultViews.size(); j++) {
                DashboardResultView result = resultViews.get(j);
                builder.append("        {\n");
                builder.append("          \"severity\": \"").append(escapeJson(result.severity())).append("\",\n");
                builder.append("          \"ruleId\": \"").append(escapeJson(result.ruleId())).append("\",\n");
                builder.append("          \"ruleDescription\": \"").append(escapeJson(result.ruleDescription())).append("\",\n");
                builder.append("          \"message\": \"").append(escapeJson(result.message())).append("\",\n");
                builder.append("          \"evidence\": \"").append(escapeJson(result.evidence())).append("\",\n");
                builder.append("          \"reason\": \"").append(escapeJson(result.reason())).append("\",\n");
                builder.append("          \"requiredAction\": \"").append(escapeJson(result.requiredAction())).append("\"\n");
                builder.append("        }");
                if (j < resultViews.size() - 1) {
                    builder.append(",");
                }
                builder.append("\n");
            }

            builder.append("      ]\n");
            builder.append("    }");
            if (i < reports.size() - 1) {
                builder.append(",");
            }
            builder.append("\n");
        }

        builder.append("  ]\n");
        builder.append("}\n");
        return builder.toString();
    }

    private static String buildDashboardHtml(List<EcnDashboardView> reports) {
        StringBuilder builder = new StringBuilder();
        builder.append("<!DOCTYPE html>\n");
        builder.append("<html lang=\"en\">\n");
        builder.append("<head>\n");
        builder.append("  <meta charset=\"utf-8\" />\n");
        builder.append("  <title>ECN Reviewer Dashboard</title>\n");
        builder.append("  <style>\n");
        builder.append("    body { font-family: Arial, sans-serif; margin: 24px; background: #f5f7fb; color: #1f2937; }\n");
        builder.append("    h1 { margin-bottom: 8px; }\n");
        builder.append("    .summary { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; margin-bottom: 24px; }\n");
        builder.append("    .card { background: white; border-radius: 10px; padding: 16px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); }\n");
        builder.append("    .card h3 { margin: 0 0 8px; font-size: 14px; text-transform: uppercase; color: #6b7280; }\n");
        builder.append("    .card .value { font-size: 28px; font-weight: bold; }\n");
        builder.append("    .panel { background: white; border-radius: 10px; padding: 16px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); margin-bottom: 16px; }\n");
        builder.append("    table { width: 100%; border-collapse: collapse; }\n");
        builder.append("    th, td { text-align: left; padding: 10px; border-bottom: 1px solid #e5e7eb; vertical-align: top; }\n");
        builder.append("    .severity { font-weight: bold; }\n");
        builder.append("    .PASS { color: #047857; }\n");
        builder.append("    .WARNING { color: #b45309; }\n");
        builder.append("    .BLOCKER { color: #b91c1c; }\n");
        builder.append("    .decision { font-weight: bold; padding: 6px 10px; border-radius: 999px; display: inline-block; }\n");
        builder.append("    .decision.APPROVE { background: #dcfce7; color: #166534; }\n");
        builder.append("    .decision.REVIEW { background: #fef3c7; color: #92400e; }\n");
        builder.append("    .decision.BLOCKER { background: #fee2e2; color: #991b1b; }\n");
        builder.append("  </style>\n");
        builder.append("</head>\n");
        builder.append("<body>\n");
        builder.append("  <h1>ECN Reviewer Dashboard</h1>\n");
        builder.append("  <p>This view summarizes automated ECN validation results for reviewer triage.</p>\n");
        builder.append("  <div class=\"summary\">\n");

        int totalPasses = 0;
        int totalWarnings = 0;
        int totalBlockers = 0;
        for (EcnDashboardView report : reports) {
            totalPasses += report.passCount();
            totalWarnings += report.warningCount();
            totalBlockers += report.blockerCount();
        }

        builder.append("    <div class=\"card\"><h3>Total ECNs</h3><div class=\"value\">" + reports.size() + "</div></div>\n");
        builder.append("    <div class=\"card\"><h3>Passes</h3><div class=\"value\">" + totalPasses + "</div></div>\n");
        builder.append("    <div class=\"card\"><h3>Warnings</h3><div class=\"value\">" + totalWarnings + "</div></div>\n");
        builder.append("    <div class=\"card\"><h3>Blockers</h3><div class=\"value\">" + totalBlockers + "</div></div>\n");
        builder.append("  </div>\n");

        for (EcnDashboardView report : reports) {
            builder.append("  <div class=\"panel\">\n");
            builder.append("    <h2>").append(escapeHtml(report.ecnId())).append(" - ").append(escapeHtml(report.title())).append("</h2>\n");
            builder.append("    <p><strong>Status:</strong> ").append(escapeHtml(report.status())).append(" &nbsp; <strong>Assembly:</strong> ").append(escapeHtml(report.affectedAssembly())).append(" &nbsp; <strong>Effective:</strong> ").append(escapeHtml(report.effectiveDate())).append("</p>\n");
            builder.append("    <p><strong>Review decision:</strong> <span class=\"decision ").append(report.decision()).append("\">").append(escapeHtml(report.decision())).append("</span></p>\n");
            builder.append("    <p><strong>Summary:</strong> Pass=" + report.passCount() + ", Warning=" + report.warningCount() + ", Blocker=" + report.blockerCount() + "</p>\n");
            builder.append("    <table>\n");
            builder.append("      <tr><th>Severity</th><th>Rule</th><th>Result</th><th>Action</th></tr>\n");
            for (DashboardResultView result : report.results()) {
                builder.append("      <tr>");
                builder.append("        <td class=\"severity ").append(escapeHtml(result.severity())).append("\">").append(escapeHtml(result.severity())).append("</td>");
                builder.append("        <td>").append(escapeHtml(result.ruleId())).append("</td>");
                builder.append("        <td>").append(escapeHtml(result.message())).append("</td>");
                builder.append("        <td>").append(escapeHtml(result.requiredAction().isBlank() ? "None" : result.requiredAction())).append("</td>");
                builder.append("      </tr>\n");
            }
            builder.append("    </table>\n");
            builder.append("  </div>\n");
        }

        builder.append("</body>\n");
        builder.append("</html>\n");
        return builder.toString();
    }

    private static String escapeJson(String value) {
        if (value == null) {
            return "";
        }

        return value.replace("\\", "\\\\")
                .replace("\"", "\\\"")
                .replace("\n", "\\n")
                .replace("\r", "");
    }

    private static String escapeHtml(String value) {
        if (value == null) {
            return "";
        }

        return value.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace("\"", "&quot;");
    }

    private static void printReport(EcnHeader ecn, List<CheckResult> results) {
        int passes = 0;
        int warnings = 0;
        int blockers = 0;

        System.out.println("--------------------------------------------------");
        System.out.println("ECN ID:             " + ecn.ecnId());
        System.out.println("Title:              " + ecn.title());
        System.out.println("Status:             " + ecn.status());
        System.out.println("Affected Assembly:  " + ecn.affectedAssembly());
        System.out.println("Effective Date:     " + ecn.effectiveDate());
        System.out.println("Quality Approval:   " + ecn.qualityApproval());
        System.out.println("--------------------------------------------------");

        for (CheckResult result : results) {
            System.out.println();
            System.out.printf("[%-7s] %s — %s%n",
                    result.severity(),
                    result.ruleId(),
                    result.ruleDescription());

            System.out.println("Result:   " + result.message());
            System.out.println("Evidence: " + result.evidence());
            System.out.println("Reason:   " + result.reason());

            if (!result.requiredAction().isBlank()) {
                System.out.println("Action:   " + result.requiredAction());
            }

            switch (result.severity()) {
                case "PASS" -> passes++;
                case "WARNING" -> warnings++;
                case "BLOCKER" -> blockers++;
                default -> { }
            }
        }

        System.out.println("--------------------------------------------------");
        System.out.println("Summary: Pass=" + passes
                + ", Warning=" + warnings
                + ", Blocker=" + blockers);

        if (blockers > 0) {
            System.out.println("FINAL DECISION: ECN cannot proceed.");
        } else if (warnings > 0) {
            System.out.println("FINAL DECISION: ECN needs checker/reviewer attention.");
        } else {
            System.out.println("FINAL DECISION: All automated checks passed.");
        }

        System.out.println("==================================================");
    }

    private static CheckResult pass(String ruleId, String ruleDescription) {
        return pass(ruleId, ruleDescription, "", "", "");
    }

    private static CheckResult pass(
        String ruleId,
        String ruleDescription,
        String message,
        String evidence,
        String reason) {

    return new CheckResult(
            "PASS",
            ruleId,
            ruleDescription,
            message,
            evidence,
            reason,
            ""
    );
}

private static CheckResult warning(String ruleId, String ruleDescription, String message) {
    return warning(ruleId, ruleDescription, message, "", "", "");
}

private static CheckResult warning(
        String ruleId,
        String ruleDescription,
        String message,
        String evidence,
        String reason,
        String action) {

    return new CheckResult(
            "WARNING",
            ruleId,
            ruleDescription,
            message,
            evidence,
            reason,
            action
    );
}

private static CheckResult blocker(String ruleId, String ruleDescription, String message) {
    return blocker(ruleId, ruleDescription, message, "", "", "");
}

private static CheckResult blocker(
        String ruleId,
        String ruleDescription,
        String message,
        String evidence,
        String reason,
        String action) {

    return new CheckResult(
            "BLOCKER",
            ruleId,
            ruleDescription,
            message,
            evidence,
            reason,
            action
    );
}

    // ---------------- CSV file readers ----------------

    private static Map<String, Part> loadParts(Path file) throws IOException {
        Map<String, Part> parts = new HashMap<>();

        for (String[] row : readCsvRows(file)) {
            Part part = new Part(
                    row[0], row[1], row[2],
                    Boolean.parseBoolean(row[3]), row[4]
            );
            parts.put(part.partNumber(), part);
        }

        return parts;
    }

    private static List<BomLine> loadBom(Path file) throws IOException {
        List<BomLine> bomLines = new ArrayList<>();

        for (String[] row : readCsvRows(file)) {
            bomLines.add(new BomLine(
                    row[0], row[1], new BigDecimal(row[2]),
                    row[3], row[4], row[5]
            ));
        }

        return bomLines;
    }

    private static List<EcnHeader> loadEcnHeaders(Path file) throws IOException {
        List<EcnHeader> headers = new ArrayList<>();

        for (String[] row : readCsvRows(file)) {
            headers.add(new EcnHeader(
                    row[0], row[1], row[2], row[3], row[4],
                    Boolean.parseBoolean(row[5])
            ));
        }

        return headers;
    }

    private static List<EcnChangeLine> loadEcnChanges(Path file) throws IOException {
        List<EcnChangeLine> changes = new ArrayList<>();

        for (String[] row : readCsvRows(file)) {
            changes.add(new EcnChangeLine(
                    row[0],
                    row[1],
                    ChangeAction.valueOf(row[2]),
                    row[3],
                    row[4],
                    row[5],
                    new BigDecimal(row[6]),
                    new BigDecimal(row[7]),
                    row[8]
            ));
        }

        return changes;
    }

    /*
     * Simple CSV reader for prototype data.
     * Do not use this for complex production CSV files containing quoted commas.
     */
    private static List<String[]> readCsvRows(Path file) throws IOException {
        List<String> lines = Files.readAllLines(file);
        List<String[]> rows = new ArrayList<>();

        for (int i = 1; i < lines.size(); i++) {
            String line = lines.get(i).trim();

            if (line.isEmpty() || line.startsWith("#")) {
                continue;
            }

            String[] columns = line.split(",", -1);

            for (int col = 0; col < columns.length; col++) {
                columns[col] = columns[col].trim();
            }

            rows.add(columns);
        }

        return rows;
    }

    // ---------------- Domain records ----------------

    enum ChangeAction {
        ADD, REMOVE, REPLACE, CHANGE_QUANTITY
    }

    record Part(
            String partNumber,
            String description,
            String lifecycleStatus,
            boolean safetyCritical,
            String approvedSupplier
    ) { }

    record BomLine(
            String parentPartNumber,
            String componentPartNumber,
            BigDecimal quantity,
            String uom,
            String bomRevision,
            String status
    ) { }

    record EcnHeader(
            String ecnId,
            String title,
            String status,
            String affectedAssembly,
            String effectiveDate,
            boolean qualityApproval
    ) { }

    record EcnChangeLine(
            String ecnId,
            String lineNumber,
            ChangeAction action,
            String parentPartNumber,
            String oldPartNumber,
            String newPartNumber,
            BigDecimal oldQuantity,
            BigDecimal newQuantity,
            String uom
    ) { }

record CheckResult(
        String severity,
        String ruleId,
        String ruleDescription,
        String message,
        String evidence,
        String reason,
        String requiredAction
) { }

record EcnDashboardView(
        String ecnId,
        String title,
        String status,
        String affectedAssembly,
        String effectiveDate,
        boolean qualityApproval,
        int passCount,
        int warningCount,
        int blockerCount,
        String decision,
        List<DashboardResultView> results
) { }

record DashboardResultView(
        String severity,
        String ruleId,
        String ruleDescription,
        String message,
        String evidence,
        String reason,
        String requiredAction
) { }
}