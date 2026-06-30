<template>
  <div class="resource-map-view">
    <!-- Truncation banner -->
    <div v-if="store.truncated" class="truncation-banner">
      <i class="pi pi-info-circle"></i>
      Graph truncated to {{ store.nodeCount }} nodes. Use filters to narrow results.
    </div>

    <!-- Filters bar -->
    <div class="filters-bar">
      <div class="filter-group">
        <select v-model="store.activeFilters.vpc_id" class="filter-input" @change="applyFilters">
          <option value="">All VPCs</option>
          <option v-for="v in store.filters?.vpc_ids" :key="v" :value="v">{{ v }}</option>
        </select>
        <select v-model="store.activeFilters.region" class="filter-input" @change="applyFilters">
          <option value="">All Regions</option>
          <option v-for="r in store.filters?.regions" :key="r" :value="r">{{ r }}</option>
        </select>
        <select v-model="store.activeFilters.service" class="filter-input" @change="applyFilters">
          <option value="">All Services</option>
          <option v-for="s in store.filters?.services" :key="s" :value="s">{{ s }}</option>
        </select>
        <select v-model="store.activeFilters.account_id" class="filter-input" @change="applyFilters">
          <option value="">All Accounts</option>
          <option v-for="a in store.filters?.account_ids" :key="a" :value="a">{{ a }}</option>
        </select>
        <select v-model.number="store.activeFilters.depth" class="filter-input" @change="applyFilters">
          <option :value="1">Depth 1</option>
          <option :value="2">Depth 2</option>
          <option :value="3">Depth 3</option>
        </select>
        <input
          v-model="arnInput"
          type="text"
          placeholder="Resource ARN..."
          class="filter-input arn-input"
          @keyup.enter="focusByArn"
        />
        <button
          v-if="hasActiveFilters"
          class="btn btn-sm btn-outline"
          @click="clearFilters"
        >
          Clear
        </button>
        <div class="layer-toggles">
          <button
            class="layer-toggle"
            :class="{ active: store.overlayLayers.lifecycle }"
            @click="store.toggleOverlay('lifecycle')"
          >
            <i class="pi pi-clock"></i> Lifecycle
          </button>
          <button
            class="layer-toggle"
            :class="{ active: store.overlayLayers.compliance }"
            @click="store.toggleOverlay('compliance')"
          >
            <i class="pi pi-check-circle"></i> Compliance
          </button>
        </div>
      </div>
    </div>

    <!-- Main content -->
    <div class="map-content">
      <!-- Graph area -->
      <div class="graph-container">
        <div v-if="store.loading" class="graph-loading">
          <i class="pi pi-spin pi-spinner"></i> Loading graph...
        </div>
        <div v-else-if="store.error" class="graph-error">
          {{ store.error }}
        </div>
        <div v-else-if="!store.graphData || store.nodeCount === 0" class="graph-empty">
          <i class="pi pi-sitemap graph-empty-icon"></i>
          <p>No relationships found.</p>
          <p class="graph-empty-hint">Run a resource scan to discover relationships.</p>
        </div>
        <VChart
          v-else
          ref="chartRef"
          class="graph-chart"
          :option="chartOption"
          autoresize
          @click="onNodeClick"
          @dblclick="onNodeDblClick"
        />
      </div>

      <!-- Detail panel -->
      <GraphDetailPanel
        v-if="store.selectedNode"
        :node="store.selectedNode"
        :edges="store.graphData?.edges ?? []"
        @close="store.selectNode(null)"
        @focus="onFocusNode"
        @blast-radius="(arn: string) => blastRadiusArn = arn"
      />
    </div>

    <!-- Footer -->
    <div class="map-footer">
      <div class="legend">
        <span
          v-for="cat in visibleCategories"
          :key="cat.name"
          class="legend-item"
        >
          <span class="legend-dot" :style="{ background: cat.color }"></span>
          {{ cat.name }}
        </span>
      </div>
      <div v-if="anyOverlayActive" class="overlay-legend">
        <template v-if="store.overlayLayers.lifecycle">
          <span class="legend-item"><span class="legend-ring" style="border-color:#f59e0b"></span>Expiring</span>
          <span class="legend-item"><span class="legend-ring" style="border-color:#991b1b"></span>Expired</span>
          <span class="legend-item"><span class="legend-ring" style="border-color:#ef4444"></span>Marked</span>
          <span class="legend-item"><span class="legend-ring" style="border-color:#3b82f6"></span>Warned</span>
        </template>
        <template v-if="store.overlayLayers.compliance">
          <span class="legend-item"><span class="legend-badge" style="background:#22c55e"></span>Compliant</span>
          <span class="legend-item"><span class="legend-badge" style="background:#ef4444"></span>Noncompliant</span>
        </template>
      </div>
      <div class="map-stats">
        {{ store.nodeCount }} nodes, {{ store.edgeCount }} edges
      </div>
    </div>

    <BlastRadiusPanel
      v-if="blastRadiusArn"
      :arn="blastRadiusArn"
      @close="blastRadiusArn = null"
      @focus="(arn: string) => { blastRadiusArn = null; onFocusNode(arn) }"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import BlastRadiusPanel from '@/components/BlastRadiusPanel.vue'
import { useRoute } from 'vue-router'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { GraphChart } from 'echarts/charts'
import { TooltipComponent, LegendComponent } from 'echarts/components'
import VChart from 'vue-echarts'
import { useGraphStore } from '@/stores/graph'
import GraphDetailPanel from '@/components/GraphDetailPanel.vue'

use([CanvasRenderer, GraphChart, TooltipComponent, LegendComponent])

const route = useRoute()
const store = useGraphStore()
const chartRef = ref<InstanceType<typeof VChart> | null>(null)
const arnInput = ref('')
const blastRadiusArn = ref<string | null>(null)

const anyOverlayActive = computed(() =>
  store.overlayLayers.lifecycle || store.overlayLayers.compliance
)

const SERVICE_COLORS: Record<string, string> = {
  ec2: '#f97316', s3: '#22c55e', lambda: '#a855f7', rds: '#3b82f6',
  dynamodb: '#f59e0b', ecs: '#14b8a6', elb: '#06b6d4', elbv2: '#06b6d4',
  sns: '#e11d48', sqs: '#8b5cf6', cloudwatch: '#ef4444', logs: '#ef4444',
  eks: '#0ea5e9', elasticache: '#dc2626', vpc: '#6b7280', subnet: '#9ca3af',
  sg: '#4b5563', iam: '#eab308',
}

const hasActiveFilters = computed(() => {
  const f = store.activeFilters
  return !!(f.vpc_id || f.region || f.service || f.account_id || f.resource_arn)
})

const visibleCategories = computed(() => {
  if (!store.graphData) return []
  const usedCategories = new Set(store.graphData.nodes.map(n => n.service_name))
  return store.graphData.categories.filter(c => usedCategories.has(c.name))
})

const chartOption = computed(() => {
  if (!store.graphData) return {}

  const nodes = store.graphData.nodes.map(n => {
    const baseColor = SERVICE_COLORS[n.service_name] || '#6b7280'
    let borderColor = n.id === store.selectedNodeArn ? '#fff' : 'transparent'
    let borderWidth = n.id === store.selectedNodeArn ? 3 : 0
    let borderType: string = 'solid'

    // Lifecycle overlay: ring around node
    if (store.overlayLayers.lifecycle) {
      if (n.lifecycle_state === 'marked_for_deletion') {
        borderColor = '#ef4444'; borderWidth = 3
      } else if (n.lifecycle_state === 'warned') {
        borderColor = '#3b82f6'; borderWidth = 3
      } else if (n.expires_at) {
        const exp = new Date(n.expires_at)
        if (exp < new Date()) {
          borderColor = '#991b1b'; borderWidth = 3
        } else {
          borderColor = '#f59e0b'; borderWidth = 3
        }
      }
      if (n.protected) {
        borderType = 'dashed'
      }
    }

    // Build label rich text for badges
    const labelParts: string[] = []
    const richStyles: Record<string, unknown> = {}

    if (store.overlayLayers.compliance && n.compliance_status) {
      if (n.compliance_status === 'noncompliant') {
        labelParts.push('{compBad|' + (n.missing_tags?.length || '!') + '}')
        richStyles.compBad = {
          backgroundColor: '#ef4444', color: '#fff', borderRadius: 6,
          padding: [1, 4], fontSize: 9, fontWeight: 'bold',
        }
      } else if (n.compliance_status === 'compliant') {
        labelParts.push('{compOk|+}')
        richStyles.compOk = {
          backgroundColor: '#22c55e', color: '#fff', borderRadius: 6,
          padding: [1, 4], fontSize: 9,
        }
      }
    }

    const hasOverlayLabels = labelParts.length > 0

    return {
      id: n.id,
      name: n.name || n.resource_id,
      symbolSize: n.symbol_size,
      category: n.category,
      itemStyle: {
        color: baseColor,
        borderColor,
        borderWidth,
        borderType,
      },
      label: {
        show: hasOverlayLabels || store.nodeCount <= 100,
        fontSize: 10,
        color: '#ccc',
        formatter: hasOverlayLabels
          ? (n.name || n.resource_id) + ' ' + labelParts.join(' ')
          : undefined,
        rich: hasOverlayLabels ? richStyles : undefined,
      },
      value: n.service_name,
    }
  })

  const edges = store.graphData.edges.map(e => ({
    source: e.source,
    target: e.target,
    label: {
      show: false,
      formatter: e.relationship_type,
      fontSize: 9,
      color: '#999',
    },
    emphasis: {
      label: { show: true },
    },
    lineStyle: {
      color: '#555',
      width: 1,
      curveness: 0.1,
    },
  }))

  const categories = store.graphData.categories.map(c => ({
    name: c.name,
    itemStyle: { color: c.color },
  }))

  return {
    tooltip: {
      trigger: 'item',
      formatter: (params: Record<string, unknown>) => {
        if (params.dataType === 'edge') {
          const data = params.data as { label?: { formatter?: string } }
          return data?.label?.formatter || ''
        }
        const nodeId = (params.data as { id?: string })?.id
        const node = store.graphData?.nodes.find(n => n.id === nodeId)
        if (!node) {
          const data = params.data as { name?: string; value?: string; id?: string }
          return `<b>${data?.name || ''}</b><br/>${data?.value || ''}`
        }
        let html = `<b>${node.name || node.resource_id}</b><br/>${node.service_name}`
        if (store.overlayLayers.lifecycle) {
          if (node.lifecycle_state) html += `<br/>State: ${node.lifecycle_state}`
          if (node.expires_at) {
            const d = new Date(node.expires_at)
            const days = Math.ceil((d.getTime() - Date.now()) / 86400000)
            html += `<br/>Expires: ${days > 0 ? 'in ' + days + 'd' : Math.abs(days) + 'd ago'}`
          }
          if (node.protected) html += `<br/><b>Protected</b>`
        }
        if (store.overlayLayers.compliance && node.compliance_status) {
          html += `<br/>Compliance: ${node.compliance_status}`
          if (node.missing_tags?.length) html += `<br/>Missing: ${node.missing_tags.join(', ')}`
        }
        html += `<br/><span style="font-size:10px;color:#999">${node.id}</span>`
        return html
      },
      backgroundColor: '#1a1a2e',
      borderColor: '#333',
      textStyle: { color: '#eee', fontSize: 12 },
    },
    series: [
      {
        type: 'graph',
        layout: 'force',
        data: nodes,
        links: edges,
        categories: categories,
        roam: true,
        draggable: true,
        force: {
          repulsion: 200,
          gravity: 0.05,
          edgeLength: [80, 200],
          friction: 0.6,
        },
        emphasis: {
          focus: 'adjacency',
          lineStyle: { width: 3 },
        },
        label: {
          position: 'right',
          distance: 5,
        },
        edgeSymbol: ['none', 'arrow'],
        edgeSymbolSize: [0, 8],
      },
    ],
    animationDuration: 1500,
    animationEasingUpdate: 'quinticInOut' as const,
  }
})

function onNodeClick(params: Record<string, unknown>) {
  if (params.dataType === 'node') {
    const data = params.data as { id?: string }
    if (data?.id) {
      store.selectNode(data.id)
    }
  }
}

function onNodeDblClick(params: Record<string, unknown>) {
  if (params.dataType === 'node') {
    const data = params.data as { id?: string }
    if (data?.id) {
      onFocusNode(data.id)
    }
  }
}

function onFocusNode(arn: string) {
  arnInput.value = ''
  store.focusNode(arn)
}

function applyFilters() {
  store.fetchGraph()
}

function focusByArn() {
  if (arnInput.value.trim()) {
    store.focusNode(arnInput.value.trim())
    arnInput.value = ''
  }
}

function clearFilters() {
  arnInput.value = ''
  store.resetFilters()
  store.fetchGraph()
}

onMounted(async () => {
  // Check for query params (cross-navigation from ResourceDetailView)
  const qArn = route.query.resource_arn as string | undefined
  const qDepth = route.query.depth as string | undefined
  if (qArn) {
    store.activeFilters.resource_arn = qArn
    if (qDepth) store.activeFilters.depth = parseInt(qDepth, 10) || 1
    store.selectedNodeArn = qArn
  }

  await store.fetchFilters()
  await store.fetchGraph()
})
</script>

<style scoped>
.resource-map-view {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 1rem);
  gap: 0;
}

.truncation-banner {
  background: rgba(245, 158, 11, 0.1);
  border: 1px solid rgba(245, 158, 11, 0.3);
  color: #f59e0b;
  padding: 0.5rem 1rem;
  font-size: 0.85rem;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  border-radius: 8px;
  margin-bottom: 0.5rem;
}

.filters-bar {
  padding: 0.5rem 0;
  display: flex;
  align-items: center;
}

.filter-group {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
}

.filter-input {
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  color: var(--text-color);
  padding: 0.4rem 0.6rem;
  border-radius: 6px;
  font-size: 0.82rem;
  min-width: 120px;
}

.filter-input:focus {
  outline: none;
  border-color: var(--primary-color);
}

.arn-input {
  min-width: 220px;
}

.map-content {
  flex: 1;
  display: flex;
  min-height: 0;
  border: 1px solid var(--surface-border);
  border-radius: 8px;
  overflow: hidden;
  background: var(--surface-card);
}

.graph-container {
  flex: 1;
  position: relative;
  min-height: 400px;
}

.graph-chart {
  width: 100%;
  height: 100%;
}

.graph-loading,
.graph-error,
.graph-empty {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.75rem;
  color: var(--text-color-secondary);
}

.graph-loading i {
  font-size: 1.5rem;
}

.graph-error {
  color: var(--color-danger, #ef4444);
}

.graph-empty-icon {
  font-size: 3rem;
  opacity: 0.3;
}

.graph-empty p {
  margin: 0;
  font-size: 0.9rem;
}

.graph-empty-hint {
  font-size: 0.8rem;
  opacity: 0.6;
}

.map-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.5rem 0;
}

.legend {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  flex-wrap: wrap;
}

.legend-item {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 0.75rem;
  color: var(--text-color-secondary);
  text-transform: uppercase;
}

.legend-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
}

.map-stats {
  font-size: 0.8rem;
  color: var(--text-color-secondary);
}

.btn {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.4rem 0.75rem;
  border-radius: 6px;
  font-size: 0.82rem;
  cursor: pointer;
  border: 1px solid transparent;
  text-decoration: none;
}

.btn-sm { font-size: 0.78rem; padding: 0.35rem 0.65rem; }
.btn-outline {
  background: transparent;
  color: var(--text-color-secondary);
  border-color: var(--surface-border);
}
.btn-outline:hover {
  background: var(--surface-hover);
  color: var(--text-color);
}

.layer-toggles {
  display: flex;
  gap: 0.25rem;
  margin-left: 0.5rem;
  border-left: 1px solid var(--surface-border);
  padding-left: 0.5rem;
}

.layer-toggle {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  padding: 0.35rem 0.6rem;
  border-radius: 6px;
  font-size: 0.78rem;
  cursor: pointer;
  border: 1px solid var(--surface-border);
  background: var(--surface-card);
  color: var(--text-color-secondary);
  transition: all 0.15s;
}

.layer-toggle.active {
  background: rgba(99, 102, 241, 0.15);
  border-color: #6366f1;
  color: #6366f1;
}

.layer-toggle:hover {
  border-color: var(--primary-color);
}

.overlay-legend {
  display: flex;
  gap: 0.75rem;
  margin-left: 1rem;
  padding-left: 1rem;
  border-left: 1px solid var(--surface-border);
}

.legend-ring {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  border: 2px solid;
  margin-right: 4px;
}

.legend-badge {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  margin-right: 4px;
}
</style>
