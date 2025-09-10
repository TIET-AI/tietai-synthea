#!/bin/bash
# Synthea Python - UV Quick Start Script
# This script demonstrates how to set up and use Synthea with UV

set -e

echo "=================================="
echo "Synthea Python - UV Quick Start"
echo "=================================="
echo ""

# Check if UV is installed
if ! command -v uv &> /dev/null; then
    echo "UV is not installed. Please install it first:"
    echo "  curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

echo "✓ UV is installed: $(uv --version)"
echo ""

# Create virtual environment if it doesn't exist
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment with UV..."
    uv venv
    echo "✓ Virtual environment created"
else
    echo "✓ Virtual environment exists"
fi

# Activate virtual environment
echo "Activating virtual environment..."
source .venv/bin/activate

# Install dependencies
echo "Installing dependencies with UV..."
uv pip install -e ".[dev]"
echo "✓ Dependencies installed"
echo ""

# Run tests
echo "Running tests..."
pytest tests/test_person.py -v --tb=no
echo "✓ Tests passed"
echo ""

# Generate sample patients
echo "Generating sample patients..."
python -m synthea.cli -p 5 --seed 12345 -o ./output/uv_test --state Massachusetts --city Boston
echo "✓ Patients generated"
echo ""

# Run example script
echo "Running example script..."
python examples/custom_patient.py
echo "✓ Example completed"
echo ""

echo "=================================="
echo "Setup Complete!"
echo "=================================="
echo ""
echo "You can now use Synthea Python with UV:"
echo ""
echo "  # Generate patients"
echo "  uv run synthea -p 10"
echo ""
echo "  # Run with specific configuration"
echo "  uv run synthea -p 100 --state California --city 'San Francisco'"
echo ""
echo "  # Run tests"
echo "  uv run pytest"
echo ""
echo "  # Run examples"
echo "  uv run python examples/basic_generation.py"
echo ""
echo "For more information, see README.md"