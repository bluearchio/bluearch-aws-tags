<template>
  <div class="resource-detail">
    <div class="detail-header">
      <button class="btn btn-secondary" @click="router.back()">
        <i class="pi pi-arrow-left"></i> Back
      </button>
      <router-link
        v-if="resource"
        :to="'/resources/map?resource_arn=' + encodeURIComponent(resource.resource_arn) + '&depth=1'"
        class="btn btn-secondary"
      >
        <i class="pi pi-sitemap"></i> View in Map
      </router-link>
    </div>

    <div v-if="loading" class="detail-loading">Loading resource...</div>
    <div v-else-if="error" class="detail-error">{{ error }}</div>
    <template v-else-if="resource">
      <!-- Overview -->
      <div class="detail-card">
        <h2 class="card-title">Resource Overview</h2>
        <div class="detail-grid">
          <div class="detail-field">
            <span class="field-label">Service</span>
            <span class="field-value">
              <span class="service-badge">{{ resource.service_name }}</span>
            </span>
          </div>
          <div class="detail-field">
            <span class="field-label">Resource Type</span>
            <span class="field-value">{{ resource.resource_type }}</span>
          </div>
          <div class="detail-field">
            <span class="field-label">Resource ID</span>
            <span class="field-value mono">{{ resource.resource_id }}</span>
          </div>
          <div class="detail-field">
            <span class="field-label">Region</span>
            <span class="field-value">{{ resource.region }}</span>
          </div>
          <div class="detail-field">
            <span class="field-label">Account ID</span>
            <span class="field-value mono">{{ resource.account_id }}</span>
          </div>
          <div class="detail-field">
            <span class="field-label">Created By</span>
            <span class="field-value">{{ resource.created_by || '-' }}</span>
          </div>
        </div>
        <div class="detail-field full-width">
          <span class="field-label">ARN</span>
          <span class="field-value mono arn">{{ resource.resource_arn }}</span>
        </div>
      </div>

      <!-- Lifecycle -->
      <div class="detail-card">
        <h2 class="card-title">Lifecycle</h2>
        <div class="detail-grid">
          <div class="detail-field">
            <span class="field-label">State</span>
            <span class="field-value">
              <span class="state-badge" :class="stateClass(resource.lifecycle_state)">
                {{ resource.lifecycle_state || 'unknown' }}
              </span>
            </span>
          </div>
          <div class="detail-field">
            <span class="field-label">Protected</span>
            <span class="field-value">
              <span v-if="resource.protected" class="protected-badge">Yes</span>
              <span v-else>No</span>
            </span>
          </div>
          <div class="detail-field">
            <span class="field-label">Expires At</span>
            <span class="field-value">{{ formatDate(resource.expires_at) }}</span>
          </div>
          <div class="detail-field">
            <span class="field-label">Delete After</span>
            <span class="field-value">{{ formatDate(resource.delete_after) }}</span>
          </div>
          <div class="detail-field">
            <span class="field-label">Compliance Status</span>
            <span class="field-value">{{ resource.compliance_status || '-' }}</span>
          </div>
        </div>
      </div>

      <!-- Dates -->
      <div class="detail-card">
        <h2 class="card-title">Dates</h2>
        <div class="detail-grid">
          <div class="detail-field">
            <span class="field-label">Created At</span>
            <span class="field-value">{{ formatDate(resource.created_at) }}</span>
          </div>
          <div class="detail-field">
            <span class="field-label">Discovered At</span>
            <span class="field-value">{{ formatDate(resource.discovered_at) }}</span>
          </div>
          <div class="detail-field">
            <span class="field-label">Last Scanned</span>
            <span class="field-value">{{ formatDate(resource.last_scanned_at) }}</span>
          </div>
        </div>
      </div>

      <!-- Tags -->
      <div v-if="resource.current_tags && Object.keys(resource.current_tags).length" class="detail-card">
        <div class="card-header">
          <h2 class="card-title">Tags ({{ Object.keys(resource.current_tags).length }})</h2>
          <button
            v-if="resource.current_tags['bluearch:ttl']"
            class="btn btn-danger-outline btn-sm"
            :disabled="removingTags"
            @click="handleRemoveTags"
          >
            <i class="pi pi-times"></i>
            {{ removingTags ? 'Removing...' : 'Remove BlueArch-managed tags' }}
          </button>
        </div>
        <table class="tags-table">
          <thead>
            <tr>
              <th>Key</th>
              <th>Value</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(value, key) in resource.current_tags" :key="key" :class="{ 'tag-managed': String(key).startsWith('bluearch:') }">
              <td class="mono">{{ key }}</td>
              <td>{{ value }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Metadata -->
      <div v-if="resource.metadata && Object.keys(resource.metadata).length" class="detail-card">
        <h2 class="card-title">Metadata</h2>
        <pre class="metadata-json">{{ JSON.stringify(resource.metadata, null, 2) }}</pre>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '@/api/client'
import { useToast } from '@/composables/useToast'
import type { ResourceResponse } from '@/types/api'

const route = useRoute()
const router = useRouter()
const toast = useToast()
const resource = ref<ResourceResponse | null>(null)
const loading = ref(true)
const error = ref<string | null>(null)
const removingTags = ref(false)

function stateClass(state?: string): string {
  const map: Record<string, string> = {
    active: 'state-active',
    warned: 'state-warned',
    marked_for_deletion: 'state-danger',
  }
  return state ? (map[state] || '') : ''
}

function formatDate(dateStr?: string): string {
  if (!dateStr) return '-'
  try {
    return new Date(dateStr).toLocaleString()
  } catch {
    return dateStr
  }
}

async function handleRemoveTags() {
  if (!resource.value) return
  removingTags.value = true
  try {
    const result = await api.removeTagManagerTags([resource.value.id])
    if (result.aws_failed > 0) {
      toast.warning('Tags Removed (partial)', result.details)
    } else {
      toast.success('Tags Removed', result.details)
    }
    // Reload resource
    resource.value = await api.getResource(route.params.id as string)
  } catch {
    // Error toast shown by API client
  } finally {
    removingTags.value = false
  }
}

onMounted(async () => {
  const id = route.params.id as string
  try {
    if (id.startsWith('arn:')) {
      resource.value = await api.getResourceByArn(id)
    } else {
      resource.value = await api.getResource(id)
    }
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Failed to load resource'
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.resource-detail {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.detail-header {
  display: flex;
  align-items: center;
  gap: 1rem;
}

.btn {
  padding: 0.5rem 1rem;
  border: none;
  border-radius: 6px;
  font-size: 0.85rem;
  cursor: pointer;
  font-weight: 500;
  display: flex;
  align-items: center;
  gap: 0.4rem;
}

.btn-secondary {
  background: var(--surface-card);
  color: var(--text-color);
  border: 1px solid var(--surface-border);
}

.btn-secondary:hover {
  background: var(--surface-card-hover);
}

.detail-card {
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 10px;
  padding: 1.25rem;
  transition: border-color 0.3s, box-shadow 0.3s;
}

.detail-card:hover {
  border-color: rgba(32, 108, 245, 0.3);
  box-shadow: var(--glow-blue);
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 1rem;
}

.card-header .card-title {
  margin-bottom: 0;
}

.card-title {
  font-size: 0.95rem;
  font-weight: 600;
  margin-bottom: 1rem;
  background: var(--gradient-brand-horizontal);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.btn-sm {
  padding: 0.35rem 0.75rem;
  font-size: 0.8rem;
}

.btn-danger-outline {
  background: transparent;
  color: #f87171;
  border: 1px solid rgba(239, 68, 68, 0.3);
}

.btn-danger-outline:hover {
  background: rgba(239, 68, 68, 0.12);
}

.btn-danger-outline:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.tag-managed {
  background: rgba(239, 68, 68, 0.05);
}

.tag-managed td:first-child {
  color: #f87171;
}

.detail-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 1rem;
}

.detail-field {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.detail-field.full-width {
  margin-top: 1rem;
}

.field-label {
  font-size: 0.75rem;
  font-weight: 600;
  text-transform: uppercase;
  color: var(--text-color-secondary);
}

.field-value {
  font-size: 0.875rem;
  color: var(--text-color);
}

.mono {
  font-family: 'SF Mono', 'Fira Code', monospace;
  font-size: 0.82rem;
}

.arn {
  word-break: break-all;
}

.service-badge {
  background: rgba(32, 108, 245, 0.12);
  color: #5a9aff;
  padding: 0.2rem 0.5rem;
  border-radius: 4px;
  font-size: 0.78rem;
  font-weight: 500;
}

.state-badge {
  padding: 0.2rem 0.5rem;
  border-radius: 4px;
  font-size: 0.78rem;
  font-weight: 500;
  background: var(--surface-card-hover);
  color: var(--text-color-secondary);
}

.state-active { background: rgba(34, 197, 94, 0.12); color: #4ade80; }
.state-warned { background: rgba(234, 179, 8, 0.12); color: #facc15; }
.state-danger { background: rgba(239, 68, 68, 0.1); color: #f87171; }

.protected-badge {
  background: rgba(124, 58, 237, 0.12);
  color: #a78bfa;
  padding: 0.2rem 0.5rem;
  border-radius: 4px;
  font-size: 0.78rem;
  font-weight: 500;
}

.tags-table {
  width: 100%;
  border-collapse: collapse;
}

.tags-table th {
  text-align: left;
  padding: 0.5rem 0.75rem;
  font-size: 0.75rem;
  font-weight: 600;
  text-transform: uppercase;
  color: var(--text-color-secondary);
  background: var(--surface-ground);
  border-bottom: 1px solid var(--surface-border);
}

.tags-table td {
  padding: 0.5rem 0.75rem;
  font-size: 0.85rem;
  border-bottom: 1px solid var(--surface-border);
}

.metadata-json {
  background: var(--surface-ground);
  color: var(--text-color);
  padding: 1rem;
  border-radius: 6px;
  font-size: 0.82rem;
  font-family: var(--font-mono);
  overflow-x: auto;
  white-space: pre-wrap;
  border: 1px solid var(--surface-border);
}

.detail-loading,
.detail-error {
  padding: 3rem;
  text-align: center;
  color: var(--text-color-secondary);
}

.detail-error {
  color: #f87171;
}
</style>
