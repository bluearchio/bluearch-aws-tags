<template>
  <div v-if="visible" class="dialog-overlay" @click.self="cancel">
    <div class="dialog-box">
      <h3 class="dialog-title">{{ editPolicy ? 'Edit Tag Policy' : 'New Tag Policy' }}</h3>
      <form @submit.prevent="submit">
        <div class="form-group">
          <label>Name</label>
          <input v-model="form.name" type="text" required placeholder="e.g. enforce-environment" />
        </div>
        <div class="form-group">
          <label>Description</label>
          <input v-model="form.description" type="text" placeholder="Optional description" />
        </div>
        <div class="form-group">
          <label>Template</label>
          <select v-model="selectedTemplate" @change="applyTemplate">
            <option value="custom">Custom</option>
            <optgroup label="Cost Allocation">
              <option value="enforce-environment">Enforce Environment values</option>
              <option value="require-costcenter">Require CostCenter tag</option>
              <option value="require-project">Require Project tag</option>
              <option value="require-department">Require Department tag</option>
            </optgroup>
            <optgroup label="Ownership &amp; Accountability">
              <option value="require-owner">Require Owner tag</option>
              <option value="require-team">Require Team tag</option>
              <option value="require-application">Require Application tag</option>
            </optgroup>
            <optgroup label="Security &amp; Compliance">
              <option value="enforce-data-classification">Enforce DataClassification values</option>
              <option value="enforce-compliance">Enforce Compliance framework</option>
              <option value="require-backup">Require Backup policy tag</option>
            </optgroup>
            <optgroup label="Operations">
              <option value="enforce-automation">Enforce Automation eligibility</option>
              <option value="require-expiry">Require Expiry date tag</option>
            </optgroup>
          </select>
        </div>
        <div class="form-group">
          <label>JSON Content</label>
          <textarea
            v-model="contentText"
            class="json-editor"
            rows="12"
            placeholder='{"tags":{"TagKey":{"tag_key":{"@@assign":"TagKey"}}}}'
          ></textarea>
          <div class="json-toolbar">
            <button type="button" class="btn btn-secondary btn-sm" @click="validateJson">
              <i class="pi pi-check"></i> Validate JSON
            </button>
            <span v-if="jsonStatus === 'valid'" class="json-valid">Valid JSON</span>
            <span v-if="jsonStatus === 'invalid'" class="json-invalid">{{ jsonError }}</span>
          </div>
        </div>
        <div v-if="errorMsg" class="form-error">{{ errorMsg }}</div>
        <div class="dialog-actions">
          <button type="button" class="btn btn-secondary" @click="cancel">Cancel</button>
          <button type="submit" class="btn btn-primary" :disabled="submitting">
            {{ submitting ? 'Saving...' : (editPolicy ? 'Update' : 'Create') }}
          </button>
        </div>
      </form>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import type { OrgPolicyDetailResponse, OrgPolicyCreateRequest } from '@/types/api'

const TEMPLATES: Record<string, { content: Record<string, unknown>; name: string; description: string }> = {
  // -- Cost Allocation --
  'enforce-environment': {
    name: 'enforce-environment',
    description: 'Enforce Environment tag with allowed values on all compute and storage',
    content: {
      tags: {
        Environment: {
          tag_key: { '@@assign': 'Environment' },
          tag_value: { '@@assign': ['production', 'staging', 'development', 'testing', 'sandbox'] },
          enforced_for: { '@@assign': ['ec2:instance', 'ec2:volume', 'rds:ALL_SUPPORTED', 's3:bucket', 'lambda:function'] },
        },
      },
    },
  },
  'require-costcenter': {
    name: 'require-costcenter',
    description: 'Require CostCenter tag on billable resources for chargeback',
    content: {
      tags: {
        CostCenter: {
          tag_key: { '@@assign': 'CostCenter' },
          enforced_for: { '@@assign': ['ec2:instance', 'ec2:volume', 'rds:ALL_SUPPORTED', 's3:bucket', 'lambda:function', 'elasticloadbalancing:loadbalancer'] },
        },
      },
    },
  },
  'require-project': {
    name: 'require-project',
    description: 'Require Project tag for resource grouping and cost tracking',
    content: {
      tags: {
        Project: {
          tag_key: { '@@assign': 'Project' },
          enforced_for: { '@@assign': ['ec2:instance', 'ec2:volume', 'rds:ALL_SUPPORTED', 's3:bucket', 'lambda:function'] },
        },
      },
    },
  },
  'require-department': {
    name: 'require-department',
    description: 'Require Department tag for organizational cost allocation',
    content: {
      tags: {
        Department: {
          tag_key: { '@@assign': 'Department' },
          enforced_for: { '@@assign': ['ec2:instance', 'rds:ALL_SUPPORTED', 's3:bucket', 'lambda:function'] },
        },
      },
    },
  },
  // -- Ownership & Accountability --
  'require-owner': {
    name: 'require-owner',
    description: 'Require Owner tag (email) on all compute resources',
    content: {
      tags: {
        Owner: {
          tag_key: { '@@assign': 'Owner' },
          enforced_for: { '@@assign': ['ec2:instance', 'ec2:volume', 'rds:ALL_SUPPORTED', 'lambda:function', 'ecs:service'] },
        },
      },
    },
  },
  'require-team': {
    name: 'require-team',
    description: 'Require Team tag for shared ownership and escalation routing',
    content: {
      tags: {
        Team: {
          tag_key: { '@@assign': 'Team' },
          enforced_for: { '@@assign': ['ec2:instance', 'rds:ALL_SUPPORTED', 's3:bucket', 'lambda:function'] },
        },
      },
    },
  },
  'require-application': {
    name: 'require-application',
    description: 'Require Application tag to associate resources with apps',
    content: {
      tags: {
        Application: {
          tag_key: { '@@assign': 'Application' },
          enforced_for: { '@@assign': ['ec2:instance', 'ec2:volume', 'rds:ALL_SUPPORTED', 's3:bucket', 'lambda:function', 'elasticloadbalancing:loadbalancer'] },
        },
      },
    },
  },
  // -- Security & Compliance --
  'enforce-data-classification': {
    name: 'enforce-data-classification',
    description: 'Enforce DataClassification on storage and databases',
    content: {
      tags: {
        DataClassification: {
          tag_key: { '@@assign': 'DataClassification' },
          tag_value: { '@@assign': ['public', 'internal', 'confidential', 'restricted'] },
          enforced_for: { '@@assign': ['s3:bucket', 'rds:ALL_SUPPORTED', 'dynamodb:table', 'ec2:volume'] },
        },
      },
    },
  },
  'enforce-compliance': {
    name: 'enforce-compliance',
    description: 'Enforce Compliance framework tag on regulated resources',
    content: {
      tags: {
        Compliance: {
          tag_key: { '@@assign': 'Compliance' },
          tag_value: { '@@assign': ['hipaa', 'pci-dss', 'soc2', 'gdpr', 'none'] },
          enforced_for: { '@@assign': ['s3:bucket', 'rds:ALL_SUPPORTED', 'dynamodb:table', 'ec2:instance'] },
        },
      },
    },
  },
  'require-backup': {
    name: 'require-backup',
    description: 'Require BackupPolicy tag on databases and volumes',
    content: {
      tags: {
        BackupPolicy: {
          tag_key: { '@@assign': 'BackupPolicy' },
          tag_value: { '@@assign': ['daily', 'weekly', 'monthly', 'none'] },
          enforced_for: { '@@assign': ['rds:ALL_SUPPORTED', 'ec2:volume', 'dynamodb:table'] },
        },
      },
    },
  },
  // -- Operations --
  'enforce-automation': {
    name: 'enforce-automation',
    description: 'Enforce AutoStop eligibility for non-production instances',
    content: {
      tags: {
        AutoStop: {
          tag_key: { '@@assign': 'AutoStop' },
          tag_value: { '@@assign': ['true', 'false'] },
          enforced_for: { '@@assign': ['ec2:instance', 'rds:ALL_SUPPORTED'] },
        },
      },
    },
  },
  'require-expiry': {
    name: 'require-expiry',
    description: 'Require ExpiryDate tag for temporary resources',
    content: {
      tags: {
        ExpiryDate: {
          tag_key: { '@@assign': 'ExpiryDate' },
          enforced_for: { '@@assign': ['ec2:instance', 'ec2:volume', 'rds:ALL_SUPPORTED'] },
        },
      },
    },
  },
}

const props = defineProps<{
  visible: boolean
  editPolicy?: OrgPolicyDetailResponse | null
}>()

const emit = defineEmits<{
  submit: [data: OrgPolicyCreateRequest]
  cancel: []
}>()

const form = ref({ name: '', description: '' })
const contentText = ref('')
const selectedTemplate = ref('custom')
const jsonStatus = ref<'valid' | 'invalid' | ''>('')
const jsonError = ref('')
const errorMsg = ref('')
const submitting = ref(false)

function resetForm(): void {
  form.value = { name: '', description: '' }
  contentText.value = ''
  selectedTemplate.value = 'custom'
  jsonStatus.value = ''
  jsonError.value = ''
  errorMsg.value = ''
  submitting.value = false
}

function populateFromPolicy(policy: OrgPolicyDetailResponse): void {
  form.value = {
    name: policy.name,
    description: policy.description || '',
  }
  if (policy.content) {
    contentText.value = JSON.stringify(policy.content, null, 2)
  } else {
    contentText.value = ''
  }
  selectedTemplate.value = 'custom'
  jsonStatus.value = ''
  jsonError.value = ''
  errorMsg.value = ''
  submitting.value = false
}

watch(
  () => props.visible,
  (visible) => {
    if (visible && props.editPolicy) {
      populateFromPolicy(props.editPolicy)
    } else if (visible) {
      resetForm()
    }
  },
)

function applyTemplate(): void {
  const template = TEMPLATES[selectedTemplate.value]
  if (template) {
    contentText.value = JSON.stringify(template.content, null, 2)
    if (!form.value.name) form.value.name = template.name
    if (!form.value.description) form.value.description = template.description
  }
  jsonStatus.value = ''
  jsonError.value = ''
}

function validateJson(): boolean {
  if (!contentText.value.trim()) {
    jsonStatus.value = 'invalid'
    jsonError.value = 'Content is required'
    return false
  }
  try {
    JSON.parse(contentText.value)
    jsonStatus.value = 'valid'
    jsonError.value = ''
    return true
  } catch (e) {
    jsonStatus.value = 'invalid'
    jsonError.value = e instanceof SyntaxError ? e.message : 'Invalid JSON'
    return false
  }
}

function submit(): void {
  errorMsg.value = ''
  if (!form.value.name.trim()) {
    errorMsg.value = 'Name is required'
    return
  }
  if (!validateJson()) {
    errorMsg.value = 'Please fix the JSON content before submitting'
    return
  }
  const data: OrgPolicyCreateRequest = {
    name: form.value.name.trim(),
    description: form.value.description || undefined,
    content: JSON.parse(contentText.value),
  }
  emit('submit', data)
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
  width: 620px;
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

.form-group {
  margin-bottom: 1rem;
}

.form-group label {
  display: block;
  font-size: 0.8rem;
  font-weight: 500;
  color: var(--text-color-secondary);
  margin-bottom: 0.35rem;
}

.form-group input[type="text"],
.form-group select {
  width: 100%;
  padding: 0.5rem 0.75rem;
  border: 1px solid var(--surface-border);
  border-radius: 6px;
  font-size: 0.875rem;
  background: var(--surface-ground);
  color: var(--text-color);
}

.form-group input:focus,
.form-group select:focus,
.json-editor:focus {
  outline: none;
  border-color: var(--primary-color);
  box-shadow: 0 0 0 2px rgba(32, 108, 245, 0.15);
}

.json-editor {
  width: 100%;
  padding: 0.75rem;
  border: 1px solid var(--surface-border);
  border-radius: 6px;
  font-family: 'SF Mono', 'Fira Code', 'Cascadia Code', monospace;
  font-size: 0.8rem;
  background: var(--surface-ground);
  color: var(--text-color);
  resize: vertical;
  line-height: 1.5;
  tab-size: 2;
}

.json-toolbar {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  margin-top: 0.5rem;
}

.json-valid {
  font-size: 0.78rem;
  font-weight: 500;
  color: #4ade80;
}

.json-invalid {
  font-size: 0.78rem;
  font-weight: 500;
  color: #f87171;
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
  box-shadow: 0 0 16px rgba(32, 108, 245, 0.4);
  transform: scale(1.02);
}

.btn-secondary {
  background: var(--surface-ground);
  color: var(--text-color);
  border: 1px solid var(--surface-border);
}

.btn-secondary:hover {
  background: var(--surface-border);
}

.btn-sm {
  padding: 0.3rem 0.6rem;
  font-size: 0.78rem;
}
</style>
