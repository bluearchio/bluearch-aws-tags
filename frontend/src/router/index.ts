import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      name: 'dashboard',
      component: () => import('@/views/DashboardView.vue'),
    },
    {
      path: '/resources',
      name: 'resources',
      component: () => import('@/views/ResourcesView.vue'),
    },
    {
      path: '/resources/map',
      name: 'resource-map',
      component: () => import('@/views/ResourceMapView.vue'),
    },
    {
      path: '/resources/:id',
      name: 'resource-detail',
      component: () => import('@/views/ResourceDetailView.vue'),
    },
    {
      path: '/lifecycle',
      name: 'lifecycle',
      component: () => import('@/views/LifecycleView.vue'),
    },
    {
      path: '/lifecycle/policies',
      name: 'lifecycle-policies',
      component: () => import('@/views/LifecycleView.vue'),
    },
    {
      path: '/lifecycle/audit',
      name: 'lifecycle-audit',
      component: () => import('@/views/AuditView.vue'),
    },
    {
      path: '/compliance',
      name: 'compliance',
      component: () => import('@/views/ComplianceView.vue'),
    },
    {
      path: '/cost',
      name: 'cost',
      component: () => import('@/views/CostView.vue'),
    },
    {
      path: '/chat',
      name: 'chat',
      component: () => import('@/views/ChatView.vue'),
    },
    {
      path: '/setup/assume-role',
      name: 'assume-role',
      component: () => import('@/views/AssumeRoleView.vue'),
    },
    {
      path: '/setup/multi-account',
      name: 'multi-account',
      component: () => import('@/views/MultiAccountView.vue'),
    },
    {
      path: '/setup/infrastructure',
      redirect: '/setup',
    },
    {
      path: '/setup',
      name: 'setup',
      component: () => import('@/views/SetupView.vue'),
    },
  ],
})

router.beforeEach(() => {
  return true
})

export default router
