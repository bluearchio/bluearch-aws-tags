export interface PaginatedResponse<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}

export interface HealthResponse {
  status: string
  database: string
  database_type?: string
  tables_exist?: boolean
  resource_count?: number
  version?: string
}

export interface ResourceResponse {
  id: string
  resource_arn: string
  resource_type: string
  service_name: string
  region: string
  account_id: string
  resource_id: string
  created_by?: string
  created_at?: string
  discovered_at?: string
  last_scanned_at?: string
  current_tags?: Record<string, string>
  metadata?: Record<string, unknown>
  expires_at?: string
  lifecycle_state?: string
  delete_after?: string
  protected?: boolean
  compliance_status?: string
}

export interface ResourceStatsResponse {
  total_resources: number
  by_service: Record<string, number>
  by_region: Record<string, number>
  by_account: Record<string, number>
  by_lifecycle_state: Record<string, number>
  by_resource_type: Record<string, number>
  by_compliance_status: Record<string, number>
}

export interface ProductNotification {
  id: string
  source: string
  event_key: string
  severity: string
  title: string
  message?: string
  payload?: Record<string, unknown>
  notification_sent: boolean
  notification_error?: string
  created_at?: string
  sent_at?: string
}

export interface LifecycleDashboardResponse {
  total_resources: number
  active: number
  warned: number
  marked_for_deletion: number
  protected: number
  expired: number
  expiring_7d: number
  expiring_30d: number
  tagged: number
  policies_count: number
}

export interface ExpiringResourceResponse {
  id: string
  resource_arn: string
  resource_type: string
  service_name: string
  region: string
  account_id: string
  expires_at?: string
  lifecycle_state?: string
  protected: boolean
  owner_email?: string
  days_until_expiry?: number
  policy_id?: string
  policy_name?: string
}

export interface TagCondition {
  field: string
  operator: string
  value?: string
}

export interface ExcludePatterns {
  resource_names: string[]
  tags: { key: string; value?: string }[]
}

export interface PolicyResponse {
  id: string
  name: string
  description?: string
  resource_types?: string[]
  regions?: string[]
  account_ids?: string[]
  default_ttl_days?: number
  warning_days?: number
  enabled: boolean
  created_at?: string
  updated_at?: string
  resource_count?: number
  conditions?: { tags: TagCondition[] }
  exclude_patterns?: ExcludePatterns
  warning_schedule?: number[]
  grace_period_days?: number
  auto_apply?: boolean
}

// --- Mutation types ---

export interface PolicyCreateRequest {
  name: string
  description?: string
  resource_types?: string[]
  ttl_days: number
  warning_days?: number
  priority?: number
  enabled?: boolean
  conditions?: { tags: TagCondition[] }
  exclude_patterns?: ExcludePatterns
  warning_schedule?: number[]
  grace_period_days?: number
  auto_apply?: boolean
}

export interface PolicyUpdateRequest {
  name?: string
  description?: string
  resource_types?: string[]
  ttl_days?: number
  warning_days?: number
  priority?: number
  enabled?: boolean
}

export interface SetTTLRequest {
  resource_ids?: string[]
  resource_arns?: string[]
  services?: string[]
  ttl_days: number
  apply_aws_tags?: boolean
}

export interface ExtendTTLRequest {
  resource_ids?: string[]
  resource_arns?: string[]
  days: number
  apply_aws_tags?: boolean
}

export interface ProtectRequest {
  resource_ids?: string[]
  resource_arns?: string[]
  protect: boolean
}

export interface MutationResult {
  affected_count: number
  details?: string
}

export interface TTLPreviewItem {
  resource_id: string
  resource_arn: string
  service_name: string
  region: string
  account_id: string
  current_expires_at?: string
  new_expires_at: string
  tag_key: string
  tag_value: string
}

export interface TTLPreviewResponse {
  resources: TTLPreviewItem[]
  total_count: number
  ttl_days: number
  apply_aws_tags: boolean
}

// --- Job types ---

export interface ScanWarning {
  type?: string
  service?: string
  severity?: string
  account_id?: string
  region?: string
  code?: string
  message: string
  suggestion?: string
  action_label?: string
  action_route?: string
}

export interface PermissionErrorDetail {
  type?: string
  service?: string
  region?: string
  account_id?: string
  code?: string
  message?: string
  resource_name?: string
  resource_types?: string[]
  suggestion?: string
}

export interface ScanProgressData {
  total_jobs?: number
  completed_jobs?: number
  total_resources?: number
  by_service?: Record<string, number>
  by_region?: Record<string, number>
  current_service?: string
  current_region?: string
  errors_count?: number
  permission_errors_count?: number
  permission_error_details?: PermissionErrorDetail[]
  permission_error_resource_types?: string[]
  warnings?: ScanWarning[]
  warnings_count?: number
  account_id?: string
  // Multi-account fields
  accounts_total?: number
  accounts_completed?: number
  by_account?: Record<string, number>
}

export interface JobResponse {
  id: string
  job_type: string
  status: string
  progress: number
  progress_message?: string
  progress_data?: ScanProgressData
  result?: Record<string, unknown>
  error?: string
  created_at: string
  started_at?: string
  completed_at?: string
}

export interface JobSubmittedResponse {
  job_id: string
  job_type: string
  status: string
  message: string
}

// --- AI Chat types ---

export interface ChatRequest {
  question: string
  model: string
  session_id?: string
}

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  timestamp: string
}

export interface SSEEvent {
  type: 'text' | 'done' | 'error' | 'tool_call' | 'tool_result' | 'suggestions'
  content: string | string[] | Record<string, unknown>
}

export interface ConversationSummary {
  id: string
  title: string
  model: string
  message_count: number
  updated_at: string
}

export interface ConversationMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  tool_calls?: Record<string, unknown>[]
  tokens?: { input: number; output: number }
  created_at: string
}

export interface IAMPolicyStatement {
  Sid: string
  Effect: string
  Action: string | string[]
  Resource: string | string[]
}

export interface ModelInfo {
  alias: string
  model_id: string
  description: string
}

export interface ModelsResponse {
  models: ModelInfo[]
  default: string
}

// --- Cost types ---

export interface CostSummaryResponse {
  total_cost: number
  currency: string
  start_date: string
  end_date: string
  source: string
  by_service?: Record<string, unknown>[]
}

export interface CostByServiceResponse {
  items: Record<string, unknown>[]
  total_cost: number
  currency: string
  start_date: string
  end_date: string
  source: string
}

export interface CostByAccountResponse {
  items: Record<string, unknown>[]
  total_cost: number
  currency: string
  start_date: string
  end_date: string
  source: string
}

export interface CostForecastResponse {
  forecast_days: number
  method: string
  projected_cost: number
  currency: string
  daily_average: number
  based_on_days: number
  source: string
}

export interface DailyCostItem {
  date: string
  cost: number
  amortized_cost?: number
}

export interface DailyCostResponse {
  items: DailyCostItem[]
  total_cost: number
  currency: string
  start_date: string
  end_date: string
  source: string
}

export interface CostByRegionItem {
  region: string
  cost: number
}

export interface CostByRegionResponse {
  items: CostByRegionItem[]
  total_cost: number
  currency: string
  start_date: string
  end_date: string
  source: string
}

export interface TopResourceItem {
  resource_id: string
  service?: string
  cost: number
}

export interface TopResourcesResponse {
  items: TopResourceItem[]
  total_cost: number
  currency: string
  source: string
  cur_required: boolean
}

export interface PricingModelItem {
  pricing_model: string
  cost: number
}

export interface PricingBreakdownResponse {
  items: PricingModelItem[]
  total_cost: number
  currency: string
  source: string
  cur_required: boolean
}

export interface SavingsPlanItem {
  rate_type?: string
  covered_cost: number
  commitment: number
  utilization_percent?: number
}

export interface SavingsPlansResponse {
  items: SavingsPlanItem[]
  total_commitment: number
  average_utilization?: number
  currency: string
  source: string
  cur_required: boolean
}

// --- Setup types ---

export interface SetupCheckItem {
  name: string
  status: 'ok' | 'warning' | 'error'
  message: string
  details?: Record<string, unknown>
}

export interface SetupValidateResponse {
  overall: 'healthy' | 'degraded' | 'unhealthy'
  checks: SetupCheckItem[]
}

// --- CUR types ---

export interface CURStatusResponse {
  found: boolean
  status?: string
  report_name?: string
  s3_bucket?: string
  athena_database?: string
  athena_table?: string
  region?: string
  message: string
}

export interface CURDeployResponse {
  success: boolean
  job_id?: string
  stack_id?: string
  message: string
  estimated_ready_hours: number
}

// --- Compliance types ---

export interface ComplianceAccessResponse {
  has_access: boolean
  org_id?: string
  master_account?: string
  current_account?: string
  tag_policies_enabled?: boolean
  error?: string
}

export interface OrgPolicyResponse {
  id: string
  name: string
  description?: string
  arn?: string
  type?: string
  aws_managed?: boolean
}

export interface NonCompliantResource {
  resource_arn?: string
  resource_type?: string
  region?: string
  account_id?: string
  keys_with_noncompliant_values?: string[]
  missing_tags?: string[]
}

export interface ComplianceCheckResponse {
  success: boolean
  resources: NonCompliantResource[]
  count: number
  has_more: boolean
  error?: string
}

export interface EffectivePolicyResponse {
  target_id: string
  content?: Record<string, unknown>
  error?: string
}

// --- Multi-Account types ---

export interface StackInstanceInfo {
  account_id: string
  region: string
  status: string
  status_reason?: string
}

export interface StackSetStatusResponse {
  exists: boolean
  status?: string
  status_reason?: string
  template_version?: string
  versions_match?: boolean
  local_version?: string
  instance_count: number
  instances: StackInstanceInfo[]
}

export interface AccountRecord {
  account_id: string
  account_name?: string
  role_arn?: string
  enabled_for_discovery: boolean
  access_check_status?: string
  last_discovery_at?: string
  total_resources_discovered?: number
}

export interface AccountsListResponse {
  accounts: AccountRecord[]
  total: number
}

export interface DeployRequest {
  accounts?: string[]
  regions?: string[]
  force_recreate?: boolean
}

export interface AccountValidationResponse {
  is_management_account: boolean
  is_delegated_admin: boolean
  can_deploy: boolean
  current_account_id?: string
  management_account_id?: string
  organization_id?: string
  error?: string
  guidance?: string
}

// --- Assume-Role types ---

export interface AssumeRoleStatusResponse {
  configured: boolean
  enabled: boolean
  role_arn?: string
  role_name?: string
  account_id?: string
  external_id_configured: boolean
  last_used_at?: string
  stack_exists: boolean
  stack_status?: string
}

export interface AssumeRoleConfigRecord {
  id: string
  account_id: string
  role_arn: string
  role_name: string
  is_active: boolean
  enabled: boolean
  external_id_configured: boolean
  last_used_at?: string
  created_at?: string
}

export interface AssumeRoleDeployRequest {
  trust_mode?: string
  specific_arn?: string
  external_id?: string
  role_name?: string
}

export interface AssumeRoleDisableRequest {
  delete_stack?: boolean
}

// --- Templates ---

export interface TemplateMetadata {
  name: string
  description: string
  public_url: string
  version: string
}

export interface TemplateDetail extends TemplateMetadata {
  content: string
}

// --- Cost Analytics (new) ---

export interface CostGenericResponse {
  items: Record<string, unknown>[]
  total_cost: number
  currency: string
  start_date: string
  end_date: string
  source: string
}

export interface CostCommitmentsResponse {
  items: Record<string, unknown>[]
  source: string
}

export interface CostServiceDeepDiveResponse {
  service: string
  view: string
  items: Record<string, unknown>[]
  total_cost?: number
  currency: string
  start_date: string
  end_date: string
  source: string
}

export interface CostTrendsRequest {
  tag_key: string
  periods?: number
  granularity?: string
  tag_value?: string
}

export interface CostTrendsResponse {
  tag_key: string
  trends: Record<string, unknown>[]
  summary?: Record<string, unknown>
  source: string
}

export interface CostAnomaliesRequest {
  tag_key: string
  percent_threshold?: number
  absolute_threshold?: number
}

export interface CostAnomaliesResponse {
  tag_key: string
  anomalies: Record<string, unknown>[]
  total_anomalies: number
  source: string
}

export interface CostChargebackRequest {
  tag_key: string
  start_date: string
  end_date: string
  granularity?: string
  group_by?: string
}

export interface CostChargebackResponse {
  tag_key: string
  report: Record<string, unknown>
  source: string
}

export interface CostGapsRequest {
  required_tags: string[]
  days?: number
  min_cost?: number
  show_roi?: boolean
}

export interface CostGapsResponse {
  gaps: Record<string, unknown>
  source: string
}

// --- Compliance CRUD (new) ---

export interface OrgPolicyCreateRequest {
  name: string
  description?: string
  content: Record<string, unknown>
}

export interface OrgPolicyUpdateRequest {
  name?: string
  description?: string
  content?: Record<string, unknown>
}

export interface OrgPolicyDetailResponse {
  id: string
  name: string
  description?: string
  arn?: string
  content?: Record<string, unknown>
  targets?: Record<string, unknown>[]
  aws_managed?: boolean
  create_date?: string
  update_date?: string
}

export interface PolicyTargetsResponse {
  targets: Record<string, unknown>[]
  count: number
}

export interface OrgStructureResponse {
  root_id?: string
  ous: Record<string, unknown>[]
  accounts: Record<string, unknown>[]
}

export interface OrgMutationResponse {
  success: boolean
  message: string
  error?: string
}

// --- Lifecycle Match Preview ---

export interface MatchPreviewRequest {
  resource_types?: string[]
  conditions?: { tags: TagCondition[] }
  exclude_patterns?: ExcludePatterns
}

export interface MatchedResourceItem {
  id: string
  resource_arn: string
  resource_type: string
  service_name: string
  region: string
  account_id: string
  has_ttl: boolean
}

export interface MatchPreviewResponse {
  matched_count: number
  resources: MatchedResourceItem[]
}

export interface PolicySaveResult {
  policy: PolicyResponse
  matched_count: number
  ttl_applied_count: number
}

// --- Lifecycle Review (new) ---

export interface ReviewResourceResponse {
  id: string
  resource_arn: string
  resource_type: string
  service_name: string
  region: string
  account_id: string
  expires_at?: string
  lifecycle_state?: string
  protected: boolean
  owner_email?: string
  days_until_expiry?: number
  current_tags?: Record<string, string>
  lifecycle_policy_id?: string
  policy_id?: string
  policy_name?: string
}

export interface ReviewActionRequest {
  resource_ids: string[]
  days?: number
  reason?: string
}

export interface ExecuteDeleteRequest {
  resource_ids: string[]
  confirmation: string
}

export interface AuditLogEntry {
  id: string
  resource_arn: string
  resource_id?: string
  operation: string
  old_state?: string
  new_state?: string
  old_expires_at?: string
  new_expires_at?: string
  success: boolean
  error_message?: string
  executed_by?: string
  executed_at?: string
  operation_details?: Record<string, unknown>
}

// --- Local user types ---

export interface UserResponse {
  sub: string
  email: string
  groups: string[]
  tier: 'free' | 'pro' | 'enterprise'
}

export interface MeResponse {
  user: UserResponse | null
  auth_disabled: boolean
}

// Infrastructure Status
export interface StackSetSummary {
  name: string
  component: string
  status: string
  instance_count: number
  healthy_count: number
  failed_count: number
  version?: string
}

export interface StackInfo {
  stack_name: string
  stack_type: string
  component: string
  status: string
  region: string
  last_updated?: string
  version?: string
  outputs?: Record<string, string>
}

export interface ResourceGroupInfo {
  exists: boolean
  name: string
  arn?: string
  resource_count: number
  error?: string
}

export interface InfrastructureHealthSummary {
  total_stacksets: number
  total_instances: number
  total_stacks: number
  healthy: number
  degraded: number
  failed: number
  overall_status: string
}

export interface InfrastructureStatusResponse {
  health: InfrastructureHealthSummary
  stacksets: StackSetSummary[]
  stacks: StackInfo[]
  resource_group: ResourceGroupInfo
  account_id?: string
  organization_id?: string
  region?: string
  local_version?: string
}

// --- Account Context types ---

export interface AccountContextResponse {
  id: string
  account_id: string
  account_alias?: string
  aws_profile?: string
  region?: string
  user_arn?: string
  is_current: boolean
  created_at?: string
  last_used_at?: string
}

export interface AccountContextListResponse {
  contexts: AccountContextResponse[]
  current_account_id?: string
}

export interface ContextGateResponse {
  status: 'ok' | 'first_run' | 'switch_required' | 'add_required'
  message: string
  context?: AccountContextResponse
}


// --- Event Tracking types ---

export interface EventTrackingInstanceStatus {
  account_id: string
  region: string
  status: string
  queue_url: string
  queue_arn: string
  stack_id: string
  last_polled_at?: string
  last_event_at?: string
  messages_processed: number
  events_today: number
  error_message?: string
}

export interface EventTrackingStatusResponse {
  stackset_exists: boolean
  stackset_status: string
  instances: EventTrackingInstanceStatus[]
  service_running: boolean
  service_paused: boolean
  total_queues: number
  active_queues: number
}

// --- Permission types ---

export interface ServicePermissionStatus {
  available: boolean
  missing: string[]
}

export interface FeatureStatus {
  available: boolean
  partial?: boolean
  missing?: string[]
  services?: Record<string, ServicePermissionStatus>
  note?: string
}

export interface UpgradePath {
  next_tier: string
  action: string
  unlocks: string[]
}

export interface PermissionStatusResponse {
  account_id: string
  tier: string
  checked_at?: string
  expires_at?: string
  features: Record<string, FeatureStatus>
  upgrade_path?: UpgradePath
}

export interface LicenseResponse {
  tier: 'free' | 'pro' | 'enterprise'
  customer: string | null
  org_id: string | null
  expires_at: string | null
  max_users: number | null
  features: Record<string, boolean>
}

export interface LicenseActivateRequest {
  key: string
}

export interface UpgradeRequestBody {
  email: string
}

export interface UpgradeRequestResponse {
  message: string
  request_id: string
}

// --- Resource Graph types ---

export interface GraphNodeResponse {
  id: string
  resource_id: string
  resource_type: string
  service_name: string
  region: string
  account_id: string
  name?: string
  lifecycle_state?: string
  category: number
  symbol_size: number
  // Overlay fields
  expires_at?: string
  protected?: boolean
  compliance_status?: string
  missing_tags?: string[]
}

export interface GraphEdgeResponse {
  source: string
  target: string
  relationship_type: string
  label?: string
}

export interface GraphResponse {
  nodes: GraphNodeResponse[]
  edges: GraphEdgeResponse[]
  categories: { name: string; color: string }[]
  total_relationships: number
  truncated: boolean
}

export interface GraphStatsResponse {
  total_relationships: number
  by_type: Record<string, number>
  most_connected: { arn: string; edge_count: number }[]
}

export interface GraphFiltersResponse {
  vpc_ids: string[]
  regions: string[]
  account_ids: string[]
  services: string[]
  relationship_types: string[]
}

export interface BlastRadiusTarget {
  arn: string
  name: string
  service: string
  resource_type: string
}

export interface BlastRadiusAffected {
  arn: string
  name: string
  service: string
  resource_type: string
  impact: 'orphaned' | 'disconnected' | 'cascade'
  relationship: string
  depth: number
  lifecycle_state?: string
  protected: boolean
}

export interface BlastRadiusDependency {
  arn: string
  name: string
  service: string
  resource_type: string
  relationship: string
}

export interface BlastRadiusSummary {
  total_affected: number
  orphaned: number
  disconnected: number
  cascade: number
  protected_affected: number
}

export interface BlastRadiusResponse {
  target: BlastRadiusTarget
  affected: BlastRadiusAffected[]
  summary: BlastRadiusSummary
  dependencies: BlastRadiusDependency[]
  truncated: boolean
}

export interface NotificationEvent {
  id: string
  source: string
  event_key: string
  severity: string
  title: string
  message?: string
  payload: Record<string, unknown>
  notification_sent: boolean
  notification_error?: string
  created_at?: string
  sent_at?: string
}
