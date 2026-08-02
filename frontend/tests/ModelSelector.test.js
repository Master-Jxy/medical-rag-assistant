import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const modelApi = vi.hoisted(() => ({ getModelCatalog: vi.fn() }))
vi.mock('../src/api/models.js', () => modelApi)

import ModelSelector from '../src/components/ModelSelector.vue'

beforeEach(() => {
  modelApi.getModelCatalog.mockResolvedValue({
    active_model_id: 'qwen',
    options: [
      { id: 'qwen', label: '通义千问', provider: 'DashScope', model_name: 'qwen3-max', enabled: true, status: 'available', input_price_per_million_tokens_cny: 2.5, output_price_per_million_tokens_cny: 10 },
      { id: 'deepseek', label: 'DeepSeek', provider: 'DeepSeek', enabled: false, status: 'testing' },
      { id: 'kimi', label: 'Kimi', provider: 'Moonshot AI', enabled: false, status: 'testing' },
    ],
  })
})

describe('ModelSelector', () => {
  it('展示当前模型、单价和不可用的候选模型', async () => {
    const wrapper = mount(ModelSelector, { props: { surface: 'rag' } })
    await flushPromises()

    expect(modelApi.getModelCatalog).toHaveBeenCalledWith('rag')
    expect(wrapper.text()).toContain('通义千问')
    expect(wrapper.text()).toContain('输入 ¥2.50 / 输出 ¥10.00')
    const buttons = wrapper.findAll('.model-menu button')
    expect(buttons).toHaveLength(3)
    expect(buttons[1].attributes('disabled')).toBeDefined()
    expect(buttons[2].attributes('disabled')).toBeDefined()
  })
})
