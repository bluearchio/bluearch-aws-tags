<template>
  <Teleport to="body">
    <Transition name="panel-slide">
      <div v-if="visible" class="scan-panel" :class="{ expanded }">
        <!-- Collapsed pill -->
        <div v-if="!expanded" class="panel-pill" @click="expanded = true">
          <i class="pi pi-spin pi-spinner pill-spinner" v-if="isRunning"></i>
          <i class="pi pi-check-circle pill-done" v-else-if="isCompleted"></i>
          <i class="pi pi-ban pill-cancelled" v-else-if="isCancelled"></i>
          <i class="pi pi-times-circle pill-failed" v-else></i>
          <span class="pill-text">
            {{ isRunning ? 'Scanning...' : isCompleted ? 'Scan done' : isCancelled ? 'Scan stopped' : 'Scan failed' }}
            <template v-if="scanJob">{{ scanJob.progress }}%</template>
          </span>
          <span v-if="totalResources > 0" class="pill-count">{{ totalResources }} found</span>
        </div>

        <!-- Expanded panel -->
        <div v-else class="panel-expanded">
          <div class="panel-titlebar">
            <span class="panel-title">
              <i class="pi pi-sync"></i>
              Resource Scan
            </span>
            <div class="panel-actions">
              <button v-if="isRunning" class="panel-btn panel-btn-danger" title="Stop scan" @click="stopScan">
                <i class="pi pi-stop-circle"></i>
              </button>
              <button class="panel-btn" title="Minimize" @click="expanded = false">
                <i class="pi pi-minus"></i>
              </button>
              <button class="panel-btn" title="Close" @click="dismiss">
                <i class="pi pi-times"></i>
              </button>
            </div>
          </div>
          <div class="panel-body">
            <JobTracker v-if="scanJob" :job="scanJob" mode="compact" />
            <!-- Post-scan event tracking prompt -->
            <div v-if="showETPrompt" class="et-prompt">
              <div class="et-prompt-icon">
                <i class="pi pi-bolt"></i>
              </div>
              <div class="et-prompt-body">
                <strong>Enable Real-Time Tracking</strong>
                <p>Auto-detect resource changes without re-scanning.</p>
              </div>
              <button class="et-prompt-btn" @click="goToSetup">Set Up</button>
              <button class="et-prompt-dismiss" @click="dismissETPrompt" title="Dismiss">
                <i class="pi pi-times"></i>
              </button>
            </div>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useJobsStore } from '@/stores/jobs'
import { api } from '@/api/client'
import JobTracker from './JobTracker.vue'

const route = useRoute()
const router = useRouter()
const jobsStore = useJobsStore()

const expanded = ref(false)
const dismissed = ref(false)
const etPromptDismissed = ref(false)
const etHasQueues = ref<boolean | null>(null)
let autoDismissTimer: ReturnType<typeof setTimeout> | null = null

const scanJob = computed(() => jobsStore.currentScanJob)

const isRunning = computed(() => {
  return scanJob.value?.status === 'running' || scanJob.value?.status === 'pending'
})

const isCompleted = computed(() => scanJob.value?.status === 'completed')
const isCancelled = computed(() => scanJob.value?.status === 'cancelled')
const isOnLifecycle = computed(() => route.path === '/lifecycle')

const totalResources = computed(() => {
  if (!scanJob.value) return 0
  if (scanJob.value.progress_data?.total_resources) {
    return scanJob.value.progress_data.total_resources
  }
  if (scanJob.value.result?.total_resources) {
    return scanJob.value.result.total_resources as number
  }
  return 0
})

// Show when active scan exists AND not on /lifecycle
const visible = computed(() => {
  if (!scanJob.value) return false
  if (dismissed.value) return false
  if (isOnLifecycle.value) return false
  return true
})

// Watch for scan starting -> expand
watch(
  () => scanJob.value?.status,
  (status, oldStatus) => {
    if (status === 'running' && oldStatus !== 'running') {
      expanded.value = true
      dismissed.value = false
      clearAutoDismiss()
    }
    // Auto-dismiss after completion
    if (status === 'completed' || status === 'failed' || status === 'cancelled') {
      startAutoDismiss()
    }
  },
)

// Reset dismissed when navigating away from lifecycle with an active scan
watch(isOnLifecycle, (val) => {
  if (!val && isRunning.value) {
    dismissed.value = false
  }
})

function dismiss() {
  expanded.value = false
  dismissed.value = true
  clearAutoDismiss()
}

async function stopScan() {
  await jobsStore.cancelScan().catch(() => {})
}

function startAutoDismiss() {
  clearAutoDismiss()
  autoDismissTimer = setTimeout(() => {
    dismissed.value = true
  }, 15000)
}

function clearAutoDismiss() {
  if (autoDismissTimer) {
    clearTimeout(autoDismissTimer)
    autoDismissTimer = null
  }
}

// Event tracking prompt: show after scan completes if ET not deployed
const showETPrompt = computed(() => {
  if (!scanJob.value || scanJob.value.status !== 'completed') return false
  if (etPromptDismissed.value) return false
  if (etHasQueues.value === null) return false // Still loading
  return !etHasQueues.value
})

// Check event tracking status when scan completes
watch(
  () => scanJob.value?.status,
  async (status) => {
    if (status === 'completed' && etHasQueues.value === null) {
      try {
        const etStatus = await api.eventTrackingStatus()
        etHasQueues.value = etStatus.total_queues > 0
      } catch {
        etHasQueues.value = true // Assume deployed on error (don't show prompt)
      }
    }
  },
)

function dismissETPrompt() {
  etPromptDismissed.value = true
}

function goToSetup() {
  etPromptDismissed.value = true
  dismiss()
  router.push('/setup')
}
</script>

<style scoped>
.scan-panel {
  position: fixed;
  bottom: 20px;
  right: 20px;
  z-index: 9999;
}

/* Collapsed pill */
.panel-pill {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 1rem;
  background: #1e293b;
  color: #f1f5f9;
  border-radius: 24px;
  cursor: pointer;
  font-size: 0.8rem;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.2);
  transition: transform 0.15s, box-shadow 0.15s;
  user-select: none;
}

.panel-pill:hover {
  transform: translateY(-1px);
  box-shadow: 0 6px 20px rgba(0, 0, 0, 0.28);
}

.pill-spinner {
  font-size: 0.75rem;
  color: #60a5fa;
}

.pill-done {
  font-size: 0.75rem;
  color: #4ade80;
}

.pill-cancelled {
  font-size: 0.75rem;
  color: #f59e0b;
}

.pill-failed {
  font-size: 0.75rem;
  color: #f87171;
}

.pill-text {
  font-weight: 500;
}

.pill-count {
  background: rgba(255, 255, 255, 0.15);
  padding: 0.15rem 0.45rem;
  border-radius: 10px;
  font-size: 0.72rem;
  font-weight: 600;
}

/* Expanded panel */
.panel-expanded {
  width: 380px;
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 12px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.15);
  overflow: hidden;
}

.panel-titlebar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.6rem 0.85rem;
  background: var(--surface-card-hover);
  border-bottom: 1px solid var(--surface-border);
}

.panel-title {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.82rem;
  font-weight: 600;
  color: var(--text-color);
}

.panel-title i {
  color: var(--primary-color);
  font-size: 0.85rem;
}

.panel-actions {
  display: flex;
  gap: 0.25rem;
}

.panel-btn {
  background: none;
  border: none;
  padding: 0.25rem 0.4rem;
  border-radius: 4px;
  cursor: pointer;
  color: var(--text-color-secondary);
  font-size: 0.78rem;
  transition: all 0.15s;
}

.panel-btn-danger {
  color: #f87171;
}

.panel-btn:hover {
  background: var(--surface-border);
  color: var(--text-color);
}

.panel-body {
  padding: 0.5rem;
}

/* Transition */
.panel-slide-enter-active,
.panel-slide-leave-active {
  transition: opacity 0.25s, transform 0.25s;
}

.panel-slide-enter-from,
.panel-slide-leave-to {
  opacity: 0;
  transform: translateY(16px);
}

/* Event tracking prompt */
.et-prompt {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  margin-top: 0.5rem;
  padding: 0.6rem 0.75rem;
  background: rgba(250, 204, 21, 0.08);
  border: 1px solid rgba(250, 204, 21, 0.2);
  border-radius: 8px;
  position: relative;
}

.et-prompt-icon {
  font-size: 1rem;
  color: #facc15;
  flex-shrink: 0;
}

.et-prompt-body {
  flex: 1;
  min-width: 0;
}

.et-prompt-body strong {
  display: block;
  font-size: 0.78rem;
  color: var(--text-color);
  line-height: 1.3;
}

.et-prompt-body p {
  font-size: 0.7rem;
  color: var(--text-color-secondary);
  margin: 0.1rem 0 0;
  line-height: 1.3;
}

.et-prompt-btn {
  background: linear-gradient(135deg, #facc15, #eab308);
  color: #1e293b;
  border: none;
  border-radius: 6px;
  padding: 0.3rem 0.7rem;
  font-size: 0.72rem;
  font-weight: 700;
  cursor: pointer;
  flex-shrink: 0;
  transition: box-shadow 0.15s;
}

.et-prompt-btn:hover {
  box-shadow: 0 0 10px rgba(250, 204, 21, 0.35);
}

.et-prompt-dismiss {
  background: none;
  border: none;
  color: var(--text-color-secondary);
  font-size: 0.65rem;
  cursor: pointer;
  padding: 0.15rem;
  flex-shrink: 0;
  opacity: 0.6;
  transition: opacity 0.15s;
}

.et-prompt-dismiss:hover {
  opacity: 1;
}

/* Spinner */
@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.pi-spin { animation: spin 1s linear infinite; }
</style>
