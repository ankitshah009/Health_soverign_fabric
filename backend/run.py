"""Run the Aubric ClaimGuard backend server."""

from __future__ import annotations

import uvicorn
from dotenv import load_dotenv

from app.config import BACKEND_HOST, BACKEND_PORT

# Load environment variables (config.py does this too, but being explicit)
load_dotenv()

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=BACKEND_HOST,
        port=BACKEND_PORT,
        reload=True,
        log_level="info",
    )
