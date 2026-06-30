#!/usr/bin/env python3
"""
Example script demonstrating the simplified Slack OAuth flow
for AWS Tag Manager CLI

This example shows how to use the new browser-based OAuth flow
instead of running a web server.

Prerequisites:
1. Set environment variables:
   - SLACK_CLIENT_ID
   - SLACK_CLIENT_SECRET  
   - SLACK_SIGNING_SECRET

2. Install dependencies:
   pip install slack-bolt slack-sdk

Usage:
   python examples/slack_oauth_example.py
"""

import os
import sys

# Add the parent directory to the Python path so we can import our modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from tag_manager_cli.integrations.slack import SlackIntegration


def main():
    """Example of setting up Slack OAuth using the new simplified flow"""
    
    # Check if required environment variables are set
    required_vars = ['SLACK_CLIENT_ID', 'SLACK_CLIENT_SECRET', 'SLACK_SIGNING_SECRET']
    missing_vars = [var for var in required_vars if not os.environ.get(var)]
    
    if missing_vars:
        print(f"[ERROR] Missing required environment variables: {', '.join(missing_vars)}")
        print("Please set these variables before running this example.")
        sys.exit(1)
    
    print("=== AWS Tag Manager CLI - Slack OAuth Example ===")
    
    # Initialize the Slack integration
    try:
        slack_integration = SlackIntegration()
        print("[OK] Slack integration initialized")
    except Exception as e:
        print(f"[ERROR] Failed to initialize Slack integration: {e}")
        sys.exit(1)
    
    # Method 1: Interactive setup (recommended for most users)
    print("\n--- Method 1: Interactive Setup ---")
    success = slack_integration.setup_oauth_interactive()
    
    if success:
        print("[OK] Interactive OAuth setup completed successfully!")
        
        # Test the integration
        try:
            result = slack_integration.send_notification(
                message="[TEST] AWS Tag Manager CLI Slack integration is working!",
                channel="#general"  # Change to your preferred channel
            )
            
            if result:
                print("[OK] Test notification sent successfully!")
            else:
                print("[WARN] Test notification failed - check your bot permissions")
                
        except Exception as e:
            print(f"[WARN] Could not send test notification: {e}")
    else:
        print("[ERROR] Interactive OAuth setup failed")
        
        # Method 2: Manual setup (for advanced users or automation)
        print("\n--- Method 2: Manual Setup ---")
        try:
            # Start OAuth flow and get URL
            oauth_url = slack_integration.start_oauth_flow()
            
            # In a real scenario, you might want to:
            # 1. Display this URL to the user
            # 2. Have them complete authorization
            # 3. Get the authorization code back
            # 4. Call complete_oauth_flow(code)
            
            print(f"OAuth URL generated: {oauth_url}")
            print("To complete manually:")
            print("1. Visit the URL above")
            print("2. Authorize the application")
            print("3. Get the authorization code")
            print("4. Call: slack_integration.complete_oauth_flow(code)")
            
        except Exception as e:
            print(f"[ERROR] Manual OAuth setup failed: {e}")


if __name__ == "__main__":
    main()