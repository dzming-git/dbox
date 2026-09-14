<template>
  <div class="tab-content backup-panel">
    <div class="card">
      <div class="card-header">
        <h3>导出元数据</h3>
      </div>
      <div class="card-body">
        <p class="hint">
          把多年积累的元数据导出成通用格式，留得住也带得走。
          <b>导出包含全部记录</b>（含已停用资源库的内容）——停用库的记录恰恰最该留底。
        </p>
        <div class="export-grid">
          <button
            v-for="k in KINDS"
            :key="k.value"
            class="export-btn"
            :disabled="exporting === k.value"
            @click="doExport(k.value)"
          >
            <span class="export-name">{{ k.label }}</span>
            <span class="export-desc">{{ k.desc }}</span>
            <span v-if="exporting === k.value" class="exporting">导出中…</span>
          </button>
        </div>
      </div>
    </div>

    <div class="card">
      <div class="card-header">
        <h3>换机 / 目录搬家</h3>
      </div>
      <div class="card-body">
        <p class="hint">
          整个目录换了位置（换了盘、换了机器）之后，逐条改路径不现实。
          填旧前缀与新前缀，先<b>试运行</b>看清会改什么，确认后再执行。
          只改索引里的位置，<b>不会移动任何文件</b>。
        </p>
        <div class="remap-form">
          <input v-model="oldPrefix" class="text-input" placeholder="旧前缀，如 D:\Media" />
          <span class="arrow">→</span>
          <input v-model="newPrefix" class="text-input" placeholder="新前缀，如 E:\Media" />
          <button class="btn btn-default" :disabled="remapping || !canRemap" @click="runRemap(true)">
            试运行
          </button>
          <button
            class="btn btn-primary"
            :disabled="remapping || !canRemap || !report || report.would_update === 0"
            @click="confirmRemap"
          >
            执行重映射
          </button>
        </div>

        <div v-if="report" class="report">
          <div class="report-row">
            <span>命中旧前缀：</span><b>{{ report.matched }}</b>
            <span class="sep">·</span>
            <span>新位置存在：</span><b class="ok">{{ report.would_update }}</b>
            <span class="sep">·</span>
            <span>新位置缺失：</span><b class="bad">{{ report.missing_target }}</b>
          </div>
          <div v-if="report.missing_target" class="report-warn">
            新位置缺失的条目会被跳过（不会把索引指向不存在的文件）。
          </div>
          <div v-if="report.samples.length" class="samples">
            <div v-for="(s, i) in report.samples" :key="i" class="sample">
              <span class="sample-flag" :class="s.ok ? 'ok' : 'bad'">{{ s.ok ? '可改' : '跳过' }}</span>
              <span class="sample-title">{{ s.title }}</span>
              <span class="sample-path">{{ s.to }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { backupApi, type BackupKind } from '../api/backup'
import { useToast } from '../composables/useToast'

const { showToast } = useToast()

const KINDS: { value: BackupKind; label: string; desc: string }[] = [
  { value: 'all', label: '全部', desc: '一次导出所有元数据' },
  { value: 'videos', label: '视频索引', desc: '标题 / 路径 / 时长 / 标签' },
  { value: 'tags', label: '标签', desc: '标签体系与分类' },
  { value: 'collections', label: '合集', desc: '合集及其成员路径' },
  { value: 'watchlater', label: '稍后再看', desc: '当前账号的清单' },
  { value: 'history', label: '观看进度', desc: '进度与最近观看时间' },
  { value: 'missing', label: '丢失文件清单', desc: '在库里但磁盘上已没有' },
]

const exporting = ref<BackupKind | ''>('')

function triggerDownload(blob: any, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

function stamp(kind: BackupKind) {
  const d = new Date()
  const p = (n: number) => String(n).padStart(2, '0')
  return `dbox-${kind}-${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}.json`
}

async function doExport(kind: BackupKind) {
  exporting.value = kind
  try {
    const res: any = await backupApi.exportJson(kind)
    triggerDownload(res, stamp(kind))
    showToast('已导出，请查看下载')
  } catch (e: any) {
    showToast(e?.response?.data?.message || '导出失败')
  } finally {
    exporting.value = ''
  }
}

const oldPrefix = ref('')
const newPrefix = ref('')
const remapping = ref(false)
const report = ref<any>(null)

const canRemap = computed(() => !!oldPrefix.value.trim() && !!newPrefix.value.trim())

async function runRemap(dryRun: boolean) {
  if (!canRemap.value) return
  remapping.value = true
  try {
    const res: any = await backupApi.remapPrefix(
      oldPrefix.value.trim(), newPrefix.value.trim(), dryRun
    )
    report.value = res
    if (!dryRun) {
      showToast(`已重映射 ${res?.updated || 0} 条`)
      // 执行后重新试运行一次，刷新展示（此时应当已经没有可改项）
      await runRemap(true)
    }
  } catch (e: any) {
    showToast(e?.response?.data?.message || '操作失败')
  } finally {
    remapping.value = false
  }
}

async function confirmRemap() {
  const n = report.value?.would_update || 0
  if (!confirm(`确定把 ${n} 条记录指向新位置吗？只改索引，不移动文件。`)) return
  await runRemap(false)
}
</script>

<style scoped>
.backup-panel {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.card {
  background: var(--bg-surface);
  border: 1px solid var(--bg-surface-2);
  border-radius: 10px;
  overflow: hidden;
}
.card-header {
  padding: 12px 16px;
  border-bottom: 1px solid var(--bg-surface-2);
}
.card-header h3 {
  margin: 0;
  font-size: 15px;
  color: var(--text-primary);
}
.card-body {
  padding: 14px 16px 18px;
}
.hint {
  margin: 0 0 14px;
  font-size: 13px;
  line-height: 1.7;
  color: var(--text-secondary);
}
.export-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 10px;
}
.export-btn {
  display: flex;
  flex-direction: column;
  gap: 3px;
  text-align: left;
  background: var(--bg-surface-hover);
  border: 1px solid var(--bg-surface-2);
  border-radius: 8px;
  padding: 10px 12px;
  cursor: pointer;
  transition: border-color 0.18s ease, background 0.18s ease;
}
.export-btn:hover:not(:disabled) {
  border-color: var(--accent);
  background: var(--accent-soft);
}
.export-btn:disabled {
  opacity: 0.6;
  cursor: progress;
}
.export-name {
  font-size: 13px;
  color: var(--text-primary);
}
.export-desc {
  font-size: 11px;
  color: var(--text-tertiary);
}
.exporting {
  font-size: 11px;
  color: var(--accent);
}

.remap-form {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.text-input {
  flex: 1 1 220px;
  min-width: 180px;
  background: var(--bg-surface-hover);
  border: 1px solid var(--bg-surface-2);
  border-radius: 8px;
  color: var(--text-primary);
  padding: 7px 10px;
  font-size: 13px;
}
.text-input:focus {
  outline: none;
  border-color: var(--accent);
}
.arrow {
  color: var(--text-tertiary);
}
.btn {
  border-radius: 8px;
  padding: 7px 14px;
  font-size: 13px;
  cursor: pointer;
  border: 1px solid transparent;
}
.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.btn-default {
  background: var(--bg-surface-hover);
  color: var(--text-secondary);
  border-color: var(--bg-surface-2);
}
.btn-primary {
  background: var(--accent);
  color: #fff;
}

.report {
  margin-top: 14px;
  border-top: 1px dashed var(--bg-surface-2);
  padding-top: 12px;
}
.report-row {
  font-size: 13px;
  color: var(--text-secondary);
}
.report-row b {
  color: var(--text-primary);
}
.report-row b.ok {
  color: var(--success, #4caf50);
}
.report-row b.bad {
  color: var(--danger);
}
.sep {
  margin: 0 8px;
  color: var(--text-tertiary);
}
.report-warn {
  margin-top: 6px;
  font-size: 12px;
  color: var(--warning);
}
.samples {
  margin-top: 10px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.sample {
  display: flex;
  gap: 8px;
  align-items: baseline;
  font-size: 12px;
  color: var(--text-tertiary);
}
.sample-flag {
  flex-shrink: 0;
  padding: 1px 6px;
  border-radius: 4px;
  background: var(--bg-surface-hover);
}
.sample-flag.ok {
  color: var(--success, #4caf50);
}
.sample-flag.bad {
  color: var(--danger);
}
.sample-title {
  color: var(--text-secondary);
  flex-shrink: 0;
}
.sample-path {
  word-break: break-all;
}
</style>
