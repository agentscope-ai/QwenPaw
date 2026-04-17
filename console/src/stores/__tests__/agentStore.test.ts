import { describe, it, expect, beforeEach } from 'vitest'
import { useAgentStore } from '../agentStore'
import type { AgentSummary } from '@/api/types/agents'

const mockAgent = (id: string): AgentSummary =>
  ({ id, name: `Agent ${id}` } as AgentSummary)

describe('agentStore', () => {
  beforeEach(() => {
    // 每个测试前重置为初始状态
    useAgentStore.setState({
      selectedAgent: 'default',
      agents: [],
    })
  })

  // ---------------------------------------------------------------------------
  // 初始状态
  // ---------------------------------------------------------------------------

  it('初始 selectedAgent 为 "default"', () => {
    expect(useAgentStore.getState().selectedAgent).toBe('default')
  })

  it('初始 agents 为空数组', () => {
    expect(useAgentStore.getState().agents).toEqual([])
  })

  // ---------------------------------------------------------------------------
  // setSelectedAgent
  // ---------------------------------------------------------------------------

  it('setSelectedAgent 更新 selectedAgent', () => {
    useAgentStore.getState().setSelectedAgent('agent-123')
    expect(useAgentStore.getState().selectedAgent).toBe('agent-123')
  })

  // ---------------------------------------------------------------------------
  // setAgents
  // ---------------------------------------------------------------------------

  it('setAgents 替换整个 agents 列表', () => {
    const agents = [mockAgent('1'), mockAgent('2')]
    useAgentStore.getState().setAgents(agents)
    expect(useAgentStore.getState().agents).toEqual(agents)
  })

  it('setAgents 传空数组清空列表', () => {
    useAgentStore.getState().setAgents([mockAgent('1')])
    useAgentStore.getState().setAgents([])
    expect(useAgentStore.getState().agents).toEqual([])
  })

  // ---------------------------------------------------------------------------
  // addAgent
  // ---------------------------------------------------------------------------

  it('addAgent 追加到列表末尾', () => {
    useAgentStore.getState().setAgents([mockAgent('1')])
    useAgentStore.getState().addAgent(mockAgent('2'))
    expect(useAgentStore.getState().agents).toHaveLength(2)
    expect(useAgentStore.getState().agents[1].id).toBe('2')
  })

  it('空列表 addAgent 后长度为 1', () => {
    useAgentStore.getState().addAgent(mockAgent('1'))
    expect(useAgentStore.getState().agents).toHaveLength(1)
  })

  // ---------------------------------------------------------------------------
  // removeAgent
  // ---------------------------------------------------------------------------

  it('removeAgent 移除指定 id', () => {
    useAgentStore.getState().setAgents([mockAgent('1'), mockAgent('2'), mockAgent('3')])
    useAgentStore.getState().removeAgent('2')
    const ids = useAgentStore.getState().agents.map((a) => a.id)
    expect(ids).toEqual(['1', '3'])
  })

  it('removeAgent 不存在的 id 不报错，列表不变', () => {
    useAgentStore.getState().setAgents([mockAgent('1')])
    useAgentStore.getState().removeAgent('999')
    expect(useAgentStore.getState().agents).toHaveLength(1)
  })

  // ---------------------------------------------------------------------------
  // updateAgent
  // ---------------------------------------------------------------------------

  it('updateAgent 修改指定 agent 的字段', () => {
    useAgentStore.getState().setAgents([mockAgent('1'), mockAgent('2')])
    useAgentStore.getState().updateAgent('1', { name: 'Updated Name' })
    const agent = useAgentStore.getState().agents.find((a) => a.id === '1')
    expect(agent?.name).toBe('Updated Name')
  })

  it('updateAgent 只修改目标，不影响其他 agent', () => {
    useAgentStore.getState().setAgents([mockAgent('1'), mockAgent('2')])
    useAgentStore.getState().updateAgent('1', { name: 'New Name' })
    const agent2 = useAgentStore.getState().agents.find((a) => a.id === '2')
    expect(agent2?.name).toBe('Agent 2')
  })

  it('updateAgent 不存在的 id 不报错，列表不变', () => {
    useAgentStore.getState().setAgents([mockAgent('1')])
    expect(() =>
      useAgentStore.getState().updateAgent('999', { name: 'Ghost' }),
    ).not.toThrow()
    expect(useAgentStore.getState().agents).toHaveLength(1)
  })
})
