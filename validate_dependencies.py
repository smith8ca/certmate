#!/usr/bin/env python3
"""
Validate CertMate dependencies and DNS provider support
"""

import sys
import subprocess
import importlib.util

def check_dependency(package_name, import_name=None):
    """Check if a dependency is available"""
    if import_name is None:
        import_name = package_name.replace('-', '_')
    
    try:
        spec = importlib.util.find_spec(import_name)
        if spec is not None:
            print(f"✓ {package_name} is available")
            return True
        else:
            print(f"✗ {package_name} is not available")
            return False
    except ImportError:
        print(f"✗ {package_name} is not available")
        return False

def check_certbot_plugins():
    """Check if certbot DNS plugins are available"""
    print("\nChecking Certbot DNS plugins...")
    
    plugins = [
        ('certbot-dns-cloudflare', 'certbot_dns_cloudflare'),
        ('certbot-dns-route53', 'certbot_dns_route53'),
        ('certbot-dns-azure', 'certbot_dns_azure'),
        ('certbot-dns-google', 'certbot_dns_google'),
        ('certbot-dns-powerdns', 'certbot_dns_powerdns'),
    ]
    
    available = 0
    total = len(plugins)
    
    for plugin_name, import_name in plugins:
        if check_dependency(plugin_name, import_name):
            available += 1
    
    print(f"\n{available}/{total} DNS plugins available")
    return available == total

def check_core_dependencies():
    """Check core application dependencies"""
    print("Checking core dependencies...")
    
    dependencies = [
        ('Flask', 'flask'),
        ('Flask-CORS', 'flask_cors'),
        ('flask-restx', 'flask_restx'),
        ('certbot', 'certbot'),
        ('requests', 'requests'),
        ('APScheduler', 'apscheduler'),
        ('cryptography', 'cryptography'),
        ('gunicorn', 'gunicorn'),
        ('python-dotenv', 'dotenv'),
    ]
    
    available = 0
    total = len(dependencies)
    
    for dep_name, import_name in dependencies:
        if check_dependency(dep_name, import_name):
            available += 1
    
    print(f"\n{available}/{total} core dependencies available")
    return available == total

def check_dns_provider_deps():
    """Check DNS provider specific dependencies"""
    print("\nChecking DNS provider dependencies...")
    
    dependencies = [
        ('cloudflare', 'cloudflare'),
        ('boto3', 'boto3'),
        ('azure-identity', 'azure.identity'),
        ('azure-mgmt-dns', 'azure.mgmt.dns'),
        ('google-cloud-dns', 'google.cloud.dns'),
    ]
    
    available = 0
    total = len(dependencies)
    
    for dep_name, import_name in dependencies:
        if check_dependency(dep_name, import_name):
            available += 1
    
    print(f"\n{available}/{total} DNS provider dependencies available")
    return available == total

def test_certbot_plugins():
    """Test if certbot can see our DNS plugins"""
    print("\nTesting Certbot plugin detection...")
    
    try:
        result = subprocess.run(['certbot', 'plugins', '--text'], 
                              capture_output=True, text=True, timeout=10)
        
        if result.returncode == 0:
            output = result.stdout
            plugins_found = []
            
            dns_plugins = ['dns-cloudflare', 'dns-route53', 'dns-azure', 'dns-google', 'dns-powerdns']
            
            for plugin in dns_plugins:
                if plugin in output:
                    plugins_found.append(plugin)
                    print(f"✓ {plugin} plugin detected by certbot")
                else:
                    print(f"✗ {plugin} plugin not detected by certbot")
            
            print(f"\n{len(plugins_found)}/{len(dns_plugins)} DNS plugins detected by certbot")
            return len(plugins_found) > 0
        else:
            print(f"✗ Certbot failed to list plugins: {result.stderr}")
            return False
    except subprocess.TimeoutExpired:
        print("✗ Certbot command timed out")
        return False
    except FileNotFoundError:
        print("✗ Certbot not found in PATH")
        return False
    except Exception as e:
        print(f"✗ Error running certbot: {e}")
        return False

def main():
    """Run all validation checks"""
    print("CertMate Dependency Validation")
    print("=" * 40)
    
    checks = [
        ("Core Dependencies", check_core_dependencies),
        ("DNS Provider Dependencies", check_dns_provider_deps),
        ("Certbot DNS Plugins", check_certbot_plugins),
        ("Certbot Plugin Detection", test_certbot_plugins),
    ]
    
    passed = 0
    total = len(checks)
    
    for check_name, check_func in checks:
        print(f"\n{check_name}:")
        print("-" * len(check_name))
        
        try:
            if check_func():
                print(f"✓ {check_name} - PASSED")
                passed += 1
            else:
                print(f"✗ {check_name} - FAILED")
        except Exception as e:
            print(f"✗ {check_name} - ERROR: {e}")
    
    print("\n" + "=" * 40)
    print(f"Validation Summary: {passed}/{total} checks passed")
    
    if passed == total:
        print("✓ All dependencies are properly installed!")
        print("✓ CertMate should work correctly with all DNS providers")
        return 0
    else:
        print("✗ Some dependencies are missing or not working")
        print("\nTo fix missing dependencies, run:")
        print("pip install -r requirements.txt")
        return 1

if __name__ == '__main__':
    sys.exit(main())
