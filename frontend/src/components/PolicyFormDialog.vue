<template>
  <div v-if="visible" class="dialog-overlay" @click.self="cancel">
    <div class="dialog-box">
      <h3 class="dialog-title">{{ editPolicy ? 'Edit Policy' : 'New Lifecycle Policy' }}</h3>

      <!-- Match Preview (top) -->
        <div class="match-preview-section">
          <div class="match-preview-header">
            <i class="pi pi-search"></i>
            <span v-if="matchLoading" class="match-loading">
              <i class="pi pi-spin pi-spinner"></i> Checking matches...
            </span>
            <span v-else-if="matchResult !== null" class="match-count" :class="{ 'has-matches': matchResult.matched_count > 0 }">
              {{ matchResult.matched_count }} resource{{ matchResult.matched_count !== 1 ? 's' : '' }} match this policy
            </span>
            <span v-else class="match-hint">
              Configure resource types or conditions to see matching resources
            </span>
            <button
              v-if="matchResult && matchResult.resources.length > 0"
              type="button"
              class="match-toggle"
              @click="matchExpanded = !matchExpanded"
            >
              <i :class="matchExpanded ? 'pi pi-chevron-up' : 'pi pi-chevron-down'"></i>
            </button>
          </div>
          <div v-if="matchExpanded && matchResult && matchResult.resources.length > 0" class="match-preview-list">
            <div v-for="res in matchResult.resources.slice(0, 20)" :key="res.id" class="match-preview-item">
              <span class="match-svc">{{ res.service_name }}</span>
              <ResourceLink class="match-arn" :id="res.id" :arn="res.resource_arn" :max-len="50" />
              <span class="match-region">{{ res.region }}</span>
              <span v-if="res.has_ttl" class="match-ttl-badge">TTL set</span>
            </div>
            <div v-if="matchResult.matched_count > 20" class="match-more">
              + {{ matchResult.matched_count - 20 }} more
            </div>
          </div>
        </div>

      <form @submit.prevent="submit">
        <!-- Section 1: Basic Info -->
        <div class="form-section" :class="{ collapsed: collapsedSections.basic }">
          <div class="section-header" @click="toggleSection('basic')">
            <i class="pi pi-info-circle section-icon"></i>
            <span class="section-label">Basic Info</span>
            <i :class="collapsedSections.basic ? 'pi pi-chevron-down' : 'pi pi-chevron-up'" class="section-chevron"></i>
          </div>
          <div v-show="!collapsedSections.basic" class="section-body">
            <div class="form-group">
              <label>Name <span class="required">*</span></label>
              <input v-model="form.name" type="text" required placeholder="e.g. dev-cleanup" />
            </div>
            <div class="form-group">
              <label>Description</label>
              <input v-model="form.description" type="text" placeholder="Optional description" />
            </div>
          </div>
        </div>

        <!-- Section 2: Resource Types -->
        <div class="form-section" :class="{ collapsed: collapsedSections.resourceTypes }">
          <div class="section-header" @click="toggleSection('resourceTypes')">
            <i class="pi pi-server section-icon"></i>
            <span class="section-label">Resource Types</span>
            <span v-if="form.resource_types.length" class="section-badge">{{ form.resource_types.length }}</span>
            <i :class="collapsedSections.resourceTypes ? 'pi pi-chevron-down' : 'pi pi-chevron-up'" class="section-chevron"></i>
          </div>
          <div v-show="!collapsedSections.resourceTypes" class="section-body">
            <div class="resource-types-grid">
              <label
                v-for="rt in resourceTypeOptions"
                :key="rt.value"
                class="checkbox-item"
                :class="{ checked: form.resource_types.includes(rt.value) }"
              >
                <input
                  type="checkbox"
                  :value="rt.value"
                  :checked="form.resource_types.includes(rt.value)"
                  @change="toggleResourceType(rt.value)"
                />
                <i :class="rt.icon" class="checkbox-svc-icon"></i>
                <span class="checkbox-label">{{ rt.label }}</span>
              </label>
            </div>
            <p class="form-hint">Select resource types this policy applies to. Leave empty for all types.</p>
          </div>
        </div>

        <!-- Section 3: Tag Conditions -->
        <div class="form-section" :class="{ collapsed: collapsedSections.conditions }">
          <div class="section-header" @click="toggleSection('conditions')">
            <i class="pi pi-tags section-icon"></i>
            <span class="section-label">Tag Conditions</span>
            <span v-if="form.tag_conditions.length" class="section-badge">{{ form.tag_conditions.length }}</span>
            <i :class="collapsedSections.conditions ? 'pi pi-chevron-down' : 'pi pi-chevron-up'" class="section-chevron"></i>
          </div>
          <div v-show="!collapsedSections.conditions" class="section-body">
            <p class="form-hint" style="margin-bottom: 0.5rem;">
              Define tag-based conditions that resources must match for this policy to apply.
            </p>
            <div v-for="(cond, idx) in form.tag_conditions" :key="idx" class="dynamic-row">
              <div class="dynamic-field" style="flex: 2;">
                <input
                  v-model="cond.field"
                  type="text"
                  placeholder="Tag key (e.g. Environment)"
                />
              </div>
              <div class="dynamic-field" style="flex: 1.5;">
                <select v-model="cond.operator">
                  <option value="equals">equals</option>
                  <option value="not_equals">not_equals</option>
                  <option value="contains">contains</option>
                  <option value="exists">exists</option>
                  <option value="not_exists">not_exists</option>
                </select>
              </div>
              <div class="dynamic-field" style="flex: 2;" v-if="!isPresenceOperator(cond.operator)">
                <input
                  v-model="cond.value"
                  type="text"
                  placeholder="Value"
                />
              </div>
              <button type="button" class="btn-icon btn-icon-danger" @click="removeTagCondition(idx)" title="Remove condition">
                <i class="pi pi-trash"></i>
              </button>
            </div>
            <button type="button" class="btn-add" @click="addTagCondition">
              <i class="pi pi-plus"></i> Add Condition
            </button>
          </div>
        </div>

        <!-- Section 4: Exclusion Patterns -->
        <div class="form-section" :class="{ collapsed: collapsedSections.exclusions }">
          <div class="section-header" @click="toggleSection('exclusions')">
            <i class="pi pi-ban section-icon"></i>
            <span class="section-label">Exclusion Patterns</span>
            <span v-if="totalExclusions > 0" class="section-badge">{{ totalExclusions }}</span>
            <i :class="collapsedSections.exclusions ? 'pi pi-chevron-down' : 'pi pi-chevron-up'" class="section-chevron"></i>
          </div>
          <div v-show="!collapsedSections.exclusions" class="section-body">
            <!-- Resource Name Patterns -->
            <div class="subsection">
              <label class="subsection-label">Resource Name Patterns</label>
              <p class="form-hint" style="margin-bottom: 0.5rem;">
                Glob patterns to exclude resources by name (e.g. *-prod-*, backup-*).
              </p>
              <div v-for="(_p, idx) in form.exclude_resource_names" :key="'rn-' + idx" class="dynamic-row">
                <div class="dynamic-field" style="flex: 1;">
                  <input
                    v-model="form.exclude_resource_names[idx]"
                    type="text"
                    placeholder="*-prod-*"
                  />
                </div>
                <button type="button" class="btn-icon btn-icon-danger" @click="removeExcludeResourceName(idx)" title="Remove pattern">
                  <i class="pi pi-trash"></i>
                </button>
              </div>
              <button type="button" class="btn-add" @click="addExcludeResourceName">
                <i class="pi pi-plus"></i> Add Pattern
              </button>
            </div>

            <!-- Tag Exclusions -->
            <div class="subsection">
              <label class="subsection-label">Tag Exclusions</label>
              <p class="form-hint" style="margin-bottom: 0.5rem;">
                Exclude resources that have specific tags (value is optional).
              </p>
              <div v-for="(tag, idx) in form.exclude_tags" :key="'et-' + idx" class="dynamic-row">
                <div class="dynamic-field" style="flex: 1;">
                  <input
                    v-model="tag.key"
                    type="text"
                    placeholder="Tag key"
                  />
                </div>
                <div class="dynamic-field" style="flex: 1;">
                  <input
                    v-model="tag.value"
                    type="text"
                    placeholder="Value (optional)"
                  />
                </div>
                <button type="button" class="btn-icon btn-icon-danger" @click="removeExcludeTag(idx)" title="Remove tag">
                  <i class="pi pi-trash"></i>
                </button>
              </div>
              <button type="button" class="btn-add" @click="addExcludeTag">
                <i class="pi pi-plus"></i> Add Tag Exclusion
              </button>
            </div>
          </div>
        </div>

        <!-- Section 5: Lifecycle Settings -->
        <div class="form-section" :class="{ collapsed: collapsedSections.lifecycle }">
          <div class="section-header" @click="toggleSection('lifecycle')">
            <i class="pi pi-clock section-icon"></i>
            <span class="section-label">Lifecycle Settings</span>
            <i :class="collapsedSections.lifecycle ? 'pi pi-chevron-down' : 'pi pi-chevron-up'" class="section-chevron"></i>
          </div>
          <div v-show="!collapsedSections.lifecycle" class="section-body">
            <div class="form-row">
              <div class="form-group">
                <label>TTL (days) <span class="required">*</span></label>
                <input v-model.number="form.ttl_days" type="number" min="1" max="3650" required />
                <p class="form-hint">Time-to-live before resource expires.</p>
              </div>
              <div class="form-group">
                <label>Grace Period (days)</label>
                <input v-model.number="form.grace_period_days" type="number" min="0" max="365" />
                <p class="form-hint">Extra days after expiry before deletion.</p>
              </div>
            </div>
            <div class="form-row">
              <div class="form-group">
                <label>Warning Days Before</label>
                <input v-model.number="form.warning_days" type="number" min="0" max="365" />
                <p class="form-hint">Days before expiry to start warnings.</p>
              </div>
              <div class="form-group">
                <label>Warning Schedule</label>
                <input
                  v-model="form.warning_schedule_text"
                  type="text"
                  placeholder="e.g. 7,3,1"
                />
                <p class="form-hint">Comma-separated days for warning notifications.</p>
              </div>
            </div>
          </div>
        </div>

        <!-- Section 6: Safety & Automation -->
        <div class="form-section" :class="{ collapsed: collapsedSections.safety }">
          <div class="section-header" @click="toggleSection('safety')">
            <i class="pi pi-shield section-icon"></i>
            <span class="section-label">Safety &amp; Automation</span>
            <i :class="collapsedSections.safety ? 'pi pi-chevron-down' : 'pi pi-chevron-up'" class="section-chevron"></i>
          </div>
          <div v-show="!collapsedSections.safety" class="section-body">
            <div class="form-row">
              <div class="form-group">
                <label>Priority</label>
                <input v-model.number="form.priority" type="number" min="1" max="10000" />
                <p class="form-hint">Lower number = higher priority.</p>
              </div>
            </div>
            <div class="toggle-row">
              <label class="toggle-item" :class="{ active: form.enabled }">
                <span class="toggle-switch" @click.prevent="form.enabled = !form.enabled">
                  <span class="toggle-knob" :class="{ on: form.enabled }"></span>
                </span>
                <span class="toggle-label">
                  <span class="toggle-title">Enabled</span>
                  <span class="toggle-desc">Policy is active and will be evaluated</span>
                </span>
              </label>
              <label class="toggle-item" :class="{ active: form.auto_apply }">
                <span class="toggle-switch" @click.prevent="form.auto_apply = !form.auto_apply">
                  <span class="toggle-knob" :class="{ on: form.auto_apply }"></span>
                </span>
                <span class="toggle-label">
                  <span class="toggle-title">Auto-Apply</span>
                  <span class="toggle-desc">Automatically apply TTL to matching resources</span>
                </span>
              </label>
            </div>
          </div>
        </div>

        <!-- Error & Actions -->
        <div v-if="errorMsg" class="form-error">
          <i class="pi pi-exclamation-triangle"></i> {{ errorMsg }}
        </div>
        <div class="dialog-actions">
          <button type="button" class="btn btn-secondary" @click="cancel">Cancel</button>
          <button type="submit" class="btn btn-primary" :disabled="submitting">
            <i v-if="submitting" class="pi pi-spin pi-spinner"></i>
            {{ submitting ? 'Saving...' : (editPolicy ? 'Update Policy' : 'Create Policy') }}
          </button>
        </div>
      </form>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, computed } from 'vue'
import type { PolicyResponse, PolicyCreateRequest, TagCondition, MatchPreviewResponse } from '@/types/api'
import { useLifecycleStore } from '@/stores/lifecycle'
import ResourceLink from '@/components/ResourceLink.vue'

const lifecycleStore = useLifecycleStore()

const props = defineProps<{
  visible: boolean
  editPolicy?: PolicyResponse | null
}>()

const emit = defineEmits<{
  submit: [data: PolicyCreateRequest]
  cancel: []
}>()

const resourceTypeOptions = [
  { value: 'ec2_instance', label: 'EC2 Instance', icon: 'pi pi-desktop' },
  { value: 'ec2_volume', label: 'EBS Volume', icon: 'pi pi-database' },
  { value: 'ec2_snapshot', label: 'EC2 Snapshot', icon: 'pi pi-camera' },
  { value: 'ec2_ami', label: 'EC2 AMI', icon: 'pi pi-image' },
  { value: 'ec2_eip', label: 'Elastic IP', icon: 'pi pi-globe' },
  { value: 's3_bucket', label: 'S3 Bucket', icon: 'pi pi-inbox' },
  { value: 'lambda_function', label: 'Lambda Function', icon: 'pi pi-bolt' },
  { value: 'lambda_layer', label: 'Lambda Layer', icon: 'pi pi-clone' },
  { value: 'rds_instance', label: 'RDS Instance', icon: 'pi pi-database' },
  { value: 'rds_cluster', label: 'RDS Cluster', icon: 'pi pi-sitemap' },
  { value: 'rds_snapshot', label: 'RDS Snapshot', icon: 'pi pi-camera' },
  { value: 'dynamodb_table', label: 'DynamoDB Table', icon: 'pi pi-table' },
  { value: 'elasticache_cluster', label: 'ElastiCache', icon: 'pi pi-bolt' },
  { value: 'ecs_cluster', label: 'ECS Cluster', icon: 'pi pi-th-large' },
  { value: 'ecs_service', label: 'ECS Service', icon: 'pi pi-cog' },
  { value: 'ecs_task_definition', label: 'ECS Task Def', icon: 'pi pi-file' },
  { value: 'eks_cluster', label: 'EKS Cluster', icon: 'pi pi-th-large' },
  { value: 'elb_load_balancer', label: 'Load Balancer', icon: 'pi pi-arrows-h' },
  { value: 'sns_topic', label: 'SNS Topic', icon: 'pi pi-bell' },
  { value: 'sqs_queue', label: 'SQS Queue', icon: 'pi pi-list' },
  { value: 'cloudwatch_alarm', label: 'CW Alarm', icon: 'pi pi-exclamation-triangle' },
  { value: 'cloudwatch_log_group', label: 'CW Log Group', icon: 'pi pi-file' },
]

interface FormTagCondition {
  field: string
  operator: string
  value: string
}

interface FormExcludeTag {
  key: string
  value: string
}

interface FormState {
  name: string
  description: string
  ttl_days: number
  warning_days: number
  priority: number
  enabled: boolean
  resource_types: string[]
  tag_conditions: FormTagCondition[]
  exclude_resource_names: string[]
  exclude_tags: FormExcludeTag[]
  warning_schedule_text: string
  grace_period_days: number
  auto_apply: boolean
}

function defaultForm(): FormState {
  return {
    name: '',
    description: '',
    ttl_days: 30,
    warning_days: 7,
    priority: 100,
    enabled: true,
    resource_types: [],
    tag_conditions: [],
    exclude_resource_names: [],
    exclude_tags: [],
    warning_schedule_text: '7,3,1',
    grace_period_days: 0,
    auto_apply: false,
  }
}

const form = ref<FormState>(defaultForm())

const collapsedSections = ref({
  basic: false,
  resourceTypes: true,
  conditions: true,
  exclusions: true,
  lifecycle: false,
  safety: true,
})

const submitting = ref(false)
const errorMsg = ref('')

const totalExclusions = computed(() => {
  return form.value.exclude_resource_names.filter(p => p.trim()).length
    + form.value.exclude_tags.filter(t => t.key.trim()).length
})

// Match preview
const matchResult = ref<MatchPreviewResponse | null>(null)
const matchLoading = ref(false)
const matchExpanded = ref(false)
let matchDebounceTimer: ReturnType<typeof setTimeout> | null = null

function triggerMatchPreview() {
  if (matchDebounceTimer) clearTimeout(matchDebounceTimer)
  matchDebounceTimer = setTimeout(async () => {
    // Build conditions for preview
    const validConditions = form.value.tag_conditions.filter(c => c.field.trim())
    const conditions = validConditions.length
      ? { tags: validConditions.map(c => ({ field: `tags.${c.field.trim()}`, operator: c.operator, value: isPresenceOperator(c.operator) ? undefined : c.value.trim() || undefined })) }
      : undefined

    const exclNames = form.value.exclude_resource_names.filter(p => p.trim()).map(p => p.trim())
    const exclTags = form.value.exclude_tags.filter(t => t.key.trim()).map(t => ({ key: t.key.trim(), value: t.value.trim() || undefined }))
    const exclude_patterns = exclNames.length || exclTags.length
      ? { resource_names: exclNames, tags: exclTags }
      : undefined

    matchLoading.value = true
    try {
      matchResult.value = await lifecycleStore.matchPreview({
        resource_types: form.value.resource_types.length ? form.value.resource_types : undefined,
        conditions,
        exclude_patterns,
      })
    } catch {
      matchResult.value = null
    } finally {
      matchLoading.value = false
    }
  }, 500)
}

// Watch form fields that affect matching
watch(
  () => [
    form.value.resource_types,
    form.value.tag_conditions,
    form.value.exclude_resource_names,
    form.value.exclude_tags,
  ],
  () => {
    if (props.visible) triggerMatchPreview()
  },
  { deep: true },
)

function isPresenceOperator(op: string): boolean {
  return op === 'exists' || op === 'not_exists'
}

function toggleSection(section: keyof typeof collapsedSections.value) {
  collapsedSections.value[section] = !collapsedSections.value[section]
}

function toggleResourceType(value: string) {
  const idx = form.value.resource_types.indexOf(value)
  if (idx >= 0) {
    form.value.resource_types.splice(idx, 1)
  } else {
    form.value.resource_types.push(value)
  }
}

// Tag conditions
function addTagCondition() {
  form.value.tag_conditions.push({ field: '', operator: 'equals', value: '' })
}

function removeTagCondition(idx: number) {
  form.value.tag_conditions.splice(idx, 1)
}

// Exclusion - resource names
function addExcludeResourceName() {
  form.value.exclude_resource_names.push('')
}

function removeExcludeResourceName(idx: number) {
  form.value.exclude_resource_names.splice(idx, 1)
}

// Exclusion - tags
function addExcludeTag() {
  form.value.exclude_tags.push({ key: '', value: '' })
}

function removeExcludeTag(idx: number) {
  form.value.exclude_tags.splice(idx, 1)
}

watch(
  () => props.visible,
  (visible) => {
    if (visible && props.editPolicy) {
      const p = props.editPolicy
      const tagConds: FormTagCondition[] = (p.conditions?.tags || []).map((c: TagCondition) => ({
        field: (c.field || '').replace(/^tags\./, ''),
        operator: c.operator || 'equals',
        value: c.value || '',
      }))
      const exclNames: string[] = p.exclude_patterns?.resource_names || []
      const exclTags: FormExcludeTag[] = (p.exclude_patterns?.tags || []).map(t => ({
        key: t.key || '',
        value: t.value || '',
      }))
      form.value = {
        name: p.name,
        description: p.description || '',
        ttl_days: p.default_ttl_days || 30,
        warning_days: p.warning_days || 7,
        priority: 100,
        enabled: p.enabled,
        resource_types: p.resource_types || [],
        tag_conditions: tagConds,
        exclude_resource_names: exclNames,
        exclude_tags: exclTags,
        warning_schedule_text: (p.warning_schedule || []).join(','),
        grace_period_days: p.grace_period_days || 0,
        auto_apply: p.auto_apply || false,
      }
      // Expand sections that have data
      collapsedSections.value = {
        basic: false,
        resourceTypes: !(p.resource_types && p.resource_types.length > 0),
        conditions: !tagConds.length,
        exclusions: !(exclNames.length || exclTags.length),
        lifecycle: false,
        safety: false,
      }
    } else if (visible) {
      form.value = defaultForm()
      collapsedSections.value = {
        basic: false,
        resourceTypes: true,
        conditions: true,
        exclusions: true,
        lifecycle: false,
        safety: true,
      }
    }
    errorMsg.value = ''
    matchResult.value = null
    matchExpanded.value = false
    if (visible) {
      // Trigger initial match preview after form is populated
      setTimeout(() => triggerMatchPreview(), 100)
    }
  },
)

function parseWarningSchedule(text: string): number[] | undefined {
  if (!text.trim()) return undefined
  const parts = text.split(',').map(s => s.trim()).filter(s => s !== '')
  const nums = parts.map(Number).filter(n => !isNaN(n) && n > 0)
  return nums.length ? nums.sort((a, b) => b - a) : undefined
}

function submit() {
  if (!form.value.name.trim()) {
    errorMsg.value = 'Name is required'
    return
  }
  if (form.value.ttl_days < 1) {
    errorMsg.value = 'TTL must be at least 1 day'
    return
  }

  // Build tag conditions
  const validConditions = form.value.tag_conditions.filter(c => c.field.trim())
  const conditions = validConditions.length
    ? {
        tags: validConditions.map(c => {
          const tc: TagCondition = { field: `tags.${c.field.trim()}`, operator: c.operator }
          if (!isPresenceOperator(c.operator) && c.value.trim()) {
            tc.value = c.value.trim()
          }
          return tc
        }),
      }
    : undefined

  // Build exclude patterns
  const exclNames = form.value.exclude_resource_names.filter(p => p.trim()).map(p => p.trim())
  const exclTags = form.value.exclude_tags
    .filter(t => t.key.trim())
    .map(t => ({ key: t.key.trim(), value: t.value.trim() || undefined }))
  const exclude_patterns =
    exclNames.length || exclTags.length
      ? { resource_names: exclNames, tags: exclTags }
      : undefined

  const data: PolicyCreateRequest = {
    name: form.value.name.trim(),
    description: form.value.description || undefined,
    ttl_days: form.value.ttl_days,
    warning_days: form.value.warning_days || undefined,
    priority: form.value.priority,
    enabled: form.value.enabled,
    resource_types: form.value.resource_types.length ? form.value.resource_types : undefined,
    conditions,
    exclude_patterns,
    warning_schedule: parseWarningSchedule(form.value.warning_schedule_text),
    grace_period_days: form.value.grace_period_days || undefined,
    auto_apply: form.value.auto_apply,
  }
  emit('submit', data)
}

function cancel() {
  emit('cancel')
}
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
  backdrop-filter: blur(2px);
}

.dialog-box {
  background: var(--surface-card);
  border-radius: 12px;
  padding: 1.5rem;
  width: 680px;
  max-width: 95vw;
  max-height: 90vh;
  overflow-y: auto;
  box-shadow: var(--glow-blue), 0 8px 32px rgba(0, 0, 0, 0.4);
  border: 1px solid var(--surface-border);
}

.dialog-title {
  font-size: 1.15rem;
  font-weight: 600;
  margin-bottom: 1.25rem;
  background: var(--gradient-brand-horizontal);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

/* ---- Collapsible Sections ---- */
.form-section {
  border: 1px solid var(--surface-border);
  border-radius: 8px;
  margin-bottom: 0.75rem;
  overflow: hidden;
  transition: border-color 0.2s;
}

.form-section:hover {
  border-color: rgba(32, 108, 245, 0.3);
}

.form-section .section-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.6rem 0.85rem;
  cursor: pointer;
  user-select: none;
  background: rgba(255, 255, 255, 0.02);
  transition: background 0.15s;
}

.form-section .section-header:hover {
  background: rgba(255, 255, 255, 0.04);
}

.section-icon {
  color: var(--primary-color);
  font-size: 0.85rem;
}

.section-label {
  font-size: 0.85rem;
  font-weight: 600;
  color: var(--text-color);
  flex: 1;
}

.section-badge {
  background: rgba(32, 108, 245, 0.15);
  color: var(--primary-color);
  font-size: 0.7rem;
  font-weight: 600;
  padding: 0.1rem 0.45rem;
  border-radius: 10px;
  min-width: 18px;
  text-align: center;
}

.section-chevron {
  color: var(--text-color-secondary);
  font-size: 0.7rem;
  transition: transform 0.2s;
}

.section-body {
  padding: 0.75rem 0.85rem 0.85rem;
  border-top: 1px solid var(--surface-border);
}

/* ---- Form Groups ---- */
.form-group {
  margin-bottom: 0.85rem;
}

.form-group:last-child {
  margin-bottom: 0;
}

.form-group > label {
  display: block;
  font-size: 0.8rem;
  font-weight: 500;
  color: var(--text-color-secondary);
  margin-bottom: 0.35rem;
}

.required {
  color: var(--color-danger);
}

.form-group input[type="text"],
.form-group input[type="number"],
.form-group select {
  width: 100%;
  padding: 0.5rem 0.75rem;
  border: 1px solid var(--surface-border);
  border-radius: 6px;
  font-size: 0.85rem;
  background: var(--surface-ground);
  color: var(--text-color);
  transition: border-color 0.15s, box-shadow 0.15s;
}

.form-group input:focus,
.form-group select:focus {
  outline: none;
  border-color: var(--primary-color);
  box-shadow: 0 0 0 2px rgba(32, 108, 245, 0.15);
}

.form-row {
  display: flex;
  gap: 0.85rem;
}

.form-row .form-group {
  flex: 1;
}

.form-hint {
  font-size: 0.72rem;
  color: var(--text-color-secondary);
  margin-top: 0.3rem;
  line-height: 1.3;
}

/* ---- Resource Types Grid ---- */
.resource-types-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 0.4rem;
}

.checkbox-item {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.35rem 0.5rem;
  border: 1px solid var(--surface-border);
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.15s;
  background: var(--surface-ground);
}

.checkbox-item:hover {
  border-color: var(--primary-color);
}

.checkbox-item.checked {
  background: rgba(32, 108, 245, 0.15);
  border-color: var(--primary-color);
}

.checkbox-item input[type="checkbox"] {
  display: none;
}

.checkbox-svc-icon {
  font-size: 0.85rem;
  width: 16px;
  text-align: center;
  flex-shrink: 0;
  color: var(--text-color-secondary);
  transition: color 0.15s;
}

.checkbox-item.checked .checkbox-svc-icon {
  color: var(--primary-color);
}

.checkbox-label {
  font-size: 0.78rem;
  color: var(--text-color);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* ---- Dynamic Rows (tag conditions, exclusions) ---- */
.dynamic-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.5rem;
}

.dynamic-field {
  min-width: 0;
}

.dynamic-field input,
.dynamic-field select {
  width: 100%;
  padding: 0.45rem 0.65rem;
  border: 1px solid var(--surface-border);
  border-radius: 6px;
  font-size: 0.82rem;
  background: var(--surface-ground);
  color: var(--text-color);
  transition: border-color 0.15s, box-shadow 0.15s;
}

.dynamic-field input:focus,
.dynamic-field select:focus {
  outline: none;
  border-color: var(--primary-color);
  box-shadow: 0 0 0 2px rgba(32, 108, 245, 0.15);
}

.btn-icon {
  flex-shrink: 0;
  width: 30px;
  height: 30px;
  border: none;
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: background 0.15s, color 0.15s;
  background: transparent;
  color: var(--text-color-secondary);
}

.btn-icon:hover {
  background: rgba(239, 68, 68, 0.1);
  color: #ef4444;
}

.btn-icon-danger {
  color: var(--text-color-secondary);
}

.btn-add {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.35rem 0.7rem;
  border: 1px dashed var(--surface-border);
  border-radius: 6px;
  background: transparent;
  color: var(--primary-color);
  font-size: 0.78rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s;
  margin-top: 0.25rem;
}

.btn-add:hover {
  border-color: var(--primary-color);
  background: rgba(32, 108, 245, 0.05);
}

.btn-add i {
  font-size: 0.7rem;
}

/* ---- Subsections (inside exclusions) ---- */
.subsection {
  margin-bottom: 1rem;
}

.subsection:last-child {
  margin-bottom: 0;
}

.subsection-label {
  display: block;
  font-size: 0.8rem;
  font-weight: 600;
  color: var(--text-color);
  margin-bottom: 0.3rem;
}

/* ---- Toggle Switches ---- */
.toggle-row {
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
}

.toggle-item {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.55rem 0.7rem;
  border: 1px solid var(--surface-border);
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.15s;
  background: var(--surface-ground);
}

.toggle-item:hover {
  border-color: rgba(32, 108, 245, 0.3);
}

.toggle-item.active {
  border-color: rgba(32, 108, 245, 0.3);
  background: rgba(32, 108, 245, 0.05);
}

.toggle-switch {
  flex-shrink: 0;
  width: 36px;
  height: 20px;
  border-radius: 10px;
  background: var(--surface-border);
  position: relative;
  transition: background 0.2s;
  cursor: pointer;
}

.toggle-item.active .toggle-switch {
  background: var(--primary-color);
}

.toggle-knob {
  position: absolute;
  top: 2px;
  left: 2px;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: #fff;
  transition: transform 0.2s;
}

.toggle-knob.on {
  transform: translateX(16px);
}

.toggle-label {
  display: flex;
  flex-direction: column;
  gap: 0.1rem;
}

.toggle-title {
  font-size: 0.82rem;
  font-weight: 500;
  color: var(--text-color);
}

.toggle-desc {
  font-size: 0.7rem;
  color: var(--text-color-secondary);
}

/* ---- Match Preview ---- */
.match-preview-section {
  border: 1px solid var(--surface-border);
  border-radius: 8px;
  margin-bottom: 0.75rem;
  overflow: hidden;
}

.match-preview-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.6rem 0.85rem;
  background: rgba(255, 255, 255, 0.02);
}

.match-preview-header > .pi-search {
  color: var(--primary-color);
  font-size: 0.85rem;
}

.match-count {
  font-size: 0.82rem;
  font-weight: 500;
  color: var(--text-color-secondary);
  flex: 1;
}

.match-count.has-matches {
  color: #4ade80;
}

.match-hint {
  font-size: 0.78rem;
  color: var(--text-color-secondary);
  flex: 1;
}

.match-loading {
  font-size: 0.82rem;
  color: var(--text-color-secondary);
  flex: 1;
  display: flex;
  align-items: center;
  gap: 0.4rem;
}

.match-toggle {
  background: none;
  border: none;
  color: var(--text-color-secondary);
  cursor: pointer;
  padding: 0.2rem 0.4rem;
  border-radius: 4px;
  font-size: 0.7rem;
}

.match-toggle:hover {
  background: var(--surface-ground);
  color: var(--text-color);
}

.match-preview-list {
  border-top: 1px solid var(--surface-border);
  max-height: 200px;
  overflow-y: auto;
}

.match-preview-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.35rem 0.85rem;
  font-size: 0.78rem;
  border-bottom: 1px solid rgba(255, 255, 255, 0.03);
}

.match-preview-item:last-child {
  border-bottom: none;
}

.match-svc {
  background: rgba(32, 108, 245, 0.15);
  color: #5a9aff;
  padding: 0.1rem 0.35rem;
  border-radius: 3px;
  font-size: 0.72rem;
  font-weight: 500;
  flex-shrink: 0;
}

.match-arn {
  flex: 1;
  font-family: var(--font-mono), monospace;
  font-size: 0.72rem;
  color: var(--text-color-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.match-region {
  font-size: 0.72rem;
  color: var(--text-color-secondary);
  flex-shrink: 0;
}

.match-ttl-badge {
  background: rgba(34, 197, 94, 0.15);
  color: #4ade80;
  padding: 0.1rem 0.35rem;
  border-radius: 3px;
  font-size: 0.68rem;
  font-weight: 500;
  flex-shrink: 0;
}

.match-more {
  padding: 0.35rem 0.85rem;
  font-size: 0.75rem;
  color: var(--text-color-secondary);
  text-align: center;
  background: rgba(255, 255, 255, 0.02);
}

/* ---- Error ---- */
.form-error {
  color: #ef4444;
  font-size: 0.8rem;
  margin-bottom: 0.75rem;
  display: flex;
  align-items: center;
  gap: 0.35rem;
}

/* ---- Actions ---- */
.dialog-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.75rem;
  margin-top: 0.75rem;
  padding-top: 0.75rem;
  border-top: 1px solid var(--surface-border);
}

.btn {
  padding: 0.5rem 1.1rem;
  border-radius: 6px;
  font-size: 0.85rem;
  font-weight: 500;
  border: none;
  cursor: pointer;
  transition: all 0.15s;
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
}

.btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.btn-primary {
  background: var(--gradient-brand-horizontal);
  color: white;
}

.btn-primary:hover:not(:disabled) {
  box-shadow: 0 0 12px rgba(32, 108, 245, 0.3);
}

.btn-secondary {
  background: var(--surface-ground);
  color: var(--text-color);
  border: 1px solid var(--surface-border);
}

.btn-secondary:hover {
  background: var(--surface-border);
}

/* ---- Responsive ---- */
@media (max-width: 700px) {
  .dialog-box {
    width: 95vw;
    padding: 1rem;
  }

  .resource-types-grid {
    grid-template-columns: repeat(2, 1fr);
  }

  .form-row {
    flex-direction: column;
    gap: 0;
  }
}
</style>
