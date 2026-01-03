"""Main entry point for the application.

Based on specification in docs/req.txt section 2.3 (起動方法)

Usage:
    python main.py

The application will start on http://localhost:9200
"""

import os
import sys
from pathlib import Path
import uvicorn
from dotenv import load_dotenv

# Add project root to Python path for module imports
# This ensures modules can be imported correctly on all platforms (Windows/Linux/macOS)
project_root = Path(__file__).parent.absolute()
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# Load environment variables
load_dotenv()

# Get app name from environment
from backend.utils import get_app_name

if __name__ == "__main__":
    # Get server configuration
    # Default to localhost only (127.0.0.1) for security
    # Set SERVER_HOST=0.0.0.0 in .env to allow LAN access
    host = os.getenv("SERVER_HOST", "127.0.0.1")
    port = int(os.getenv("SERVER_PORT", "9200"))

    app_name = get_app_name()
    print("=" * 60)
    print(f"{app_name} - Phase 2 COMPLETE")
    print("=" * 60)
    print(f"Starting server on http://{host}:{port}")
    print("Press Ctrl+C to stop")
    print()
    print("Phase 2 Features:")
    print("  ✓ Multiple project management")
    print("  ✓ Prompt/parser revision tracking")
    print("  ✓ Excel dataset import")
    print("  ✓ Batch execution")
    print("  ✓ System settings API")
    print("  ✓ Job progress tracking")
    print("=" * 60)

    # Import app after sys.path is set
    # This ensures all modules can be found
    from app.main import app

    # Start uvicorn server
    # Pass app object directly instead of string to avoid import issues
    uvicorn.run(
        app,  # Direct app object, not "app.main:app" string
        host=host,
        port=port,
        reload=False,  # Disabled to fix Windows module path issues
        log_level="info",
        timeout_keep_alive=1000,  # 1000 seconds keep-alive for long requests
        timeout_graceful_shutdown=30  # 30 seconds for graceful shutdown
    )
