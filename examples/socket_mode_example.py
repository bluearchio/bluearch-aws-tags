#!/usr/bin/env python3
"""
AWS Tag Manager CLI - Socket Mode Slack Integration Example

This example demonstrates how to use the Socket Mode Slack integration
with proper OAuth handling and production-ready deployment.

Socket Mode eliminates the need for:
- ngrok or port forwarding
- Static OAuth redirect pages  
- Manual authorization code entry
- Complex callback server setup

Requirements:
- All environment variables set (see below)
- Database server running (PostgreSQL recommended)
- Slack app configured with Socket Mode enabled

Usage:
    python examples/socket_mode_example.py

Environment Variables Required:
    SLACK_CLIENT_ID=your_client_id
    SLACK_CLIENT_SECRET=your_client_secret
    SLACK_SIGNING_SECRET=your_signing_secret
    SLACK_APP_TOKEN=xapp-your-app-level-token
    DATABASE_URL=postgresql://user:pass@localhost:5432/dbname
    SLACK_APPROVAL_CHANNEL=#aws-tag-approvals (optional)
"""

import os
import sys
import time
import logging
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from tag_manager_cli.integrations.slack import SlackIntegration

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def validate_environment():
    """Validate all required environment variables are set"""
    required_vars = [
        'SLACK_CLIENT_ID',
        'SLACK_CLIENT_SECRET', 
        'SLACK_SIGNING_SECRET',
        'SLACK_APP_TOKEN',
        'DATABASE_URL'
    ]
    
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    
    if missing_vars:
        print(f"[ERROR] Missing required environment variables: {', '.join(missing_vars)}")
        print("\n[SETUP] Please set the following environment variables:")
        print("export SLACK_CLIENT_ID=your_client_id")
        print("export SLACK_CLIENT_SECRET=your_client_secret") 
        print("export SLACK_SIGNING_SECRET=your_signing_secret")
        print("export SLACK_APP_TOKEN=xapp-your-app-level-token")
        print("export DATABASE_URL=postgresql://user:pass@localhost:5432/dbname")
        print("export SLACK_APPROVAL_CHANNEL=#aws-tag-approvals  # optional")
        return False
    
    return True


def demonstrate_socket_mode():
    """Demonstrate Socket Mode Slack integration"""
    
    print("\n" + "=" * 70)
    print("    AWS Tag Manager CLI - Socket Mode Integration Demo")
    print("=" * 70)
    
    if not validate_environment():
        return False
    
    try:
        # Initialize the Socket Mode Slack integration
        print("\n[ACTION] Initializing Socket Mode Slack integration...")
        slack = SlackIntegration()
        
        # Display setup status
        print("\n[STATUS] Checking Socket Mode setup...")
        slack.print_socket_mode_status()
        
        # Validate setup
        checks = slack.validate_socket_mode_setup()
        if not all(checks.values()):
            print("\n[ERROR] Socket Mode setup validation failed!")
            print("Please resolve the issues above before continuing.")
            return False
        
        # Display installation instructions
        slack.display_installation_instructions()
        
        print("\n[INFO] Socket Mode Integration Ready!")
        print("\nTo start the bot:")
        print("1. Deploy OAuth endpoints (optional Flask app)")
        print("2. Share installation URL with users") 
        print("3. Call slack.start_socket_mode() to begin WebSocket connection")
        
        # Ask user if they want to start Socket Mode
        print("\n" + "=" * 50)
        start_demo = input("Start Socket Mode connection now? [y/N]: ").lower().strip()
        
        if start_demo == 'y':
            print("\n[ACTION] Starting Socket Mode connection...")
            print("Press Ctrl+C to stop the connection\n")
            
            # Start Socket Mode (this will block)
            slack.start_socket_mode()
        else:
            print("\n[INFO] Socket Mode demo completed without starting connection.")
            print("Call slack.start_socket_mode() when ready to go live.")
            
            # Demonstrate other features
            demonstrate_api_features(slack)
        
        return True
        
    except KeyboardInterrupt:
        print("\n[INFO] Socket Mode demo interrupted by user")
        return True
    except Exception as e:
        logger.error(f"Socket Mode demo failed: {e}")
        print(f"\n[ERROR] Demo failed: {e}")
        return False


def demonstrate_api_features(slack: SlackIntegration):
    """Demonstrate API features without starting Socket Mode"""
    print("\n[DEMO] API Features Available:")
    
    # Example approval request
    print("\nExample: Send approval request")
    print("slack.send_approval_request(")
    print("    execution_id='demo-12345',")
    print("    operation='Apply Environment=Production tags',") 
    print("    resource_count=25,")
    print("    details={'summary': 'Tag 25 EC2 instances'})")
    print(")")
    
    # Example notification
    print("\nExample: Send notification")
    print("slack.send_notification(")
    print("    message='AWS tag operation completed successfully',")
    print("    channel='#aws-notifications')")
    print(")")
    
    # Installation info
    print("\nExample: Get installation info")
    print("info = slack.get_installation_info(team_id='T1234567')")
    print("print(info)")


def demonstrate_flask_oauth():
    """Demonstrate Flask OAuth-only app for deployment"""
    print("\n[DEMO] Flask OAuth App for Deployment:")
    print("""
# Deploy this Flask app to provide OAuth endpoints
from tag_manager_cli.integrations.slack import SlackIntegration

slack = SlackIntegration()
app = slack.get_flask_app_for_oauth_only()

# For production deployment:
# gunicorn --bind 0.0.0.0:8000 examples.socket_mode_example:get_flask_app

def get_flask_app():
    slack = SlackIntegration()
    return slack.get_flask_app_for_oauth_only()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)
    """)


if __name__ == "__main__":
    try:
        success = demonstrate_socket_mode()
        
        if success:
            print("\n[OK] Socket Mode demo completed successfully!")
            demonstrate_flask_oauth()
        else:
            print("\n[ERROR] Socket Mode demo failed!")
            sys.exit(1)
            
    except Exception as e:
        logger.error(f"Demo script failed: {e}")
        print(f"\n[ERROR] Demo script failed: {e}")
        sys.exit(1)