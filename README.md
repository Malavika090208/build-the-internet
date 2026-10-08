# 🗄️ acm-db — Database Service

**Role:** User Credential Storage Microservice  
**Hackathon:** [Build The Internet](https://mits-acm.github.io/BuildTheInternet/) · ACM MITS  
**Service Name:** `acm-db` (Service 2 of 4)  
**Contract Compliance:** Strict OpenAPI 3.0 (`acm-db.yaml`)

---

## 📌 Architecture Overview

```text
CLIENT (acm-app)
      │
      ▼ [1. DNS Lookup / 4. Sign-in]
DNS (acm-dns) ◄── [Services Register / Discover via DNS]
      ▲
      │ [2. Auth Lookup / Session Cookie]
AUTH SERVER (acm-server)
      │
      ▼ [3. User Persistence & Hash Retrieval]
DATABASE (acm-db) ◄── [YOU ARE HERE: Port 8001]
```

### Flow Breakdown for `acm-db`:
1. **Dynamic DNS Registration:** On startup, `acm-db` sends `POST http://<DNS_IP>:<DNS_PORT>/register` with body `{"domain": "acm-db"}`. `acm-dns` registers `<DB_IP>`.
2. **Dynamic Discovery:** When `acm-server` needs to access credentials, it queries `acm-dns` via `GET http://<DNS_IP>:<DNS_PORT>/lookup?domain=acm-db`, receiving `<DB_IP>`.
3. **Registration:** `acm-server` hashes the user password and issues `POST http://<DB_IP>:8001/db/users` to store the record.
4. **Login:** `acm-server` retrieves the hashed password via `GET http://<DB_IP>:8001/db/users/{username}` to verify credentials.

---

## 🚀 Quick Start

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure Environment
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```
Edit `.env` as needed:
```ini
HOST=0.0.0.0
PORT=8001
DB_PATH=users.db
DNS_URL=http://<DNS_IP>:8000
```

### 3. Run the Database Service
```bash
python main.py
```
Or with uvicorn directly:
```bash
uvicorn main:app --host 0.0.0.0 --port 8001
```

### 4. Run Automated Tests
```bash
python test_db.py
```

---

## 📡 API Contract (Strict OpenAPI 3.0)

### 1. Create / Save User Record
*Called by `acm-server` during registration.*

- **Endpoint:** `POST /db/users`
- **Headers:** `Content-Type: application/json`
- **Request Body:**
  ```json
  {
    "username": "alice",
    "password_hash": "5e884898da28047151d0e56f8dc6292773603d0d6aabbdd62a11ef721d1542d8"
  }
  ```
- **Responses:**
  - `201 Created`:
    ```json
    {
      "status": "ok",
      "user_id": 1
    }
    ```
  - `400 Bad Request` (User already exists):
    ```json
    {
      "error": "Username already exists"
    }
    ```

### 2. Fetch User Record by Username
*Called by `acm-server` during login.*

- **Endpoint:** `GET /db/users/{username}`
- **Responses:**
  - `200 OK`:
    ```json
    {
      "user_id": 1,
      "username": "alice",
      "password_hash": "5e884898da28047151d0e56f8dc6292773603d0d6aabbdd62a11ef721d1542d8"
    }
    ```
  - `404 Not Found`:
    ```json
    {
      "error": "User not found"
    }
    ```

---

## 🤝 Auth Server Team Integration Guide

Provide these network parameters to the `acm-server` team:

| Parameter | Value / Placeholder |
| :--- | :--- |
| **DATABASE IP** | `<DB_IP>` *(Your laptop's local LAN IP)* |
| **DATABASE PORT** | `8001` *(Default, configurable via `PORT`)* |
| **DATABASE NAME** | `users.db` |
| **DATABASE PROTOCOL** | HTTP REST (JSON) |
| **DISCOVERY DOMAIN** | `acm-db` |
| **CONNECTION FORMAT** | `http://<DB_IP>:8001` or via DNS `http://<resolved_ip>:8001` |

> ⚠️ **Security Notice:** The database strictly stores **password hashes** produced by `acm-server`. The Auth Server must NEVER transmit plaintext passwords to `acm-db`.

### How Auth Server Verifies Connection:
```bash
# Health check
curl http://<DB_IP>:8001/health

# Test user registration
curl -X POST http://<DB_IP>:8001/db/users \
  -H "Content-Type: application/json" \
  -d '{"username": "test_user", "password_hash": "testhash123"}'

# Test user retrieval
curl http://<DB_IP>:8001/db/users/test_user
```

---

## 🛡️ Security Features
- **Parameterized Queries:** 100% of SQL statements use parameterized binds (`?`), providing complete immunity against SQL injection attacks.
- **No Plaintext Passwords:** Strict enforcement of password hashes only.
- **Resource Management:** Safe context management ensures clean SQLite connection release with WAL (Write-Ahead Logging) mode.
- **Safe Error Handling:** Internal stack traces and database details are never leaked to HTTP clients.
- **Network Isolation:** Listens on configurable host/port with CORS enabled for local network interoperability.

---

## 📊 Live Monitoring Dashboard (Bonus Feature)
Open `http://<DB_IP>:8001/` in any browser to view:
- **Live Event Stream:** Real-time visibility into queries, lookups, and registrations as they arrive from `acm-server`.
- **Dynamic DNS Control:** One-click registration with `acm-dns`.
- **User Record Inspector:** Safe preview of registered users with masked hashes.
- **Interactive Swagger UI:** Accessible at `http://<DB_IP>:8001/docs`.
