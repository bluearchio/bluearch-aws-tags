#!/usr/bin/env python3
"""
Example: Simplified Slack OAuth Setup (No ngrok required)

This example demonstrates the new simplified OAuth flow that eliminates
the need for ngrok, callback servers, and complex configuration.

Prerequisites:
1. Slack app created at https://api.slack.com/apps
2. Environment variables set:
   - SLACK_CLIENT_ID
   - SLACK_CLIENT_SECRET  
   - SLACK_SIGNING_SECRET
3. Slack app configured with redirect URI: urn:ietf:wg:oauth:2.0:oob

Usage:
    python examples/slack_simplified_oauth_example.py
"""

import os
import sys

# Add the parent directory to the path so we can import the tag manager CLI
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

def main():
    """Example of using the simplified OAuth setup"""
    
    # Example environment variables (in real use, set these in your shell)
    example_env_vars = {
        'SLACK_CLIENT_ID': 'your-slack-client-id',
        'SLACK_CLIENT_SECRET': 'your-slack-client-secret', 
        'SLACK_SIGNING_SECRET': 'your-slack-signing-secret',
        'SLACK_APPROVAL_CHANNEL': '#aws-tag-approvals'  # Optional
    }
    
    print("=== Simplified Slack OAuth Example ===\n")
    
    print("1. Set required environment variables:")
    for key, value in example_env_vars.items():
        print(f"   export {key}='{value}'")
    
    print("\n2. Configure your Slack app:")
    print("   - Go to https://api.slack.com/apps")
    print("   - Select your app -> OAuth & Permissions -> Redirect URLs")
    print("   - Add: urn:ietf:wg:oauth:2.0:oob")
    print("   - Save settings")
    
    print("\n3. Run OAuth setup in your code:")
    print("""
from tag_manager_cli.integrations.slack import SlackIntegration

# Initialize Slack integration
slack = SlackIntegration()

# Run interactive OAuth setup (no ngrok needed!)
success = slack.setup_oauth_interactive()

if success:
    print("OAuth setup completed successfully!")
    # Your Slack integration is now ready to use
    
    # Example: Send a test notification
    slack.send_notification(
        message="AWS Tag Manager is now connected to Slack!",
        channel="#aws-tag-approvals"
    )
else:
    print("OAuth setup failed. Check your configuration.")
""")
    
    print("\n4. User experience during OAuth:")
    print("   a) Script opens browser to Slack authorization page")
    print("   b) User clicks 'Allow' to authorize the app")
    print("   c) User sees page with authorization code")
    print("   d) User copies the authorization code")
    print("   e) User returns to terminal and pastes code")
    print("   f) OAuth completes automatically")
    
    print("\n5. What's eliminated:")
    print("   - No ngrok installation required")
    print("   - No tunnel setup or management") 
    print("   - No callback server complexity")
    print("   - No network configuration issues")
    print("   - No external dependencies")
    
    print("\n6. Benefits:")
    print("   - Works in any environment (local, containers, CI/CD)")
    print("   - No firewall or network issues")
    print("   - Simple and reliable")
    print("   - One-time setup per workspace")
    print("   - User-friendly terminal interaction")
    
    print("\n=== Example Complete ===")
    print("The simplified OAuth flow is ready to use!")
    print("Just follow steps 1-3 above to get started.")

if __name__ == '__main__':
    main()