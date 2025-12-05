"""Main entry point for Prompt Evaluation System.

Based on specification in docs/req.txt section 2.3 (起動方法)

Usage:
    python main.py

The application will start on http://localhost:9200
"""

import os
import uvicorn
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

if __name__ == "__main__":
    # Get server configuration
    host = os.getenv("SERVER_HOST", "127.0.0.1")
    port = int(os.getenv("SERVER_PORT", "9200"))

    print("=" * 60)
    print("Prompt Evaluation System - Phase 2 COMPLETE")
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

    # Start uvicorn server
    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        reload=True,  # Enable auto-reload during development
        log_level="info"
    )
