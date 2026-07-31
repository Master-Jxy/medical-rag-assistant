import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import UsageMeta from '../src/components/UsageMeta.vue'

describe('UsageMeta', () => {
  it.each([
    [{ measurement: 'unknown' }, '模型未返回计量'],
    [
      {
        measurement: 'not_applicable',
        input_tokens: 0,
        output_tokens: 0,
        total_tokens: 0,
        estimated_cost_cny: 0,
      },
      '未调用模型 · 0 Token · ¥0',
    ],
    [
      {
        measurement: 'actual',
        input_tokens: 1286,
        output_tokens: 436,
        total_tokens: 1722,
        estimated_cost_cny: null,
      },
      '输入 1,286 · 输出 436 · 单价未配置',
    ],
  ])('明确区分实际、未知和未调用计量 %#', (usage, expected) => {
    expect(mount(UsageMeta, { props: { usage } }).text()).toBe(expected)
  })

  it('没有回答级计量时不渲染占位文本', () => {
    expect(mount(UsageMeta).text()).toBe('')
  })
})
