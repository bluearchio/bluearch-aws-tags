#!/usr/bin/env python3
"""
Example: Setting up Slack OAuth with Static Page Redirect

This example demonstrates how to configure and test the Slack OAuth integration
using a static HTML page for authorization code capture, eliminating the need
for ngrok or local callback servers.

Prerequisites:
1. Host the oauth-redirect.html page (see docs/slack-oauth-hosting-guide.md)
2. Configure your Slack app with the hosted redirect URI
3. Set environment variables with your Slack app credentials

Setup Steps:
1. Copy docs/oauth-redirect.html to your hosting service
2. Set SLACK_REDIRECT_URI to your hosted page URL
3. Run this script to test the OAuth flow
"""

import os
import sys
from dotenv import load_dotenv

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load environment variables
load_dotenv()

def setup_environment_example():
    """Show example of setting up environment variables for static redirect OAuth"""
    
    print("=== Slack OAuth Static Redirect Setup Example ===\n")
    
    # Example environment configuration
    example_config = {
        'SLACK_CLIENT_ID': 'your-slack-app-client-id',
        'SLACK_CLIENT_SECRET': 'your-slack-app-client-secret', 
        'SLACK_SIGNING_SECRET': 'your-slack-app-signing-secret',
        'SLACK_REDIRECT_URI': 'https://yourusername.github.io/your-repo/oauth-redirect.html',
        'SLACK_APPROVAL_CHANNEL': '#aws-tag-approvals'
    }
    
    print("1. Required Environment Variables:")
    print("   Add these to your .env file or export them:")
    print()
    for key, value in example_config.items():
        current_value = os.getenv(key)
        status = "[SET]" if current_value else "[MISSING]"
        print(f"   {status} {key}={value}")
    print()
    
    print("2. Hosting Options for oauth-redirect.html:")
    hosting_examples = [
        ("GitHub Pages", "https://yourusername.github.io/your-repo/oauth-redirect.html"),
        ("Netlify", "https://your-app.netlify.app/oauth-redirect.html"),
        ("Vercel", "https://your-app.vercel.app/oauth-redirect.html"),
        ("Surge.sh", "https://your-chosen-name.surge.sh/oauth-redirect.html")
    ]
    
    for service, url in hosting_examples:
        print(f"   - {service}: {url}")
    print()
    
    print("3. Slack App Configuration:")
    print("   - Go to https://api.slack.com/apps")
    print("   - Select your app -> OAuth & Permissions -> Redirect URLs")
    print("   - Add your hosted redirect URI")
    print("   - Save the configuration")
    print()

def test_oauth_flow():
    """Test the OAuth flow with static redirect"""
    
    # Check if environment is configured
    required_vars = ['SLACK_CLIENT_ID', 'SLACK_CLIENT_SECRET', 'SLACK_SIGNING_SECRET', 'SLACK_REDIRECT_URI']
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    
    if missing_vars:
        print(f"[ERROR] Missing environment variables: {', '.join(missing_vars)}")
        print("Please set these variables before running OAuth setup.")
        return False
    
    redirect_uri = os.getenv('SLACK_REDIRECT_URI')
    
    # Validate redirect URI
    if not redirect_uri.startswith('https://'):
        print(f"[ERROR] SLACK_REDIRECT_URI must use HTTPS: {redirect_uri}")
        return False
    
    if 'yourusername.github.io' in redirect_uri:
        print(f"[WARN] Using example redirect URI: {redirect_uri}")
        print("Please update SLACK_REDIRECT_URI to your actual hosted page.")
    
    # Test the integration
    try:
        from tag_manager_cli.integrations.slack import SlackIntegration
        
        print(f"[OK] Testing Slack OAuth with redirect URI: {redirect_uri}")
        
        slack = SlackIntegration()
        
        print("\n=== Starting OAuth Flow ===")
        print("This will open your browser and guide you through the process.")
        print("The authorization code will be captured by your static page.")
        
        # Run interactive OAuth setup
        success = slack.setup_oauth_interactive()
        
        if success:
            print("\n[OK] OAuth setup completed successfully!")
            print("You can now use Slack integration features.")
            return True
        else:
            print("\n[ERROR] OAuth setup failed.")
            return False
            
    except ImportError as e:
        print(f"[ERROR] Failed to import Slack integration: {e}")
        print("Install required packages: pip install slack-bolt python-dotenv")
        return False
    except Exception as e:
        print(f"[ERROR] OAuth test failed: {e}")
        return False

def demonstrate_integration():
    """Demonstrate basic Slack integration functionality"""
    
    try:
        from tag_manager_cli.integrations.slack import SlackIntegration
        
        slack = SlackIntegration()
        
        print("\n=== Testing Basic Integration Features ===")
        
        # Test sending an approval request
        print("\n[TEST] Sending test approval request...")
        message_ts = slack.send_approval_request(
            execution_id="static-oauth-test-001",
            operation="Test Static OAuth Integration", 
            resource_count=2,
            details={
                'summary': 'Testing Slack integration after static OAuth setup',
                'resources': ['ec2:instance/i-test1', 's3:bucket/test-bucket'],
                'tags': {'Environment': 'test', 'OAuth': 'static'},
                'test': True
            }
        )
        
        if message_ts:
            print(f"[OK] Test approval request sent! Message timestamp: {message_ts}")
            print("Check your Slack approval channel for the test message.")
        else:
            print("[WARN] Could not send test approval request.")
            print("This might indicate an issue with the bot token or channel access.")
        
        print("\n[INFO] Available slash commands:")
        commands = [
            "/tag-status - Check pending approvals",
            "/tag-approve <id> - Approve an operation",
            "/tag-reject <id> - Reject an operation",
            "/tag-history - View operation history"
        ]
        for cmd in commands:
            print(f"   - {cmd}")
        
    except Exception as e:
        print(f"[ERROR] Integration test failed: {e}")

def main():
    """Main example function"""
    
    print("AWS Tag Manager CLI - Slack OAuth Static Redirect Example\n")
    
    # Show environment setup
    setup_environment_example()
    
    # Check current configuration
    print("4. Current Configuration Status:")
    redirect_uri = os.getenv('SLACK_REDIRECT_URI')
    if redirect_uri:
        print(f"   [OK] SLACK_REDIRECT_URI is set: {redirect_uri}")
    else:
        print("   [MISSING] SLACK_REDIRECT_URI not set")
    
    client_id = os.getenv('SLACK_CLIENT_ID')
    if client_id:
        print(f"   [OK] SLACK_CLIENT_ID is set")
    else:
        print("   [MISSING] SLACK_CLIENT_ID not set")
    print()
    
    # Ask user what they want to do
    print("What would you like to do?")
    print("1. Test OAuth flow (requires environment setup)")
    print("2. Demonstrate integration features (requires completed OAuth)")
    print("3. Exit")
    
    try:
        choice = input("\nEnter choice (1-3): ").strip()
        
        if choice == '1':
            print("\n=== Testing OAuth Flow ===")
            test_oauth_flow()
        elif choice == '2':
            print("\n=== Demonstrating Integration ===")
            demonstrate_integration()
        elif choice == '3':
            print("Goodbye!")
        else:
            print("Invalid choice. Please run the script again.")
    
    except KeyboardInterrupt:
        print("\nExiting...")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()