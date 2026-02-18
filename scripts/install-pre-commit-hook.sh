#!/bin/bash
# Script to install the pre-commit hook

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
HOOK_FILE="$PROJECT_ROOT/.git/hooks/pre-commit"
HOOK_SOURCE="$PROJECT_ROOT/.git/hooks/pre-commit"

# Check if .git/hooks directory exists
if [ ! -d "$PROJECT_ROOT/.git/hooks" ]; then
    echo "Error: .git/hooks directory not found. Are you in a git repository?"
    exit 1
fi

# Copy the hook if it exists, or create it
if [ -f "$HOOK_SOURCE" ]; then
    cp "$HOOK_SOURCE" "$HOOK_FILE"
else
    # Create the hook
    cat > "$HOOK_FILE" << 'EOF'
#!/bin/bash
# Pre-commit hook to run formatting and linting before commits

set -e

echo "Running pre-commit checks..."

# Get the directory where the hook is located (project root)
HOOK_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$HOOK_DIR"

# Check if Makefile exists
if [ ! -f "Makefile" ]; then
    echo "Error: Makefile not found"
    exit 1
fi

# Run formatting
echo "Formatting code..."
make format || {
    echo "Error: Formatting failed. Please run 'make format' manually."
    exit 1
}

# Stage any changes made by formatting
git add -u

# Run linting
echo "Linting code..."
make lint || {
    echo "Error: Linting failed. Please fix the issues and try again."
    exit 1
}

echo "Pre-commit checks passed!"
EOF
fi

# Make the hook executable
chmod +x "$HOOK_FILE"

echo "Pre-commit hook installed successfully!"
echo "The hook will now run 'make format' and 'make lint' before each commit."
