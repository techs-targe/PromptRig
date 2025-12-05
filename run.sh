#!/bin/bash
# Startup script for Prompt Evaluation System (Linux)
# Based on specification in docs/req.txt section 2.3

echo "============================================================"
echo "Prompt Evaluation System - Startup Script (Linux)"
echo "============================================================"

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "Virtual environment not found. Creating..."
    python3 -m venv venv
    if [ $? -ne 0 ]; then
        echo "Failed to create virtual environment"
        exit 1
    fi
fi

# Activate virtual environment
echo "Activating virtual environment..."
source venv/bin/activate

# Check if .env exists
if [ ! -f ".env" ]; then
    echo "Warning: .env file not found!"
    echo "Please copy .env.example to .env and configure it."
    exit 1
fi

# Install/update dependencies
echo "Installing dependencies..."
pip install -r requirements.txt
if [ $? -ne 0 ]; then
    echo "Failed to install dependencies"
    exit 1
fi

# Start application
echo ""
echo "Starting application..."
echo "Access at: http://localhost:9200"
echo ""
python main.py
