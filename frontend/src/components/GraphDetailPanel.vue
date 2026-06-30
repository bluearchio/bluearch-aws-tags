<template>
  <div class="detail-panel" v-if="node">
    <div class="panel-header">
      <h3>{{ node.name || node.resource_id }}</h3>
      <button class="panel-close" @click="$emit('close')">
        <i class="pi pi-times"></i>
      </button>
    </div>
    <div class="panel-body">
      <div class="panel-field">
        <span class="field-label">Service</span>
        <span class="service-badge" :style="{ background: serviceColor }">{{ node.service_name }}</span>
      </div>
      <div class="panel-field">
        <span class="field-label">Type</span>
        <span class="field-value">{{ node.resource_type }}</span>
      </div>
      <div class="panel-field">
        <span class="field-label">Region</span>
        <span class="field-value">{{ node.region }}</span>
      </div>
      <div class="panel-field">
        <span class="field-label">Account</span>
        <span class="field-value mono">{{ node.account_id }}</span>
      </div>
      <div class="panel-field" v-if="node.lifecycle_state">
        <span class="field-label">State</span>
        <span class="state-badge" :class="'state-' + node.lifecycle_state">{{ node.lifecycle_state }}</span>
      </div>
      <div class="panel-field" v-if="node.compliance_status">
        <span class="field-label">Compliance</span>
        <span class="state-badge" :class="'compliance-' + node.compliance_status">{{ node.compliance_status }}</span>
      </div>
      <div class="panel-field" v-if="node.missing_tags?.length">
        <span class="field-label">Missing Tags</span>
        <span class="field-value">{{ node.missing_tags.join(', ') }}</span>
      </div>
      <div class="panel-field" v-if="node.protected">
        <span class="field-label">Protected</span>
        <span class="state-badge state-protected">Yes</span>
      </div>
      <div class="panel-field">
        <span class="field-label">Connections</span>
        <span class="field-value">{{ connectionCount }}</span>
      </div>
      <div class="panel-arn">
        <span class="field-label">ARN</span>
        <span class="field-value mono arn-text">{{ node.id }}</span>
      </div>
      <div class="panel-actions">
        <button class="btn btn-sm btn-primary" @click="$emit('focus', node.id)">
          <i class="pi pi-search"></i> Focus Graph
        </button>
        <button class="btn btn-sm btn-warning" @click="$emit('blast-radius', node.id)">
          <i class="pi pi-bolt"></i> Blast Radius
        </button>
        <router-link
          v-if="node.lifecycle_state && node.lifecycle_state !== 'infrastructure'"
          :to="resourceDetailPath"
          class="btn btn-sm btn-secondary"
        >
          <i class="pi pi-external-link"></i> View Resource
        </router-link>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { GraphNodeResponse, GraphEdgeResponse } from '@/types/api'

const props = defineProps<{
  node: GraphNodeResponse | null
  edges: GraphEdgeResponse[]
}>()

defineEmits<{
  close: []
  focus: [arn: string]
  'blast-radius': [arn: string]
}>()

const SERVICE_COLORS: Record<string, string> = {
  ec2: '#f97316', s3: '#22c55e', lambda: '#a855f7', rds: '#3b82f6',
  dynamodb: '#f59e0b', ecs: '#14b8a6', elb: '#06b6d4', elbv2: '#06b6d4',
  sns: '#e11d48', sqs: '#8b5cf6', cloudwatch: '#ef4444', logs: '#ef4444',
  eks: '#0ea5e9', elasticache: '#dc2626', vpc: '#6b7280', subnet: '#9ca3af',
  sg: '#4b5563', iam: '#eab308',
}

const serviceColor = computed(() => SERVICE_COLORS[props.node?.service_name ?? ''] ?? '#6b7280')

const connectionCount = computed(() => {
  if (!props.node) return 0
  return props.edges.filter(
    e => e.source === props.node!.id || e.target === props.node!.id
  ).length
})

const resourceDetailPath = computed(() => {
  if (!props.node) return '/resources'
  return `/resources/${encodeURIComponent(props.node.id)}`
})
</script>

<style scoped>
.detail-panel {
  width: 320px;
  background: var(--surface-card);
  border-left: 1px solid var(--surface-border);
  display: flex;
  flex-direction: column;
  overflow-y: auto;
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 1rem;
  border-bottom: 1px solid var(--surface-border);
}

.panel-header h3 {
  margin: 0;
  font-size: 0.95rem;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 250px;
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

.panel-body {
  padding: 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.panel-field {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
}

.field-label {
  font-size: 0.8rem;
  color: var(--text-color-secondary);
  flex-shrink: 0;
}

.field-value {
  font-size: 0.85rem;
  text-align: right;
}

.mono {
  font-family: monospace;
  font-size: 0.8rem;
}

.service-badge {
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 0.75rem;
  font-weight: 600;
  color: #fff;
  text-transform: uppercase;
}

.state-badge {
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 0.75rem;
  font-weight: 600;
}

.state-active { background: rgba(34, 197, 94, 0.15); color: #22c55e; }
.state-warned { background: rgba(245, 158, 11, 0.15); color: #f59e0b; }
.state-infrastructure { background: rgba(107, 114, 128, 0.15); color: #9ca3af; }
.state-expired { background: rgba(239, 68, 68, 0.15); color: #ef4444; }
.state-marked_for_deletion { background: rgba(239, 68, 68, 0.15); color: #ef4444; }

.panel-arn {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding-top: 0.5rem;
  border-top: 1px solid var(--surface-border);
}

.arn-text {
  font-size: 0.7rem;
  word-break: break-all;
  color: var(--text-color-secondary);
}

.panel-actions {
  display: flex;
  gap: 0.5rem;
  padding-top: 0.75rem;
  border-top: 1px solid var(--surface-border);
}

.btn {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.4rem 0.75rem;
  border-radius: 6px;
  font-size: 0.8rem;
  cursor: pointer;
  border: 1px solid transparent;
  text-decoration: none;
  white-space: nowrap;
}

.btn-sm { font-size: 0.78rem; padding: 0.35rem 0.65rem; }
.btn-primary { background: var(--primary-color); color: #fff; border-color: var(--primary-color); }
.btn-primary:hover { opacity: 0.9; }
.btn-secondary { background: var(--surface-hover); color: var(--text-color); border-color: var(--surface-border); }
.btn-secondary:hover { background: var(--surface-ground); }
.btn-warning { background: rgba(245, 158, 11, 0.15); color: #f59e0b; border-color: rgba(245, 158, 11, 0.3); }
.btn-warning:hover { background: rgba(245, 158, 11, 0.25); }
.compliance-compliant { background: rgba(34, 197, 94, 0.15); color: #22c55e; }
.compliance-noncompliant { background: rgba(239, 68, 68, 0.15); color: #ef4444; }
.state-protected { background: rgba(99, 102, 241, 0.15); color: #6366f1; }
</style>
