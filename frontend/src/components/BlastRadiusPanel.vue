<template>
  <div class="blast-radius-overlay">
    <div class="blast-radius-panel">
      <div class="panel-header">
        <h3><i class="pi pi-bolt"></i> Blast Radius</h3>
        <button class="panel-close" @click="$emit('close')">
          <i class="pi pi-times"></i>
        </button>
      </div>

      <div v-if="loading" class="panel-loading">
        <i class="pi pi-spin pi-spinner"></i> Analyzing impact...
      </div>

      <div v-else-if="error" class="panel-error">
        {{ error }}
      </div>

      <template v-else-if="data">
        <!-- Target -->
        <div class="panel-section">
          <div class="target-info">
            <span class="service-badge" :style="{ background: serviceColor(data.target.service) }">
              {{ data.target.service }}
            </span>
            <span class="target-name">{{ data.target.name }}</span>
          </div>
        </div>

        <!-- Summary -->
        <div class="panel-section summary-section" :class="{ 'has-warning': data.summary.protected_affected > 0 }">
          <div class="summary-stats">
            <div class="stat">
              <span class="stat-value">{{ data.summary.total_affected }}</span>
              <span class="stat-label">affected</span>
            </div>
            <div class="stat">
              <span class="stat-value orphaned">{{ data.summary.orphaned }}</span>
              <span class="stat-label">orphaned</span>
            </div>
            <div class="stat">
              <span class="stat-value cascade">{{ data.summary.cascade }}</span>
              <span class="stat-label">cascade</span>
            </div>
            <div class="stat">
              <span class="stat-value disconnected">{{ data.summary.disconnected }}</span>
              <span class="stat-label">disconn.</span>
            </div>
          </div>
          <div v-if="data.summary.protected_affected > 0" class="protected-warning">
            <i class="pi pi-exclamation-triangle"></i>
            {{ data.summary.protected_affected }} protected resource(s) affected
          </div>
        </div>

        <!-- Affected resources -->
        <div class="panel-section" v-if="data.affected.length">
          <h4>Affected Resources</h4>
          <div class="resource-list">
            <div
              v-for="item in data.affected"
              :key="item.arn"
              class="resource-row"
              @click="$emit('focus', item.arn)"
            >
              <span class="impact-badge" :class="'impact-' + item.impact">
                {{ item.impact.toUpperCase() }}
              </span>
              <span class="service-badge small" :style="{ background: serviceColor(item.service) }">
                {{ item.service }}
              </span>
              <span class="resource-name">{{ item.name }}</span>
              <span class="rel-type">{{ item.relationship }}</span>
            </div>
          </div>
          <div v-if="data.truncated" class="truncation-note">
            Results truncated. Some affected resources not shown.
          </div>
        </div>

        <!-- No affected -->
        <div v-else class="panel-section empty-section">
          <p>No dependent resources found. Safe to delete.</p>
        </div>

        <!-- Dependencies -->
        <div class="panel-section" v-if="data.dependencies.length">
          <h4>Dependencies (outgoing)</h4>
          <div class="resource-list">
            <div
              v-for="dep in data.dependencies"
              :key="dep.arn"
              class="resource-row dep-row"
              @click="$emit('focus', dep.arn)"
            >
              <span class="service-badge small" :style="{ background: serviceColor(dep.service) }">
                {{ dep.service }}
              </span>
              <span class="resource-name">{{ dep.name }}</span>
              <span class="rel-type">{{ dep.relationship }}</span>
            </div>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { api } from '@/api/client'
import type { BlastRadiusResponse } from '@/types/api'

const props = defineProps<{
  arn: string
}>()

defineEmits<{
  close: []
  focus: [arn: string]
}>()

const data = ref<BlastRadiusResponse | null>(null)
const loading = ref(true)
const error = ref<string | null>(null)

const SERVICE_COLORS: Record<string, string> = {
  ec2: '#f97316', s3: '#22c55e', lambda: '#a855f7', rds: '#3b82f6',
  dynamodb: '#f59e0b', ecs: '#14b8a6', elb: '#06b6d4', elbv2: '#06b6d4',
  sns: '#e11d48', sqs: '#8b5cf6', cloudwatch: '#ef4444', logs: '#ef4444',
  eks: '#0ea5e9', elasticache: '#dc2626', vpc: '#6b7280', subnet: '#9ca3af',
  sg: '#4b5563', iam: '#eab308',
}

function serviceColor(svc: string): string {
  return SERVICE_COLORS[svc] || '#6b7280'
}

onMounted(async () => {
  try {
    data.value = await api.blastRadius(props.arn)
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Failed to analyze blast radius'
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.blast-radius-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.4);
  z-index: 1000;
  display: flex;
  justify-content: flex-end;
}

.blast-radius-panel {
  width: 400px;
  max-width: 90vw;
  background: var(--surface-card);
  border-left: 1px solid var(--surface-border);
  display: flex;
  flex-direction: column;
  overflow-y: auto;
  box-shadow: -4px 0 20px rgba(0, 0, 0, 0.3);
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 1rem 1.25rem;
  border-bottom: 1px solid var(--surface-border);
  flex-shrink: 0;
}

.panel-header h3 {
  margin: 0;
  font-size: 1rem;
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  color: var(--text-color);
}

.panel-header h3 i {
  color: #f59e0b;
}

.panel-close {
  background: none;
  border: none;
  color: var(--text-color-secondary);
  cursor: pointer;
  padding: 4px;
  border-radius: 4px;
}

.panel-close:hover {
  background: var(--surface-hover);
  color: var(--text-color);
}

.panel-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  padding: 3rem 1rem;
  color: var(--text-color-secondary);
  font-size: 0.9rem;
}

.panel-error {
  padding: 1.5rem 1.25rem;
  color: #f87171;
  font-size: 0.85rem;
}

.panel-section {
  padding: 1rem 1.25rem;
  border-bottom: 1px solid var(--surface-border);
}

.panel-section h4 {
  margin: 0 0 0.75rem 0;
  font-size: 0.8rem;
  font-weight: 600;
  text-transform: uppercase;
  color: var(--text-color-secondary);
}

.target-info {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.target-name {
  font-size: 0.9rem;
  font-weight: 500;
  color: var(--text-color);
  word-break: break-all;
}

.service-badge {
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 0.72rem;
  font-weight: 600;
  color: #fff;
  text-transform: uppercase;
  flex-shrink: 0;
}

.service-badge.small {
  padding: 1px 6px;
  font-size: 0.65rem;
}

.summary-section {
  background: var(--surface-ground);
}

.summary-section.has-warning {
  background: rgba(239, 68, 68, 0.05);
  border-color: rgba(239, 68, 68, 0.2);
}

.summary-stats {
  display: flex;
  gap: 0.75rem;
}

.stat {
  display: flex;
  flex-direction: column;
  align-items: center;
  flex: 1;
}

.stat-value {
  font-size: 1.25rem;
  font-weight: 700;
  color: var(--text-color);
}

.stat-value.orphaned { color: #ef4444; }
.stat-value.cascade { color: #f59e0b; }
.stat-value.disconnected { color: #6b7280; }

.stat-label {
  font-size: 0.7rem;
  color: var(--text-color-secondary);
  text-transform: uppercase;
}

.protected-warning {
  margin-top: 0.75rem;
  padding: 0.5rem 0.75rem;
  background: rgba(239, 68, 68, 0.1);
  border: 1px solid rgba(239, 68, 68, 0.3);
  border-radius: 6px;
  color: #f87171;
  font-size: 0.8rem;
  display: flex;
  align-items: center;
  gap: 0.4rem;
}

.resource-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.resource-row {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.4rem 0.5rem;
  border-radius: 4px;
  cursor: pointer;
  font-size: 0.8rem;
  transition: background 0.1s;
}

.resource-row:hover {
  background: var(--surface-hover);
}

.dep-row {
  opacity: 0.8;
}

.impact-badge {
  padding: 1px 6px;
  border-radius: 3px;
  font-size: 0.6rem;
  font-weight: 700;
  flex-shrink: 0;
}

.impact-orphaned {
  background: rgba(239, 68, 68, 0.15);
  color: #ef4444;
}

.impact-cascade {
  background: rgba(245, 158, 11, 0.15);
  color: #f59e0b;
}

.impact-disconnected {
  background: rgba(107, 114, 128, 0.15);
  color: #6b7280;
}

.resource-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-color);
  font-family: monospace;
  font-size: 0.75rem;
}

.rel-type {
  font-size: 0.65rem;
  color: var(--text-color-secondary);
  opacity: 0.7;
  flex-shrink: 0;
  text-transform: uppercase;
}

.truncation-note {
  margin-top: 0.5rem;
  padding: 0.4rem 0.6rem;
  background: rgba(245, 158, 11, 0.1);
  border-radius: 4px;
  font-size: 0.75rem;
  color: #f59e0b;
}

.empty-section p {
  margin: 0;
  font-size: 0.85rem;
  color: var(--text-color-secondary);
}
</style>
