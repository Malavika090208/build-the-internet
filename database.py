"""
acm-db Database Management Module
Build The Internet Hackathon - Database Microservice

Handles low-level persistence for user credentials required by acm-server.
Uses SQLite with strict parameterized queries, proper constraints, and safe error handling.
"""

import os
import sqlite3
from contextlib import contextmanager
from typing import Optional, Dict, Any, List, Generator
from datetime import datetime

# Custom Exceptions for safe, structured error handling
class DatabaseError(Exception):
    """Base class for database exceptions."""
    pass

class UserAlreadyExistsError(DatabaseError):
    """Raised when attempting to insert a duplicate username."""
    pass

class UserNotFoundError(DatabaseError):
    """Raised when the requested user is not found."""
    pass


class Database:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or os.getenv("DB_PATH", "users.db")
        self.init_db()

    @contextmanager
    def get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Provides a thread-safe connection to SQLite with WAL mode, auto-closing on exit."""
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys = ON;")
            conn.execute("PRAGMA journal_mode = WAL;")
            yield conn
        finally:
            conn.close()

    def init_db(self) -> None:
        """Initializes database schema with primary keys, unique constraints, and indexes."""
        # Ensure parent directory exists if db_path has directories
        parent_dir = os.path.dirname(self.db_path)
        if parent_dir and not os.path.exists(parent_dir):
            os.makedirs(parent_dir, exist_ok=True)

        with self.get_connection() as conn:
            cursor = conn.cursor()
            # Users table: strictly stores password_hash (NEVER plaintext passwords)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL COLLATE NOCASE,
                    password_hash TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            # Explicit index on username for sub-millisecond lookups
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
            """)
            conn.commit()

    def create_user(self, username: str, password_hash: str) -> Dict[str, Any]:
        """
        Inserts a new user record using parameterized SQL.
        Raises UserAlreadyExistsError if username already exists.
        Never allows SQL injection.
        """
        clean_username = username.strip()
        if not clean_username:
            raise ValueError("Username cannot be empty")
        if not password_hash or not password_hash.strip():
            raise ValueError("Password hash cannot be empty")

        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                # Fully parameterized query: '?' prevents any SQL injection vulnerability
                cursor.execute(
                    "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                    (clean_username, password_hash.strip())
                )
                conn.commit()
                user_id = cursor.lastrowid
                return {
                    "status": "ok",
                    "user_id": user_id
                }
            except sqlite3.IntegrityError as e:
                if "UNIQUE constraint failed" in str(e) or "users.username" in str(e):
                    raise UserAlreadyExistsError(f"Username '{clean_username}' already exists")
                raise DatabaseError(f"Database constraint error: {e}")
            except Exception as e:
                raise DatabaseError(f"Database insertion failed: {e}")

    def get_user_by_username(self, username: str) -> Dict[str, Any]:
        """
        Fetches user record by username using parameterized SQL.
        Raises UserNotFoundError if user does not exist.
        """
        clean_username = username.strip()
        if not clean_username:
            raise ValueError("Username cannot be empty")

        with self.get_connection() as conn:
            cursor = conn.cursor()
            # Parameterized query: '?' prevents SQL injection
            cursor.execute(
                "SELECT id, username, password_hash FROM users WHERE username = ?",
                (clean_username,)
            )
            row = cursor.fetchone()
            if not row:
                raise UserNotFoundError(f"User '{clean_username}' not found")
            
            return {
                "user_id": row["id"],
                "username": row["username"],
                "password_hash": row["password_hash"]
            }

    def check_user_exists(self, username: str) -> bool:
        """Checks if a username already exists without returning password hash."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM users WHERE username = ? LIMIT 1", (username.strip(),))
            return cursor.fetchone() is not None

    def list_users(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Lists users with masked password hashes for dashboard display."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, username, password_hash, created_at FROM users ORDER BY id DESC LIMIT ?",
                (limit,)
            )
            rows = cursor.fetchall()
            return [
                {
                    "user_id": row["id"],
                    "username": row["username"],
                    "password_hash_preview": (row["password_hash"][:8] + "..." + row["password_hash"][-8:])
                        if len(row["password_hash"]) > 16 else "***",
                    "created_at": row["created_at"]
                }
                for row in rows
            ]

    def count_users(self) -> int:
        """Returns total user count."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM users")
            return cursor.fetchone()[0]

    def health_check(self) -> bool:
        """Verifies database connectivity."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT 1")
                return cursor.fetchone()[0] == 1
        except Exception:
            return False
