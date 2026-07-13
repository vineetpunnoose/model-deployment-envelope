#!/usr/bin/env python3
"""
Run the Envelope Dashboard

Usage:
    python run_dashboard.py

Then open: http://localhost:8080/ui/
"""

import sys
sys.path.insert(0, 'src')

from envelope.ui.dashboard import create_dashboard_app
import uvicorn

if __name__ == "__main__":
    app = create_dashboard_app()

    print("""
    ╔══════════════════════════════════════════════════════════╗
    ║           🛡️  ENVELOPE DASHBOARD                         ║
    ║                                                          ║
    ║   Human-in-the-Loop Interface for AI Governance          ║
    ║                                                          ║
    ║   Open in browser: http://localhost:8080/ui/             ║
    ║                                                          ║
    ║   Features:                                              ║
    ║   • View all model interactions                          ║
    ║   • Review and resolve escalations                       ║
    ║   • Approve/reject access requests                       ║
    ║   • Monitor system health                                ║
    ║                                                          ║
    ╚══════════════════════════════════════════════════════════╝
    """)

    uvicorn.run(app, host="0.0.0.0", port=8080)
