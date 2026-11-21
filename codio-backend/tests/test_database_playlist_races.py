import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.models.database import CodioDatabase


class _BarrierCursor:
    def __init__(self, cursor, barrier, query_fragment):
        self._cursor = cursor
        self._barrier = barrier
        self._query_fragment = query_fragment

    def execute(self, query, parameters=()):
        self._cursor.execute(query, parameters)
        normalized_query = " ".join(query.upper().split())
        if self._query_fragment in normalized_query:
            self._barrier.wait(timeout=5)
        return self

    def fetchone(self):
        return self._cursor.fetchone()


class _BarrierConnection:
    def __init__(self, connection, barrier, query_fragment):
        self._connection = connection
        self._barrier = barrier
        self._query_fragment = query_fragment

    def cursor(self):
        return _BarrierCursor(
            self._connection.cursor(),
            self._barrier,
            self._query_fragment,
        )

    def __getattr__(self, name):
        return getattr(self._connection, name)


class PlaylistDatabaseRaceTests(unittest.TestCase):
    def _run_concurrently(self, db, query_fragment, operation):
        original_get_connection = db._get_connection
        barrier = threading.Barrier(2)
        db._get_connection = lambda: _BarrierConnection(
            original_get_connection(), barrier, query_fragment
        )

        try:
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [executor.submit(operation) for _ in range(2)]
                return [future.result(timeout=10) for future in futures]
        finally:
            db._get_connection = original_get_connection

    def test_duplicate_playlist_saves_are_idempotent_and_release_database_lock(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "codio.db"
            db = CodioDatabase(db_path=str(db_path))
            db.create_user("admin@gmail.com", "Admin", "test-only-password")

            add_results = self._run_concurrently(
                db,
                "SELECT PLAYLIST_ID FROM PLAYLISTS",
                lambda: db.add_or_update_playlist(
                    "playlist-1", "https://example.test/playlist", "Course", 1
                ),
            )
            link_results = self._run_concurrently(
                db,
                "SELECT ID FROM USER_PLAYLISTS",
                lambda: db.link_user_to_playlist("admin@gmail.com", "playlist-1"),
            )

            self.assertEqual(add_results, [True, True])
            self.assertEqual(link_results, [True, True])

            conn = db._get_connection()
            try:
                playlist_count = conn.execute(
                    "SELECT COUNT(*) FROM playlists"
                ).fetchone()[0]
                link_count = conn.execute(
                    "SELECT COUNT(*) FROM user_playlists"
                ).fetchone()[0]
                conn.execute("BEGIN IMMEDIATE")
                conn.rollback()
            finally:
                conn.close()

            self.assertEqual(playlist_count, 1)
            self.assertEqual(link_count, 1)


if __name__ == "__main__":
    unittest.main()
