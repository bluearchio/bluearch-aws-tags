"""User-owned Slack App Integration for AWS Tag Manager CLI

Features:
- Generate "Add to Slack" URLs for easy distribution
- Uses a Slack app client ID provided by the user or organization
- Standard OAuth 2.0 authorization flow
- User-friendly installation process

Benefits:
- Click "Add to Slack" and authorize
- Works with any Slack workspace
- Standard Slack app directory installation flow

Installation Flow:
1. User runs CLI command to get installation URL
2. User clicks "Add to Slack" URL in browser
3. User authorizes the app in their Slack workspace
4. User receives bot token for configuration
5. Bot ready for tag management workflows
"""

import os
import logging
import secrets
import webbrowser
import json
import threading
import time
import requests
from typing import Optional, Dict, Any, List
from urllib.parse import urlencode, parse_qs
from datetime import datetime, timedelta

# Import env_config early to ensure .env file is loaded
try:
    from ..utils.env_config import settings
except ImportError:
    # Fallback for direct execution
    import sys
    import os
    parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)
    from tag_manager_cli.utils.env_config import settings

try:
    from slack_sdk import WebClient
    from slack_sdk.errors import SlackApiError
    SLACK_SDK_AVAILABLE = True
except ImportError:
    SLACK_SDK_AVAILABLE = False

# Flask no longer needed - using browser-based OAuth flow
FLASK_AVAILABLE = False
Flask = None

logger = logging.getLogger(__name__)


class SlackMarketplaceIntegration:
    """
    User-owned Slack integration for AWS Tag Manager CLI
    
    Implementation with:
    - Generate "Add to Slack" installation URLs
    - User-provided Slack app client ID
    - Standard OAuth 2.0 authorization flow
    - User-friendly installation guidance
    """
    
    def __init__(self, client_id: Optional[str] = None):
        """
        Initialize marketplace-ready Slack integration
        
        Args:
            client_id: Slack app client ID. If None, reads SLACK_CLIENT_ID.
        """
        if not SLACK_SDK_AVAILABLE:
            raise ImportError(
                "Slack SDK not available. Install with: pip install slack-sdk"
            )
        
        self.client_id = client_id or self._get_client_id_from_env()
        
        # Default approval channel for organizations
        self.approval_channel_default = '#aws-tag-approvals'
        
        # OAuth configuration
        self.oauth_base_url = "https://slack.com/oauth/v2/authorize"
        self.oauth_access_url = "https://slack.com/api/oauth.v2.access"
        
        # OAuth callback configuration
        self.callback_path = '/slack/oauth/callback'
        self.callback_host = 'localhost'
        self.callback_port = 8080
        
        # Token storage configuration
        self.token_storage_path = os.path.expanduser("~/.aws-tag-manager/slack-tokens.json")
        
        # Track installation state
        self.installation_state = None
        self.bot_token = None
        self.team_info = None
        
        # OAuth completion tracking
        self.oauth_result = None
        self.oauth_complete = False
        self._oauth_token_manager = None
        
        logger.info("Marketplace Slack integration initialized successfully")

    def _get_oauth_token_manager(self):
        """Get or create OAuth token manager instance."""
        if self._oauth_token_manager is None:
            try:
                from ..utils.oauth_token_manager import OAuthTokenManager
                self._oauth_token_manager = OAuthTokenManager()
            except Exception as e:
                logger.error(f"Failed to initialize OAuth token manager: {e}")
                return None
        return self._oauth_token_manager
    
    def _get_client_id_from_env(self) -> str:
        """Read the user-owned Slack app client ID from the environment."""
        client_id = os.getenv("SLACK_CLIENT_ID")
        if not client_id:
            raise RuntimeError(
                "Slack Client ID not configured. Set SLACK_CLIENT_ID for your Slack app."
            )
        return client_id
    
    def get_marketplace_scopes(self) -> List[str]:
        """
        Get scopes required for marketplace distribution
        
        These are the minimum scopes needed for AWS tag management workflows
        in a typical Slack workspace.
        """
        return [
            # Core messaging capabilities
            "chat:write",
            "chat:write.public",
            "channels:read",
            "groups:read",
            
            # Interactive components
            "commands",
            "app_mentions:read",
            
            # User and team information
            "users:read",
            "team:read",
            
            # File operations for reports
            "files:write",
            
            # Message history for approval workflows
            "channels:history",
            "groups:history",
            "im:history",
            
            # Direct messaging capabilities
            "im:read",
            "im:write",
            
            # Reactions for user feedback
            "reactions:write"
        ]
    
    def get_user_scopes(self) -> List[str]:
        """
        Get user scopes for marketplace distribution

        Minimal user scopes for security - only request what's absolutely needed.
        """
        return ['users:read', 'users:read.email']  # Needed for local profile lookup
    
    def generate_installation_url(self, redirect_uri: Optional[str] = None, state: Optional[str] = None, use_aws_oauth: bool = True) -> str:
        """
        Generate "Add to Slack" installation URL for marketplace distribution
        
        Args:
            redirect_uri: Optional custom redirect URI (defaults to AWS OAuth service or localhost)
            state: Optional state parameter for security (auto-generated if not provided)
            use_aws_oauth: Whether to use AWS OAuth service (recommended for production)
        
        Returns:
            Complete Slack OAuth authorization URL for installation
        """
        if not self.client_id:
            raise ValueError(
                "Slack Client ID not configured. This should be embedded during production build. "
                "For development, set SLACK_CLIENT_ID environment variable."
            )
        
        # Generate state for security if not provided
        if state is None:
            state = secrets.token_urlsafe(32)
            
        self.installation_state = state
        
        # OAuth parameters
        oauth_params = {
            'client_id': self.client_id,
            'scope': ','.join(self.get_marketplace_scopes()),
            'user_scope': ','.join(self.get_user_scopes()),
            'state': state,
            'response_type': 'code'
        }
        
        # Add redirect URI (use provided one or construct default)
        if redirect_uri:
            oauth_params['redirect_uri'] = redirect_uri
        elif use_aws_oauth:
            # Use AWS OAuth service (production-ready HTTPS endpoint)
            aws_oauth_callback_url = os.getenv('AWS_OAUTH_CALLBACK_URL')
            logger.debug(f"AWS OAuth callback URL from env: {aws_oauth_callback_url}")
            if aws_oauth_callback_url:
                oauth_params['redirect_uri'] = aws_oauth_callback_url
            else:
                # Default AWS OAuth callback URL pattern - should not be used in production
                logger.warning("AWS_OAUTH_CALLBACK_URL not set, using placeholder. Please set AWS_OAUTH_CALLBACK_URL environment variable.")
                oauth_params['redirect_uri'] = "https://your-api-gateway-url.execute-api.region.amazonaws.com/prod/oauth/callback"
        else:
            # Construct default redirect URI for local OAuth callback server
            oauth_params['redirect_uri'] = f"http://{self.callback_host}:{self.callback_port}{self.callback_path}"
        
        # Construct the installation URL
        installation_url = f"{self.oauth_base_url}?{urlencode(oauth_params)}"
        
        logger.info(f"Generated Slack installation URL with state: {state[:8]}...")
        return installation_url
    
    def open_installation_url(self, redirect_uri: Optional[str] = None) -> str:
        """
        Generate installation URL and automatically open it in the user's browser
        
        Args:
            redirect_uri: Optional custom redirect URI
        
        Returns:
            The installation URL that was opened
        """
        installation_url = self.generate_installation_url(redirect_uri=redirect_uri)
        
        try:
            webbrowser.open(installation_url)
            logger.info("Opened installation URL in browser")
        except Exception as e:
            logger.warning(f"Could not open browser automatically: {e}")
        
        return installation_url
    
    def exchange_code_for_token(self, authorization_code: str, client_secret: str, 
                               redirect_uri: Optional[str] = None) -> Dict[str, Any]:
        """
        Exchange authorization code for access token
        
        Args:
            authorization_code: Authorization code received from Slack OAuth
            client_secret: Slack app client secret (required for token exchange)
            redirect_uri: Redirect URI used in original authorization request
        
        Returns:
            Dictionary containing access token and team information
        """
        if not SLACK_SDK_AVAILABLE:
            raise RuntimeError("Slack SDK required for token exchange")
        
        # Prepare token exchange request
        token_params = {
            'client_id': self.client_id,
            'client_secret': client_secret,
            'code': authorization_code
        }
        
        # Use provided redirect_uri or construct the default one used in authorization
        if redirect_uri:
            token_params['redirect_uri'] = redirect_uri
        else:
            # Use the same default redirect URI that was used in authorization
            token_params['redirect_uri'] = f"http://{self.callback_host}:{self.callback_port}{self.callback_path}"
        
        try:
            # Use WebClient to exchange code for token
            client = WebClient()
            response = client.oauth_v2_access(**token_params)
            
            if response['ok']:
                # Store token and team information
                self.bot_token = response['access_token']
                self.team_info = {
                    'team_id': response['team']['id'],
                    'team_name': response['team']['name'],
                    'bot_user_id': response['bot_user_id'],
                    'app_id': response['app_id']
                }
                
                # Store token to persistent storage
                token_data = {
                    'access_token': self.bot_token,
                    'team_info': self.team_info,
                    'installed_at': datetime.now().isoformat(),
                    'response': response
                }
                self._store_token(self.team_info['team_id'], token_data)
                
                logger.info(f"OAuth successful for team: {self.team_info['team_name']}")
                return {
                    'success': True,
                    'access_token': self.bot_token,
                    'team_info': self.team_info,
                    'response': response
                }
            else:
                logger.error(f"OAuth token exchange failed: {response.get('error', 'Unknown error')}")
                return {
                    'success': False,
                    'error': response.get('error', 'Unknown error')
                }
        
        except SlackApiError as e:
            logger.error(f"Slack API error during token exchange: {e}")
            return {
                'success': False,
                'error': str(e)
            }
        except Exception as e:
            logger.error(f"Unexpected error during token exchange: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def send_welcome_message(self, channel: Optional[str] = None) -> bool:
        """
        Send welcome message after successful installation
        
        Args:
            channel: Channel to send welcome message (defaults to general or random)
        
        Returns:
            True if message sent successfully, False otherwise
        """
        if not self.bot_token:
            logger.error("No bot token available - complete OAuth first")
            return False
        
        try:
            client = WebClient(token=self.bot_token)
            
            # If no channel specified, try to find a suitable default
            if not channel:
                # Try common channel names
                for channel_name in ['general', 'random', 'aws-tag-approvals']:
                    try:
                        channels_response = client.conversations_list()
                        for ch in channels_response['channels']:
                            if ch['name'] == channel_name:
                                channel = f"#{channel_name}"
                                break
                        if channel:
                            break
                    except:
                        continue
            
            if not channel:
                logger.warning("Could not find suitable channel for welcome message")
                return False
            
            message = (
                "[OK] AWS Tag Manager Bot installed successfully!\\n\\n"
                "*Getting Started:*\\n"
                "1. Invite me to your approval channel\\n"
                "2. Use slash commands like `/tag-status` to interact\\n"
                "3. Configure your AWS Tag Manager CLI with this bot token\\n\\n"
                "*Available Commands:*\\n"
                "- `/tag-status` - Check pending approvals\\n"
                "- `/tag-approve` - Approve tag operations\\n"
                "- `/tag-reject` - Reject tag operations\\n"
                "- `/tag-history` - View operation history\\n\\n"
                "For more information, mention @aws-tag-manager or send me a direct message."
            )
            
            result = client.chat_postMessage(
                channel=channel,
                text=message
            )
            
            if result['ok']:
                logger.info(f"Welcome message sent to {channel}")
                return True
            else:
                logger.error(f"Failed to send welcome message: {result.get('error', 'Unknown error')}")
                return False
                
        except SlackApiError as e:
            logger.error(f"Slack API error sending welcome message: {e}")
            return False
        except Exception as e:
            logger.error(f"Error sending welcome message: {e}")
            return False
    
    def display_installation_instructions(self, installation_url: str):
        """
        Display user-friendly installation instructions
        
        Args:
            installation_url: The "Add to Slack" URL to display
        """
        print("\\n" + "=" * 70)
        print("          AWS Tag Manager - Slack App Installation")
        print("=" * 70)
        
        print("\\n[STEP 1] Click the 'Add to Slack' URL below:")
        print(f"\\n    {installation_url}")
        
        print("\\n[STEP 2] In your browser:")
        print("  1. Select the Slack workspace to install in")
        print("  2. Review the permissions requested")
        print("  3. Click 'Allow' to authorize the app")
        
        print("\\n[STEP 3] After authorization:")
        print("  1. Token will be stored automatically")
        print("  2. Setup will complete automatically")
        print("  3. Invite the bot to your approval channel:")
        print("     /invite @aws-tag-manager")
        
        print("\\n[STEP 4] Test the installation:")
        print("  1. In Slack, type: /tag-status")
        print("  2. Or mention the bot: @aws-tag-manager help")
        print("  3. Check installation status: tag-manager slack status")
        
        print("\\n[PERMISSIONS REQUESTED]")
        scopes = self.get_marketplace_scopes()
        for scope in scopes:
            print(f"  - {scope}")
        
        print("\\n[SECURITY] This installation URL contains a unique state")
        print("parameter for security. Do not share this URL with others.")
        
        print("\\n" + "=" * 70)
    
    def validate_installation_state(self, received_state: str) -> bool:
        """
        Validate that the received state matches our installation state
        
        Args:
            received_state: State parameter received from OAuth callback
        
        Returns:
            True if state is valid, False otherwise
        """
        if not self.installation_state:
            logger.error("No installation state found - generate URL first")
            return False
        
        if received_state != self.installation_state:
            logger.error("Invalid state parameter - possible CSRF attack")
            return False
        
        logger.info("Installation state validated successfully")
        return True
    
    def test_bot_connection(self) -> Dict[str, Any]:
        """
        Test the bot connection and gather workspace information
        
        Returns:
            Dictionary with connection test results and workspace info
        """
        if not self.bot_token:
            return {
                'success': False,
                'error': 'No bot token available - complete OAuth first'
            }
        
        try:
            client = WebClient(token=self.bot_token)
            
            # Test auth and get bot info
            auth_response = client.auth_test()
            
            if auth_response['ok']:
                # Get team info
                team_response = client.team_info()
                
                return {
                    'success': True,
                    'bot_info': {
                        'user_id': auth_response['user_id'],
                        'user': auth_response['user'],
                        'team_id': auth_response['team_id'],
                        'team': auth_response['team']
                    },
                    'team_info': team_response.get('team', {}) if team_response['ok'] else {},
                    'connection_status': 'active'
                }
            else:
                return {
                    'success': False,
                    'error': f"Auth test failed: {auth_response.get('error', 'Unknown error')}"
                }
        
        except SlackApiError as e:
            return {
                'success': False,
                'error': f"Slack API error: {e}"
            }
        except Exception as e:
            return {
                'success': False,
                'error': f"Connection test failed: {e}"
            }
    
    def create_marketplace_summary(self) -> Dict[str, Any]:
        """
        Create a summary of the marketplace installation for user reference
        
        Returns:
            Dictionary containing installation summary and next steps
        """
        summary = {
            'app_name': 'AWS Tag Manager',
            'client_id': self.client_id,
            'scopes_requested': self.get_marketplace_scopes(),
            'installation_steps': [
                'Click the "Add to Slack" URL',
                'Authorize in your Slack workspace', 
                'Copy the bot token provided',
                'Configure your CLI with the token',
                'Invite bot to approval channels'
            ],
            'slash_commands': [
                '/tag-status - Check pending approvals',
                '/tag-approve - Approve tag operations',
                '/tag-reject - Reject tag operations',
                '/tag-history - View operation history'
            ],
            'required_configuration': [
                'SLACK_BOT_TOKEN - The token received after authorization',
                'SLACK_APPROVAL_CHANNEL - Channel for approval workflows (optional)'
            ],
            'security_features': [
                'State parameter validation for CSRF protection',
                'OAuth 2.0 standard authorization flow',
                'Minimal permission scope requests',
                'Secure token exchange process'
            ]
        }
        
        if self.team_info:
            summary['installed_team'] = self.team_info
        
        return summary
    
    # ===============================
    # Token Storage and OAuth Server Methods
    # ===============================
    
    def _ensure_token_storage_dir(self):
        """Ensure the token storage directory exists"""
        storage_dir = os.path.dirname(self.token_storage_path)
        os.makedirs(storage_dir, exist_ok=True)
    
    def _store_token(self, team_id: str, token_data: Dict[str, Any]):
        """
        Store token data to local JSON file
        
        Args:
            team_id: Slack team/workspace ID
            token_data: Token and team information to store
        """
        try:
            self._ensure_token_storage_dir()
            
            # Load existing tokens or create new storage
            tokens = {}
            if os.path.exists(self.token_storage_path):
                with open(self.token_storage_path, 'r') as f:
                    tokens = json.load(f)
            
            # Store/update token for this team
            tokens[team_id] = token_data
            
            # Write back to file
            with open(self.token_storage_path, 'w') as f:
                json.dump(tokens, f, indent=2)
            
            # Set restrictive permissions
            os.chmod(self.token_storage_path, 0o600)
            
            logger.info(f"Token stored for team {team_id}")
            
        except Exception as e:
            logger.error(f"Failed to store token: {e}")
            raise
    
    def _load_token(self, team_id: str) -> Optional[Dict[str, Any]]:
        """
        Load token data from local storage
        
        Args:
            team_id: Slack team/workspace ID
            
        Returns:
            Token data if found, None otherwise
        """
        try:
            if not os.path.exists(self.token_storage_path):
                return None
                
            with open(self.token_storage_path, 'r') as f:
                tokens = json.load(f)
                
            return tokens.get(team_id)
            
        except Exception as e:
            logger.error(f"Failed to load token for team {team_id}: {e}")
            return None
    
    def get_stored_teams(self) -> Dict[str, Dict[str, Any]]:
        """
        Get all stored team tokens
        
        Returns:
            Dictionary of team_id -> token_data for all stored teams
        """
        try:
            if not os.path.exists(self.token_storage_path):
                return {}
                
            with open(self.token_storage_path, 'r') as f:
                return json.load(f)
                
        except Exception as e:
            logger.error(f"Failed to load stored teams: {e}")
            return {}

    def _store_user_email_locally(self, email: str):
        """
        Store user email locally for local profile use.

        Args:
            email: User email to store
        """
        try:
            import os
            from pathlib import Path
            import json
            from datetime import datetime, timedelta

            # Store in user's config directory
            config_dir = Path.home() / '.config' / 'tag-manager-cli'
            config_dir.mkdir(parents=True, exist_ok=True)
            email_file = config_dir / 'user_email.json'

            # Store with expiration (24 hours)
            email_data = {
                'email': email,
                'stored_at': datetime.now().isoformat(),
                'expires_at': (datetime.now() + timedelta(hours=24)).isoformat()
            }

            with open(email_file, 'w') as f:
                json.dump(email_data, f, indent=2)

            logger.info(f"Stored user email locally: {email}")

        except Exception as e:
            logger.error(f"Failed to store user email locally: {e}")

    def load_token_for_current_context(self) -> bool:
        """
        Load the most recently installed token or prompt user to select
        
        Returns:
            True if token loaded successfully, False otherwise
        """
        stored_teams = self.get_stored_teams()
        
        if not stored_teams:
            logger.info("No stored tokens found")
            return False
        
        if len(stored_teams) == 1:
            # Only one team, use it automatically
            team_id, token_data = next(iter(stored_teams.items()))
            self.bot_token = token_data['access_token']
            self.team_info = token_data['team_info']
            logger.info(f"Loaded token for team: {self.team_info['team_name']}")
            return True
        
        # Multiple teams - use most recent by default
        most_recent_team = None
        most_recent_time = None
        
        for team_id, token_data in stored_teams.items():
            installed_at = token_data.get('installed_at')
            if installed_at:
                try:
                    install_time = datetime.fromisoformat(installed_at)
                    if most_recent_time is None or install_time > most_recent_time:
                        most_recent_time = install_time
                        most_recent_team = (team_id, token_data)
                except ValueError:
                    continue
        
        if most_recent_team:
            team_id, token_data = most_recent_team
            self.bot_token = token_data['access_token']
            self.team_info = token_data['team_info']
            logger.info(f"Loaded most recent token for team: {self.team_info['team_name']}")
            return True
        
        logger.warning("Could not determine which stored token to use")
        return False

    def create_oauth_callback_server(self, client_secret: str) -> Flask:
        """
        Create Flask app for handling OAuth callbacks
        
        Args:
            client_secret: Slack app client secret for token exchange
            
        Returns:
            Configured Flask app instance
        """
        if not FLASK_AVAILABLE:
            raise RuntimeError("Flask not available. Install with: pip install flask")
        
        app = Flask(__name__)
        app.secret_key = secrets.token_urlsafe(32)
        
        # Success page template
        SUCCESS_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AWS Tag Manager - Slack Installation Complete</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; 
               max-width: 600px; margin: 50px auto; padding: 20px; text-align: center; }
        .success { color: #28a745; font-size: 48px; margin-bottom: 20px; }
        .title { color: #333; margin-bottom: 30px; }
        .info { background: #f8f9fa; padding: 20px; border-radius: 8px; margin: 20px 0; text-align: left; }
        .token { font-family: monospace; background: #e9ecef; padding: 10px; border-radius: 4px; 
                 word-break: break-all; margin: 10px 0; }
        .next-steps { text-align: left; }
        .footer { margin-top: 40px; color: #6c757d; font-size: 14px; }
    </style>
</head>
<body>
    <div class="success">[OK]</div>
    <h1 class="title">AWS Tag Manager Slack Installation Complete!</h1>
    
    <div class="info">
        <h3>Installation Summary:</h3>
        <p><strong>Team:</strong> {{ team_name }}</p>
        <p><strong>Bot User ID:</strong> {{ bot_user_id }}</p>
        <p><strong>Installation Status:</strong> <span style="color: #28a745;">Complete</span></p>
    </div>
    
    <div class="info">
        <h3>Next Steps:</h3>
        <div class="next-steps">
            <p>1. <strong>Your bot is ready!</strong> No manual configuration needed.</p>
            <p>2. <strong>Invite the bot to your channels:</strong><br>
               Type <code>/invite @aws-tag-manager</code> in your approval channel</p>
            <p>3. <strong>Test the installation:</strong><br>
               Run <code>tag-manager slack test</code> in your CLI</p>
            <p>4. <strong>Start using slash commands:</strong><br>
               Try <code>/tag-status</code> in Slack</p>
        </div>
    </div>
    
    <div class="footer">
        <p>You can safely close this window. The token has been stored automatically.</p>
        <p>AWS Tag Manager CLI - Marketplace Slack Integration</p>
    </div>
</body>
</html>
        '''
        
        # Error page template
        ERROR_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AWS Tag Manager - Installation Error</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; 
               max-width: 600px; margin: 50px auto; padding: 20px; text-align: center; }
        .error { color: #dc3545; font-size: 48px; margin-bottom: 20px; }
        .title { color: #333; margin-bottom: 30px; }
        .info { background: #f8d7da; color: #721c24; padding: 20px; border-radius: 8px; margin: 20px 0; }
        .footer { margin-top: 40px; color: #6c757d; font-size: 14px; }
    </style>
</head>
<body>
    <div class="error">[ERROR]</div>
    <h1 class="title">Installation Failed</h1>
    
    <div class="info">
        <h3>Error Details:</h3>
        <p>{{ error_message }}</p>
    </div>
    
    <div class="info">
        <h3>What to try:</h3>
        <p>1. Make sure you're using the correct installation URL</p>
        <p>2. Check that your Slack app is configured with the right redirect URI</p>
        <p>3. Try generating a new installation URL: <code>tag-manager slack setup</code></p>
        <p>4. Contact support if the problem persists</p>
    </div>
    
    <div class="footer">
        <p>AWS Tag Manager CLI - Marketplace Slack Integration</p>
    </div>
</body>
</html>
        '''
        
        @app.route(self.callback_path)
        def oauth_callback():
            """Handle OAuth callback from Slack"""
            try:
                # Get authorization code and state from callback
                code = request.args.get('code')
                state = request.args.get('state')
                error = request.args.get('error')
                
                # Check for OAuth errors
                if error:
                    logger.error(f"OAuth error: {error}")
                    self.oauth_result = {'success': False, 'error': error}
                    self.oauth_complete = True
                    return render_template_string(ERROR_TEMPLATE, error_message=f"OAuth error: {error}")
                
                # Validate state parameter
                if not self.validate_installation_state(state):
                    error_msg = "Invalid state parameter - possible security issue"
                    logger.error(error_msg)
                    self.oauth_result = {'success': False, 'error': error_msg}
                    self.oauth_complete = True
                    return render_template_string(ERROR_TEMPLATE, error_message=error_msg)
                
                if not code:
                    error_msg = "No authorization code received"
                    logger.error(error_msg)
                    self.oauth_result = {'success': False, 'error': error_msg}
                    self.oauth_complete = True
                    return render_template_string(ERROR_TEMPLATE, error_message=error_msg)
                
                # Exchange code for token
                token_result = self.exchange_code_for_token(code, client_secret)
                self.oauth_result = token_result
                self.oauth_complete = True
                
                if token_result['success']:
                    # Send welcome message
                    try:
                        self.send_welcome_message()
                    except Exception as e:
                        logger.warning(f"Could not send welcome message: {e}")
                    
                    return render_template_string(
                        SUCCESS_TEMPLATE,
                        team_name=self.team_info['team_name'],
                        bot_user_id=self.team_info['bot_user_id']
                    )
                else:
                    return render_template_string(ERROR_TEMPLATE, error_message=token_result['error'])
                
            except Exception as e:
                logger.error(f"OAuth callback error: {e}")
                self.oauth_result = {'success': False, 'error': str(e)}
                self.oauth_complete = True
                return render_template_string(ERROR_TEMPLATE, error_message=str(e))
        
        @app.route('/health')
        def health_check():
            """Health check endpoint"""
            return {'status': 'ok', 'service': 'aws-tag-manager-oauth'}
        
        return app

    def generate_aws_oauth_url(self, session_id: str) -> str:
        """
        Generate OAuth URL using Slack's distribution URL with AWS callback
        
        Args:
            session_id: Unique session identifier for this auth attempt
            
        Returns:
            OAuth URL for browser-based authentication
        """
        # Use Slack's official distribution URL with all required scopes
        # This matches what's in your Slack app's distribution settings
        scopes = [
            'app_mentions:read',
            'channels:history',
            'channels:read',
            'chat:write',
            'chat:write.public',
            'commands',
            'groups:history',
            'groups:read',
            'im:history',
            'im:read',
            'im:write',
            'incoming-webhook',
            'mpim:history',
            'mpim:read',
            'users:read',
            'users:read.email',
            'team:read',
            'files:write',
            'files:read'
        ]
        
        # Try to get AWS OAuth callback URL if configured
        redirect_uri = None

        # First try environment variable (preferred method)
        redirect_uri = os.getenv('AWS_OAUTH_CALLBACK_URL')
        if redirect_uri:
            logger.debug(f"Using AWS OAuth callback URL from environment: {redirect_uri}")
        else:
            # Fallback to OAuth token manager configuration
            try:
                oauth_token_manager = self._get_oauth_token_manager()
                if oauth_token_manager:
                    oauth_config = oauth_token_manager.get_oauth_configuration()
                    if oauth_config and oauth_config.get('callback_url'):
                        redirect_uri = oauth_config['callback_url']
                        logger.debug(f"Using AWS OAuth callback URL from Parameter Store: {redirect_uri}")
            except Exception as e:
                logger.debug(f"Could not get AWS OAuth callback URL from Parameter Store: {e}")
        
        # User scopes needed for email access
        user_scopes = [
            'users:read',
            'users:read.email'
        ]

        # Build the OAuth URL (matching Slack's distribution URL format)
        oauth_url = (
            f"https://slack.com/oauth/v2/authorize"
            f"?client_id={self.client_id}"
            f"&scope={','.join(scopes)}"
            f"&user_scope={','.join(user_scopes)}"
        )
        
        # Add redirect_uri if we have AWS OAuth service configured
        if redirect_uri:
            oauth_url += f"&redirect_uri={redirect_uri}"
        
        # Add state for session tracking
        oauth_url += f"&state={session_id}"
        
        return oauth_url

    def display_browser_installation_instructions(self, installation_url: str, session_id: str):
        """
        Display installation instructions for browser-based OAuth
        
        Args:
            installation_url: OAuth URL for installation
            session_id: Session ID for tracking
        """
        print("")
        print("=" * 80)
        print("  AWS Tag Manager - Slack Integration Setup")
        print("=" * 80)
        print("")
        print("To complete the Slack integration setup:")
        print("")
        print("1. Click the link below or copy it to your browser:")
        print(f"   {installation_url}")
        print("")
        print("2. Authorize the AWS Tag Manager app in your Slack workspace")
        print("3. You'll be redirected to a success page")
        print("4. Return to this terminal - authentication will complete automatically")
        print("")
        print(f"Session ID: {session_id[:8]}...")
        print("Waiting for authentication to complete...")
        print("")

    def poll_for_oauth_completion(self, session_id: str, timeout: int = 300) -> Dict[str, Any]:
        """
        Poll AWS DynamoDB for OAuth completion
        
        Args:
            session_id: Session ID to poll for
            timeout: Maximum time to wait in seconds
            
        Returns:
            OAuth result dictionary
        """
        oauth_token_manager = self._get_oauth_token_manager()
        if not oauth_token_manager:
            return {'success': False, 'error': 'OAuth token manager not available'}
        
        start_time = time.time()
        poll_interval = 2  # Poll every 2 seconds
        
        while time.time() - start_time < timeout:
            try:
                # Check if OAuth session has completed
                token_data = oauth_token_manager.get_oauth_session_result(session_id)
                
                if token_data:
                    # OAuth completed successfully
                    self.bot_token = token_data.get('access_token')
                    self.team_info = token_data.get('team_info', {})
                    user_email = token_data.get('user_email')
                    self.oauth_complete = True

                    # Store email locally for local profile use
                    if user_email:
                        self._store_user_email_locally(user_email)

                    return {
                        'success': True,
                        'access_token': self.bot_token,
                        'team_info': self.team_info,
                        'user_email': user_email,
                        'session_id': session_id
                    }
                
                # Show progress
                elapsed = int(time.time() - start_time)
                remaining = timeout - elapsed
                print(f"\rWaiting for authentication... ({remaining}s remaining)", end="", flush=True)
                
                time.sleep(poll_interval)
                
            except Exception as e:
                logger.error(f"Error polling for OAuth completion: {e}")
                time.sleep(poll_interval)
        
        print("\n")  # New line after progress indicator
        return {'success': False, 'error': 'Timeout waiting for OAuth completion'}

    def complete_marketplace_installation(self, client_secret: str = None, open_browser: bool = True, timeout: int = 300, manual_mode: bool = False) -> Dict[str, Any]:
        """
        Complete marketplace installation with browser-based OAuth flow
        
        Args:
            client_secret: DEPRECATED - Not needed, kept for compatibility
            open_browser: Whether to automatically open the browser
            timeout: Timeout in seconds to wait for OAuth completion
            manual_mode: DEPRECATED - Not used in browser flow
            
        Returns:
            Dictionary with installation result
        """
        try:
            # Reset OAuth state
            self.oauth_result = None
            self.oauth_complete = False
            
            # Generate unique session ID for this authentication attempt
            import uuid
            session_id = str(uuid.uuid4())
            
            # Generate installation URL pointing to AWS OAuth service
            installation_url = self.generate_aws_oauth_url(session_id)
            logger.info(f"Generated OAuth URL: {installation_url}")
            
            # Display instructions
            self.display_browser_installation_instructions(installation_url, session_id)
            
            # Open browser if requested
            if open_browser:
                try:
                    webbrowser.open(installation_url)
                    logger.info("Opened installation URL in browser")
                except Exception as e:
                    logger.warning(f"Could not open browser: {e}")
            
            # Poll for OAuth completion from AWS
            result = self.poll_for_oauth_completion(session_id, timeout)
            
            if result['success']:
                print(f"\n[OK] Slack installation completed successfully!")
                print(f"Team: {result['team_info'].get('team_name', 'Unknown')}")
                print(f"Bot User ID: {result['team_info'].get('bot_user_id', 'Unknown')}")
                print("Token stored automatically - no manual configuration needed!")
                
                # Store result for compatibility
                self.oauth_result = result
                
                return result
            else:
                return {
                    'success': False,
                    'error': result.get('error', 'Unknown error during installation'),
                    'timeout': 'Timeout' in result.get('error', '')
                }
            
        except Exception as e:
            logger.error(f"Installation error: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    # ===============================
    # Marketplace Utility Methods
    # ===============================
    
    def get_bot_token_for_team(self, team_id: str) -> Optional[str]:
        """
        Get bot token for a specific team (if available)
        
        Args:
            team_id: Slack team/workspace ID
        
        Returns:
            Bot token if available for the team, None otherwise
        """
        if self.team_info and self.team_info.get('team_id') == team_id:
            return self.bot_token
        
        # In a production app, this would query a database
        # For marketplace distribution, tokens are managed per installation
        logger.warning(f"No bot token available for team {team_id}")
        return None
    
    def is_properly_configured(self) -> bool:
        """
        Check if the marketplace integration is properly configured
        
        Returns:
            True if ready for installation URL generation, False otherwise
        """
        return (
            self.client_id and 
            SLACK_SDK_AVAILABLE
        )
    
    def validate_marketplace_setup(self) -> Dict[str, bool]:
        """
        Validate marketplace integration setup and configuration
        
        Returns:
            Dictionary with validation results for each component
        """
        checks = {
            'slack_sdk_available': SLACK_SDK_AVAILABLE,
            'client_id_configured': bool(self.client_id),
            'scopes_defined': len(self.get_marketplace_scopes()) > 0,
            'oauth_urls_configured': bool(self.oauth_base_url and self.oauth_access_url),
            'ready_for_installation': False
        }
        
        # Overall readiness check
        checks['ready_for_installation'] = all([
            checks['slack_sdk_available'],
            checks['client_id_configured'],
            checks['scopes_defined'],
            checks['oauth_urls_configured']
        ])
        
        return checks
    
    def print_marketplace_status(self):
        """
        Print comprehensive marketplace integration status information
        """
        print("\\n" + "=" * 70)
        print("         AWS Tag Manager - Marketplace Integration Status")
        print("=" * 70)
        
        checks = self.validate_marketplace_setup()
        
        print("\\n[CONFIG] Marketplace Configuration:")
        config_items = [
            ('Client ID Configured', bool(self.client_id)),
            ('Slack SDK Available', SLACK_SDK_AVAILABLE),
            ('OAuth Base URL', bool(self.oauth_base_url)),
            ('Default Approval Channel', self.approval_channel_default)
        ]
        
        for item_name, item_status in config_items:
            if isinstance(item_status, bool):
                status = "[OK]" if item_status else "[MISSING]"
                print(f"  {status} {item_name}")
            else:
                print(f"  [OK] {item_name}: {item_status}")
        
        print("\\n[STATUS] Marketplace Setup:")
        for check_name, check_result in checks.items():
            status = "[OK]" if check_result else "[FAIL]"
            print(f"  {status} {check_name.replace('_', ' ').title()}")
        
        print(f"\\n[SCOPES] Bot Permissions Requested ({len(self.get_marketplace_scopes())} total):")
        for scope in self.get_marketplace_scopes():
            print(f"  - {scope}")
        
        if self.team_info:
            print("\\n[INSTALLATION] Current Installation:")
            print(f"  - Team: {self.team_info.get('team_name', 'Unknown')}")
            print(f"  - Team ID: {self.team_info.get('team_id', 'Unknown')}")
            print(f"  - Bot User ID: {self.team_info.get('bot_user_id', 'Unknown')}")
            print(f"  - Token Available: {bool(self.bot_token)}")
        
        if checks['ready_for_installation']:
            print("\\n[OK] Marketplace integration is ready for installation!")
            print("\\n[ACTION] Next steps:")
            print("1. Run generate_installation_url() to create 'Add to Slack' URL")
            print("2. Share the URL with users for easy installation")
            print("3. Users click, authorize, and receive bot token")
            print("4. Configure CLI with received bot token")
        else:
            print("\\n[WARN] Marketplace integration has issues. Please resolve failed checks.")
        
        print("=" * 70)
    
    def display_marketplace_guide(self):
        """
        Display comprehensive marketplace distribution guide
        """
        print("\\n" + "=" * 70)
        print("    AWS Tag Manager - Slack Marketplace Distribution Guide")
        print("=" * 70)
        
        print("\\n[INFO] Marketplace Benefits:")
        print("- No environment variables required from users")
        print("- Standard 'Add to Slack' installation flow")
        print("- Professional marketplace-ready distribution")
        print("- Automatic OAuth 2.0 authorization handling")
        print("- Works with any Slack workspace")
        
        print("\\n[SETUP] Slack App Configuration for Distribution:")
        print("1. Go to: https://api.slack.com/apps")
        print("2. Create new app -> 'From scratch'")
        print("3. Go to 'OAuth & Permissions':")
        print("   - Add Bot Token Scopes (see scopes below)")
        print("   - Set Redirect URLs: https://your-domain.com/oauth/callback")
        print("4. Go to 'Slash Commands' -> Create commands:")
        print("   - /tag-status, /tag-approve, /tag-reject, etc.")
        print("5. Go to 'App Home' -> Configure bot display name")
        print("6. Submit to Slack App Directory (optional)")
        
        print("\\n[DISTRIBUTION] How Users Install:")
        print("1. User runs: tag-manager slack setup")
        print("2. CLI generates and displays 'Add to Slack' URL")
        print("3. User clicks URL and authorizes in browser")
        print("4. User receives bot token on success page")
        print("5. User configures CLI with received token")
        print("6. Bot ready for tag management workflows")
        
        print(f"\\n[SCOPES] Required Bot Token Scopes ({len(self.get_marketplace_scopes())} total):")
        for scope in self.get_marketplace_scopes():
            print(f"   {scope}")
        
        print("\\n[SECURITY] Built-in Security Features:")
        print("- OAuth 2.0 standard authorization flow")
        print("- CSRF protection with state parameter validation")
        print("- Minimal permission scope requests")
        print("- Secure token exchange process")
        print("- No hardcoded credentials in distributed app")
        
        print("\\n[USAGE] CLI Integration:")
        print("```python")
        print("# Generate installation URL")
        print("slack = SlackMarketplaceIntegration()")
        print("url = slack.generate_installation_url()")
        print("slack.display_installation_instructions(url)")
        print("```")
        
        print("\\n" + "=" * 70)
    
    # ===============================
    # Messaging Methods (require bot token)
    # ===============================
    
    def send_notification(
        self,
        message: str,
        channel: Optional[str] = None,
        thread_ts: Optional[str] = None,
        blocks: Optional[list] = None
    ) -> Optional[Dict]:
        """
        Send a notification to Slack (requires bot token from completed OAuth)
        
        Args:
            message: Text message to send
            channel: Target channel (defaults to approval channel)
            thread_ts: Optional thread timestamp for threading
            blocks: Optional Slack Block Kit blocks
        
        Returns:
            Message response dict if successful, None if failed
        """
        if not self.bot_token:
            logger.error("No bot token available - complete OAuth first")
            return None
        
        try:
            client = WebClient(token=self.bot_token)
            channel = channel or self.approval_channel_default
            
            result = client.chat_postMessage(
                channel=channel,
                text=message,
                blocks=blocks,
                thread_ts=thread_ts
            )
            
            if result['ok']:
                return result
            else:
                logger.error(f"Failed to send message: {result.get('error', 'Unknown error')}")
                return None
                
        except SlackApiError as e:
            logger.error(f"Slack API error sending notification: {e}")
            return None
        except Exception as e:
            logger.error(f"Error sending Slack notification: {e}")
            return None


# Marketplace integration instance
_marketplace_integration = None

def get_marketplace_integration(client_id: Optional[str] = None) -> SlackMarketplaceIntegration:
    """Get or create the marketplace Slack integration singleton"""
    global _marketplace_integration
    if _marketplace_integration is None:
        _marketplace_integration = SlackMarketplaceIntegration(client_id=client_id)
    return _marketplace_integration


# Legacy compatibility - keep the old class name as an alias for transition
SlackIntegration = SlackMarketplaceIntegration

def get_slack_integration(_database_url: Optional[str] = None) -> SlackMarketplaceIntegration:
    """Legacy compatibility function - redirects to marketplace integration"""
    # database_url parameter ignored in marketplace version
    return get_marketplace_integration()
