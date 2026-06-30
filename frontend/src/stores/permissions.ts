import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { api } from '@/api/client'
import type { PermissionStatusResponse, FeatureStatus } from '@/types/api'

export const usePermissionStore = defineStore('permissions', () => {
    const status = ref<PermissionStatusResponse | null>(null)
    const loading = ref(false)

    const tier = computed(() => status.value?.tier || 'unknown')

    function canUse(feature: string): boolean {
        if (!status.value) return true // optimistic until loaded
        const f = status.value.features[feature]
        return f ? f.available : true
    }

    function featureStatus(feature: string): FeatureStatus | null {
        if (!status.value) return null
        return status.value.features[feature] || null
    }

    function isPartial(feature: string): boolean {
        if (!status.value) return false
        const f = status.value.features[feature]
        return f ? (f.partial || false) : false
    }

    // Map nav route names to feature keys for badge display
    const navFeatureMap: Record<string, string> = {
        resources: 'discover_resources',
        lifecycle: 'lifecycle_management',
        compliance: 'compliance',
        cost: 'cost_report',
        chat: 'ai_assistant',
    }

    function navHasWarning(routeName: string): boolean {
        const feature = navFeatureMap[routeName]
        if (!feature || !status.value) return false
        const f = status.value.features[feature]
        if (!f) return false
        return !f.available || (f.partial || false)
    }

    async function load() {
        loading.value = true
        try {
            status.value = await api.permissions()
        } catch {
            // handled by API client
        } finally {
            loading.value = false
        }
    }

    async function refresh() {
        loading.value = true
        try {
            status.value = await api.refreshPermissions()
        } catch {
            // handled by API client
        } finally {
            loading.value = false
        }
    }

    return { status, loading, tier, canUse, featureStatus, isPartial, navHasWarning, load, refresh }
})
