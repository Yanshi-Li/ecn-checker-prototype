"""Create the local evaluation tables."""

from getpass import getpass

try:
    from scripts.evaluation_store import connect_evaluation_db, initialise_schema
except ModuleNotFoundError:  # Direct execution adds only scripts/ to sys.path.
    from evaluation_store import connect_evaluation_db, initialise_schema


def main() -> None:
    password = getpass("Enter the ecn_app database password: ")
    connection = connect_evaluation_db({"ECN_DB_PASSWORD": password})
    try:
        initialise_schema(connection)
    finally:
        connection.close()
    print("Evaluation database schema is ready.")


if __name__ == "__main__":
    main()
