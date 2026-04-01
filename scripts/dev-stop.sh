#!/bin/bash

# CoPaw Development Environment Stop Script

set -e

echo "🛑 Stopping CoPaw development environment..."
echo ""

docker-compose down

echo ""
echo "✅ All services stopped!"
echo ""
echo "💡 To start again, run:"
echo "   ./scripts/dev-start.sh"
echo ""
