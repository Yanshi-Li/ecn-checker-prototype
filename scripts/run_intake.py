import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from ecn_intake import build_input_files, load_ecns_from_imap, load_ecn_from_path, normalize_ecn_text

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "out" / "intake"

DEFAULT_TEXT = """ECN Intake from email
ECN ID: ECN-2026-001
Title: Sample ECN from email intake
Affected assembly: A-100
Quality approval: no
Description: Replace the obsolete capacitor with an approved alternative and adjust the affected assembly quantity for the next release.
Change 1: Replace component C-200 with C-250 quantity 1
Change 2: Remove component C-999 quantity 1
Change 3: Add component C-100 quantity 1
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Normalize an ECN intake source and run the Java checker")
    parser.add_argument("input_path", nargs="?", help="Optional path to a .txt, .pdf, or .eml ECN intake file")
    parser.add_argument("--imap-host", default=os.getenv("ECN_IMAP_HOST"), help="IMAP server host")
    parser.add_argument("--imap-user", default=os.getenv("ECN_IMAP_USER"), help="IMAP username")
    parser.add_argument("--imap-password", default=os.getenv("ECN_IMAP_PASSWORD"), help="IMAP password")
    parser.add_argument("--imap-folder", default=os.getenv("ECN_IMAP_FOLDER", "INBOX"), help="IMAP folder")
    parser.add_argument("--imap-limit", type=int, default=int(os.getenv("ECN_IMAP_LIMIT", "5")), help="Number of recent messages to process")
    args = parser.parse_args(argv)

    if args.input_path:
        input_path = Path(args.input_path)
        if not input_path.exists():
            raise FileNotFoundError(f"Input file not found: {input_path}")
        normalized = load_ecn_from_path(input_path)
    elif args.imap_host and args.imap_user and args.imap_password:
        ecns = load_ecns_from_imap(args.imap_host, args.imap_user, args.imap_password, args.imap_folder, args.imap_limit)
        if not ecns:
            raise RuntimeError("No ECNs were found in the mailbox")
        normalized = ecns[0]
    else:
        normalized = normalize_ecn_text(DEFAULT_TEXT)

    build_input_files(normalized, OUT_DIR, ROOT / "data")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    subprocess.run(["javac", "-d", str(OUT_DIR), "src/EcnCheckerSimulation.java"], cwd=ROOT, check=True)
    subprocess.run(["java", "-cp", str(OUT_DIR), "EcnCheckerSimulation", str(OUT_DIR)], cwd=ROOT, check=True)

    print(json.dumps(normalized, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
