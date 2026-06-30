<template>
  <header class="topbar">
    <div class="topbar-left">
      <h1 class="page-title">{{ pageTitle }}</h1>
    </div>
    <div class="topbar-right">
      <ContextSwitcher />
      <NotificationBell />
      <div class="health-indicator" :class="healthClass" :title="`Status: ${healthStatus}`">
        <i class="pi pi-circle-fill"></i>
        <span>{{ healthStatus }}</span>
      </div>
    </div>
  </header>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { api } from '@/api/client'
import { useContextStore } from '@/stores/context'
import { usePermissionStore } from '@/stores/permissions'
import ContextSwitcher from './ContextSwitcher.vue'
import NotificationBell from './NotificationBell.vue'

const route = useRoute()
const contextStore = useContextStore()
const permissionStore = usePermissionStore()
const healthStatus = ref('checking...')
const isHealthy = ref(false)

const pageTitle = computed(() => {
  const titles: Record<string, string> = {
    dashboard: 'Dashboard',
    resources: 'Resources',
    'resource-detail': 'Resource Detail',
    lifecycle: 'Lifecycle',
    'lifecycle-policies': 'Lifecycle',
    compliance: 'Tag Policy Compliance',
    cost: 'Cost Analytics',
    chat: 'AI Chat',
  }
  return titles[route.name as string] || 'AWS Tag Manager'
})

const healthClass = computed(() => ({
  healthy: isHealthy.value,
  unhealthy: !isHealthy.value && healthStatus.value !== 'checking...',
}))

async function checkHealth() {
  try {
    const data = await api.health()
    healthStatus.value = data.status
    isHealthy.value = data.status === 'healthy'
  } catch {
    healthStatus.value = 'unreachable'
    isHealthy.value = false
  }
}

onMounted(() => {
  checkHealth()
  contextStore.loadCurrent()
  contextStore.loadAll()
  permissionStore.load()
})
</script>

<style scoped>
.topbar {
  position: fixed;
  top: 0;
  left: var(--sidebar-width);
  right: 0;
  height: var(--topbar-height);
  background: var(--surface-card);
  border-bottom: 1px solid var(--surface-border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 1.5rem;
  z-index: 90;
}

/* Gradient glow line at bottom */
.topbar::after {
  content: '';
  position: absolute;
  bottom: -1px;
  left: 0;
  right: 0;
  height: 1px;
  background: var(--gradient-border);
  box-shadow: 0px 2px 12px rgba(32, 108, 245, 0.3);
}

.page-title {
  font-size: 1rem;
  font-weight: 400;
  letter-spacing: 0.04em;
  background: var(--gradient-brand-horizontal);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.topbar-right {
  display: flex;
  align-items: center;
  gap: 1rem;
}

.health-indicator {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.8rem;
  color: var(--text-color-secondary);
}

.health-indicator i {
  font-size: 0.5rem;
}

.health-indicator.healthy i {
  color: var(--color-success);
}

.health-indicator.unhealthy i {
  color: var(--color-danger);
}

.notification-menu {
  position: relative;
}

.notification-trigger {
  position: relative;
  width: 36px;
  height: 36px;
  border: 1px solid var(--surface-border);
  border-radius: 8px;
  background: var(--surface-card);
  color: var(--text-color-secondary);
  cursor: pointer;
  transition: all 0.2s ease;
}

.notification-trigger:hover,
.notification-trigger.has-notifications {
  color: var(--primary-color);
  border-color: rgba(32, 108, 245, 0.45);
  box-shadow: var(--glow-blue);
}

.notification-count {
  position: absolute;
  top: -6px;
  right: -6px;
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  border-radius: 999px;
  background: var(--color-warning);
  color: #0a0a0a;
  font-size: 0.68rem;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
}

.notification-dropdown {
  position: absolute;
  top: calc(100% + 8px);
  right: 0;
  width: min(440px, calc(100vw - 2rem));
  max-height: 70vh;
  overflow: auto;
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 10px;
  box-shadow: var(--glow-blue), 0 8px 24px rgba(0, 0, 0, 0.45);
  z-index: 120;
}

.notification-dropdown-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.85rem 1rem;
  border-bottom: 1px solid var(--surface-border);
  color: var(--text-color);
  font-weight: 700;
}

.notification-refresh {
  width: 28px;
  height: 28px;
  border: 1px solid var(--surface-border);
  border-radius: 6px;
  background: transparent;
  color: var(--text-color-secondary);
  cursor: pointer;
}

.notification-list {
  display: flex;
  flex-direction: column;
}

.notification-item {
  padding: 0.95rem 1rem;
  border-bottom: 1px solid rgba(148, 163, 184, 0.12);
}

.notification-item:last-child {
  border-bottom: 0;
}

.notification-item-header,
.notification-footer {
  display: flex;
  justify-content: space-between;
  gap: 0.75rem;
  align-items: center;
}

.notification-title {
  color: var(--text-color);
  font-size: 0.86rem;
  font-weight: 700;
}

.notification-severity {
  color: var(--color-warning);
  font-size: 0.7rem;
  text-transform: uppercase;
  font-family: var(--font-mono);
}

.notification-message {
  color: var(--text-color-secondary);
  font-size: 0.8rem;
  line-height: 1.45;
  margin: 0.45rem 0 0.6rem;
  white-space: pre-wrap;
}

.notification-footer {
  color: var(--text-color-secondary);
  font-size: 0.72rem;
}

.notification-link {
  color: var(--accent-cyan);
  text-decoration: none;
  font-weight: 700;
}

.notification-empty {
  padding: 1rem;
  color: var(--text-color-secondary);
  font-size: 0.82rem;
}

/* User menu */
.user-menu {
  position: relative;
}

.user-menu-trigger {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.35rem 0.65rem;
  border: 1px solid var(--surface-border);
  border-radius: 8px;
  background: var(--surface-card);
  cursor: pointer;
  font-size: 0.82rem;
  color: var(--text-color);
  transition: all 0.2s;
  font-family: var(--font-body);
}

.user-menu-trigger:hover {
  background: var(--surface-card-hover);
  border-color: rgba(32, 108, 245, 0.3);
}

.user-menu-trigger .pi-chevron-down {
  font-size: 0.6rem;
  opacity: 0.5;
}

.user-name {
  font-weight: 500;
}

.user-role-badge {
  padding: 0.1rem 0.4rem;
  border-radius: 4px;
  font-size: 0.7rem;
  font-weight: 600;
  text-transform: capitalize;
  font-family: var(--font-mono);
}

.role-admin { background: rgba(32, 108, 245, 0.2); color: #5a9aff; }

.user-dropdown {
  position: absolute;
  top: calc(100% + 4px);
  right: 0;
  min-width: 220px;
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 10px;
  box-shadow: var(--glow-blue), 0 4px 16px rgba(0, 0, 0, 0.4);
  z-index: 100;
  overflow: hidden;
}

.dropdown-header {
  padding: 0.65rem 0.85rem;
}

.dropdown-email {
  font-size: 0.8rem;
  color: var(--text-color);
  font-weight: 500;
}

.dropdown-tier {
  font-size: 0.72rem;
  color: var(--text-color-secondary);
  margin-top: 0.15rem;
  text-transform: capitalize;
}

.dropdown-divider {
  height: 1px;
  background: var(--surface-border);
}

.dropdown-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  width: 100%;
  padding: 0.6rem 0.85rem;
  border: none;
  background: none;
  color: var(--text-color);
  font-size: 0.82rem;
  cursor: pointer;
  transition: background 0.15s;
  text-align: left;
  font-family: var(--font-body);
}

.dropdown-item:hover {
  background: rgba(32, 108, 245, 0.08);
}

.dropdown-item-danger {
  color: var(--color-danger);
}

.dropdown-item-danger:hover {
  background: rgba(239, 68, 68, 0.1);
}
</style>
