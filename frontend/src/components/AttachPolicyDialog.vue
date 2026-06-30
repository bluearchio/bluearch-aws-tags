<template>
  <div v-if="visible" class="dialog-overlay" @click.self="cancel">
    <div class="dialog-box">
      <h3 class="dialog-title">Attach Policy to Targets</h3>

      <div v-if="loading" class="dialog-loading">
        <i class="pi pi-spin pi-spinner"></i> Loading organization structure...
      </div>

      <div v-else-if="!complianceStore.orgStructure" class="dialog-empty">
        Failed to load organization structure.
      </div>

      <div v-else class="org-tree">
        <!-- Root -->
        <div v-if="complianceStore.orgStructure.root_id" class="tree-item root-item">
          <span class="tree-label">
            <i class="pi pi-globe"></i>
            Root
          </span>
          <span class="tree-id">{{ complianceStore.orgStructure.root_id }}</span>
          <button
            v-if="isAlreadyAttached(complianceStore.orgStructure.root_id)"
            class="btn btn-secondary btn-xs"
            disabled
          >
            Attached
          </button>
          <button
            v-else
            class="btn btn-primary btn-xs"
            :disabled="attaching === complianceStore.orgStructure.root_id"
            @click="handleAttach(complianceStore.orgStructure.root_id)"
          >
            {{ attaching === complianceStore.orgStructure.root_id ? 'Attaching...' : 'Attach' }}
          </button>
        </div>

        <!-- OUs -->
        <div
          v-for="ou in complianceStore.orgStructure.ous"
          :key="String(ou.id || ou.Id)"
          class="tree-item ou-item"
        >
          <span class="tree-label">
            <i class="pi pi-sitemap"></i>
            {{ ou.name || ou.Name || 'OU' }}
          </span>
          <span class="tree-id">{{ ou.id || ou.Id }}</span>
          <button
            v-if="isAlreadyAttached(String(ou.id || ou.Id))"
            class="btn btn-secondary btn-xs"
            disabled
          >
            Attached
          </button>
          <button
            v-else
            class="btn btn-primary btn-xs"
            :disabled="attaching === String(ou.id || ou.Id)"
            @click="handleAttach(String(ou.id || ou.Id))"
          >
            {{ attaching === String(ou.id || ou.Id) ? 'Attaching...' : 'Attach' }}
          </button>
        </div>

        <!-- Accounts -->
        <div
          v-for="acct in complianceStore.orgStructure.accounts"
          :key="String(acct.id || acct.Id)"
          class="tree-item account-item"
        >
          <span class="tree-label">
            <i class="pi pi-user"></i>
            {{ acct.name || acct.Name || 'Account' }}
          </span>
          <span class="tree-id">{{ acct.id || acct.Id }}</span>
          <button
            v-if="isAlreadyAttached(String(acct.id || acct.Id))"
            class="btn btn-secondary btn-xs"
            disabled
          >
            Attached
          </button>
          <button
            v-else
            class="btn btn-primary btn-xs"
            :disabled="attaching === String(acct.id || acct.Id)"
            @click="handleAttach(String(acct.id || acct.Id))"
          >
            {{ attaching === String(acct.id || acct.Id) ? 'Attaching...' : 'Attach' }}
          </button>
        </div>
      </div>

      <div v-if="errorMsg" class="form-error">{{ errorMsg }}</div>

      <div class="dialog-actions">
        <button class="btn btn-secondary" @click="cancel">Close</button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { useComplianceStore } from '@/stores/compliance'

const props = defineProps<{
  visible: boolean
  policyId: string
  currentTargets?: Record<string, unknown>[]
}>()

const emit = defineEmits<{
  attach: [targetId: string]
  cancel: []
}>()

const complianceStore = useComplianceStore()
const loading = ref(false)
const attaching = ref('')
const errorMsg = ref('')

watch(
  () => props.visible,
  async (visible) => {
    if (visible) {
      loading.value = true
      errorMsg.value = ''
      attaching.value = ''
      await complianceStore.fetchOrgStructure()
      loading.value = false
    }
  },
)

function isAlreadyAttached(targetId: string): boolean {
  if (!props.currentTargets) return false
  return props.currentTargets.some(
    (t) => String(t.target_id || t.TargetId || t.id || '') === targetId,
  )
}

async function handleAttach(targetId: string): Promise<void> {
  attaching.value = targetId
  errorMsg.value = ''
  try {
    emit('attach', targetId)
  } finally {
    attaching.value = ''
  }
}

function cancel(): void {
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
}

.dialog-box {
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 10px;
  padding: 1.5rem;
  width: 560px;
  max-width: 90vw;
  max-height: 90vh;
  overflow-y: auto;
  box-shadow: var(--glow-blue), 0 8px 32px rgba(0, 0, 0, 0.4);
}

.dialog-title {
  font-size: 1.1rem;
  font-weight: 600;
  margin-bottom: 1.25rem;
  background: var(--gradient-brand-horizontal);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.dialog-loading,
.dialog-empty {
  padding: 2rem;
  text-align: center;
  color: var(--text-color-secondary);
  font-size: 0.875rem;
}

.dialog-loading i {
  margin-right: 0.5rem;
}

.org-tree {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  margin-bottom: 1rem;
  max-height: 400px;
  overflow-y: auto;
}

.tree-item {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.5rem 0.75rem;
  border: 1px solid var(--surface-border);
  border-radius: 6px;
  background: var(--surface-ground);
}

.tree-item.ou-item {
  margin-left: 1.25rem;
}

.tree-item.account-item {
  margin-left: 2.5rem;
}

.tree-label {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.85rem;
  font-weight: 500;
  color: var(--text-color);
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tree-label i {
  font-size: 0.85rem;
  color: var(--text-color-secondary);
  flex-shrink: 0;
}

.tree-id {
  font-family: 'SF Mono', monospace;
  font-size: 0.72rem;
  color: var(--text-color-secondary);
  flex-shrink: 0;
}

.form-error {
  color: #ef4444;
  font-size: 0.8rem;
  margin-bottom: 0.75rem;
}

.dialog-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.75rem;
  margin-top: 0.5rem;
}

.btn {
  padding: 0.5rem 1rem;
  border-radius: 6px;
  font-size: 0.85rem;
  font-weight: 500;
  border: none;
  cursor: pointer;
  transition: background 0.15s;
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
  box-shadow: 0 0 12px rgba(32, 108, 245, 0.4);
}

.btn-secondary {
  background: var(--surface-ground);
  color: var(--text-color);
  border: 1px solid var(--surface-border);
}

.btn-secondary:hover:not(:disabled) {
  background: var(--surface-border);
}

.btn-xs {
  padding: 0.2rem 0.5rem;
  font-size: 0.75rem;
  flex-shrink: 0;
}
</style>
