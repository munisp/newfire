# NewFire Repository

This repository contains documentation, infrastructure configuration, and operational scripts for the NewFire AI homelab platform.

## Quick Start

This is a documentation and infrastructure repository. The actual application code lives in separate repositories:

- **Backend**: Internal Express.js service (not in this repo)
- **Frontend**: Internal React app (not in this repo)
- **NSS Service**: Sandbox service components (not in this repo)

## Contents

- `00_OVERVIEW.md` through `08_CHECKLIST.md` - Architecture documentation
- `infra/` - Infrastructure configuration (Cloudflare, Docker, Nginx)
- `scripts/` - Operational scripts for node management
- `newfire_backend_docker/` - Docker configuration for backend service
- `progress/` - Session logs and deployment guides
- `tenants/` - Tenant-specific configurations
- `workflows/` - Workflow definitions and evaluation tools

## Security

All services are behind Tailscale or zrok2 + OpenZiti. No service is exposed publicly without authenticated tunnels.

## License

Proprietary. See [LICENSE](LICENSE) for details.
