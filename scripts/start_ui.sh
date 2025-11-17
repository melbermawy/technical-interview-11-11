#!/bin/bash
# Quick start script for PR-4B UI
# Must be run from project root directory

set -e

# Check we're in project root
if [ ! -f "pyproject.toml" ] || [ ! -d "ui" ]; then
    echo "❌ ERROR: Must run from project root directory"
    echo "Current directory: $(pwd)"
    echo "Please cd to the technical-interview-11-11 directory first"
    exit 1
fi

echo "🚀 Starting Travel Planner UI (PR-4B)"
echo ""
echo "Prerequisites:"
echo "  - Backend must be running at http://localhost:8000"
echo "  - If not, run: uvicorn backend.app.main:app --reload"
echo ""
echo "Opening Streamlit UI..."
echo ""

streamlit run ui/app.py
