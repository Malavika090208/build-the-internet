"""
acm-db: Low-Level User Database Storage Service
Build The Internet Hackathon - Service 2 (acm-db)

Implements the official OpenAPI 3.0 specification for acm-db:
- POST /db/users (Save a new user record with username & password_hash)
- GET  /db/users/{username} (Fetch user record and password_hash by username)

Includes:
- Dynamic DNS registration with acm-dns
- Live event-log monitoring dashboard (Bonus Criterion)
- Parameterized SQL / Prepared statements
- Zero-leakage error handling
"""

import os
import time
import logging
from collections import deque
from datetime import datetime
from contextlib import asynccontextmanager
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from dotenv import load_dotenv

from database import Database, UserAlreadyExistsError, UserNotFoundError, DatabaseError
from dns_client import DNSClient

# Load environment configuration
load_dotenv()

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s"
)
logger = logging.getLogger("acm-db")

# Initialize database
DB_PATH = os.getenv("DB_PATH", "users.db")
db = Database(db_path=DB_PATH)

# Initialize DNS Client
DNS_URL = os.getenv("DNS_URL")
dns_client = DNSClient(dns_url=DNS_URL)

# Ring buffer for real-time live event monitoring (Bonus Dashboard)
MAX_LOG_ENTRIES = 100
event_logs: deque = deque(maxlen=MAX_LOG_ENTRIES)

def log_event(event_type: str, method: str, path: str, status_code: int, detail: str, client_ip: str):
    """Appends an event to the circular buffer for the live monitoring dashboard."""
    entry = {
        "id": int(time.time() * 1000),
        "timestamp": datetime.now().strftime("%H:%M:%S.%f")[:-3],
        "type": event_type,
        "method": method,
        "path": path,
        "status_code": status_code,
        "detail": detail,
        "client_ip": client_ip,
    }
    event_logs.appendleft(entry)
    logger.info("[%s] %s %s -> %d (%s) from %s", event_type, method, path, status_code, detail, client_ip)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Modern lifespan handler managing startup and shutdown tasks."""
    logger.info("=========================================")
    logger.info("   acm-db Service Starting Up...")
    logger.info("   Database path: %s", DB_PATH)
    logger.info("   OpenAPI spec: /acm-db.yaml or /docs")
    logger.info("=========================================")
    
    # Auto-register with DNS if DNS_URL / DNS_HOST is provided
    if os.getenv("DNS_URL") or os.getenv("DNS_HOST"):
        reg_result = dns_client.register_service(domain="acm-db")
        log_event(
            event_type="DNS_REGISTRATION",
            method="POST",
            path="/register",
            status_code=200 if reg_result.get("success") else 500,
            detail=reg_result.get("message", "DNS Registration attempted"),
            client_ip="localhost"
        )
    yield
    logger.info("acm-db Service Shutting Down...")


# FastAPI App
app = FastAPI(
    title="acm-db",
    description="Low-level user database storage service for Build The Internet hackathon.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan
)

# Enable CORS for cross-origin integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==========================================================
# Pydantic Request / Response Models (Strict OpenAPI Contract)
# ==========================================================

class CreateUserRequest(BaseModel):
    username: str = Field(..., description="Unique username for the user", examples=["alice"])
    password_hash: str = Field(..., description="Hashed password string from acm-server", examples=["5e884898da28047151d0e56f8dc6292773603d0d6aabbdd62a11ef721d1542d8"])

class CreateUserResponse(BaseModel):
    status: str = Field("ok", examples=["ok"])
    user_id: int = Field(..., examples=[101])

class UserRecordResponse(BaseModel):
    user_id: int = Field(..., examples=[101])
    username: str = Field(..., examples=["alice"])
    password_hash: str = Field(..., examples=["5e884898da28047151d0e56f8dc6292773603d0d6aabbdd62a11ef721d1542d8"])

class ErrorResponse(BaseModel):
    error: str = Field(..., examples=["Username already exists"])


# ==========================================================
# Official OpenAPI Endpoints for acm-db
# ==========================================================

@app.post(
    "/db/users",
    response_model=CreateUserResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        201: {"model": CreateUserResponse, "description": "Record created successfully"},
        400: {"model": ErrorResponse, "description": "User already exists or invalid payload"}
    },
    summary="Save a new user record",
    description="Called by acm-server during registration to store username and hashed password."
)
async def create_user_endpoint(payload: CreateUserRequest, request: Request):
    client_ip = request.client.host if request.client else "unknown"
    username = payload.username.strip()
    password_hash = payload.password_hash.strip()

    if not username:
        log_event("USER_CREATE_FAIL", "POST", "/db/users", 400, "Username cannot be empty", client_ip)
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": "Username cannot be empty"}
        )

    if not password_hash:
        log_event("USER_CREATE_FAIL", "POST", "/db/users", 400, "Password hash cannot be empty", client_ip)
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": "Password hash cannot be empty"}
        )

    try:
        result = db.create_user(username=username, password_hash=password_hash)
        log_event(
            "USER_CREATED",
            "POST",
            "/db/users",
            201,
            f"Created user '{username}' with user_id {result['user_id']}",
            client_ip
        )
        return JSONResponse(
            status_code=status.HTTP_201_CREATED,
            content=result
        )
    except UserAlreadyExistsError:
        log_event("USER_CREATE_CONFLICT", "POST", "/db/users", 400, f"Username '{username}' already exists", client_ip)
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": "Username already exists"}
        )
    except Exception as e:
        logger.error("Error creating user: %s", e)
        log_event("USER_CREATE_ERROR", "POST", "/db/users", 500, str(e), client_ip)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"error": "Internal database error"}
        )


@app.get(
    "/db/users/{username}",
    response_model=UserRecordResponse,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"model": UserRecordResponse, "description": "User record found"},
        404: {"model": ErrorResponse, "description": "User not found"}
    },
    summary="Fetch user record by username",
    description="Called by acm-server during /login to retrieve the stored password hash."
)
async def get_user_endpoint(username: str, request: Request):
    client_ip = request.client.host if request.client else "unknown"
    clean_username = username.strip()

    try:
        user_record = db.get_user_by_username(clean_username)
        log_event(
            "USER_LOOKUP_SUCCESS",
            "GET",
            f"/db/users/{clean_username}",
            200,
            f"Retrieved user_id {user_record['user_id']} for '{clean_username}'",
            client_ip
        )
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=user_record
        )
    except UserNotFoundError:
        log_event(
            "USER_LOOKUP_NOT_FOUND",
            "GET",
            f"/db/users/{clean_username}",
            404,
            f"User '{clean_username}' not found",
            client_ip
        )
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"error": "User not found"}
        )
    except Exception as e:
        logger.error("Error looking up user '%s': %s", clean_username, e)
        log_event("USER_LOOKUP_ERROR", "GET", f"/db/users/{clean_username}", 500, str(e), client_ip)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"error": "Internal database error"}
        )


# ==========================================================
# Health, DNS, and Monitoring Endpoints (Bonus Dashboard)
# ==========================================================

@app.get("/health", summary="Health check endpoint")
async def health_check():
    """Health check endpoint to verify database connectivity and status."""
    is_healthy = db.health_check()
    return {
        "status": "ok" if is_healthy else "degraded",
        "service": "acm-db",
        "version": "1.0.0",
        "db_connected": is_healthy,
        "total_users": db.count_users(),
        "timestamp": datetime.now().isoformat()
    }


class RegisterDNSRequest(BaseModel):
    dns_url: Optional[str] = Field(None, examples=["http://192.168.1.100:8000"])
    domain: Optional[str] = Field("acm-db", examples=["acm-db"])

@app.post("/register-dns", summary="Trigger dynamic DNS registration with acm-dns")
async def register_dns_endpoint(payload: Optional[RegisterDNSRequest] = None):
    """Triggers registration of acm-db with acm-dns over the local network."""
    dns_target = payload.dns_url if payload and payload.dns_url else None
    client = DNSClient(dns_url=dns_target) if dns_target else dns_client
    domain_to_register = payload.domain if payload and payload.domain else "acm-db"
    
    result = client.register_service(domain=domain_to_register)
    log_event(
        "DNS_REGISTRATION_MANUAL",
        "POST",
        "/register-dns",
        200 if result.get("success") else 500,
        result.get("message", "DNS registration result"),
        "local"
    )
    return result


@app.get("/api/logs", summary="Fetch real-time event logs for monitoring")
async def get_logs():
    """Returns the last 100 system events for the live event-log dashboard."""
    return {
        "events": list(event_logs),
        "total_users": db.count_users(),
        "users": db.list_users(limit=20)
    }


# ==========================================================
# Real-Time Monitoring Web Dashboard (Bonus Criterion 5)
# ==========================================================

@app.get("/", response_class=HTMLResponse, summary="Live Monitoring Dashboard")
@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_view():
    """Renders the dark-mode live event monitoring dashboard for judges & teammates."""
    html_content = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>acm-db | Live Database Monitor</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&family=Outfit:wght@400;500;600;700;800&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg: #0c0f17;
      --card-bg: #141926;
      --card-border: #232b3e;
      --text-main: #f0f3f8;
      --text-muted: #8c97ac;
      --primary: #3b82f6;
      --primary-glow: rgba(59, 130, 246, 0.25);
      --accent: #ed003b;
      --success: #10b981;
      --success-glow: rgba(16, 185, 129, 0.2);
      --warning: #f59e0b;
      --error: #ef4444;
      --font-body: 'Outfit', sans-serif;
      --font-mono: 'JetBrains Mono', monospace;
    }

    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background-color: var(--bg);
      color: var(--text-main);
      font-family: var(--font-body);
      min-height: 100vh;
      padding: 1.5rem;
      background-image: 
        radial-gradient(circle at 10% 20%, rgba(59, 130, 246, 0.08) 0%, transparent 40%),
        radial-gradient(circle at 90% 80%, rgba(237, 0, 59, 0.06) 0%, transparent 40%);
    }

    .container {
      max-width: 1200px;
      margin: 0 auto;
    }

    /* Masthead */
    header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 1rem 1.5rem;
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 14px;
      margin-bottom: 1.5rem;
      box-shadow: 0 4px 20px rgba(0, 0, 0, 0.4);
    }
    .brand {
      display: flex;
      align-items: center;
      gap: 1rem;
    }
    .badge {
      font-family: var(--font-mono);
      font-size: 0.75rem;
      font-weight: 700;
      padding: 0.35rem 0.75rem;
      border-radius: 999px;
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }
    .badge-service {
      background: rgba(237, 0, 59, 0.15);
      color: #ff4d6d;
      border: 1px solid rgba(237, 0, 59, 0.4);
    }
    .badge-status {
      display: inline-flex;
      align-items: center;
      gap: 0.4rem;
      background: var(--success-glow);
      color: #34d399;
      border: 1px solid rgba(16, 185, 129, 0.3);
    }
    .status-dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: #10b981;
      box-shadow: 0 0 10px #10b981;
      animation: pulse 2s infinite;
    }
    @keyframes pulse {
      0%, 100% { opacity: 1; transform: scale(1); }
      50% { opacity: 0.5; transform: scale(0.9); }
    }

    /* Stats Grid */
    .stats-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      gap: 1.25rem;
      margin-bottom: 1.5rem;
    }
    .card {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 12px;
      padding: 1.25rem;
      box-shadow: 0 4px 15px rgba(0, 0, 0, 0.2);
    }
    .card-title {
      font-size: 0.8rem;
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: 0.05em;
      margin-bottom: 0.5rem;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
    .card-value {
      font-size: 1.8rem;
      font-weight: 700;
      color: var(--text-main);
      font-family: var(--font-mono);
    }
    .card-sub {
      font-size: 0.8rem;
      color: var(--text-muted);
      margin-top: 0.4rem;
    }

    /* Architecture Flow Banner */
    .arch-flow {
      background: #101524;
      border: 1px solid #1f273b;
      border-radius: 12px;
      padding: 1rem 1.25rem;
      margin-bottom: 1.5rem;
      display: flex;
      align-items: center;
      justify-content: space-around;
      flex-wrap: wrap;
      gap: 0.75rem;
      font-family: var(--font-mono);
      font-size: 0.85rem;
    }
    .arch-node {
      display: flex;
      flex-direction: column;
      align-items: center;
      padding: 0.5rem 0.9rem;
      background: rgba(255, 255, 255, 0.03);
      border-radius: 8px;
      border: 1px solid transparent;
    }
    .arch-node.active-db {
      border-color: var(--accent);
      background: rgba(237, 0, 59, 0.12);
      box-shadow: 0 0 15px rgba(237, 0, 59, 0.25);
    }
    .arch-node strong { color: #fff; }
    .arch-node small { color: var(--text-muted); font-size: 0.7rem; }
    .arch-arrow { color: var(--text-muted); font-size: 1.1rem; }

    /* Main Grid */
    .main-grid {
      display: grid;
      grid-template-columns: 2fr 1fr;
      gap: 1.5rem;
    }
    @media (max-width: 900px) {
      .main-grid { grid-template-columns: 1fr; }
    }

    /* Event Logs */
    .section-head {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 1rem;
    }
    .section-head h2 {
      font-size: 1.15rem;
      font-weight: 600;
      display: flex;
      align-items: center;
      gap: 0.5rem;
    }
    .live-dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: #ef4444;
      animation: pulse 1.5s infinite;
    }

    .log-stream {
      background: #090c13;
      border: 1px solid var(--card-border);
      border-radius: 10px;
      padding: 0.75rem;
      max-height: 480px;
      overflow-y: auto;
      font-family: var(--font-mono);
      font-size: 0.82rem;
    }
    .log-entry {
      display: grid;
      grid-template-columns: 80px 65px 1fr 60px;
      gap: 0.6rem;
      padding: 0.55rem 0.65rem;
      border-bottom: 1px solid #161c2b;
      align-items: center;
      transition: background 0.15s ease;
    }
    .log-entry:hover { background: rgba(255, 255, 255, 0.03); }
    .log-time { color: var(--text-muted); font-size: 0.75rem; }
    .method-badge {
      padding: 0.15rem 0.4rem;
      border-radius: 4px;
      font-weight: 700;
      font-size: 0.7rem;
      text-align: center;
    }
    .method-POST { background: rgba(59, 130, 246, 0.2); color: #60a5fa; border: 1px solid rgba(59, 130, 246, 0.4); }
    .method-GET { background: rgba(16, 185, 129, 0.2); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.4); }
    .status-badge {
      font-weight: 700;
      font-size: 0.75rem;
      text-align: center;
      padding: 0.15rem 0.35rem;
      border-radius: 4px;
    }
    .status-200, .status-201 { color: #34d399; background: rgba(16, 185, 129, 0.15); }
    .status-400, .status-404 { color: #f59e0b; background: rgba(245, 158, 11, 0.15); }
    .status-500 { color: #ef4444; background: rgba(239, 68, 68, 0.15); }

    /* Interactive Test Tools */
    .tool-box {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 12px;
      padding: 1.25rem;
      margin-bottom: 1.25rem;
    }
    .tool-box h3 {
      font-size: 0.95rem;
      margin-bottom: 0.8rem;
      color: #fff;
    }
    .form-group {
      margin-bottom: 0.75rem;
    }
    label {
      display: block;
      font-size: 0.75rem;
      color: var(--text-muted);
      margin-bottom: 0.3rem;
      font-family: var(--font-mono);
    }
    input {
      width: 100%;
      background: #090c13;
      border: 1px solid var(--card-border);
      border-radius: 6px;
      padding: 0.55rem 0.75rem;
      color: #fff;
      font-family: var(--font-mono);
      font-size: 0.85rem;
      outline: none;
      transition: border-color 0.2s;
    }
    input:focus { border-color: var(--primary); }
    button {
      width: 100%;
      background: var(--primary);
      color: #fff;
      border: none;
      border-radius: 6px;
      padding: 0.65rem;
      font-family: var(--font-body);
      font-weight: 600;
      font-size: 0.85rem;
      cursor: pointer;
      transition: background 0.2s;
    }
    button:hover { background: #2563eb; }
    .btn-secondary {
      background: #232b3e;
      color: #f0f3f8;
      margin-top: 0.4rem;
    }
    .btn-secondary:hover { background: #2d374d; }

    /* Users Table */
    .users-table {
      width: 100%;
      border-collapse: collapse;
      font-size: 0.8rem;
      margin-top: 0.5rem;
      font-family: var(--font-mono);
    }
    .users-table th {
      text-align: left;
      padding: 0.5rem;
      color: var(--text-muted);
      border-bottom: 1px solid var(--card-border);
    }
    .users-table td {
      padding: 0.5rem;
      border-bottom: 1px solid #161c2b;
    }

    footer {
      text-align: center;
      margin-top: 2rem;
      padding-top: 1rem;
      color: var(--text-muted);
      font-size: 0.8rem;
      border-top: 1px solid var(--card-border);
    }
  </style>
</head>
<body>
  <div class="container">
    <header>
      <div class="brand">
        <div>
          <h1 style="font-size: 1.35rem; font-weight: 800;">acm-db</h1>
          <p style="font-size: 0.8rem; color: var(--text-muted);">Database Microservice · Build The Internet</p>
        </div>
        <span class="badge badge-service">SERVICE 2 OF 4</span>
      </div>
      <div style="display: flex; gap: 0.75rem; align-items: center;">
        <a href="/docs" target="_blank" style="color: #60a5fa; font-size: 0.85rem; text-decoration: none; font-weight: 600;">Swagger Docs ↗</a>
        <span class="badge badge-status">
          <span class="status-dot"></span> LISTENING ON PORT 8001
        </span>
      </div>
    </header>

    <!-- Architecture flow trace -->
    <div class="arch-flow">
      <div class="arch-node">
        <strong>acm-app</strong>
        <small>Client</small>
      </div>
      <span class="arch-arrow">→</span>
      <div class="arch-node">
        <strong>acm-dns</strong>
        <small>Service Registry</small>
      </div>
      <span class="arch-arrow">→</span>
      <div class="arch-node">
        <strong>acm-server</strong>
        <small>Auth & Sessions</small>
      </div>
      <span class="arch-arrow">→</span>
      <div class="arch-node active-db">
        <strong>acm-db</strong>
        <small>User Storage (HERE)</small>
      </div>
    </div>

    <!-- Quick Stats -->
    <div class="stats-grid">
      <div class="card">
        <div class="card-title">Stored User Records</div>
        <div class="card-value" id="stat-users">0</div>
        <div class="card-sub">Table: users (indexed by username)</div>
      </div>
      <div class="card">
        <div class="card-title">Database Engine</div>
        <div class="card-value" style="font-size: 1.3rem;">SQLite WAL</div>
        <div class="card-sub">Zero-leakage parameterized SQL</div>
      </div>
      <div class="card">
        <div class="card-title">API Contract</div>
        <div class="card-value" style="font-size: 1.3rem; color: #34d399;">OpenAPI 3.0</div>
        <div class="card-sub">POST /db/users · GET /db/users/{user}</div>
      </div>
      <div class="card">
        <div class="card-title">Security Status</div>
        <div class="card-value" style="font-size: 1.3rem; color: #60a5fa;">Enforced</div>
        <div class="card-sub">Hashes only · Zero plaintext passwords</div>
      </div>
    </div>

    <div class="main-grid">
      <!-- Live Event Log -->
      <div class="card">
        <div class="section-head">
          <h2><span class="live-dot"></span> Live Event Stream (Bonus Dashboard)</h2>
          <span style="font-size: 0.75rem; color: var(--text-muted); font-family: var(--font-mono);">Auto-refreshes every 1.5s</span>
        </div>
        <div class="log-stream" id="log-container">
          <div style="padding: 1rem; color: var(--text-muted); text-align: center;">Waiting for incoming queries from acm-server...</div>
        </div>
      </div>

      <!-- Right Column: Manual Integration & Quick Tests -->
      <div>
        <!-- DNS Registration Box -->
        <div class="tool-box">
          <h3>Dynamic DNS Registration</h3>
          <div class="form-group">
            <label>acm-dns Address (e.g. http://10.0.0.2:8000)</label>
            <input type="text" id="dns-input" placeholder="http://<DNS_IP>:8000">
          </div>
          <button onclick="registerWithDNS()">Register acm-db with DNS</button>
          <div id="dns-result" style="margin-top: 0.5rem; font-size: 0.75rem; font-family: var(--font-mono);"></div>
        </div>

        <!-- Quick User Query Box -->
        <div class="tool-box">
          <h3>Quick User Lookup Test</h3>
          <div class="form-group">
            <label>Username to find</label>
            <input type="text" id="lookup-input" placeholder="alice">
          </div>
          <button class="btn-secondary" onclick="lookupUser()">Test GET /db/users/{username}</button>
          <div id="lookup-result" style="margin-top: 0.5rem; font-size: 0.75rem; font-family: var(--font-mono);"></div>
        </div>

        <!-- User Registry Preview -->
        <div class="tool-box">
          <h3>Recent Users (Masked Hashes)</h3>
          <table class="users-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Username</th>
                <th>Hash Preview</th>
              </tr>
            </thead>
            <tbody id="users-table-body">
              <tr><td colspan="3" style="text-align: center; color: var(--text-muted);">No users yet</td></tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <footer>
      Build The Internet Hackathon · Service: <code>acm-db</code> · Connected to <code>acm-server</code>
    </footer>
  </div>

  <script>
    async function fetchLogs() {
      try {
        const res = await fetch('/api/logs');
        if (!res.ok) return;
        const data = await res.json();
        
        document.getElementById('stat-users').innerText = data.total_users;

        // Render Logs
        const logBox = document.getElementById('log-container');
        if (data.events.length === 0) {
          logBox.innerHTML = '<div style="padding: 1rem; color: var(--text-muted); text-align: center;">No queries recorded yet. Start acm-server and make a request!</div>';
        } else {
          logBox.innerHTML = data.events.map(ev => `
            <div class="log-entry">
              <span class="log-time">${ev.timestamp}</span>
              <span class="method-badge method-${ev.method}">${ev.method}</span>
              <div style="overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
                <span style="color: #fff;">${ev.path}</span>
                <span style="color: var(--text-muted); font-size: 0.7rem; margin-left: 0.4rem;">${ev.detail}</span>
              </div>
              <span class="status-badge status-${ev.status_code}">${ev.status_code}</span>
            </div>
          `).join('');
        }

        // Render Users
        const usersTable = document.getElementById('users-table-body');
        if (data.users && data.users.length > 0) {
          usersTable.innerHTML = data.users.map(u => `
            <tr>
              <td>#${u.user_id}</td>
              <td style="color: #60a5fa; font-weight: 600;">${u.username}</td>
              <td style="color: var(--text-muted);">${u.password_hash_preview}</td>
            </tr>
          `).join('');
        } else {
          usersTable.innerHTML = '<tr><td colspan="3" style="text-align: center; color: var(--text-muted);">No users stored yet</td></tr>';
        }

      } catch (err) {
        console.error('Error fetching logs:', err);
      }
    }

    async function registerWithDNS() {
      const dnsUrl = document.getElementById('dns-input').value.trim();
      const resBox = document.getElementById('dns-result');
      resBox.innerHTML = '<span style="color: #60a5fa;">Registering...</span>';
      try {
        const res = await fetch('/register-dns', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ dns_url: dnsUrl || undefined, domain: 'acm-db' })
        });
        const json = await res.json();
        if (json.success) {
          resBox.innerHTML = '<span style="color: #34d399;">✓ ' + json.message + '</span>';
        } else {
          resBox.innerHTML = '<span style="color: #ef4444;">✗ ' + (json.message || json.error) + '</span>';
        }
      } catch (e) {
        resBox.innerHTML = '<span style="color: #ef4444;">✗ Error: ' + e.message + '</span>';
      }
      fetchLogs();
    }

    async function lookupUser() {
      const username = document.getElementById('lookup-input').value.trim();
      const resBox = document.getElementById('lookup-result');
      if (!username) return;
      resBox.innerHTML = '<span style="color: #60a5fa;">Querying /db/users/' + username + '...</span>';
      try {
        const res = await fetch('/db/users/' + encodeURIComponent(username));
        const json = await res.json();
        if (res.status === 200) {
          resBox.innerHTML = '<span style="color: #34d399;">✓ 200 OK: ID #' + json.user_id + ' | Hash: ' + json.password_hash.substring(0, 12) + '...</span>';
        } else {
          resBox.innerHTML = '<span style="color: #f59e0b;">✗ ' + res.status + ': ' + json.error + '</span>';
        }
      } catch (e) {
        resBox.innerHTML = '<span style="color: #ef4444;">✗ Error: ' + e.message + '</span>';
      }
      fetchLogs();
    }

    // Auto-poll every 1.5s
    setInterval(fetchLogs, 1500);
    fetchLogs();
  </script>
</body>
</html>
    """
    return HTMLResponse(content=html_content)


if __name__ == "__main__":
    import uvicorn
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8001"))
    logger.info("Starting uvicorn server on %s:%d", host, port)
    uvicorn.run("main:app", host=host, port=port, reload=False)
