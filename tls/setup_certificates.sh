#!/bin/bash
# Script to copy TLS certificates from CrowdSec installation

# CrowdSec certificate directories (adjust paths as needed)
CROWDSEC_BOUNCER_DIR="/etc/crowdsec/bouncers"  # Linux/Mac
# CROWDSEC_BOUNCER_DIR="C:\\ProgramData\\CrowdSec\\bouncers"  # Windows

# Target directory (current directory)
TARGET_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Copying CrowdSec TLS certificates..."
echo "Source: $CROWDSEC_BOUNCER_DIR"
echo "Target: $TARGET_DIR"

# Copy certificates
cp "$CROWDSEC_BOUNCER_DIR"/client.crt "$TARGET_DIR/" 2>/dev/null && echo "✓ client.crt copied" || echo "✗ client.crt not found"
cp "$CROWDSEC_BOUNCER_DIR"/client.key "$TARGET_DIR/" 2>/dev/null && echo "✓ client.key copied" || echo "✗ client.key not found"
cp "$CROWDSEC_BOUNCER_DIR"/ca.crt "$TARGET_DIR/" 2>/dev/null && echo "✓ ca.crt copied" || echo "✗ ca.crt not found"

# Set secure permissions (Linux/Mac only)
if [[ "$OSTYPE" != "msys" && "$OSTYPE" != "cygwin" ]]; then
    chmod 600 "$TARGET_DIR"/*.crt "$TARGET_DIR"/*.key 2>/dev/null
    echo "✓ Permissions set to 600"
fi

echo "Done!"
