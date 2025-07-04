from flask import Flask, render_template, request, jsonify, send_file
from flask_cors import CORS
from flask_restx import Api, Resource, fields, Namespace
from functools import wraps
import os
import json
import subprocess
import tempfile
import zipfile
from datetime import datetime, timedelta
import threading
from apscheduler.schedulers.background import BackgroundScheduler
import logging
from pathlib import Path
import ssl
import socket
from urllib.parse import urlparse
import requests
from cryptography import x509
from cryptography.hazmat.backends import default_backend
import fcntl  # For file locking
import re
import secrets
import atexit

# Initialize Flask app
app = Flask(__name__)
# Generate a secure random secret key if not provided
default_secret = os.urandom(32).hex() if not os.getenv('SECRET_KEY') else 'your-secret-key-here'
app.secret_key = os.getenv('SECRET_KEY', default_secret)
CORS(app)

# Initialize Flask-RESTX
api = Api(
    app,
    version='1.0',
    title='CertMate API',
    description='SSL Certificate Management API with Cloudflare DNS Challenge',
    doc='/docs/',
    prefix='/api'
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Directories with proper error handling
try:
    CERT_DIR = Path("certificates")
    DATA_DIR = Path("data")
    CERT_DIR.mkdir(exist_ok=True)
    DATA_DIR.mkdir(exist_ok=True)
    
    # Verify directory permissions
    if not os.access(CERT_DIR, os.W_OK):
        logger.error(f"No write permission for certificates directory: {CERT_DIR}")
    if not os.access(DATA_DIR, os.W_OK):
        logger.error(f"No write permission for data directory: {DATA_DIR}")
        
except Exception as e:
    logger.error(f"Failed to create required directories: {e}")
    # Use temporary directories as fallback
    CERT_DIR = Path(tempfile.mkdtemp(prefix="certmate_certs_"))
    DATA_DIR = Path(tempfile.mkdtemp(prefix="certmate_data_"))
    logger.warning(f"Using temporary directories - certificates may not persist")

# Settings file
SETTINGS_FILE = DATA_DIR / "settings.json"

# Initialize scheduler with error handling
try:
    scheduler = BackgroundScheduler()
    scheduler.start()
    logger.info("Background scheduler started successfully")
except Exception as e:
    logger.error(f"Failed to start background scheduler: {e}")
    scheduler = None

def load_settings():
    """Load settings from file with improved error handling"""
    default_settings = {
        'cloudflare_token': '',
        'domains': [],
        'email': '',
        'auto_renew': True,
        'api_bearer_token': os.getenv('API_BEARER_TOKEN') or generate_secure_token(),
        'setup_completed': False,  # Track if initial setup is done
        'dns_provider': 'cloudflare',
        'dns_providers': {
            'cloudflare': {'api_token': ''},
            'route53': {'access_key_id': '', 'secret_access_key': '', 'region': 'us-east-1'},
            'azure': {'subscription_id': '', 'resource_group': '', 'tenant_id': '', 'client_id': '', 'client_secret': ''},
            'google': {'project_id': '', 'service_account_key': ''},
            'powerdns': {'api_url': '', 'api_key': ''},
            'digitalocean': {'api_token': ''},
            'linode': {'api_key': ''},
            'gandi': {'api_token': ''},
            'ovh': {'endpoint': '', 'application_key': '', 'application_secret': '', 'consumer_key': ''},
            'namecheap': {'username': '', 'api_key': ''}
        }
    }
    
    if not SETTINGS_FILE.exists():
        # First time setup - create with secure defaults
        logger.info("Creating initial settings file with secure defaults")
        save_settings(default_settings)
        return default_settings
    
    try:
        settings = safe_file_read(SETTINGS_FILE, is_json=True)
        if settings is None:
            logger.warning("Failed to read settings, using defaults")
            return default_settings
            
        # Validate and merge with defaults
        for key, default_value in default_settings.items():
            if key not in settings:
                settings[key] = default_value
                
        # Validate critical settings
        if settings.get('api_bearer_token') in ['change-this-token', 'certmate-api-token-12345', '']:
            logger.warning("Insecure API token detected, generating new one")
            settings['api_bearer_token'] = generate_secure_token()
            save_settings(settings)
            
        return settings
        
    except Exception as e:
        logger.error(f"Error loading settings: {e}")
        return default_settings

def save_settings(settings):
    """Save settings to file with improved error handling and validation"""
    try:
        # Validate critical settings before saving
        if 'email' in settings and settings['email']:
            is_valid, email_or_error = validate_email(settings['email'])
            if not is_valid:
                logger.error(f"Invalid email in settings: {email_or_error}")
                return False
            settings['email'] = email_or_error
            
        if 'api_bearer_token' in settings:
            is_valid, token_or_error = validate_api_token(settings['api_bearer_token'])
            if not is_valid:
                logger.error(f"Invalid API token: {token_or_error}")
                return False
                
        # Validate domains
        if 'domains' in settings:
            validated_domains = []
            for domain_entry in settings['domains']:
                if isinstance(domain_entry, str):
                    is_valid, domain_or_error = validate_domain(domain_entry)
                    if is_valid:
                        validated_domains.append(domain_or_error)
                    else:
                        logger.warning(f"Invalid domain skipped: {domain_or_error}")
                elif isinstance(domain_entry, dict) and 'domain' in domain_entry:
                    is_valid, domain_or_error = validate_domain(domain_entry['domain'])
                    if is_valid:
                        domain_entry['domain'] = domain_or_error
                        validated_domains.append(domain_entry)
                    else:
                        logger.warning(f"Invalid domain in object skipped: {domain_or_error}")
            settings['domains'] = validated_domains
        
        return safe_file_write(SETTINGS_FILE, settings)
        
    except Exception as e:
        logger.error(f"Error saving settings: {e}")
        return False

def require_auth(f):
    """Enhanced decorator to require bearer token authentication"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        if not auth_header:
            return {'error': 'Authorization header required', 'code': 'AUTH_HEADER_MISSING'}, 401
        
        try:
            scheme, token = auth_header.split(' ', 1)
            if scheme.lower() != 'bearer':
                return {'error': 'Invalid authorization scheme. Use Bearer token', 'code': 'INVALID_AUTH_SCHEME'}, 401
        except ValueError:
            return {'error': 'Invalid authorization header format. Use: Bearer <token>', 'code': 'INVALID_AUTH_FORMAT'}, 401
        
        settings = load_settings()
        expected_token = settings.get('api_bearer_token')
        
        if not expected_token:
            return {'error': 'Server configuration error: no API token configured', 'code': 'SERVER_CONFIG_ERROR'}, 500
            
        # Validate token strength
        is_valid, validation_error = validate_api_token(expected_token)
        if not is_valid:
            logger.error(f"Server has weak API token: {validation_error}")
            return {'error': 'Server security configuration error', 'code': 'WEAK_SERVER_TOKEN'}, 500
        
        if not secrets.compare_digest(token, expected_token):
            logger.warning(f"Invalid token attempt from {request.remote_addr}")
            return {'error': 'Invalid or expired token', 'code': 'INVALID_TOKEN'}, 401
        
        return f(*args, **kwargs)
    return decorated_function

def create_cloudflare_config(token):
    """Create Cloudflare credentials file"""
    config_dir = Path("letsencrypt/config")
    config_dir.mkdir(parents=True, exist_ok=True)
    
    config_file = config_dir / "cloudflare.ini"
    with open(config_file, 'w') as f:
        f.write(f"dns_cloudflare_api_token = {token}\n")
    
    # Set proper permissions
    config_file.chmod(0o600)
    return config_file

def create_route53_config(access_key_id, secret_access_key):
    """Create AWS Route53 credentials file"""
    config_dir = Path("letsencrypt/config")
    config_dir.mkdir(parents=True, exist_ok=True)
    
    config_file = config_dir / "route53.ini"
    with open(config_file, 'w') as f:
        f.write(f"dns_route53_access_key_id = {access_key_id}\n")
        f.write(f"dns_route53_secret_access_key = {secret_access_key}\n")
    
    # Set proper permissions
    config_file.chmod(0o600)
    return config_file

def create_azure_config(subscription_id, resource_group, tenant_id, client_id, client_secret):
    """Create Azure DNS credentials file"""
    config_dir = Path("letsencrypt/config")
    config_dir.mkdir(parents=True, exist_ok=True)
    
    config_file = config_dir / "azure.ini"
    with open(config_file, 'w') as f:
        f.write(f"dns_azure_subscription_id = {subscription_id}\n")
        f.write(f"dns_azure_resource_group = {resource_group}\n")
        f.write(f"dns_azure_tenant_id = {tenant_id}\n")
        f.write(f"dns_azure_client_id = {client_id}\n")
        f.write(f"dns_azure_client_secret = {client_secret}\n")
    
    # Set proper permissions
    config_file.chmod(0o600)
    return config_file

def create_google_config(project_id, service_account_key):
    """Create Google Cloud DNS credentials file"""
    config_dir = Path("letsencrypt/config")
    config_dir.mkdir(parents=True, exist_ok=True)
    
    # Create service account JSON file
    sa_file = config_dir / "google-service-account.json"
    with open(sa_file, 'w') as f:
        f.write(service_account_key)
    sa_file.chmod(0o600)
    
    # Create credentials file
    config_file = config_dir / "google.ini"
    with open(config_file, 'w') as f:
        f.write(f"dns_google_project_id = {project_id}\n")
        f.write(f"dns_google_service_account_key = {str(sa_file)}\n")
    
    # Set proper permissions
    config_file.chmod(0o600)
    return config_file

def create_powerdns_config(api_url, api_key):
    """Create PowerDNS credentials file"""
    config_dir = Path("letsencrypt/config")
    config_dir.mkdir(parents=True, exist_ok=True)
    
    config_file = config_dir / "powerdns.ini"
    with open(config_file, 'w') as f:
        f.write(f"dns_powerdns_api_url = {api_url}\n")
        f.write(f"dns_powerdns_api_key = {api_key}\n")
    
    # Set proper permissions
    config_file.chmod(0o600)
    return config_file

def create_digitalocean_config(api_token):
    """Create DigitalOcean DNS credentials file"""
    config_dir = Path("letsencrypt/config")
    config_dir.mkdir(parents=True, exist_ok=True)
    
    config_file = config_dir / "digitalocean.ini"
    with open(config_file, 'w') as f:
        f.write(f"dns_digitalocean_token = {api_token}\n")
    
    # Set proper permissions
    config_file.chmod(0o600)
    return config_file

def create_linode_config(api_key):
    """Create Linode DNS credentials file"""
    config_dir = Path("letsencrypt/config")
    config_dir.mkdir(parents=True, exist_ok=True)
    
    config_file = config_dir / "linode.ini"
    with open(config_file, 'w') as f:
        f.write(f"dns_linode_key = {api_key}\n")
        f.write("dns_linode_version = 4\n")  # Use API v4
    
    # Set proper permissions
    config_file.chmod(0o600)
    return config_file

def create_gandi_config(api_token):
    """Create Gandi DNS credentials file"""
    config_dir = Path("letsencrypt/config")
    config_dir.mkdir(parents=True, exist_ok=True)
    
    config_file = config_dir / "gandi.ini"
    with open(config_file, 'w') as f:
        f.write(f"dns_gandi_token = {api_token}\n")
    
    # Set proper permissions
    config_file.chmod(0o600)
    return config_file

def create_ovh_config(endpoint, application_key, application_secret, consumer_key):
    """Create OVH DNS credentials file"""
    config_dir = Path("letsencrypt/config")
    config_dir.mkdir(parents=True, exist_ok=True)
    
    config_file = config_dir / "ovh.ini"
    with open(config_file, 'w') as f:
        f.write(f"dns_ovh_endpoint = {endpoint}\n")
        f.write(f"dns_ovh_application_key = {application_key}\n")
        f.write(f"dns_ovh_application_secret = {application_secret}\n")
        f.write(f"dns_ovh_consumer_key = {consumer_key}\n")
    
    # Set proper permissions
    config_file.chmod(0o600)
    return config_file

def create_namecheap_config(username, api_key):
    """Create Namecheap DNS credentials file"""
    config_dir = Path("letsencrypt/config")
    config_dir.mkdir(parents=True, exist_ok=True)
    
    config_file = config_dir / "namecheap.ini"
    with open(config_file, 'w') as f:
        f.write(f"dns_namecheap_username = {username}\n")
        f.write(f"dns_namecheap_api_key = {api_key}\n")
    
    # Set proper permissions
    config_file.chmod(0o600)
    return config_file

def create_multi_provider_config(provider, config_data):
    """Create configuration for additional DNS providers using individual plugins where available
    
    This function supports additional providers beyond the core Tier 1 providers.
    For providers without individual certbot plugins, returns None to indicate
    direct API implementation should be used instead.
    """
    config_dir = Path("letsencrypt/config")
    config_dir.mkdir(parents=True, exist_ok=True)
    
    # Map providers to their individual plugin configuration files
    plugin_configs = {
        'vultr': 'vultr.ini',
        'dnsmadeeasy': 'dnsmadeeasy.ini',
        'nsone': 'nsone.ini',
        'rfc2136': 'rfc2136.ini',
        'hetzner': 'hetzner.ini',
        'porkbun': 'porkbun.ini',
        'godaddy': 'godaddy.ini',
        'he-ddns': 'he-ddns.ini',
        'dynudns': 'dynudns.ini'
    }
    
    if provider not in plugin_configs:
        # Provider doesn't have an individual plugin
        # Return None to indicate fallback to direct API should be used
        return None
    
    config_file = config_dir / plugin_configs[provider]
    
    # Create provider-specific configuration
    if provider == 'vultr':
        api_key = config_data.get('api_key')
        if not api_key:
            raise ValueError("Vultr API key required")
        
        config_content = f"dns_vultr_api_key = {api_key}\n"
        
    elif provider == 'dnsmadeeasy':
        api_key = config_data.get('api_key')
        secret_key = config_data.get('secret_key')
        if not api_key or not secret_key:
            raise ValueError("DNS Made Easy API key and secret key required")
            
        config_content = f"dns_dnsmadeeasy_api_key = {api_key}\n"
        config_content += f"dns_dnsmadeeasy_secret_key = {secret_key}\n"
        
    elif provider == 'nsone':
        api_key = config_data.get('api_key')
        if not api_key:
            raise ValueError("NS1 API key required")
            
        config_content = f"dns_nsone_api_key = {api_key}\n"
        
    elif provider == 'rfc2136':
        nameserver = config_data.get('nameserver')
        tsig_key = config_data.get('tsig_key')
        tsig_secret = config_data.get('tsig_secret')
        tsig_algorithm = config_data.get('tsig_algorithm', 'HMAC-SHA512')
        
        if not nameserver or not tsig_key or not tsig_secret:
            raise ValueError("RFC2136 nameserver, TSIG key and secret required")
            
        config_content = f"dns_rfc2136_nameserver = {nameserver}\n"
        config_content += f"dns_rfc2136_name = {tsig_key}\n"
        config_content += f"dns_rfc2136_secret = {tsig_secret}\n"
        config_content += f"dns_rfc2136_algorithm = {tsig_algorithm}\n"
        
    elif provider == 'hetzner':
        api_token = config_data.get('api_token')
        if not api_token:
            raise ValueError("Hetzner DNS API token required")
            
        config_content = f"dns_hetzner_api_token = {api_token}\n"
        
    elif provider == 'porkbun':
        api_key = config_data.get('api_key')
        secret_key = config_data.get('secret_key')
        if not api_key or not secret_key:
            raise ValueError("Porkbun API key and secret key required")
            
        config_content = f"dns_porkbun_api_key = {api_key}\n"
        config_content += f"dns_porkbun_secret_key = {secret_key}\n"
        
    elif provider == 'godaddy':
        api_key = config_data.get('api_key')
        secret = config_data.get('secret')
        if not api_key or not secret:
            raise ValueError("GoDaddy API key and secret required")
            
        config_content = f"dns_godaddy_key = {api_key}\n"
        config_content += f"dns_godaddy_secret = {secret}\n"
        
    elif provider == 'he-ddns':
        username = config_data.get('username')
        password = config_data.get('password')
        if not username or not password:
            raise ValueError("Hurricane Electric username and password required")
            
        config_content = f"dns_he_ddns_username = {username}\n"
        config_content += f"dns_he_ddns_password = {password}\n"
        
    elif provider == 'dynudns':
        token = config_data.get('token')
        if not token:
            raise ValueError("Dynu API token required")
            
        config_content = f"dns_dynudns_token = {token}\n"
        
    else:
        # This shouldn't happen given our check above, but just in case
        return None
    
    # Write the configuration file
    with open(config_file, 'w') as f:
        f.write(config_content)
    
    # Set proper permissions
    config_file.chmod(0o600)
    return config_file
def get_certificate_info(domain):
    """Get certificate information for a domain"""
    cert_path = CERT_DIR / domain
    if not cert_path.exists():
        return {
            'domain': domain,
            'exists': False,
            'expiry_date': None,
            'days_left': None,
            'days_until_expiry': None,
            'needs_renewal': False,
            'dns_provider': None
        }
    
    cert_file = cert_path / "cert.pem"
    if not cert_file.exists():
        return {
            'domain': domain,
            'exists': False,
            'expiry_date': None,
            'days_left': None,
            'days_until_expiry': None,
            'needs_renewal': False,
            'dns_provider': None
        }
    
    # Get DNS provider info from settings
    settings = load_settings()
    dns_provider = get_domain_dns_provider(domain, settings)
    
    try:
        # Get certificate expiry using openssl
        result = subprocess.run([
            'openssl', 'x509', '-in', str(cert_file), '-noout', '-dates'
        ], capture_output=True, text=True)
        
        if result.returncode == 0:
            lines = result.stdout.strip().split('\n')
            not_after = None
            for line in lines:
                if line.startswith('notAfter='):
                    not_after = line.split('=', 1)[1]
                    break
            
            if not_after:
                # Parse the date
                from datetime import datetime
                try:
                    expiry_date = datetime.strptime(not_after, '%b %d %H:%M:%S %Y %Z')
                    days_left = (expiry_date - datetime.now()).days
                    
                    return {
                        'domain': domain,
                        'exists': True,
                        'expiry_date': expiry_date.strftime('%Y-%m-%d %H:%M:%S'),
                        'days_left': days_left,
                        'days_until_expiry': days_left,
                        'needs_renewal': days_left < 30,
                        'dns_provider': dns_provider
                    }
                except Exception as e:
                    logger.error(f"Error parsing certificate date: {e}")
    except Exception as e:
        logger.error(f"Error getting certificate info: {e}")
    
    return {
        'domain': domain,
        'exists': False,
        'expiry_date': None,
        'days_left': None,
        'days_until_expiry': None,
        'needs_renewal': False,
        'dns_provider': dns_provider
    }

def create_certificate(domain, email, dns_provider=None, dns_config=None):
    """Create SSL certificate using Let's Encrypt with configurable DNS challenge"""
    try:
        # Enhanced input validation
        if not domain or not isinstance(domain, str):
            return False, "Invalid domain provided"
            
        # Validate domain format and security
        is_valid_domain, domain_error = validate_domain(domain)
        if not is_valid_domain:
            return False, f"Domain validation failed: {domain_error}"
        domain = domain_error  # validated domain
        
        # Validate email
        is_valid_email, email_error = validate_email(email)
        if not is_valid_email:
            return False, f"Email validation failed: {email_error}"
        email = email_error  # validated email
        
        # Load settings to get DNS provider configuration
        settings = load_settings()
        
        # Use provided DNS provider or fall back to settings
        if not dns_provider:
            dns_provider = settings.get('dns_provider', 'cloudflare')
        
        if not dns_config:
            dns_config = settings.get('dns_providers', {}).get(dns_provider, {})
        
        # Create config file based on DNS provider
        config_file = None
        dns_plugin = None
        dns_args = []
        
        if dns_provider == 'cloudflare':
            token = dns_config.get('api_token') or settings.get('cloudflare_token', '')  # Backward compatibility
            if not token:
                return False, "Cloudflare API token not configured"
            config_file = create_cloudflare_config(token)
            dns_plugin = 'cloudflare'
            dns_args = ['--dns-cloudflare-credentials', str(config_file), '--dns-cloudflare-propagation-seconds', '60']
            
        elif dns_provider == 'route53':
            access_key = dns_config.get('access_key_id', '')
            secret_key = dns_config.get('secret_access_key', '')
            if not access_key or not secret_key:
                return False, "AWS Route53 credentials not configured"
            config_file = create_route53_config(access_key, secret_key)
            dns_plugin = 'route53'
            dns_args = ['--dns-route53-credentials', str(config_file)]
            
        elif dns_provider == 'azure':
            subscription_id = dns_config.get('subscription_id', '')
            resource_group = dns_config.get('resource_group', '')
            tenant_id = dns_config.get('tenant_id', '')
            client_id = dns_config.get('client_id', '')
            client_secret = dns_config.get('client_secret', '')
            if not all([subscription_id, resource_group, tenant_id, client_id, client_secret]):
                return False, "Azure DNS credentials not fully configured"
            config_file = create_azure_config(subscription_id, resource_group, tenant_id, client_id, client_secret)
            dns_plugin = 'azure'
            dns_args = ['--dns-azure-credentials', str(config_file)]
            
        elif dns_provider == 'google':
            project_id = dns_config.get('project_id', '')
            service_account_key = dns_config.get('service_account_key', '')
            if not project_id or not service_account_key:
                return False, "Google Cloud DNS credentials not configured"
            config_file = create_google_config(project_id, service_account_key)
            dns_plugin = 'google'
            dns_args = ['--dns-google-credentials', str(config_file)]
            
        elif dns_provider == 'powerdns':
            api_url = dns_config.get('api_url', '')
            api_key = dns_config.get('api_key', '')
            if not api_url or not api_key:
                return False, "PowerDNS credentials not configured"
            config_file = create_powerdns_config(api_url, api_key)
            dns_plugin = 'powerdns'
            dns_args = ['--dns-powerdns-credentials', str(config_file)]
            
        elif dns_provider == 'digitalocean':
            api_token = dns_config.get('api_token', '')
            if not api_token:
                return False, "DigitalOcean API token not configured"
            config_file = create_digitalocean_config(api_token)
            dns_plugin = 'digitalocean'
            dns_args = ['--dns-digitalocean-credentials', str(config_file)]
            
        elif dns_provider == 'linode':
            api_key = dns_config.get('api_key', '')
            if not api_key:
                return False, "Linode API key not configured"
            config_file = create_linode_config(api_key)
            dns_plugin = 'linode'
            dns_args = ['--dns-linode-credentials', str(config_file)]
            
        elif dns_provider == 'gandi':
            api_token = dns_config.get('api_token', '')
            if not api_token:
                return False, "Gandi API token not configured"
            config_file = create_gandi_config(api_token)
            dns_plugin = 'gandi'
            dns_args = ['--dns-gandi-credentials', str(config_file)]
            
        elif dns_provider == 'ovh':
            endpoint = dns_config.get('endpoint', '')
            application_key = dns_config.get('application_key', '')
            application_secret = dns_config.get('application_secret', '')
            consumer_key = dns_config.get('consumer_key', '')
            if not all([endpoint, application_key, application_secret, consumer_key]):
                return False, "OVH credentials not fully configured"
            config_file = create_ovh_config(endpoint, application_key, application_secret, consumer_key)
            dns_plugin = 'ovh'
            dns_args = ['--dns-ovh-credentials', str(config_file)]
            
        elif dns_provider == 'namecheap':
            username = dns_config.get('username', '')
            api_key = dns_config.get('api_key', '')
            if not username or not api_key:
                return False, "Namecheap credentials not configured"
            config_file = create_namecheap_config(username, api_key)
            dns_plugin = 'namecheap'
            dns_args = ['--dns-namecheap-credentials', str(config_file)]
            
        else:
            # Try to use individual plugins for additional providers
            if not dns_config:
                return False, f"DNS provider '{dns_provider}' requires configuration"
            
            try:
                config_file = create_multi_provider_config(dns_provider, dns_config)
                if config_file is None:
                    # Provider doesn't have individual plugin - not supported in this version
                    return False, f"DNS provider '{dns_provider}' is not supported. Please use one of the supported providers: cloudflare, route53, azure, google, powerdns, digitalocean, linode, gandi, ovh, namecheap, vultr, dnsmadeeasy, nsone, rfc2136, hetzner, porkbun, godaddy, he-ddns, dynudns"
                
                # Determine the plugin name based on provider
                plugin_map = {
                    'vultr': 'vultr',
                    'dnsmadeeasy': 'dnsmadeeasy',
                    'nsone': 'nsone',
                    'rfc2136': 'rfc2136',
                    'hetzner': 'hetzner',
                    'porkbun': 'porkbun',
                    'godaddy': 'godaddy',
                    'he-ddns': 'he-ddns',
                    'dynudns': 'dynudns'
                }
                
                dns_plugin = plugin_map.get(dns_provider, dns_provider)
                dns_args = [f'--dns-{dns_plugin}-credentials', str(config_file)]
                logger.info(f"Using certbot-dns-{dns_plugin} for provider: {dns_provider}")
                
            except Exception as e:
                logger.error(f"Failed to configure DNS provider {dns_provider}: {e}")
                return False, f"Failed to configure DNS provider '{dns_provider}': {str(e)}"
        
        # Create local directories for certbot
        letsencrypt_dir = Path("letsencrypt")
        config_dir = letsencrypt_dir / "config"
        work_dir = letsencrypt_dir / "work"
        logs_dir = letsencrypt_dir / "logs"
        
        # Create directories if they don't exist
        config_dir.mkdir(parents=True, exist_ok=True)
        work_dir.mkdir(parents=True, exist_ok=True)
        logs_dir.mkdir(parents=True, exist_ok=True)
        
        # Prepare certbot command with local directories
        cmd = [
            'certbot', 'certonly',
            '--config-dir', str(config_dir),
            '--work-dir', str(work_dir),
            '--logs-dir', str(logs_dir),
            f'--dns-{dns_plugin}',
            *dns_args,
            '--email', email,
            '--agree-tos',
            '--non-interactive',
            '--cert-name', domain,
            '-d', domain,
            '-d', f'*.{domain}'  # Include wildcard
        ]
        
        logger.info(f"Creating certificate for {domain} using {dns_provider} DNS provider")
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode == 0:
            # Copy certificates to our directory
            src_dir = config_dir / "live" / domain
            dest_dir = CERT_DIR / domain
            dest_dir.mkdir(exist_ok=True)
            
            # Copy certificate files
            files_to_copy = ['cert.pem', 'chain.pem', 'fullchain.pem', 'privkey.pem']
            for file_name in files_to_copy:
                src_file = src_dir / file_name
                dest_file = dest_dir / file_name
                if src_file.exists():
                    with open(src_file, 'rb') as src, open(dest_file, 'wb') as dest:
                        dest.write(src.read())
            
            logger.info(f"Certificate created successfully for {domain}")
            return True, "Certificate created successfully"
        else:
            error_msg = result.stderr or result.stdout
            logger.error(f"Certificate creation failed: {error_msg}")
            return False, f"Certificate creation failed: {error_msg}"
    
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Exception during certificate creation: {error_msg}")
        return False, f"Exception: {error_msg}"

# Legacy function for backward compatibility
def create_certificate_legacy(domain, email, cloudflare_token):
    """Legacy function for backward compatibility"""
    dns_config = {'api_token': cloudflare_token}
    return create_certificate(domain, email, 'cloudflare', dns_config)

def renew_certificate(domain):
    """Renew a certificate"""
    try:
        cmd = ['certbot', 'renew', '--cert-name', domain, '--quiet']
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode == 0:
            # Copy renewed certificates
            src_dir = Path(f"/etc/letsencrypt/live/{domain}")
            dest_dir = CERT_DIR / domain
            
            files_to_copy = ['cert.pem', 'chain.pem', 'fullchain.pem', 'privkey.pem']
            for file_name in files_to_copy:
                src_file = src_dir / file_name
                dest_file = dest_dir / file_name
                if src_file.exists():
                    with open(src_file, 'rb') as src, open(dest_file, 'wb') as dest:
                        dest.write(src.read())
            
            logger.info(f"Certificate renewed successfully for {domain}")
            return True
        else:
            logger.error(f"Certificate renewal failed for {domain}: {result.stderr}")
            return False
    except Exception as e:
        logger.error(f"Exception during certificate renewal for {domain}: {e}")
        return False

def check_renewals():
    """Check and renew certificates that are about to expire"""
    settings = load_settings()
    if not settings.get('auto_renew', True):
        return
    
    # Migrate settings format if needed
    settings = migrate_domains_format(settings)
    
    logger.info("Checking for certificates that need renewal")
    
    for domain_entry in settings.get('domains', []):
        # Handle both old format (string) and new format (object)
        if isinstance(domain_entry, str):
            domain = domain_entry
        elif isinstance(domain_entry, dict):
            domain = domain_entry.get('domain')
        else:
            continue  # Skip invalid entries
            
        if domain:
            cert_info = get_certificate_info(domain)
            if cert_info and cert_info['needs_renewal']:
                logger.info(f"Renewing certificate for {domain}")
                renew_certificate(domain)

# Schedule renewal check every day at 2 AM (only if scheduler is available)
if scheduler:
    try:
        scheduler.add_job(
            func=check_renewals,
            trigger="cron",
            hour=2,
            minute=0,
            id='renewal_check'
        )
        logger.info("Automatic renewal check scheduled for 2 AM daily")
    except Exception as e:
        logger.error(f"Failed to schedule renewal check: {e}")
else:
    logger.warning("Background scheduler not available - automatic renewals disabled")

# Define API models
# DNS Provider models
cloudflare_model = api.model('CloudflareConfig', {
    'api_token': fields.String(description='Cloudflare API token')
})

route53_model = api.model('Route53Config', {
    'access_key_id': fields.String(description='AWS Access Key ID'),
    'secret_access_key': fields.String(description='AWS Secret Access Key'),
    'region': fields.String(description='AWS Region', default='us-east-1')
})

azure_model = api.model('AzureConfig', {
    'subscription_id': fields.String(description='Azure Subscription ID'),
    'resource_group': fields.String(description='Azure Resource Group'),
    'tenant_id': fields.String(description='Azure Tenant ID'),
    'client_id': fields.String(description='Azure Client ID'),
    'client_secret': fields.String(description='Azure Client Secret')
})

google_model = api.model('GoogleConfig', {
    'project_id': fields.String(description='Google Cloud Project ID'),
    'service_account_key': fields.String(description='Google Service Account JSON Key')
})

powerdns_model = api.model('PowerDNSConfig', {
    'api_url': fields.String(description='PowerDNS API URL'),
    'api_key': fields.String(description='PowerDNS API Key')
})

digitalocean_model = api.model('DigitalOceanConfig', {
    'api_token': fields.String(description='DigitalOcean API token')
})

linode_model = api.model('LinodeConfig', {
    'api_key': fields.String(description='Linode API key')
})

gandi_model = api.model('GandiConfig', {
    'api_token': fields.String(description='Gandi API token')
})

ovh_model = api.model('OvhConfig', {
    'endpoint': fields.String(description='OVH API endpoint'),
    'application_key': fields.String(description='OVH application key'),
    'application_secret': fields.String(description='OVH application secret'),
    'consumer_key': fields.String(description='OVH consumer key')
})

namecheap_model = api.model('NamecheapConfig', {
    'username': fields.String(description='Namecheap username'),
    'api_key': fields.String(description='Namecheap API key')
})

# Tier 3 DNS Providers (Additional individual plugins)
hetzner_model = api.model('HetznerConfig', {
    'api_token': fields.String(description='Hetzner DNS API token')
})

porkbun_model = api.model('PorkbunConfig', {
    'api_key': fields.String(description='Porkbun API key'),
    'secret_key': fields.String(description='Porkbun secret key')
})

godaddy_model = api.model('GoDaddyConfig', {
    'api_key': fields.String(description='GoDaddy API key'),
    'secret': fields.String(description='GoDaddy API secret')
})

he_ddns_model = api.model('HurricaneElectricConfig', {
    'username': fields.String(description='Hurricane Electric username'),
    'password': fields.String(description='Hurricane Electric password')
})

dynudns_model = api.model('DynuConfig', {
    'token': fields.String(description='Dynu API token')
})

# Multi-provider model for certbot-dns-multi (117+ providers)
multi_provider_model = api.model('MultiProviderConfig', {
    'provider': fields.String(description='DNS provider name (e.g., hetzner, porkbun, vultr)'),
    'config': fields.Raw(description='Provider-specific configuration (flexible key-value pairs)')
})

dns_providers_model = api.model('DNSProviders', {
    'cloudflare': fields.Nested(cloudflare_model),
    'route53': fields.Nested(route53_model),
    'azure': fields.Nested(azure_model),
    'google': fields.Nested(google_model),
    'powerdns': fields.Nested(powerdns_model),
    'digitalocean': fields.Nested(digitalocean_model),
    'linode': fields.Nested(linode_model),
    'gandi': fields.Nested(gandi_model),
    'ovh': fields.Nested(ovh_model),
    'namecheap': fields.Nested(namecheap_model),
    'vultr': fields.Nested(linode_model),  # Same API structure as Linode
    'dnsmadeeasy': fields.Nested(digitalocean_model),  # Simple API token
    'nsone': fields.Nested(digitalocean_model),  # Simple API token
    'rfc2136': fields.Nested(powerdns_model),  # Server URL and key
    # Tier 3 providers
    'hetzner': fields.Nested(hetzner_model),
    'porkbun': fields.Nested(porkbun_model),
    'godaddy': fields.Nested(godaddy_model),
    'he-ddns': fields.Nested(he_ddns_model),
    'dynudns': fields.Nested(dynudns_model),
    # Support for any other provider via certbot-dns-multi
    'multi': fields.Raw(description='Configuration for any DNS provider via certbot-dns-multi')
})

certificate_model = api.model('Certificate', {
    'domain': fields.String(required=True, description='Domain name'),
    'exists': fields.Boolean(description='Whether certificate exists'),
    'expiry_date': fields.String(description='Certificate expiry date'),
    'days_left': fields.Integer(description='Days until expiry'),
    'days_until_expiry': fields.Integer(description='Days until expiry (alias for days_left)'),
    'needs_renewal': fields.Boolean(description='Whether certificate needs renewal'),
    'dns_provider': fields.String(description='DNS provider used for the certificate')
})

settings_model = api.model('Settings', {
    'cloudflare_token': fields.String(description='Cloudflare API token (deprecated, use dns_providers)'),
    'domains': fields.List(fields.Raw, description='List of domains (can be strings or objects)'),
    'email': fields.String(description='Email for Let\'s Encrypt'),
    'auto_renew': fields.Boolean(description='Enable auto-renewal'),
    'api_bearer_token': fields.String(description='API bearer token for authentication'),
    'dns_provider': fields.String(description='Active DNS provider', enum=['cloudflare', 'route53', 'azure', 'google', 'powerdns', 'digitalocean', 'linode', 'gandi', 'ovh', 'namecheap', 'vultr', 'dnsmadeeasy', 'nsone', 'rfc2136', 'hetzner', 'porkbun', 'godaddy', 'he-ddns', 'dynudns']),
    'dns_providers': fields.Nested(dns_providers_model, description='DNS provider configurations')
})

create_cert_model = api.model('CreateCertificate', {
    'domain': fields.String(required=True, description='Domain name to create certificate for'),
    'dns_provider': fields.String(description='DNS provider to use (optional, uses default from settings)', enum=['cloudflare', 'route53', 'azure', 'google', 'powerdns', 'digitalocean', 'linode', 'gandi', 'ovh', 'namecheap', 'vultr', 'dnsmadeeasy', 'nsone', 'rfc2136', 'hetzner', 'porkbun', 'godaddy', 'he-ddns', 'dynudns'])
})

# Define namespaces
ns_certificates = Namespace('certificates', description='Certificate operations')
ns_settings = Namespace('settings', description='Settings operations')
ns_health = Namespace('health', description='Health check')

api.add_namespace(ns_certificates)
api.add_namespace(ns_settings)
api.add_namespace(ns_health)

# Health check endpoint
@ns_health.route('')
class HealthCheck(Resource):
    def get(self):
        """Health check endpoint"""
        return {'status': 'healthy', 'timestamp': datetime.now().isoformat()}

# Settings endpoints
@ns_settings.route('')
class Settings(Resource):
    @api.doc(security='Bearer')
    @api.marshal_with(settings_model)
    @require_auth
    def get(self):
        """Get current settings"""
        settings = load_settings()
        # Don't return sensitive data - mask credentials
        safe_settings = {
            'domains': settings.get('domains', []),
            'email': settings.get('email', ''),
            'auto_renew': settings.get('auto_renew', True),
            'dns_provider': settings.get('dns_provider', 'cloudflare'),
            'has_cloudflare_token': bool(settings.get('cloudflare_token')),  # Backward compatibility
            'has_api_bearer_token': bool(settings.get('api_bearer_token')),
            'dns_providers': {}
        }
        
        # Add masked DNS provider info
        dns_providers = settings.get('dns_providers', {})
        for provider, config in dns_providers.items():
            safe_settings['dns_providers'][provider] = {}
            for key, value in config.items():
                # Mask sensitive values
                if value:
                    if key in ['api_token', 'secret_access_key', 'client_secret', 'api_key', 'service_account_key']:
                        safe_settings['dns_providers'][provider][key] = '***masked***'
                    else:
                        safe_settings['dns_providers'][provider][key] = value
                else:
                    safe_settings['dns_providers'][provider][key] = ''
        
        return safe_settings
    
    @api.doc(security='Bearer')
    @api.expect(settings_model)
    @require_auth
    def post(self):
        """Update settings"""
        data = request.get_json()
        settings = load_settings()
        
        # Update basic settings
        if 'cloudflare_token' in data:
            settings['cloudflare_token'] = data['cloudflare_token']
            # Also update the new structure for backward compatibility
            if 'dns_providers' not in settings:
                settings['dns_providers'] = {}
            if 'cloudflare' not in settings['dns_providers']:
                settings['dns_providers']['cloudflare'] = {}
            settings['dns_providers']['cloudflare']['api_token'] = data['cloudflare_token']
            
        if 'domains' in data:
            settings['domains'] = data['domains']
        if 'email' in data:
            settings['email'] = data['email']
        if 'auto_renew' in data:
            settings['auto_renew'] = data['auto_renew']
        if 'api_bearer_token' in data:
            settings['api_bearer_token'] = data['api_bearer_token']
        if 'dns_provider' in data:
            settings['dns_provider'] = data['dns_provider']
        
        # Update DNS provider configurations
        if 'dns_providers' in data:
            if 'dns_providers' not in settings:
                settings['dns_providers'] = {}
            
            for provider, config in data['dns_providers'].items():
                if provider not in settings['dns_providers']:
                    settings['dns_providers'][provider] = {}
                
                # Only update non-masked values
                for key, value in config.items():
                    if value and value != '***masked***':
                        settings['dns_providers'][provider][key] = value
        
        if save_settings(settings):
            return {'success': True, 'message': 'Settings saved successfully'}
        else:
            return {'success': False, 'message': 'Failed to save settings'}, 500

# DNS Providers endpoint
@ns_settings.route('/dns-providers')
class DNSProviders(Resource):
    @api.doc(security='Bearer')
    @require_auth
    def get(self):
        """Get available DNS providers and their configuration status"""
        settings = load_settings()
        dns_providers = settings.get('dns_providers', {})
        current_provider = settings.get('dns_provider', 'cloudflare')
        
        providers_status = {
            'current_provider': current_provider,
            'available_providers': {
                'cloudflare': {
                    'name': 'Cloudflare',
                    'description': 'Cloudflare DNS provider using API tokens',
                    'configured': bool(dns_providers.get('cloudflare', {}).get('api_token') or settings.get('cloudflare_token')),
                    'required_fields': ['api_token']
                },
                'route53': {
                    'name': 'AWS Route53',
                    'description': 'Amazon Web Services Route53 DNS provider',
                    'configured': bool(
                        dns_providers.get('route53', {}).get('access_key_id') and 
                        dns_providers.get('route53', {}).get('secret_access_key')
                    ),
                    'required_fields': ['access_key_id', 'secret_access_key'],
                    'optional_fields': ['region']
                },
                'azure': {
                    'name': 'Azure DNS',
                    'description': 'Microsoft Azure DNS provider',
                    'configured': all([
                        dns_providers.get('azure', {}).get('subscription_id'),
                        dns_providers.get('azure', {}).get('resource_group'),
                        dns_providers.get('azure', {}).get('tenant_id'),
                        dns_providers.get('azure', {}).get('client_id'),
                        dns_providers.get('azure', {}).get('client_secret')
                    ]),
                    'required_fields': ['subscription_id', 'resource_group', 'tenant_id', 'client_id', 'client_secret']
                },
                'google': {
                    'name': 'Google Cloud DNS',
                    'description': 'Google Cloud Platform DNS provider',
                    'configured': bool(
                        dns_providers.get('google', {}).get('project_id') and 
                        dns_providers.get('google', {}).get('service_account_key')
                    ),
                    'required_fields': ['project_id', 'service_account_key']
                },
                'powerdns': {
                    'name': 'PowerDNS',
                    'description': 'PowerDNS API provider',
                    'configured': bool(
                        dns_providers.get('powerdns', {}).get('api_url') and 
                        dns_providers.get('powerdns', {}).get('api_key')
                    ),
                    'required_fields': ['api_url', 'api_key']
                },
                'digitalocean': {
                    'name': 'DigitalOcean',
                    'description': 'DigitalOcean DNS provider',
                    'configured': bool(dns_providers.get('digitalocean', {}).get('api_token')),
                    'required_fields': ['api_token']
                },
                'linode': {
                    'name': 'Linode',
                    'description': 'Linode DNS provider',
                    'configured': bool(dns_providers.get('linode', {}).get('api_key')),
                    'required_fields': ['api_key']
                },
                'gandi': {
                    'name': 'Gandi',
                    'description': 'Gandi DNS provider',
                    'configured': bool(dns_providers.get('gandi', {}).get('api_token')),
                    'required_fields': ['api_token']
                },
                'ovh': {
                    'name': 'OVH',
                    'description': 'OVH DNS provider',
                    'configured': bool(
                        dns_providers.get('ovh', {}).get('endpoint') and 
                        dns_providers.get('ovh', {}).get('application_key') and
                        dns_providers.get('ovh', {}).get('application_secret') and
                        dns_providers.get('ovh', {}).get('consumer_key')
                    ),
                    'required_fields': ['endpoint', 'application_key', 'application_secret', 'consumer_key']
                },
                'namecheap': {
                    'name': 'Namecheap',
                    'description': 'Namecheap DNS provider',
                    'configured': bool(
                        dns_providers.get('namecheap', {}).get('username') and 
                        dns_providers.get('namecheap', {}).get('api_key')
                    ),
                    'required_fields': ['username', 'api_key']
                },
                # RFC2136 and additional individual plugins
                'rfc2136': {
                    'name': 'RFC2136',
                    'description': 'RFC2136 DNS Update Protocol',
                    'configured': bool(
                        dns_providers.get('rfc2136', {}).get('nameserver') and
                        dns_providers.get('rfc2136', {}).get('tsig_key')
                    ),
                    'required_fields': ['nameserver', 'tsig_key', 'tsig_secret'],
                    'optional_fields': ['tsig_algorithm']
                },
                'vultr': {
                    'name': 'Vultr',
                    'description': 'Vultr DNS provider',
                    'configured': bool(dns_providers.get('vultr', {}).get('api_key')),
                    'required_fields': ['api_key']
                },
                'dnsmadeeasy': {
                    'name': 'DNS Made Easy',
                    'description': 'DNS Made Easy provider',
                    'configured': bool(
                        dns_providers.get('dnsmadeeasy', {}).get('api_key') and
                        dns_providers.get('dnsmadeeasy', {}).get('secret_key')
                    ),
                    'required_fields': ['api_key', 'secret_key']
                },
                'nsone': {
                    'name': 'NS1',
                    'description': 'NS1 DNS provider',
                    'configured': bool(dns_providers.get('nsone', {}).get('api_key')),
                    'required_fields': ['api_key']
                }
            }
        }
        
        return providers_status

# Certificate endpoints
@ns_certificates.route('')
class CertificateList(Resource):
    @api.doc(security='Bearer')
    @api.marshal_list_with(certificate_model)
    @require_auth
    def get(self):
        """Get all certificates"""
        settings = load_settings()
        certificates = []
        
        for domain_config in settings.get('domains', []):
            domain_name = domain_config.get('domain') if isinstance(domain_config, dict) else domain_config
            cert_info = get_certificate_info(domain_name)
            if cert_info:
                certificates.append(cert_info)
        
        return certificates

@ns_certificates.route('/create')
class CreateCertificate(Resource):
    @api.doc(security='Bearer')
    @api.expect(create_cert_model)
    @require_auth
    def post(self):
        """Create a new certificate"""
        data = request.get_json()
        domain = data.get('domain')
        dns_provider = data.get('dns_provider')  # Optional, uses default from settings
        
        if not domain:
            return {'success': False, 'message': 'Domain is required'}, 400
        
        settings = load_settings()
        email = settings.get('email')
        
        if not email:
            return {'success': False, 'message': 'Email not configured in settings'}, 400
        
        # Determine DNS provider
        if not dns_provider:
            dns_provider = settings.get('dns_provider', 'cloudflare')
        
        # Validate DNS provider configuration
        dns_providers = settings.get('dns_providers', {})
        dns_config = dns_providers.get(dns_provider, {})
        
        # Check if DNS provider is configured
        provider_configured = False
        if dns_provider == 'cloudflare':
            # Check both new and legacy configuration
            token = dns_config.get('api_token') or settings.get('cloudflare_token', '')
            provider_configured = bool(token)
        elif dns_provider == 'route53':
            provider_configured = bool(dns_config.get('access_key_id') and dns_config.get('secret_access_key'))
        elif dns_provider == 'azure':
            provider_configured = all([
                dns_config.get('subscription_id'),
                dns_config.get('resource_group'),
                dns_config.get('tenant_id'),
                dns_config.get('client_id'),
                dns_config.get('client_secret')
            ])
        elif dns_provider == 'google':
            provider_configured = bool(dns_config.get('project_id') and dns_config.get('service_account_key'))
        elif dns_provider == 'powerdns':
            provider_configured = bool(dns_config.get('api_url') and dns_config.get('api_key'))
        elif dns_provider == 'digitalocean':
            provider_configured = bool(dns_config.get('api_token'))
        elif dns_provider == 'linode':
            provider_configured = bool(dns_config.get('api_key'))
        elif dns_provider == 'gandi':
            provider_configured = bool(dns_config.get('api_token'))
        elif dns_provider == 'ovh':
            provider_configured = bool(
                dns_config.get('endpoint') and 
                dns_config.get('application_key') and
                dns_config.get('application_secret') and
                dns_config.get('consumer_key')
            )
        elif dns_provider == 'namecheap':
            provider_configured = bool(
                dns_config.get('username') and 
                dns_config.get('api_key')
            )
        else:
            # Check for multi-provider configurations (certbot-dns-multi)
            # Check if the DNS provider is configured
            # All supported providers should have their configuration in dns_providers
            supported_providers = [
                'cloudflare', 'route53', 'azure', 'google', 'powerdns',
                'digitalocean', 'linode', 'gandi', 'ovh', 'namecheap',
                'vultr', 'dnsmadeeasy', 'nsone', 'rfc2136'
            ]
            
            if dns_provider in supported_providers:
                # For supported providers, check if they are configured
                provider_configured = bool(dns_config and any(dns_config.values()))
            else:
                # Unsupported provider
                return {'success': False, 'message': f'DNS provider "{dns_provider}" is not supported. Please use one of the supported providers: {", ".join(supported_providers)}'}, 400
        
        if not provider_configured:
            return {'success': False, 'message': f'{dns_provider.title()} DNS provider not configured in settings'}, 400
        
        # Create certificate in background
        def create_cert_async():
            success, message = create_certificate(domain, email, dns_provider, dns_config)
            logger.info(f"Certificate creation for {domain} using {dns_provider}: {'Success' if success else 'Failed'} - {message}")
        
        thread = threading.Thread(target=create_cert_async)
        thread.start()
        
        return {'success': True, 'message': f'Certificate creation started for {domain} using {dns_provider} DNS provider'}

@ns_certificates.route('/<string:domain>/download')
class DownloadCertificate(Resource):
    @api.doc(security='Bearer')
    @require_auth
    def get(self, domain):
        """Download certificate as ZIP file"""
        cert_dir = CERT_DIR / domain
        if not cert_dir.exists():
            return {'error': 'Certificate not found'}, 404
        
        # Create temporary ZIP file
        with tempfile.NamedTemporaryFile(delete=False, suffix='.zip') as tmp_file:
            with zipfile.ZipFile(tmp_file.name, 'w') as zip_file:
                for file_name in ['cert.pem', 'chain.pem', 'fullchain.pem', 'privkey.pem']:
                    file_path = cert_dir / file_name
                    if file_path.exists():
                        zip_file.write(file_path, file_name)
            
            return send_file(tmp_file.name, as_attachment=True, download_name=f'{domain}-certificates.zip')

@ns_certificates.route('/<string:domain>/renew')
class RenewCertificate(Resource):
    @api.doc(security='Bearer')
    @require_auth
    def post(self, domain):
        """Renew a certificate"""
        settings = load_settings()
        
        # Check if domain exists in settings
        domain_exists = False
        for domain_config in settings.get('domains', []):
            if isinstance(domain_config, dict) and domain_config.get('domain') == domain:
                domain_exists = True
                break
            elif isinstance(domain_config, str) and domain_config == domain:
                domain_exists = True
                break
        
        if not domain_exists:
            return {'success': False, 'message': 'Domain not found in settings'}, 404
        
        # Renew certificate in background
        def renew_cert_async():
            success = renew_certificate(domain)
            logger.info(f"Certificate renewal for {domain}: {'Success' if success else 'Failed'}")
        
        thread = threading.Thread(target=renew_cert_async)
        thread.start()
        
        return {'success': True, 'message': f'Certificate renewal started for {domain}'}

# Special download endpoint for easy automation
@app.route('/<string:domain>/tls')
@require_auth
def download_tls(domain):
    """Download certificate via simple URL with bearer token auth"""
    cert_dir = CERT_DIR / domain
    if not cert_dir.exists():
        return jsonify({'error': 'Certificate not found'}), 404
    
    # Create temporary ZIP file
    with tempfile.NamedTemporaryFile(delete=False, suffix='.zip') as tmp_file:
        with zipfile.ZipFile(tmp_file.name, 'w') as zip_file:
            for file_name in ['cert.pem', 'chain.pem', 'fullchain.pem', 'privkey.pem']:
                file_path = cert_dir / file_name
                if file_path.exists():
                    zip_file.write(file_path, file_name)
        
        return send_file(tmp_file.name, as_attachment=True, download_name=f'{domain}-tls.zip')

# Configure API security
api.authorizations = {
    'Bearer': {
        'type': 'apiKey',
        'in': 'header',
        'name': 'Authorization',
        'description': 'Add "Bearer " before your token'
    }
}

# Web interface routes
@app.route('/')
def index():
    """Main dashboard"""
    settings = load_settings()
    certificates = []
    
    for domain_config in settings.get('domains', []):
        domain_name = domain_config.get('domain') if isinstance(domain_config, dict) else domain_config
        cert_info = get_certificate_info(domain_name)
        if cert_info:
            certificates.append(cert_info)
    
    # Get API token for frontend use
    api_token = settings.get('api_bearer_token', 'token-not-configured')
    return render_template('index.html', certificates=certificates, api_token=api_token)

@app.route('/settings')
def settings_page():
    """Settings page"""
    settings = load_settings()
    # Get API token for frontend use
    api_token = settings.get('api_bearer_token', 'token-not-configured')
    return render_template('settings.html', settings=settings, api_token=api_token)

@app.route('/help')
def help_page():
    """Help and documentation page"""
    return render_template('help.html')

# Health check for Docker
@app.route('/health')
def health_check():
    """Enhanced health check endpoint for Docker and monitoring"""
    try:
        status = 'healthy'
        checks = {}
        
        # Check directory access
        checks['directories'] = {
            'cert_dir_writable': os.access(CERT_DIR, os.W_OK),
            'data_dir_writable': os.access(DATA_DIR, os.W_OK)
        }
        
        # Check settings file
        checks['settings'] = {
            'file_exists': SETTINGS_FILE.exists(),
            'readable': SETTINGS_FILE.exists() and os.access(SETTINGS_FILE, os.R_OK)
        }
        
        # Check scheduler
        checks['scheduler'] = {
            'available': scheduler is not None,
            'running': scheduler.running if scheduler else False
        }
        
        # Determine overall status
        if not all([
            checks['directories']['cert_dir_writable'],
            checks['directories']['data_dir_writable'],
            checks['settings']['readable']
        ]):
            status = 'degraded'
            
        return jsonify({
            'status': status,
            'timestamp': datetime.now().isoformat(),
            'checks': checks
        })
        
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return jsonify({
            'status': 'unhealthy',
            'timestamp': datetime.now().isoformat(),
            'error': str(e)
        }), 500

# Web-specific settings endpoints (no auth required for initial setup)
@app.route('/api/web/settings', methods=['GET', 'POST'])
def web_settings():
    """Web interface settings endpoint (no auth required for initial setup)"""
    if request.method == 'GET':
        settings = load_settings()
        # Don't return sensitive data
        safe_settings = {
            'domains': settings.get('domains', []),
            'email': settings.get('email', ''),
            'auto_renew': settings.get('auto_renew', True),
            'has_cloudflare_token': bool(settings.get('cloudflare_token')),
            'has_api_bearer_token': bool(settings.get('api_bearer_token'))
        }
        return jsonify(safe_settings)
    
    elif request.method == 'POST':
        data = request.get_json()
        settings = load_settings()
        
        # Update settings
        if 'cloudflare_token' in data and data['cloudflare_token']:
            settings['cloudflare_token'] = data['cloudflare_token']
        if 'domains' in data:
            settings['domains'] = data['domains']
        if 'email' in data:
            settings['email'] = data['email']
        if 'auto_renew' in data:
            settings['auto_renew'] = data['auto_renew']
        if 'api_bearer_token' in data and data['api_bearer_token']:
            settings['api_bearer_token'] = data['api_bearer_token']
        
        if save_settings(settings):
            return jsonify({'success': True, 'message': 'Settings saved successfully'})
        else:
            return jsonify({'success': False, 'message': 'Failed to save settings'}), 500

# Web-specific certificates endpoint (no auth required for initial setup)
@app.route('/api/web/certificates')
def web_certificates():
    """Web interface certificates endpoint (no auth required)"""
    settings = load_settings()
    
    # Migrate settings format if needed
    settings = migrate_domains_format(settings)
    
    certificates = []
    
    for domain_entry in settings.get('domains', []):
        # Handle both old format (string) and new format (object)
        if isinstance(domain_entry, str):
            domain = domain_entry
        elif isinstance(domain_entry, dict):
            domain = domain_entry.get('domain')
        else:
            continue  # Skip invalid entries
            
        if domain:
            cert_info = get_certificate_info(domain)
            certificates.append(cert_info)
    
    return jsonify(certificates)

@app.route('/api/web/certificates/create', methods=['POST'])
def web_create_certificate():
    """Web interface create certificate endpoint (no auth required)"""
    data = request.get_json()
    domain = data.get('domain')
    dns_provider_override = data.get('dns_provider')  # Optional DNS provider override
    
    if not domain:
        return jsonify({'success': False, 'message': 'Domain is required'}), 400
    
    settings = load_settings()
    
    # Migrate settings format if needed
    settings = migrate_domains_format(settings) 
    
    email = settings.get('email')
    
    if not email:
        return jsonify({'success': False, 'message': 'Email not configured in settings'}), 400
    
    # Determine DNS provider to use
    dns_provider = dns_provider_override or settings.get('dns_provider', 'cloudflare')
    
    # Validate DNS provider configuration
    dns_config = settings.get('dns_providers', {}).get(dns_provider, {})
    
    if dns_provider == 'cloudflare':
        # Support legacy cloudflare_token setting
        token = dns_config.get('api_token') or settings.get('cloudflare_token', '')
        if not token:
            return jsonify({'success': False, 'message': f'{dns_provider.title()} token not configured in settings'}), 400
        dns_config = {'api_token': token}
    elif dns_provider == 'route53':
        if not dns_config.get('access_key_id') or not dns_config.get('secret_access_key'):
            return jsonify({'success': False, 'message': 'AWS Route53 credentials not configured in settings'}), 400
    elif dns_provider == 'azure':
        required_fields = ['subscription_id', 'resource_group', 'tenant_id', 'client_id', 'client_secret']
        if not all(dns_config.get(field) for field in required_fields):
            return jsonify({'success': False, 'message': 'Azure DNS credentials not configured in settings'}), 400
    elif dns_provider == 'google':
        if not dns_config.get('credentials_file') and not dns_config.get('credentials_json'):
            return jsonify({'success': False, 'message': 'Google Cloud DNS credentials not configured in settings'}), 400
    elif dns_provider == 'powerdns':
        if not dns_config.get('api_url') or not dns_config.get('api_key'):
            return jsonify({'success': False, 'message': 'PowerDNS API credentials not configured in settings'}), 400
    elif dns_provider == 'digitalocean':
        if not dns_config.get('api_token'):
            return jsonify({'success': False, 'message': 'DigitalOcean API token not configured in settings'}), 400
    elif dns_provider == 'linode':
        if not dns_config.get('api_key'):
            return jsonify({'success': False, 'message': 'Linode API key not configured in settings'}), 400
    elif dns_provider == 'gandi':
        if not dns_config.get('api_token'):
            return jsonify({'success': False, 'message': 'Gandi API token not configured in settings'}), 400
    elif dns_provider == 'ovh':
        if not all(dns_config.get(field) for field in ['endpoint', 'application_key', 'application_secret', 'consumer_key']):
            return jsonify({'success': False, 'message': 'OVH credentials not fully configured in settings'}), 400
    elif dns_provider == 'namecheap':
        if not all(dns_config.get(field) for field in ['username', 'api_key']):
            return jsonify({'success': False, 'message': 'Namecheap credentials not fully configured in settings'}), 400
    
    # Add domain to settings if not already there (using new format)
    domains = settings.get('domains', [])
    domain_exists = False
    
    for domain_entry in domains:
        if isinstance(domain_entry, str):
            if domain_entry == domain:
                domain_exists = True
                break
        elif isinstance(domain_entry, dict):
            if domain_entry.get('domain') == domain:
                domain_exists = True
                # Update DNS provider if it changed
                if domain_entry.get('dns_provider') != dns_provider:
                    domain_entry['dns_provider'] = dns_provider
                break
    
    if not domain_exists:
        domains.append({
            'domain': domain,
            'dns_provider': dns_provider
        })
        settings['domains'] = domains
        save_settings(settings)
    
    # Create certificate using new multi-provider function
    success, message = create_certificate(domain, email, dns_provider, dns_config)
    logger.info(f"Certificate creation for {domain} using {dns_provider}: {'Success' if success else 'Failed'} - {message}")
    
    if success:
        return jsonify({'success': True, 'message': message})
    else:
        return jsonify({'success': False, 'message': message}), 500

@app.route('/api/web/certificates/<domain>/renew', methods=['POST'])
def web_renew_certificate(domain):
    """Web interface renew certificate endpoint (no auth required)"""
    settings = load_settings()
    
    # Migrate settings format if needed
    settings = migrate_domains_format(settings)
    
    # Check if domain exists in settings (handle both old and new formats)
    domain_found = False
    for domain_entry in settings.get('domains', []):
        if isinstance(domain_entry, str):
            if domain_entry == domain:
                domain_found = True
                break
        elif isinstance(domain_entry, dict):
            if domain_entry.get('domain') == domain:
                domain_found = True
                break
    
    if not domain_found:
        return jsonify({'success': False, 'message': 'Domain not found in settings'}), 404
    
    # Renew certificate in background
    def renew_cert_async():
        success = renew_certificate(domain)
        logger.info(f"Certificate renewal for {domain}: {'Success' if success else 'Failed'}")
    
    thread = threading.Thread(target=renew_cert_async)
    thread.start()
    
    return jsonify({'success': True, 'message': f'Certificate renewal started for {domain}'})

@app.route('/api/web/certificates/<domain>/download')
def web_download_certificate(domain):
    """Web interface download certificate endpoint (no auth required)"""
    cert_dir = CERT_DIR / domain
    if not cert_dir.exists():
        return jsonify({'error': 'Certificate not found'}), 404
    
    # Create temporary ZIP file
    with tempfile.NamedTemporaryFile(delete=False, suffix='.zip') as tmp_file:
        with zipfile.ZipFile(tmp_file.name, 'w') as zip_file:
            for file_name in ['cert.pem', 'chain.pem', 'fullchain.pem', 'privkey.pem']:
                file_path = cert_dir / file_name
                if file_path.exists():
                    zip_file.write(file_path, file_name)
        
        return send_file(tmp_file.name, as_attachment=True, download_name=f'{domain}-certificates.zip')

def check_ssl_certificate(domain, port=443, timeout=10):
    """Check SSL certificate for a domain"""
    try:
        # Create SSL context
        context = ssl.create_default_context()
        
        # Connect to the domain
        with socket.create_connection((domain, port), timeout=timeout) as sock:
            with context.wrap_socket(sock, server_hostname=domain) as ssock:
                # Get certificate info
                cert_der = ssock.getpeercert(binary_form=True)
                cert = x509.load_der_x509_certificate(cert_der, default_backend())
                
                # Check if certificate is valid for this domain
                san_extension = None
                try:
                    san_extension = cert.extensions.get_extension_for_oid(x509.oid.ExtensionOID.SUBJECT_ALTERNATIVE_NAME)
                    san_names = [name.value for name in san_extension.value]
                except:
                    san_names = []
                
                # Get subject common name
                subject_cn = None
                for attribute in cert.subject:
                    if attribute.oid == x509.oid.NameOID.COMMON_NAME:
                        subject_cn = attribute.value
                        break
                
                # Check if domain matches certificate
                certificate_domains = []
                if subject_cn:
                    certificate_domains.append(subject_cn)
                certificate_domains.extend(san_names)
                
                domain_match = any(
                    domain == cert_domain or 
                    (cert_domain.startswith('*.') and domain.endswith(cert_domain[2:]))
                    for cert_domain in certificate_domains
                )
                
                return {
                    'deployed': True,
                    'reachable': True,
                    'certificate_match': domain_match,
                    'certificate_domains': certificate_domains,
                    'issuer': cert.issuer.rfc4514_string(),
                    'expires_at': cert.not_valid_after_utc.isoformat(),
                    'method': 'ssl-direct',
                    'timestamp': datetime.now().isoformat()
                }
                
    except socket.timeout:
        return {
            'deployed': False,
            'reachable': False,
            'certificate_match': False,
            'error': 'timeout',
            'method': 'ssl-direct',
            'timestamp': datetime.now().isoformat()
        }
    except socket.gaierror:
        return {
            'deployed': False,
            'reachable': False,
            'certificate_match': False,
            'error': 'dns_resolution_failed',
            'method': 'ssl-direct',
            'timestamp': datetime.now().isoformat()
        }
    except ssl.SSLError as e:
        return {
            'deployed': False,
            'reachable': True,
            'certificate_match': False,
            'error': f'ssl_error: {str(e)}',
            'method': 'ssl-direct',
            'timestamp': datetime.now().isoformat()
        }
    except Exception as e:
        return {
            'deployed': False,
            'reachable': False,
            'certificate_match': False,
            'error': f'unknown: {str(e)}',
            'method': 'ssl-direct',
            'timestamp': datetime.now().isoformat()
        }

@ns_certificates.route('/<string:domain>/deployment-status')
class CertificateDeploymentStatus(Resource):
    def get(self, domain):
        """Check deployment status of a certificate for a domain"""
        try:
            logger.info(f"Checking deployment status for domain: {domain}")
            
            # Check SSL certificate deployment
            deployment_status = check_ssl_certificate(domain)
            
            # If we have a certificate for this domain, compare with deployed cert
            cert_dir = CERT_DIR / domain
            if cert_dir.exists():
                cert_file = cert_dir / "cert.pem"
                if cert_file.exists():
                    try:
                        # Load our certificate
                        with open(cert_file, 'rb') as f:
                            our_cert = x509.load_pem_x509_certificate(f.read(), default_backend())
                        
                        # If the domain has SSL but doesn't match, check if it's our certificate
                        if deployment_status['reachable'] and not deployment_status['certificate_match']:
                            # Additional verification - check certificate fingerprints or other identifiers
                            deployment_status['has_local_cert'] = True
                            deployment_status['local_cert_expires'] = our_cert.not_valid_after_utc.isoformat()
                        else:
                            deployment_status['has_local_cert'] = True
                            deployment_status['local_cert_expires'] = our_cert.not_valid_after_utc.isoformat()
                            
                    except Exception as e:
                        logger.error(f"Error reading local certificate for {domain}: {e}")
                        deployment_status['has_local_cert'] = False
                else:
                    deployment_status['has_local_cert'] = False
            else:
                deployment_status['has_local_cert'] = False
            
            return deployment_status
            
        except Exception as e:
            logger.error(f"Error checking deployment status for {domain}: {e}")
            return {
                'deployed': False,
                'reachable': False,
                'certificate_match': False,
                'error': f'check_failed: {str(e)}',
                'method': 'ssl-direct',
                'timestamp': datetime.now().isoformat()
            }, 500

def get_domain_dns_provider(domain, settings):
    """Get the DNS provider used for a specific domain"""
    domains = settings.get('domains', [])
    
    # Handle both old format (list of strings) and new format (list of objects)
    for domain_entry in domains:
        if isinstance(domain_entry, str):
            # Old format - just domain name, use default provider
            if domain_entry == domain:
                return settings.get('dns_provider', 'cloudflare')
        elif isinstance(domain_entry, dict):
            # New format - domain object with provider info
            if domain_entry.get('domain') == domain:
                return domain_entry.get('dns_provider', settings.get('dns_provider', 'cloudflare'))
    
    # If domain not found, return default provider
    return settings.get('dns_provider', 'cloudflare')

def migrate_domains_format(settings):
    """Migrate domains from old format (list of strings) to new format (list of objects)"""
    domains = settings.get('domains', [])
    migrated_domains = []
    needs_migration = False
    
    for domain_entry in domains:
        if isinstance(domain_entry, str):
            # Old format - convert to new format
            migrated_domains.append({
                'domain': domain_entry,
                'dns_provider': settings.get('dns_provider', 'cloudflare')
            })
            needs_migration = True
        elif isinstance(domain_entry, dict):
            # Already new format
            migrated_domains.append(domain_entry)
        else:
            # Invalid format, skip
            logger.warning(f"Invalid domain entry format: {domain_entry}")
    
    if needs_migration:
        settings['domains'] = migrated_domains
        save_settings(settings)
        logger.info("Migrated domains to new format")
    
    return settings

# Input validation utilities
def validate_domain(domain):
    """Validate domain name format and security"""
    if not domain or not isinstance(domain, str):
        return False, "Domain must be a non-empty string"
    
    domain = domain.strip().lower()
    
    # Basic format validation
    domain_pattern = r'^[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$'
    if not re.match(domain_pattern, domain):
        return False, "Invalid domain format"
    
    # Length checks
    if len(domain) > 253:
        return False, "Domain name too long"
    
    # Check for dangerous characters
    if any(char in domain for char in [' ', '\n', '\r', '\t', ';', '&', '|', '`']):
        return False, "Domain contains invalid characters"
    
    return True, domain

def validate_email(email):
    """Validate email format"""
    if not email or not isinstance(email, str):
        return False, "Email must be a non-empty string"
    
    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    if not re.match(email_pattern, email.strip()):
        return False, "Invalid email format"
    
    return True, email.strip().lower()

def validate_api_token(token):
    """Validate API token strength"""
    if not token or not isinstance(token, str):
        return False, "Token must be a non-empty string"
    
    if len(token) < 32:
        return False, "Token must be at least 32 characters long"
    
    if token in ['change-this-token', 'certmate-api-token-12345']:
        return False, "Please use a secure, unique token"
    
    return True, token

def generate_secure_token():
    """Generate a cryptographically secure token"""
    return secrets.token_urlsafe(32)

# File locking utilities
def safe_file_write(file_path, content, mode='w'):
    """Safely write to file with locking"""
    try:
        with open(file_path, mode) as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            if isinstance(content, dict):
                json.dump(content, f, indent=2)
            else:
                f.write(content)
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        return True
    except Exception as e:
        logger.error(f"Error writing to {file_path}: {e}")
        return False

def safe_file_read(file_path, is_json=True):
    """Safely read from file with locking"""
    try:
        with open(file_path, 'r') as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_SH)
            content = json.load(f) if is_json else f.read()
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        return content
    except Exception as e:
        logger.error(f"Error reading from {file_path}: {e}")
        return None

def is_setup_completed():
    """Check if initial setup has been completed"""
    settings = load_settings()
    return (
        settings.get('setup_completed', False) or
        (settings.get('email') and 
         settings.get('domains') and 
         len(settings.get('domains', [])) > 0)
    )

def require_setup_or_auth(f):
    """Allow access during setup OR with valid auth"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not is_setup_completed():
            # Allow access during initial setup
            return f(*args, **kwargs)
        else:
            # Require authentication after setup
            return require_auth(f)(*args, **kwargs)
    return decorated_function

# Graceful shutdown for scheduler
def shutdown_scheduler():
    """Gracefully shutdown the background scheduler"""
    if scheduler:
        try:
            scheduler.shutdown(wait=True)
            logger.info("Background scheduler shut down gracefully")
        except Exception as e:
            logger.error(f"Error shutting down scheduler: {e}")

# Register shutdown handler
atexit.register(shutdown_scheduler)

if __name__ == '__main__':
    host = os.getenv('HOST', '127.0.0.1')
    port = int(os.getenv('PORT', 8000))
    debug = os.getenv('FLASK_DEBUG', 'False').lower() == 'true'
    
    print(f"Starting CertMate on http://{host}:{port}")
    app.run(host=host, port=port, debug=debug)
