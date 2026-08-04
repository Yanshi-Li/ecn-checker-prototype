import java.io.IOException;
import java.math.BigDecimal;
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

            for (EcnHeader ecn : ecnHeaders) {
                List<CheckResult> results = runChecks(ecn, changes, releasedBom, parts);
                printReport(ecn, results);
            }

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
}