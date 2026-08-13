import { api } from './index'
import type { Issue, IssueListResponse } from '../types'

export interface IssueListParams {
  status?: 'open' | 'in_progress' | 'pending' | 'pending_verification' | 'closed' | 'all'
  type?: IssueType | 'all'
  keyword?: string
  page?: number
  page_size?: number
}

export function extractMessage(err: any, fallback = '操作失败'): string {
  if (err?.response?.data?.message) return err.response.data.message
  if (err?.response?.data?.error) return err.response.data.error
  if (err?.message) return err.message
  return fallback
}

export async function getIssues(params: IssueListParams = {}): Promise<IssueListResponse> {
  return await api.get('/api/suggestion', { params })
}

export async function getIssue(id: string): Promise<{ success: boolean; issue: Issue }> {
  return await api.get(`/api/suggestion/${id}`)
}

export async function createIssue(payload: {
  title: string
  content: string
  type?: IssueType
  contact?: string
}): Promise<{ success: boolean; id: string; issue: Issue }> {
  return await api.post('/api/suggestion', payload)
}

export async function updateIssue(
  id: string,
  payload: {
    status?: 'open' | 'in_progress' | 'pending' | 'pending_verification' | 'closed'
    closed_reason?: 'resolved' | 'dismissed' | null
    title?: string
    content?: string
  }
): Promise<{ success: boolean; issue: Issue }> {
  return await api.put(`/api/suggestion/${id}`, payload)
}

export async function addIssueComment(
  id: string,
  payload: { content: string }
): Promise<{ success: boolean; issue: Issue }> {
  return await api.post(`/api/suggestion/${id}/comment`, payload)
}

// 回复并重新打开（原子操作）：一次性追加回复 + 置为 open，仅产生 1 个状态变更事件
export async function replyAndReopen(
  id: string,
  payload: { content: string }
): Promise<{ success: boolean; issue: Issue }> {
  return await api.post(`/api/suggestion/${id}/reply_reopen`, payload)
}

// 验证完成并关闭（原子操作）：可选追加回复 + 置为 closed（已解决），仅产生 1 个状态变更事件
export async function verifyClose(
  id: string,
  payload?: { content?: string }
): Promise<{ success: boolean; issue: Issue }> {
  return await api.post(`/api/suggestion/${id}/verify_close`, payload || {})
}

// 删除反馈单（含全部评论），仅管理员可操作
export async function deleteIssue(id: string): Promise<{ success: boolean }> {
  return await api.delete(`/api/suggestion/${id}`)
}
