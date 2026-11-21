import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.models.database import ADMIN_EMAIL, CodioDatabase


class AdminPasswordTests(unittest.TestCase):
    def test_password_reset_updates_existing_account(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = CodioDatabase(str(Path(temp_dir) / "codio.db"))
            db.create_user(ADMIN_EMAIL, "Admin", "old-password")

            self.assertTrue(db.set_user_password(ADMIN_EMAIL, "a-new-admin-password"))
            self.assertFalse(db.authenticate_user(ADMIN_EMAIL, "old-password")["success"])
            self.assertTrue(
                db.authenticate_user(ADMIN_EMAIL, "a-new-admin-password")["success"]
            )

    def test_legacy_sha256_password_is_upgraded_after_successful_login(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "codio.db")
            db = CodioDatabase(db_path)
            password = "legacy-password"
            db.create_user(ADMIN_EMAIL, "Admin", password)

            conn = sqlite3.connect(db_path)
            try:
                conn.execute(
                    "UPDATE users SET password_hash = ? WHERE email = ?",
                    (hashlib.sha256(password.encode("utf-8")).hexdigest(), ADMIN_EMAIL),
                )
                conn.commit()
            finally:
                conn.close()

            self.assertTrue(db.authenticate_user(ADMIN_EMAIL, password)["success"])

            conn = db._get_connection()
            try:
                password_hash = conn.execute(
                    "SELECT password_hash FROM users WHERE email = ?", (ADMIN_EMAIL,)
                ).fetchone()["password_hash"]
            finally:
                conn.close()

            self.assertTrue(password_hash.startswith("bcrypt-sha256$"))

    def test_initial_admin_is_not_created_with_a_hardcoded_password(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("app.models.database.ADMIN_INITIAL_PASSWORD", ""):
                db = CodioDatabase(str(Path(temp_dir) / "codio.db"))

            conn = db._get_connection()
            try:
                admin = conn.execute(
                    "SELECT email FROM users WHERE email = ?", (ADMIN_EMAIL,)
                ).fetchone()
            finally:
                conn.close()

            self.assertIsNone(admin)

    def test_initial_admin_uses_configured_password(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            password = "configured-admin-password"
            with patch("app.models.database.ADMIN_INITIAL_PASSWORD", password):
                db = CodioDatabase(str(Path(temp_dir) / "codio.db"))

            self.assertTrue(db.authenticate_user(ADMIN_EMAIL, password)["success"])
            self.assertFalse(db.authenticate_user(ADMIN_EMAIL, "wrong-password")["success"])


if __name__ == "__main__":
    unittest.main()
