"""Job scheduler for collection engine.

Builds an ordered list of CollectionJobs, prioritizing global services
first and slow services early for better overall throughput.
"""

from typing import List, Optional, Any

from .models import CollectionJob


class JobScheduler:
    """Builds ordered job list for collection."""

    # Lower number = higher priority (runs first).
    # Slow / large services get lower numbers so they start early.
    SERVICE_PRIORITIES = {
        'vpc': 1,
        'iam': 2,
        's3': 3,
        'ec2': 4,
        'rds': 5,
        'ecs': 6,
        'elb': 7,
        'lambda': 8,
        'dynamodb': 9,
        'sns': 10,
        'sqs': 11,
        'cloudwatch': 12,
        'eks': 13,
        'elasticache': 14,
    }

    GLOBAL_SERVICES = {'s3', 'iam'}

    def build_jobs(
        self,
        services: List[str],
        regions: List[str],
        account_id: Optional[str] = None,
        session: Any = None,
    ) -> List[CollectionJob]:
        """Build and return jobs sorted by priority.

        Global services appear first, then regional jobs sorted by priority.
        """
        global_jobs: List[CollectionJob] = []
        regional_jobs: List[CollectionJob] = []

        for service in services:
            priority = self.SERVICE_PRIORITIES.get(service, 99)

            if service in self.GLOBAL_SERVICES:
                global_jobs.append(
                    CollectionJob(
                        service=service,
                        region=None,
                        priority=priority,
                        is_global=True,
                        account_id=account_id,
                        session=session,
                    )
                )
            else:
                for region in regions:
                    regional_jobs.append(
                        CollectionJob(
                            service=service,
                            region=region,
                            priority=priority,
                            is_global=False,
                            account_id=account_id,
                            session=session,
                        )
                    )

        # Sort each group by priority (lower = first)
        global_jobs.sort(key=lambda j: j.priority)
        regional_jobs.sort(key=lambda j: j.priority)

        return global_jobs + regional_jobs
