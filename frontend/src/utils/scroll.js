import { nextTick, unref } from 'vue'

export async function scrollToLatest(target) {
  await nextTick()
  const element = unref(target)
  if (!element) return

  const previousBehavior = element.style.scrollBehavior
  element.style.scrollBehavior = 'auto'
  element.scrollTop = element.scrollHeight
  element.style.scrollBehavior = previousBehavior
}
