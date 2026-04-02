/**
 * 建议反馈 API
 */

interface Suggestion {
  id: string
  content: string
  contact?: string
  user: string
  created_at: string
  status: 'pending' | 'reviewed' | 'replied'
  reply?: string
}

interface SubmitResponse {
  success: boolean
  message?: string
  suggestion_id?: string
  error?: string
}

interface ListResponse {
  success: boolean
  suggestions: Suggestion[]
  total: number
  error?: string
}

/**
 * 提交建议
 */
export async function submitSuggestion(content: string, contact?: string): Promise<SubmitResponse> {
  const response = await fetch('/api/suggestion', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({ content, contact })
  })
  return response.json()
}

/**
 * 获取建议列表（管理员）
 */
export async function getSuggestions(): Promise<ListResponse> {
  const response = await fetch('/api/suggestion/list')
  return response.json()
}

/**
 * 更新建议状态（管理员）
 */
export async function updateSuggestion(
  suggestionId: string,
  data: { status?: string; reply?: string }
): Promise<{ success: boolean; error?: string }> {
  const response = await fetch(`/api/suggestion/${suggestionId}`, {
    method: 'PUT',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify(data)
  })
  return response.json()
}