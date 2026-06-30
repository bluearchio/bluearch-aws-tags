<template>
  <div class="audit-view">
    <div class="audit-header">
      <h2 class="audit-title">Audit Log</h2>
      <div class="audit-header-actions">
        <label class="auto-refresh-toggle">
          <input type="checkbox" v-model="autoRefresh" />
          <span>Auto-refresh</span>
        </label>
        <button class="btn btn-secondary btn-sm" :disabled="loading" @click="refresh">
          <i class="pi pi-refresh" :class="{ spin: loading }"></i>
          Refresh
        </button>
      </div>
    </div>

    <!-- Tabs -->
    <div class="audit-tabs">
      <button
        class="tab-btn"
        :class="{ active: activeTab === 'lifecycle' }"
        @click="activeTab = 'lifecycle'"
      >
        <i class="pi pi-clock"></i> Lifecycle Audit
      </button>
      <button
        class="tab-btn"
        :class="{ active: activeTab === 'events' }"
        @click="activeTab = 'events'; loadEventTracking()"
      >
        <i class="pi pi-bolt"></i> Event Tracking
      </button>
    </div>

    <!-- Lifecycle Audit Tab -->
    <template v-if="activeTab === 'lifecycle'">
      <!-- Operation Filter Pills -->
      <div class="filter-pills">
        <button
          v-for="op in operationFilters"
          :key="op.value"
          class="pill-btn"
          :class="{ active: activeFilter === op.value }"
          @click="setFilter(op.value)"
        >
          {{ op.label }}
        </button>
      </div>

      <!-- Audit Table -->
      <div class="table-wrap">
        <table class="data-table" v-if="filteredItems.length > 0 || loading">
          <thead>
            <tr>
              <th>Timestamp</th>
              <th>Resource ARN</th>
              <th>Operation</th>
              <th>Old State</th>
              <th>New State</th>
              <th>Executed By</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="entry in filteredItems" :key="entry.id">
              <td class="mono ts-col">{{ formatTimestamp(entry.executed_at) }}</td>
              <td>
                <button
                  v-if="entry.resource_id"
                  class="arn-link"
                  @click="router.push(`/resources/${entry.resource_id}`)"
                >
                  {{ truncateArn(entry.resource_arn) }}
                </button>
                <span v-else class="mono">{{ truncateArn(entry.resource_arn) }}</span>
              </td>
              <td>
                <span class="op-pill" :class="opClass(entry.operation)">{{ entry.operation }}</span>
              </td>
              <td>
                <span v-if="entry.old_state" class="state-text">{{ entry.old_state }}</span>
                <span v-else-if="entry.old_expires_at" class="mono">{{ formatDate(entry.old_expires_at) }}</span>
                <span v-else class="dim">-</span>
              </td>
              <td>
                <span v-if="entry.new_state" class="state-text">{{ entry.new_state }}</span>
                <span v-else-if="entry.new_expires_at" class="mono">{{ formatDate(entry.new_expires_at) }}</span>
                <span v-else class="dim">-</span>
              </td>
              <td class="mono">{{ entry.executed_by || '-' }}</td>
              <td>
                <span v-if="entry.success" class="status-pill pill-success">OK</span>
                <span v-else class="status-pill pill-danger" :title="entry.error_message">Error</span>
              </td>
            </tr>
          </tbody>
        </table>
        <div v-else-if="!loading" class="empty-state">
          <i class="pi pi-list"></i>
          <p>No audit log entries found.</p>
        </div>
        <div v-if="loading" class="loading-row">
          <i class="pi pi-spin pi-spinner"></i> Loading...
        </div>
      </div>

      <!-- Pagination -->
      <div v-if="total > pageSize" class="pagination">
        <button class="btn btn-secondary btn-sm" :disabled="currentPage === 1" @click="goToPage(currentPage - 1)">
          <i class="pi pi-chevron-left"></i>
        </button>
        <span class="page-info">Page {{ currentPage }} of {{ totalPages }}</span>
        <button class="btn btn-secondary btn-sm" :disabled="currentPage >= totalPages" @click="goToPage(currentPage + 1)">
          <i class="pi pi-chevron-right"></i>
        </button>
      </div>
    </template>

    <!-- Event Tracking Tab -->
    <template v-if="activeTab === 'events'">
      <div v-if="etLoading" class="loading-row">
        <i class="pi pi-spin pi-spinner"></i> Loading event tracking status...
      </div>
      <div v-else-if="etData && etData.instances.length > 0" class="table-wrap">
        <table class="data-table">
          <thead>
            <tr>
              <th>Account</th>
              <th>Region</th>
              <th>Status</th>
              <th>Events Today</th>
              <th>Messages Processed</th>
              <th>Last Polled</th>
              <th>Last Event</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="inst in etData.instances" :key="`${inst.account_id}:${inst.region}`">
              <td class="mono">{{ inst.account_id }}</td>
              <td>{{ inst.region }}</td>
              <td>
                <span class="status-pill" :class="{
                  'pill-success': inst.status === 'active',
                  'pill-warning': inst.status === 'paused',
                  'pill-danger': inst.status === 'error' || inst.status === 'failed',
                  'pill-neutral': !['active','paused','error','failed'].includes(inst.status),
                }">{{ inst.status }}</span>
              </td>
              <td class="mono">{{ inst.events_today }}</td>
              <td class="mono">{{ inst.messages_processed }}</td>
              <td>{{ formatTimeAgo(inst.last_polled_at) }}</td>
              <td>{{ formatTimeAgo(inst.last_event_at) }}</td>
            </tr>
          </tbody>
        </table>
        <div class="et-summary">
          <span>Service: <strong>{{ etData.service_running ? (etData.service_paused ? 'Paused' : 'Running') : 'Stopped' }}</strong></span>
          <span>Queues: <strong>{{ etData.active_queues }} / {{ etData.total_queues }} active</strong></span>
        </div>
      </div>
      <div v-else class="empty-state">
        <i class="pi pi-bolt"></i>
        <p>No event tracking instances deployed.</p>
        <router-link to="/setup" class="btn btn-primary btn-sm">Set up Event Tracking</router-link>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@/api/client'
import type { AuditLogEntry, EventTrackingStatusResponse } from '@/types/api'

const router = useRouter()

const activeTab = ref<'lifecycle' | 'events'>('lifecycle')
const loading = ref(false)
const items = ref<AuditLogEntry[]>([])
const total = ref(0)
const pageSize = 50
const currentPage = ref(1)
const activeFilter = ref('all')
const autoRefresh = ref(false)
let refreshInterval: ReturnType<typeof setInterval> | null = null

const etData = ref<EventTrackingStatusResponse | null>(null)
const etLoading = ref(false)

const operationFilters = [
  { label: 'All', value: 'all' },
  { label: 'TTL Set', value: 'TTL_SET' },
  { label: 'TTL Extended', value: 'TTL_EXTENDED' },
  { label: 'Protected', value: 'PROTECTED' },
  { label: 'Deletion Scheduled', value: 'DELETION_SCHEDULED' },
  { label: 'Deleted', value: 'RESOURCE_DELETED' },
]

const filteredItems = computed(() => {
  if (activeFilter.value === 'all') return items.value
  return items.value.filter(i => i.operation === activeFilter.value)
})

const totalPages = computed(() => Math.ceil(total.value / pageSize))

function setFilter(val: string) {
  activeFilter.value = val
}

async function fetchAuditLog() {
  loading.value = true
  try {
    const offset = (currentPage.value - 1) * pageSize
    const resp = await api.auditLog({ limit: pageSize, offset })
    items.value = resp.items
    total.value = resp.total
  } catch {
    // Error shown by API client
  } finally {
    loading.value = false
  }
}

async function loadEventTracking() {
  if (etData.value) return
  etLoading.value = true
  try {
    etData.value = await api.eventTrackingStatus()
  } catch {
    // Error shown by API client
  } finally {
    etLoading.value = false
  }
}

function goToPage(page: number) {
  currentPage.value = page
  fetchAuditLog()
}

function refresh() {
  if (activeTab.value === 'lifecycle') {
    fetchAuditLog()
  } else {
    etData.value = null
    loadEventTracking()
  }
}

function formatTimestamp(iso?: string): string {
  if (!iso) return '-'
  const d = new Date(iso)
  return d.toLocaleString(undefined, {
    month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  })
}

function formatDate(iso?: string): string {
  if (!iso) return '-'
  const d = new Date(iso)
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
}

function formatTimeAgo(isoString?: string): string {
  if (!isoString) return '-'
  const d = new Date(isoString)
  const now = new Date()
  const diffMs = now.getTime() - d.getTime()
  const diffMin = Math.floor(diffMs / 60000)
  if (diffMin < 1) return 'just now'
  if (diffMin < 60) return `${diffMin}m ago`
  const diffHr = Math.floor(diffMin / 60)
  if (diffHr < 24) return `${diffHr}h ago`
  const diffDay = Math.floor(diffHr / 24)
  return `${diffDay}d ago`
}

function truncateArn(arn: string): string {
  if (!arn) return '-'
  // Show service:type/name portion
  const parts = arn.split(':')
  if (parts.length >= 6) {
    return parts.slice(5).join(':')
  }
  return arn.length > 60 ? arn.slice(0, 57) + '...' : arn
}

function opClass(op: string): string {
  switch (op) {
    case 'TTL_SET': return 'op-ttl-set'
    case 'TTL_EXTENDED': return 'op-ttl-extended'
    case 'PROTECTED': return 'op-protected'
    case 'DELETION_SCHEDULED': return 'op-deletion'
    case 'RESOURCE_DELETED': return 'op-deleted'
    default: return 'op-default'
  }
}

// Auto-refresh
function startAutoRefresh() {
  stopAutoRefresh()
  refreshInterval = setInterval(() => {
    if (activeTab.value === 'lifecycle') fetchAuditLog()
    else { etData.value = null; loadEventTracking() }
  }, 15000)
}

function stopAutoRefresh() {
  if (refreshInterval) {
    clearInterval(refreshInterval)
    refreshInterval = null
  }
}

import { watch } from 'vue'
watch(autoRefresh, (val) => {
  if (val) startAutoRefresh()
  else stopAutoRefresh()
})

onMounted(() => {
  fetchAuditLog()
})

onUnmounted(() => {
  stopAutoRefresh()
})
</script>

<style scoped>
.audit-view {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.audit-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.audit-title {
  font-size: 1.1rem;
  font-weight: 600;
}

.audit-header-actions {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.auto-refresh-toggle {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  font-size: 0.78rem;
  color: var(--text-color-secondary);
  cursor: pointer;
}

.auto-refresh-toggle input {
  cursor: pointer;
}

/* Tabs */
.audit-tabs {
  display: flex;
  gap: 0;
  border-bottom: 2px solid var(--surface-border);
}

.tab-btn {
  padding: 0.6rem 1.25rem;
  border: none;
  background: none;
  color: var(--text-color-secondary);
  font-size: 0.85rem;
  font-weight: 500;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 0.4rem;
  border-bottom: 2px solid transparent;
  margin-bottom: -2px;
  transition: all 0.15s;
}

.tab-btn:hover {
  color: var(--text-color);
}

.tab-btn.active {
  color: var(--primary-color);
  border-bottom-color: var(--primary-color);
}

/* Filter Pills */
.filter-pills {
  display: flex;
  gap: 0.35rem;
  flex-wrap: wrap;
}

.pill-btn {
  padding: 0.3rem 0.7rem;
  border: 1px solid var(--surface-border);
  border-radius: 16px;
  background: var(--surface-card);
  color: var(--text-color-secondary);
  font-size: 0.75rem;
  cursor: pointer;
  transition: all 0.15s;
}

.pill-btn:hover {
  border-color: var(--primary-color);
  color: var(--primary-color);
}

.pill-btn.active {
  background: rgba(32, 108, 245, 0.15);
  border-color: var(--primary-color);
  color: var(--primary-color);
  font-weight: 600;
}

/* Table */
.table-wrap {
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 10px;
  overflow-x: auto;
}

.data-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.82rem;
}

.data-table th {
  text-align: left;
  padding: 0.65rem 1rem;
  font-weight: 600;
  font-size: 0.75rem;
  text-transform: uppercase;
  letter-spacing: 0.03em;
  color: var(--text-color-secondary);
  background: var(--surface-ground);
  border-bottom: 1px solid var(--surface-border);
  white-space: nowrap;
}

.data-table td {
  padding: 0.55rem 1rem;
  border-bottom: 1px solid var(--surface-border);
  color: var(--text-color);
}

.data-table tbody tr:last-child td { border-bottom: none; }
.data-table tbody tr:hover { background: rgba(32, 108, 245, 0.05); }

.mono {
  font-family: 'SF Mono', monospace;
  font-size: 0.78rem;
}

.ts-col {
  white-space: nowrap;
}

.dim {
  color: var(--text-color-secondary);
  opacity: 0.6;
}

/* ARN link */
.arn-link {
  background: none;
  border: none;
  color: var(--primary-color);
  cursor: pointer;
  font-family: 'SF Mono', monospace;
  font-size: 0.78rem;
  text-decoration: none;
  padding: 0;
}

.arn-link:hover {
  text-decoration: underline;
}

/* Operation pills */
.op-pill {
  display: inline-block;
  padding: 0.12rem 0.5rem;
  border-radius: 10px;
  font-size: 0.72rem;
  font-weight: 600;
  white-space: nowrap;
}

.op-ttl-set { background: rgba(32, 108, 245, 0.15); color: #5a9aff; }
.op-ttl-extended { background: rgba(25, 212, 212, 0.15); color: #19D4D4; }
.op-protected { background: rgba(168, 85, 247, 0.15); color: #c084fc; }
.op-deletion { background: rgba(234, 179, 8, 0.15); color: #facc15; }
.op-deleted { background: rgba(239, 68, 68, 0.15); color: #f87171; }
.op-default { background: var(--surface-ground); color: var(--text-color-secondary); }

/* State text */
.state-text {
  font-size: 0.8rem;
}

/* Status pills */
.status-pill {
  display: inline-block;
  padding: 0.12rem 0.5rem;
  border-radius: 10px;
  font-size: 0.72rem;
  font-weight: 600;
}

.pill-success { background: rgba(34, 197, 94, 0.15); color: #4ade80; }
.pill-warning { background: rgba(234, 179, 8, 0.15); color: #facc15; }
.pill-danger { background: rgba(239, 68, 68, 0.15); color: #f87171; }
.pill-neutral { background: var(--surface-ground); color: var(--text-color-secondary); }

/* Pagination */
.pagination {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.75rem;
}

.page-info {
  font-size: 0.82rem;
  color: var(--text-color-secondary);
}

/* Loading */
.loading-row {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  padding: 2rem;
  color: var(--text-color-secondary);
  font-size: 0.85rem;
}

/* Empty state */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 3rem 2rem;
  color: var(--text-color-secondary);
  text-align: center;
  gap: 0.5rem;
}

.empty-state > i {
  font-size: 2rem;
  opacity: 0.4;
}

.empty-state p {
  font-size: 0.88rem;
  margin: 0;
}

/* ET summary */
.et-summary {
  display: flex;
  gap: 1.5rem;
  padding: 0.65rem 1rem;
  border-top: 1px solid var(--surface-border);
  font-size: 0.78rem;
  color: var(--text-color-secondary);
}

.et-summary strong {
  color: var(--text-color);
}

/* Buttons */
.btn {
  padding: 0.5rem 1rem;
  border: none;
  border-radius: 6px;
  font-size: 0.85rem;
  cursor: pointer;
  font-weight: 500;
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  transition: all 0.15s;
}

.btn-primary {
  background: var(--gradient-brand-horizontal);
  color: white;
}

.btn-secondary {
  background: var(--surface-ground);
  color: var(--text-color);
  border: 1px solid var(--surface-border);
}

.btn-secondary:hover:not(:disabled) {
  background: var(--surface-border);
}

.btn-secondary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-sm {
  padding: 0.3rem 0.65rem;
  font-size: 0.78rem;
}

.spin { animation: spin 1s linear infinite; }
@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
</style>
