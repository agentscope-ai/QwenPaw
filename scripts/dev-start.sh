#!/bin/bash

# CoPaw Development Environment Startup Script

set -e

echo "🚀 Starting CoPaw development environment..."
echo ""

# Check if .env file exists
if [ ! -f ".env" ]; then
    echo "⚠️  Warning: .env file not found"
    echo "Creating .env from console/.env..."
    cp console/.env .env
fi

# Load environment variables
export $(cat .env | grep -v '^#' | xargs)

echo "📦 Building Docker images..."
docker-compose build

echo ""
echo "🔧 Starting services..."
docker-compose up -d

echo ""
echo "⏳ Waiting for services to be ready..."
sleep 5

echo ""
echo "✅ CoPaw is running!"
echo ""
echo "📍 Access URLs:"
echo "   - Website:  http://localhost (or http://192.168.31.210)"
echo "   - Console:  http://localhost/console/chat"
echo "   - Backend:  http://localhost:8088"
echo "   - External: https://copaw-comokiki.gd.ddnsto.com"
echo ""
echo "📊 View logs:"
echo "   docker-compose logs -f"
echo ""
echo "🛑 Stop services:"
echo "   ./scripts/dev-stop.sh"
echo ""
