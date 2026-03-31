from __future__ import annotations

import getpass

from backend_database import SessionLocal, create_db_and_tables, create_user, get_user_by_username


def main() -> None:
    create_db_and_tables()

    username = input("Admin username: ").strip()
    name = input("Admin name: ").strip() or "Administrator"
    password = getpass.getpass("Admin password: ").strip()

    if not username or not password:
        print("Username and password are required.")
        return

    db = SessionLocal()
    try:
        existing = get_user_by_username(db, username)
        if existing:
            existing.role = "admin"
            db.commit()
            print(f"Updated existing user '{username}' to admin role.")
            return

        create_user(db, name=name, username=username, password=password, role="admin")
        print(f"Admin user '{username}' created successfully.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
