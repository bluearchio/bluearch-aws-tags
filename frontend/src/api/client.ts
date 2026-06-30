import type {
  PaginatedResponse,
  HealthResponse,
  ResourceResponse,
  ResourceStatsResponse,
  LifecycleDashboardResponse,
  ExpiringResourceResponse,
  PolicyResponse,
  PolicyCreateRequest,
  PolicyUpdateRequest,
  SetTTLRequest,
  ExtendTTLRequest,
  ProtectRequest,
  MutationResult,
  TTLPreviewResponse,
  MatchPreviewRequest,
  MatchPreviewResponse,
  MatchedResourceItem,
  PolicySaveResult,
  JobResponse,
  JobSubmittedResponse,
  ChatRequest,
  SSEEvent,
  ModelsResponse,
  ConversationSummary,
  ConversationMessage,
  CostSummaryResponse,
  CostByServiceResponse,
  CostByAccountResponse,
  CostForecastResponse,
  CostGenericResponse,
  CostCommitmentsResponse,
  CostServiceDeepDiveResponse,
  CostTrendsRequest,
  CostTrendsResponse,
  CostAnomaliesRequest,
  CostAnomaliesResponse,
  CostChargebackRequest,
  CostChargebackResponse,
  CostGapsRequest,
  CostGapsResponse,
  SetupValidateResponse,
  CURStatusResponse,
  CURDeployResponse,
  ComplianceAccessResponse,
  OrgPolicyResponse,
  ComplianceCheckResponse,
  EffectivePolicyResponse,
  OrgPolicyCreateRequest,
  OrgPolicyUpdateRequest,
  OrgPolicyDetailResponse,
  PolicyTargetsResponse,
  OrgStructureResponse,
  OrgMutationResponse,
  ReviewResourceResponse,
  ReviewActionRequest,
  ExecuteDeleteRequest,
  AuditLogEntry,
  StackSetStatusResponse,
  AccountsListResponse,
  AccountValidationResponse,
  DeployRequest,
  AssumeRoleStatusResponse,
  AssumeRoleConfigRecord,
  AssumeRoleDeployRequest,
  AssumeRoleDisableRequest,
  TemplateMetadata,
  TemplateDetail,
  InfrastructureStatusResponse,
  ResourceGroupInfo,
  EventTrackingStatusResponse,
  AccountContextResponse,
  AccountContextListResponse,
  ContextGateResponse,
  PermissionStatusResponse,
  GraphResponse,
  GraphStatsResponse,
  GraphFiltersResponse,
  BlastRadiusResponse,
  NotificationEvent,
} from '@/types/api'

import { useToast } from '@/composables/useToast'

const BASE_URL = import.meta.env.DEV ? 'http://localhost:8096' : ''

function formatErrorDetail(detail: unknown): string {
  if (typeof detail === 'string') return detail
  // FastAPI validation errors return detail as array of objects
  if (Array.isArray(detail)) {
    return detail.map((d: Record<string, unknown>) => {
      const loc = Array.isArray(d.loc) ? d.loc.join(' > ') : ''
      return loc ? `${loc}: ${d.msg}` : String(d.msg || d)
    }).join('; ')
  }
  if (detail && typeof detail === 'object') {
    const d = detail as Record<string, unknown>
    if (d.message) return String(d.message)
    if (d.msg) return String(d.msg)
  }
  return ''
}

function errorTitle(status: number): string {
  if (status === 400) return 'Bad Request'
  if (status === 401) return 'Unauthorized'
  if (status === 403) return 'Access Denied'
  if (status === 404) return 'Not Found'
  if (status === 422) return 'Validation Error'
  if (status === 429) return 'Rate Limited'
  if (status === 500) return 'Internal Server Error'
  if (status === 502) return 'Bad Gateway'
  if (status === 503) return 'Service Unavailable'
  if (status === 504) return 'Gateway Timeout'
  return `Error ${status}`
}

function notifyError(status: number, detail: unknown, fallback: string) {
  const toast = useToast()
  const message = formatErrorDetail(detail) || fallback
  toast.error(errorTitle(status), message)
}

function notifyNetworkError(err: unknown) {
  const toast = useToast()
  const msg = err instanceof Error ? err.message : 'Unknown error'
  toast.error('Network Error', `Unable to reach server: ${msg}`)
}

async function request<T>(
  path: string,
  params?: Record<string, string | number | boolean | undefined>,
): Promise<T> {
  const url = new URL(`${BASE_URL}${path}`, window.location.origin)
  if (params) {
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== '') {
        url.searchParams.set(key, String(value))
      }
    })
  }
  let response: Response
  try {
    response = await fetch(url.toString(), { credentials: 'include' })
  } catch (err) {
    notifyNetworkError(err)
    throw err
  }
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    const detail = body?.detail
    if (response.status !== 401) {
      notifyError(response.status, detail, response.statusText)
    }
    throw new Error(formatErrorDetail(detail) || `API error: ${response.status} ${response.statusText}`)
  }
  return response.json()
}

async function requestMutation<T>(
  method: 'POST' | 'PATCH' | 'DELETE',
  path: string,
  body?: unknown,
): Promise<T> {
  const url = `${BASE_URL}${path}`
  let response: Response
  try {
    response = await fetch(url, {
      method,
      headers: body !== undefined ? { 'Content-Type': 'application/json' } : {},
      body: body !== undefined ? JSON.stringify(body) : undefined,
      credentials: 'include',
    })
  } catch (err) {
    notifyNetworkError(err)
    throw err
  }
  if (!response.ok) {
    const data = await response.json().catch(() => null)
    const detail = data?.detail
    if (response.status !== 401) {
      notifyError(response.status, detail, response.statusText)
    }
    throw new Error(formatErrorDetail(detail) || `API error: ${response.status} ${response.statusText}`)
  }
  if (response.status === 204) return undefined as T
  return response.json()
}

async function* requestSSE(path: string, body: unknown): AsyncGenerator<SSEEvent> {
  const url = `${BASE_URL}${path}`
  let response: Response
  try {
    response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      credentials: 'include',
    })
  } catch (err) {
    notifyNetworkError(err)
    throw err
  }
  if (!response.ok) {
    const data = await response.json().catch(() => null)
    const detail = data?.detail
    if (response.status !== 401) notifyError(response.status, detail, response.statusText)
    throw new Error(formatErrorDetail(detail) || `SSE error: ${response.status}`)
  }
  const reader = response.body?.getReader()
  if (!reader) throw new Error('No response body')

  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() || ''

    for (const line of lines) {
      if (line.startsWith('data: ')) {
        const data = line.slice(6).trim()
        if (data === '[DONE]') return
        try {
          yield JSON.parse(data) as SSEEvent
        } catch {
          // skip malformed events
        }
      }
    }
  }
}

export const api = {
  // System
  health(): Promise<HealthResponse> {
    return request('/api/v1/system/health')
  },

  notifications(params?: { limit?: number; refresh?: boolean }): Promise<NotificationEvent[]> {
    return request('/api/v1/notifications', {
      limit: params?.limit ?? 20,
      refresh: params?.refresh ?? false,
    })
  },

  setupValidate(): Promise<SetupValidateResponse> {
    return request('/api/v1/system/setup/validate')
  },

  iamPolicy(): Promise<Record<string, unknown>> {
    return request('/api/v1/system/setup/iam-policy')
  },

  // Resources
  listResources(params?: Record<string, string | number | boolean | undefined>): Promise<PaginatedResponse<ResourceResponse>> {
    return request('/api/v1/resources', params)
  },

  getResource(id: string): Promise<ResourceResponse> {
    return request(`/api/v1/resources/${id}`)
  },

  resourceStats(): Promise<ResourceStatsResponse> {
    return request('/api/v1/resources/stats')
  },

  getResourceByArn(arn: string): Promise<ResourceResponse> {
    return request('/api/v1/resources/by-arn', { arn })
  },

  removeTagManagerTags(resourceIds: string[]): Promise<{ affected_count: number; aws_removed: number; aws_failed: number; details: string }> {
    return requestMutation('POST', '/api/v1/resources/remove-tags', { resource_ids: resourceIds })
  },

  // Lifecycle - Read
  lifecycleDashboard(): Promise<LifecycleDashboardResponse> {
    return request('/api/v1/lifecycle/dashboard')
  },

  expiringResources(params?: {
    days?: number
    limit?: number
    offset?: number
  }): Promise<PaginatedResponse<ExpiringResourceResponse>> {
    return request('/api/v1/lifecycle/expiring', params)
  },

  expiredResources(params?: {
    limit?: number
    offset?: number
  }): Promise<PaginatedResponse<ExpiringResourceResponse>> {
    return request('/api/v1/lifecycle/expired', params)
  },

  listPolicies(params?: {
    enabled_only?: boolean
    limit?: number
    offset?: number
  }): Promise<PaginatedResponse<PolicyResponse>> {
    return request('/api/v1/lifecycle/policies', params)
  },

  // Lifecycle - Mutations
  createPolicy(body: PolicyCreateRequest): Promise<PolicySaveResult> {
    return requestMutation('POST', '/api/v1/lifecycle/policies', body)
  },

  updatePolicy(id: string, body: PolicyUpdateRequest): Promise<PolicySaveResult> {
    return requestMutation('PATCH', `/api/v1/lifecycle/policies/${id}`, body)
  },

  deletePolicy(id: string): Promise<void> {
    return requestMutation('DELETE', `/api/v1/lifecycle/policies/${id}`)
  },

  matchPreview(body: MatchPreviewRequest): Promise<MatchPreviewResponse> {
    return requestMutation('POST', '/api/v1/lifecycle/policies/match-preview', body)
  },

  getPolicyResources(policyId: string, params?: {
    limit?: number
    offset?: number
  }): Promise<PaginatedResponse<MatchedResourceItem>> {
    return request(`/api/v1/lifecycle/policies/${policyId}/resources`, params)
  },

  previewSetTTL(body: SetTTLRequest): Promise<TTLPreviewResponse> {
    return requestMutation('POST', '/api/v1/lifecycle/set-ttl/preview', body)
  },

  setTTL(body: SetTTLRequest): Promise<MutationResult> {
    return requestMutation('POST', '/api/v1/lifecycle/set-ttl', body)
  },

  extendTTL(body: ExtendTTLRequest): Promise<MutationResult> {
    return requestMutation('POST', '/api/v1/lifecycle/extend', body)
  },

  protectResources(body: ProtectRequest): Promise<MutationResult> {
    return requestMutation('POST', '/api/v1/lifecycle/protect', body)
  },

  // Jobs
  submitScan(body?: { services?: string[]; regions?: string[] }): Promise<JobSubmittedResponse> {
    return requestMutation('POST', '/api/v1/jobs/scan', body || {})
  },

  submitDelete(body?: { services?: string[] }): Promise<JobSubmittedResponse> {
    return requestMutation('POST', '/api/v1/jobs/delete', body || {})
  },

  cancelJob(id: string): Promise<JobResponse> {
    return requestMutation('POST', `/api/v1/jobs/${id}/cancel`)
  },

  getJob(id: string): Promise<JobResponse> {
    return request(`/api/v1/jobs/${id}`)
  },

  listJobs(params?: { job_type?: string }): Promise<JobResponse[]> {
    return request('/api/v1/jobs', params)
  },

  // AI Chat
  chatStream(body: ChatRequest): AsyncGenerator<SSEEvent> {
    return requestSSE('/api/v1/ai/chat', body)
  },

  aiModels(): Promise<ModelsResponse> {
    return request('/api/v1/ai/models')
  },

  getConversations(): Promise<ConversationSummary[]> {
    return request('/api/v1/ai/conversations')
  },

  getConversationMessages(id: string): Promise<ConversationMessage[]> {
    return request(`/api/v1/ai/conversations/${id}/messages`)
  },

  deleteConversation(id: string): Promise<{ success: boolean }> {
    return requestMutation('DELETE', `/api/v1/ai/conversations/${id}`)
  },

  // Cost
  costSummary(params?: { days?: number }): Promise<CostSummaryResponse> {
    return request('/api/v1/cost/summary', params)
  },

  costByService(params?: { days?: number }): Promise<CostByServiceResponse> {
    return request('/api/v1/cost/services', params)
  },

  costByAccount(params?: { days?: number }): Promise<CostByAccountResponse> {
    return request('/api/v1/cost/accounts', params)
  },

  costForecast(body: { days?: number; method?: string }): Promise<CostForecastResponse> {
    return requestMutation('POST', '/api/v1/cost/forecast', body)
  },

  curStatus(): Promise<CURStatusResponse> {
    return request('/api/v1/cost/cur/status')
  },

  curDeploy(body: { bucket_name?: string; report_name?: string }): Promise<CURDeployResponse> {
    return requestMutation('POST', '/api/v1/cost/cur/deploy', body)
  },

  curValidate(body: { database: string; table: string }): Promise<CURStatusResponse> {
    return requestMutation('POST', '/api/v1/cost/cur/validate', body)
  },

  // Cost - CUR endpoints
  costRegions(params?: { days?: number; include_services?: boolean }): Promise<CostGenericResponse> {
    return request('/api/v1/cost/regions', params)
  },

  costDaily(params?: { days?: number }): Promise<CostGenericResponse> {
    return request('/api/v1/cost/daily', params)
  },

  costTopResources(params?: { days?: number; limit?: number }): Promise<CostGenericResponse> {
    return request('/api/v1/cost/top-resources', params)
  },

  costDataTransfer(params?: { days?: number }): Promise<CostGenericResponse> {
    return request('/api/v1/cost/data-transfer', params)
  },

  costSavingsPlans(params?: { days?: number }): Promise<CostCommitmentsResponse> {
    return request('/api/v1/cost/savings-plans', params)
  },

  costReservations(params?: { days?: number }): Promise<CostCommitmentsResponse> {
    return request('/api/v1/cost/reservations', params)
  },

  // Cost - Service deep-dives
  costEC2(params?: { days?: number; view?: string }): Promise<CostServiceDeepDiveResponse> {
    return request('/api/v1/cost/ec2', params)
  },

  costS3(params?: { days?: number; view?: string }): Promise<CostServiceDeepDiveResponse> {
    return request('/api/v1/cost/s3', params)
  },

  costRDS(params?: { days?: number; view?: string }): Promise<CostServiceDeepDiveResponse> {
    return request('/api/v1/cost/rds', params)
  },

  costLambda(params?: { days?: number; view?: string }): Promise<CostServiceDeepDiveResponse> {
    return request('/api/v1/cost/lambda', params)
  },

  // Cost - Analysis
  costTrends(body: CostTrendsRequest): Promise<CostTrendsResponse> {
    return requestMutation('POST', '/api/v1/cost/trends', body)
  },

  costAnomalies(body: CostAnomaliesRequest): Promise<CostAnomaliesResponse> {
    return requestMutation('POST', '/api/v1/cost/anomalies', body)
  },

  costChargeback(body: CostChargebackRequest): Promise<CostChargebackResponse> {
    return requestMutation('POST', '/api/v1/cost/report', body)
  },

  costGaps(body: CostGapsRequest): Promise<CostGapsResponse> {
    return requestMutation('POST', '/api/v1/cost/gaps', body)
  },

  // Compliance
  complianceAccess(): Promise<ComplianceAccessResponse> {
    return request('/api/v1/compliance/access')
  },

  compliancePolicies(params?: { detailed?: boolean }): Promise<OrgPolicyResponse[]> {
    return request('/api/v1/compliance/policies', params)
  },

  complianceCheck(params?: {
    resource_type?: string
    region?: string
    tag_key?: string
    max_results?: number
  }): Promise<ComplianceCheckResponse> {
    return request('/api/v1/compliance/check', params)
  },

  effectivePolicy(params?: { target_id?: string }): Promise<EffectivePolicyResponse> {
    return request('/api/v1/compliance/effective-policy', params)
  },

  // Compliance - CRUD
  createOrgPolicy(body: OrgPolicyCreateRequest): Promise<OrgMutationResponse> {
    return requestMutation('POST', '/api/v1/compliance/policies', body)
  },

  getOrgPolicyDetail(policyId: string): Promise<OrgPolicyDetailResponse> {
    return request(`/api/v1/compliance/policies/${policyId}`)
  },

  updateOrgPolicy(policyId: string, body: OrgPolicyUpdateRequest): Promise<OrgMutationResponse> {
    return requestMutation('PATCH', `/api/v1/compliance/policies/${policyId}`, body)
  },

  deleteOrgPolicy(policyId: string): Promise<OrgMutationResponse> {
    return requestMutation('DELETE', `/api/v1/compliance/policies/${policyId}`)
  },

  attachPolicy(policyId: string, targetId: string): Promise<OrgMutationResponse> {
    return requestMutation('POST', `/api/v1/compliance/policies/${policyId}/attach`, { target_id: targetId })
  },

  detachPolicy(policyId: string, targetId: string): Promise<OrgMutationResponse> {
    return requestMutation('POST', `/api/v1/compliance/policies/${policyId}/detach`, { target_id: targetId })
  },

  policyTargets(policyId: string): Promise<PolicyTargetsResponse> {
    return request(`/api/v1/compliance/policies/${policyId}/targets`)
  },

  enableTagPolicies(): Promise<OrgMutationResponse> {
    return requestMutation('POST', '/api/v1/compliance/tag-policies/enable')
  },

  disableTagPolicies(): Promise<OrgMutationResponse> {
    return requestMutation('POST', '/api/v1/compliance/tag-policies/disable')
  },

  orgStructure(): Promise<OrgStructureResponse> {
    return request('/api/v1/compliance/org-structure')
  },

  // Lifecycle - Review
  reviewResources(params?: {
    days?: number
    services?: string
    include_active?: boolean
    lifecycle_state?: string
    account_id?: string
    limit?: number
    offset?: number
  }): Promise<PaginatedResponse<ReviewResourceResponse>> {
    return request('/api/v1/lifecycle/review', params)
  },

  reviewExtend(body: ReviewActionRequest): Promise<MutationResult> {
    return requestMutation('POST', '/api/v1/lifecycle/review/extend', body)
  },

  reviewProtect(body: ReviewActionRequest): Promise<MutationResult> {
    return requestMutation('POST', '/api/v1/lifecycle/review/protect', body)
  },

  reviewMarkDelete(body: ReviewActionRequest): Promise<MutationResult> {
    return requestMutation('POST', '/api/v1/lifecycle/review/mark-delete', body)
  },

  reviewExecuteDelete(body: ExecuteDeleteRequest): Promise<MutationResult> {
    return requestMutation('POST', '/api/v1/lifecycle/review/execute-delete', body)
  },

  auditLog(params?: {
    resource_id?: string
    limit?: number
    offset?: number
  }): Promise<PaginatedResponse<AuditLogEntry>> {
    return request('/api/v1/lifecycle/audit-log', params)
  },

  // Multi-Account
  validateAccount(): Promise<AccountValidationResponse> {
    return request('/api/v1/accounts/validate')
  },

  multiAccountStatus(): Promise<StackSetStatusResponse> {
    return request('/api/v1/accounts/status')
  },

  listAccounts(): Promise<AccountsListResponse> {
    return request('/api/v1/accounts')
  },

  deployMultiAccount(body?: DeployRequest): Promise<JobSubmittedResponse> {
    return requestMutation('POST', '/api/v1/accounts/deploy', body || {})
  },

  updateMultiAccount(): Promise<JobSubmittedResponse> {
    return requestMutation('POST', '/api/v1/accounts/update')
  },

  removeMultiAccount(): Promise<JobSubmittedResponse> {
    return requestMutation('POST', '/api/v1/accounts/remove')
  },

  // Assume Role
  assumeRoleStatus(): Promise<AssumeRoleStatusResponse> {
    return request('/api/v1/assume-role/status')
  },

  assumeRoleConfigs(): Promise<AssumeRoleConfigRecord[]> {
    return request('/api/v1/assume-role/configs')
  },

  deployAssumeRole(body?: AssumeRoleDeployRequest): Promise<JobSubmittedResponse> {
    return requestMutation('POST', '/api/v1/assume-role/deploy', body || {})
  },

  disableAssumeRole(body?: AssumeRoleDisableRequest): Promise<JobSubmittedResponse & { success?: boolean; message?: string }> {
    return requestMutation('POST', '/api/v1/assume-role/disable', body || {})
  },

  // Templates
  listTemplates(): Promise<TemplateMetadata[]> {
    return request('/api/v1/system/templates')
  },

  getTemplate(name: string): Promise<TemplateDetail> {
    return request(`/api/v1/system/templates/${name}`)
  },

  // Account Context
  currentContext(): Promise<AccountContextResponse> {
    return request('/api/v1/system/context')
  },

  allContexts(): Promise<AccountContextListResponse> {
    return request('/api/v1/system/contexts')
  },

  addContext(body?: { alias?: string }): Promise<AccountContextResponse> {
    return requestMutation('POST', '/api/v1/system/context', body)
  },

  switchContext(body: { account_id: string }): Promise<AccountContextResponse> {
    return requestMutation('POST', '/api/v1/system/context/switch', body)
  },

  removeContext(accountId: string): Promise<void> {
    return requestMutation('DELETE', `/api/v1/system/context/${accountId}`)
  },

  contextGate(): Promise<ContextGateResponse> {
    return request('/api/v1/system/context/gate')
  },

  // Permissions
  permissions(): Promise<PermissionStatusResponse> {
    return request('/api/v1/system/permissions')
  },

  refreshPermissions(): Promise<PermissionStatusResponse> {
    return requestMutation('POST', '/api/v1/system/permissions/refresh')
  },

  // Infrastructure
  infrastructureStatus(): Promise<InfrastructureStatusResponse> {
    return request('/api/v1/infrastructure/status')
  },

  createResourceGroup(): Promise<ResourceGroupInfo> {
    return requestMutation('POST', '/api/v1/infrastructure/resource-group/create')
  },

  deleteResourceGroup(): Promise<{ success: boolean }> {
    return requestMutation('POST', '/api/v1/infrastructure/resource-group/delete')
  },

  deleteCurStack(): Promise<{ success: boolean; message: string }> {
    return requestMutation('POST', '/api/v1/infrastructure/cur-stack/delete')
  },

  deployCurStack(config?: { bucket_name?: string; report_name?: string }): Promise<JobSubmittedResponse> {
    return requestMutation('POST', '/api/v1/infrastructure/stacks/cost-reports/deploy', config || {})
  },

  updateInfraStack(component: string): Promise<JobSubmittedResponse> {
    return requestMutation('POST', `/api/v1/infrastructure/stacks/${component}/update`)
  },

  // Event Tracking
  eventTrackingStatus(): Promise<EventTrackingStatusResponse> {
    return request('/api/v1/event-tracking/status')
  },

  deployEventTracking(targets: Record<string, string[]>): Promise<JobSubmittedResponse> {
    return requestMutation('POST', '/api/v1/event-tracking/deploy', { targets })
  },

  removeEventTracking(targets: Record<string, string[]>): Promise<JobSubmittedResponse> {
    return requestMutation('POST', '/api/v1/event-tracking/remove', { targets })
  },

  removeAllEventTracking(): Promise<JobSubmittedResponse> {
    return requestMutation('POST', '/api/v1/event-tracking/remove-all')
  },

  eventTrackingService(action: string): Promise<Record<string, unknown>> {
    return requestMutation('POST', '/api/v1/event-tracking/service', { action })
  },

  // Resource Graph
  resourceGraph(params?: Record<string, string | number | boolean | undefined>): Promise<GraphResponse> {
    return request('/api/v1/graph', params)
  },

  graphStats(params?: Record<string, string | number | boolean | undefined>): Promise<GraphStatsResponse> {
    return request('/api/v1/graph/stats', params)
  },

  graphFilters(): Promise<GraphFiltersResponse> {
    return request('/api/v1/graph/filters')
  },

  blastRadius(arn: string): Promise<BlastRadiusResponse> {
    return request('/api/v1/graph/blast-radius', { arn })
  },
}
