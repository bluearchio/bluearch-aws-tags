<template>
  <div v-if="showBanner" class="permission-banner" :class="bannerClass">
    <i class="pi pi-exclamation-triangle banner-icon"></i>
    <div class="banner-content">
      <strong>{{ title }}</strong>
      <span>{{ message }}</span>
    </div>
    <router-link to="/setup" class="banner-link">View Setup</router-link>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { usePermissionStore } from '@/stores/permissions'

const props = defineProps<{
  feature: string
}>()

const permissionStore = usePermissionStore()

const status = computed(() => permissionStore.featureStatus(props.feature))

const showBanner = computed(() => {
  if (!status.value) return false
  return !status.value.available || status.value.partial
})

const bannerClass = computed(() => ({
  'banner-unavailable': status.value && !status.value.available && !status.value.partial,
  'banner-partial': status.value?.partial,
}))

const title = computed(() => {
  if (!status.value) return ''
  if (status.value.partial) return 'Limited Permissions'
  return 'Feature Unavailable'
})

const message = computed(() => {
  if (!status.value) return ''
  const missing = status.value.missing || []
  if (status.value.partial) {
    // Show which services are unavailable
    const services = status.value.services
    if (services) {
      const unavailable = Object.entries(services)
        .filter(([, s]) => !s.available)
        .map(([name]) => name)
      if (unavailable.length > 0) {
        return `Some services are unavailable: ${unavailable.join(', ')}`
      }
    }
    return `Missing ${missing.length} permission(s). Some functionality may be limited.`
  }
  if (missing.length > 0) {
    return `Missing required permissions: ${missing.slice(0, 3).join(', ')}${missing.length > 3 ? ` (+${missing.length - 3} more)` : ''}`
  }
  return 'Required permissions are not available for this feature.'
})
</script>

<style scoped>
.permission-banner {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.65rem 1rem;
  border-radius: 8px;
  margin-bottom: 1rem;
  font-size: 0.85rem;
}

.banner-partial {
  background: rgba(245, 158, 11, 0.1);
  border: 1px solid rgba(245, 158, 11, 0.25);
  color: #f59e0b;
}

.banner-unavailable {
  background: rgba(239, 68, 68, 0.1);
  border: 1px solid rgba(239, 68, 68, 0.25);
  color: #ef4444;
}

.banner-icon {
  font-size: 1rem;
  flex-shrink: 0;
}

.banner-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
}

.banner-content strong {
  font-size: 0.85rem;
}

.banner-content span {
  font-size: 0.8rem;
  opacity: 0.85;
}

.banner-link {
  font-size: 0.8rem;
  font-weight: 500;
  color: var(--accent-cyan);
  text-decoration: none;
  white-space: nowrap;
  padding: 0.3rem 0.6rem;
  border-radius: 6px;
  border: 1px solid rgba(25, 212, 212, 0.2);
  transition: all 0.2s;
}

.banner-link:hover {
  background: rgba(25, 212, 212, 0.1);
  border-color: rgba(25, 212, 212, 0.4);
}
</style>
