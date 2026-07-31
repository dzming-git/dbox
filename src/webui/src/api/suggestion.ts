import api from './index'
import type { Issue, IssueListResponse } from '../types'

export interface IssueListParams {
  status?: 'open' | 'pending' | 'closed' | 'all'
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
    status?: 'open' | 'pending' | 'closed'
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
