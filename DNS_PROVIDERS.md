# DNS Providers Support

CertMate now supports **19 DNS providers** for Let's Encrypt DNS challenges through individual certbot plugins that provide reliable, well-tested DNS challenge support.

## 🎯 Supported Providers

### 🏆 Tier 1: Core Providers (Fully Supported)
These providers have dedicated, well-maintained certbot plugins:

| Provider | Plugin | Credentials Required | Use Case |
|----------|--------|---------------------|----------|
| **Cloudflare** | `certbot-dns-cloudflare` | API Token | Global CDN, Free tier |
| **AWS Route53** | `certbot-dns-route53` | Access Key, Secret Key | AWS infrastructure |
| **Azure DNS** | `certbot-dns-azure` | Service Principal | Microsoft ecosystem |
| **Google Cloud DNS** | `certbot-dns-google` | Service Account JSON | Google Cloud Platform |
| **PowerDNS** | `certbot-dns-powerdns` | API URL, API Key | Self-hosted DNS |
| **DigitalOcean** | `certbot-dns-digitalocean` | API Token | Cloud infrastructure |
| **Linode** | `certbot-dns-linode` | API Key | Cloud hosting |
| **Gandi** | `certbot-dns-gandi` | API Token | Domain registrar |
| **OVH** | `certbot-dns-ovh` | API Credentials | European hosting |
| **Namecheap** | `certbot-dns-namecheap` | Username, API Key | Domain registrar |

### 🚀 Tier 2: Additional Providers
High-demand providers with dedicated certbot plugins:

| Provider | Credentials Required | Use Case |
|----------|---------------------|----------|
| **Vultr** | API Key | Global cloud infrastructure |
| **DNS Made Easy** | API Key, Secret Key | Enterprise DNS management |
| **NS1** | API Key | Intelligent DNS platform |
| **RFC2136** | Nameserver, TSIG Key/Secret | Standard DNS update protocol |

### 🌟 Tier 3: Extended Providers
Additional popular providers with dedicated certbot plugins:

| Provider | Credentials Required | Use Case |
|----------|---------------------|----------|
| **Hetzner** | API Token | European cloud hosting |
| **Porkbun** | API Key, Secret Key | Domain registrar with DNS |
| **GoDaddy** | API Key, Secret | Domain registrar |
| **Hurricane Electric** | Username, Password | Free DNS hosting |
| **Dynu** | API Token | Dynamic DNS service |

## 🛠 Configuration

### Via Web Interface

1. Navigate to **Settings** page
2. Select your DNS provider from the dropdown
3. Fill in the required credentials
4. Save settings

### Via API

```bash
curl -X POST http://localhost:5000/api/settings \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "dns_provider": "vultr",
    "dns_providers": {
      "vultr": {
        "api_key": "your_vultr_api_key"
      }
    }
  }'
```

## 🎯 Popular Provider Setup Examples

### Vultr
```bash
# Get API key from Vultr account
{
  "dns_provider": "vultr",
  "dns_providers": {
    "vultr": {
      "api_key": "your_vultr_api_key"
    }
  }
}
```

### DNS Made Easy
```bash
# Get API credentials from DNS Made Easy account
{
  "dns_provider": "dnsmadeeasy", 
  "dns_providers": {
    "dnsmadeeasy": {
      "api_key": "your_api_key",
      "secret_key": "your_secret_key"
    }
  }
}
```

### NS1
```bash
# Get API key from NS1 account
{
  "dns_provider": "nsone",
  "dns_providers": {
    "nsone": {
      "api_key": "your_nsone_api_key"
    }
  }
}
```

### RFC2136 (Standard Protocol)
```bash
# For BIND or other RFC2136-compatible DNS servers
{
  "dns_provider": "rfc2136",
  "dns_providers": {
    "rfc2136": {
      "nameserver": "ns.example.com",
      "tsig_key": "mykey",
      "tsig_secret": "base64-encoded-secret",
      "tsig_algorithm": "HMAC-SHA512"
    }
  }
}
```

### Hetzner (Tier 3)
```bash
# Get API token from Hetzner DNS Console
{
  "dns_provider": "hetzner",
  "dns_providers": {
    "hetzner": {
      "api_token": "your_hetzner_api_token"
    }
  }
}
```

### Porkbun (Tier 3)
```bash
# Get API credentials from Porkbun
{
  "dns_provider": "porkbun",
  "dns_providers": {
    "porkbun": {
      "api_key": "your_porkbun_api_key",
      "secret_key": "your_porkbun_secret_key"
    }
  }
}
```

### GoDaddy (Tier 3)
```bash
# Get API credentials from GoDaddy Developer Portal
{
  "dns_provider": "godaddy",
  "dns_providers": {
    "godaddy": {
      "api_key": "your_godaddy_api_key",
      "secret": "your_godaddy_secret"
    }
  }
}
```

### Hurricane Electric (Tier 3)
```bash
# Use your Hurricane Electric DNS account credentials
{
  "dns_provider": "he-ddns",
  "dns_providers": {
    "he-ddns": {
      "username": "your_he_username",
      "password": "your_he_password"
    }
  }
}
```

### Dynu (Tier 3)
```bash
# Get API token from Dynu Control Panel
{
  "dns_provider": "dynudns",
  "dns_providers": {
    "dynudns": {
      "token": "your_dynu_api_token"
    }
  }
}
```

## Creating Certificates

### Using Default Provider
```bash
curl -X POST http://localhost:5000/api/certificates/create \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"domain": "example.com"}'
```

### Using Specific Provider
```bash
curl -X POST http://localhost:5000/api/certificates/create \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "domain": "example.com",
    "dns_provider": "vultr"
  }'
```

## 🚀 How Provider Support Works

CertMate uses individual, well-maintained certbot plugins for maximum reliability:
- **Tier 1 providers** use their core plugins (cloudflare, route53, azure, etc.)
- **Tier 2 providers** use additional individual plugins (vultr, dnsmadeeasy, nsone, rfc2136)

All providers are supported through official or well-maintained certbot plugins, ensuring stability and reliability.

## 🔍 Provider Detection Logic

```python
# Tier 1: Core providers with individual plugins  
if dns_provider in ['cloudflare', 'route53', 'azure', 'google', 'powerdns', 
                   'digitalocean', 'linode', 'gandi', 'ovh', 'namecheap']:
    use_individual_plugin()

# Tier 2: Additional providers with individual plugins
elif dns_provider in ['vultr', 'dnsmadeeasy', 'nsone', 'rfc2136']:
    use_individual_plugin()

# Tier 3: Extended providers with individual plugins    
elif dns_provider in ['hetzner', 'porkbun', 'godaddy', 'he-ddns', 'dynudns']:
    use_individual_plugin()
    
else:
    return_not_supported_error()
```

## 🛡 Security Features

- **Credential masking** in web interface
- **Secure file permissions** (600) for all credential files
- **API token validation** before certificate creation
- **Environment variable support** for CI/CD workflows
- **Audit logging** for all DNS provider usage

## 📋 Migration Guide

### From Single Provider to Multi-Provider

Your existing configurations remain unchanged! Simply add new providers:

```bash
# Existing Cloudflare config continues to work
# Add Vultr for new domains
{
  "dns_providers": {
    "cloudflare": {
      "api_token": "existing_token"
    },
    "vultr": {
      "api_key": "new_vultr_api_key"  
    }
  }
}
```

## 🏗 Contributing New Providers

Adding support for a new provider:

1. **Individual Plugin Route:**
   - Add plugin to `requirements.txt` (e.g., `certbot-dns-newprovider`)
   - Create config function in `app.py` (e.g., `create_newprovider_config()`)
   - Add provider logic to `create_certificate()` function
   - Add UI elements in templates
   - Update documentation

2. **Check for Existing Plugins:**
   - Search for `certbot-dns-[provider]` on PyPI
   - Verify plugin is actively maintained
   - Test plugin compatibility with current certbot version

## 🔧 Troubleshooting

### Common Issues

1. **"DNS provider not configured"**
   - Verify all required credentials are provided
   - Check credential validity with provider

2. **"Certificate creation failed"**
   - Ensure domain is managed by your DNS provider
   - Verify API permissions include DNS record management
   - Check rate limits and quotas

3. **Plugin not found errors**
   - Run `pip install -r requirements.txt` to install all plugins
   - For Docker: rebuild container to get latest plugins

### Debug Mode
```bash
export FLASK_DEBUG=1
python app.py
```

### Testing Provider Configuration
```bash
curl -X GET http://localhost:5000/api/settings/dns-providers \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```

## 📊 Provider Statistics

- **Total Supported**: 19 providers
- **Tier 1 Providers**: 10 providers (Core certbot plugins)
- **Tier 2 Providers**: 4 providers (Additional individual plugins)
- **Tier 3 Providers**: 5 providers (Extended individual plugins)
- **Geographic Coverage**: Global (all continents)
- **Enterprise Providers**: AWS, Azure, GCP, Cloudflare, PowerDNS, DNS Made Easy, NS1
- **European Providers**: OVH, Gandi, Hetzner
- **Budget Providers**: Namecheap, DigitalOcean, Linode, Vultr, Porkbun
- **Free Providers**: Hurricane Electric

---

🎉 **CertMate provides rock-solid DNS provider support with individual, well-maintained plugins!**

## Configuration

### Via Web Interface

1. Go to Settings page
2. Select your preferred DNS provider
3. Fill in the required credentials for your chosen provider
4. Save settings

### Via API

```bash
curl -X POST http://localhost:5000/api/settings \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "dns_provider": "cloudflare",
    "dns_providers": {
      "cloudflare": {
        "api_token": "your_cloudflare_token"
      }
    }
  }'
```

## Creating Certificates

### Using Default Provider

```bash
curl -X POST http://localhost:5000/api/certificates/create \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "domain": "example.com"
  }'
```

### Using Specific Provider

```bash
curl -X POST http://localhost:5000/api/certificates/create \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "domain": "example.com",
    "dns_provider": "route53"
  }'
```

## Environment Variables

You can also set DNS provider credentials via environment variables:

```bash
# Cloudflare
CLOUDFLARE_API_TOKEN=your_token

# AWS Route53
AWS_ACCESS_KEY_ID=your_access_key
AWS_SECRET_ACCESS_KEY=your_secret_key
AWS_DEFAULT_REGION=us-east-1

# Azure
AZURE_SUBSCRIPTION_ID=your_subscription_id
AZURE_RESOURCE_GROUP=your_resource_group
AZURE_TENANT_ID=your_tenant_id
AZURE_CLIENT_ID=your_client_id
AZURE_CLIENT_SECRET=your_client_secret

# Google Cloud
GOOGLE_PROJECT_ID=your_project_id
GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json

# PowerDNS
POWERDNS_API_URL=https://your-powerdns-server:8081
POWERDNS_API_KEY=your_api_key
```

## Backward Compatibility

CertMate maintains full backward compatibility:
- Existing Cloudflare configurations continue to work
- Old `cloudflare_token` setting is automatically migrated
- All existing certificates remain valid

## Migration Guide

### From Cloudflare-only to Multi-provider

1. **Automatic Migration**: Your existing Cloudflare token will be automatically migrated to the new DNS providers structure
2. **Manual Migration**: You can manually configure additional providers in the settings
3. **No Downtime**: Existing certificates and renewals continue to work during migration

### Adding New Providers

1. Go to Settings → DNS Provider section
2. Select your new provider
3. Fill in the required credentials
4. Set as default (optional)
5. Test with a new certificate

## Security Considerations

- All credentials are stored securely and masked in the UI
- API tokens are never exposed in logs
- Credentials are validated before use
- Failed authentication attempts are logged

## Troubleshooting

### Common Issues

1. **"DNS provider not configured"**: Ensure all required fields are filled
2. **"Certificate creation failed"**: Check DNS provider credentials and permissions
3. **"Domain not found"**: Verify domain is managed by your DNS provider

### Debug Mode

Enable debug logging to troubleshoot issues:

```bash
export FLASK_ENV=development
export FLASK_DEBUG=1
```

### Testing Credentials

Use the API to test your DNS provider configuration:

```bash
curl -X GET http://localhost:5000/api/settings/dns-providers \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```

## Contributing

To add support for a new DNS provider:

1. Add the certbot DNS plugin to `requirements.txt`
2. Create a configuration function in `app.py`
3. Add provider logic to `create_certificate()` function
4. Update the settings UI and API models
5. Add documentation and tests

## Examples

### Multi-domain Setup with Different Providers

```json
{
  "domains": ["example.com", "test.org"],
  "dns_provider": "cloudflare",
  "dns_providers": {
    "cloudflare": {
      "api_token": "token_for_example_com"
    },
    "route53": {
      "access_key_id": "key_for_test_org",
      "secret_access_key": "secret_for_test_org"
    }
  }
}
```

### Using Different Providers per Certificate

```bash
# Create certificate using Cloudflare
curl -X POST http://localhost:5000/api/certificates/create \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"domain": "example.com", "dns_provider": "cloudflare"}'

# Create certificate using Route53
curl -X POST http://localhost:5000/api/certificates/create \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"domain": "test.org", "dns_provider": "route53"}'
```
