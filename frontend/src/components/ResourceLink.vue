<template>
  <router-link
    :to="linkTarget"
    class="resource-link"
    :title="arn || ''"
  >
    <slot>{{ displayText }}</slot>
  </router-link>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  /** Database resource UUID - links to /resources/:id */
  id?: string
  /** Resource ARN - used for display and fallback search link */
  arn?: string
  /** Max display length for truncated ARN (default 60) */
  maxLen?: number
}>()

const linkTarget = computed(() => {
  if (props.id) {
    return { name: 'resource-detail', params: { id: props.id } }
  }
  if (props.arn) {
    return { path: '/resources', query: { search: props.arn } }
  }
  return '/resources'
})

const displayText = computed(() => {
  if (!props.arn) return props.id || '-'
  const max = props.maxLen ?? 60
  if (props.arn.length <= max) return props.arn
  // Keep service prefix and tail
  const parts = props.arn.split(':')
  if (parts.length >= 6) {
    const prefix = parts.slice(0, 3).join(':')
    const tail = parts.slice(5).join(':')
    if (prefix.length + tail.length + 4 <= max) {
      return `${prefix}:...:${tail}`
    }
    const available = max - prefix.length - 5
    return `${prefix}:...:${tail.slice(-Math.max(available, 12))}`
  }
  return props.arn.slice(0, max - 3) + '...'
})
</script>

<style scoped>
.resource-link {
  color: var(--primary-color, #5a9aff);
  text-decoration: none;
  font-family: 'SF Mono', 'Fira Code', 'Cascadia Code', monospace;
  font-size: inherit;
  border-bottom: 1px dashed rgba(32, 108, 245, 0.35);
  transition: all 0.15s;
  word-break: break-all;
}

.resource-link:hover {
  color: #79b0ff;
  border-bottom-color: rgba(32, 108, 245, 0.7);
}
</style>
