#!/usr/bin/env python3
"""Reset the existing admin password using hidden terminal prompts."""

from getpass import getpass

from app.models.database import ADMIN_EMAIL, CodioDatabase
from config.settings import DB_PATH


def main() -> int:
    password = getpass("New admin password: ")
    confirmation = getpass("Confirm admin password: ")

    if password != confirmation:
        print("Passwords do not match.")
        return 1

    database = CodioDatabase(DB_PATH)
    try:
        updated = database.set_user_password(ADMIN_EMAIL, password)
    except ValueError as error:
        print(error)
        return 1

    if not updated:
        print(f"Admin account {ADMIN_EMAIL} was not found in this database.")
        return 1

    print("Admin password updated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
