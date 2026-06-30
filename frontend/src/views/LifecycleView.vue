<template>
  <div class="lifecycle-view">
    <ProBadge feature="lifecycle:policies" label="Lifecycle Policies" />
    <!-- Actions Bar -->
    <div class="actions-bar">
      <button
        class="btn btn-primary"
        :disabled="scanInProgress || (jobsStore.currentScanJob?.status === 'running')"
        @click="triggerScan"
      >
        <i :class="scanInProgress ? 'pi pi-spin pi-spinner' : 'pi pi-sync'"></i>
        {{ scanInProgress ? 'Scanning...' : 'Scan Resources' }}
      </button>
      <JobTracker v-if="jobsStore.currentScanJob" :job="jobsStore.currentScanJob" />
    </div>

    <!-- Workflow Guide Banner -->
    <div v-if="!guideHidden" class="workflow-guide">
      <div class="guide-header">
        <div class="guide-title">
          <i class="pi pi-info-circle"></i>
          <span>How Lifecycle Management Works</span>
        </div>
        <div class="guide-actions">
          <button class="guide-toggle" @click="guideCollapsed = !guideCollapsed">
            <i :class="guideCollapsed ? 'pi pi-chevron-down' : 'pi pi-chevron-up'"></i>
          </button>
          <button class="guide-dismiss" title="Dismiss guide" @click="dismissGuide">
            <i class="pi pi-times"></i>
          </button>
        </div>
      </div>
      <div v-if="!guideCollapsed" class="guide-stepper">
        <div class="step">
          <div class="step-circle">1</div>
          <div class="step-connector"></div>
          <div class="step-content">
            <div class="step-label">Create Policies</div>
            <div class="step-desc">Define lifecycle policies with tag conditions, TTL rules, and resource types</div>
          </div>
        </div>
        <div class="step">
          <div class="step-circle">2</div>
          <div class="step-connector"></div>
          <div class="step-content">
            <div class="step-label">Scan Resources</div>
            <div class="step-desc">Discover AWS resources and match them against policies</div>
          </div>
        </div>
        <div class="step">
          <div class="step-circle">3</div>
          <div class="step-connector"></div>
          <div class="step-content">
            <div class="step-label">Review & Set TTL</div>
            <div class="step-desc">Review matched resources, set expiration dates, protect critical resources</div>
          </div>
        </div>
        <div class="step">
          <div class="step-circle">4</div>
          <div class="step-connector"></div>
          <div class="step-content">
            <div class="step-label">Monitor Warnings</div>
            <div class="step-desc">Resources approaching expiry get warned (7, 3, 1 days before)</div>
          </div>
        </div>
        <div class="step">
          <div class="step-circle">5</div>
          <div class="step-content">
            <div class="step-label">Clean Up</div>
            <div class="step-desc">Expired resources are marked for deletion after grace period</div>
          </div>
        </div>
      </div>
    </div>

    <!-- Policy Save Result Banner -->
    <div v-if="saveResultBanner" class="save-result-banner">
      <i class="pi pi-check-circle"></i>
      <span>
        Matched <strong>{{ saveResultBanner.matched_count }}</strong> resource{{ saveResultBanner.matched_count !== 1 ? 's' : '' }}
        <template v-if="saveResultBanner.ttl_applied_count > 0">
          -- applied TTL to <strong>{{ saveResultBanner.ttl_applied_count }}</strong>
        </template>
      </span>
      <button class="banner-dismiss" @click="saveResultBanner = null">
        <i class="pi pi-times"></i>
      </button>
    </div>

    <!-- Policies Section (FIRST) -->
    <div class="section-card">
      <div class="section-header">
        <h2 class="section-title">Lifecycle Policies</h2>
        <div class="section-controls">
          <span class="section-count">{{ lifecycleStore.policiesTotal }} policies</span>
          <button class="btn btn-primary btn-sm" @click="showPolicyForm = true">
            <i class="pi pi-plus"></i> New Policy
          </button>
        </div>
      </div>
      <div v-if="!lifecycleStore.policies.length" class="section-empty">
        No lifecycle policies configured
      </div>
      <table v-else class="data-table">
        <thead>
          <tr>
            <th></th>
            <th>Name</th>
            <th>TTL (days)</th>
            <th>Warning (days)</th>
            <th>Resource Types</th>
            <th>Resources</th>
            <th>Status</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          <template v-for="policy in lifecycleStore.policies" :key="policy.id">
            <tr :class="{ 'row-expanded': expandedPolicyId === policy.id }">
              <td class="expand-cell">
                <button
                  class="btn-expand"
                  :title="expandedPolicyId === policy.id ? 'Collapse' : 'Show matched resources'"
                  @click="togglePolicyExpand(policy)"
                >
                  <i :class="expandedPolicyId === policy.id ? 'pi pi-chevron-down' : 'pi pi-chevron-right'"></i>
                </button>
              </td>
              <td>
                <div class="policy-name">{{ policy.name }}</div>
                <div v-if="policy.description" class="policy-desc">{{ policy.description }}</div>
              </td>
              <td>{{ policy.default_ttl_days ?? '-' }}</td>
              <td>{{ policy.warning_days ?? '-' }}</td>
              <td>
                <div class="type-chips">
                  <span v-for="t in (policy.resource_types || [])" :key="t" class="type-chip">{{ t }}</span>
                  <span v-if="!policy.resource_types?.length">All</span>
                </div>
              </td>
              <td>
                <span class="resource-count clickable" @click="togglePolicyExpand(policy)">{{ policy.resource_count ?? 0 }}</span>
              </td>
              <td>
                <span class="status-badge" :class="policy.enabled ? 'enabled' : 'disabled'">
                  {{ policy.enabled ? 'Enabled' : 'Disabled' }}
                </span>
              </td>
              <td class="actions-cell" @click.stop>
                <button class="btn-icon" title="Edit" @click="editPolicyItem(policy)">
                  <i class="pi pi-pencil"></i>
                </button>
                <button class="btn-icon btn-icon-danger" title="Delete" @click="confirmDeletePolicy(policy)">
                  <i class="pi pi-trash"></i>
                </button>
              </td>
            </tr>
            <!-- Policy Drill-Down: matched resources -->
            <tr v-if="expandedPolicyId === policy.id" class="policy-drilldown-row">
              <td :colspan="8">
                <div class="policy-drilldown">
                  <div v-if="policyResourcesLoading" class="drilldown-loading">
                    <i class="pi pi-spin pi-spinner"></i> Loading matched resources...
                  </div>
                  <div v-else-if="lifecycleStore.policyResources.length === 0" class="drilldown-empty">
                    No resources matched by this policy
                  </div>
                  <table v-else class="drilldown-table">
                    <thead>
                      <tr>
                        <th>Service</th>
                        <th>Resource ARN</th>
                        <th>Type</th>
                        <th>Region</th>
                        <th>TTL</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr v-for="res in lifecycleStore.policyResources" :key="res.id">
                        <td><span class="service-badge">{{ res.service_name }}</span></td>
                        <td class="arn-cell"><ResourceLink :id="res.id" :arn="res.resource_arn" /></td>
                        <td class="text-muted">{{ res.resource_type }}</td>
                        <td>{{ res.region }}</td>
                        <td>
                          <span v-if="res.has_ttl" class="ttl-set-badge">Set</span>
                          <span v-else class="text-muted">--</span>
                        </td>
                      </tr>
                    </tbody>
                  </table>
                  <div v-if="lifecycleStore.policyResourcesTotal > lifecycleStore.policyResources.length" class="drilldown-footer">
                    {{ lifecycleStore.policyResourcesTotal }} total matched resources
                  </div>
                </div>
              </td>
            </tr>
          </template>
        </tbody>
      </table>
    </div>

    <!-- Unified Resource Explorer -->
    <div class="section-card">
      <div class="section-header">
        <h2 class="section-title">Resource Explorer</h2>
        <div class="section-controls">
          <span class="section-count">{{ lifecycleStore.explorerTotal }} resources</span>
        </div>
      </div>

      <!-- State Filter Chips -->
      <div class="state-chips-bar">
        <button
          v-for="chip in stateChips"
          :key="chip.value"
          class="state-chip"
          :class="{ active: explorerState === chip.value }"
          @click="setExplorerState(chip.value)"
        >
          <span class="chip-dot" :style="{ background: chip.color }"></span>
          {{ chip.label }}
        </button>
      </div>

      <!-- Dropdown Filters Row -->
      <div class="explorer-filters">
        <label class="filter-label">
          Service
          <select v-model="explorerService" class="filter-input">
            <option value="">All Services</option>
            <option v-for="(count, svc) in (resourcesStore.stats?.by_service || {})" :key="svc" :value="svc">
              {{ svc }} ({{ count }})
            </option>
          </select>
        </label>
        <label class="filter-label">
          Account
          <select v-model="explorerAccount" class="filter-input">
            <option value="">All Accounts</option>
            <option v-for="(count, acct) in (resourcesStore.stats?.by_account || {})" :key="acct" :value="acct">
              {{ acct }} ({{ count }})
            </option>
          </select>
        </label>
        <label v-if="explorerState === 'expiring' || explorerState === ''" class="filter-label">
          Days
          <input
            v-model.number="explorerDays"
            type="number"
            class="filter-input filter-input-narrow"
            min="1"
          />
        </label>
        <button class="btn btn-primary btn-sm" @click="loadExplorer">
          <i class="pi pi-search"></i> Load
        </button>
      </div>

      <!-- Action message -->
      <div v-if="actionMessage" class="action-message" :class="actionMessageType">
        <i :class="actionMessageType === 'success' ? 'pi pi-check-circle' : 'pi pi-times-circle'"></i>
        {{ actionMessage }}
      </div>

      <!-- Bulk Action Bar -->
      <div v-if="selectedIds.size > 0" class="bulk-action-bar">
        <span class="bulk-count">{{ selectedIds.size }} selected</span>
        <div class="bulk-buttons">
          <button
            class="btn btn-sm btn-outline"
            :class="{ active: showExtendPanel }"
            @click="togglePanel('extend')"
          >
            <i class="pi pi-clock"></i> Extend
          </button>
          <button
            class="btn btn-sm btn-outline btn-outline-purple"
            :class="{ active: showProtectPanel }"
            @click="togglePanel('protect')"
          >
            <i class="pi pi-shield"></i> Protect
          </button>
          <button
            class="btn btn-sm btn-outline btn-outline-danger"
            :class="{ active: showMarkDeletePanel }"
            @click="togglePanel('markDelete')"
          >
            <i class="pi pi-trash"></i> Mark Delete
          </button>
          <button
            v-if="explorerState === 'marked_for_deletion'"
            class="btn btn-sm btn-danger"
            :class="{ active: showExecuteDeletePanel }"
            @click="togglePanel('executeDelete')"
          >
            <i class="pi pi-ban"></i> Execute Delete
          </button>
        </div>
      </div>

      <!-- Extend Panel -->
      <div v-if="showExtendPanel" class="action-panel">
        <div class="action-panel-header">Extend TTL for {{ selectedIds.size }} resource(s)</div>
        <div class="action-panel-fields">
          <label class="filter-label">
            Days
            <input v-model.number="extendDays" type="number" class="filter-input filter-input-narrow" min="1" />
          </label>
          <label class="filter-label">
            Reason (optional)
            <input v-model="actionReason" type="text" class="filter-input" placeholder="Why extend?" />
          </label>
        </div>
        <div class="action-panel-actions">
          <button class="btn btn-sm btn-secondary" @click="showExtendPanel = false">Cancel</button>
          <button class="btn btn-sm btn-primary" :disabled="actionLoading" @click="handleExtend">
            <i v-if="actionLoading" class="pi pi-spin pi-spinner"></i>
            Extend
          </button>
        </div>
      </div>

      <!-- Protect Panel -->
      <div v-if="showProtectPanel" class="action-panel">
        <div class="action-panel-header">Protect {{ selectedIds.size }} resource(s)</div>
        <div class="action-panel-fields">
          <label class="filter-label">
            Reason (optional)
            <input v-model="actionReason" type="text" class="filter-input" placeholder="Why protect?" />
          </label>
        </div>
        <div class="action-panel-actions">
          <button class="btn btn-sm btn-secondary" @click="showProtectPanel = false">Cancel</button>
          <button class="btn btn-sm btn-primary" :disabled="actionLoading" @click="handleProtect">
            <i v-if="actionLoading" class="pi pi-spin pi-spinner"></i>
            Protect
          </button>
        </div>
      </div>

      <!-- Mark Delete Panel -->
      <div v-if="showMarkDeletePanel" class="action-panel">
        <div class="action-panel-header action-panel-header-danger">
          Mark {{ selectedIds.size }} resource(s) for deletion
        </div>
        <p class="action-panel-warning">
          These resources will be scheduled for cleanup. This action can be reversed by extending or protecting the resources.
        </p>
        <div class="action-panel-fields">
          <label class="filter-label">
            Reason (optional)
            <input v-model="actionReason" type="text" class="filter-input" placeholder="Why mark for deletion?" />
          </label>
        </div>
        <div class="action-panel-actions">
          <button class="btn btn-sm btn-secondary" @click="showMarkDeletePanel = false">Cancel</button>
          <button class="btn btn-sm btn-danger" :disabled="actionLoading" @click="handleMarkDelete">
            <i v-if="actionLoading" class="pi pi-spin pi-spinner"></i>
            Mark Delete
          </button>
        </div>
      </div>

      <!-- Execute Delete Panel -->
      <div v-if="showExecuteDeletePanel" class="action-panel">
        <div class="action-panel-header action-panel-header-danger">
          Permanently delete {{ selectedIds.size }} resource(s) from AWS
        </div>
        <p class="action-panel-warning">
          This will permanently delete the selected AWS resources. This cannot be undone.
          S3 buckets will be skipped (require manual deletion).
        </p>
        <div class="action-panel-fields">
          <label class="filter-label">
            Type DELETE to confirm
            <input v-model="deleteConfirmText" type="text" class="filter-input"
                   placeholder="Type DELETE" autocomplete="off" />
          </label>
        </div>
        <div class="action-panel-actions">
          <button class="btn btn-sm btn-secondary" @click="showExecuteDeletePanel = false">Cancel</button>
          <button class="btn btn-sm btn-danger"
                  :disabled="actionLoading || deleteConfirmText !== 'DELETE'"
                  @click="handleExecuteDelete">
            <i v-if="actionLoading" class="pi pi-spin pi-spinner"></i>
            Execute Delete
          </button>
        </div>
      </div>

      <div v-if="!lifecycleStore.explorerResources.length" class="section-empty">
        No resources found
      </div>
      <table v-else class="data-table">
        <thead>
          <tr>
            <th class="checkbox-col">
              <input
                type="checkbox"
                :checked="allExplorerSelected"
                :indeterminate="someExplorerSelected && !allExplorerSelected"
                @change="toggleSelectAll"
              />
            </th>
            <th>Service</th>
            <th>Resource ARN</th>
            <th>Region</th>
            <th>Account</th>
            <th>State</th>
            <th>Policy</th>
            <th>Expires</th>
            <th>Time Left</th>
            <th>Tags</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="res in lifecycleStore.explorerResources"
            :key="res.id"
            :class="{ 'row-selected': selectedIds.has(res.id) }"
          >
            <td class="checkbox-col" @click.stop>
              <input
                type="checkbox"
                :checked="selectedIds.has(res.id)"
                @change="toggleSelect(res.id)"
              />
            </td>
            <td>
              <span class="service-badge">{{ res.service_name }}</span>
            </td>
            <td class="arn-cell"><ResourceLink :id="res.id" :arn="res.resource_arn" /></td>
            <td>{{ res.region }}</td>
            <td class="account-cell">{{ res.account_id }}</td>
            <td>
              <span class="state-badge" :class="fmt.stateClass(res.lifecycle_state)">
                {{ res.lifecycle_state || 'unknown' }}
              </span>
            </td>
            <td>
              <span v-if="res.policy_name" class="policy-pill">{{ res.policy_name }}</span>
              <span v-else class="text-muted">--</span>
            </td>
            <td>{{ fmt.formatDate(res.expires_at) }}</td>
            <td>
              <span class="days-badge" :class="daysDisplayClass(res)">
                {{ daysDisplayText(res) }}
              </span>
            </td>
            <td>
              <div class="tags-summary">
                <span
                  v-for="(tag, idx) in visibleTags(res.current_tags)"
                  :key="idx"
                  class="tag-chip"
                >
                  {{ tag }}
                </span>
                <span v-if="extraTagCount(res.current_tags) > 0" class="tag-chip tag-more">
                  +{{ extraTagCount(res.current_tags) }} more
                </span>
                <span v-if="!res.current_tags || Object.keys(res.current_tags).length === 0" class="text-muted">
                  --
                </span>
              </div>
            </td>
            <td class="actions-cell" @click.stop>
              <button
                class="btn-action"
                title="Blast Radius"
                @click.stop="blastRadiusArn = res.resource_arn"
              >
                <i class="pi pi-bolt"></i>
              </button>
              <button class="btn-action" title="Extend 7 days" @click="handleRowExtend(res, 7)">+7d</button>
              <button class="btn-action" title="Extend 30 days" @click="handleRowExtend(res, 30)">+30d</button>
              <button class="btn-action btn-action-purple" title="Protect" @click="handleRowProtect(res)">
                <i class="pi pi-shield"></i>
              </button>
              <button
                v-if="res.lifecycle_state !== 'marked_for_deletion'"
                class="btn-action btn-action-danger"
                title="Mark for deletion"
                @click="handleRowMarkDelete(res)"
              >
                <i class="pi pi-trash"></i>
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Lifecycle Audit Log Section -->
    <div class="section-card">
      <div class="section-header">
        <h2 class="section-title">Lifecycle Audit Log</h2>
        <div class="section-controls">
          <span class="section-count">{{ lifecycleStore.auditLogTotal }} entries</span>
          <button class="btn btn-sm btn-outline" @click="lifecycleStore.fetchAuditLog()">
            <i class="pi pi-refresh"></i> Refresh
          </button>
        </div>
      </div>
      <div v-if="!lifecycleStore.auditLog.length" class="section-empty">
        No audit log entries
      </div>
      <table v-else class="data-table audit-table">
        <thead>
          <tr>
            <th>Timestamp</th>
            <th>Resource ARN</th>
            <th>Operation</th>
            <th>State Transition</th>
            <th>Success</th>
            <th>Executed By</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="entry in visibleAuditLog" :key="entry.id">
            <td class="timestamp-cell">{{ fmt.formatDateTime(entry.executed_at) }}</td>
            <td class="arn-cell"><ResourceLink :arn="entry.resource_arn" /></td>
            <td>
              <span class="operation-badge">{{ entry.operation }}</span>
            </td>
            <td>
              <span v-if="entry.old_state || entry.new_state" class="state-transition">
                <span class="state-badge" :class="fmt.stateClass(entry.old_state)">
                  {{ entry.old_state || '?' }}
                </span>
                <i class="pi pi-arrow-right state-arrow"></i>
                <span class="state-badge" :class="fmt.stateClass(entry.new_state)">
                  {{ entry.new_state || '?' }}
                </span>
              </span>
              <span v-else class="text-muted">--</span>
            </td>
            <td class="success-cell">
              <i v-if="entry.success" class="pi pi-check-circle success-icon"></i>
              <i v-else class="pi pi-times-circle error-icon" :title="entry.error_message"></i>
            </td>
            <td>{{ entry.executed_by || '--' }}</td>
          </tr>
        </tbody>
      </table>
      <div v-if="hasMoreAuditEntries" class="audit-log-footer">
        <button class="btn btn-sm btn-outline" @click="auditLogShowAll = !auditLogShowAll">
          <i :class="auditLogShowAll ? 'pi pi-chevron-up' : 'pi pi-chevron-down'"></i>
          {{ auditLogShowAll ? 'Show less' : `Show all ${lifecycleStore.auditLogTotal} entries` }}
        </button>
      </div>
    </div>

    <!-- Dialogs -->
    <PolicyFormDialog
      :visible="showPolicyForm"
      :edit-policy="editingPolicy"
      @submit="handlePolicySubmit"
      @cancel="closePolicyForm"
    />
    <ConfirmDialog
      :visible="showDeleteConfirm"
      title="Delete Policy"
      :message="`Are you sure you want to delete policy '${deletingPolicy?.name}'?`"
      confirm-label="Delete"
      :destructive="true"
      @confirm="handleDeletePolicy"
      @cancel="showDeleteConfirm = false"
    />
    <BlastRadiusPanel
      v-if="blastRadiusArn"
      :arn="blastRadiusArn"
      @close="blastRadiusArn = null"
      @focus="() => blastRadiusArn = null"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useLifecycleStore } from '@/stores/lifecycle'
import { useJobsStore } from '@/stores/jobs'
import { useResourcesStore } from '@/stores/resources'
import { useFormatters } from '@/composables/useFormatters'
import type { PolicyResponse, PolicyCreateRequest, PolicySaveResult, ReviewResourceResponse } from '@/types/api'
import ProBadge from '@/components/ProBadge.vue'
import JobTracker from '@/components/JobTracker.vue'
import PolicyFormDialog from '@/components/PolicyFormDialog.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import ResourceLink from '@/components/ResourceLink.vue'
import BlastRadiusPanel from '@/components/BlastRadiusPanel.vue'

const lifecycleStore = useLifecycleStore()
const jobsStore = useJobsStore()
const resourcesStore = useResourcesStore()
const fmt = useFormatters()
const scanInProgress = ref(false)
const blastRadiusArn = ref<string | null>(null)

// Workflow guide state
const guideHidden = ref(localStorage.getItem('lifecycle-guide-hidden') === 'true')
const guideCollapsed = ref(false)

function dismissGuide() {
  guideHidden.value = true
  localStorage.setItem('lifecycle-guide-hidden', 'true')
}

// Save result banner
const saveResultBanner = ref<{ matched_count: number; ttl_applied_count: number } | null>(null)

// Policy drill-down
const expandedPolicyId = ref<string | null>(null)
const policyResourcesLoading = ref(false)

async function togglePolicyExpand(policy: PolicyResponse) {
  if (expandedPolicyId.value === policy.id) {
    expandedPolicyId.value = null
    return
  }
  expandedPolicyId.value = policy.id
  policyResourcesLoading.value = true
  try {
    await lifecycleStore.fetchPolicyResources(policy.id)
  } finally {
    policyResourcesLoading.value = false
  }
}

// --- Unified Explorer State ---
const explorerState = ref('')
const explorerService = ref('')
const explorerAccount = ref('')
const explorerDays = ref(7)
const selectedIds = ref<Set<string>>(new Set())
const showExtendPanel = ref(false)
const showProtectPanel = ref(false)
const showMarkDeletePanel = ref(false)
const showExecuteDeletePanel = ref(false)
const deleteConfirmText = ref('')
const extendDays = ref(30)
const actionReason = ref('')
const actionLoading = ref(false)
const actionMessage = ref('')
const actionMessageType = ref<'success' | 'error'>('success')

const MAX_VISIBLE_TAGS = 3

const stateChips = [
  { value: '', label: 'All', color: '#94a3b8' },
  { value: 'active', label: 'Active', color: '#4ade80' },
  { value: 'warned', label: 'Warned', color: '#facc15' },
  { value: 'expiring', label: 'Expiring', color: '#fb923c' },
  { value: 'expired', label: 'Expired', color: '#f87171' },
  { value: 'marked_for_deletion', label: 'Marked for Deletion', color: '#ef4444' },
]

// Selection helpers
const allExplorerSelected = computed(() =>
  lifecycleStore.explorerResources.length > 0 &&
  lifecycleStore.explorerResources.every(r => selectedIds.value.has(r.id))
)
const someExplorerSelected = computed(() =>
  lifecycleStore.explorerResources.some(r => selectedIds.value.has(r.id))
)

// Audit log pagination
const auditLogPageSize = 15
const auditLogShowAll = ref(false)
const visibleAuditLog = computed(() => {
  if (auditLogShowAll.value) return lifecycleStore.auditLog
  return lifecycleStore.auditLog.slice(0, auditLogPageSize)
})
const hasMoreAuditEntries = computed(() => lifecycleStore.auditLog.length > auditLogPageSize)

// Watch for scan job completion to refresh data
watch(
  () => jobsStore.currentScanJob,
  (job, oldJob) => {
    if (job && oldJob) {
      if (oldJob.status === 'running' && job.status === 'completed') {
        scanInProgress.value = false
        lifecycleStore.fetchPolicies()
        loadExplorer()
        lifecycleStore.fetchAuditLog()
        resourcesStore.fetchStats()
      } else if (oldJob.status === 'running' && job.status === 'failed') {
        scanInProgress.value = false
      }
    }
  },
  { deep: true },
)

async function triggerScan() {
  if (scanInProgress.value) return
  scanInProgress.value = true
  try {
    await jobsStore.submitScan()
  } catch {
    scanInProgress.value = false
  }
}

// Policies
const showPolicyForm = ref(false)
const editingPolicy = ref<PolicyResponse | null>(null)
const showDeleteConfirm = ref(false)
const deletingPolicy = ref<PolicyResponse | null>(null)

function editPolicyItem(policy: PolicyResponse) {
  editingPolicy.value = policy
  showPolicyForm.value = true
}

function closePolicyForm() {
  showPolicyForm.value = false
  editingPolicy.value = null
}

async function handlePolicySubmit(data: PolicyCreateRequest) {
  try {
    let result: PolicySaveResult
    if (editingPolicy.value) {
      result = await lifecycleStore.updatePolicy(editingPolicy.value.id, data)
    } else {
      result = await lifecycleStore.createPolicy(data)
    }
    closePolicyForm()
    saveResultBanner.value = {
      matched_count: result.matched_count,
      ttl_applied_count: result.ttl_applied_count,
    }
    setTimeout(() => { saveResultBanner.value = null }, 8000)
    if (result.ttl_applied_count > 0) {
      lifecycleStore.fetchAuditLog()
    }
  } catch {
    // Error toast shown by API client
  }
}

function confirmDeletePolicy(policy: PolicyResponse) {
  deletingPolicy.value = policy
  showDeleteConfirm.value = true
}

async function handleDeletePolicy() {
  if (deletingPolicy.value) {
    try {
      await lifecycleStore.deletePolicy(deletingPolicy.value.id)
    } catch {
      // Error toast shown by API client
    }
  }
  showDeleteConfirm.value = false
  deletingPolicy.value = null
}

// --- Explorer functions ---
function setExplorerState(state: string) {
  explorerState.value = state
  loadExplorer()
}

function loadExplorer() {
  selectedIds.value.clear()
  showExtendPanel.value = false
  showProtectPanel.value = false
  showMarkDeletePanel.value = false
  showExecuteDeletePanel.value = false

  const params: Record<string, string | number | boolean | undefined> = {}

  if (explorerState.value) {
    params.lifecycle_state = explorerState.value
  }
  if (explorerService.value) {
    params.services = explorerService.value
  }
  if (explorerAccount.value) {
    params.account_id = explorerAccount.value
  }
  if (explorerState.value === 'expiring' || explorerState.value === '') {
    params.days = explorerDays.value
  }
  if (explorerState.value === '') {
    params.include_active = true
  }

  lifecycleStore.fetchExplorerResources(params as Parameters<typeof lifecycleStore.fetchExplorerResources>[0])
}

function toggleSelectAll() {
  if (allExplorerSelected.value) {
    lifecycleStore.explorerResources.forEach(r => selectedIds.value.delete(r.id))
  } else {
    lifecycleStore.explorerResources.forEach(r => selectedIds.value.add(r.id))
  }
}

function toggleSelect(id: string) {
  if (selectedIds.value.has(id)) {
    selectedIds.value.delete(id)
  } else {
    selectedIds.value.add(id)
  }
}

function togglePanel(panel: 'extend' | 'protect' | 'markDelete' | 'executeDelete') {
  showExtendPanel.value = panel === 'extend' ? !showExtendPanel.value : false
  showProtectPanel.value = panel === 'protect' ? !showProtectPanel.value : false
  showMarkDeletePanel.value = panel === 'markDelete' ? !showMarkDeletePanel.value : false
  showExecuteDeletePanel.value = panel === 'executeDelete' ? !showExecuteDeletePanel.value : false
  actionReason.value = ''
  extendDays.value = 30
  deleteConfirmText.value = ''
}

function showActionMessage(message: string, type: 'success' | 'error') {
  actionMessage.value = message
  actionMessageType.value = type
  setTimeout(() => { actionMessage.value = '' }, 4000)
}

// Per-row action handlers
async function handleRowExtend(res: ReviewResourceResponse, days: number) {
  try {
    await lifecycleStore.reviewExtend([res.id], days)
    showActionMessage(`Extended 1 resource by ${days} days`, 'success')
    loadExplorer()
    lifecycleStore.fetchAuditLog()
  } catch {
    // Error toast shown by API client
  }
}

async function handleRowProtect(res: ReviewResourceResponse) {
  try {
    await lifecycleStore.reviewProtect([res.id])
    showActionMessage('Protected 1 resource', 'success')
    loadExplorer()
    lifecycleStore.fetchAuditLog()
  } catch {
    // Error toast shown by API client
  }
}

async function handleRowMarkDelete(res: ReviewResourceResponse) {
  try {
    await lifecycleStore.reviewMarkDelete([res.id])
    showActionMessage('Marked 1 resource for deletion', 'success')
    loadExplorer()
    lifecycleStore.fetchAuditLog()
  } catch {
    // Error toast shown by API client
  }
}

// Bulk action handlers
async function handleExtend() {
  actionLoading.value = true
  try {
    const ids = Array.from(selectedIds.value)
    const result = await lifecycleStore.reviewExtend(ids, extendDays.value, actionReason.value || undefined)
    showActionMessage(`Extended ${result.affected_count} resource(s) by ${extendDays.value} days`, 'success')
    selectedIds.value.clear()
    showExtendPanel.value = false
    actionReason.value = ''
    loadExplorer()
    lifecycleStore.fetchAuditLog()
  } catch (e) {
    showActionMessage(e instanceof Error ? e.message : 'Extend failed', 'error')
  } finally {
    actionLoading.value = false
  }
}

async function handleProtect() {
  actionLoading.value = true
  try {
    const ids = Array.from(selectedIds.value)
    const result = await lifecycleStore.reviewProtect(ids, actionReason.value || undefined)
    showActionMessage(`Protected ${result.affected_count} resource(s)`, 'success')
    selectedIds.value.clear()
    showProtectPanel.value = false
    actionReason.value = ''
    loadExplorer()
    lifecycleStore.fetchAuditLog()
  } catch (e) {
    showActionMessage(e instanceof Error ? e.message : 'Protect failed', 'error')
  } finally {
    actionLoading.value = false
  }
}

async function handleMarkDelete() {
  actionLoading.value = true
  try {
    const ids = Array.from(selectedIds.value)
    const result = await lifecycleStore.reviewMarkDelete(ids, actionReason.value || undefined)
    showActionMessage(`Marked ${result.affected_count} resource(s) for deletion`, 'success')
    selectedIds.value.clear()
    showMarkDeletePanel.value = false
    actionReason.value = ''
    loadExplorer()
    lifecycleStore.fetchAuditLog()
  } catch (e) {
    showActionMessage(e instanceof Error ? e.message : 'Mark delete failed', 'error')
  } finally {
    actionLoading.value = false
  }
}

async function handleExecuteDelete() {
  actionLoading.value = true
  try {
    const ids = Array.from(selectedIds.value)
    const result = await lifecycleStore.executeDelete(ids)
    const detail = result.details || `Deleted ${result.affected_count} resource(s)`
    const hasFailures = detail.includes('Failed')
    showActionMessage(detail, hasFailures ? 'error' : 'success')
    selectedIds.value.clear()
    showExecuteDeletePanel.value = false
    deleteConfirmText.value = ''
    loadExplorer()
    lifecycleStore.fetchAuditLog()
  } catch (e) {
    showActionMessage(e instanceof Error ? e.message : 'Execute delete failed', 'error')
  } finally {
    actionLoading.value = false
  }
}

// Display helpers
function daysDisplayClass(res: ReviewResourceResponse): string {
  if (res.days_until_expiry == null) return ''
  if (res.days_until_expiry < 0) return 'days-overdue'
  return fmt.daysClass(res.days_until_expiry)
}

function daysDisplayText(res: ReviewResourceResponse): string {
  if (res.days_until_expiry == null) return '--'
  if (res.days_until_expiry < 0) return `${Math.abs(res.days_until_expiry)}d overdue`
  return `${res.days_until_expiry}d`
}

// Tag helpers
function visibleTags(tags?: Record<string, string>): string[] {
  if (!tags) return []
  return Object.entries(tags)
    .slice(0, MAX_VISIBLE_TAGS)
    .map(([k, v]) => `${k}=${v}`)
}

function extraTagCount(tags?: Record<string, string>): number {
  if (!tags) return 0
  const total = Object.keys(tags).length
  if (total <= MAX_VISIBLE_TAGS) return 0
  return total - MAX_VISIBLE_TAGS
}

onMounted(() => {
  lifecycleStore.fetchPolicies()
  loadExplorer()
  lifecycleStore.fetchAuditLog()
  resourcesStore.fetchStats()

  if (jobsStore.currentScanJob?.status === 'running') {
    scanInProgress.value = true
  }
})
</script>

<style scoped>
.lifecycle-view {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}

.actions-bar {
  display: flex;
  align-items: center;
  gap: 1rem;
}

/* Feedback Banner */
.feedback-banner {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.75rem 1rem;
  border-radius: 8px;
  border: 1px solid;
  font-size: 0.85rem;
}

.feedback-success {
  background: #f0fdf4;
  border-color: #bbf7d0;
  color: #166534;
}

.feedback-error {
  background: #fef2f2;
  border-color: #fecaca;
  color: #991b1b;
}

.btn-dismiss {
  margin-left: auto;
  background: none;
  border: none;
  cursor: pointer;
  opacity: 0.5;
  color: inherit;
  padding: 0.2rem;
}
.btn-dismiss:hover { opacity: 1; }

/* Bulk Actions Bar */
.bulk-bar {
  background: #eff6ff;
  border-bottom: 1px solid #bfdbfe;
  padding: 0.65rem 1.25rem;
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.bulk-count {
  font-size: 0.82rem;
  font-weight: 600;
  color: #1e40af;
  margin-right: 0.5rem;
}

.bulk-btn {
  background: var(--primary-color) !important;
  color: white !important;
  border: none !important;
}
.bulk-btn:hover { background: #1d4ed8 !important; }

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
  background: white !important;
  color: var(--text-color) !important;
  border: 1px solid var(--surface-border) !important;
  padding: 0.35rem 0.75rem;
  font-size: 0.8rem;
  border-radius: 6px;
  cursor: pointer;
  font-weight: 500;
}
.bulk-btn-outline:hover { background: #f3f4f6 !important; }

.section-card {
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 10px;
  overflow: hidden;
}

.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 1rem 1.25rem;
  border-bottom: 1px solid var(--surface-border);
}

.section-title {
  font-size: 0.95rem;
  font-weight: 600;
  background: var(--gradient-brand-horizontal);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.section-controls {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.section-count {
  font-size: 0.8rem;
  color: var(--text-color-secondary);
}

.filter-input {
  padding: 0.35rem 0.6rem;
  border: 1px solid var(--surface-border);
  border-radius: 6px;
  font-size: 0.82rem;
  background: var(--surface-ground);
  color: var(--text-color);
}

.filter-input-narrow {
  width: 70px;
}

.section-empty {
  padding: 2.5rem;
  text-align: center;
  color: var(--text-color-secondary);
  font-size: 0.875rem;
}

.data-table {
  width: 100%;
  border-collapse: collapse;
}

.data-table th {
  text-align: left;
  padding: 0.65rem 1rem;
  font-size: 0.75rem;
  font-weight: 600;
  text-transform: uppercase;
  color: var(--text-color-secondary);
  background: var(--surface-ground);
  border-bottom: 1px solid var(--surface-border);
}

.data-table td {
  padding: 0.65rem 1rem;
  font-size: 0.85rem;
  border-bottom: 1px solid var(--surface-border);
}

.data-table tbody tr:hover {
  background: rgba(32, 108, 245, 0.05);
}

.checkbox-col {
  width: 40px;
  text-align: center;
}

.checkbox-col input[type="checkbox"] {
  cursor: pointer;
}

.row-selected {
  background: #eff6ff;
}

.row-selected:hover {
  background: #dbeafe;
}

.policy-name {
  font-weight: 500;
}

.policy-desc {
  font-size: 0.78rem;
  color: var(--text-color-secondary);
  margin-top: 2px;
}

.type-chips {
  display: flex;
  gap: 0.3rem;
  flex-wrap: wrap;
}

.type-chip {
  background: rgba(255, 255, 255, 0.06);
  padding: 0.15rem 0.4rem;
  border-radius: 3px;
  font-size: 0.75rem;
  color: var(--text-color-secondary);
}

.resource-count {
  font-weight: 600;
}

.status-badge {
  padding: 0.2rem 0.5rem;
  border-radius: 4px;
  font-size: 0.78rem;
  font-weight: 500;
}

.status-badge.enabled {
  background: rgba(34, 197, 94, 0.15);
  color: #4ade80;
}

.status-badge.disabled {
  background: rgba(255, 255, 255, 0.06);
  color: var(--text-color-secondary);
}

.service-badge {
  background: rgba(32, 108, 245, 0.15);
  color: #5a9aff;
  padding: 0.2rem 0.5rem;
  border-radius: 4px;
  font-size: 0.78rem;
  font-weight: 500;
}

.arn-cell {
  font-family: var(--font-mono), monospace;
  font-size: 0.78rem;
  color: var(--text-color-secondary);
}

.state-badge {
  padding: 0.2rem 0.5rem;
  border-radius: 4px;
  font-size: 0.78rem;
  font-weight: 500;
  background: rgba(255, 255, 255, 0.06);
  color: var(--text-color-secondary);
}

.state-active { background: rgba(34, 197, 94, 0.15); color: #4ade80; }
.state-warned { background: rgba(234, 179, 8, 0.15); color: #facc15; }
.state-danger { background: rgba(239, 68, 68, 0.15); color: #f87171; }
.state-expired { background: rgba(239, 68, 68, 0.15); color: #f87171; }

/* Policy pill */
.policy-pill {
  display: inline-block;
  padding: 0.15rem 0.45rem;
  border-radius: 10px;
  font-size: 0.72rem;
  font-weight: 500;
  background: #ede9fe;
  color: #6d28d9;
  max-width: 140px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.policy-pill-none {
  background: transparent;
  color: var(--text-color-secondary);
}

.days-badge {
  padding: 0.2rem 0.5rem;
  border-radius: 4px;
  font-size: 0.78rem;
  font-weight: 600;
}

.days-critical { background: rgba(239, 68, 68, 0.15); color: #f87171; }
.days-warning { background: rgba(234, 179, 8, 0.15); color: #facc15; }
.days-ok { background: rgba(34, 197, 94, 0.15); color: #4ade80; }
.days-overdue { background: rgba(239, 68, 68, 0.15); color: #f87171; }

.actions-cell {
  display: flex;
  gap: 0.35rem;
  align-items: center;
}

.btn-icon {
  background: none;
  border: 1px solid var(--surface-border);
  border-radius: 4px;
  padding: 0.3rem 0.45rem;
  cursor: pointer;
  color: var(--text-color-secondary);
  font-size: 0.8rem;
  transition: all 0.15s;
}

.btn-icon:hover {
  background: var(--surface-ground);
  color: var(--primary-color);
}

.btn-icon-danger:hover {
  color: #f87171;
  border-color: rgba(239, 68, 68, 0.3);
  background: rgba(239, 68, 68, 0.15);
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

.btn-action:hover {
  background: rgba(32, 108, 245, 0.12);
}

.btn-action-purple {
  color: #a78bfa;
}

.btn-action-purple:hover {
  background: rgba(124, 58, 237, 0.15);
}

.btn {
  padding: 0.5rem 1rem;
  border: none;
  border-radius: 6px;
  font-size: 0.85rem;
  cursor: pointer;
  font-weight: 500;
  transition: all 0.15s;
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
}

.btn-primary {
  background: var(--gradient-brand-horizontal);
  color: white;
}

.btn-primary:hover:not(:disabled) {
  box-shadow: 0 0 14px rgba(32, 108, 245, 0.35);
}

.btn-primary:disabled {
  opacity: 0.7;
  cursor: not-allowed;
}

.btn-secondary {
  background: var(--surface-ground);
  color: var(--text-color);
  border: 1px solid var(--surface-border);
}

.btn-secondary:hover {
  background: var(--surface-border);
}

.btn-danger {
  background: #ef4444;
  color: white;
}

.btn-danger:hover:not(:disabled) {
  background: #dc2626;
}

.btn-danger:disabled {
  opacity: 0.7;
  cursor: not-allowed;
}

.btn-outline {
  background: transparent;
  border: 1px solid var(--surface-border);
  color: var(--primary-color);
}

.btn-outline:hover,
.btn-outline.active {
  background: rgba(32, 108, 245, 0.12);
  border-color: var(--primary-color);
}

.btn-outline-purple {
  color: #a78bfa;
}

.btn-outline-purple:hover,
.btn-outline-purple.active {
  background: rgba(124, 58, 237, 0.15);
  border-color: #a78bfa;
}

.btn-outline-danger {
  color: #f87171;
}

.btn-outline-danger:hover,
.btn-outline-danger.active {
  background: rgba(239, 68, 68, 0.15);
  border-color: #f87171;
}

.btn-sm {
  padding: 0.35rem 0.75rem;
  font-size: 0.8rem;
}

/* Review filters */
.review-filters {
  display: flex;
  align-items: flex-end;
  gap: 1rem;
  padding: 0.75rem 1.25rem;
  border-bottom: 1px solid var(--surface-border);
  background: var(--surface-ground);
}

.filter-label {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  font-size: 0.75rem;
  font-weight: 500;
  color: var(--text-color-secondary);
}

.filter-label-inline {
  flex-direction: row;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.82rem;
  padding-bottom: 0.35rem;
}

/* Checkbox column */
.checkbox-col {
  width: 36px;
  text-align: center;
}

/* Bulk action bar */
.bulk-action-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.6rem 1.25rem;
  background: rgba(32, 108, 245, 0.12);
  border-bottom: 1px solid rgba(32, 108, 245, 0.25);
}

.bulk-count {
  font-size: 0.82rem;
  font-weight: 600;
  color: var(--primary-color);
}

.bulk-buttons {
  display: flex;
  gap: 0.5rem;
}

/* Action panels */
.action-panel {
  padding: 1rem 1.25rem;
  background: var(--surface-ground);
  border-bottom: 1px solid var(--surface-border);
}

.action-panel-header {
  font-size: 0.88rem;
  font-weight: 600;
  margin-bottom: 0.75rem;
}

.action-panel-header-danger {
  color: #f87171;
}

.action-panel-warning {
  font-size: 0.82rem;
  color: #facc15;
  background: rgba(234, 179, 8, 0.15);
  padding: 0.5rem 0.75rem;
  border-radius: 6px;
  margin-bottom: 0.75rem;
  line-height: 1.4;
}

.action-panel-fields {
  display: flex;
  gap: 1rem;
  align-items: flex-end;
  margin-bottom: 0.75rem;
}

.action-panel-fields .filter-label {
  flex: 1;
}

.action-panel-actions {
  display: flex;
  gap: 0.5rem;
  justify-content: flex-end;
}

/* Tags summary */
.tags-summary {
  display: flex;
  flex-wrap: wrap;
  gap: 0.25rem;
  align-items: center;
}

.tag-chip {
  background: rgba(255, 255, 255, 0.06);
  padding: 0.1rem 0.35rem;
  border-radius: 3px;
  font-size: 0.7rem;
  font-family: var(--font-mono), monospace;
  color: var(--text-color-secondary);
  max-width: 160px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tag-more {
  background: rgba(255, 255, 255, 0.1);
  font-family: inherit;
  font-weight: 500;
  color: var(--text-color-secondary);
}

/* Action message */
.action-message {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.6rem 1.25rem;
  font-size: 0.82rem;
  font-weight: 500;
  border-bottom: 1px solid var(--surface-border);
}

.action-message.success {
  background: rgba(34, 197, 94, 0.15);
  color: #4ade80;
}

.action-message.error {
  background: rgba(239, 68, 68, 0.15);
  color: #f87171;
}

/* Audit log */
.audit-table td {
  vertical-align: middle;
}

.timestamp-cell {
  font-size: 0.78rem;
  color: var(--text-color-secondary);
  white-space: nowrap;
}

.operation-badge {
  background: rgba(255, 255, 255, 0.06);
  padding: 0.2rem 0.5rem;
  border-radius: 4px;
  font-size: 0.78rem;
  font-weight: 500;
  color: var(--text-color-secondary);
}

.state-transition {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
}

.state-arrow {
  font-size: 0.65rem;
  color: var(--text-color-secondary);
}

.success-cell {
  text-align: center;
}

.success-icon {
  color: #4ade80;
  font-size: 1rem;
}

.error-icon {
  color: #f87171;
  font-size: 1rem;
  cursor: help;
}

.text-muted {
  color: var(--text-color-secondary);
  font-size: 0.78rem;
}

/* Workflow Guide */
.workflow-guide {
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 10px;
  overflow: hidden;
}

.guide-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.75rem 1.25rem;
  border-bottom: 1px solid var(--surface-border);
}

.guide-title {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.88rem;
  font-weight: 600;
  color: var(--text-color);
}

.guide-title i {
  background: var(--gradient-brand-horizontal);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  font-size: 1rem;
}

.guide-actions {
  display: flex;
  align-items: center;
  gap: 0.25rem;
}

.guide-toggle,
.guide-dismiss {
  background: none;
  border: none;
  color: var(--text-color-secondary);
  cursor: pointer;
  padding: 0.3rem 0.45rem;
  border-radius: 4px;
  font-size: 0.8rem;
  transition: all 0.15s;
}

.guide-toggle:hover,
.guide-dismiss:hover {
  background: var(--surface-ground);
  color: var(--text-color);
}

.guide-stepper {
  display: flex;
  align-items: flex-start;
  padding: 1.25rem 1.5rem 1.5rem;
  gap: 0;
}

.step {
  display: flex;
  flex-direction: column;
  align-items: center;
  flex: 1;
  position: relative;
  text-align: center;
}

.step-circle {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: linear-gradient(92.87deg, #206CF5 14.71%, #19D5D5 87.94%);
  color: white;
  font-size: 0.82rem;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
  z-index: 1;
  flex-shrink: 0;
}

.step-connector {
  position: absolute;
  top: 16px;
  left: calc(50% + 16px);
  width: calc(100% - 32px);
  height: 2px;
  background: var(--surface-border);
}

.step:last-child .step-connector {
  display: none;
}

.step-content {
  margin-top: 0.65rem;
  padding: 0 0.25rem;
}

.step-label {
  font-size: 0.82rem;
  font-weight: 600;
  color: var(--text-color);
  margin-bottom: 0.2rem;
}

.step-desc {
  font-size: 0.72rem;
  color: var(--text-color-secondary);
  line-height: 1.4;
}

/* Save result banner */
.save-result-banner {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  padding: 0.65rem 1rem;
  background: rgba(34, 197, 94, 0.15);
  border: 1px solid rgba(34, 197, 94, 0.3);
  border-radius: 8px;
  color: #4ade80;
  font-size: 0.85rem;
}

.save-result-banner strong {
  font-weight: 700;
}

.banner-dismiss {
  margin-left: auto;
  background: none;
  border: none;
  color: #4ade80;
  cursor: pointer;
  padding: 0.2rem 0.4rem;
  border-radius: 4px;
  font-size: 0.8rem;
}

.banner-dismiss:hover {
  background: rgba(34, 197, 94, 0.2);
}

/* Policy expand / drill-down */
.expand-cell {
  width: 36px;
  text-align: center;
}

.btn-expand {
  background: none;
  border: none;
  color: var(--text-color-secondary);
  cursor: pointer;
  padding: 0.25rem;
  border-radius: 4px;
  font-size: 0.75rem;
  transition: all 0.15s;
}

.btn-expand:hover {
  background: var(--surface-ground);
  color: var(--primary-color);
}

.row-expanded {
  background: rgba(32, 108, 245, 0.05);
}

.resource-count.clickable {
  cursor: pointer;
  text-decoration: underline;
  text-decoration-style: dotted;
  text-underline-offset: 2px;
}

.resource-count.clickable:hover {
  color: var(--primary-color);
}

.policy-drilldown-row td {
  padding: 0 !important;
  background: rgba(32, 108, 245, 0.03);
}

.policy-drilldown {
  padding: 0.75rem 1rem 0.75rem 2.5rem;
}

.drilldown-loading {
  font-size: 0.82rem;
  color: var(--text-color-secondary);
  padding: 0.5rem 0;
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.drilldown-empty {
  font-size: 0.82rem;
  color: var(--text-color-secondary);
  padding: 0.5rem 0;
}

.drilldown-table {
  width: 100%;
  border-collapse: collapse;
}

.drilldown-table th {
  text-align: left;
  padding: 0.4rem 0.75rem;
  font-size: 0.7rem;
  font-weight: 600;
  text-transform: uppercase;
  color: var(--text-color-secondary);
  border-bottom: 1px solid var(--surface-border);
}

.drilldown-table td {
  padding: 0.35rem 0.75rem;
  font-size: 0.8rem;
  border-bottom: 1px solid rgba(255, 255, 255, 0.03);
}

.drilldown-footer {
  text-align: center;
  padding: 0.5rem;
  font-size: 0.78rem;
  color: var(--text-color-secondary);
}

.ttl-set-badge {
  background: rgba(34, 197, 94, 0.15);
  color: #4ade80;
  padding: 0.1rem 0.35rem;
  border-radius: 3px;
  font-size: 0.72rem;
  font-weight: 500;
}

/* Spinner animation */
@keyframes spin {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}

.pi-spin {
  animation: spin 1s linear infinite;
}

.audit-log-footer {
  display: flex;
  justify-content: center;
  padding: 0.75rem;
  border-top: 1px solid var(--surface-border);
}

/* State filter chips */
.state-chips-bar {
  display: flex;
  gap: 0.5rem;
  padding: 0.75rem 1.25rem;
  border-bottom: 1px solid var(--surface-border);
  background: var(--surface-ground);
  flex-wrap: wrap;
}

.state-chip {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.35rem 0.75rem;
  border-radius: 20px;
  border: 1px solid var(--surface-border);
  background: transparent;
  color: var(--text-color-secondary);
  font-size: 0.8rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s;
}

.state-chip:hover {
  border-color: var(--primary-color);
  color: var(--text-color);
}

.state-chip.active {
  background: rgba(32, 108, 245, 0.15);
  border-color: var(--primary-color);
  color: var(--primary-color);
  font-weight: 600;
}

.chip-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

/* Explorer filters */
.explorer-filters {
  display: flex;
  align-items: flex-end;
  gap: 1rem;
  padding: 0.75rem 1.25rem;
  border-bottom: 1px solid var(--surface-border);
}

.account-cell {
  font-size: 0.78rem;
  font-family: var(--font-mono), monospace;
  color: var(--text-color-secondary);
}

.btn-action-danger {
  color: #f87171;
}

.btn-action-danger:hover {
  background: rgba(239, 68, 68, 0.15);
}
</style>
