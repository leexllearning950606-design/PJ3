import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/', name: 'generate', component: () => import('./views/GenerateView.vue') },
  { path: '/history', name: 'history', component: () => import('./views/HistoryView.vue') },
  { path: '/history/:id', name: 'history-detail', component: () => import('./views/HistoryDetail.vue') },
  { path: '/preferences', name: 'preferences', component: () => import('./views/PreferencesView.vue') },
  { path: '/compare', name: 'compare', component: () => import('./views/CompareView.vue') },
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
})
