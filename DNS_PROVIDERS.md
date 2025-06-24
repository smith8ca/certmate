# DNS Providers Support

CertMate now supports multiple DNS providers for Let's Encrypt DNS challenges, allowing you to use your preferred DNS service without being locked into a single provider.

## Supported DNS Providers

### 1. Cloudflare
- **Requirements**: Cloudflare API Token
- **Plugin**: `certbot-dns-cloudflare==4.1.1`
- **Permissions**: Zone:DNS:Edit
- **How to get**: [Cloudflare Dashboard](https://dash.cloudflare.com/profile/api-tokens)

### 2. AWS Route53
- **Requirements**: AWS Access Key ID and Secret Access Key
- **Plugin**: `certbot-dns-route53==4.1.1`
- **Permissions**: Route53FullAccess or custom policy with Route53 DNS permissions
- **Region**: Optional (defaults to us-east-1)

### 3. Azure DNS
- **Requirements**: Service Principal with DNS Zone Contributor role
- **Plugin**: `certbot-dns-azure==2.6.1`
- **Credentials**: Subscription ID, Resource Group, Tenant ID, Client ID, Client Secret
- **How to setup**: Create a Service Principal in Azure Portal

### 4. Google Cloud DNS
- **Requirements**: Service Account with DNS Administrator role
- **Plugin**: `certbot-dns-google==4.1.1`
- **Credentials**: Project ID and Service Account JSON key
- **How to setup**: Create a Service Account in Google Cloud Console

### 5. PowerDNS
- **Requirements**: PowerDNS server with API enabled
- **Plugin**: `certbot-dns-powerdns==0.2.1`
- **Credentials**: API URL and API Key
- **How to setup**: Enable API in PowerDNS configuration

> **Note**: We use Certbot 4.1.1 and compatible DNS plugins. The Azure DNS plugin has independent versioning (2.6.1) and PowerDNS plugin is newer (0.2.1).

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
