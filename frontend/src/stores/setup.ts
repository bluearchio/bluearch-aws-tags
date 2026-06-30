import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '@/api/client'
import type { SetupValidateResponse, InfrastructureStatusResponse, IAMPolicyStatement } from '@/types/api'

export const useSetupStore = defineStore('setup', () => {
  // Validation state
  const result = ref<SetupValidateResponse | null>(null)
  const loading = ref(false)

  // Infrastructure state
  const infraData = ref<InfrastructureStatusResponse | null>(null)
  const infraLoading = ref(false)

  // IAM Policy state
  const iamPolicy = ref<{ Statement: IAMPolicyStatement[];[key: string]: unknown } | null>(null)
  const iamPolicyLoading = ref(false)
  const iamPolicyError = ref<string | null>(null)

  async function runValidation() {
    loading.value = true
    try {
      result.value = await api.setupValidate()
    } catch {
      // Error toast shown by API client
    } finally {
      loading.value = false
    }
  }

  async function loadInfrastructure() {
    infraLoading.value = true
    try {
      infraData.value = await api.infrastructureStatus()
    } catch {
      // Error toast shown by API client
    } finally {
      infraLoading.value = false
    }
  }

  async function loadIamPolicy() {
    if (iamPolicy.value) return
    iamPolicyLoading.value = true
    iamPolicyError.value = null
    try {
      const data = await api.iamPolicy()
      if (data.error) {
        iamPolicyError.value = data.error as string
      } else {
        iamPolicy.value = data as { Statement: IAMPolicyStatement[];[key: string]: unknown }
      }
    } catch (e) {
      iamPolicyError.value = e instanceof Error ? e.message : 'Failed to load policy'
    } finally {
      iamPolicyLoading.value = false
    }
  }

  async function refreshAll() {
    await Promise.all([runValidation(), loadInfrastructure()])
  }

  return {
    result,
    loading,
    infraData,
    infraLoading,
    iamPolicy,
    iamPolicyLoading,
    iamPolicyError,
    runValidation,
    loadInfrastructure,
    loadIamPolicy,
    refreshAll,
  }
})
