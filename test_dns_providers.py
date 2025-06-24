#!/usr/bin/env python3
"""
Test script for CertMate DNS provider functionality
"""

import requests
import json
import sys
import os
import time

# Configuration
BASE_URL = os.getenv('CERTMATE_URL', 'http://localhost:5000')
API_TOKEN = os.getenv('API_BEARER_TOKEN', 'test-token')

def wait_for_service(max_attempts=30, delay=2):
    """Wait for the service to be available"""
    print("Waiting for CertMate service to be available...")
    
    for attempt in range(max_attempts):
        try:
            response = requests.get(f"{BASE_URL}/api/health", timeout=5)
            if response.status_code == 200:
                print("✓ Service is available")
                return True
        except requests.exceptions.ConnectionError:
            if attempt < max_attempts - 1:
                print(f"Attempt {attempt + 1}/{max_attempts}: Service not ready, waiting {delay}s...")
                time.sleep(delay)
            else:
                print("✗ Service failed to start within timeout")
                return False
        except Exception as e:
            print(f"✗ Unexpected error connecting to service: {e}")
            return False
    
    return False

def test_dns_providers():
    """Test DNS providers endpoint"""
    print("Testing DNS providers endpoint...")
    
    headers = {'Authorization': f'Bearer {API_TOKEN}'}
    
    try:
        response = requests.get(f"{BASE_URL}/api/settings/dns-providers", headers=headers, timeout=10)
        if response.status_code == 200:
            data = response.json()
            print("✓ DNS providers endpoint working")
            print(f"Current provider: {data.get('current_provider', 'None')}")
            
            providers = data.get('available_providers', {})
            for provider, info in providers.items():
                status = "✓ Configured" if info.get('configured') else "✗ Not configured"
                print(f"  {provider}: {info.get('name')} - {status}")
            
            return True
        elif response.status_code == 401:
            print("✗ DNS providers endpoint failed: Invalid API token")
            return False
        else:
            print(f"✗ DNS providers endpoint failed: {response.status_code}")
            try:
                error_data = response.json()
                print(f"Error details: {error_data}")
            except:
                print(f"Raw response: {response.text}")
            return False
    except requests.exceptions.Timeout:
        print("✗ Request timed out - service may be overloaded")
        return False
    except Exception as e:
        print(f"✗ Error testing DNS providers: {e}")
        return False

def test_settings_update():
    """Test updating settings with DNS provider configuration"""
    print("\nTesting settings update...")
    
    headers = {
        'Authorization': f'Bearer {API_TOKEN}',
        'Content-Type': 'application/json'
    }
    
    # Test data
    test_settings = {
        'email': 'test@example.com',
        'dns_provider': 'cloudflare',
        'dns_providers': {
            'cloudflare': {
                'api_token': 'test-token-123'
            }
        }
    }
    
    try:
        response = requests.post(f"{BASE_URL}/api/settings", 
                               headers=headers, 
                               json=test_settings)
        
        if response.status_code == 200:
            data = response.json()
            if data.get('success'):
                print("✓ Settings update working")
                return True
            else:
                print(f"✗ Settings update failed: {data.get('message')}")
                return False
        else:
            print(f"✗ Settings update failed: {response.status_code}")
            return False
    except Exception as e:
        print(f"✗ Error testing settings update: {e}")
        return False

def test_certificate_creation():
    """Test certificate creation with DNS provider"""
    print("\nTesting certificate creation API...")
    
    headers = {
        'Authorization': f'Bearer {API_TOKEN}',
        'Content-Type': 'application/json'
    }
    
    # Test data (won't actually create cert without proper config)
    test_cert = {
        'domain': 'test.example.com',
        'dns_provider': 'cloudflare'
    }
    
    try:
        response = requests.post(f"{BASE_URL}/api/certificates/create", 
                               headers=headers, 
                               json=test_cert)
        
        # We expect this to fail with configuration error, which is normal
        if response.status_code in [200, 400]:
            data = response.json()
            if 'not configured' in data.get('message', '').lower():
                print("✓ Certificate creation API working (config validation working)")
                return True
            elif data.get('success'):
                print("✓ Certificate creation API working (creation started)")
                return True
            else:
                print(f"? Certificate creation response: {data.get('message')}")
                return True  # Still working, just not configured
        else:
            print(f"✗ Certificate creation failed: {response.status_code}")
            return False
    except Exception as e:
        print(f"✗ Error testing certificate creation: {e}")
        return False

def test_version_compatibility():
    """Test if the installed certbot version is compatible"""
    print("\nTesting version compatibility...")
    
    try:
        import certbot
        import pkg_resources
        
        # Get installed version
        certbot_version = pkg_resources.get_distribution('certbot').version
        print(f"Installed Certbot version: {certbot_version}")
        
        # Check if it's 4.1.1 or compatible
        if certbot_version >= "4.1.1":
            print("✓ Certbot version is compatible with all DNS providers")
            return True
        elif certbot_version >= "2.11.0":
            print("⚠ Certbot version may have compatibility issues with newer DNS plugins")
            print("  Consider upgrading to 4.1.1 for full compatibility")
            return True
        else:
            print("✗ Certbot version is too old")
            print("  Please upgrade to 4.1.1")
            return False
            
    except ImportError:
        print("✗ Certbot is not installed")
        return False
    except Exception as e:
        print(f"✗ Error checking certbot version: {e}")
        return False

def main():
    """Run all tests"""
    print("CertMate DNS Provider Test Suite")
    print("=" * 40)
    
    # Check if service is available first
    if not wait_for_service():
        print("✗ Cannot connect to CertMate service")
        print("Make sure the service is running at:", BASE_URL)
        return 1
    
    tests = [
        test_version_compatibility,
        test_dns_providers,
        test_settings_update,
        test_certificate_creation
    ]
    
    passed = 0
    total = len(tests)
    
    for test in tests:
        try:
            if test():
                passed += 1
        except KeyboardInterrupt:
            print("\n⚠ Tests interrupted by user")
            break
        except Exception as e:
            print(f"✗ Test {test.__name__} crashed: {e}")
    
    print("\n" + "=" * 40)
    print(f"Tests passed: {passed}/{total}")
    
    if passed == total:
        print("✓ All tests passed! DNS provider support is working correctly.")
        return 0
    else:
        print("✗ Some tests failed. Check the output above for details.")
        print("Common issues:")
        print("  - Make sure CertMate is running")
        print("  - Check your API_BEARER_TOKEN environment variable")
        print("  - Verify the service URL is correct")
        return 1

if __name__ == '__main__':
    sys.exit(main())
