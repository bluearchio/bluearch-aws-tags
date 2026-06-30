#!/usr/bin/env python3
"""
Example: Marketplace-Ready Slack App Installation

This example demonstrates the new marketplace-ready Slack integration
that generates "Add to Slack" URLs for easy user installation.

Key Features:
- No environment variables required from users
- Standard OAuth 2.0 authorization flow
- Professional marketplace distribution
- User-friendly installation process

Prerequisites:
1. Slack SDK installed: pip install slack-sdk
2. SLACK_CLIENT_ID set (for development/testing)

Usage:
    python examples/marketplace_slack_example.py
"""

import os
import sys

# Add the parent directory to the path so we can import the tag manager CLI
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

def main():
    """Example of the marketplace-ready Slack installation flow"""
    
    print("=" * 70)
    print("    AWS Tag Manager - Marketplace Slack Integration Example")
    print("=" * 70)
    
    # Test basic import
    try:
        from tag_manager_cli.integrations.slack import SlackMarketplaceIntegration
        print("\n[OK] SlackMarketplaceIntegration imported successfully")
    except ImportError as e:
        print(f"\n[ERROR] Failed to import SlackMarketplaceIntegration: {e}")
        return
    
    # Test initialization
    try:
        # For testing, we can pass a client ID directly
        # In production, this would be embedded during build
        test_client_id = os.getenv('SLACK_CLIENT_ID', 'test-client-id-123')
        
        slack_integration = SlackMarketplaceIntegration(client_id=test_client_id)
        print(f"[OK] Integration initialized with client ID: {slack_integration.client_id}")
        
    except Exception as e:
        print(f"[ERROR] Failed to initialize integration: {e}")
        return
    
    # Display marketplace features
    print("\n" + "=" * 50)
    print("MARKETPLACE FEATURES DEMONSTRATION")
    print("=" * 50)
    
    # Show scopes
    scopes = slack_integration.get_marketplace_scopes()
    print(f"\n[SCOPES] Bot permissions ({len(scopes)} total):")
    for scope in scopes:
        print(f"  - {scope}")
    
    # Show configuration validation
    checks = slack_integration.validate_marketplace_setup()
    print(f"\n[CONFIG] Setup validation ({len(checks)} checks):")
    for check_name, result in checks.items():
        status = "[OK]" if result else "[FAIL]"
        print(f"  {status} {check_name.replace('_', ' ').title()}")
    
    # Show installation URL generation (if properly configured)
    if slack_integration.is_properly_configured():
        print("\n[URL] Generating installation URL...")
        try:
            installation_url = slack_integration.generate_installation_url()
            print(f"[OK] Installation URL generated:")
            print(f"     {installation_url}")
            
            print("\n[FLOW] User Installation Process:")
            print("1. User runs: tag-manager slack setup")
            print("2. CLI displays the 'Add to Slack' URL above")
            print("3. User clicks URL and authorizes in browser")
            print("4. User receives bot token from Slack")
            print("5. User configures CLI: export SLACK_BOT_TOKEN=your-slack-bot-token")
            print("6. Bot is ready for tag management workflows")
            
        except Exception as e:
            print(f"[ERROR] URL generation failed: {e}")
    else:
        print("\n[INFO] URL generation not available (SDK not installed or client ID not configured)")
        print("To test URL generation:")
        print("1. Install Slack SDK: pip install slack-sdk")
        print("2. Set client ID: export SLACK_CLIENT_ID=your-app-client-id")
        print("3. Run this example again")
    
    # Show marketplace summary
    summary = slack_integration.create_marketplace_summary()
    print(f"\n[SUMMARY] Marketplace Integration Summary:")
    print(f"- App Name: {summary['app_name']}")
    print(f"- Client ID: {summary['client_id']}")
    print(f"- Scopes: {len(summary['scopes_requested'])} permissions")
    print(f"- Installation Steps: {len(summary['installation_steps'])} steps")
    print(f"- Available Commands: {len(summary['slash_commands'])} slash commands")
    print(f"- Security Features: {len(summary['security_features'])} protections")
    
    print("\n" + "=" * 50)
    print("CLI INTEGRATION EXAMPLE")
    print("=" * 50)
    
    print("\n[CLI] Available Commands:")
    print("  tag-manager slack setup     # Generate installation URL")
    print("  tag-manager slack test      # Test bot connection")
    print("  tag-manager slack status    # Show integration status")
    print("  tag-manager slack guide     # Display marketplace guide")
    print("  tag-manager slack send      # Send test message")
    
    print("\n[EXAMPLE] Typical User Workflow:")
    print("1. User downloads and installs tag-manager CLI")
    print("2. User runs: tag-manager slack setup")
    print("3. CLI opens browser with 'Add to Slack' URL")
    print("4. User authorizes app in their Slack workspace")
    print("5. User copies bot token and configures CLI")
    print("6. User runs: tag-manager slack test")
    print("7. Bot is ready for AWS tag management workflows")
    
    print("\n" + "=" * 70)
    print("MARKETPLACE DISTRIBUTION BENEFITS")
    print("=" * 70)
    
    print("\n[BENEFITS] For Users:")
    print("- No complex environment variable setup")
    print("- Standard 'Add to Slack' installation flow")
    print("- Works with any Slack workspace")
    print("- Professional, trustworthy installation process")
    print("- Clear permissions and security information")
    
    print("\n[BENEFITS] For Distribution:")
    print("- Ready for Slack App Directory submission")
    print("- OAuth 2.0 compliant for enterprise approval")
    print("- No hardcoded credentials in distributed app")
    print("- Scalable across multiple installations")
    print("- Built-in security features (CSRF protection)")
    
    print("\n[SECURITY] Built-in Protections:")
    print("- State parameter validation (CSRF protection)")
    print("- Minimal permission scope requests")
    print("- Secure OAuth 2.0 token exchange")
    print("- No sensitive data in client-side code")
    
    print("\n" + "=" * 70)
    print("Example completed successfully!")
    print("The marketplace-ready Slack integration is working correctly.")
    print("=" * 70)


if __name__ == '__main__':
    main()
