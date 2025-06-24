# CertMate - Enhanced SSL Certificate Management System

CertMate is a comprehensive SSL certificate management system with Docker support, REST API, and **multi-DNS provider support**. Perfect for managing certificates across multiple datacenters with support for **Cloudflare, AWS Route53, Azure DNS, Google Cloud DNS, and PowerDNS**.

## Screenshots

![screenshot1](https://github.com/fabriziosalmi/certmate/blob/main/screenshot_1.png?raw=true)
![screenshot2](https://github.com/fabriziosalmi/certmate/blob/main/screenshot_2.png?raw=true)

## Features

- 🔐 **SSL Certificate Management** - Create, renew, and manage Let's Encrypt certificates
- 🌐 **Multi-DNS Provider Support** - Cloudflare, AWS Route53, Azure DNS, Google Cloud DNS, PowerDNS
- 🔄 **Auto-Renewal** - Certificates are automatically renewed 30 days before expiry
- 🐳 **Docker Support** - Complete containerization with Docker Compose
- 🚀 **REST API** - Full API with Bearer token authentication
- 📚 **Swagger/ReDoc** - Automatic API documentation
- 📦 **Easy Downloads** - Simple URL-based certificate downloads for automation
- 🎨 **Modern UI** - Clean, responsive web interface with Tailwind CSS
- 🔒 **Security** - Bearer token authentication for all API endpoints
- 🔄 **Backward Compatible** - Existing Cloudflare configurations work seamlessly

## Supported DNS Providers

| Provider | Certbot Plugin | Required Credentials | Status |
|----------|---------------|---------------------|---------|
| **Cloudflare** | `certbot-dns-cloudflare==4.1.1` | API Token | ✅ Stable |
| **AWS Route53** | `certbot-dns-route53==4.1.1` | Access Key ID, Secret Access Key | ✅ Stable |
| **Azure DNS** | `certbot-dns-azure==2.6.1` | Subscription ID, Resource Group, Tenant ID, Client ID, Client Secret | ✅ Stable |
| **Google Cloud DNS** | `certbot-dns-google==4.1.1` | Project ID, Service Account JSON Key | ✅ Stable |
| **PowerDNS** | `certbot-dns-powerdns==0.2.1` | API URL, API Key | ✅ Stable |

> 📚 **Documentation:** See [DNS_PROVIDERS.md](DNS_PROVIDERS.md) for detailed configuration instructions.  
> 🔧 **Installation:** See [INSTALLATION.md](INSTALLATION.md) for step-by-step setup guide.

## Quick Start with Docker

### 1. Environment Setup

Create a `.env` file:

```bash
# Required settings
API_BEARER_TOKEN=your_secure_api_token_here

# DNS Provider (choose one or multiple)
CLOUDFLARE_TOKEN=your_cloudflare_api_token_here
# OR
AWS_ACCESS_KEY_ID=your_aws_access_key
AWS_SECRET_ACCESS_KEY=your_aws_secret_key
# OR
AZURE_SUBSCRIPTION_ID=your_azure_subscription_id
AZURE_RESOURCE_GROUP=your_resource_group
AZURE_TENANT_ID=your_tenant_id
AZURE_CLIENT_ID=your_client_id
AZURE_CLIENT_SECRET=your_client_secret
# OR
GOOGLE_PROJECT_ID=your_gcp_project_id
GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
# OR
POWERDNS_API_URL=https://your-powerdns-server:8081
POWERDNS_API_KEY=your_powerdns_api_key

# Optional settings
SECRET_KEY=your_flask_secret_key_here
```

### 2. Start the Application

```bash
# Build and start with Docker Compose
docker-compose up -d

# Or build the image manually
docker build -t certmate .
docker run -p 8000:8000 --env-file .env -v ./certificates:/app/certificates certmate
```

### 3. Access the Application

- **Web Interface**: http://localhost:8000
- **API Documentation**: http://localhost:8000/docs/ (Swagger)
- **API Documentation**: http://localhost:8000/redoc/ (ReDoc)
- **Health Check**: http://localhost:8000/health

## Manual Installation

### Prerequisites

- Python 3.8+
- Certbot with Cloudflare DNS plugin
- OpenSSL

### Installation Steps

```bash
# Clone the repository
git clone <repository-url>
cd certmate

# Install Python dependencies
pip install -r requirements.txt

# Set environment variables
export CLOUDFLARE_TOKEN="your_token_here"
export API_BEARER_TOKEN="your_api_token_here"

# Run the application
python app.py
```

## API Usage

### Authentication

All API endpoints require Bearer token authentication:

```bash
# Include the Authorization header in all requests
Authorization: Bearer your_api_token_here
```

### API Endpoints

#### 1. Health Check
```bash
GET /health
```

#### 2. Get Settings
```bash
GET /api/settings
Authorization: Bearer your_token_here
```

#### 3. Update Settings
```bash
POST /api/settings
Authorization: Bearer your_token_here
Content-Type: application/json

{
  "cloudflare_token": "your_cloudflare_token",
  "domains": ["example.com", "test.com"],
  "email": "admin@example.com",
  "auto_renew": true,
  "api_bearer_token": "new_api_token"
}
```

#### 4. List Certificates
```bash
GET /api/certificates
Authorization: Bearer your_token_here
```

#### 5. Create Certificate
```bash
POST /api/certificates/create
Authorization: Bearer your_token_here
Content-Type: application/json

{
  "domain": "example.com"
}
```

#### 6. Renew Certificate
```bash
POST /api/certificates/example.com/renew
Authorization: Bearer your_token_here
```

#### 7. Download Certificate (API)
```bash
GET /api/certificates/example.com/download
Authorization: Bearer your_token_here
```

### 🎯 Special Download URL for Automation

The most powerful feature for datacenter automation:

```bash
# Download certificates for any domain via simple URL
GET /example.com/tls
Authorization: Bearer your_token_here
```

This returns a ZIP file containing:
- `cert.pem` - The certificate
- `chain.pem` - The certificate chain
- `fullchain.pem` - Full certificate chain
- `privkey.pem` - Private key

#### Automation Examples

**Download with curl:**
```bash
curl -H "Authorization: Bearer your_token_here" \
     -o example.com-tls.zip \
     http://your-server:8000/example.com/tls
```

**Python automation script:**
```python
import requests
import zipfile
import os

def download_certificate(domain, server_url, token):
    url = f"{server_url}/{domain}/tls"
    headers = {"Authorization": f"Bearer {token}"}
    
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        filename = f"{domain}-tls.zip"
        with open(filename, 'wb') as f:
            f.write(response.content)
        
        # Extract certificates
        with zipfile.ZipFile(filename, 'r') as zip_ref:
            zip_ref.extractall(f"/etc/ssl/certs/{domain}/")
        
        print(f"Certificate for {domain} downloaded and extracted")
        return True
    else:
        print(f"Failed to download certificate: {response.status_code}")
        return False

# Usage
download_certificate("example.com", "http://certmate:8000", "your_token_here")
```

**Bash automation script:**
```bash
#!/bin/bash

CERTMATE_URL="http://your-server:8000"
API_TOKEN="your_token_here"
DOMAIN="example.com"
CERT_DIR="/etc/ssl/certs/$DOMAIN"

# Download certificate
curl -H "Authorization: Bearer $API_TOKEN" \
     -o "$DOMAIN-tls.zip" \
     "$CERTMATE_URL/$DOMAIN/tls"

# Extract to certificate directory
mkdir -p "$CERT_DIR"
unzip -o "$DOMAIN-tls.zip" -d "$CERT_DIR"

# Reload nginx/apache/etc
systemctl reload nginx

echo "Certificate for $DOMAIN updated successfully"
```

**Ansible playbook example:**
```yaml
---
- name: Update SSL certificates from CertMate
  hosts: web_servers
  vars:
    certmate_url: "http://certmate.internal:8000"
    api_token: "{{ vault_certmate_token }}"
    domains:
      - example.com
      - api.example.com
  
  tasks:
    - name: Download certificates
      uri:
        url: "{{ certmate_url }}/{{ item }}/tls"
        method: GET
        headers:
          Authorization: "Bearer {{ api_token }}"
        dest: "/tmp/{{ item }}-tls.zip"
      loop: "{{ domains }}"
    
    - name: Extract certificates
      unarchive:
        src: "/tmp/{{ item }}-tls.zip"
        dest: "/etc/ssl/certs/{{ item }}/"
        remote_src: yes
      loop: "{{ domains }}"
      notify: reload nginx
    
  handlers:
    - name: reload nginx
      service:
        name: nginx
        state: reloaded
```

## Configuration

### Cloudflare API Token Setup

1. Go to [Cloudflare API Tokens](https://dash.cloudflare.com/profile/api-tokens)
2. Click "Create Token"
3. Use "Custom token" template
4. Set permissions:
   - **Zone:DNS:Edit** - Required for DNS challenge
   - **Zone:Zone:Read** - Required to list zones
5. Set "Zone Resources" to include your domains
6. Create and copy the token

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `CLOUDFLARE_TOKEN` | Yes | Cloudflare API token for DNS challenge |
| `API_BEARER_TOKEN` | Yes | Bearer token for API authentication |
| `SECRET_KEY` | No | Flask secret key (auto-generated if not set) |
| `FLASK_ENV` | No | Flask environment (production/development) |

### Docker Compose Configuration

The included `docker-compose.yml` provides:
- Automatic container restart
- Volume persistence for certificates and logs
- Health checks
- Optional nginx reverse proxy

#### With nginx reverse proxy:
```bash
docker-compose --profile nginx up -d
```

## Directory Structure

```
certmate/
├── app.py                 # Main application
├── requirements.txt       # Python dependencies
├── Dockerfile            # Docker configuration
├── docker-compose.yml    # Docker Compose setup
├── nginx.conf           # Nginx configuration
├── certificates/        # Certificate storage
├── data/               # Application data
├── logs/               # Application logs
└── templates/          # HTML templates
    ├── index.html      # Dashboard
    └── settings.html   # Settings page
```

## Security Considerations

1. **Bearer Token**: Use a strong, unique token for API authentication
2. **HTTPS**: Always use HTTPS in production
3. **Firewall**: Restrict access to the application port
4. **File Permissions**: Certificate files are stored with appropriate permissions
5. **Environment Variables**: Never commit sensitive tokens to version control

## Monitoring and Logging

- Application logs are written to the `logs/` directory
- Certificate renewal attempts are logged
- Health check endpoint available at `/health`
- Use Docker healthchecks for container monitoring

## Troubleshooting

### Certificate Creation Issues

1. **DNS Propagation**: Ensure DNS records can propagate (60s default)
2. **Token Permissions**: Verify Cloudflare token has correct permissions
3. **Rate Limits**: Let's Encrypt has rate limits (50 certificates per domain per week)

### API Authentication Issues

1. **Bearer Token**: Ensure the token matches what's configured
2. **Header Format**: Use `Authorization: Bearer your_token_here`
3. **Token Storage**: Check token is properly saved in settings

### Docker Issues

1. **Volumes**: Ensure certificate volumes are properly mounted
2. **Environment**: Check environment variables are set
3. **Health Check**: Monitor container health status

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## License

This project is licensed under the MIT License - see the LICENSE file for details.
