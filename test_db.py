"""
Comprehensive Test Suite for acm-db
Build The Internet Hackathon - Database Microservice

Runs standalone with:
    python test_db.py
or with pytest:
    pytest test_db.py
"""

import os
import tempfile
import unittest
import hashlib
from fastapi.testclient import TestClient

from database import Database, UserAlreadyExistsError, UserNotFoundError
from main import app, db


class TestDatabaseService(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Use an isolated temporary database file for tests
        cls.temp_db_fd, cls.temp_db_path = tempfile.mkstemp(suffix=".db")
        cls.test_db = Database(db_path=cls.temp_db_path)
        # Point main app db to the test db
        import main
        main.db = cls.test_db
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        os.close(cls.temp_db_fd)
        if os.path.exists(cls.temp_db_path):
            try:
                os.remove(cls.temp_db_path)
            except Exception:
                pass

    def setUp(self):
        # Clear users table before each test
        with self.test_db.get_connection() as conn:
            conn.execute("DELETE FROM users;")
            conn.commit()

    # =========================================================================
    # Unit Tests: Database Schema, SQL Constraints, Security
    # =========================================================================

    def test_01_db_connectivity_and_health(self):
        """Test database initialization and health check."""
        self.assertTrue(self.test_db.health_check(), "Database health check should return True")

    def test_02_create_user(self):
        """Test creating a valid user record."""
        # Simulated SHA-256 hash provided by acm-server
        sample_hash = hashlib.sha256(b"secret123").hexdigest()
        result = self.test_db.create_user("alice", sample_hash)

        self.assertEqual(result["status"], "ok")
        self.assertIsInstance(result["user_id"], int)
        self.assertGreater(result["user_id"], 0)

    def test_03_get_user_by_username(self):
        """Test retrieving user record and verifying password hash matches."""
        sample_hash = hashlib.sha256(b"mypassword").hexdigest()
        self.test_db.create_user("bob", sample_hash)

        user = self.test_db.get_user_by_username("bob")
        self.assertEqual(user["username"], "bob")
        self.assertEqual(user["password_hash"], sample_hash)
        self.assertIsInstance(user["user_id"], int)

    def test_04_duplicate_username_rejected(self):
        """Test that duplicate usernames violate UNIQUE constraint and raise error."""
        sample_hash = hashlib.sha256(b"pass1").hexdigest()
        self.test_db.create_user("charlie", sample_hash)

        with self.assertRaises(UserAlreadyExistsError):
            self.test_db.create_user("charlie", sample_hash)

    def test_05_nonexistent_user_raises_not_found(self):
        """Test that fetching a non-existent user raises UserNotFoundError."""
        with self.assertRaises(UserNotFoundError):
            self.test_db.get_user_by_username("nonexistent_user_123")

    def test_06_sql_injection_defense(self):
        """Test that parameterized SQL safely handles malicious SQL injection attempts."""
        malicious_username = "admin' OR '1'='1"
        malicious_hash = "fakehash'; DROP TABLE users; --"

        # Insertion should safely treat the input as literal string
        res = self.test_db.create_user(malicious_username, malicious_hash)
        self.assertEqual(res["status"], "ok")

        # Table should still exist and contain the literal username
        retrieved = self.test_db.get_user_by_username(malicious_username)
        self.assertEqual(retrieved["username"], malicious_username)
        self.assertEqual(retrieved["password_hash"], malicious_hash)
        self.assertTrue(self.test_db.health_check())

    def test_07_never_store_plaintext_passwords(self):
        """Test that only hash is stored in database records."""
        plaintext = "supersecretpassword123"
        sha256_hash = hashlib.sha256(plaintext.encode()).hexdigest()

        self.test_db.create_user("david", sha256_hash)
        user = self.test_db.get_user_by_username("david")

        # Must never equal the plaintext
        self.assertNotEqual(user["password_hash"], plaintext)
        self.assertEqual(user["password_hash"], sha256_hash)

    # =========================================================================
    # HTTP Contract Tests: Official OpenAPI Specification Endpoints
    # =========================================================================

    def test_08_api_post_user_success(self):
        """POST /db/users returns 201 Created and user_id per contract."""
        payload = {
            "username": "emma",
            "password_hash": hashlib.sha256(b"emmapass").hexdigest()
        }
        res = self.client.post("/db/users", json=payload)
        self.assertEqual(res.status_code, 201)
        data = res.json()
        self.assertEqual(data["status"], "ok")
        self.assertIn("user_id", data)

    def test_09_api_post_user_duplicate_400(self):
        """POST /db/users returns 400 Bad Request if username already exists."""
        payload = {
            "username": "frank",
            "password_hash": hashlib.sha256(b"frankpass").hexdigest()
        }
        # First creation
        res1 = self.client.post("/db/users", json=payload)
        self.assertEqual(res1.status_code, 201)

        # Duplicate attempt
        res2 = self.client.post("/db/users", json=payload)
        self.assertEqual(res2.status_code, 400)
        data = res2.json()
        self.assertEqual(data["error"], "Username already exists")

    def test_10_api_get_user_success_200(self):
        """GET /db/users/{username} returns 200 and user record per contract."""
        test_hash = hashlib.sha256(b"gracepass").hexdigest()
        self.client.post("/db/users", json={"username": "grace", "password_hash": test_hash})

        res = self.client.get("/db/users/grace")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["username"], "grace")
        self.assertEqual(data["password_hash"], test_hash)
        self.assertIn("user_id", data)

    def test_11_api_get_user_not_found_404(self):
        """GET /db/users/{username} returns 404 Not Found if user doesn't exist."""
        res = self.client.get("/db/users/ghost_user")
        self.assertEqual(res.status_code, 404)
        data = res.json()
        self.assertEqual(data["error"], "User not found")

    def test_12_api_invalid_payloads(self):
        """POST /db/users handles missing or blank fields gracefully."""
        # Missing password_hash
        res1 = self.client.post("/db/users", json={"username": "harry"})
        self.assertEqual(res1.status_code, 422)

        # Empty username string
        res2 = self.client.post("/db/users", json={"username": "   ", "password_hash": "hash123"})
        self.assertEqual(res2.status_code, 400)
        self.assertIn("error", res2.json())

    def test_13_api_health_endpoint(self):
        """GET /health returns healthy status."""
        res = self.client.get("/health")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["service"], "acm-db")
        self.assertTrue(data["db_connected"])

    def test_14_auth_server_integration_simulation(self):
        """
        Simulate the exact Auth Server workflow:
        1. Auth Server registers a new user with hash
        2. Auth Server checks user during login and compares hash
        """
        server_hash = hashlib.sha256(b"integration_secret").hexdigest()

        # Step 1: acm-server registers user
        create_res = self.client.post("/db/users", json={
            "username": "alex",
            "password_hash": server_hash
        })
        self.assertEqual(create_res.status_code, 201)
        created_user_id = create_res.json()["user_id"]

        # Step 2: acm-server logs in user: fetches user record to verify hash
        fetch_res = self.client.get("/db/users/alex")
        self.assertEqual(fetch_res.status_code, 200)
        user_record = fetch_res.json()

        self.assertEqual(user_record["user_id"], created_user_id)
        self.assertEqual(user_record["username"], "alex")
        self.assertEqual(user_record["password_hash"], server_hash)


if __name__ == "__main__":
    unittest.main(verbosity=2)
