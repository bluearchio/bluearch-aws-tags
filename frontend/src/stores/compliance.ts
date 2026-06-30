import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '@/api/client'
import type {
  ComplianceAccessResponse,
  OrgPolicyResponse,
  ComplianceCheckResponse,
  OrgPolicyDetailResponse,
  OrgStructureResponse,
  OrgMutationResponse,
  OrgPolicyCreateRequest,
  OrgPolicyUpdateRequest,
} from '@/types/api'

export const useComplianceStore = defineStore('compliance', () => {
  const access = ref<ComplianceAccessResponse | null>(null)
  const orgPolicies = ref<OrgPolicyResponse[]>([])
  const checkResult = ref<ComplianceCheckResponse | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function fetchAccess() {
    loading.value = true
    error.value = null
    try {
      access.value = await api.complianceAccess()
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Failed to check access'
    } finally {
      loading.value = false
    }
  }

  async function fetchPolicies() {
    try {
      orgPolicies.value = await api.compliancePolicies()
    } catch (e) {
      console.error('Failed to fetch org policies:', e)
    }
  }

  async function checkCompliance(params?: {
    resource_type?: string
    region?: string
    tag_key?: string
  }) {
    loading.value = true
    error.value = null
    try {
      checkResult.value = await api.complianceCheck(params)
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Compliance check failed'
    } finally {
      loading.value = false
    }
  }

  async function fetchAll() {
    await Promise.all([fetchAccess(), fetchPolicies(), checkCompliance()])
  }

  const policyDetail = ref<OrgPolicyDetailResponse | null>(null)
  const orgStructure = ref<OrgStructureResponse | null>(null)

  async function fetchPolicyDetail(policyId: string) {
    try {
      policyDetail.value = await api.getOrgPolicyDetail(policyId)
    } catch (e) {
      console.error('Failed to fetch policy detail:', e)
    }
  }

  async function fetchOrgStructure() {
    try {
      orgStructure.value = await api.orgStructure()
    } catch (e) {
      console.error('Failed to fetch org structure:', e)
    }
  }

  async function createOrgPolicy(body: OrgPolicyCreateRequest): Promise<OrgMutationResponse> {
    const result = await api.createOrgPolicy(body)
    await fetchPolicies()
    return result
  }

  async function updateOrgPolicy(policyId: string, body: OrgPolicyUpdateRequest): Promise<OrgMutationResponse> {
    const result = await api.updateOrgPolicy(policyId, body)
    await fetchPolicies()
    return result
  }

  async function deleteOrgPolicy(policyId: string): Promise<OrgMutationResponse> {
    const result = await api.deleteOrgPolicy(policyId)
    await fetchPolicies()
    return result
  }

  async function attachPolicy(policyId: string, targetId: string): Promise<OrgMutationResponse> {
    const result = await api.attachPolicy(policyId, targetId)
    if (policyDetail.value?.id === policyId) {
      await fetchPolicyDetail(policyId)
    }
    return result
  }

  async function detachPolicy(policyId: string, targetId: string): Promise<OrgMutationResponse> {
    const result = await api.detachPolicy(policyId, targetId)
    if (policyDetail.value?.id === policyId) {
      await fetchPolicyDetail(policyId)
    }
    return result
  }

  async function enableTagPolicies(): Promise<OrgMutationResponse> {
    const result = await api.enableTagPolicies()
    await fetchAccess()
    return result
  }

  async function disableTagPolicies(): Promise<OrgMutationResponse> {
    const result = await api.disableTagPolicies()
    await fetchAccess()
    return result
  }

  return {
    access,
    orgPolicies,
    checkResult,
    loading,
    error,
    fetchAccess,
    fetchPolicies,
    checkCompliance,
    fetchAll,
    policyDetail,
    orgStructure,
    fetchPolicyDetail,
    fetchOrgStructure,
    createOrgPolicy,
    updateOrgPolicy,
    deleteOrgPolicy,
    attachPolicy,
    detachPolicy,
    enableTagPolicies,
    disableTagPolicies,
  }
})
