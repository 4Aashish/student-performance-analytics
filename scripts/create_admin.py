"""Creates the FIRST administrator account.  Run:  python -m scripts.create_admin
The password is typed hidden and is never saved anywhere except as a bcrypt hash in the database."""
import getpass

from app.db.connection import transaction
from app.security import users
from app.validation import ValidationError


def main() -> None:
    username = input("Admin username (letters/digits, at least 3 characters): ")
    password = getpass.getpass("Password (hidden, at least 8 characters with a letter and a digit): ")
    again = getpass.getpass("Type the password again: ")
    if password != again:
        print("The two passwords are different. Nothing was created.")
        return
    try:
        with transaction() as conn:
            with conn.cursor() as cur:
                users.create_first_admin(cur, username, password)
    except ValidationError as e:
        print(f"Not created: {e}")
        return
    print(f"Admin '{username.strip().lower()}' created. You can now log in on the Home page.")


if __name__ == "__main__":
    main()
