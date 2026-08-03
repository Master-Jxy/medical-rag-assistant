import { describe, expect, it } from 'vitest'
import { useConversationStreamRegistry } from '../src/features/agent-chat/useConversationStreamRegistry.js'

describe('按会话流注册表', () => {
  it('隔离会话状态并按event_id拒绝重复事件', () => {
    const registry = useConversationStreamRegistry()
    registry.start('conversation-a', { phase: 'running' })
    registry.start('conversation-b', { phase: 'running' })

    expect(registry.isRunning('conversation-a')).toBe(true)
    expect(registry.acceptEvent('conversation-a', { event_id: 'event-1' })).toBe(true)
    expect(registry.acceptEvent('conversation-a', { event_id: 'event-1' })).toBe(false)
    expect(registry.acceptEvent('conversation-b', { event_id: 'event-1' })).toBe(true)

    registry.markUnread('conversation-a')
    expect(registry.hasUnread('conversation-a')).toBe(true)
    expect(registry.hasUnread('conversation-b')).toBe(false)
  })
})
