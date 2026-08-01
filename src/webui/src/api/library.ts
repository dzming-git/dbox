// 资源库相关 API
import api from './client'

export const libraryApi = {
  getLibraries: () => api.get('/api/my-libraries'),
  getLibrary: (id: number) => api.get(`/api/library/${id}`),
  createLibrary: (data: {
    name: string
    path?: string
    library_type?: 'video' | 'gallery' | 'mixed'
    cover?: string
    scan_directories?: Array<Record<string, unknown>>
    supported_formats?: string[]
    default_tags?: string[]
    tags?: string[]
    description?: string
  }) => api.post('/api/libraries', data),
  deleteLibrary: (id: number) => api.delete(`/api/library/${id}`),
  updateLibrary: (id: number, data: Record<string, unknown>) => api.put(`/api/library/${id}`, data),
  getLibraryVideos: (id: number, params?: Record<string, unknown>) =>
    api.get(`/api/library/${id}/videos`, { params }),
  getLibraryGalleries: (id: number, params?: Record<string, unknown>) =>
    api.get(`/api/library/${id}/galleries`, { params }),
  addScanDirectory: (id: number, directory: string) =>
    api.post(`/api/library/${id}/scan-directory`, { directory }),
  removeScanDirectory: (id: number, directory: string) =>
    api.delete(`/api/library/${id}/scan-directory`, { data: { directory } }),
  scanLibrary: (id: number) => api.post(`/api/library/${id}/scan`, {}),
  browseDirectories: (path?: string) => api.get('/api/browse-directories', { params: { path } }),
  getScanProgress: (id: number) => api.get(`/api/library/${id}/scan-progress`)
}

export const logApi = {
  getLog: (params?: Record<string, unknown>) => api.get('/api/log', { params }),
  getErrors: () => api.get('/api/log/errors'),
  getLogFiles: () => api.get('/api/log/files'),
  getStats: () => api.get('/api/log/stats')
}
