<template>
  <div class="resources-view">
    <PermissionBanner feature="discover_resources" />

    <!-- Scan Status Bar -->
    <div class="scan-bar">
      <div class="scan-bar-left">
        <button
          class="btn scan-btn"
          :class="{ 'scan-btn-running': isScanRunning }"
          :disabled="isScanRunning || selectedScanRegions.length === 0"
          @click="startScan"
        >
          <i :class="isScanRunning ? 'pi pi-spin pi-spinner' : 'pi pi-refresh'"></i>
          {{ isScanRunning ? 'Scanning...' : scanButtonLabel }}
        </button>
        <button
          v-if="isScanRunning"
          class="btn stop-scan-btn"
          @click="stopScan"
        >
          <i class="pi pi-stop-circle"></i>
          Stop
        </button>
        <div class="scan-region-picker">
          <button class="scan-region-toggle" @click="showRegionPicker = !showRegionPicker">
            <i class="pi pi-globe"></i>
            {{ selectedScanRegions.length === availableRegions.length ? 'All regions' : `${selectedScanRegions.length} region${selectedScanRegions.length !== 1 ? 's' : ''}` }}
            <i class="pi" :class="showRegionPicker ? 'pi-chevron-up' : 'pi-chevron-down'"></i>
          </button>
          <div v-if="showRegionPicker" class="scan-region-dropdown">
            <label class="scan-region-option">
              <input
                type="checkbox"
                :checked="selectedScanRegions.length === availableRegions.length"
                @change="toggleAllRegions"
              />
              <span>Select All</span>
            </label>
            <div class="scan-region-divider"></div>
            <label
              v-for="r in availableRegions"
              :key="r"
              class="scan-region-option"
            >
              <input
                type="checkbox"
                :checked="selectedScanRegions.includes(r)"
                @change="toggleScanRegion(r)"
              />
              <span>{{ r }}</span>
            </label>
          </div>
        </div>
        <div v-if="isScanRunning && jobsStore.currentScanJob" class="scan-progress-info">
          <div class="scan-progress-bar">
            <div class="scan-progress-fill" :style="{ width: jobsStore.currentScanJob.progress + '%' }"></div>
          </div>
          <span class="scan-progress-text">{{ jobsStore.currentScanJob.progress_message || `${jobsStore.currentScanJob.progress}%` }}</span>
        </div>
      </div>
      <div class="scan-bar-right">
        <span v-if="lastScanTime" class="scan-status-item">
          <i class="pi pi-clock"></i>
          Last scan: {{ lastScanTime }}
        </span>
        <span v-else class="scan-status-item scan-status-dim">
          <i class="pi pi-clock"></i>
          Never scanned
        </span>
        <span class="scan-status-divider"></span>
        <span
          class="scan-status-item"
          :class="etActive ? 'scan-status-ok' : 'scan-status-dim'"
        >
          <i class="pi pi-bolt"></i>
          {{ etActive ? `Event tracking (${etQueueCount} queue${etQueueCount !== 1 ? 's' : ''})` : 'Event tracking off' }}
        </span>
      </div>
    </div>

    <!-- Event Tracking Banner -->
    <div v-if="showETBanner" class="et-warning-banner">
      <i class="pi pi-bolt"></i>
      <span>Real-time tracking is not enabled. Resource data may be stale.</span>
      <router-link to="/setup" class="et-banner-link">Set up Event Tracking</router-link>
      <button class="et-banner-dismiss" @click="etBannerDismissed = true">
        <i class="pi pi-times"></i>
      </button>
    </div>
    <!-- Bulk Actions Bar -->
    <div v-if="selectedIds.size > 0" class="bulk-bar">
      <span class="bulk-count">{{ selectedIds.size }} selected</span>
      <button class="btn btn-sm bulk-btn" @click="bulkSetTTL(30)">Set TTL 30d</button>
      <button class="btn btn-sm bulk-btn" @click="bulkExtend(7)">Extend +7d</button>
      <button class="btn btn-sm bulk-btn-purple" @click="bulkProtect(true)">
        <i class="pi pi-shield"></i> Protect
      </button>
      <button class="btn btn-sm bulk-btn-outline" @click="bulkProtect(false)">Unprotect</button>
      <button class="btn btn-sm bulk-btn-danger" @click="bulkRemoveTags()">
        <i class="pi pi-times"></i> Remove Tags
      </button>
      <button
        v-if="store.filters.lifecycle_state === 'marked_for_deletion'"
        class="btn btn-sm bulk-btn-delete"
        @click="openBulkDeleteConfirm"
      >
        <i class="pi pi-ban"></i> Execute Delete
      </button>
      <button class="btn btn-sm bulk-btn-outline" @click="selectedIds.clear()">Deselect All</button>
    </div>

    <!-- Filters -->
    <div class="filters-bar">
      <div class="filter-group">
        <input
          v-model="store.filters.search"
          type="text"
          placeholder="Search ARN or ID..."
          class="filter-input search-input"
          @keyup.enter="store.fetchResources()"
        />
        <select v-model="store.filters.service" class="filter-input" @change="applyFilters">
          <option value="">All Services</option>
          <option v-for="svc in serviceOptions" :key="svc" :value="svc">{{ svc }}</option>
        </select>
        <select v-model="store.filters.region" class="filter-input" @change="applyFilters">
          <option value="">All Regions</option>
          <option v-for="r in regionOptions" :key="r" :value="r">{{ r }}</option>
        </select>
        <select v-model="store.filters.account_id" class="filter-input" @change="applyFilters">
          <option value="">All Accounts</option>
          <option v-for="acct in accountOptions" :key="acct" :value="acct">{{ acct }}</option>
        </select>
        <select v-model="store.filters.resource_type" class="filter-input" @change="applyFilters">
          <option value="">All Types</option>
          <option v-for="rt in resourceTypeOptions" :key="rt" :value="rt">{{ rt }}</option>
        </select>
        <select v-model="store.filters.lifecycle_state" class="filter-input" @change="onLifecycleStateChange">
          <option value="">All States</option>
          <option value="active">Active</option>
          <option value="warned">Warned</option>
          <option value="marked_for_deletion">Marked for Deletion</option>
          <option value="expired">Expired</option>
          <option value="protected">Protected</option>
        </select>
      </div>
      <div class="filter-actions">
        <label class="tagged-filter" :class="{ active: store.filters.tagged === 'true' }">
          <input
            type="checkbox"
            :checked="store.filters.tagged === 'true'"
            @change="toggleTaggedFilter"
          />
          <i class="pi pi-tag"></i>
          Tagged
        </label>
        <button class="btn btn-secondary" @click="handleReset">Reset</button>
        <button class="btn btn-primary" @click="store.fetchResources()">Search</button>
      </div>
    </div>

    <!-- Lifecycle State Legend -->
    <div class="legend-bar">
      <span class="legend-label">
        <i class="pi pi-info-circle"></i> States:
      </span>
      <span class="legend-item">
        <span class="legend-dot dot-active"></span> active -- tracked, TTL set
      </span>
      <span class="legend-item">
        <span class="legend-dot dot-warned"></span> warned -- approaching expiry
      </span>
      <span class="legend-item">
        <span class="legend-dot dot-marked"></span> marked_for_deletion -- queued for cleanup
      </span>
      <span class="legend-item">
        <span class="legend-dot dot-protected"></span> protected -- deletion blocked
      </span>
      <span class="legend-item">
        <span class="legend-dot dot-expired"></span> expired -- past TTL
      </span>
      <span class="legend-item">
        <span class="legend-dot dot-unknown"></span> unknown -- no policy assigned
      </span>
    </div>

    <!-- Table -->
    <div class="table-card">
      <div v-if="store.loading" class="table-loading">Loading resources...</div>
      <div v-else-if="store.error" class="table-error">{{ store.error }}</div>
      <table v-else class="data-table">
        <thead>
          <tr>
            <th class="checkbox-col select-all-col">
              <label class="select-all-label">
                <input
                  type="checkbox"
                  :checked="allSelected"
                  :indeterminate="someSelected && !allSelected"
                  @change="toggleSelectAll"
                />
                <span class="select-all-text">All</span>
              </label>
            </th>
            <th>Service</th>
            <th>Resource ID</th>
            <th>Type</th>
            <th>Region</th>
            <th>Account</th>
            <th>State</th>
            <th>Expires</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="resource in store.resources"
            :key="resource.id"
            class="table-row"
            :class="{ 'row-selected': selectedIds.has(resource.id) }"
            @click="onRowClick(resource)"
          >
            <td class="checkbox-col" @click.stop>
              <input
                type="checkbox"
                :checked="selectedIds.has(resource.id)"
                @change="toggleSelect(resource.id)"
              />
            </td>
            <td>
              <span class="service-badge">{{ resource.service_name }}</span>
            </td>
            <td class="resource-id">{{ resource.resource_id }}</td>
            <td>{{ resource.resource_type }}</td>
            <td>{{ resource.region }}</td>
            <td class="account-id">{{ resource.account_id }}</td>
            <td>
              <span class="state-badge" :class="getStateBadgeClass(resource)">
                {{ getStateLabel(resource) }}
              </span>
              <span v-if="resource.expires_at" class="expiry-relative" :class="getExpiryClass(resource.expires_at)">
                {{ getExpiryText(resource.expires_at) }}
              </span>
            </td>
            <td>{{ fmt.formatDate(resource.expires_at) }}</td>
            <td class="actions-cell" @click.stop>
              <button
                class="btn-action"
                title="Set TTL 30d"
                @click="setResourceTTL(resource, 30)"
              >TTL</button>
              <button
                v-if="resource.expires_at"
                class="btn-action"
                title="Extend 7 days"
                @click="extendResource(resource, 7)"
              >+7d</button>
              <button
                class="btn-action btn-action-purple"
                :title="resource.protected ? 'Unprotect' : 'Protect'"
                @click="toggleProtect(resource)"
              >
                <i class="pi pi-shield"></i>
              </button>
              <button
                v-if="resource.lifecycle_state === 'marked_for_deletion' && !resource.protected"
                class="btn-action btn-action-danger"
                title="Delete from AWS"
                @click="openSingleDeleteConfirm(resource)"
              >
                <i class="pi pi-ban"></i>
              </button>
              <button
                v-if="hasTagManagerTags(resource)"
                class="btn-action btn-action-danger"
                title="Remove tag-manager tags"
                @click="removeResourceTags(resource)"
              >
                <i class="pi pi-times"></i>
              </button>
            </td>
          </tr>
          <tr v-if="!store.resources.length">
            <td colspan="9" class="table-empty">No resources found</td>
          </tr>
        </tbody>
      </table>

      <!-- Pagination -->
      <div v-if="store.total > store.filters.limit" class="pagination">
        <span class="pagination-info">
          Showing {{ store.filters.offset + 1 }}-{{ Math.min(store.filters.offset + store.filters.limit, store.total) }}
          of {{ store.total }}
        </span>
        <div class="pagination-buttons">
          <button
            class="btn btn-sm"
            :disabled="store.filters.offset === 0"
            @click="store.setPage(store.filters.offset - store.filters.limit)"
          >Prev</button>
          <button
            class="btn btn-sm"
            :disabled="store.filters.offset + store.filters.limit >= store.total"
            @click="store.setPage(store.filters.offset + store.filters.limit)"
          >Next</button>
        </div>
      </div>
    </div>

    <!-- TTL Preview / Confirmation Dialog -->
    <div v-if="showTTLPreview" class="dialog-overlay" @click.self="cancelTTLPreview">
      <div class="ttl-dialog">
        <h3 class="ttl-dialog-title">
          <i class="pi pi-tag"></i> Confirm Tag Application
        </h3>
        <p class="ttl-dialog-subtitle">
          The following AWS tag will be applied to {{ ttlPreviewData?.total_count }} resource(s):
        </p>
        <div class="ttl-tag-preview">
          <span class="ttl-tag-key">bluearch:ttl</span>
          <span class="ttl-tag-arrow">=</span>
          <span class="ttl-tag-value">{{ ttlPreviewData?.resources?.[0]?.tag_value }}</span>
          <span class="ttl-tag-days">({{ ttlPreviewData?.ttl_days }} days)</span>
        </div>
        <div class="ttl-resource-list">
          <table class="ttl-table">
            <thead>
              <tr>
                <th>Resource ARN</th>
                <th>Service</th>
                <th>Region</th>
                <th>Current Expires</th>
                <th>New Expires</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in ttlPreviewData?.resources" :key="item.resource_id">
                <td class="ttl-arn">{{ item.resource_arn }}</td>
                <td>{{ item.service_name }}</td>
                <td>{{ item.region }}</td>
                <td>{{ item.current_expires_at ? fmt.formatDate(item.current_expires_at) : '--' }}</td>
                <td class="ttl-new-date">{{ fmt.formatDate(item.new_expires_at) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="ttl-dialog-actions">
          <button class="btn btn-secondary" @click="cancelTTLPreview">Cancel</button>
          <button class="btn btn-primary" :disabled="ttlApplying" @click="confirmTTL">
            <template v-if="ttlApplying">Applying...</template>
            <template v-else>Apply TTL Tags</template>
          </button>
        </div>
      </div>
    </div>

    <!-- Relationship Preview Modal -->
    <ResourceRelationshipPreview
      v-if="previewResource"
      :resource="previewResource"
      @close="previewResource = null"
      @detail="goToDetail"
    />

    <!-- Execute Delete Confirmation Dialog -->
    <div v-if="showDeleteConfirm" class="dialog-overlay" @click.self="cancelDeleteConfirm">
      <div class="ttl-dialog">
        <h3 class="ttl-dialog-title" style="color: #f87171;">
          <i class="pi pi-ban" style="color: #f87171;"></i> Permanently Delete AWS Resources
        </h3>
        <p class="ttl-dialog-subtitle">
          This will permanently delete {{ deleteTargetIds.length }} resource(s) from AWS. This cannot be undone.
          S3 buckets will be skipped (require manual deletion).
        </p>
        <div class="delete-confirm-field">
          <label class="delete-confirm-label">
            Type <strong>DELETE</strong> to confirm
            <input
              v-model="deleteConfirmText"
              type="text"
              class="filter-input"
              placeholder="Type DELETE"
              autocomplete="off"
            />
          </label>
        </div>
        <div class="ttl-dialog-actions">
          <button class="btn btn-secondary" @click="cancelDeleteConfirm">Cancel</button>
          <button
            class="btn btn-danger"
            :disabled="deleteApplying || deleteConfirmText !== 'DELETE'"
            @click="confirmExecuteDelete"
          >
            <template v-if="deleteApplying">Deleting...</template>
            <template v-else>Execute Delete</template>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useResourcesStore } from '@/stores/resources'
import { useJobsStore } from '@/stores/jobs'
import PermissionBanner from '@/components/PermissionBanner.vue'
import ResourceRelationshipPreview from '@/components/ResourceRelationshipPreview.vue'
import { useFormatters } from '@/composables/useFormatters'
import { api } from '@/api/client'
import type { ResourceResponse, TTLPreviewResponse, SetTTLRequest } from '@/types/api'
import { useToast } from '@/composables/useToast'

const store = useResourcesStore()
const jobsStore = useJobsStore()
const router = useRouter()
const route = useRoute()
const fmt = useFormatters()
const toast = useToast()

const selectedIds = ref<Set<string>>(new Set())

// Execute delete confirmation state
const showDeleteConfirm = ref(false)
const deleteConfirmText = ref('')
const deleteTargetIds = ref<string[]>([])
const deleteApplying = ref(false)

// TTL preview/confirmation state
const showTTLPreview = ref(false)
const ttlPreviewData = ref<TTLPreviewResponse | null>(null)
const ttlPendingRequest = ref<SetTTLRequest | null>(null)
const ttlApplying = ref(false)

// Relationship preview
const previewResource = ref<ResourceResponse | null>(null)

// Event Tracking banner & status
const etBannerDismissed = ref(false)
const etNotDeployed = ref(false)
const etActive = ref(false)
const etQueueCount = ref(0)
const showETBanner = computed(() => !etBannerDismissed.value && etNotDeployed.value)

// Region picker
const showRegionPicker = ref(false)
const availableRegions = ref<string[]>([
  'us-east-1', 'us-east-2', 'us-west-1', 'us-west-2',
  'eu-west-1', 'eu-west-2', 'eu-west-3', 'eu-central-1', 'eu-north-1',
  'ap-southeast-1', 'ap-southeast-2', 'ap-northeast-1', 'ap-northeast-2', 'ap-south-1',
  'sa-east-1', 'ca-central-1',
])
const defaultScanRegions = ['us-east-1', 'us-east-2', 'us-west-1', 'us-west-2']
const selectedScanRegions = ref<string[]>([...defaultScanRegions])
const scanButtonLabel = computed(() => `Scan ${selectedScanRegions.value.join(', ')}`)

function toggleScanRegion(region: string) {
  const idx = selectedScanRegions.value.indexOf(region)
  if (idx >= 0) {
    selectedScanRegions.value.splice(idx, 1)
  } else {
    selectedScanRegions.value.push(region)
  }
}

function toggleAllRegions() {
  if (selectedScanRegions.value.length === availableRegions.value.length) {
    selectedScanRegions.value = []
  } else {
    selectedScanRegions.value = [...availableRegions.value]
  }
}

// Scan status
const isScanRunning = computed(() => {
  const job = jobsStore.currentScanJob
  return !!(job && (job.status === 'running' || job.status === 'pending'))
})

const lastScanTime = computed(() => {
  // Find most recent completed scan job
  const completedScans = jobsStore.jobs
    .filter(j => j.job_type === 'scan' && j.status === 'completed' && j.completed_at)
    .sort((a, b) => new Date(b.completed_at!).getTime() - new Date(a.completed_at!).getTime())
  if (completedScans.length === 0) return null
  return timeAgo(completedScans[0].completed_at!)
})

function timeAgo(dateStr: string): string {
  const date = new Date(dateStr)
  const now = new Date()
  const diffMs = now.getTime() - date.getTime()
  const diffMin = Math.floor(diffMs / 60000)
  if (diffMin < 1) return 'just now'
  if (diffMin < 60) return `${diffMin}m ago`
  const diffHrs = Math.floor(diffMin / 60)
  if (diffHrs < 24) return `${diffHrs}h ago`
  const diffDays = Math.floor(diffHrs / 24)
  return `${diffDays}d ago`
}

async function startScan() {
  if (selectedScanRegions.value.length === 0) {
    toast.warning('No Regions', 'Select at least one region to scan')
    return
  }
  showRegionPicker.value = false
  try {
    await jobsStore.submitScan(undefined, selectedScanRegions.value)
    toast.success('Scan Started', `Scanning ${selectedScanRegions.value.length} region(s)`)
  } catch {
    // Error handled by store/API client
  }
}

async function stopScan() {
  try {
    await jobsStore.cancelScan()
    toast.info('Scan Stopped', 'Resource scan cancellation requested')
  } catch {
    // Error handled by store/API client
  }
}

// Close region picker on outside click
function onDocClick(e: MouseEvent) {
  const target = e.target as HTMLElement
  if (!target.closest('.scan-region-picker')) {
    showRegionPicker.value = false
  }
}

onUnmounted(() => document.removeEventListener('click', onDocClick))

// Reload resources when scan completes
watch(() => jobsStore.currentScanJob?.status, (status, oldStatus) => {
  if (oldStatus === 'running' && status === 'completed') {
    store.fetchResources()
    store.fetchStats()
  }
})

const serviceOptions = computed(() => {
  if (!store.stats) return []
  return Object.keys(store.stats.by_service).sort()
})

const regionOptions = computed(() => {
  if (!store.stats) return []
  return Object.keys(store.stats.by_region).sort()
})

const accountOptions = computed(() => {
  if (!store.stats) return []
  return Object.keys(store.stats.by_account).sort()
})

const resourceTypeOptions = computed(() => {
  if (!store.stats) return []
  return Object.keys(store.stats.by_resource_type).sort()
})

const allSelected = computed(() => {
  return store.resources.length > 0 && store.resources.every(r => selectedIds.value.has(r.id))
})

const someSelected = computed(() => {
  return store.resources.some(r => selectedIds.value.has(r.id))
})

function toggleSelectAll() {
  if (allSelected.value) {
    store.resources.forEach(r => selectedIds.value.delete(r.id))
  } else {
    store.resources.forEach(r => selectedIds.value.add(r.id))
  }
}

function toggleSelect(id: string) {
  if (selectedIds.value.has(id)) {
    selectedIds.value.delete(id)
  } else {
    selectedIds.value.add(id)
  }
}

function getStateBadgeClass(resource: ResourceResponse): string {
  if (resource.protected) return 'state-protected'
  if (resource.expires_at && new Date(resource.expires_at) < new Date()) return 'state-expired'
  return fmt.stateClass(resource.lifecycle_state)
}

function getStateLabel(resource: ResourceResponse): string {
  if (resource.protected) return 'protected'
  if (resource.expires_at && new Date(resource.expires_at) < new Date()) return 'expired'
  return resource.lifecycle_state || 'unknown'
}

function getExpiryText(expiresAt: string): string {
  const now = new Date()
  const expiry = new Date(expiresAt)
  const diffMs = expiry.getTime() - now.getTime()
  const diffDays = Math.round(diffMs / (1000 * 60 * 60 * 24))
  if (diffDays > 1) return `expires in ${diffDays} days`
  if (diffDays === 1) return 'expires in 1 day'
  if (diffDays === 0) return 'expires today'
  if (diffDays === -1) return 'expired 1 day ago'
  return `expired ${Math.abs(diffDays)} days ago`
}

function getExpiryClass(expiresAt: string): string {
  const now = new Date()
  const expiry = new Date(expiresAt)
  const diffMs = expiry.getTime() - now.getTime()
  const diffDays = Math.round(diffMs / (1000 * 60 * 60 * 24))
  if (diffDays < 0) return 'expiry-overdue'
  if (diffDays <= 3) return 'expiry-critical'
  if (diffDays <= 7) return 'expiry-warning'
  return 'expiry-ok'
}

function hasTagManagerTags(resource: ResourceResponse): boolean {
  return !!(resource.current_tags && resource.current_tags['bluearch:ttl'])
}

function toggleTaggedFilter() {
  store.filters.tagged = store.filters.tagged === 'true' ? '' : 'true'
  applyFilters()
}

function applyFilters() {
  store.filters.offset = 0
  selectedIds.value.clear()
  store.fetchResources()
}

function onLifecycleStateChange() {
  // When choosing "protected" virtual state, set the protected filter instead
  if (store.filters.lifecycle_state === 'protected') {
    store.filters.lifecycle_state = ''
    store.filters.protected = 'true'
  } else {
    store.filters.protected = ''
  }
  applyFilters()
}

function handleReset() {
  selectedIds.value.clear()
  store.resetFilters()
}

function onRowClick(resource: ResourceResponse) {
  previewResource.value = resource
}

function goToDetail(id: string) {
  previewResource.value = null
  router.push({ name: 'resource-detail', params: { id } })
}

async function setResourceTTL(resource: ResourceResponse, days: number) {
  const body: SetTTLRequest = { resource_ids: [resource.id], ttl_days: days }
  try {
    const preview = await api.previewSetTTL(body)
    ttlPreviewData.value = preview
    ttlPendingRequest.value = body
    showTTLPreview.value = true
  } catch {
    // Error toast shown by API client
  }
}

async function extendResource(resource: ResourceResponse, days: number) {
  try {
    const result = await api.extendTTL({ resource_ids: [resource.id], days })
    const detail = result.details || `Extended by ${days} days`
    if (detail.includes('FAILED')) {
      toast.warning('Extend (partial)', detail)
    } else {
      toast.success('TTL Extended', detail)
    }
    store.fetchResources()
  } catch {
    // Error toast shown by API client
  }
}

async function toggleProtect(resource: ResourceResponse) {
  try {
    const protect = !resource.protected
    await api.protectResources({ resource_ids: [resource.id], protect })
    toast.success(protect ? 'Resource Protected' : 'Protection Removed', resource.resource_id)
    store.fetchResources()
  } catch {
    // Error toast shown by API client
  }
}

// TTL confirmation flow
async function confirmTTL() {
  if (!ttlPendingRequest.value) return
  ttlApplying.value = true
  try {
    const count = ttlPendingRequest.value.resource_ids?.length ?? 0
    const result = await api.setTTL(ttlPendingRequest.value)
    const detail = result.details || `Set TTL on ${count} resource(s)`
    if (detail.includes('FAILED')) {
      toast.warning('TTL Set (partial)', detail)
    } else {
      toast.success('TTL Applied', detail)
    }
    // Clear bulk selection if it was a bulk operation
    if (count > 1) {
      selectedIds.value.clear()
    }
    store.fetchResources()
  } catch {
    // Error toast shown by API client
  } finally {
    showTTLPreview.value = false
    ttlPreviewData.value = null
    ttlPendingRequest.value = null
    ttlApplying.value = false
  }
}

function cancelTTLPreview() {
  showTTLPreview.value = false
  ttlPreviewData.value = null
  ttlPendingRequest.value = null
}

// Bulk actions
async function bulkSetTTL(days: number) {
  const body: SetTTLRequest = { resource_ids: Array.from(selectedIds.value), ttl_days: days }
  try {
    const preview = await api.previewSetTTL(body)
    ttlPreviewData.value = preview
    ttlPendingRequest.value = body
    showTTLPreview.value = true
  } catch {
    // Error toast shown by API client
  }
}

async function bulkExtend(days: number) {
  try {
    const result = await api.extendTTL({ resource_ids: Array.from(selectedIds.value), days })
    const detail = result.details || `Extended by ${days} days`
    if (detail.includes('FAILED')) {
      toast.warning('Extend (partial)', detail)
    } else {
      toast.success('TTL Extended', detail)
    }
    selectedIds.value.clear()
    store.fetchResources()
  } catch {
    // Error toast shown by API client
  }
}

async function bulkProtect(protect: boolean) {
  const count = selectedIds.value.size
  try {
    await api.protectResources({ resource_ids: Array.from(selectedIds.value), protect })
    toast.success(protect ? 'Resources Protected' : 'Protection Removed', `${count} resource(s) updated`)
    selectedIds.value.clear()
    store.fetchResources()
  } catch {
    // Error toast shown by API client
  }
}

async function removeResourceTags(resource: ResourceResponse) {
  try {
    const result = await api.removeTagManagerTags([resource.id])
    if (result.aws_failed > 0) {
      toast.warning('Tags Removed (partial)', result.details)
    } else {
      toast.success('Tags Removed', result.details)
    }
    store.fetchResources()
  } catch {
    // Error toast shown by API client
  }
}

async function bulkRemoveTags() {
  const ids = Array.from(selectedIds.value)
  if (!ids.length) return
  try {
    const result = await api.removeTagManagerTags(ids)
    if (result.aws_failed > 0) {
      toast.warning('Tags Removed (partial)', result.details)
    } else {
      toast.success('Tags Removed', result.details)
    }
    selectedIds.value.clear()
    store.fetchResources()
  } catch {
    // Error toast shown by API client
  }
}

// Execute delete
function openSingleDeleteConfirm(resource: ResourceResponse) {
  deleteTargetIds.value = [resource.id]
  deleteConfirmText.value = ''
  showDeleteConfirm.value = true
}

function openBulkDeleteConfirm() {
  deleteTargetIds.value = Array.from(selectedIds.value)
  deleteConfirmText.value = ''
  showDeleteConfirm.value = true
}

function cancelDeleteConfirm() {
  showDeleteConfirm.value = false
  deleteConfirmText.value = ''
  deleteTargetIds.value = []
}

async function confirmExecuteDelete() {
  if (deleteConfirmText.value !== 'DELETE') return
  deleteApplying.value = true
  try {
    const result = await api.reviewExecuteDelete({
      resource_ids: deleteTargetIds.value,
      confirmation: 'DELETE',
    })
    const detail = result.details || `Deleted ${result.affected_count} resource(s)`
    if (detail.includes('Failed')) {
      toast.warning('Delete (partial)', detail)
    } else {
      toast.success('Resources Deleted', detail)
    }
    selectedIds.value.clear()
    store.fetchResources()
  } catch {
    // Error toast shown by API client
  } finally {
    showDeleteConfirm.value = false
    deleteConfirmText.value = ''
    deleteTargetIds.value = []
    deleteApplying.value = false
  }
}

function applyQueryParams() {
  // Reset filters first so stale params from previous navigation are cleared
  store.filters.service = ''
  store.filters.region = ''
  store.filters.account_id = ''
  store.filters.lifecycle_state = ''
  store.filters.resource_type = ''
  store.filters.protected = ''
  store.filters.tagged = ''
  store.filters.search = ''
  store.filters.offset = 0

  const q = route.query
  if (q.service) store.filters.service = String(q.service)
  if (q.region) store.filters.region = String(q.region)
  if (q.lifecycle_state) store.filters.lifecycle_state = String(q.lifecycle_state)
  if (q.search) store.filters.search = String(q.search)
  if (q.account_id) store.filters.account_id = String(q.account_id)
  if (q.resource_type) store.filters.resource_type = String(q.resource_type)
  if (q.protected) store.filters.protected = String(q.protected) as '' | 'true' | 'false'
  if (q.tagged) store.filters.tagged = String(q.tagged) as '' | 'true' | 'false'

  selectedIds.value.clear()
  store.fetchResources()
}

onMounted(() => {
  document.addEventListener('click', onDocClick)
  applyQueryParams()
  store.fetchStats().then(() => {
    // Use actually scanned regions as defaults for region picker
    if (store.stats && Object.keys(store.stats.by_region).length > 0) {
      const scannedRegions = Object.keys(store.stats.by_region).sort()
      // Merge with the default list so user can also pick unscanned regions
      const merged = new Set([...availableRegions.value, ...scannedRegions])
      availableRegions.value = Array.from(merged).sort()
      selectedScanRegions.value = defaultScanRegions.filter((r) => availableRegions.value.includes(r))
    }
  })
  // Fetch jobs to show scan status
  jobsStore.fetchJobs()
  // Check event tracking status
  api.eventTrackingStatus().then(status => {
    etNotDeployed.value = status.total_queues === 0
    etActive.value = status.active_queues > 0
    etQueueCount.value = status.active_queues
  }).catch(() => {})
})

// Re-apply filters when navigating to this page with different query params
// (e.g. clicking smart links from Chat view)
watch(() => route.query, (newQuery, oldQuery) => {
  if (route.name !== 'resources') return
  // Only react if the query actually changed
  if (JSON.stringify(newQuery) !== JSON.stringify(oldQuery)) {
    applyQueryParams()
  }
})
</script>

<style scoped>
.resources-view {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

/* Scan Status Bar */
.scan-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.6rem 1rem;
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 10px;
  gap: 1rem;
  flex-wrap: wrap;
}

.scan-bar-left {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  flex: 1;
  min-width: 0;
}

.scan-bar-right {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  flex-shrink: 0;
}

.scan-btn {
  background: var(--gradient-brand-horizontal);
  color: white;
  border: none;
  padding: 0.4rem 0.85rem;
  border-radius: 6px;
  font-size: 0.82rem;
  cursor: pointer;
  font-weight: 500;
  display: flex;
  align-items: center;
  gap: 0.35rem;
  white-space: nowrap;
  transition: all 0.15s;
}

.scan-btn:hover:not(:disabled) {
  box-shadow: 0 0 14px rgba(32, 108, 245, 0.35);
}

.scan-btn:disabled {
  opacity: 0.8;
  cursor: default;
}

.scan-btn-running {
  background: rgba(32, 108, 245, 0.2);
  color: #5a9aff;
}

.stop-scan-btn {
  background: rgba(239, 68, 68, 0.14);
  color: #f87171;
  border: 1px solid rgba(239, 68, 68, 0.35);
  padding: 0.4rem 0.85rem;
  border-radius: 6px;
  font-size: 0.82rem;
  cursor: pointer;
  font-weight: 500;
  display: flex;
  align-items: center;
  gap: 0.35rem;
  white-space: nowrap;
}

.scan-region-picker {
  position: relative;
}

.scan-region-toggle {
  background: var(--surface-ground);
  border: 1px solid var(--surface-border);
  border-radius: 6px;
  padding: 0.35rem 0.65rem;
  font-size: 0.78rem;
  color: var(--text-color-secondary);
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 0.3rem;
  white-space: nowrap;
}

.scan-region-toggle:hover {
  border-color: var(--primary-color);
  color: var(--text-color);
}

.scan-region-toggle .pi-globe {
  font-size: 0.75rem;
}

.scan-region-toggle .pi-chevron-down,
.scan-region-toggle .pi-chevron-up {
  font-size: 0.55rem;
  opacity: 0.6;
}

.scan-region-dropdown {
  position: absolute;
  top: 100%;
  left: 0;
  margin-top: 4px;
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 8px;
  padding: 0.4rem 0;
  min-width: 180px;
  max-height: 280px;
  overflow-y: auto;
  z-index: 50;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3);
}

.scan-region-option {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.3rem 0.65rem;
  font-size: 0.78rem;
  color: var(--text-color-secondary);
  cursor: pointer;
  white-space: nowrap;
}

.scan-region-option:hover {
  background: rgba(32, 108, 245, 0.08);
  color: var(--text-color);
}

.scan-region-option input[type="checkbox"] {
  cursor: pointer;
}

.scan-region-divider {
  height: 1px;
  background: var(--surface-border);
  margin: 0.25rem 0;
}

.scan-progress-info {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex: 1;
  min-width: 0;
}

.scan-progress-bar {
  flex: 1;
  max-width: 200px;
  height: 4px;
  background: var(--surface-ground);
  border-radius: 2px;
  overflow: hidden;
}

.scan-progress-fill {
  height: 100%;
  background: var(--gradient-brand-horizontal);
  border-radius: 2px;
  transition: width 0.3s ease;
}

.scan-progress-text {
  font-size: 0.75rem;
  color: var(--text-color-secondary);
  white-space: nowrap;
}

.scan-status-item {
  display: flex;
  align-items: center;
  gap: 0.3rem;
  font-size: 0.78rem;
  color: var(--text-color-secondary);
  white-space: nowrap;
}

.scan-status-item i {
  font-size: 0.75rem;
}

.scan-status-ok {
  color: #4ade80;
}

.scan-status-dim {
  opacity: 0.5;
}

.scan-status-divider {
  width: 1px;
  height: 14px;
  background: var(--surface-border);
}

/* Event Tracking Warning Banner */
.et-warning-banner {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  padding: 0.6rem 1rem;
  background: rgba(234, 179, 8, 0.1);
  border: 1px solid rgba(234, 179, 8, 0.25);
  border-radius: 8px;
  font-size: 0.82rem;
  color: #facc15;
}

.et-warning-banner > .pi-bolt {
  font-size: 0.9rem;
  flex-shrink: 0;
}

.et-banner-link {
  margin-left: auto;
  color: #facc15;
  text-decoration: underline;
  font-weight: 500;
  white-space: nowrap;
}

.et-banner-link:hover {
  color: #fde68a;
}

.et-banner-dismiss {
  background: none;
  border: none;
  color: #facc15;
  cursor: pointer;
  padding: 0.2rem;
  opacity: 0.7;
  font-size: 0.75rem;
  flex-shrink: 0;
}

.et-banner-dismiss:hover {
  opacity: 1;
}

.bulk-bar {
  background: rgba(32, 108, 245, 0.12);
  border: 1px solid rgba(32, 108, 245, 0.25);
  border-radius: 10px;
  padding: 0.65rem 1rem;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  position: sticky;
  top: 0;
  z-index: 10;
}

.bulk-count {
  font-size: 0.85rem;
  font-weight: 600;
  color: #5a9aff;
  margin-right: 0.5rem;
}

.bulk-btn {
  background: var(--primary-color) !important;
  color: white !important;
  border: none !important;
}

.bulk-btn:hover { background: #1a5ad4 !important; }

.bulk-btn-purple {
  background: #7c3aed !important;
  color: white !important;
  border: none !important;
  padding: 0.35rem 0.75rem;
  font-size: 0.8rem;
  border-radius: 6px;
  cursor: pointer;
  font-weight: 500;
}

.bulk-btn-purple:hover { background: #6d28d9 !important; }

.bulk-btn-outline {
  background: var(--surface-card) !important;
  color: var(--text-color) !important;
  border: 1px solid var(--surface-border) !important;
  padding: 0.35rem 0.75rem;
  font-size: 0.8rem;
  border-radius: 6px;
  cursor: pointer;
  font-weight: 500;
}

.bulk-btn-danger {
  background: rgba(239, 68, 68, 0.15) !important;
  color: #f87171 !important;
  border: 1px solid rgba(239, 68, 68, 0.3) !important;
  padding: 0.35rem 0.75rem;
  font-size: 0.8rem;
  border-radius: 6px;
  cursor: pointer;
  font-weight: 500;
}

.bulk-btn-danger:hover { background: rgba(239, 68, 68, 0.25) !important; }

.bulk-btn-delete {
  background: #ef4444 !important;
  color: white !important;
  border: none !important;
  padding: 0.35rem 0.75rem;
  font-size: 0.8rem;
  border-radius: 6px;
  cursor: pointer;
  font-weight: 500;
}

.bulk-btn-delete:hover { background: #dc2626 !important; }

.bulk-btn-outline:hover { background: var(--surface-card-hover) !important; }

.filters-bar {
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 10px;
  padding: 1rem;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  flex-wrap: wrap;
}

.filter-group {
  display: flex;
  gap: 0.5rem;
  flex-wrap: wrap;
  flex: 1;
}

.filter-input {
  padding: 0.5rem 0.75rem;
  border: 1px solid var(--surface-border);
  border-radius: 6px;
  font-size: 0.85rem;
  background: var(--surface-input);
  color: var(--text-color);
  outline: none;
}

.filter-input:focus {
  border-color: var(--primary-color);
}

.search-input {
  min-width: 200px;
}

.filter-actions {
  display: flex;
  gap: 0.5rem;
  align-items: center;
}

.tagged-filter {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.45rem 0.75rem;
  border: 1px solid var(--surface-border);
  border-radius: 6px;
  font-size: 0.82rem;
  font-weight: 500;
  cursor: pointer;
  color: var(--text-color-secondary);
  background: var(--surface-ground);
  transition: all 0.15s;
  user-select: none;
  white-space: nowrap;
}

.tagged-filter input { display: none; }

.tagged-filter:hover {
  border-color: var(--primary-color);
  color: var(--text-color);
}

.tagged-filter.active {
  background: rgba(32, 108, 245, 0.12);
  border-color: rgba(32, 108, 245, 0.4);
  color: #5a9aff;
}

.btn {
  padding: 0.5rem 1rem;
  border: none;
  border-radius: 6px;
  font-size: 0.85rem;
  cursor: pointer;
  font-weight: 500;
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

.btn-sm {
  padding: 0.35rem 0.75rem;
  font-size: 0.8rem;
  background: var(--surface-ground);
  border: 1px solid var(--surface-border);
  color: var(--text-color);
}

.btn-sm:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.table-card {
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 10px;
  overflow: hidden;
}

.data-table {
  width: 100%;
  border-collapse: collapse;
}

.data-table th {
  text-align: left;
  padding: 0.75rem 1rem;
  font-size: 0.78rem;
  font-weight: 600;
  text-transform: uppercase;
  color: var(--text-color-secondary);
  background: var(--surface-ground);
  border-bottom: 1px solid var(--surface-border);
}

.data-table td {
  padding: 0.7rem 1rem;
  font-size: 0.85rem;
  border-bottom: 1px solid var(--surface-border);
}

.checkbox-col {
  width: 40px;
  text-align: center;
}

.select-all-col {
  width: auto;
  min-width: 55px;
}

.select-all-label {
  display: flex;
  align-items: center;
  gap: 4px;
  cursor: pointer;
  white-space: nowrap;
}

.select-all-text {
  font-size: 0.75rem;
  color: var(--text-secondary);
  font-weight: 500;
}

.checkbox-col input[type="checkbox"] {
  cursor: pointer;
}

.table-row {
  cursor: pointer;
  transition: background 0.1s;
}

.table-row:hover {
  background: rgba(32, 108, 245, 0.05);
}

.row-selected {
  background: rgba(32, 108, 245, 0.12);
}

.row-selected:hover {
  background: rgba(32, 108, 245, 0.15);
}

.service-badge {
  background: rgba(32, 108, 245, 0.15);
  color: #5a9aff;
  padding: 0.2rem 0.5rem;
  border-radius: 4px;
  font-size: 0.78rem;
  font-weight: 500;
}

.resource-id {
  font-family: var(--font-mono), monospace;
  font-size: 0.8rem;
  color: var(--text-color-secondary);
}

.account-id {
  font-family: var(--font-mono), monospace;
  font-size: 0.8rem;
}

.state-badge {
  padding: 0.2rem 0.5rem;
  border-radius: 4px;
  font-size: 0.78rem;
  font-weight: 500;
  background: rgba(255, 255, 255, 0.03);
  color: var(--text-color-secondary);
}

.state-active { background: rgba(34, 197, 94, 0.15); color: #4ade80; }
.state-warned { background: rgba(234, 179, 8, 0.15); color: #facc15; }
.state-danger { background: rgba(239, 68, 68, 0.15); color: #f87171; }
.state-expired { background: rgba(239, 68, 68, 0.15); color: #f87171; }
.state-protected { background: rgba(124, 58, 237, 0.15); color: #a78bfa; }

.actions-cell {
  display: flex;
  gap: 0.35rem;
  align-items: center;
}

.btn-action {
  background: var(--surface-ground);
  border: 1px solid var(--surface-border);
  border-radius: 4px;
  padding: 0.2rem 0.45rem;
  cursor: pointer;
  font-size: 0.72rem;
  font-weight: 600;
  color: var(--primary-color);
  transition: all 0.15s;
}

.btn-action:hover { background: rgba(32, 108, 245, 0.12); }
.btn-action-purple { color: #a78bfa; }
.btn-action-purple:hover { background: rgba(124, 58, 237, 0.15); }
.btn-action-danger { color: #f87171; }
.btn-action-danger:hover { background: rgba(239, 68, 68, 0.15); }

.table-loading,
.table-error,
.table-empty {
  padding: 3rem;
  text-align: center;
  color: var(--text-color-secondary);
  font-size: 0.9rem;
}

.table-error { color: #f87171; }

.pagination {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.75rem 1rem;
  border-top: 1px solid var(--surface-border);
}

.pagination-info {
  font-size: 0.8rem;
  color: var(--text-color-secondary);
}

.pagination-buttons {
  display: flex;
  gap: 0.5rem;
}

/* Lifecycle State Legend */
.legend-bar {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 0.5rem 1rem;
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 10px;
  flex-wrap: wrap;
}

.legend-label {
  font-size: 0.78rem;
  font-weight: 600;
  color: var(--text-color-secondary);
  display: flex;
  align-items: center;
  gap: 0.35rem;
  flex-shrink: 0;
}

.legend-label i {
  font-size: 0.82rem;
}

.legend-item {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  font-size: 0.75rem;
  color: var(--text-color-secondary);
  white-space: nowrap;
}

.legend-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.dot-active { background: #4ade80; }
.dot-warned { background: #facc15; }
.dot-marked { background: #f87171; }
.dot-protected { background: #a78bfa; }
.dot-expired { background: #f87171; }
.dot-unknown { background: #6b7280; }

/* Expiry relative text */
.expiry-relative {
  display: inline-block;
  margin-left: 0.4rem;
  font-size: 0.7rem;
  font-weight: 500;
}

.expiry-ok { color: #4ade80; }
.expiry-warning { color: #facc15; }
.expiry-critical { color: #f87171; }
.expiry-overdue { color: #f87171; }

/* TTL Confirmation Dialog */
.dialog-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.6);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.ttl-dialog {
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 12px;
  padding: 1.5rem;
  width: 720px;
  max-width: 92vw;
  max-height: 80vh;
  display: flex;
  flex-direction: column;
  box-shadow: 0 8px 40px rgba(0, 0, 0, 0.5);
}

.ttl-dialog-title {
  font-size: 1.1rem;
  font-weight: 600;
  color: var(--text-color);
  margin-bottom: 0.5rem;
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.ttl-dialog-title i {
  color: var(--primary-color);
}

.ttl-dialog-subtitle {
  font-size: 0.85rem;
  color: var(--text-color-secondary);
  margin-bottom: 1rem;
}

.ttl-tag-preview {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.65rem 1rem;
  background: rgba(32, 108, 245, 0.08);
  border: 1px solid rgba(32, 108, 245, 0.2);
  border-radius: 8px;
  margin-bottom: 1rem;
  flex-wrap: wrap;
}

.ttl-tag-key {
  font-family: var(--font-mono), monospace;
  font-size: 0.85rem;
  font-weight: 600;
  color: #5a9aff;
}

.ttl-tag-arrow {
  color: var(--text-color-secondary);
  font-weight: 500;
}

.ttl-tag-value {
  font-family: var(--font-mono), monospace;
  font-size: 0.85rem;
  font-weight: 600;
  color: #4ade80;
}

.ttl-tag-days {
  font-size: 0.78rem;
  color: var(--text-color-secondary);
}

.ttl-resource-list {
  overflow: auto;
  max-height: 320px;
  border: 1px solid var(--surface-border);
  border-radius: 8px;
  margin-bottom: 1rem;
}

.ttl-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.8rem;
}

.ttl-table th {
  text-align: left;
  padding: 0.55rem 0.75rem;
  font-size: 0.72rem;
  font-weight: 600;
  text-transform: uppercase;
  color: var(--text-color-secondary);
  background: var(--surface-ground);
  border-bottom: 1px solid var(--surface-border);
  position: sticky;
  top: 0;
}

.ttl-table td {
  padding: 0.5rem 0.75rem;
  border-bottom: 1px solid var(--surface-border);
  color: var(--text-color-secondary);
}

.ttl-arn {
  font-family: var(--font-mono), monospace;
  font-size: 0.72rem;
  word-break: break-all;
  max-width: 280px;
}

.ttl-new-date {
  color: #4ade80 !important;
  font-weight: 500;
}

.ttl-dialog-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.75rem;
}

.btn-danger {
  background: #ef4444;
  color: white;
}

.btn-danger:hover:not(:disabled) {
  background: #dc2626;
}

.btn-danger:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.delete-confirm-field {
  margin-bottom: 1rem;
}

.delete-confirm-label {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  font-size: 0.85rem;
  color: var(--text-color-secondary);
}

.delete-confirm-label input {
  max-width: 200px;
}
</style>
