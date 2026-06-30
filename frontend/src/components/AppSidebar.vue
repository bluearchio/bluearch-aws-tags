<template>
  <aside class="sidebar">
    <div class="sidebar-header">
      <div class="logo">
        <svg width="28" height="28" viewBox="0 0 103 103" fill="none">
          <circle cx="51" cy="51" r="47.5" stroke="#206CF5" stroke-width="5"/>
          <circle cx="51" cy="51" r="36" stroke="#206CF5" stroke-width="5"/>
          <path d="M32.4 68.1L51.7 29.6L71 68.1" stroke="#206CF5" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
        <span class="logo-text">Tag Manager</span>
      </div>
    </div>
    <nav class="sidebar-nav">
      <template v-for="item in navItems" :key="item.path">
        <!-- Item with children -->
        <template v-if="item.children">
          <router-link
            :to="item.path"
            class="nav-item"
            :class="{ active: isExactActive(item.path) }"
          >
            <i :class="item.icon"></i>
            <span>{{ item.label }}</span>
            <i v-if="item.routeName && permissionStore.navHasWarning(item.routeName)"
               class="pi pi-exclamation-triangle nav-warning-badge"
               title="Limited permissions"></i>
            <i class="pi sub-chevron" :class="isGroupOpen(item.path) ? 'pi-chevron-down' : 'pi-chevron-right'"></i>
          </router-link>
          <div v-if="isGroupOpen(item.path)" class="sub-nav">
            <router-link
              v-for="child in item.children"
              :key="child.path"
              :to="child.path"
              class="nav-item sub-item"
              :class="{ active: isActive(child.path) }"
            >
              <i :class="child.icon"></i>
              <span>{{ child.label }}</span>
            </router-link>
          </div>
        </template>
        <!-- Simple item -->
        <router-link
          v-else
          :to="item.path"
          class="nav-item"
          :class="{ active: isActive(item.path) }"
        >
          <i :class="item.icon"></i>
          <span>{{ item.label }}</span>
          <i v-if="item.routeName && permissionStore.navHasWarning(item.routeName)"
             class="pi pi-exclamation-triangle nav-warning-badge"
             title="Limited permissions"></i>
        </router-link>
    </template>
  </nav>
    <div class="sidebar-footer">
      <a href="/docs" target="_blank" class="nav-item">
        <i class="pi pi-book"></i>
        <span>API Docs</span>
      </a>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { usePermissionStore } from '@/stores/permissions'

const route = useRoute()
const permissionStore = usePermissionStore()

interface NavChild {
  path: string
  label: string
  icon: string
}

interface NavItem {
  path: string
  label: string
  icon: string
  routeName?: string
  children?: NavChild[]
}

const navItems = computed<NavItem[]>(() => {
  const setupChildren: NavChild[] = [
    { path: '/setup/assume-role', label: 'Assume Role', icon: 'pi pi-key' },
    { path: '/setup/multi-account', label: 'Multi-Account', icon: 'pi pi-sitemap' },
  ]

  return [
    { path: '/', label: 'Dashboard', icon: 'pi pi-home' },
    {
      path: '/resources',
      label: 'Resources',
      icon: 'pi pi-server',
      routeName: 'resources',
      children: [
        { path: '/resources/map', label: 'Resource Map', icon: 'pi pi-sitemap' },
      ],
    },
    {
      path: '/lifecycle',
      label: 'Lifecycle',
      icon: 'pi pi-clock',
      routeName: 'lifecycle',
      children: [
        { path: '/lifecycle/policies', label: 'Tag Policies', icon: 'pi pi-tag' },
        { path: '/lifecycle/audit', label: 'Audit Log', icon: 'pi pi-list' },
      ],
    },
    { path: '/compliance', label: 'Compliance', icon: 'pi pi-check-circle', routeName: 'compliance' },
    { path: '/cost', label: 'Cost', icon: 'pi pi-dollar', routeName: 'cost' },
    { path: '/chat', label: 'AI Chat', icon: 'pi pi-comment', routeName: 'chat' },
    {
      path: '/setup',
      label: 'Setup',
      icon: 'pi pi-cog',
      children: setupChildren,
    },
  ]
})

function isActive(path: string): boolean {
  if (path === '/') return route.path === '/'
  return route.path.startsWith(path)
}

function isExactActive(path: string): boolean {
  return route.path === path
}

function isGroupOpen(parentPath: string): boolean {
  if (parentPath === '/setup') {
    return route.path.startsWith('/setup')
  }
  if (parentPath === '/lifecycle') {
    return route.path.startsWith('/lifecycle')
  }
  if (parentPath === '/resources') {
    return route.path.startsWith('/resources')
  }
  return route.path.startsWith(parentPath)
}
</script>

<style scoped>
.sidebar {
  position: fixed;
  top: 0;
  left: 0;
  width: var(--sidebar-width);
  height: 100vh;
  background: #0a0a0a;
  border-right: 1px solid var(--surface-border);
  color: var(--text-color-secondary);
  display: flex;
  flex-direction: column;
  z-index: 100;
}

/* Gradient glow line at top */
.sidebar::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 2px;
  background: var(--gradient-border);
  box-shadow: 0px 2px 12px rgba(32, 108, 245, 0.4);
}

.sidebar-header {
  padding: 1.25rem 1rem;
  border-bottom: 1px solid var(--surface-border);
}

.logo {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.logo-text {
  font-family: var(--font-heading);
  font-size: 0.95rem;
  letter-spacing: 0.03em;
  text-transform: uppercase;
  background: var(--gradient-brand-horizontal);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.sidebar-nav {
  flex: 1;
  padding: 0.75rem 0.5rem;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.65rem 0.85rem;
  border-radius: 8px;
  color: var(--text-color-secondary);
  text-decoration: none;
  font-size: 0.875rem;
  transition: all 0.2s ease;
}

.nav-item:hover {
  background: rgba(32, 108, 245, 0.08);
  color: var(--text-color);
}

.nav-item.active {
  background: rgba(32, 108, 245, 0.15);
  color: #fff;
  border-left: 2px solid transparent;
  border-image: var(--gradient-border) 1;
}

.nav-item i {
  font-size: 1rem;
  width: 20px;
  text-align: center;
}

.nav-item.active i {
  color: var(--accent-cyan);
}

.nav-item.active span {
  background: var(--gradient-brand-horizontal);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.nav-warning-badge {
  margin-left: auto;
  font-size: 0.7rem !important;
  width: auto !important;
  color: var(--color-warning);
  opacity: 0.8;
}

.sub-chevron {
  margin-left: auto;
  font-size: 0.65rem !important;
  width: auto !important;
  opacity: 0.5;
}

.sub-nav {
  display: flex;
  flex-direction: column;
  gap: 1px;
  padding-left: 0.5rem;
}

.sub-item {
  padding: 0.5rem 0.85rem 0.5rem 1.75rem;
  font-size: 0.82rem;
}

.sub-item i {
  font-size: 0.85rem;
}

.sidebar-footer {
  padding: 0.75rem 0.5rem;
  border-top: 1px solid var(--surface-border);
}

.nav-lock-badge {
  font-size: 0.7rem !important;
  width: auto !important;
  color: var(--text-color-secondary);
  margin-left: auto;
  opacity: 0.6;
}

.tier-badge {
  padding: 2px 8px;
  margin: 4px 16px;
  font-size: 0.7rem;
  font-weight: 700;
  letter-spacing: 0.05em;
  color: var(--primary-color);
  border: 1px solid var(--primary-color);
  border-radius: 4px;
  text-align: center;
}
</style>
