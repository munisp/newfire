# NewFire Infrastructure Repository - Agent Skill Guide

## Repository Overview

This is the infrastructure repository for the NewFire AI homelab platform. It contains:
- Architecture documentation (00_OVERVIEW.md - 08_CHECKLIST.md)
- Infrastructure-as-code for deployment
- Operational scripts for node management
- Tenant configurations
- Docker configurations for backend services

## Project Structure

```
newfire/
├── 00_OVERVIEW.md - 08_CHECKLIST.md  # Architecture documentation
├── infra/                            # Infrastructure configuration
│   ├── cloudflared/                  # Cloudflare Tunnel config
│   ├── codeep/                       # Codeep TUI setup
│   └── dev-hub/                      # Developer hub frontend
├── scripts/                          # Operational scripts
├── newfire_backend_docker/           # Backend Docker configuration
├── tenants/                          # Tenant-specific configs
├── workflows/                        # Workflow evaluation tools
├── progress/                         # Session logs and guides
└── blueprint/                        # Original design documents
```

## Key Files to Know

- `newfire_backend_docker/backfill_collections.py` - Backfills Qdrant collections
- `newfire_backend_docker/seed_company_content.sh` - Seeds company content
- `newfire_backend_docker/docker-compose.yml` - Backend service deployment
- `scripts/ci_review.py` - Local code review using local model
- `scripts/gen_worklog.py` - Generates worklog from git history
- `scripts/verify_isolation_from_personal.sh` - Network isolation verifier
- `scripts/verify_network_isolation.sh` - Homelab isolation verifier
- `infra/cloudflared/config.yml` - Cloudflare Tunnel ingress rules
- `.github/workflows/ci.yml` - GitHub Actions CI pipeline

## Security Notes

- All secrets must be in environment variables, never hardcoded
- Docker images should use non-root users where possible
- Network isolation between homelab and personal networks is critical
- Tailscale API key should be stored securely
- APISIX admin key should be rotated regularly

## Common Commands

```bash
# Generate worklog from git history
python3 scripts/gen_worklog.py

# Run CI review locally (requires DGX online)
python3 scripts/ci_review.py

# Verify network isolation (from homelab)
bash scripts/verify_network_isolation.sh

# Verify isolation from personal devices
bash scripts/verify_isolation_from_personal.sh

# Backfill Qdrant collections
python3 newfire_backend_docker/backfill_collections.py
```

## Contributing Guidelines

1. Never commit secrets or credentials
2. Use .env.example files as templates for required environment variables
3. Follow conventional commit format: `type(scope): description`
4. Add docstrings to all functions and scripts
5. Test scripts before committing changes
6. Document any new environment variables in .env.example

## Troubleshooting

- Docker build fails: Check that all required files are in the build context
- Network isolation tests fail: Verify Tailscale and subnet router configurations
- CI pipeline fails: Check that all Python dependencies are installed correctly
- Qdrant seeding fails: Verify that QDRANT_API_KEY is set and accessible