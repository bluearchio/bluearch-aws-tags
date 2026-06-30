"""Example of using the configuration system."""

import os
from tag_manager_cli.utils.config import config

def setup_example_config():
    """Set up example configuration values."""
    
    # Example tagging policies
    tagging_policies = {
        "required_tags": ["Environment", "Project", "Owner"],
        "allowed_environments": ["Development", "Staging", "Production"],
        "cost_center_tags": ["CostCenter", "Department", "Team"],
        "compliance_tags": ["DataClassification", "Compliance"]
    }
    
    # Example notification settings
    notification_settings = {
        "cost_threshold": 1000.0,
        "email_alerts": True,
        "slack_webhook": "https://hooks.slack.com/services/YOUR/SLACK/WEBHOOK",
        "alert_frequency": "daily"
    }
    
    # Example dashboard preferences
    dashboard_preferences = {
        "default_date_range": 30,
        "cost_currency": "USD",
        "show_cache_status": True,
        "auto_refresh": True,
        "theme": "dark"
    }
    
    # Store configurations
    config.set_config("tagging_policies", tagging_policies)
    config.set_config("notification_settings", notification_settings)
    config.set_config("dashboard_preferences", dashboard_preferences)
    
    print("✓ Example configuration stored in DynamoDB")


def display_current_config():
    """Display current configuration values."""
    print("Current Configuration:")
    print("=" * 50)
    
    configs = config.list_configs()
    for key, value in configs.items():
        print(f"\n{key.upper()}:")
        if isinstance(value, dict):
            for sub_key, sub_value in value.items():
                print(f"  {sub_key}: {sub_value}")
        else:
            print(f"  {value}")


def get_specific_config():
    """Example of getting specific configuration values."""
    
    # Get tagging policies
    policies = config.get_config("tagging_policies")
    if policies:
        print("Required tags:", policies.get("required_tags", []))
    
    # Get cost threshold
    notifications = config.get_config("notification_settings")
    if notifications:
        threshold = notifications.get("cost_threshold", 0)
        print(f"Cost alert threshold: ${threshold}")


if __name__ == "__main__":
    # Note: This requires AWS credentials and DynamoDB access
    
    # Set AWS profile for testing
    os.environ['AWS_PROFILE'] = 'your-sso-profile'
    
    try:
        # Setup example configuration
        setup_example_config()
        
        # Display all configurations
        display_current_config()
        
        # Get specific configuration values
        get_specific_config()
        
    except Exception as e:
        print(f"Error: {e}")
        print("Make sure AWS_PROFILE is set and you have DynamoDB permissions")