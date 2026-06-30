"""
AWS Profile Detector Module

Automatically detects and validates AWS SSO profiles from AWS CLI configuration.
Used during setup to help users select the appropriate AWS profile.
"""

import os
import configparser
from pathlib import Path
from typing import List, Dict, Optional, Tuple
import subprocess
import json
import logging

logger = logging.getLogger(__name__)


class AWSProfileDetector:
    """Detects and validates AWS profiles from AWS CLI configuration."""
    
    def __init__(self):
        """Initialize the AWS Profile Detector."""
        self.aws_config_path = Path.home() / '.aws' / 'config'
        self.aws_credentials_path = Path.home() / '.aws' / 'credentials'
        
    def detect_profiles(self) -> List[Dict[str, str]]:
        """
        Detect all AWS profiles from AWS CLI configuration.
        
        Returns:
            List of dictionaries containing profile information:
            [
                {
                    'name': 'profile-name',
                    'type': 'sso|static|assume_role',
                    'sso_start_url': 'https://...' (if SSO),
                    'sso_account_id': '123456789012' (if SSO),
                    'sso_role_name': 'AdministratorAccess' (if SSO),
                    'region': 'us-east-1'
                }
            ]
        """
        profiles = []
        
        # Check if AWS config file exists
        if not self.aws_config_path.exists():
            logger.warning(f"AWS config file not found at {self.aws_config_path}")
            return profiles
            
        # Parse AWS config file
        config = configparser.ConfigParser()
        try:
            config.read(self.aws_config_path)
        except Exception as e:
            logger.error(f"Error reading AWS config file: {e}")
            return profiles
            
        # Extract profiles
        for section in config.sections():
            profile_info = {}
            
            # Parse profile name
            if section == 'default':
                profile_info['name'] = 'default'
            elif section.startswith('profile '):
                profile_info['name'] = section.replace('profile ', '')
            else:
                continue
                
            # Detect profile type and extract relevant info
            if 'sso_start_url' in config[section]:
                # SSO Profile
                profile_info['type'] = 'sso'
                profile_info['sso_start_url'] = config[section].get('sso_start_url', '')
                profile_info['sso_account_id'] = config[section].get('sso_account_id', '')
                profile_info['sso_role_name'] = config[section].get('sso_role_name', '')
                profile_info['sso_region'] = config[section].get('sso_region', 'us-east-1')
                
            elif 'role_arn' in config[section]:
                # Assume Role Profile
                profile_info['type'] = 'assume_role'
                profile_info['role_arn'] = config[section].get('role_arn', '')
                profile_info['source_profile'] = config[section].get('source_profile', '')
                
            else:
                # Static Credentials (check credentials file)
                if self._has_static_credentials(profile_info['name']):
                    profile_info['type'] = 'static'
                else:
                    profile_info['type'] = 'unknown'
                    
            # Get region
            profile_info['region'] = config[section].get('region', 'us-east-1')
            
            profiles.append(profile_info)
            
        return profiles
    
    def _has_static_credentials(self, profile_name: str) -> bool:
        """
        Check if a profile has static credentials in the credentials file.
        
        Args:
            profile_name: Name of the AWS profile
            
        Returns:
            True if static credentials exist, False otherwise
        """
        if not self.aws_credentials_path.exists():
            return False
            
        credentials = configparser.ConfigParser()
        try:
            credentials.read(self.aws_credentials_path)
            return profile_name in credentials.sections()
        except Exception:
            return False
    
    def validate_profile(self, profile_name: str) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Validate an AWS profile by attempting to get caller identity.
        
        Args:
            profile_name: Name of the AWS profile to validate
            
        Returns:
            Tuple of (is_valid, identity_arn, error_message)
        """
        try:
            # Set environment variable for profile
            env = os.environ.copy()
            env['AWS_PROFILE'] = profile_name
            
            # Try to get caller identity
            result = subprocess.run(
                ['aws', 'sts', 'get-caller-identity', '--output', 'json'],
                capture_output=True,
                text=True,
                env=env,
                timeout=10
            )
            
            if result.returncode == 0:
                # Parse the output
                identity = json.loads(result.stdout)
                arn = identity.get('Arn', '')
                return True, arn, None
            else:
                # Check if it's an SSO login issue
                if 'Token has expired' in result.stderr or 'SSO' in result.stderr:
                    return False, None, "SSO session expired. Please run: aws sso login --profile " + profile_name
                else:
                    return False, None, result.stderr.strip()
                    
        except subprocess.TimeoutExpired:
            return False, None, "AWS CLI command timed out"
        except json.JSONDecodeError:
            return False, None, "Failed to parse AWS CLI output"
        except FileNotFoundError:
            return False, None, "AWS CLI not found. Please install AWS CLI."
        except Exception as e:
            return False, None, str(e)
    
    def get_current_profile(self) -> Optional[str]:
        """
        Get the currently configured AWS profile from environment.
        
        Returns:
            Profile name or None if not set
        """
        return os.environ.get('AWS_PROFILE')
    
    def suggest_profile(self, profiles: List[Dict[str, str]]) -> Optional[str]:
        """
        Suggest the best profile to use based on current environment.
        
        Args:
            profiles: List of detected profiles
            
        Returns:
            Suggested profile name or None
        """
        # First, check if AWS_PROFILE is already set
        current = self.get_current_profile()
        if current:
            # Verify it exists in detected profiles
            for profile in profiles:
                if profile['name'] == current:
                    return current
                    
        # Prefer SSO profiles over static credentials
        sso_profiles = [p for p in profiles if p['type'] == 'sso']
        if sso_profiles:
            # If there's a production profile, suggest it
            for profile in sso_profiles:
                if 'prod' in profile['name'].lower():
                    return profile['name']
            # Otherwise return the first SSO profile
            return sso_profiles[0]['name']
            
        # Return first available profile
        if profiles:
            return profiles[0]['name']
            
        return None
    
    def format_profile_display(self, profile: Dict[str, str]) -> str:
        """
        Format a profile for display to the user.
        
        Args:
            profile: Profile dictionary
            
        Returns:
            Formatted string for display
        """
        name = profile['name']
        profile_type = profile['type']
        
        if profile_type == 'sso':
            account = profile.get('sso_account_id', 'N/A')
            role = profile.get('sso_role_name', 'N/A')
            return f"{name} (SSO - Account: {account}, Role: {role})"
        elif profile_type == 'static':
            return f"{name} (Static Credentials)"
        elif profile_type == 'assume_role':
            role = profile.get('role_arn', 'N/A').split('/')[-1]
            return f"{name} (Assume Role: {role})"
        else:
            return f"{name} (Unknown Type)"
    
    def export_profile_command(self, profile_name: str) -> str:
        """
        Generate the export command for setting AWS_PROFILE.
        
        Args:
            profile_name: Name of the AWS profile
            
        Returns:
            Export command string
        """
        # Detect shell
        shell = os.environ.get('SHELL', '/bin/bash')
        
        if 'fish' in shell:
            return f"set -x AWS_PROFILE {profile_name}"
        elif 'csh' in shell or 'tcsh' in shell:
            return f"setenv AWS_PROFILE {profile_name}"
        else:
            # Default to bash/zsh syntax
            return f"export AWS_PROFILE={profile_name}"