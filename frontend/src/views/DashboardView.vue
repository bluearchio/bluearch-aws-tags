<template>
  <div class="dashboard">
    <!-- Scan in progress banner -->
    <div v-if="scanRunning && !hasData" class="scan-banner">
      <div class="scan-banner-icon">
        <i class="pi pi-spin pi-sync"></i>
      </div>
      <div class="scan-banner-body">
        <strong>Resource scan in progress</strong>
        <p>
          Discovering your AWS resources. Dashboard data will appear once the scan completes.
          <template v-if="scanProgress"> ({{ scanProgress }}%)</template>
        </p>
        <div class="scan-banner-bar">
          <div class="scan-banner-fill" :style="{ width: (scanProgress ?? 0) + '%' }"></div>
        </div>
        <span v-if="scanMessage" class="scan-banner-detail">{{ scanMessage }}</span>
      </div>
    </div>

    <!-- Summary Cards -->
    <div class="cards-grid" :class="{ 'cards-dimmed': scanRunning && !hasData }">
      <div class="stat-card stat-clickable" @click="router.push('/resources')">
        <div class="stat-icon" style="background: rgba(32, 108, 245, 0.12); color: #5a9aff;">
          <i class="pi pi-server"></i>
        </div>
        <div class="stat-body">
          <span class="stat-value">{{ dashboard?.total_resources ?? '-' }}</span>
          <span class="stat-label">Total Resources</span>
        </div>
      </div>
      <div class="stat-card stat-clickable" @click="router.push({ path: '/resources', query: { lifecycle_state: 'active' } })">
        <div class="stat-icon" style="background: rgba(34, 197, 94, 0.12); color: #4ade80;">
          <i class="pi pi-check-circle"></i>
        </div>
        <div class="stat-body">
          <span class="stat-value">{{ dashboard?.active ?? '-' }}</span>
          <span class="stat-label">Active</span>
        </div>
      </div>
      <div class="stat-card stat-clickable" @click="router.push({ path: '/resources', query: { lifecycle_state: 'warned' } })">
        <div class="stat-icon" style="background: rgba(234, 179, 8, 0.12); color: #facc15;">
          <i class="pi pi-exclamation-triangle"></i>
        </div>
        <div class="stat-body">
          <span class="stat-value">{{ dashboard?.warned ?? '-' }}</span>
          <span class="stat-label">Warned</span>
        </div>
      </div>
      <div class="stat-card stat-clickable" @click="router.push({ path: '/resources', query: { lifecycle_state: 'marked_for_deletion' } })">
        <div class="stat-icon" style="background: rgba(239, 68, 68, 0.12); color: #f87171;">
          <i class="pi pi-trash"></i>
        </div>
        <div class="stat-body">
          <span class="stat-value">{{ dashboard?.marked_for_deletion ?? '-' }}</span>
          <span class="stat-label">Marked for Deletion</span>
        </div>
      </div>
      <div class="stat-card stat-clickable" @click="router.push({ path: '/resources', query: { protected: 'true' } })">
        <div class="stat-icon" style="background: rgba(124, 58, 237, 0.12); color: #a78bfa;">
          <i class="pi pi-shield"></i>
        </div>
        <div class="stat-body">
          <span class="stat-value">{{ dashboard?.protected ?? '-' }}</span>
          <span class="stat-label">Protected</span>
        </div>
      </div>
      <div class="stat-card stat-clickable" @click="router.push({ path: '/resources', query: { lifecycle_state: 'expired' } })">
        <div class="stat-icon" style="background: rgba(239, 68, 68, 0.12); color: #f87171;">
          <i class="pi pi-calendar-times"></i>
        </div>
        <div class="stat-body">
          <span class="stat-value">{{ dashboard?.expired ?? '-' }}</span>
          <span class="stat-label">Expired</span>
        </div>
      </div>
      <div class="stat-card stat-clickable" @click="router.push('/lifecycle')">
        <div class="stat-icon" style="background: rgba(234, 88, 12, 0.12); color: #fb923c;">
          <i class="pi pi-clock"></i>
        </div>
        <div class="stat-body">
          <span class="stat-value">{{ dashboard?.expiring_7d ?? '-' }}</span>
          <span class="stat-label">Expiring (7d)</span>
        </div>
      </div>
      <div class="stat-card stat-clickable" @click="router.push({ path: '/resources', query: { tagged: 'true' } })">
        <div class="stat-icon" style="background: rgba(32, 108, 245, 0.12); color: #5a9aff;">
          <i class="pi pi-tag"></i>
        </div>
        <div class="stat-body">
          <span class="stat-value">{{ dashboard?.tagged ?? '-' }}</span>
          <span class="stat-label">Tagged</span>
        </div>
      </div>
    </div>

    <!-- Charts -->
    <div class="charts-grid" :class="{ 'charts-dimmed': scanRunning && !hasData }">
      <div class="chart-card clickable-chart">
        <h3 class="chart-title">Resources by Service</h3>
        <VChart v-if="serviceChartOption" class="chart" :option="serviceChartOption" autoresize @click="onServiceClick" />
        <div v-else class="chart-empty">
          <template v-if="scanRunning">
            <i class="pi pi-spin pi-spinner chart-empty-spin"></i>
            <span>Waiting for scan to finish...</span>
          </template>
          <template v-else>No data available</template>
        </div>
      </div>
      <div class="chart-card clickable-chart">
        <h3 class="chart-title">Resources by Region</h3>
        <VChart v-if="regionChartOption" class="chart" :option="regionChartOption" autoresize @click="onRegionClick" />
        <div v-else class="chart-empty">
          <template v-if="scanRunning">
            <i class="pi pi-spin pi-spinner chart-empty-spin"></i>
            <span>Waiting for scan to finish...</span>
          </template>
          <template v-else>No data available</template>
        </div>
      </div>
      <div class="chart-card clickable-chart">
        <h3 class="chart-title">Lifecycle State</h3>
        <VChart v-if="lifecycleChartOption" class="chart" :option="lifecycleChartOption" autoresize @click="onLifecycleClick" />
        <div v-else class="chart-empty">
          <template v-if="scanRunning">
            <i class="pi pi-spin pi-spinner chart-empty-spin"></i>
            <span>Waiting for scan to finish...</span>
          </template>
          <template v-else>No data available</template>
        </div>
      </div>
      <div class="chart-card clickable-chart" @click="!complianceChartOption && router.push('/compliance')">
        <h3 class="chart-title">Compliance Status</h3>
        <VChart v-if="complianceChartOption" class="chart" :option="complianceChartOption" autoresize />
        <div v-else class="chart-empty">
          <template v-if="scanRunning">
            <i class="pi pi-spin pi-spinner chart-empty-spin"></i>
            <span>Waiting for scan to finish...</span>
          </template>
          <template v-else>
            <i class="pi pi-check-circle" style="font-size: 1.5rem; color: var(--color-success); margin-bottom: 0.5rem;"></i>
            <span>All resources compliant</span>
            <span style="font-size: 0.78rem; opacity: 0.6;">Click to manage tag policies</span>
          </template>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { PieChart, BarChart } from 'echarts/charts'
import { TitleComponent, TooltipComponent, LegendComponent, GridComponent } from 'echarts/components'
import VChart from 'vue-echarts'
import { useLifecycleStore } from '@/stores/lifecycle'
import { useResourcesStore } from '@/stores/resources'
import { useJobsStore } from '@/stores/jobs'

use([CanvasRenderer, PieChart, BarChart, TitleComponent, TooltipComponent, LegendComponent, GridComponent])

const router = useRouter()
const lifecycleStore = useLifecycleStore()
const resourcesStore = useResourcesStore()
const jobsStore = useJobsStore()

const dashboard = computed(() => lifecycleStore.dashboard)

const scanRunning = computed(() => {
  const job = jobsStore.currentScanJob
  return job?.status === 'running' || job?.status === 'pending'
})

const scanProgress = computed(() => jobsStore.currentScanJob?.progress ?? null)
const scanMessage = computed(() => jobsStore.currentScanJob?.progress_message ?? null)

const hasData = computed(() => {
  return (dashboard.value?.total_resources ?? 0) > 0
})

// Refresh dashboard data when scan completes
watch(
  () => jobsStore.currentScanJob?.status,
  (status, oldStatus) => {
    if (oldStatus === 'running' && status === 'completed') {
      lifecycleStore.fetchDashboard()
      resourcesStore.fetchStats()
    }
  },
)

const serviceChartOption = computed(() => {
  const stats = resourcesStore.stats
  if (!stats || !Object.keys(stats.by_service).length) return null
  const data = Object.entries(stats.by_service).map(([name, value]) => ({ name, value }))
  return {
    tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
    series: [{
      type: 'pie',
      radius: ['40%', '70%'],
      itemStyle: { borderRadius: 6, borderColor: 'var(--surface-card)', borderWidth: 2 },
      label: { show: true, formatter: '{b}: {c}', color: 'var(--text-color-secondary)' },
      data,
    }],
  }
})

const regionChartOption = computed(() => {
  const stats = resourcesStore.stats
  if (!stats || !Object.keys(stats.by_region).length) return null
  const entries = Object.entries(stats.by_region).sort((a, b) => b[1] - a[1])
  return {
    tooltip: { trigger: 'axis' },
    grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
    xAxis: {
      type: 'category',
      data: entries.map(([k]) => k),
      axisLabel: { rotate: 30, fontSize: 11, color: '#a0a0a0' },
      axisLine: { lineStyle: { color: '#262626' } },
    },
    yAxis: {
      type: 'value',
      axisLabel: { color: '#a0a0a0' },
      splitLine: { lineStyle: { color: '#262626' } },
      axisLine: { lineStyle: { color: '#262626' } },
    },
    series: [{
      type: 'bar',
      data: entries.map(([_, v]) => v),
      itemStyle: { color: '#206CF5', borderRadius: [4, 4, 0, 0] },
    }],
  }
})

const lifecycleChartOption = computed(() => {
  const d = dashboard.value
  if (!d) return null
  const data = [
    { name: 'Active', value: d.active, itemStyle: { color: '#22c55e' } },
    { name: 'Warned', value: d.warned, itemStyle: { color: '#eab308' } },
    { name: 'Marked', value: d.marked_for_deletion, itemStyle: { color: '#ef4444' } },
    { name: 'Protected', value: d.protected, itemStyle: { color: '#7c3aed' } },
    { name: 'Expired', value: d.expired, itemStyle: { color: '#991b1b' } },
  ].filter(item => item.value > 0)
  if (!data.length) return null
  return {
    tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
    series: [{
      type: 'pie',
      radius: ['40%', '70%'],
      itemStyle: { borderRadius: 6, borderColor: 'var(--surface-card)', borderWidth: 2 },
      label: { show: true, formatter: '{b}: {c}', color: 'var(--text-color-secondary)' },
      data,
    }],
  }
})

const complianceChartOption = computed(() => {
  const stats = resourcesStore.stats
  if (!stats || !stats.by_compliance_status || !Object.keys(stats.by_compliance_status).length) return null
  const colorMap: Record<string, string> = {
    compliant: '#22c55e',
    noncompliant: '#ef4444',
    non_compliant: '#ef4444',
    unknown: '#9ca3af',
  }
  const data = Object.entries(stats.by_compliance_status).map(([name, value]) => ({
    name: name.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()),
    value,
    itemStyle: { color: colorMap[name.toLowerCase()] || '#6b7280' },
  }))
  if (!data.length) return null
  return {
    tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
    series: [{
      type: 'pie',
      radius: ['40%', '70%'],
      itemStyle: { borderRadius: 6, borderColor: 'var(--surface-card)', borderWidth: 2 },
      label: { show: true, formatter: '{b}: {c}', color: 'var(--text-color-secondary)' },
      data,
    }],
  }
})

// Chart click handlers - navigate to filtered views
const lifecycleNameToState: Record<string, string> = {
  Active: 'active',
  Warned: 'warned',
  Marked: 'marked_for_deletion',
  Protected: 'protected',
  Expired: 'expired',
}

function onServiceClick(params: { name?: string }) {
  if (params.name) {
    router.push({ path: '/resources', query: { service: params.name } })
  }
}

function onRegionClick(params: { name?: string }) {
  if (params.name) {
    router.push({ path: '/resources', query: { region: params.name } })
  }
}

function onLifecycleClick(params: { name?: string }) {
  if (params.name) {
    const state = lifecycleNameToState[params.name]
    if (state === 'protected') {
      router.push({ path: '/resources', query: { protected: 'true' } })
    } else if (state) {
      router.push({ path: '/resources', query: { lifecycle_state: state } })
    }
  }
}

onMounted(() => {
  lifecycleStore.fetchDashboard()
  resourcesStore.fetchStats()
})
</script>

<style scoped>
.dashboard {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}

.cards-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 1rem;
}

.stat-card {
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 10px;
  padding: 1.25rem;
  display: flex;
  align-items: center;
  gap: 1rem;
}

.stat-icon {
  width: 44px;
  height: 44px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.stat-icon i {
  font-size: 1.2rem;
}

.stat-body {
  display: flex;
  flex-direction: column;
}

.stat-value {
  font-size: 1.5rem;
  font-weight: 700;
  line-height: 1.2;
  color: var(--text-color);
}

.stat-label {
  font-size: 0.78rem;
  color: var(--text-color-secondary);
  margin-top: 2px;
}

.charts-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(380px, 1fr));
  gap: 1rem;
}

.chart-card {
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 10px;
  padding: 1.25rem;
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}

.chart-card:hover {
  border-color: rgba(32, 108, 245, 0.3);
  box-shadow: var(--glow-blue);
}

.chart-title {
  font-size: 0.9rem;
  font-weight: 600;
  margin-bottom: 1rem;
  background: var(--gradient-brand-horizontal);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.chart {
  height: 300px;
  width: 100%;
}

.chart-empty {
  height: 300px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: var(--text-color-secondary);
  font-size: 0.875rem;
  gap: 0.25rem;
}

.stat-clickable {
  cursor: pointer;
  transition: all 0.2s ease;
  position: relative;
}

.stat-clickable:hover {
  border-color: transparent;
  box-shadow: 0 0 20px rgba(32, 108, 245, 0.2);
  transform: translateY(-1px);
}

/* Gradient border on hover */
.stat-clickable::before {
  content: '';
  position: absolute;
  inset: -1px;
  border-radius: 11px;
  background: var(--gradient-border);
  z-index: -1;
  opacity: 0;
  transition: opacity 0.2s ease;
}

.stat-clickable:hover::before {
  opacity: 1;
}

.clickable-chart :deep(canvas) {
  cursor: pointer;
}

/* Scan banner */
.scan-banner {
  display: flex;
  gap: 1rem;
  padding: 1.25rem 1.5rem;
  background: rgba(32, 108, 245, 0.12);
  border: 1px solid rgba(32, 108, 245, 0.25);
  border-radius: 10px;
}

.scan-banner-icon {
  font-size: 1.5rem;
  color: #5a9aff;
  flex-shrink: 0;
}

.scan-banner-body {
  flex: 1;
  min-width: 0;
}

.scan-banner-body strong {
  font-size: 0.95rem;
  color: #5a9aff;
  display: block;
  margin-bottom: 0.25rem;
}

.scan-banner-body p {
  font-size: 0.82rem;
  color: var(--text-color-secondary);
  margin: 0 0 0.6rem;
}

.scan-banner-bar {
  height: 6px;
  background: rgba(32, 108, 245, 0.15);
  border-radius: 3px;
  overflow: hidden;
  margin-bottom: 0.35rem;
}

.scan-banner-fill {
  height: 100%;
  background: var(--gradient-brand-horizontal);
  border-radius: 3px;
  transition: width 0.3s ease;
  box-shadow: 0 0 8px rgba(25, 212, 212, 0.3);
}

.scan-banner-detail {
  font-size: 0.75rem;
  color: var(--text-color-secondary);
}

/* Dimmed state while scanning with no data */
.cards-dimmed,
.charts-dimmed {
  opacity: 0.45;
  pointer-events: none;
}

/* Chart empty scanning state */
.chart-empty-spin {
  font-size: 1.1rem;
  color: var(--primary-color);
}

/* Spinner */
@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.pi-spin { animation: spin 1s linear infinite; }
</style>
