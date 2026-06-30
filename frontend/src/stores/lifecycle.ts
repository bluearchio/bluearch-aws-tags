import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '@/api/client'
import type {
  LifecycleDashboardResponse,
  ExpiringResourceResponse,
  PolicyResponse,
  PolicyCreateRequest,
  PolicyUpdateRequest,
  MutationResult,
  ReviewResourceResponse,
  AuditLogEntry,
  MatchPreviewRequest,
  MatchPreviewResponse,
  MatchedResourceItem,
  PolicySaveResult,
} from '@/types/api'

export const useLifecycleStore = defineStore('lifecycle', () => {
  const dashboard = ref<LifecycleDashboardResponse | null>(null)
  const expiring = ref<ExpiringResourceResponse[]>([])
  const expiringTotal = ref(0)
  const expired = ref<ExpiringResourceResponse[]>([])
  const expiredTotal = ref(0)
  const policies = ref<PolicyResponse[]>([])
  const policiesTotal = ref(0)
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function fetchDashboard() {
    loading.value = true
    error.value = null
    try {
      dashboard.value = await api.lifecycleDashboard()
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Failed to fetch dashboard'
    } finally {
      loading.value = false
    }
  }

  async function fetchExpiring(days = 7) {
    try {
      const data = await api.expiringResources({ days, limit: 100 })
      expiring.value = data.items
      expiringTotal.value = data.total
    } catch (e) {
      console.error('Failed to fetch expiring resources:', e)
    }
  }

  async function fetchExpired() {
    try {
      const data = await api.expiredResources({ limit: 100 })
      expired.value = data.items
      expiredTotal.value = data.total
    } catch (e) {
      console.error('Failed to fetch expired resources:', e)
    }
  }

  async function fetchPolicies() {
    try {
      const data = await api.listPolicies({ limit: 100 })
      policies.value = data.items
      policiesTotal.value = data.total
    } catch (e) {
      console.error('Failed to fetch policies:', e)
    }
  }

  // Last save result for feedback banner
  const lastSaveResult = ref<PolicySaveResult | null>(null)

  async function createPolicy(data: PolicyCreateRequest): Promise<PolicySaveResult> {
    const result = await api.createPolicy(data)
    lastSaveResult.value = result
    await fetchPolicies()
    return result
  }

  async function updatePolicy(id: string, data: PolicyUpdateRequest): Promise<PolicySaveResult> {
    const result = await api.updatePolicy(id, data)
    lastSaveResult.value = result
    await fetchPolicies()
    return result
  }

  async function deletePolicy(id: string): Promise<void> {
    await api.deletePolicy(id)
    await fetchPolicies()
  }

  async function matchPreview(body: MatchPreviewRequest): Promise<MatchPreviewResponse> {
    return api.matchPreview(body)
  }

  // Policy resources drill-down
  const policyResources = ref<MatchedResourceItem[]>([])
  const policyResourcesTotal = ref(0)

  async function fetchPolicyResources(policyId: string) {
    try {
      const data = await api.getPolicyResources(policyId, { limit: 100 })
      policyResources.value = data.items
      policyResourcesTotal.value = data.total
    } catch (e) {
      console.error('Failed to fetch policy resources:', e)
    }
  }

  async function extendResource(resourceIds: string[], days: number): Promise<MutationResult> {
    const result = await api.extendTTL({ resource_ids: resourceIds, days })
    await Promise.all([fetchExpiring(), fetchExpired()])
    return result
  }

  async function protectResource(resourceIds: string[], protect: boolean): Promise<MutationResult> {
    const result = await api.protectResources({ resource_ids: resourceIds, protect })
    await Promise.all([fetchExpiring(), fetchExpired()])
    return result
  }

  // Review
  const reviewResources = ref<ReviewResourceResponse[]>([])
  const reviewTotal = ref(0)
  const auditLog = ref<AuditLogEntry[]>([])
  const auditLogTotal = ref(0)

  // Unified explorer
  const explorerResources = ref<ReviewResourceResponse[]>([])
  const explorerTotal = ref(0)

  async function fetchExplorerResources(params?: {
    days?: number
    services?: string
    include_active?: boolean
    lifecycle_state?: string
    account_id?: string
  }) {
    try {
      const data = await api.reviewResources({ ...params, limit: 100 })
      explorerResources.value = data.items
      explorerTotal.value = data.total
    } catch (e) {
      console.error('Failed to fetch explorer resources:', e)
    }
  }

  async function fetchReviewResources(params?: {
    days?: number
    services?: string
    include_active?: boolean
  }) {
    try {
      const data = await api.reviewResources({ ...params, limit: 100 })
      reviewResources.value = data.items
      reviewTotal.value = data.total
    } catch (e) {
      console.error('Failed to fetch review resources:', e)
    }
  }

  async function reviewExtend(resourceIds: string[], days: number, reason?: string): Promise<MutationResult> {
    const result = await api.reviewExtend({ resource_ids: resourceIds, days, reason })
    return result
  }

  async function reviewProtect(resourceIds: string[], reason?: string): Promise<MutationResult> {
    const result = await api.reviewProtect({ resource_ids: resourceIds, reason })
    return result
  }

  async function reviewMarkDelete(resourceIds: string[], reason?: string): Promise<MutationResult> {
    const result = await api.reviewMarkDelete({ resource_ids: resourceIds, reason })
    return result
  }

  async function executeDelete(resourceIds: string[]): Promise<MutationResult> {
    return api.reviewExecuteDelete({ resource_ids: resourceIds, confirmation: 'DELETE' })
  }

  async function fetchAuditLog(resourceId?: string) {
    try {
      const data = await api.auditLog({ resource_id: resourceId, limit: 100 })
      auditLog.value = data.items
      auditLogTotal.value = data.total
    } catch (e) {
      console.error('Failed to fetch audit log:', e)
    }
  }

  return {
    dashboard,
    expiring,
    expiringTotal,
    expired,
    expiredTotal,
    policies,
    policiesTotal,
    loading,
    error,
    fetchDashboard,
    fetchExpiring,
    fetchExpired,
    fetchPolicies,
    createPolicy,
    updatePolicy,
    deletePolicy,
    extendResource,
    protectResource,
    reviewResources,
    reviewTotal,
    explorerResources,
    explorerTotal,
    fetchExplorerResources,
    auditLog,
    auditLogTotal,
    fetchReviewResources,
    reviewExtend,
    reviewProtect,
    reviewMarkDelete,
    executeDelete,
    fetchAuditLog,
    lastSaveResult,
    matchPreview,
    policyResources,
    policyResourcesTotal,
    fetchPolicyResources,
  }
})
