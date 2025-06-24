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

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'your-secret-key-here')
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

# Directories
CERT_DIR = Path("certificates")
DATA_DIR = Path("data")
CERT_DIR.mkdir(exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)

# Settings file
SETTINGS_FILE = DATA_DIR / "settings.json"

# Initialize scheduler
scheduler = BackgroundScheduler()
scheduler.start()

def load_settings():
    """Load settings from file"""
    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading settings: {e}")
    return {
        'cloudflare_token': '',
        'domains': [],
        'email': '',
        'auto_renew': True,
        'api_bearer_token': os.getenv('API_BEARER_TOKEN', 'change-this-token'),
        # DNS provider settings
        'dns_provider': 'cloudflare',  # Default to cloudflare for backward compatibility
        'dns_providers': {
            'cloudflare': {
                'api_token': ''
            },
            'route53': {
                'access_key_id': '',
                'secret_access_key': '',
                'region': 'us-east-1'
            },
            'azure': {
                'subscription_id': '',
                'resource_group': '',
                'tenant_id': '',
                'client_id': '',
                'client_secret': ''
            },
            'google': {
                'project_id': '',
                'service_account_key': ''  # JSON key content
            },
            'powerdns': {
                'api_url': '',
                'api_key': ''
            }
        }
    }

def save_settings(settings):
    """Save settings to file"""
    try:
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(settings, f, indent=2)
        return True
    except Exception as e:
        logger.error(f"Error saving settings: {e}")
        return False

def require_auth(f):
    """Decorator to require bearer token authentication"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        if not auth_header:
            return {'error': 'Authorization header required'}, 401
        
        try:
            scheme, token = auth_header.split(' ', 1)
            if scheme.lower() != 'bearer':
                return {'error': 'Invalid authorization scheme'}, 401
        except ValueError:
            return {'error': 'Invalid authorization header format'}, 401
        
        settings = load_settings()
        expected_token = settings.get('api_bearer_token', os.getenv('API_BEARER_TOKEN', 'change-this-token'))
        
        if token != expected_token:
            return {'error': 'Invalid token'}, 401
        
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

def get_certificate_info(domain):
    """Get certificate information for a domain"""
    cert_path = CERT_DIR / domain
    if not cert_path.exists():
        return {
            'domain': domain,
            'exists': False,
            'expiry_date': None,
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
        'days_until_expiry': None,
        'needs_renewal': False,
        'dns_provider': dns_provider
    }

def create_certificate(domain, email, dns_provider=None, dns_config=None):
    """Create SSL certificate using Let's Encrypt with configurable DNS challenge"""
    try:
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
            
        else:
            return False, f"Unsupported DNS provider: {dns_provider}"
        
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

# Schedule renewal check every day at 2 AM
scheduler.add_job(
    func=check_renewals,
    trigger="cron",
    hour=2,
    minute=0,
    id='renewal_check'
)

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

dns_providers_model = api.model('DNSProviders', {
    'cloudflare': fields.Nested(cloudflare_model),
    'route53': fields.Nested(route53_model),
    'azure': fields.Nested(azure_model),
    'google': fields.Nested(google_model),
    'powerdns': fields.Nested(powerdns_model)
})

certificate_model = api.model('Certificate', {
    'domain': fields.String(required=True, description='Domain name'),
    'expiry_date': fields.String(description='Certificate expiry date'),
    'days_left': fields.Integer(description='Days until expiry'),
    'needs_renewal': fields.Boolean(description='Whether certificate needs renewal')
})

settings_model = api.model('Settings', {
    'cloudflare_token': fields.String(description='Cloudflare API token (deprecated, use dns_providers)'),
    'domains': fields.List(fields.String, description='List of domains'),
    'email': fields.String(description='Email for Let\'s Encrypt'),
    'auto_renew': fields.Boolean(description='Enable auto-renewal'),
    'api_bearer_token': fields.String(description='API bearer token for authentication'),
    'dns_provider': fields.String(description='Active DNS provider', enum=['cloudflare', 'route53', 'azure', 'google', 'powerdns']),
    'dns_providers': fields.Nested(dns_providers_model, description='DNS provider configurations')
})

create_cert_model = api.model('CreateCertificate', {
    'domain': fields.String(required=True, description='Domain name to create certificate for'),
    'dns_provider': fields.String(description='DNS provider to use (optional, uses default from settings)', enum=['cloudflare', 'route53', 'azure', 'google', 'powerdns'])
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
        
        if domain not in settings.get('domains', []):
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
    
    return render_template('index.html', certificates=certificates)

@app.route('/settings')
def settings_page():
    """Settings page"""
    settings = load_settings()
    return render_template('settings.html', settings=settings)

# Health check for Docker
@app.route('/health')
def health_check():
    """Health check endpoint for Docker"""
    return jsonify({'status': 'healthy', 'timestamp': datetime.now().isoformat()})

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

if __name__ == '__main__':
    host = os.getenv('HOST', '127.0.0.1')
    port = int(os.getenv('PORT', 8000))
    debug = os.getenv('FLASK_DEBUG', 'False').lower() == 'true'
    
    print(f"Starting CertMate on http://{host}:{port}")
    app.run(host=host, port=port, debug=debug)
