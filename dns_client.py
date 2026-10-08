"""
acm-db DNS Registration Client
Build The Internet Hackathon - Dynamic Service Discovery

Enables acm-db to register its domain ('acm-db') with the acm-dns service,
fulfilling Rule 2 (Dynamic Service Discovery) and Rule 3 (No hardcoded IPs).
"""

import os
import logging
from typing import Dict, Any, Optional
import httpx

logger = logging.getLogger("acm-db.dns")

class DNSClient:
    def __init__(self, dns_url: Optional[str] = None):
        # Format: http://<DNS_IP>:<DNS_PORT>
        self.dns_url = dns_url or os.getenv("DNS_URL")
        if not self.dns_url and os.getenv("DNS_HOST"):
            dns_host = os.getenv("DNS_HOST")
            dns_port = os.getenv("DNS_PORT", "8000")
            self.dns_url = f"http://{dns_host}:{dns_port}"

    def register_service(self, domain: str = "acm-db") -> Dict[str, Any]:
        """
        Sends POST /register with {"domain": domain} to acm-dns.
        acm-dns captures our source IP address and maps it to domain 'acm-db'.
        """
        if not self.dns_url:
            logger.warning("DNS_URL / DNS_HOST not configured. Skipping automated DNS registration.")
            return {
                "success": False,
                "message": "DNS_URL not configured. Provide DNS_HOST or DNS_URL to register."
            }

        endpoint = f"{self.dns_url.rstrip('/')}/register"
        payload = {"domain": domain}

        try:
            logger.info("Registering '%s' with DNS at %s", domain, endpoint)
            with httpx.Client(timeout=5.0) as client:
                response = client.post(endpoint, json=payload)
                if response.status_code in (200, 201):
                    logger.info("Successfully registered '%s' with DNS!", domain)
                    return {
                        "success": True,
                        "status_code": response.status_code,
                        "dns_response": response.json(),
                        "message": f"Successfully registered '{domain}' with acm-dns at {self.dns_url}"
                    }
                else:
                    logger.warning("Failed to register with DNS (status %s): %s", response.status_code, response.text)
                    return {
                        "success": False,
                        "status_code": response.status_code,
                        "message": f"DNS server returned {response.status_code}: {response.text}"
                    }
        except Exception as e:
            logger.error("Error connecting to DNS at %s: %s", endpoint, e)
            return {
                "success": False,
                "error": str(e),
                "message": f"Could not reach DNS server at {endpoint}. Ensure acm-dns is running."
            }
