# Tag Manager CLI - CTO Demo Guide

## Pre-Demo Setup (Do this before the call)

### 1. Generate demo resources (if you have already deleted them)

```bash
aws lambda invoke --function-name lifecycle-demo-resource-generator /tmp/response.json && cat /tmp/response.json
```

### 2. Verify resources were created

```bash
aws lambda list-functions --query "Functions[?starts_with(FunctionName, 'lifecycle-demo-')].FunctionName" | jq .
```

You should see 8 Lambda functions + the generator.

### 3. Clear any existing demo policies

```bash
bluearch-aws-tags lifecycle policies delete
```

---

## DEMO FLOW (Share screen from here)

---

### STEP 1: Show the Problem

**Say:** "Let me show you some demo resources that simulate orphaned cloud resources created by development teams."

```bash
aws lambda list-functions --query "Functions[?starts_with(FunctionName, 'lifecycle-demo-')].[FunctionName]" | jq .
```

**Say:** "These 8 Lambda functions have tags, but no lifecycle management. Without TTL, they run forever wasting money."


### STEP 2: Discover Resources

**Say:** "First, let's scan AWS to discover all resources and import them into Tag Manager."

```bash
bluearch-aws-tags lifecycle scan --discover --services lambda,sns,sqs -y
```

> Note: `-y` skips interactive prompts. Without it, the CLI will ask about discovery and multi-account options.

**Say:** "We found Lambda functions, SNS topics, and SQS queues. The scan imports all resources into our local database so we can apply lifecycle policies to them."


### STEP 3: Create a Policy with "contains" Operator

**Say:** "Now let's create a lifecycle policy. We'll use the 'contains' operator to catch any resource where the Environment tag contains 'demo'."

```bash
bluearch-aws-tags lifecycle policies create
```

**Follow the wizard:**
- Name: `demo-zombie-cleanup`
- Description: `Catch demo resources for cleanup`
- Resource types: Select `lambda_function`, `sns_topic`, `sqs_queue`
- Add condition: Yes
  - Field: `tags.Environment`
  - Operator: `contains` **Say:** "The 'contains' operator is powerful - it matches partial values. So 'demo-test', 'demo-staging', or 'production-demo' would all be caught."
  - Value: `demo`
- add another condition: No
- Add exclusion patterns: No
- TTL (days until expiration) (30): 7
- Warning days (comma-separated) (7,3,1): 7
- Grace period after expiry (days) (7): 1
- Auto-apply to matching resources? [y/n] (y): y
- Create policy? [y/n] (y): y



### STEP 4: Verify the Policy

**Say:** "Let's see our new policy."

```bash
bluearch-aws-tags lifecycle policies list
```


### STEP 5: Scan for Matching Resources

**Say:** "Now let's scan to find all resources matching our policy."

```bash
bluearch-aws-tags lifecycle scan -y
```

**Say:** "Look - it found all the demo resources! They match our policy because their Environment tag contains 'demo'. Notice they have 'No TTL' set yet."


### STEP 6: Apply TTL

**Say:** "Let's apply a 7-day TTL to these resources. This will tag them in AWS with expiration metadata."

```bash
bluearch-aws-tags lifecycle set-ttl
```

**Say:** "Confirm with 'y'. Now all matching resources have a 7-day TTL. The CLI applied AWS tags directly to the resources."


### STEP 7: Verify AWS Tags

**Say:** "Let's verify the tags were applied directly in AWS."

```bash
aws lambda list-tags --resource $(aws lambda get-function --function-name lifecycle-demo-data-processor --query 'Configuration.FunctionArn' --output text) --output table
```

**Say:** "See the 'bluearch:ttl' and 'bluearch:policy' tags? These are now visible in the AWS Console and through any AWS API."


### STEP 8: View Resources with TTL

**Say:** "Let's scan again to see the resources with their new TTL."

```bash
bluearch-aws-tags lifecycle scan -y
```

**Say:** "Now all resources show their TTL status - 6 or 7 days remaining."


### STEP 9: Delete a Resource (Show Regeneration)

**Say:** "Let me show you something interesting. I'll delete one of these Lambda functions."

```bash
aws lambda delete-function --function-name lifecycle-demo-data-processor
```

**Say:** "Now let's trigger the resource generator - this simulates developers creating new resources."

```bash
aws lambda invoke --function-name lifecycle-demo-resource-generator /tmp/response.json && cat /tmp/response.json
```

**Say:** "The resource was recreated! This happens all the time in real environments - resources keep appearing."


### STEP 10: Scan Again - Policy Catches New Resource

**Say:** "Let's scan again. Our policy will automatically catch the newly created resource."

```bash
bluearch-aws-tags lifecycle scan --discover --services lambda -y
```

**Say:** "Look - the new 'data-processor' function was discovered and matched by our policy, but it has 'No TTL' because it was just created. We can apply TTL again to catch it."

```bash
bluearch-aws-tags lifecycle set-ttl
```


### STEP 11: Review Mode (Optional)

**Say:** "For resources approaching expiration, we have an interactive review mode."

```bash
bluearch-aws-tags lifecycle review --include-active
```

**Say:** "Here you can extend TTL, protect resources from deletion, or mark them for immediate deletion."

Press `s` to skip through or `q` to quit.



### STEP 12: Cleanup Demo

**Say:** "Finally, let me show the actual deletion capability."

```bash
bluearch-aws-tags lifecycle delete --dry-run
```

**Say:** "The dry-run shows what would be deleted. In production, the delete command actually removes the AWS resources."

**Say:** "Now let's clean up the demo resources."

```bash
bluearch-aws-tags lifecycle delete
```

## Key Points to Emphasize

1. **Policy-Based**: Define rules once, apply automatically to matching resources
2. **Contains Operator**: Powerful partial matching for flexible policies
3. **AWS Native Tags**: TTL metadata stored as AWS tags, visible everywhere
4. **Continuous Discovery**: New resources are caught on each scan
5. **Safe Deletion**: Dry-run mode, confirmation prompts, audit logging


---

## Vision: 1.0 Release

**What you're seeing today is the CLI foundation.** The 1.0 release will transform this into a fully automated, enterprise-ready platform:

### Full Automation
- **Scheduled scanning**: Resources discovered automatically on a schedule (hourly/daily)
- **Auto-TTL enforcement**: New resources matching policies get TTL applied immediately
- **Automated warnings**: Slack/email notifications sent automatically as resources approach expiration
- **Hands-off deletion**: Expired resources cleaned up without manual intervention

### Web UI Dashboard
- **Policy management**: Create, edit, and manage lifecycle policies through a visual interface
- **Resource explorer**: Browse all discovered resources with filtering and search
- **Compliance dashboard**: Real-time view of tag compliance across accounts
- **Audit trail**: Full history of all lifecycle actions (TTL applied, extended, deleted)
- **Cost insights**: Track savings from automated resource cleanup

### Enterprise Features
- **Multi-account overview**: Single pane of glass across all AWS accounts
- **Role-based access**: Different permissions for viewers, operators, admins
- **Approval workflows**: Require approval before deleting high-value resources
- **Custom integrations**: Webhooks for ITSM, ticketing, and alerting systems

**The CLI you see today becomes the automation engine powering the platform.**


