import { describe, it, expect, vi } from 'vitest'
import { screen, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '@/test/common_setup'
import ChatSessionItem from '../index'

vi.mock('@agentscope-ai/design', () => ({
  IconButton: ({ onClick, icon }: { onClick?: (e: React.MouseEvent) => void; icon: React.ReactNode }) => (
    <button onClick={onClick}>{icon}</button>
  ),
}))

vi.mock('@agentscope-ai/icons', () => ({
  SparkEditLine: () => <span data-testid="icon-edit" />,
  SparkDeleteLine: () => <span data-testid="icon-delete" />,
}))

// getChannelIconUrl 返回图片 URL，mock 掉避免网络请求
vi.mock('../../../Control/Channels/components', () => ({
  getChannelIconUrl: (key: string) => `/icons/${key}.png`,
}))

const baseProps = {
  name: 'Test Session',
  time: '2024-01-01 12:00:00',
}

describe('ChatSessionItem', () => {
  it('渲染 session 名称和时间', () => {
    renderWithProviders(<ChatSessionItem {...baseProps} />)
    expect(screen.getByText('Test Session')).toBeInTheDocument()
    expect(screen.getByText('2024-01-01 12:00:00')).toBeInTheDocument()
  })

  it('点击 item 触发 onClick 回调', async () => {
    const user = userEvent.setup()
    const onClick = vi.fn()
    renderWithProviders(<ChatSessionItem {...baseProps} onClick={onClick} />)
    await user.click(screen.getByText('Test Session'))
    expect(onClick).toHaveBeenCalledOnce()
  })

  it('点击编辑按钮触发 onEdit，不冒泡到 onClick', () => {
    // action 按钮 CSS 设了 pointer-events:none（hover 才显示），用 fireEvent 绕过
    const onClick = vi.fn()
    const onEdit = vi.fn()
    renderWithProviders(<ChatSessionItem {...baseProps} onClick={onClick} onEdit={onEdit} />)
    fireEvent.click(screen.getByTestId('icon-edit').closest('button')!)
    expect(onEdit).toHaveBeenCalledOnce()
    expect(onClick).not.toHaveBeenCalled()
  })

  it('点击删除按钮触发 onDelete，不冒泡到 onClick', () => {
    const onClick = vi.fn()
    const onDelete = vi.fn()
    renderWithProviders(<ChatSessionItem {...baseProps} onClick={onClick} onDelete={onDelete} />)
    fireEvent.click(screen.getByTestId('icon-delete').closest('button')!)
    expect(onDelete).toHaveBeenCalledOnce()
    expect(onClick).not.toHaveBeenCalled()
  })

  it('editing 模式显示 Input，不显示名称文字', () => {
    renderWithProviders(
      <ChatSessionItem {...baseProps} editing editValue="edit text" />,
    )
    expect(screen.queryByText('Test Session')).not.toBeInTheDocument()
    expect(screen.getByRole('textbox')).toBeInTheDocument()
  })

  it('editing 模式输入触发 onEditChange', async () => {
    const user = userEvent.setup()
    const onEditChange = vi.fn()
    renderWithProviders(
      <ChatSessionItem {...baseProps} editing editValue="" onEditChange={onEditChange} />,
    )
    await user.type(screen.getByRole('textbox'), 'new name')
    expect(onEditChange).toHaveBeenCalled()
  })

  it('editing 模式点击 item 不触发 onClick', async () => {
    const user = userEvent.setup()
    const onClick = vi.fn()
    renderWithProviders(
      <ChatSessionItem {...baseProps} editing editValue="x" onClick={onClick} />,
    )
    await user.click(screen.getByRole('textbox'))
    expect(onClick).not.toHaveBeenCalled()
  })

  it('有 channelLabel 时显示频道标签', () => {
    renderWithProviders(
      <ChatSessionItem {...baseProps} channelKey="dingtalk" channelLabel="DingTalk" />,
    )
    expect(screen.getByText('DingTalk')).toBeInTheDocument()
  })

  it('无 channelLabel 时不显示频道区域', () => {
    renderWithProviders(<ChatSessionItem {...baseProps} />)
    expect(screen.queryByTitle(/.*/)).not.toBeInTheDocument()
  })
})
