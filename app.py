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
        'api_bearer_token': os.getenv('API_BEARER_TOKEN', 'change-this-token')
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
    config_dir = Path.home() / ".secrets"
    config_dir.mkdir(exist_ok=True)
    
    config_file = config_dir / "cloudflare.ini"
    with open(config_file, 'w') as f:
        f.write(f"dns_cloudflare_api_token = {token}\n")
    
    # Set proper permissions
    os.chmod(config_file, 0o600)
    return config_file

def get_certificate_info(domain):
    """Get certificate information for a domain"""
    cert_path = CERT_DIR / domain
    if not cert_path.exists():
        return None
    
    cert_file = cert_path / "cert.pem"
    if not cert_file.exists():
        return None
    
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
                        'expiry_date': expiry_date.strftime('%Y-%m-%d %H:%M:%S'),
                        'days_left': days_left,
                        'needs_renewal': days_left < 30
                    }
                except Exception as e:
                    logger.error(f"Error parsing certificate date: {e}")
    except Exception as e:
        logger.error(f"Error getting certificate info: {e}")
    
    return None

def create_certificate(domain, email, cloudflare_token):
    """Create SSL certificate using Let's Encrypt and Cloudflare DNS challenge"""
    try:
        # Create Cloudflare config
        config_file = create_cloudflare_config(cloudflare_token)
        
        # Prepare certbot command
        cmd = [
            'certbot', 'certonly',
            '--dns-cloudflare',
            '--dns-cloudflare-credentials', str(config_file),
            '--dns-cloudflare-propagation-seconds', '60',
            '--email', email,
            '--agree-tos',
            '--non-interactive',
            '--cert-name', domain,
            '-d', domain,
            '-d', f'*.{domain}'  # Include wildcard
        ]
        
        logger.info(f"Creating certificate for {domain}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode == 0:
            # Copy certificates to our directory
            src_dir = Path(f"/etc/letsencrypt/live/{domain}")
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
    
    logger.info("Checking for certificates that need renewal")
    
    for domain in settings.get('domains', []):
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
certificate_model = api.model('Certificate', {
    'domain': fields.String(required=True, description='Domain name'),
    'expiry_date': fields.String(description='Certificate expiry date'),
    'days_left': fields.Integer(description='Days until expiry'),
    'needs_renewal': fields.Boolean(description='Whether certificate needs renewal')
})

settings_model = api.model('Settings', {
    'cloudflare_token': fields.String(description='Cloudflare API token'),
    'domains': fields.List(fields.String, description='List of domains'),
    'email': fields.String(description='Email for Let\'s Encrypt'),
    'auto_renew': fields.Boolean(description='Enable auto-renewal'),
    'api_bearer_token': fields.String(description='API bearer token for authentication')
})

create_cert_model = api.model('CreateCertificate', {
    'domain': fields.String(required=True, description='Domain name to create certificate for')
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
        # Don't return sensitive data
        safe_settings = {
            'domains': settings.get('domains', []),
            'email': settings.get('email', ''),
            'auto_renew': settings.get('auto_renew', True),
            'has_cloudflare_token': bool(settings.get('cloudflare_token')),
            'has_api_bearer_token': bool(settings.get('api_bearer_token'))
        }
        return safe_settings
    
    @api.doc(security='Bearer')
    @api.expect(settings_model)
    @require_auth
    def post(self):
        """Update settings"""
        data = request.get_json()
        settings = load_settings()
        
        # Update settings
        if 'cloudflare_token' in data:
            settings['cloudflare_token'] = data['cloudflare_token']
        if 'domains' in data:
            settings['domains'] = data['domains']
        if 'email' in data:
            settings['email'] = data['email']
        if 'auto_renew' in data:
            settings['auto_renew'] = data['auto_renew']
        if 'api_bearer_token' in data:
            settings['api_bearer_token'] = data['api_bearer_token']
        
        if save_settings(settings):
            return {'success': True, 'message': 'Settings saved successfully'}
        else:
            return {'success': False, 'message': 'Failed to save settings'}, 500

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
        
        for domain in settings.get('domains', []):
            cert_info = get_certificate_info(domain)
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
        
        if not domain:
            return {'success': False, 'message': 'Domain is required'}, 400
        
        settings = load_settings()
        email = settings.get('email')
        cloudflare_token = settings.get('cloudflare_token')
        
        if not email:
            return {'success': False, 'message': 'Email not configured in settings'}, 400
        
        if not cloudflare_token:
            return {'success': False, 'message': 'Cloudflare token not configured in settings'}, 400
        
        # Create certificate in background
        def create_cert_async():
            success, message = create_certificate(domain, email, cloudflare_token)
            logger.info(f"Certificate creation for {domain}: {'Success' if success else 'Failed'} - {message}")
        
        thread = threading.Thread(target=create_cert_async)
        thread.start()
        
        return {'success': True, 'message': f'Certificate creation started for {domain}'}

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
    
    for domain in settings.get('domains', []):
        cert_info = get_certificate_info(domain)
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

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=8000)
