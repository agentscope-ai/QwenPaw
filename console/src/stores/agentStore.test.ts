import { describe, it, expect, beforeEach } from 'vitest'
import { useAgentStore } from './agentStore'
import type { AgentSummary } from '@/api/types/agents'

const mockAgent = (id: string): AgentSummary =>
  ({ id, name: `Agent ${id}` } as AgentSummary)

describe('agentStore', () => {
  beforeEach(() => {
    // Reset to initial state before each test
    useAgentStore.setState({
      selectedAgent: 'default',
      agents: [],
    })
  })

  // ---------------------------------------------------------------------------
  // Initial state
  // ---------------------------------------------------------------------------

  it('initial selectedAgent is "default"', () => {
    expect(useAgentStore.getState().selectedAgent).toBe('default')
  })

  it('initial agents is an empty array', () => {
    expect(useAgentStore.getState().agents).toEqual([])
  })

  // ---------------------------------------------------------------------------
  // setSelectedAgent
  // ---------------------------------------------------------------------------

  it('setSelectedAgent updates selectedAgent', () => {
    useAgentStore.getState().setSelectedAgent('agent-123')
    expect(useAgentStore.getState().selectedAgent).toBe('agent-123')
  })

  // ---------------------------------------------------------------------------
  // setAgents
  // ---------------------------------------------------------------------------

  it('setAgents replaces the entire agents list', () => {
    const agents = [mockAgent('1'), mockAgent('2')]
    useAgentStore.getState().setAgents(agents)
    expect(useAgentStore.getState().agents).toEqual(agents)
  })

  it('setAgents with empty array clears the list', () => {
    useAgentStore.getState().setAgents([mockAgent('1')])
    useAgentStore.getState().setAgents([])
    expect(useAgentStore.getState().agents).toEqual([])
  })

  // ---------------------------------------------------------------------------
  // addAgent
  // ---------------------------------------------------------------------------

  it('addAgent appends to the end of the list', () => {
    useAgentStore.getState().setAgents([mockAgent('1')])
    useAgentStore.getState().addAgent(mockAgent('2'))
    expect(useAgentStore.getState().agents).toHaveLength(2)
    expect(useAgentStore.getState().agents[1].id).toBe('2')
  })

  it('addAgent on empty list results in length 1', () => {
    useAgentStore.getState().addAgent(mockAgent('1'))
    expect(useAgentStore.getState().agents).toHaveLength(1)
  })

  // ---------------------------------------------------------------------------
  // removeAgent
  // ---------------------------------------------------------------------------

  it('removeAgent removes the agent with matching id', () => {
    useAgentStore.getState().setAgents([mockAgent('1'), mockAgent('2'), mockAgent('3')])
    useAgentStore.getState().removeAgent('2')
    const ids = useAgentStore.getState().agents.map((a) => a.id)
    expect(ids).toEqual(['1', '3'])
  })

  it('removeAgent with non-existent id does not throw and list is unchanged', () => {
    useAgentStore.getState().setAgents([mockAgent('1')])
    useAgentStore.getState().removeAgent('999')
    expect(useAgentStore.getState().agents).toHaveLength(1)
  })

  // ---------------------------------------------------------------------------
  // updateAgent
  // ---------------------------------------------------------------------------

  it('updateAgent modifies fields of the matching agent', () => {
    useAgentStore.getState().setAgents([mockAgent('1'), mockAgent('2')])
    useAgentStore.getState().updateAgent('1', { name: 'Updated Name' })
    const agent = useAgentStore.getState().agents.find((a) => a.id === '1')
    expect(agent?.name).toBe('Updated Name')
  })

  it('updateAgent only modifies the target, leaving others unchanged', () => {
    useAgentStore.getState().setAgents([mockAgent('1'), mockAgent('2')])
    useAgentStore.getState().updateAgent('1', { name: 'New Name' })
    const agent2 = useAgentStore.getState().agents.find((a) => a.id === '2')
    expect(agent2?.name).toBe('Agent 2')
  })

  it('updateAgent with non-existent id does not throw and list is unchanged', () => {
    useAgentStore.getState().setAgents([mockAgent('1')])
    expect(() =>
      useAgentStore.getState().updateAgent('999', { name: 'Ghost' }),
    ).not.toThrow()
    expect(useAgentStore.getState().agents).toHaveLength(1)
  })
})
