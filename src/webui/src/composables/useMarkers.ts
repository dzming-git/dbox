// 精彩片段标记（用户个人时间戳）能力，从 Video.vue 抽离为独立 composable。
// 依赖底层 <video> 的 currentTime / duration，由父组件把这两个响应式值传进来，
// 以保持「观看进度上报」(onTimeUpdate -> reportHistory) 与标记功能共享同一 currentTime。
import { ref, computed, type Ref, type ComputedRef } from 'vue'
import type { VideoMarker } from '../types'

export interface UseMarkersOptions {
  /** 播放器当前时间（由父组件的 timeupdate 监听写入，标记「当前位置」与进度上报共用） */
  currentTime: Ref<number>
  /** 视频时长（computed，优先取 <video>.duration，回退后端 video.duration） */
  videoDuration: ComputedRef<number>
  /** 取当前视频 hash（接口路径用）；视频未加载时返回 undefined */
  getHash: () => string | undefined
  /** 取底层 <video> 元素，用于跳转播放 */
  getPlayer: () => HTMLVideoElement | null
}

export function useMarkers(opts: UseMarkersOptions) {
  const { currentTime, videoDuration, getHash, getPlayer } = opts

  const markers = ref<VideoMarker[]>([])
  const showMarkerForm = ref(false)
  const markerNote = ref('')

  const markerTrack = computed(() => {
    if (!videoDuration.value) return []
    return markers.value
      .filter((m) => m.time_seconds >= 0 && m.time_seconds <= videoDuration.value)
      .map((m) => ({
        id: m.id,
        time: m.time_seconds,
        note: m.note || '精彩片段',
        left: (m.time_seconds / videoDuration.value) * 100,
      }))
  })

  const seekTo = (time: number) => {
    const player = getPlayer()
    if (player) {
      player.currentTime = time
      player.play().catch(() => {})
    }
  }

  const formatTime = (sec: number) => {
    const s = Math.max(0, Math.floor(sec || 0))
    const m = Math.floor(s / 60)
    const r = s % 60
    const h = Math.floor(m / 60)
    const mm = h > 0 ? String(m % 60).padStart(2, '0') : String(m)
    const ss = String(r).padStart(2, '0')
    return h > 0 ? `${h}:${mm}:${ss}` : `${mm}:${ss}`
  }

  const formatMarkerTime = (sec: number) => {
    const s = Math.max(0, Math.floor(sec))
    const m = Math.floor(s / 60)
    const r = s % 60
    return `${m}:${r.toString().padStart(2, '0')}`
  }

  const _tokenHeaders = (): Record<string, string> => {
    const token = localStorage.getItem('token')
    const h: Record<string, string> = {}
    if (token) h['Authorization'] = `Bearer ${token}`
    return h
  }

  const loadMarkers = async () => {
    const hash = getHash()
    if (!hash) return
    try {
      const res = await fetch(`/api/video/${hash}/markers`, { headers: _tokenHeaders() })
      if (res.ok) markers.value = await res.json()
    } catch (e) {
      console.error('加载精彩片段标记失败', e)
    }
  }

  const startAddMarker = () => {
    markerNote.value = ''
    showMarkerForm.value = true
  }

  const cancelAddMarker = () => {
    showMarkerForm.value = false
    markerNote.value = ''
  }

  const submitMarker = async () => {
    const hash = getHash()
    if (!hash) return
    const time = getPlayer()?.currentTime ?? 0
    try {
      const headers: Record<string, string> = { 'Content-Type': 'application/json', ..._tokenHeaders() }
      const res = await fetch(`/api/video/${hash}/markers`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ time, note: markerNote.value.trim() }),
      })
      if (res.ok) {
        await loadMarkers()
        cancelAddMarker()
      }
    } catch (e) {
      console.error('添加精彩片段标记失败', e)
    }
  }

  const jumpToMarker = (time: number) => seekTo(time)

  const deleteMarker = async (id: number) => {
    const hash = getHash()
    if (!hash) return
    try {
      const res = await fetch(`/api/video/${hash}/markers/${id}`, {
        method: 'DELETE',
        headers: _tokenHeaders(),
      })
      if (res.ok) markers.value = markers.value.filter((m) => m.id !== id)
    } catch (e) {
      console.error('删除精彩片段标记失败', e)
    }
  }

  return {
    markers,
    showMarkerForm,
    markerNote,
    markerTrack,
    seekTo,
    formatTime,
    formatMarkerTime,
    loadMarkers,
    startAddMarker,
    cancelAddMarker,
    submitMarker,
    jumpToMarker,
    deleteMarker,
  }
}
