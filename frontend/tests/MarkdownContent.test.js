import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import MarkdownContent from '../src/components/MarkdownContent.vue'

describe('MarkdownContent', () => {
  it('渲染标题、重点、列表和安全链接', () => {
    const wrapper = mount(MarkdownContent, {
      props: {
        content: [
          '## 回答重点',
          '',
          '- **安全边界**：不提供诊断',
          '- [参考资料](https://example.com/guide)',
        ].join('\n'),
      },
    })

    expect(wrapper.get('h2').text()).toBe('回答重点')
    expect(wrapper.get('strong').text()).toBe('安全边界')
    expect(wrapper.findAll('li')).toHaveLength(2)
    expect(wrapper.get('a').attributes()).toMatchObject({
      href: 'https://example.com/guide',
      target: '_blank',
      rel: 'noopener noreferrer',
    })
  })

  it('禁用原始HTML并阻止危险链接进入可执行DOM', () => {
    const wrapper = mount(MarkdownContent, {
      props: {
        content: [
          '<img src=x onerror="alert(1)">',
          '<script>alert(1)</script>',
          '[危险链接](javascript:alert(1))',
        ].join('\n'),
      },
    })

    expect(wrapper.find('img').exists()).toBe(false)
    expect(wrapper.find('script').exists()).toBe(false)
    expect(wrapper.find('a').exists()).toBe(false)
    expect(wrapper.text()).toContain('<img src=x onerror="alert(1)">')
    expect(wrapper.text()).toContain('<script>alert(1)</script>')
  })
})
