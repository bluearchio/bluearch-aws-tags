import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '@/api/client'
import type { ResourceResponse, ResourceStatsResponse } from '@/types/api'

export const useResourcesStore = defineStore('resources', () => {
  const resources = ref<ResourceResponse[]>([])
  const stats = ref<ResourceStatsResponse | null>(null)
  const total = ref(0)
  const loading = ref(false)
  const error = ref<string | null>(null)

  // Filters
  const filters = ref({
    service: '',
    region: '',
    account_id: '',
    lifecycle_state: '',
    resource_type: '',
    protected: '' as '' | 'true' | 'false',
    tagged: '' as '' | 'true' | 'false',
    search: '',
    limit: 50,
    offset: 0,
  })

  async function fetchResources() {
    loading.value = true
    error.value = null
    try {
      const params: Record<string, string | number | undefined> = {
        limit: filters.value.limit,
        offset: filters.value.offset,
      }
      if (filters.value.service) params.service = filters.value.service
      if (filters.value.region) params.region = filters.value.region
      if (filters.value.account_id) params.account_id = filters.value.account_id
      if (filters.value.lifecycle_state) params.lifecycle_state = filters.value.lifecycle_state
      if (filters.value.resource_type) params.resource_type = filters.value.resource_type
      if (filters.value.protected) params.protected = filters.value.protected
      if (filters.value.tagged) params.tagged = filters.value.tagged
      if (filters.value.search) params.search = filters.value.search

      const data = await api.listResources(params)
      resources.value = data.items
      total.value = data.total
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Failed to fetch resources'
    } finally {
      loading.value = false
    }
  }

  async function fetchStats() {
    try {
      stats.value = await api.resourceStats()
    } catch (e) {
      console.error('Failed to fetch stats:', e)
    }
  }

  function setPage(offset: number) {
    filters.value.offset = offset
    fetchResources()
  }

  function resetFilters() {
    filters.value = {
      service: '',
      region: '',
      account_id: '',
      lifecycle_state: '',
      resource_type: '',
      protected: '',
      tagged: '',
      search: '',
      limit: 50,
      offset: 0,
    }
    fetchResources()
  }

  return {
    resources,
    stats,
    total,
    loading,
    error,
    filters,
    fetchResources,
    fetchStats,
    setPage,
    resetFilters,
  }
})
