<template>
  <div class="card">
    <h2>候选解对照（只读历史，不按当前拾取重算）</h2>
    <div class="muted" style="margin-bottom:8px">
      选择<b>同一案例、同一震相</b>的两个已保存候选解：后端基于各自保存时的结果、
      输入快照与残差计算水平位置距离、深度/发震时刻/RMS 差与逐台站残差变化。
      P 与 S、或不同案例的结果不能组成一次对照。
    </div>

    <div class="row">
      <label>基准 A
        <select v-model.number="aId" :disabled="busy">
          <option :value="null">— 选择候选解 —</option>
          <option v-for="r in runs" :key="r.id" :value="r.id"
                  :disabled="bId!=null && r.phase!==phaseOf(bId)">
            #{{ r.id }} {{ r.label }} [{{ r.phase }}]{{ r.locatable ? '' : ' · 不可定位' }}
          </option>
        </select>
      </label>
      <button class="sm" :disabled="busy || !ready" title="交换 A、B（差值方向取反）" @click="swap">⇄</button>
      <label>对照 B
        <select v-model.number="bId" :disabled="busy">
          <option :value="null">— 选择候选解 —</option>
          <option v-for="r in runs" :key="r.id" :value="r.id"
                  :disabled="aId!=null && r.phase!==phaseOf(aId)">
            #{{ r.id }} {{ r.label }} [{{ r.phase }}]{{ r.locatable ? '' : ' · 不可定位' }}
          </option>
        </select>
      </label>
      <button class="primary" :disabled="busy || !ready" @click="doCompare">
        {{ busy ? '对照计算中…' : '建立对照' }}
      </button>
      <button v-if="result" class="sm" :disabled="busy" @click="clearCompare">清除对照</button>
    </div>
    <div v-if="guardHint" class="warnbox" style="margin-top:8px">{{ guardHint }}</div>
    <div v-if="error" class="warnbox bad" style="margin-top:8px">{{ error }}</div>

    <template v-if="result">
      <div style="margin-top:8px">
        <div v-for="(n, i) in result.notes" :key="i" class="warnbox"
             :class="noteClass(n)">{{ n }}</div>
      </div>

      <!-- 并列元数据：模型 / 拾取版本 / 排除台站 / 定位状态 -->
      <div class="grid2" style="margin-top:8px">
        <div class="sidebox" :class="{selA:true}">
          <div class="sidehead">
            <span class="tag a">基准 A</span>
            <b>#{{ sa.id }} {{ sa.label }}</b>
            <span class="tag" :class="sa.phase">{{ sa.phase }}</span>
          </div>
          <div v-if="!sa.locatable" class="notlocatable" style="padding:8px 10px">
            ⛔ 不可定位：{{ sa.reason }}
          </div>
          <dl class="kv mono" style="font-size:11.5px">
            <dt>速度模型</dt><dd>{{ sa.model_id }}</dd>
            <dt>拟合方式</dt><dd>{{ sa.robust ? '稳健 soft_l1' : '普通 OLS' }}</dd>
            <dt>拾取版本(哈希)</dt>
            <dd :style="{color: result.pick_version_differs ? 'var(--warn)' : 'inherit'}">
              {{ sa.pick_data_version }}
            </dd>
            <dt>排除台站</dt>
            <dd>{{ sa.excluded_station_codes.length ? sa.excluded_station_codes.join(', ') : '（无）' }}</dd>
            <template v-if="sa.locatable">
              <dt>经度 / 纬度</dt><dd>{{ sa.lon.toFixed(5) }}, {{ sa.lat.toFixed(5) }}</dd>
              <dt>深度</dt><dd>{{ sa.depth_km.toFixed(2) }} km</dd>
              <dt>发震时刻</dt><dd style="font-size:10.5px">{{ fmtEpoch(sa.origin_time_epoch, 2) }}Z</dd>
              <dt>RMS</dt><dd>{{ sa.rms_s.toFixed(3) }} s</dd>
            </template>
            <dt>使用到时</dt><dd>{{ sa.n_used }} 个</dd>
          </dl>
        </div>
        <div class="sidebox">
          <div class="sidehead">
            <span class="tag b">对照 B</span>
            <b>#{{ sb.id }} {{ sb.label }}</b>
            <span class="tag" :class="sb.phase">{{ sb.phase }}</span>
          </div>
          <div v-if="!sb.locatable" class="notlocatable" style="padding:8px 10px">
            ⛔ 不可定位：{{ sb.reason }}
          </div>
          <dl class="kv mono" style="font-size:11.5px">
            <dt>速度模型</dt>
            <dd :style="{color: result.model_differs ? 'var(--warn)' : 'inherit'}">
              {{ sb.model_id }}<span v-if="result.model_differs" class="tag warn" style="margin-left:4px">模型不同</span>
            </dd>
            <dt>拟合方式</dt>
            <dd>{{ sb.robust ? '稳健 soft_l1' : '普通 OLS' }}
              <span v-if="result.robust_differs" class="tag warn" style="margin-left:4px">方式不同</span></dd>
            <dt>拾取版本(哈希)</dt>
            <dd :style="{color: result.pick_version_differs ? 'var(--warn)' : 'inherit'}">
              {{ sb.pick_data_version }}
              <span v-if="result.pick_version_differs" class="tag warn" style="margin-left:4px">版本不同</span>
            </dd>
            <dt>排除台站</dt>
            <dd>{{ sb.excluded_station_codes.length ? sb.excluded_station_codes.join(', ') : '（无）' }}</dd>
            <template v-if="sb.locatable">
              <dt>经度 / 纬度</dt><dd>{{ sb.lon.toFixed(5) }}, {{ sb.lat.toFixed(5) }}</dd>
              <dt>深度</dt><dd>{{ sb.depth_km.toFixed(2) }} km</dd>
              <dt>发震时刻</dt><dd style="font-size:10.5px">{{ fmtEpoch(sb.origin_time_epoch, 2) }}Z</dd>
              <dt>RMS</dt><dd>{{ sb.rms_s.toFixed(3) }} s</dd>
            </template>
            <dt>使用到时</dt><dd>{{ sb.n_used }} 个</dd>
          </dl>
        </div>
      </div>

      <!-- 汇总差值（B − A） -->
      <h3>差异汇总（B 相对 A）</h3>
      <table>
        <thead><tr>
          <th>指标</th><th>基准 A</th><th>对照 B</th><th>差值 (B − A)</th>
        </tr></thead>
        <tbody>
          <tr>
            <td style="text-align:left">水平位置距离</td>
            <td>{{ sa.locatable ? `(${sa.lon.toFixed(4)}, ${sa.lat.toFixed(4)})` : '—' }}</td>
            <td>{{ sb.locatable ? `(${sb.lon.toFixed(4)}, ${sb.lat.toFixed(4)})` : '—' }}</td>
            <td v-if="result.horizontal_distance_km!=null" class="res-neg" style="font-weight:650">
              {{ result.horizontal_distance_km.toFixed(3) }} km
            </td>
            <td v-else><span class="tag bad">不可比较</span></td>
          </tr>
          <tr>
            <td style="text-align:left">深度</td>
            <td>{{ sa.locatable ? sa.depth_km.toFixed(2) + ' km' : '—' }}</td>
            <td>{{ sb.locatable ? sb.depth_km.toFixed(2) + ' km' : '—' }}</td>
            <td v-if="result.depth_delta_km!=null" :class="deltaClass(result.depth_delta_km)">
              {{ signed(result.depth_delta_km) }} km
            </td>
            <td v-else><span class="tag bad">不可比较</span></td>
          </tr>
          <tr>
            <td style="text-align:left">发震时刻</td>
            <td>{{ sa.locatable ? fmtEpoch(sa.origin_time_epoch, 2) : '—' }}</td>
            <td>{{ sb.locatable ? fmtEpoch(sb.origin_time_epoch, 2) : '—' }}</td>
            <td v-if="result.origin_time_delta_s!=null" :class="deltaClass(result.origin_time_delta_s)">
              {{ signed(result.origin_time_delta_s) }} s
            </td>
            <td v-else><span class="tag bad">不可比较</span></td>
          </tr>
          <tr>
            <td style="text-align:left">RMS 残差</td>
            <td>{{ sa.locatable ? sa.rms_s.toFixed(3) + ' s' : '—' }}</td>
            <td>{{ sb.locatable ? sb.rms_s.toFixed(3) + ' s' : '—' }}</td>
            <td v-if="result.rms_delta_s!=null"
                :class="result.rms_delta_s <= 0 ? 'res-ok' : 'res-pos'">
              {{ signed(result.rms_delta_s) }} s
              <span class="muted">{{ result.rms_delta_s <= 0 ? '（拟合改善）' : '（拟合变差）' }}</span>
            </td>
            <td v-else><span class="tag bad">不可比较</span></td>
          </tr>
        </tbody>
      </table>

      <!-- 逐台站残差变化 -->
      <h3>各台站残差变化（保存值，观测 − 理论到时）</h3>
      <div class="scroll">
        <table>
          <thead><tr>
            <th>台站</th>
            <th>A 参与情况</th><th>A 残差(s)</th>
            <th>B 参与情况</th><th>B 残差(s)</th>
            <th>Δ残差 B−A(s)</th><th>Δ观测到时(s)</th>
          </tr></thead>
          <tbody>
            <tr v-for="row in result.station_changes" :key="row.station_code"
                :class="{suspect: Math.abs(row.residual_delta_s ?? 0) > 0.6}">
              <td>{{ row.station_code }}</td>
              <td><span class="tag" :class="statusTag(row.status_a)">{{ statusText(row.status_a) }}</span></td>
              <td>{{ fmtRes(row.residual_a_s) }}</td>
              <td><span class="tag" :class="statusTag(row.status_b)">{{ statusText(row.status_b) }}</span></td>
              <td>{{ fmtRes(row.residual_b_s) }}</td>
              <td v-if="row.residual_delta_s!=null"
                  :class="deltaClass(row.residual_delta_s)" style="font-weight:650">
                {{ signed(row.residual_delta_s) }}
              </td>
              <td v-else class="muted">—</td>
              <td v-if="row.observed_delta_s!=null"
                  :class="Math.abs(row.observed_delta_s) > 0.05 ? 'res-neg' : 'res-ok'">
                {{ signed(row.observed_delta_s) }}
              </td>
              <td v-else class="muted">—</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="muted" style="margin-top:4px">
        「Δ观测到时」是两次保存的输入快照中该台站有效到时之差：人工修订会体现为非零值；
        残差变化 = 解的位置/时刻变化与拾取变化共同造成。排除/缺测台站不参与该次反演，无残差可比。
      </div>
    </template>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { api, fmtEpoch } from '../lib/api.js'

const props = defineProps({
  runs: { type: Array, default: () => [] },
  scenarioKey: { type: String, default: '' },
})
const emit = defineEmits(['pair'])

const aId = ref(null)
const bId = ref(null)
const busy = ref(false)
const error = ref('')
const result = ref(null)

const ready = computed(() =>
  aId.value != null && bId.value != null && aId.value !== bId.value)

const guardHint = computed(() => {
  if (aId.value == null || bId.value == null) return ''
  if (aId.value === bId.value) return '请选择两个不同的候选解。'
  const pa = phaseOf(aId.value), pb = phaseOf(bId.value)
  if (pa && pb && pa !== pb) {
    return `不能跨震相对照：#${aId.value} 是 ${pa} 解、#${bId.value} 是 ${pb} 解，` +
      'P、S 速度与残差含义不同。请在同一震相内选择。'
  }
  return ''
})

watch(() => props.scenarioKey, reset)
watch(() => props.runs, (rows) => {
  const ids = new Set(rows.map(r => r.id))
  if (aId.value != null && !ids.has(aId.value)) aId.value = null
  if (bId.value != null && !ids.has(bId.value)) bId.value = null
  if (!ready.value) clearCompare()
})

function reset() {
  aId.value = null
  bId.value = null
  clearCompare()
}

function clearCompare() {
  result.value = null
  error.value = ''
  emit('pair', null)
}

function phaseOf(id) {
  return props.runs.find(r => r.id === id)?.phase
}

function swap() {
  const t = aId.value
  aId.value = bId.value
  bId.value = t
  if (result.value) doCompare()
}

async function doCompare() {
  if (!ready.value || guardHint.value) return
  busy.value = true
  error.value = ''
  try {
    const cmp = await api.compareRuns(aId.value, bId.value)
    result.value = cmp
    // 供地图并列标注（side 结构与 run 形状兼容）
    emit('pair', { a: sideForMap(cmp.side_a), b: sideForMap(cmp.side_b) })
  } catch (e) {
    result.value = null
    emit('pair', null)
    error.value = String(e.message || e)
  } finally {
    busy.value = false
  }
}

function sideForMap(s) {
  return {
    id: s.id, label: s.label, phase: s.phase, locatable: s.locatable,
    lon: s.lon, lat: s.lat, uncertainty: s.uncertainty,
  }
}

const sa = computed(() => result.value?.side_a)
const sb = computed(() => result.value?.side_b)

function signed(v) {
  return (v >= 0 ? '+' : '') + Number(v).toFixed(3)
}
function fmtRes(v) {
  if (v == null) return '—'
  return signed(v)
}
function deltaClass(v) {
  if (v == null) return ''
  if (Math.abs(v) <= 0.05) return 'res-ok'
  return 'res-neg'
}
const STATUS = {
  located: ['good', '参与反演'],
  excluded: ['warn', '用户排除'],
  missing: ['missing', '缺测'],
  not_locatable: ['bad', '整体不可定位'],
}
function statusText(s) { return STATUS[s]?.[1] ?? s ?? '—' }
function statusTag(s) { return STATUS[s]?.[0] ?? '' }
function noteClass(n) {
  if (n.includes('不可定位') || n.includes('不能')) return 'bad'
  if (n.includes('不同') || n.includes('版本')) return ''
  return 'good'
}
</script>

<style scoped>
.sidebox {
  border: 1px solid var(--border);
  border-radius: 7px;
  padding: 8px 10px;
  background: var(--panel2);
}
.sidebox.selA { border-color: rgba(210, 153, 34, .55); }
.sidehead { display: flex; align-items: center; gap: 6px; margin-bottom: 6px; }
.tag.a { color: #1a1a1a; background: var(--warn); border-color: var(--warn); }
.tag.b { color: #fff; background: #8957e5; border-color: #8957e5; }
</style>
