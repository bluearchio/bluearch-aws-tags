<template>
  <div class="dialog-overlay" @click.self="$emit('close')">
    <div class="preview-dialog">
      <div class="preview-header">
        <div class="preview-title-row">
          <h3 class="preview-title">
            <i class="pi pi-sitemap"></i>
            Resource Relationships
          </h3>
          <button class="preview-close" @click="$emit('close')">
            <i class="pi pi-times"></i>
          </button>
        </div>
        <div class="preview-resource-info">
          <span class="service-badge">{{ resource.service_name }}</span>
          <span class="resource-id-text">{{ resource.resource_id }}</span>
          <span class="resource-region">{{ resource.region }}</span>
        </div>
      </div>

      <div class="preview-body">
        <div v-if="loading" class="preview-loading">
          <i class="pi pi-spin pi-spinner"></i> Loading relationships...
        </div>
        <div v-else-if="error" class="preview-error">{{ error }}</div>
        <div v-else-if="!graphData || graphData.nodes.length <= 1" class="preview-empty">
          <i class="pi pi-info-circle"></i>
          No relationships found for this resource.
        </div>
        <template v-else>
          <div class="preview-graph-area">
            <VChart
              ref="chartRef"
              class="preview-chart"
              :option="chartOption"
              autoresize
            />
          </div>
          <div class="preview-connections">
            <div class="connections-header">
              Connections ({{ connections.length }})
            </div>
            <div class="connections-list">
              <div
                v-for="conn in connections"
                :key="conn.arn"
                class="connection-item"
              >
                <span class="conn-service-badge" :style="{ background: serviceColor(conn.service) }">
                  {{ conn.service }}
                </span>
                <span class="conn-name">{{ conn.name }}</span>
                <span class="conn-type">{{ conn.relType }}</span>
              </div>
            </div>
          </div>
        </template>
      </div>

      <div class="preview-footer">
        <button class="btn btn-secondary" @click="$emit('close')">Close</button>
        <button class="btn btn-secondary" @click="$emit('detail', resource.id)">
          <i class="pi pi-eye"></i> View Details
        </button>
        <router-link
          :to="'/resources/map?resource_arn=' + encodeURIComponent(resource.resource_arn) + '&depth=1'"
          class="btn btn-primary"
        >
          <i class="pi pi-sitemap"></i> Open in Map
        </router-link>
        <button class="btn btn-warning" @click="blastRadiusArn = resource.resource_arn">
          <i class="pi pi-bolt"></i> Blast Radius
        </button>
      </div>
    </div>
    <BlastRadiusPanel
      v-if="blastRadiusArn"
      :arn="blastRadiusArn"
      @close="blastRadiusArn = null"
      @focus="() => { blastRadiusArn = null; $emit('close') }"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import BlastRadiusPanel from '@/components/BlastRadiusPanel.vue'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { GraphChart } from 'echarts/charts'
import { TooltipComponent } from 'echarts/components'
import VChart from 'vue-echarts'
import { api } from '@/api/client'
import type { ResourceResponse, GraphResponse } from '@/types/api'

use([CanvasRenderer, GraphChart, TooltipComponent])

const props = defineProps<{
  resource: ResourceResponse
}>()

defineEmits<{
  close: []
  detail: [id: string]
}>()

const chartRef = ref<InstanceType<typeof VChart> | null>(null)
const graphData = ref<GraphResponse | null>(null)
const loading = ref(true)
const error = ref<string | null>(null)
const blastRadiusArn = ref<string | null>(null)

const SERVICE_COLORS: Record<string, string> = {
  ec2: '#f97316', s3: '#22c55e', lambda: '#a855f7', rds: '#3b82f6',
  dynamodb: '#f59e0b', ecs: '#14b8a6', elb: '#06b6d4', elbv2: '#06b6d4',
  sns: '#e11d48', sqs: '#8b5cf6', cloudwatch: '#ef4444', logs: '#ef4444',
  eks: '#0ea5e9', elasticache: '#dc2626', vpc: '#6b7280', subnet: '#9ca3af',
  sg: '#4b5563', iam: '#eab308',
}

function serviceColor(service: string): string {
  return SERVICE_COLORS[service] || '#6b7280'
}

interface ConnectionInfo {
  arn: string
  name: string
  service: string
  relType: string
}

const connections = computed<ConnectionInfo[]>(() => {
  if (!graphData.value) return []
  const arn = props.resource.resource_arn
  const result: ConnectionInfo[] = []
  const seen = new Set<string>()

  for (const edge of graphData.value.edges) {
    const otherArn = edge.source === arn ? edge.target : edge.target === arn ? edge.source : null
    if (!otherArn || seen.has(otherArn)) continue
    seen.add(otherArn)

    const node = graphData.value.nodes.find(n => n.id === otherArn)
    result.push({
      arn: otherArn,
      name: node?.name || node?.resource_id || otherArn.split('/').pop() || otherArn.split(':').pop() || otherArn,
      service: node?.service_name || 'unknown',
      relType: edge.relationship_type,
    })
  }
  return result
})

const chartOption = computed(() => {
  if (!graphData.value) return {}

  const centerArn = props.resource.resource_arn
  const nodes = graphData.value.nodes.map(n => ({
    id: n.id,
    name: n.name || n.resource_id,
    symbolSize: n.id === centerArn ? 40 : 24,
    category: n.category,
    itemStyle: {
      color: SERVICE_COLORS[n.service_name] || '#6b7280',
      borderColor: n.id === centerArn ? '#fff' : 'transparent',
      borderWidth: n.id === centerArn ? 3 : 0,
    },
    label: {
      show: true,
      fontSize: n.id === centerArn ? 11 : 9,
      color: '#ccc',
    },
    value: n.service_name,
  }))

  const edges = graphData.value.edges.map(e => ({
    source: e.source,
    target: e.target,
    lineStyle: { color: '#555', width: 1, curveness: 0.1 },
    emphasis: { label: { show: true } },
    label: { show: false, formatter: e.relationship_type, fontSize: 8, color: '#999' },
  }))

  const categories = graphData.value.categories.map(c => ({
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
        const data = params.data as { name?: string; value?: string; id?: string }
        return `<b>${data?.name || ''}</b><br/>${data?.value || ''}`
      },
      backgroundColor: '#1a1a2e',
      borderColor: '#333',
      textStyle: { color: '#eee', fontSize: 11 },
    },
    series: [{
      type: 'graph',
      layout: 'force',
      data: nodes,
      links: edges,
      categories,
      roam: true,
      draggable: true,
      force: {
        repulsion: 150,
        gravity: 0.1,
        edgeLength: [60, 140],
        friction: 0.6,
      },
      emphasis: {
        focus: 'adjacency',
        lineStyle: { width: 2 },
      },
      label: { position: 'right', distance: 5 },
      edgeSymbol: ['none', 'arrow'],
      edgeSymbolSize: [0, 6],
    }],
    animationDuration: 800,
    animationEasingUpdate: 'quinticInOut' as const,
  }
})

onMounted(async () => {
  try {
    graphData.value = await api.resourceGraph({
      resource_arn: props.resource.resource_arn,
      depth: 2,
      max_nodes: 80,
    })
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Failed to load relationships'
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.dialog-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.6);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.preview-dialog {
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 12px;
  width: 800px;
  max-width: 94vw;
  max-height: 85vh;
  display: flex;
  flex-direction: column;
  box-shadow: 0 8px 40px rgba(0, 0, 0, 0.5);
}

.preview-header {
  padding: 1.25rem 1.5rem 1rem;
  border-bottom: 1px solid var(--surface-border);
}

.preview-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.preview-title {
  font-size: 1rem;
  font-weight: 600;
  color: var(--text-color);
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin: 0;
}

.preview-title i {
  color: var(--primary-color);
}

.preview-close {
  background: none;
  border: none;
  color: var(--text-color-secondary);
  cursor: pointer;
  padding: 0.3rem;
  font-size: 0.9rem;
}

.preview-close:hover {
  color: var(--text-color);
}

.preview-resource-info {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-top: 0.5rem;
}

.service-badge {
  background: rgba(32, 108, 245, 0.15);
  color: #5a9aff;
  padding: 0.15rem 0.4rem;
  border-radius: 4px;
  font-size: 0.75rem;
  font-weight: 500;
}

.resource-id-text {
  font-family: var(--font-mono), monospace;
  font-size: 0.8rem;
  color: var(--text-color-secondary);
}

.resource-region {
  font-size: 0.78rem;
  color: var(--text-color-secondary);
  opacity: 0.7;
}

.preview-body {
  flex: 1;
  display: flex;
  min-height: 0;
  overflow: hidden;
}

.preview-loading,
.preview-error,
.preview-empty {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  padding: 3rem;
  color: var(--text-color-secondary);
  font-size: 0.85rem;
}

.preview-error {
  color: #f87171;
}

.preview-graph-area {
  flex: 1;
  min-height: 320px;
  position: relative;
}

.preview-chart {
  width: 100%;
  height: 100%;
}

.preview-connections {
  width: 240px;
  border-left: 1px solid var(--surface-border);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.connections-header {
  padding: 0.6rem 0.75rem;
  font-size: 0.78rem;
  font-weight: 600;
  text-transform: uppercase;
  color: var(--text-color-secondary);
  background: var(--surface-ground);
  border-bottom: 1px solid var(--surface-border);
  flex-shrink: 0;
}

.connections-list {
  overflow-y: auto;
  flex: 1;
}

.connection-item {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.45rem 0.75rem;
  border-bottom: 1px solid var(--surface-border);
  font-size: 0.78rem;
}

.conn-service-badge {
  padding: 0.1rem 0.35rem;
  border-radius: 3px;
  font-size: 0.68rem;
  font-weight: 600;
  color: white;
  flex-shrink: 0;
}

.conn-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-color);
  font-family: var(--font-mono), monospace;
  font-size: 0.72rem;
}

.conn-type {
  font-size: 0.65rem;
  color: var(--text-color-secondary);
  opacity: 0.7;
  flex-shrink: 0;
  text-transform: uppercase;
}

.preview-footer {
  padding: 0.75rem 1.5rem;
  border-top: 1px solid var(--surface-border);
  display: flex;
  justify-content: flex-end;
  gap: 0.5rem;
}

.btn {
  padding: 0.45rem 0.85rem;
  border: none;
  border-radius: 6px;
  font-size: 0.82rem;
  cursor: pointer;
  font-weight: 500;
  display: flex;
  align-items: center;
  gap: 0.35rem;
  text-decoration: none;
  transition: all 0.15s;
}

.btn-primary {
  background: var(--gradient-brand-horizontal);
  color: white;
}

.btn-primary:hover {
  box-shadow: 0 0 14px rgba(32, 108, 245, 0.35);
}

.btn-secondary {
  background: var(--surface-ground);
  color: var(--text-color);
  border: 1px solid var(--surface-border);
}

.btn-secondary:hover {
  background: var(--surface-card-hover);
}

.btn-warning {
  background: rgba(245, 158, 11, 0.15);
  color: #f59e0b;
  border: 1px solid rgba(245, 158, 11, 0.3);
}

.btn-warning:hover {
  background: rgba(245, 158, 11, 0.25);
}
</style>
