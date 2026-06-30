"""AWS Resource Groups manager for bluearch:product=tag-manager resources."""

import json
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Optional

from .aws_auth import aws_auth
from .infrastructure_tags import RESOURCE_GROUP_NAME

logger = logging.getLogger(__name__)


@dataclass
class ResourceGroupStatus:
    exists: bool = False
    name: str = RESOURCE_GROUP_NAME
    arn: Optional[str] = None
    resource_count: int = 0
    error: Optional[str] = None


class ResourceGroupManager:
    """Manages the BlueArch-TagManager AWS Resource Group."""

    TAG_FILTER_KEY = "bluearch:product"
    TAG_FILTER_VALUE = "tag-manager"

    def _get_client(self):
        return aws_auth.get_client("resource-groups")

    def get_status(self) -> ResourceGroupStatus:
        """Check if the Resource Group exists and get resource count."""
        try:
            client = self._get_client()
            resp = client.get_group(GroupName=RESOURCE_GROUP_NAME)
            arn = resp.get("Group", {}).get("GroupArn", "")

            # Get resource count
            resource_count = 0
            try:
                paginator = client.get_paginator("list_group_resources")
                for page in paginator.paginate(GroupName=RESOURCE_GROUP_NAME):
                    resource_count += len(
                        page.get("ResourceIdentifiers", [])
                    ) + len(page.get("Resources", []))
            except Exception:
                pass

            return ResourceGroupStatus(
                exists=True,
                arn=arn,
                resource_count=resource_count,
            )
        except client.exceptions.NotFoundException:
            return ResourceGroupStatus(exists=False)
        except Exception as e:
            return ResourceGroupStatus(exists=False, error=str(e))

    def create_or_update(self) -> ResourceGroupStatus:
        """Create or update the tag-based Resource Group."""
        try:
            client = self._get_client()

            query = json.dumps(
                {
                    "ResourceTypeFilters": ["AWS::AllSupported"],
                    "TagFilters": [
                        {
                            "Key": self.TAG_FILTER_KEY,
                            "Values": [self.TAG_FILTER_VALUE],
                        }
                    ],
                }
            )

            # Check if it exists first
            status = self.get_status()
            if status.exists:
                # Update the query in case it changed
                client.update_group_query(
                    GroupName=RESOURCE_GROUP_NAME,
                    ResourceQuery={"Type": "TAG_FILTERS_1_0", "Query": query},
                )
                logger.info("Updated Resource Group: %s", RESOURCE_GROUP_NAME)
            else:
                client.create_group(
                    Name=RESOURCE_GROUP_NAME,
                    Description="All AWS resources managed by BlueArch Tag Manager CLI",
                    ResourceQuery={"Type": "TAG_FILTERS_1_0", "Query": query},
                    Tags={
                        "bluearch:product": "tag-manager",
                        "bluearch:managed-by": "tag-manager-cli",
                    },
                )
                logger.info("Created Resource Group: %s", RESOURCE_GROUP_NAME)

            return self.get_status()
        except Exception as e:
            return ResourceGroupStatus(exists=False, error=str(e))

    def delete(self) -> bool:
        """Delete the Resource Group."""
        try:
            client = self._get_client()
            client.delete_group(GroupName=RESOURCE_GROUP_NAME)
            logger.info("Deleted Resource Group: %s", RESOURCE_GROUP_NAME)
            return True
        except Exception as e:
            logger.error("Failed to delete Resource Group: %s", e)
            return False

    def list_resources(self) -> List[Dict]:
        """List all resources in the Resource Group."""
        try:
            client = self._get_client()
            resources = []
            paginator = client.get_paginator("list_group_resources")
            for page in paginator.paginate(GroupName=RESOURCE_GROUP_NAME):
                for r in page.get("ResourceIdentifiers", []):
                    resources.append(
                        {
                            "arn": r.get("ResourceArn", ""),
                            "type": r.get("ResourceType", ""),
                        }
                    )
                for r in page.get("Resources", []):
                    ident = r.get("Identifier", {})
                    resources.append(
                        {
                            "arn": ident.get("ResourceArn", ""),
                            "type": ident.get("ResourceType", ""),
                        }
                    )
            return resources
        except Exception as e:
            logger.error("Failed to list Resource Group resources: %s", e)
            return []


resource_group_manager = ResourceGroupManager()
