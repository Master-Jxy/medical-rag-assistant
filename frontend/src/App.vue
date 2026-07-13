<template>
  <div class="app-shell">
    <header class="app-header">
      <router-link class="brand" to="/">
        <span class="brand-mark">M</span>
        <span><strong>Medical RAG</strong><small>医疗知识库助手</small></span>
      </router-link>
      <nav aria-label="主导航">
        <router-link to="/">系统概览</router-link>
        <router-link to="/chat">知识问答</router-link>
        <router-link to="/knowledge">知识库</router-link>
      </nav>
    </header>
    <main><router-view /></main>
    <footer>仅供学习和信息检索，不构成医疗建议。</footer>
  </div>
</template>
