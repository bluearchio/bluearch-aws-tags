<template>
  <div v-if="showLayout" class="app-layout">
    <AppSidebar />
    <div class="app-main">
      <AppTopbar />
      <main class="app-content">
        <router-view />
      </main>
    </div>
    <ScanProgressPanel />
  </div>
  <router-view v-else />
  <ToastContainer />
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import AppSidebar from './components/AppSidebar.vue'
import AppTopbar from './components/AppTopbar.vue'
import ScanProgressPanel from './components/ScanProgressPanel.vue'
import ToastContainer from './components/ToastContainer.vue'

const route = useRoute()
const showLayout = computed(() => route.meta.public !== true)
</script>

<style>
/* BlueArch fonts */
@font-face {
  font-family: 'Audiowide';
  src: url('@/assets/fonts/Audiowide-Regular.ttf') format('truetype');
  font-weight: 400;
  font-style: normal;
  font-display: swap;
}

@font-face {
  font-family: 'Alata';
  src: url('@/assets/fonts/Alata-Regular.ttf') format('truetype');
  font-weight: 400;
  font-style: normal;
  font-display: swap;
}

@font-face {
  font-family: 'ShareTechMono';
  src: url('@/assets/fonts/ShareTechMono-Regular.ttf') format('truetype');
  font-weight: 400;
  font-style: normal;
  font-display: swap;
}

:root {
  --sidebar-width: 240px;
  --topbar-height: 56px;

  /* BlueArch dark theme */
  --surface-ground: #0a0a0a;
  --surface-card: #141414;
  --surface-card-hover: #1a1a1a;
  --surface-border: #262626;
  --surface-input: #0f0f0f;

  /* Text */
  --text-color: #f0f0f0;
  --text-color-secondary: #a0a0a0;

  /* Brand */
  --primary-color: #206CF5;
  --primary-hover: #116DFE;
  --accent-cyan: #19D4D4;
  --gradient-brand: linear-gradient(135deg, #206CF5, #19D4D4);

  /* Semantic */
  --color-success: #22c55e;
  --color-warning: #eab308;
  --color-danger: #ef4444;

  /* Glow */
  --glow-blue: 0 0 20px rgba(32, 108, 245, 0.15);
  --glow-blue-strong: 0 0 30px rgba(32, 108, 245, 0.3);
  --glow-header: 0px 4px 20px rgba(42, 106, 246, 0.25);

  /* Gradients */
  --gradient-brand: linear-gradient(135deg, #206CF5, #19D4D4);
  --gradient-brand-horizontal: linear-gradient(92.87deg, #206CF5 14.71%, #19D5D5 87.94%);
  --gradient-border: linear-gradient(to right, #206CF5, #19D4D4);
  --gradient-card: linear-gradient(135deg, rgba(10, 37, 64, 0.4), rgba(18, 44, 80, 0.2));

  /* Fonts */
  --font-heading: 'Audiowide', sans-serif;
  --font-body: 'Alata', 'Inter', system-ui, sans-serif;
  --font-mono: 'ShareTechMono', 'SF Mono', 'Fira Code', monospace;
}

* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

body {
  font-family: var(--font-body);
  background: var(--surface-ground);
  color: var(--text-color);
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

h1, h2, h3, h4 {
  font-family: var(--font-heading);
  letter-spacing: 0.02em;
  text-transform: uppercase;
}

/* Brand text gradient utility */
.text-gradient {
  background: var(--gradient-brand-horizontal);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

/* Gradient border on hover utility */
.gradient-border-hover {
  position: relative;
}

.gradient-border-hover::before {
  content: '';
  position: absolute;
  inset: 0;
  border-radius: inherit;
  padding: 1px;
  background: var(--gradient-border);
  -webkit-mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
  -webkit-mask-composite: xor;
  mask-composite: exclude;
  opacity: 0;
  transition: opacity 0.25s ease;
  pointer-events: none;
}

.gradient-border-hover:hover::before {
  opacity: 1;
}

code, pre, .mono {
  font-family: var(--font-mono);
}

/* Scrollbar */
::-webkit-scrollbar {
  width: 6px;
  height: 6px;
}
::-webkit-scrollbar-track {
  background: var(--surface-ground);
}
::-webkit-scrollbar-thumb {
  background: #333;
  border-radius: 3px;
}
::-webkit-scrollbar-thumb:hover {
  background: #444;
}

.app-layout {
  display: flex;
  min-height: 100vh;
}

.app-main {
  flex: 1;
  margin-left: var(--sidebar-width);
  display: flex;
  flex-direction: column;
}

.app-content {
  padding: 1.5rem;
  margin-top: var(--topbar-height);
  flex: 1;
}

/* Selection */
::selection {
  background: rgba(32, 108, 245, 0.3);
  color: #fff;
}

/* License banner */
.license-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  background: linear-gradient(90deg, rgba(32, 108, 245, 0.15), rgba(32, 108, 245, 0.05));
  border-bottom: 1px solid rgba(32, 108, 245, 0.3);
  color: var(--text-color-secondary);
  font-size: 0.85rem;
}
.license-banner .pi { color: var(--primary-color); }
.license-banner .banner-link {
  margin-left: auto;
  color: var(--primary-color);
  text-decoration: none;
  font-weight: 600;
}
.license-banner .banner-link:hover { text-decoration: underline; }
</style>
