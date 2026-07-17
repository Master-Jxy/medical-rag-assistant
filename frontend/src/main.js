import { createApp } from 'vue'
import { ElButton } from 'element-plus'
import 'element-plus/es/components/button/style/css'
import './style.css'
import App from './App.vue'
import router from './router'
import { AUTH_UNAUTHORIZED_EVENT } from './auth/token.js'

window.addEventListener(AUTH_UNAUTHORIZED_EVENT, () => {
  const current = router.currentRoute.value
  if (current.name === 'login') return
  router.replace({ name: 'login', query: { redirect: current.fullPath } })
})

createApp(App).use(router).component('ElButton', ElButton).mount('#app')
