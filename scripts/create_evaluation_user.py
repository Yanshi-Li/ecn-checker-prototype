"""Create an identified ECN evaluation account in local PostgreSQL."""

from __future__ import annotations

import argparse
import sys
from getpass import getpass
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.evaluation_auth import ROLES
from scripts.evaluation_queries import create_user
from scripts.evaluation_store import connect_evaluation_db, initialise_schema


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--role", required=True, choices=sorted(ROLES))
    args = parser.parse_args()

    database_password = getpass("Enter the ecn_app database password: ")
    account_password = getpass(f"Choose a password for {args.email}: ")
    confirmation = getpass("Confirm that account password: ")
    if account_password != confirmation:
        raise SystemExit("Account passwords do not match.")

    with connect_evaluation_db({"ECN_DB_PASSWORD": database_password}) as connection:
        initialise_schema(connection)
        user_id = create_user(connection, args.email, args.name, account_password, args.role)
    print(f"Created {args.role.lower()} account {user_id} for {args.email}.")


if __name__ == "__main__":
    main()
