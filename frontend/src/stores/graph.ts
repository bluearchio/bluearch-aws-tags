import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { api } from '@/api/client'
import type { GraphResponse, GraphStatsResponse, GraphFiltersResponse } from '@/types/api'

export const useGraphStore = defineStore('graph', () => {
  const graphData = ref<GraphResponse | null>(null)
  const stats = ref<GraphStatsResponse | null>(null)
  const filters = ref<GraphFiltersResponse | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)
  const selectedNodeArn = ref<string | null>(null)

  const overlayLayers = ref<{
    lifecycle: boolean
    compliance: boolean
  }>({
    lifecycle: false,
    compliance: false,
  })

  const activeFilters = ref<{
    vpc_id: string
    region: string
    account_id: string
    service: string
    resource_arn: string
    depth: number
    max_nodes: number
  }>({
    vpc_id: '',
    region: '',
    account_id: '',
    service: '',
    resource_arn: '',
    depth: 2,
    max_nodes: 200,
  })

  const nodeCount = computed(() => graphData.value?.nodes.length ?? 0)
  const edgeCount = computed(() => graphData.value?.edges.length ?? 0)
  const truncated = computed(() => graphData.value?.truncated ?? false)

  const selectedNode = computed(() => {
    if (!selectedNodeArn.value || !graphData.value) return null
    return graphData.value.nodes.find(n => n.id === selectedNodeArn.value) ?? null
  })

  async function fetchGraph() {
    loading.value = true
    error.value = null
    try {
      const params: Record<string, string | number | boolean | undefined> = {}
      if (activeFilters.value.vpc_id) params.vpc_id = activeFilters.value.vpc_id
      if (activeFilters.value.region) params.region = activeFilters.value.region
      if (activeFilters.value.account_id) params.account_id = activeFilters.value.account_id
      if (activeFilters.value.service) params.service = activeFilters.value.service
      if (activeFilters.value.resource_arn) params.resource_arn = activeFilters.value.resource_arn
      params.depth = activeFilters.value.depth
      params.max_nodes = activeFilters.value.max_nodes
      const activeOverlays = Object.entries(overlayLayers.value)
        .filter(([, v]) => v)
        .map(([k]) => k)
      if (activeOverlays.length > 0) {
        params.overlays = activeOverlays.join(',')
      }
      graphData.value = await api.resourceGraph(params)
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Failed to load graph'
    } finally {
      loading.value = false
    }
  }

  async function fetchStats() {
    try {
      const params: Record<string, string | number | boolean | undefined> = {}
      if (activeFilters.value.region) params.region = activeFilters.value.region
      if (activeFilters.value.account_id) params.account_id = activeFilters.value.account_id
      stats.value = await api.graphStats(params)
    } catch {
      // non-critical
    }
  }

  async function fetchFilters() {
    try {
      filters.value = await api.graphFilters()
    } catch {
      // non-critical
    }
  }

  function selectNode(arn: string | null) {
    selectedNodeArn.value = arn
  }

  function focusNode(arn: string) {
    activeFilters.value.resource_arn = arn
    activeFilters.value.depth = 2
    selectedNodeArn.value = arn
    fetchGraph()
  }

  function toggleOverlay(layer: 'lifecycle' | 'compliance') {
    overlayLayers.value[layer] = !overlayLayers.value[layer]
    fetchGraph()
  }

  function resetFilters() {
    activeFilters.value = {
      vpc_id: '',
      region: '',
      account_id: '',
      service: '',
      resource_arn: '',
      depth: 2,
      max_nodes: 200,
    }
    selectedNodeArn.value = null
  }

  return {
    graphData,
    stats,
    filters,
    loading,
    error,
    selectedNodeArn,
    overlayLayers,
    activeFilters,
    nodeCount,
    edgeCount,
    truncated,
    selectedNode,
    fetchGraph,
    fetchStats,
    fetchFilters,
    selectNode,
    focusNode,
    resetFilters,
    toggleOverlay,
  }
})
