# Nginx Configuration Generator Service Design

## Overview

This document describes the design for an nginx configuration generator service that automatically creates and manages nginx reverse proxy configurations for sandbox environments. The service will generate nginx site-available configurations, manage SSL certificates, and handle site enable/disable operations.

## Problem Statement

The current `--force-https` approach with EIPs fails due to certificate mismatch:
- User accesses: `https://134.199.204.237:53350/`
- Browser expects: Certificate matching `134.199.204.237`
- code-server presents: Certificate for `localhost`/`127.0.0.1`
- Result: Browser rejects connection with hostname mismatch error

## Solution Architecture

```
Client (HTTPS) → nginx (SSL termination) → code-server (HTTP)
                      ↓
              /etc/nginx/sites-available/
              /etc/nginx/sites-enabled/
```

## Service Components

### 1. NginxConfigService

**Location**: `server/src/services/nginx_config.py`

**Responsibilities**:
- Generate nginx configuration files for sandbox endpoints
- Manage site-available and site-enabled directories
- Reload nginx after configuration changes
- Validate nginx configuration before applying

**Configuration Templates**:

#### HTTP Configuration Template

```nginx
# /etc/nginx/sites-available/sandbox-{sandbox_id}-{port}
server {
    listen 80;
    server_name {server_name};

    location / {
        proxy_pass http://127.0.0.1:{container_port};
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

#### HTTPS Configuration Template

```nginx
# /etc/nginx/sites-available/sandbox-{sandbox_id}-{port}
server {
    listen 443 ssl http2;
    server_name {server_name};

    ssl_certificate {cert_path};
    ssl_certificate_key {key_path};
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;

    location / {
        proxy_pass http://127.0.0.1:{container_port};
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### 2. SSL Certificate Manager

**Location**: `server/src/services/ssl_manager.py`

**Responsibilities**:
- Generate self-signed certificates for development
- Integrate with certbot for production certificates
- Manage certificate lifecycle (create, renew, delete)
- Validate certificate existence and validity

### 3. Site Manager

**Location**: `server/src/services/site_manager.py`

**Responsibilities**:
- Create symlinks from sites-available to sites-enabled
- Remove symlinks when sites are disabled
- Run nginx validation and reload commands
- Handle permission requirements (sudo/root)

## Service Interface

### NginxConfigService API

```python
class NginxConfigService:
    """Service for managing nginx reverse proxy configurations."""
    
    def __init__(
        self,
        sites_available_dir: str = "/etc/nginx/sites-available",
        sites_enabled_dir: str = "/etc/nginx/sites-enabled",
        nginx_reload_cmd: str = "nginx -s reload",
        nginx_test_cmd: str = "nginx -t",
    ):
        """Initialize the nginx configuration service."""
    
    async def create_config(
        self,
        sandbox_id: str,
        container_port: int,
        server_name: str,
        use_https: bool = False,
        cert_path: Optional[str] = None,
        key_path: Optional[str] = None,
    ) -> str:
        """
        Create nginx configuration for a sandbox endpoint.
        
        Args:
            sandbox_id: Unique sandbox identifier
            container_port: Port inside the container
            server_name: Server name (domain or IP)
            use_https: Whether to use HTTPS
            cert_path: Path to SSL certificate (required if use_https)
            key_path: Path to SSL key (required if use_https)
        
        Returns:
            Path to the created configuration file
        
        Raises:
            ValueError: If HTTPS enabled but no certificates provided
            RuntimeError: If nginx configuration is invalid
        """
    
    async def delete_config(self, sandbox_id: str, container_port: int) -> None:
        """
        Delete nginx configuration for a sandbox endpoint.
        
        Args:
            sandbox_id: Unique sandbox identifier
            container_port: Port inside the container
        """
    
    async def enable_config(self, config_path: str) -> None:
        """
        Enable nginx configuration by creating symlink.
        
        Args:
            config_path: Path to configuration file in sites-available
        
        Raises:
            RuntimeError: If nginx test fails
        """
    
    async def disable_config(self, config_path: str) -> None:
        """
        Disable nginx configuration by removing symlink.
        
        Args:
            config_path: Path to configuration file in sites-available
        """
    
    async def reload_nginx(self) -> None:
        """Reload nginx configuration."""
    
    async def test_config(self) -> bool:
        """Test nginx configuration validity."""
```

### SSLManager API

```python
class SSLManager:
    """Service for managing SSL certificates."""
    
    def __init__(
        self,
        cert_dir: str = "/etc/letsencrypt/live",
        use_certbot: bool = False,
    ):
        """Initialize the SSL certificate manager."""
    
    async def generate_self_signed_cert(
        self,
        server_name: str,
        output_dir: str = "/etc/nginx/ssl",
    ) -> tuple[str, str]:
        """
        Generate self-signed certificate for development.
        
        Args:
            server_name: Server name (domain or IP)
            output_dir: Directory to save certificate files
        
        Returns:
            Tuple of (cert_path, key_path)
        """
    
    async def obtain_certbot_cert(
        self,
        domain: str,
        email: str,
    ) -> tuple[str, str]:
        """
        Obtain certificate using certbot.
        
        Args:
            domain: Domain name
            email: Email for certificate registration
        
        Returns:
            Tuple of (cert_path, key_path)
        
        Raises:
            RuntimeError: If certbot command fails
        """
    
    async def delete_cert(self, server_name: str) -> None:
        """
        Delete certificate for a server name.
        
        Args:
            server_name: Server name (domain or IP)
        """
    
    async def cert_exists(self, server_name: str) -> bool:
        """Check if certificate exists for server name."""
```

## Configuration Schema

Add nginx configuration to `server/src/config.py`:

```python
class NginxConfig(BaseModel):
    """Nginx reverse proxy configuration."""

    enabled: bool = Field(
        default=False,
        description="Enable nginx reverse proxy for sandbox endpoints",
    )
    sites_available_dir: str = Field(
        default="/etc/nginx/sites-available",
        description="Directory for nginx site-available configurations",
    )
    sites_enabled_dir: str = Field(
        default="/etc/nginx/sites-enabled",
        description="Directory for nginx site-enabled symlinks",
    )
    reload_command: str = Field(
        default="nginx -s reload",
        description="Command to reload nginx configuration",
    )
    test_command: str = Field(
        default="nginx -t",
        description="Command to test nginx configuration",
    )

class SSLConfig(BaseModel):
    """SSL certificate management configuration."""

    enabled: bool = Field(
        default=False,
        description="Enable SSL certificate management",
    )
    use_certbot: bool = Field(
        default=False,
        description="Use certbot for automatic SSL certificates",
    )
    cert_dir: str = Field(
        default="/etc/letsencrypt/live",
        description="Directory for Let's Encrypt certificates",
    )
    self_signed_dir: str = Field(
        default="/etc/nginx/ssl",
        description="Directory for self-signed certificates",
    )
    certbot_email: Optional[str] = Field(
        default=None,
        description="Email for certbot certificate registration",
    )

# Add to AppConfig
class AppConfig(BaseModel):
    # ... existing fields ...
    
    nginx: NginxConfig = Field(
        default_factory=NginxConfig,
        description="Nginx reverse proxy configuration",
    )
    
    ssl: SSLConfig = Field(
        default_factory=SSLConfig,
        description="SSL certificate management configuration",
    )
```

## Integration with Sandbox Lifecycle

### DockerSandboxService Modifications

**Location**: `server/src/services/docker.py`

#### 1. Initialize NginxConfigService

```python
class DockerSandboxService(SandboxService):
    def __init__(self, app_config: AppConfig):
        # ... existing initialization ...
        
        # Initialize nginx config service if enabled
        self._nginx_config_service = None
        if app_config.nginx.enabled:
            self._nginx_config_service = NginxConfigService(
                sites_available_dir=app_config.nginx.sites_available_dir,
                sites_enabled_dir=app_config.nginx.sites_enabled_dir,
                nginx_reload_cmd=app_config.nginx.reload_command,
                nginx_test_cmd=app_config.nginx.test_command,
            )
            logger.info("Nginx configuration service initialized")
```

#### 2. Modify _provision_sandbox

Add nginx configuration after container is running:

```python
def _provision_sandbox(
    self,
    sandbox_id: str,
    request: CreateSandboxRequest,
    created_at: datetime,
    expires_at: datetime,
    pvc_inspect_cache: Optional[dict[str, dict]] = None,
) -> CreateSandboxResponse:
    # ... existing provisioning code ...
    
    # Start the container
    container = self.docker_client.containers.run(
        image=image_uri,
        name=container_name,
        hostname=container_name,
        environment=environment,
        labels=labels,
        volumes=volume_binds,
        host_config=host_config_kwargs,
        detach=True,
    )
    
    # ... existing post-start code ...
    
    # Create nginx configuration if enabled
    if self._nginx_config_service:
        await self._create_nginx_config(
            sandbox_id=sandbox_id,
            container=container,
            request=request,
        )
    
    # ... rest of provisioning ...
```

#### 3. Add _create_nginx_config method

```python
async def _create_nginx_config(
    self,
    sandbox_id: str,
    container,
    request: CreateSandboxRequest,
) -> None:
    """Create nginx configuration for sandbox endpoints."""
    try:
        # Get container port mappings
        port_bindings = container.attrs.get("NetworkSettings", {}).get("Ports", {})
        
        # Determine server name (domain or EIP)
        server_name = self.app_config.server.eip or request.metadata.get("domain", "localhost")
        
        # For each exposed port, create nginx config
        for container_port, host_bindings in port_bindings.items():
            if not host_bindings:
                continue
            
            # Extract port number (e.g., "8080/tcp" -> "8080")
            port_num = container_port.split("/")[0]
            
            # Determine if HTTPS should be used
            use_https = request.metadata.get("use_https", "false").lower() == "true"
            
            # Get certificate paths if HTTPS enabled
            cert_path = None
            key_path = None
            if use_https:
                cert_path = request.metadata.get("ssl_cert")
                key_path = request.metadata.get("ssl_key")
                if not cert_path or not key_path:
                    # Generate self-signed certificate
                    cert_path, key_path = await self._ssl_manager.generate_self_signed_cert(
                        server_name=server_name,
                    )
            
            # Create nginx configuration
            config_path = await self._nginx_config_service.create_config(
                sandbox_id=sandbox_id,
                container_port=int(port_num),
                server_name=server_name,
                use_https=use_https,
                cert_path=cert_path,
                key_path=key_path,
            )
            
            # Enable the configuration
            await self._nginx_config_service.enable_config(config_path)
            
            logger.info(
                "Created nginx config for sandbox %s port %s -> %s",
                sandbox_id,
                port_num,
                config_path,
            )
    
    except Exception as exc:
        logger.error(
            "Failed to create nginx config for sandbox %s: %s",
            sandbox_id,
            exc,
        )
        # Non-fatal: sandbox can still function without nginx
```

#### 4. Modify delete_sandbox

Remove nginx configuration when sandbox is deleted:

```python
async def delete_sandbox(self, sandbox_id: str) -> None:
    """Delete a sandbox and its nginx configuration."""
    # ... existing deletion code ...
    
    # Remove nginx configuration
    if self._nginx_config_service:
        await self._delete_nginx_config(sandbox_id)
```

#### 5. Add _delete_nginx_config method

```python
async def _delete_nginx_config(self, sandbox_id: str) -> None:
    """Delete nginx configuration for a sandbox."""
    try:
        # List all nginx configs for this sandbox
        config_pattern = f"sandbox-{sandbox_id}-*"
        
        # Find and remove all matching configs
        for config_file in glob.glob(
            f"{self._nginx_config_service.sites_available_dir}/{config_pattern}"
        ):
            # Disable the config
            await self._nginx_config_service.disable_config(config_file)
            
            # Delete the config file
            await self._nginx_config_service.delete_config(
                sandbox_id=sandbox_id,
                container_port=int(config_file.split("-")[-1]),
            )
            
            logger.info("Deleted nginx config: %s", config_file)
    
    except Exception as exc:
        logger.error(
            "Failed to delete nginx config for sandbox %s: %s",
            sandbox_id,
            exc,
        )
```

## Implementation Plan

### Phase 1: Core Service Implementation

1. **Create NginxConfigService** (`server/src/services/nginx_config.py`)
   - Implement configuration file generation
   - Implement site enable/disable operations
   - Implement nginx reload functionality
   - Add comprehensive logging

2. **Create SSLManager** (`server/src/services/ssl_manager.py`)
   - Implement self-signed certificate generation
   - Implement certificate validation
   - Add certbot integration stub

3. **Add Configuration Schema** (`server/src/config.py`)
   - Add NginxConfig model
   - Add SSLConfig model
   - Update AppConfig model

4. **Create Unit Tests**
   - Test configuration file generation
   - Test site enable/disable
   - Test certificate generation

### Phase 2: Docker Integration

1. **Modify DockerSandboxService** (`server/src/services/docker.py`)
   - Initialize NginxConfigService
   - Add _create_nginx_config method
   - Add _delete_nginx_config method
   - Integrate with _provision_sandbox
   - Integrate with delete_sandbox

2. **Update Factory** (`server/src/services/factory.py`)
   - Pass nginx config to DockerSandboxService

3. **Add Integration Tests**
   - Test sandbox creation with nginx config
   - Test sandbox deletion with nginx cleanup
   - Test HTTP and HTTPS configurations

### Phase 3: Example Updates

1. **Update vscode-remote example** (`examples/vscode-remote/main.py`)
   - Add support for nginx mode
   - Update documentation
   - Add example configuration

2. **Update README** (`examples/vscode-remote/README.md`)
   - Document nginx mode
   - Provide setup instructions
   - Add troubleshooting guide

### Phase 4: Advanced Features

1. **Certbot Integration**
   - Implement automatic certificate obtaining
   - Implement certificate renewal
   - Add webhook support for DNS challenges

2. **Wildcard Certificate Support**
   - Support wildcard domains
   - Support SAN (Subject Alternative Names)

3. **Configuration Validation**
   - Validate nginx syntax before applying
   - Validate certificate validity
   - Add rollback on failure

## Deployment Considerations

### Prerequisites

1. **nginx Installation**
   ```bash
   sudo apt-get install nginx
   ```

2. **Directory Permissions**
   ```bash
   sudo mkdir -p /etc/nginx/sites-available
   sudo mkdir -p /etc/nginx/sites-enabled
   sudo chown -R $USER:$USER /etc/nginx/sites-available
   sudo chown -R $USER:$USER /etc/nginx/sites-enabled
   ```

3. **SSL Directory**
   ```bash
   sudo mkdir -p /etc/nginx/ssl
   sudo chown -R $USER:$USER /etc/nginx/ssl
   ```

### Configuration Example

Add to `~/.sandbox.toml`:

```toml
[nginx]
enabled = true
sites_available_dir = "/etc/nginx/sites-available"
sites_enabled_dir = "/etc/nginx/sites-enabled"
reload_command = "nginx -s reload"
test_command = "nginx -t"

[ssl]
enabled = true
use_certbot = false
cert_dir = "/etc/letsencrypt/live"
self_signed_dir = "/etc/nginx/ssl"
certbot_email = "admin@example.com"
```

## Security Considerations

1. **File Permissions**
   - Ensure SSL key files have restricted permissions (600)
   - Validate paths to prevent directory traversal

2. **Certificate Validation**
   - Verify certificate expiration before use
   - Validate certificate chain

3. **nginx Configuration**
   - Use strong SSL ciphers
   - Enable HSTS for production
   - Disable weak protocols (SSLv3, TLSv1.0, TLSv1.1)

4. **Privilege Separation**
   - Consider running nginx reload with sudo
   - Use sudoers for controlled command execution

## Testing Strategy

### Unit Tests

- Test configuration file generation with various inputs
- Test site enable/disable operations
- Test certificate generation and validation
- Test error handling and edge cases

### Integration Tests

- Test sandbox creation with nginx config
- Test sandbox deletion with nginx cleanup
- Test HTTP and HTTPS configurations
- Test nginx reload after configuration changes

### End-to-End Tests

- Test full workflow: create sandbox → nginx config → access via browser
- Test certificate renewal workflow
- Test error recovery (e.g., nginx fails to reload)

## Future Enhancements

1. **Load Balancing**
   - Support multiple backend containers
   - Implement load balancing algorithms

2. **Caching**
   - Add nginx caching for static content
   - Implement cache invalidation

3. **Rate Limiting**
   - Add rate limiting per sandbox
   - Implement IP-based blocking

4. **Monitoring**
   - Add nginx access/error log integration
   - Implement metrics collection

5. **WebSocket Support**
   - Ensure proper WebSocket proxying
   - Add connection timeout configuration
