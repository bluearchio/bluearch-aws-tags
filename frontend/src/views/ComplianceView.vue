<template>
  <div class="compliance-view">
    <PermissionBanner feature="compliance" />
    <!-- Loading / Error -->
    <div v-if="compStore.loading && !compStore.access" class="loading-state">
      Checking AWS Organizations access...
    </div>

    <!-- No Access -->
    <div v-else-if="compStore.access && !compStore.access.has_access" class="no-access-card">
      <i class="pi pi-lock"></i>
      <h3>AWS Organizations Access Required</h3>
      <p>Tag policy compliance requires AWS Organizations with Tag Policies enabled.</p>
      <p v-if="compStore.access.error" class="error-detail">{{ compStore.access.error }}</p>
    </div>

    <template v-else>
      <!-- Workflow Guide Banner -->
      <div v-if="!guideHidden" class="workflow-guide">
        <div class="guide-header">
          <div class="guide-title">
            <i class="pi pi-info-circle"></i>
            <span>How Tag Policy Compliance Works</span>
          </div>
          <div class="guide-actions">
            <a
              href="https://docs.aws.amazon.com/organizations/latest/userguide/orgs_manage_policies_tag-policies.html"
              target="_blank"
              class="guide-doc-link"
              title="AWS Documentation"
            >
              <i class="pi pi-external-link"></i> AWS Docs
            </a>
            <button class="guide-toggle" @click="guideCollapsed = !guideCollapsed">
              <i :class="guideCollapsed ? 'pi pi-chevron-down' : 'pi pi-chevron-up'"></i>
            </button>
            <button class="guide-dismiss" title="Dismiss guide" @click="dismissGuide">
              <i class="pi pi-times"></i>
            </button>
          </div>
        </div>
        <div v-if="!guideCollapsed" class="guide-body">
          <p class="guide-intro">
            AWS Tag Policies enforce standardized tagging across your organization.
            They define which tag keys are required, allowed values, and which resource types must be tagged.
          </p>
          <div class="guide-stepper">
            <div class="step">
              <div class="step-circle">1</div>
              <div class="step-connector"></div>
              <div class="step-content">
                <div class="step-label">Enable Tag Policies</div>
                <div class="step-desc">Enable the Tag Policies feature in AWS Organizations (requires management account)</div>
              </div>
            </div>
            <div class="step">
              <div class="step-circle">2</div>
              <div class="step-connector"></div>
              <div class="step-content">
                <div class="step-label">Create Policies</div>
                <div class="step-desc">Define tag keys, allowed values, and enforcement rules (e.g. require "Environment" with values dev/staging/prod)</div>
              </div>
            </div>
            <div class="step">
              <div class="step-circle">3</div>
              <div class="step-connector"></div>
              <div class="step-content">
                <div class="step-label">Attach to Targets</div>
                <div class="step-desc">Attach policies to the organization root, OUs, or specific accounts</div>
              </div>
            </div>
            <div class="step">
              <div class="step-circle">4</div>
              <div class="step-connector"></div>
              <div class="step-content">
                <div class="step-label">Check Compliance</div>
                <div class="step-desc">Identify resources with missing or non-compliant tags and remediate</div>
              </div>
            </div>
            <div class="step">
              <div class="step-circle">5</div>
              <div class="step-content">
                <div class="step-label">Enforce</div>
                <div class="step-desc">Enable enforcement to prevent non-compliant tag operations on supported resource types</div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Summary Cards -->
      <div class="cards-grid">
        <div class="stat-card">
          <div class="stat-icon stat-icon-primary">
            <i class="pi pi-file"></i>
          </div>
          <div class="stat-body">
            <span class="stat-value">{{ compStore.orgPolicies.length }}</span>
            <span class="stat-label">Tag Policies</span>
          </div>
        </div>
        <div class="stat-card clickable" @click="toggleEnableTagPolicies">
          <div class="stat-icon stat-icon-success">
            <i class="pi pi-check-circle"></i>
          </div>
          <div class="stat-body">
            <span class="stat-value">{{ compStore.access?.tag_policies_enabled ? 'Yes' : 'No' }}</span>
            <span class="stat-label">Tag Policies Enabled</span>
          </div>
          <button
            v-if="compStore.access?.tag_policies_enabled === false"
            class="btn btn-primary btn-sm enable-btn"
            @click.stop="toggleEnableTagPolicies"
          >
            Enable
          </button>
        </div>
        <div class="stat-card">
          <div class="stat-icon stat-icon-danger">
            <i class="pi pi-times-circle"></i>
          </div>
          <div class="stat-body">
            <span class="stat-value">{{ compStore.checkResult?.count ?? '-' }}</span>
            <span class="stat-label">Non-Compliant Resources</span>
          </div>
        </div>
        <div class="stat-card">
          <div class="stat-icon stat-icon-purple">
            <i class="pi pi-building"></i>
          </div>
          <div class="stat-body">
            <span class="stat-value">{{ compStore.access?.org_id || '-' }}</span>
            <span class="stat-label">Organization</span>
          </div>
        </div>
      </div>

      <!-- Org Policies Table -->
      <div class="section-card">
        <div class="section-header">
          <h2 class="section-title">AWS Tag Policies</h2>
          <div class="section-controls">
            <span class="section-count">{{ compStore.orgPolicies.length }} policies</span>
            <button class="btn btn-primary btn-sm" @click="openNewPolicyForm">
              <i class="pi pi-plus"></i> New Tag Policy
            </button>
          </div>
        </div>
        <div v-if="!compStore.orgPolicies.length" class="section-empty">
          No tag policies found in your organization
        </div>
        <table v-else class="data-table">
          <thead>
            <tr>
              <th>Name</th>
              <th>ID</th>
              <th>Description</th>
              <th>Type</th>
              <th>AWS Managed</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            <template v-for="p in compStore.orgPolicies" :key="p.id">
              <tr class="policy-row" :class="{ expanded: expandedPolicyId === p.id }">
                <td class="policy-name clickable" @click="togglePolicyDetail(p.id)">
                  <i
                    class="pi expand-icon"
                    :class="expandedPolicyId === p.id ? 'pi-chevron-down' : 'pi-chevron-right'"
                  ></i>
                  {{ p.name }}
                </td>
                <td class="id-cell">{{ p.id }}</td>
                <td>{{ p.description || '-' }}</td>
                <td>{{ p.type || 'TAG_POLICY' }}</td>
                <td>
                  <span class="status-badge" :class="p.aws_managed ? 'managed' : 'custom'">
                    {{ p.aws_managed ? 'AWS' : 'Custom' }}
                  </span>
                </td>
                <td class="actions-cell">
                  <button
                    v-if="!p.aws_managed"
                    class="btn-icon"
                    title="Edit policy"
                    @click="openEditPolicyForm(p)"
                  >
                    <i class="pi pi-pencil"></i>
                  </button>
                  <button
                    class="btn-icon"
                    title="Attach to target"
                    @click="openAttachDialog(p.id)"
                  >
                    <i class="pi pi-link"></i>
                  </button>
                  <button
                    v-if="!p.aws_managed"
                    class="btn-icon btn-icon-danger"
                    title="Delete policy"
                    @click="openDeleteConfirm(p.id, p.name)"
                  >
                    <i class="pi pi-trash"></i>
                  </button>
                </td>
              </tr>
              <!-- Expanded Detail Panel -->
              <tr v-if="expandedPolicyId === p.id" class="detail-row">
                <td colspan="6">
                  <div class="policy-detail-panel">
                    <div v-if="loadingDetail" class="detail-loading">
                      <i class="pi pi-spin pi-spinner"></i> Loading policy details...
                    </div>
                    <template v-else-if="compStore.policyDetail && compStore.policyDetail.id === p.id">
                      <div class="detail-section">
                        <h4>Policy Content</h4>
                        <pre class="detail-json">{{ formatJson(compStore.policyDetail.content) }}</pre>
                      </div>
                      <div class="detail-section">
                        <h4>
                          Attached Targets
                          <span class="target-count">
                            ({{ compStore.policyDetail.targets?.length || 0 }})
                          </span>
                        </h4>
                        <div v-if="!compStore.policyDetail.targets?.length" class="detail-empty">
                          No targets attached
                        </div>
                        <div v-else class="targets-list">
                          <div
                            v-for="t in compStore.policyDetail.targets"
                            :key="String(t.target_id || t.TargetId || t.id)"
                            class="target-item"
                          >
                            <span class="target-info">
                              <i class="pi" :class="getTargetIcon(t)"></i>
                              <span class="target-name">{{ t.name || t.Name || 'Target' }}</span>
                              <span class="target-id">{{ t.target_id || t.TargetId || t.id }}</span>
                              <span v-if="t.type || t.Type" class="target-type">{{ t.type || t.Type }}</span>
                            </span>
                            <button
                              class="btn btn-secondary btn-xs"
                              :disabled="detachingTarget === String(t.target_id || t.TargetId || t.id)"
                              @click="detachFromTarget(p.id, String(t.target_id || t.TargetId || t.id))"
                            >
                              {{ detachingTarget === String(t.target_id || t.TargetId || t.id) ? 'Detaching...' : 'Detach' }}
                            </button>
                          </div>
                        </div>
                      </div>
                      <div v-if="compStore.policyDetail.create_date || compStore.policyDetail.update_date" class="detail-section detail-meta">
                        <span v-if="compStore.policyDetail.create_date">
                          Created: {{ compStore.policyDetail.create_date }}
                        </span>
                        <span v-if="compStore.policyDetail.update_date">
                          Updated: {{ compStore.policyDetail.update_date }}
                        </span>
                      </div>
                    </template>
                  </div>
                </td>
              </tr>
            </template>
          </tbody>
        </table>
      </div>

      <!-- Non-Compliant Resources Table -->
      <div class="section-card">
        <div class="section-header">
          <h2 class="section-title">Non-Compliant Resources</h2>
          <div class="section-controls">
            <button class="btn btn-primary btn-sm" @click="refresh">
              <i class="pi pi-refresh"></i> Refresh
            </button>
          </div>
        </div>
        <div v-if="compStore.loading" class="section-loading">Checking compliance...</div>
        <div v-else-if="!compStore.checkResult?.resources?.length" class="section-empty">
          All resources are compliant
        </div>
        <table v-else class="data-table">
          <thead>
            <tr>
              <th>Resource ARN</th>
              <th>Type</th>
              <th>Region</th>
              <th>Account</th>
              <th>Issues</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(r, idx) in compStore.checkResult.resources" :key="idx">
              <td class="arn-cell"><ResourceLink :arn="r.resource_arn || ''" /></td>
              <td>{{ r.resource_type || '-' }}</td>
              <td>{{ r.region || '-' }}</td>
              <td class="id-cell">{{ r.account_id || '-' }}</td>
              <td>
                <div class="issue-chips">
                  <span
                    v-for="tag in (r.missing_tags || [])"
                    :key="'m-' + tag"
                    class="issue-chip missing"
                    :title="'Missing tag: ' + tag"
                  >{{ tag }}</span>
                  <span
                    v-for="tag in (r.keys_with_noncompliant_values || [])"
                    :key="'v-' + tag"
                    class="issue-chip invalid"
                    :title="'Invalid value: ' + tag"
                  >{{ tag }}</span>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>

    <!-- Tag Policy Create/Edit Dialog -->
    <TagPolicyDialog
      :visible="showTagPolicyForm"
      :edit-policy="editingOrgPolicy"
      @submit="handlePolicySubmit"
      @cancel="showTagPolicyForm = false"
    />

    <!-- Attach Policy Dialog -->
    <AttachPolicyDialog
      :visible="showAttachDialog"
      :policy-id="attachingPolicyId"
      :current-targets="attachDialogTargets"
      @attach="attachToTarget"
      @cancel="showAttachDialog = false"
    />

    <!-- Delete Confirm Dialog -->
    <ConfirmDialog
      :visible="showOrgDeleteConfirm"
      title="Delete Tag Policy"
      :message="'Are you sure you want to delete the tag policy \'' + deletingOrgPolicyName + '\'? This action cannot be undone.'"
      confirm-label="Delete"
      :destructive="true"
      @confirm="deleteOrgPolicy"
      @cancel="showOrgDeleteConfirm = false"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useComplianceStore } from '@/stores/compliance'
import PermissionBanner from '@/components/PermissionBanner.vue'
import TagPolicyDialog from '@/components/TagPolicyDialog.vue'
import AttachPolicyDialog from '@/components/AttachPolicyDialog.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import ResourceLink from '@/components/ResourceLink.vue'
import type { OrgPolicyCreateRequest, OrgPolicyDetailResponse, OrgPolicyResponse } from '@/types/api'

const compStore = useComplianceStore()

// Workflow guide state
const guideHidden = ref(localStorage.getItem('compliance-guide-hidden') === 'true')
const guideCollapsed = ref(false)

function dismissGuide() {
  guideHidden.value = true
  localStorage.setItem('compliance-guide-hidden', 'true')
}

const showTagPolicyForm = ref(false)
const editingOrgPolicy = ref<OrgPolicyDetailResponse | null>(null)
const expandedPolicyId = ref<string | null>(null)
const loadingDetail = ref(false)
const showAttachDialog = ref(false)
const attachingPolicyId = ref('')
const showOrgDeleteConfirm = ref(false)
const deletingOrgPolicyId = ref('')
const deletingOrgPolicyName = ref('')
const detachingTarget = ref('')

const attachDialogTargets = computed(() => {
  if (
    compStore.policyDetail &&
    compStore.policyDetail.id === attachingPolicyId.value &&
    compStore.policyDetail.targets
  ) {
    return compStore.policyDetail.targets
  }
  return []
})

function refresh(): void {
  compStore.checkCompliance()
}

function openNewPolicyForm(): void {
  editingOrgPolicy.value = null
  showTagPolicyForm.value = true
}

function openEditPolicyForm(policy: OrgPolicyResponse): void {
  if (compStore.policyDetail && compStore.policyDetail.id === policy.id) {
    editingOrgPolicy.value = compStore.policyDetail
  } else {
    editingOrgPolicy.value = {
      id: policy.id,
      name: policy.name,
      description: policy.description,
      arn: policy.arn,
      aws_managed: policy.aws_managed,
    }
  }
  showTagPolicyForm.value = true
}

async function handlePolicySubmit(data: OrgPolicyCreateRequest): Promise<void> {
  if (editingOrgPolicy.value) {
    await compStore.updateOrgPolicy(editingOrgPolicy.value.id, {
      name: data.name,
      description: data.description,
      content: data.content,
    })
  } else {
    await compStore.createOrgPolicy(data)
  }
  showTagPolicyForm.value = false
  editingOrgPolicy.value = null
}

function openDeleteConfirm(policyId: string, policyName: string): void {
  deletingOrgPolicyId.value = policyId
  deletingOrgPolicyName.value = policyName
  showOrgDeleteConfirm.value = true
}

async function deleteOrgPolicy(): Promise<void> {
  await compStore.deleteOrgPolicy(deletingOrgPolicyId.value)
  showOrgDeleteConfirm.value = false
  if (expandedPolicyId.value === deletingOrgPolicyId.value) {
    expandedPolicyId.value = null
  }
  deletingOrgPolicyId.value = ''
  deletingOrgPolicyName.value = ''
}

function openAttachDialog(policyId: string): void {
  attachingPolicyId.value = policyId
  showAttachDialog.value = true
}

async function attachToTarget(targetId: string): Promise<void> {
  await compStore.attachPolicy(attachingPolicyId.value, targetId)
  if (expandedPolicyId.value === attachingPolicyId.value) {
    await compStore.fetchPolicyDetail(attachingPolicyId.value)
  }
}

async function detachFromTarget(policyId: string, targetId: string): Promise<void> {
  detachingTarget.value = targetId
  await compStore.detachPolicy(policyId, targetId)
  detachingTarget.value = ''
}

async function toggleEnableTagPolicies(): Promise<void> {
  if (compStore.access?.tag_policies_enabled) {
    await compStore.disableTagPolicies()
  } else {
    await compStore.enableTagPolicies()
  }
}

async function togglePolicyDetail(policyId: string): Promise<void> {
  if (expandedPolicyId.value === policyId) {
    expandedPolicyId.value = null
    return
  }
  expandedPolicyId.value = policyId
  loadingDetail.value = true
  await compStore.fetchPolicyDetail(policyId)
  loadingDetail.value = false
}

function formatJson(content: Record<string, unknown> | undefined): string {
  if (!content) return '(no content)'
  return JSON.stringify(content, null, 2)
}

function getTargetIcon(target: Record<string, unknown>): string {
  const type = String(target.type || target.Type || '').toUpperCase()
  if (type === 'ROOT') return 'pi-globe'
  if (type === 'ORGANIZATIONAL_UNIT') return 'pi-sitemap'
  return 'pi-user'
}

onMounted(() => {
  compStore.fetchAll()
})
</script>

<style scoped>
.compliance-view {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}

.cards-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
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

.stat-card.clickable {
  cursor: pointer;
  transition: border-color 0.15s;
}

.stat-card.clickable:hover {
  border-color: var(--primary-color);
}

.stat-icon {
  width: 44px;
  height: 44px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1.1rem;
  flex-shrink: 0;
}

.stat-icon-primary { background: rgba(32, 108, 245, 0.12); color: #5a9aff; }
.stat-icon-success { background: rgba(34, 197, 94, 0.12); color: #4ade80; }
.stat-icon-danger { background: rgba(239, 68, 68, 0.1); color: #f87171; }
.stat-icon-purple { background: rgba(124, 58, 237, 0.12); color: #a78bfa; }

.stat-body {
  display: flex;
  flex-direction: column;
  flex: 1;
}

.stat-value {
  font-size: 1.2rem;
  font-weight: 700;
  color: var(--text-color);
}

.stat-label {
  font-size: 0.78rem;
  color: var(--text-color-secondary);
  margin-top: 2px;
}

.enable-btn {
  flex-shrink: 0;
}

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
.section-count { font-size: 0.8rem; color: var(--text-color-secondary); }

.section-controls {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.section-empty, .section-loading {
  padding: 2.5rem;
  text-align: center;
  color: var(--text-color-secondary);
  font-size: 0.875rem;
}

.data-table { width: 100%; border-collapse: collapse; }

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

.policy-row.expanded td {
  border-bottom-color: transparent;
}

.policy-name {
  font-weight: 500;
}

.policy-name.clickable {
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 0.4rem;
}

.policy-name.clickable:hover {
  color: var(--primary-color);
}

.expand-icon {
  font-size: 0.7rem;
  color: var(--text-color-secondary);
  flex-shrink: 0;
}

.arn-cell, .id-cell {
  font-family: 'SF Mono', monospace;
  font-size: 0.78rem;
  color: var(--text-color-secondary);
}

.actions-cell {
  white-space: nowrap;
}

.btn-icon {
  background: none;
  border: none;
  cursor: pointer;
  padding: 0.3rem;
  border-radius: 4px;
  color: var(--text-color-secondary);
  transition: all 0.15s;
}

.btn-icon:hover {
  background: var(--surface-ground);
  color: var(--primary-color);
}

.btn-icon-danger:hover {
  color: var(--color-danger);
}

.btn-icon i {
  font-size: 0.85rem;
}

.status-badge {
  padding: 0.2rem 0.5rem;
  border-radius: 4px;
  font-size: 0.78rem;
  font-weight: 500;
}

.status-badge.managed { background: rgba(32, 108, 245, 0.15); color: #5a9aff; }
.status-badge.custom { background: rgba(34, 197, 94, 0.15); color: #4ade80; }

/* Detail Panel */
.detail-row td {
  padding: 0;
  background: var(--surface-ground);
}

.policy-detail-panel {
  padding: 1rem 1.25rem 1.25rem;
  border-bottom: 2px solid var(--surface-border);
}

.detail-loading {
  padding: 1.5rem;
  text-align: center;
  color: var(--text-color-secondary);
  font-size: 0.85rem;
}

.detail-loading i {
  margin-right: 0.5rem;
}

.detail-section {
  margin-bottom: 1rem;
}

.detail-section:last-child {
  margin-bottom: 0;
}

.detail-section h4 {
  font-size: 0.82rem;
  font-weight: 600;
  color: var(--text-color);
  margin-bottom: 0.5rem;
}

.target-count {
  font-weight: 400;
  color: var(--text-color-secondary);
}

.detail-json {
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 6px;
  padding: 0.75rem 1rem;
  font-family: 'SF Mono', 'Fira Code', 'Cascadia Code', monospace;
  font-size: 0.78rem;
  line-height: 1.5;
  overflow-x: auto;
  max-height: 300px;
  overflow-y: auto;
  white-space: pre;
  color: var(--text-color);
}

.detail-empty {
  font-size: 0.82rem;
  color: var(--text-color-secondary);
  padding: 0.5rem 0;
}

.targets-list {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}

.target-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.4rem 0.75rem;
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 6px;
}

.target-info {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  min-width: 0;
  overflow: hidden;
}

.target-info i {
  font-size: 0.8rem;
  color: var(--text-color-secondary);
  flex-shrink: 0;
}

.target-name {
  font-size: 0.82rem;
  font-weight: 500;
  color: var(--text-color);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.target-id {
  font-family: 'SF Mono', monospace;
  font-size: 0.72rem;
  color: var(--text-color-secondary);
  flex-shrink: 0;
}

.target-type {
  font-size: 0.7rem;
  padding: 0.1rem 0.35rem;
  border-radius: 3px;
  background: var(--surface-ground);
  color: var(--text-color-secondary);
  flex-shrink: 0;
}

.detail-meta {
  display: flex;
  gap: 1.5rem;
  font-size: 0.75rem;
  color: var(--text-color-secondary);
  padding-top: 0.5rem;
  border-top: 1px solid var(--surface-border);
}

.issue-chips {
  display: flex;
  gap: 0.3rem;
  flex-wrap: wrap;
}

.issue-chip {
  padding: 0.15rem 0.45rem;
  border-radius: 3px;
  font-size: 0.72rem;
  font-weight: 500;
}

.issue-chip.missing { background: rgba(239, 68, 68, 0.1); color: #f87171; }
.issue-chip.invalid { background: rgba(234, 179, 8, 0.1); color: var(--color-warning); }

.no-access-card {
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 10px;
  padding: 3rem;
  text-align: center;
  color: var(--text-color-secondary);
}

.no-access-card i { font-size: 2.5rem; color: var(--color-warning); margin-bottom: 1rem; }
.no-access-card h3 { color: var(--text-color); margin-bottom: 0.5rem; }
.no-access-card p { font-size: 0.9rem; }
.error-detail { font-family: 'SF Mono', monospace; font-size: 0.8rem; margin-top: 0.75rem; color: #f87171; }

.loading-state {
  padding: 3rem;
  text-align: center;
  color: var(--text-color-secondary);
  font-size: 0.9rem;
}

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
}

.btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
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

.guide-doc-link {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  padding: 0.3rem 0.65rem;
  border-radius: 4px;
  font-size: 0.78rem;
  font-weight: 500;
  color: var(--primary-color);
  text-decoration: none;
  transition: all 0.15s;
}

.guide-doc-link:hover {
  background: rgba(32, 108, 245, 0.1);
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

.guide-body {
  padding: 1rem 1.5rem 1.5rem;
}

.guide-intro {
  font-size: 0.85rem;
  color: var(--text-color-secondary);
  line-height: 1.5;
  margin-bottom: 1.25rem;
}

.guide-stepper {
  display: flex;
  align-items: flex-start;
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

.btn-primary { background: var(--gradient-brand-horizontal); color: white; }
.btn-primary:hover:not(:disabled) { box-shadow: 0 0 14px rgba(32, 108, 245, 0.35); }
.btn-secondary { background: var(--surface-ground); color: var(--text-color); border: 1px solid var(--surface-border); }
.btn-secondary:hover:not(:disabled) { background: var(--surface-border); }
.btn-sm { padding: 0.35rem 0.75rem; font-size: 0.8rem; }
.btn-xs { padding: 0.2rem 0.5rem; font-size: 0.75rem; }
</style>
