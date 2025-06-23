#!/usr/bin/env python3
"""
CertMate API Client Example
This script demonstrates how to interact with the CertMate API
"""

import requests
import json
import os
from typing import Optional, Dict, Any

class CertMateClient:
    def __init__(self, base_url: str, api_token: str):
        """
        Initialize the CertMate API client
        
        Args:
            base_url: Base URL of the CertMate server (e.g., http://localhost:8000)
            api_token: Bearer token for authentication
        """
        self.base_url = base_url.rstrip('/')
        self.headers = {
            'Authorization': f'Bearer {api_token}',
            'Content-Type': 'application/json'
        }
    
    def health_check(self) -> Dict[str, Any]:
        """Check if the server is healthy"""
        response = requests.get(f"{self.base_url}/health")
        return response.json()
    
    def get_settings(self) -> Dict[str, Any]:
        """Get current settings"""
        response = requests.get(f"{self.base_url}/api/settings", headers=self.headers)
        response.raise_for_status()
        return response.json()
    
    def update_settings(self, settings: Dict[str, Any]) -> Dict[str, Any]:
        """Update settings"""
        response = requests.post(
            f"{self.base_url}/api/settings",
            headers=self.headers,
            json=settings
        )
        response.raise_for_status()
        return response.json()
    
    def list_certificates(self) -> list:
        """List all certificates"""
        response = requests.get(f"{self.base_url}/api/certificates", headers=self.headers)
        response.raise_for_status()
        return response.json()
    
    def create_certificate(self, domain: str) -> Dict[str, Any]:
        """Create a new certificate"""
        response = requests.post(
            f"{self.base_url}/api/certificates/create",
            headers=self.headers,
            json={'domain': domain}
        )
        response.raise_for_status()
        return response.json()
    
    def renew_certificate(self, domain: str) -> Dict[str, Any]:
        """Renew a certificate"""
        response = requests.post(
            f"{self.base_url}/api/certificates/{domain}/renew",
            headers=self.headers
        )
        response.raise_for_status()
        return response.json()
    
    def download_certificate(self, domain: str, output_file: str) -> bool:
        """Download certificate as ZIP file"""
        response = requests.get(
            f"{self.base_url}/api/certificates/{domain}/download",
            headers=self.headers
        )
        response.raise_for_status()
        
        with open(output_file, 'wb') as f:
            f.write(response.content)
        
        return True
    
    def download_certificate_simple(self, domain: str, output_file: str) -> bool:
        """Download certificate using the simple /domain/tls endpoint"""
        response = requests.get(
            f"{self.base_url}/{domain}/tls",
            headers=self.headers
        )
        response.raise_for_status()
        
        with open(output_file, 'wb') as f:
            f.write(response.content)
        
        return True

def main():
    """Example usage of the CertMate API client"""
    # Configuration
    SERVER_URL = os.getenv('CERTMATE_URL', 'http://localhost:8000')
    API_TOKEN = os.getenv('CERTMATE_TOKEN', 'change-this-token')
    
    # Initialize client
    client = CertMateClient(SERVER_URL, API_TOKEN)
    
    try:
        # Health check
        print("🔍 Checking server health...")
        health = client.health_check()
        print(f"✅ Server is healthy: {health}")
        
        # Get settings
        print("\n⚙️  Getting current settings...")
        settings = client.get_settings()
        print(f"📋 Current settings: {json.dumps(settings, indent=2)}")
        
        # List certificates
        print("\n📜 Listing certificates...")
        certificates = client.list_certificates()
        if certificates:
            for cert in certificates:
                print(f"🔐 {cert['domain']}: expires {cert['expiry_date']} ({cert['days_left']} days left)")
        else:
            print("📭 No certificates found")
        
        # Example: Create a certificate (uncomment to use)
        # print("\n🆕 Creating certificate for example.com...")
        # result = client.create_certificate('example.com')
        # print(f"✅ Certificate creation started: {result}")
        
        # Example: Download certificate (uncomment to use)
        # print("\n📦 Downloading certificate...")
        # client.download_certificate_simple('example.com', 'example.com-tls.zip')
        # print("✅ Certificate downloaded to example.com-tls.zip")
        
    except requests.exceptions.RequestException as e:
        print(f"❌ API request failed: {e}")
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == '__main__':
    main()
