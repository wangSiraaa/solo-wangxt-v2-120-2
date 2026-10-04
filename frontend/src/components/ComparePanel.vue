<template>
  <div class="card compare-panel">
    <div class="row" style="justify-content:space-between">
      <h2>候选解对照（只读历史，不按当前拾取重算）</h2>
      <button class="sm" @click="$emit('close')">关闭对照</button>
    </div>
    <div class="muted" style="margin:4px 0 8px">
      所有数值直接取自两个候选解<b>保存时</b>的坐标、残差与输入快照；
      差异定义为 <b>A − B</b>（A 相对 B 的变化）。即使某解已被后续修订标记为「过期」，
      这里呈现的仍是当时保存的结果。
    </div>

    <!-- 模型不同提示 -->
    <div class="warnbox" :class="cmp.model_differs ? 'bad' : 'good'">
      <b>{{ cmp.model_differs ? '⚠ 两个候选解速度模型不同' : '✓ 同一速度模型' }}</b>：
      {{ cmp.model_note }}
    </div>

    <!-- 不可定位原因 -->
    <div v-for="(reason, i) in cmp.not_locatable_reasons" :key="i" class="notlocatable" style="margin:6px 0">
      <div style="font-weight:650;margin-bottom:2px">⛔ 该候选保存时即判定不可定位</div>
      <div>{{ reason }}</div>
    </div>
    <div v-if="cmp.not_comparable_reason" class="warnbox bad">
      {{ cmp.not_comparable_reason }}
    </div>

    <!-- 并列：两个候选的元信息 -->
    <div class="compare-cols">
      <div class="compare-side side-a">
        <h3>候选 A #{{ a.id }} {{ a.label }}</h3>
        <dl class="kv mono" style="font-size:11.5px">
          <dt>状态</dt>
          <dd>
            <span v-if="a.locatable" class="tag good">已定位</span>
            <span v-else class="tag bad">不可定位</span>
            <span class="tag" :class="a.phase">{{ a.phase }}</span>
            <span v-if="a.robust" class="tag warn">稳健</span>
          </dd>
          <dt>速度模型</dt><dd class="cmp-model">{{ modelName(a.model_id) }}</dd>
          <dt>模型 ID</dt><dd>{{ a.model_id }}</dd>
          <dt>拾取版本</dt>
          <dd :class="pickVersionClass('a')" :title="pickVersionTitle('a')">
            {{ a.pick_data_version }}
            <span v-if="cmp.inputs.pick_versions_differ" class="tag warn">与 B 不同</span>
          </dd>
          <dt>排除台站</dt>
          <dd>
            <span v-if="!a.excludes.length" class="muted">无</span>
            <span v-else class="tag bad">{{ excludedStations('a').join(', ') }}</span>
          </dd>
          <dt>坐标</dt>
          <dd v-if="a.locatable">{{ a.lon?.toFixed(4) }}, {{ a.lat?.toFixed(4) }}</dd>
          <dd v-else class="muted">不可比较（无坐标）</dd>
          <dt>深度 / RMS</dt>
          <dd v-if="a.locatable">{{ a.depth_km?.toFixed(2) }} km / {{ a.rms_s?.toFixed(3) }} s</dd>
          <dd v-else class="muted">—</dd>
        </dl>
      </div>

      <div class="compare-side side-b">
        <h3>候选 B #{{ b.id }} {{ b.label }}</h3>
        <dl class="kv mono" style="font-size:11.5px">
          <dt>状态</dt>
          <dd>
            <span v-if="b.locatable" class="tag good">已定位</span>
            <span v-else class="tag bad">不可定位</span>
            <span class="tag" :class="b.phase">{{ b.phase }}</span>
            <span v-if="b.robust" class="tag warn">稳健</span>
          </dd>
          <dt>速度模型</dt><dd class="cmp-model">{{ modelName(b.model_id) }}</dd>
          <dt>模型 ID</dt><dd>{{ b.model_id }}</dd>
          <dt>拾取版本</dt>
          <dd :class="pickVersionClass('b')" :title="pickVersionTitle('b')">
            {{ b.pick_data_version }}
            <span v-if="cmp.inputs.pick_versions_differ" class="tag warn">与 A 不同</span>
          </dd>
          <dt>排除台站</dt>
          <dd>
            <span v-if="!b.excludes.length" class="muted">无</span>
            <span v-else class="tag bad">{{ excludedStations('b').join(', ') }}</span>
          </dd>
          <dt>坐标</dt>
          <dd v-if="b.locatable">{{ b.lon?.toFixed(4) }}, {{ b.lat?.toFixed(4) }}</dd>
          <dd v-else class="muted">不可比较（无坐标）</dd>
          <dt>深度 / RMS</dt>
          <dd v-if="b.locatable">{{ b.depth_km?.toFixed(2) }} km / {{ b.rms_s?.toFixed(3) }} s</dd>
          <dd v-else class="muted">—</dd>
        </dl>
      </div>
    </div>

    <!-- 差异指标 -->
    <h3>量化差异（A − B）</h3>
    <table class="metrics-table">
      <thead>
        <tr><th style="text-align:left">指标</th><th>含义</th><th>差值</th></tr>
      </thead>
      <tbody>
        <tr>
          <td style="text-align:left">水平位置距离</td>
          <td class="muted">两个解震中的水平距离（局部切平面投影，与定位同投影）；另有 E/N 分量与 A 相对 B 的方位</td>
          <td>
            <template v-if="m.horizontal_distance_km != null">
              <b>{{ fmt(m.horizontal_distance_km, 2) }} km</b>
              <span class="muted">
                （E {{ signed(m.horizontal_dx_km, 2) }} / N {{ signed(m.horizontal_dy_km, 2) }} km，
                方位 {{ m.bearing_deg?.toFixed(0) }}°）
              </span>
            </template>
            <span v-else class="tag bad">不可比较</span>
          </td>
        </tr>
        <tr>
          <td style="text-align:left">深度差</td>
          <td class="muted">A 深度 − B 深度，正值表示 A 更深</td>
          <td>
            <span v-if="m.depth_delta_km != null"><b :class="deltaClass(m.depth_delta_km)">{{ signed(m.depth_delta_km, 2) }} km</b></span>
            <span v-else class="tag bad">不可比较</span>
          </td>
        </tr>
        <tr>
          <td style="text-align:left">发震时刻差</td>
          <td class="muted">A t₀ − B t₀，正值表示 A 的发震时刻更晚</td>
          <td>
            <span v-if="m.origin_time_delta_s != null"><b :class="deltaClass(m.origin_time_delta_s)">{{ signed(m.origin_time_delta_s, 2) }} s</b></span>
            <span v-else class="tag bad">不可比较</span>
          </td>
        </tr>
        <tr>
          <td style="text-align:left">RMS 残差变化</td>
          <td class="muted">A RMS − B RMS；负值表示 A 整体拟合更好</td>
          <td>
            <span v-if="m.rms_delta_s != null"><b :class="deltaClass(m.rms_delta_s)">{{ signed(m.rms_delta_s, 3) }} s</b></span>
            <span v-else class="tag bad">不可比较</span>
          </td>
        </tr>
        <tr>
          <td style="text-align:left">最大绝对残差变化</td>
          <td class="muted">A max|残差| − B max|残差|</td>
          <td>
            <span v-if="m.max_abs_residual_delta_s != null"><b :class="deltaClass(m.max_abs_residual_delta_s)">{{ signed(m.max_abs_residual_delta_s, 2) }} s</b></span>
            <span v-else class="tag bad">不可比较</span>
          </td>
        </tr>
      </tbody>
    </table>

    <!-- 并列地图 -->
    <h3>地图位置对照</h3>
    <div ref="mapNode" style="height:380px"></div>

    <!-- 输入差异小结 -->
    <h3>所用台站 / 输入差异</h3>
    <div class="grid2">
      <dl class="kv">
        <dt>使用到时数 A / B</dt><dd>{{ inp.n_used_a }} / {{ inp.n_used_b }}</dd>
        <dt>拟合方式</dt>
        <dd>{{ inp.robust_a ? '稳健 soft_l1' : '普通 OLS' }} /
            {{ inp.robust_b ? '稳健 soft_l1' : '普通 OLS' }}</dd>
      </dl>
      <dl class="kv">
        <dt>仅 A 使用</dt>
        <dd>{{ pickStationList(inp.used_only_a) || '—' }}</dd>
        <dt>仅 B 使用</dt>
        <dd>{{ pickStationList(inp.used_only_b) || '—' }}</dd>
      </dl>
    </div>
    <div v-if="inp.pick_versions_differ" class="warnbox" style="margin-top:6px">
      两个候选基于<b>不同版本的拾取内容</b>（人工修订或排除变化会改变拾取版本哈希）：
      残差与位置差异可由此解释；本对照不会用当前拾取重算任何一边。
    </div>

    <!-- 逐台站残差变化 -->
    <h3>逐台站残差变化（保存值）</h3>
    <div class="scroll">
      <table>
        <thead>
          <tr>
            <th>台站</th>
            <th><span class="tag" :class="a.phase">A 来源</span></th>
            <th><span class="tag" :class="b.phase">B 来源</span></th>
            <th>A 残差(s)</th>
            <th>B 残差(s)</th>
            <th>残差变化 A−B(s)</th>
            <th>观测到时差 A−B(s)</th>
            <th>A 状态</th>
            <th>B 状态</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in cmp.station_comparison" :key="row.pick_id"
              :class="{suspect: row.flag_a==='suspect' || row.flag_b==='suspect'}">
            <td>{{ row.station_code }}</td>
            <td><span class="tag" :class="srcClass(row.time_source_a)">{{ srcText(row.time_source_a) }}</span></td>
            <td><span class="tag" :class="srcClass(row.time_source_b)">{{ srcText(row.time_source_b) }}</span></td>
            <td :class="resClass(row.residual_s_a)">{{ fmtNullable(row.residual_s_a) }}</td>
            <td :class="resClass(row.residual_s_b)">{{ fmtNullable(row.residual_s_b) }}</td>
            <td>
              <span v-if="row.residual_delta_s != null"
                    :class="deltaClass(row.residual_delta_s)" style="font-weight:650">
                {{ signed(row.residual_delta_s, 2) }}
              </span>
              <span v-else class="muted">—</span>
            </td>
            <td>
              <span v-if="row.observed_delta_s != null"
                    :class="deltaClass(row.observed_delta_s)">
                {{ signed(row.observed_delta_s, 2) }}
              </span>
              <span v-else class="muted">—</span>
            </td>
            <td><span class="tag" :class="statusClass(row.status_a)">{{ statusText(row.status_a) }}</span></td>
            <td><span class="tag" :class="statusClass(row.status_b)">{{ statusText(row.status_b) }}</span></td>
          </tr>
        </tbody>
      </table>
    </div>
    <div class="muted" style="margin-top:4px">
      「观测到时差 A−B」= 两边保存的观测到时之差（人工修订/排除都会体现）；
      残差 = 观测到时 − 该候选保存模型下的理论到时，任一边未参与定位（缺测/排除/不可定位）时记为 —。
    </div>
  </div>
</template>

<script setup>
import { ref, computed, nextTick, onMounted, watch } from 'vue'
import Plotly from 'plotly.js-dist-min'
import { kmToDeg } from '../lib/api.js'

const props = defineProps({
  cmp: { type: Object, required: true },
  stations: { type: Array, default: () => [] },
  models: { type: Array, default: () => [] },
})
defineEmits(['close'])

const cmp = computed(() => props.cmp)
const a = computed(() => cmp.value.run_a)
const b = computed(() => props.cmp.run_b)
const m = computed(() => cmp.value.metrics)
const inp = computed(() => cmp.value.inputs)

function modelName(id) {
  return props.models.find(x => x.model_id === id)?.name || id
}

// pick_id -> station_code（从对照行取，避免依赖当前拾取表）
const pickStationMap = computed(() => {
  const map = new Map()
  for (const r of cmp.value.station_comparison) map.set(r.pick_id, r.station_code)
  return map
})
function pickStationList(ids) {
  const codes = ids.map(i => pickStationMap.value.get(i)).filter(Boolean)
  return codes.join(', ')
}
function excludedStations(side) {
  const run = side === 'a' ? a.value : b.value
  return run.excludes.map(i => pickStationMap.value.get(i)).filter(Boolean)
}

function pickVersionClass(side) {
  if (!cmp.value.inputs.pick_versions_differ) return ''
  return side === 'a' ? 'cmp-a-text' : 'cmp-b-text'
}
function pickVersionTitle(side) {
  if (!cmp.value.inputs.pick_versions_differ) return '两边基于相同版本的拾取内容'
  const other = side === 'a' ? 'B' : 'A'
  return `与候选 ${other} 的拾取内容版本不同（拾取被修订或排除台站变化）`
}

function fmt(v, d = 2) { return v == null ? '—' : Number(v).toFixed(d) }
function signed(v, d = 2) { return v == null ? '—' : (v >= 0 ? '+' : '') + Number(v).toFixed(d) }
function fmtNullable(v) { return v == null ? '—' : Number(v).toFixed(2) }
function deltaClass(v) {
  if (v == null || Math.abs(v) < 0.05) return 'res-ok'
  if (Math.abs(v) > 0.6) return 'res-pos'
  return 'res-neg'
}
function resClass(v) {
  if (v == null) return 'muted'
  if (Math.abs(v) > 0.6) return 'res-pos'
  if (Math.abs(v) > 0.3) return 'res-neg'
  return 'res-ok'
}
function srcText(s) { return s === 'manual' ? '人工' : s === 'raw' ? '原始' : '缺测' }
function srcClass(s) { return s === 'manual' ? 'manual' : s === 'raw' ? 'raw' : 'missing' }
function statusText(s) { return { used: '使用', excluded: '排除', missing: '缺测' }[s] || s }
function statusClass(s) { return s === 'used' ? 'good' : s === 'excluded' ? 'bad' : 'missing' }

// —— 并列地图：台站 + 真值由 App 地图展示，这里聚焦两个解与保存的误差椭圆 ——
const mapNode = ref(null)

function ellipseLonLat(run) {
  const u = run.uncertainty
  if (!u || run.lon == null) return null
  const [ax, bx] = u.ellipse_semi_axes_km
  const az = (u.ellipse_major_axis_azimuth_deg ?? 0) * Math.PI / 180
  const lon = [], lat = []
  for (let i = 0; i <= 64; i++) {
    const th = (i / 64) * 2 * Math.PI
    const dx = ax * Math.cos(th) * Math.cos(az) - bx * Math.sin(th) * Math.sin(az)
    const dy = ax * Math.cos(th) * Math.sin(az) + bx * Math.sin(th) * Math.cos(az)
    const [dlo, dla] = kmToDeg(dx, dy, run.lat)
    lon.push(run.lon + dlo)
    lat.push(run.lat + dla)
  }
  return { lon, lat }
}

function redraw() {
  if (!mapNode.value) return
  const traces = []
  traces.push({
    x: props.stations.map(s => s.lon),
    y: props.stations.map(s => s.lat),
    text: props.stations.map(s => s.code),
    type: 'scatter', mode: 'markers+text',
    marker: { symbol: 'triangle-down', size: 10, color: '#f85149' },
    textposition: 'top center', textfont: { size: 9, color: '#f85149' },
    name: '台站', hovertemplate: '%{text}<extra></extra>',
  })

  const locRuns = [['A', a.value, '#58a6ff'], ['B', b.value, '#d29922']]
  const points = []
  for (const [tag, run, color] of locRuns) {
    if (!run.locatable) continue
    const e = ellipseLonLat(run)
    if (e) traces.push({
      x: e.lon, y: e.lat, type: 'scatter', mode: 'lines',
      line: { color, width: 1.5 }, fill: 'toself', fillcolor: color + '22',
      showlegend: false, hoverinfo: 'skip',
    })
    traces.push({
      x: [run.lon], y: [run.lat], text: [`候选 ${tag} #${run.id}`],
      type: 'scatter', mode: 'markers+text',
      marker: { symbol: 'diamond', size: 13, color, line: { color: '#0d1117', width: 1 } },
      textposition: 'middle right', textfont: { size: 11, color },
      name: `候选 ${tag}`,
      hovertemplate: `候选 ${tag} #${run.id} ${run.label}` +
        `<br>(%{x:.4f}, %{y:.4f})<extra></extra>`,
    })
    points.push([run.lon, run.lat])
  }
  // A-B 连线，直观显示水平偏移
  if (points.length === 2) {
    traces.push({
      x: [points[0][0], points[1][0]], y: [points[0][1], points[1][1]],
      type: 'scatter', mode: 'lines+markers',
      line: { color: '#c9d4e0', width: 1.5, dash: 'dashdot' },
      marker: { size: 1 },
      name: `距离 ${m.value.horizontal_distance_km?.toFixed(2) ?? '—'} km`,
      hoverinfo: 'name',
    })
  }

  const allX = traces.flatMap(t => t.x || [])
  const allY = traces.flatMap(t => t.y || [])
  let xrange = null, yrange = null
  if (allX.length) {
    const x0 = Math.min(...allX), x1 = Math.max(...allX)
    const y0 = Math.min(...allY), y1 = Math.max(...allY)
    const mx = Math.max((x1 - x0) / 2 + 0.02, 0.04)
    const my = Math.max((y1 - y0) / 2 + 0.02, 0.04)
    const cx = (x0 + x1) / 2, cy = (y0 + y1) / 2
    const lat0 = cy * Math.PI / 180
    const mxAdj = Math.max(mx, my / Math.cos(lat0))
    const myAdj = mxAdj * Math.cos(lat0)
    xrange = [cx - mxAdj, cx + mxAdj]
    yrange = [cy - myAdj, cy + myAdj]
  }

  Plotly.react(mapNode.value, traces, {
    margin: { l: 52, r: 12, t: 12, b: 40 },
    paper_bgcolor: '#181f2e', plot_bgcolor: '#10151f',
    font: { color: '#c9d4e0', size: 11 },
    xaxis: { title: { text: '经度 °E' }, gridcolor: '#232d3d', range: xrange },
    yaxis: { title: { text: '纬度 °N' }, gridcolor: '#232d3d', range: yrange },
    legend: { orientation: 'h', y: -0.18 },
    hovermode: 'closest',
  }, { displaylogo: false, scrollZoom: true })
}

onMounted(() => nextTick(redraw))
watch(() => props.cmp, () => nextTick(redraw), { deep: false })
</script>

<style scoped>
.compare-cols { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin: 8px 0; }
.compare-side { border: 1px solid var(--border); border-radius: 7px; padding: 8px 10px; background: var(--panel2); }
.side-a { border-top: 3px solid #58a6ff; }
.side-b { border-top: 3px solid #d29922; }
.compare-side h3 { margin-top: 2px; }
.cmp-a-text { color: #79b8ff; }
.cmp-b-text { color: #e3b341; }
.metrics-table td, .metrics-table th { text-align: right; }
.cmp-model { font-family: -apple-system, "Segoe UI", sans-serif; }
</style>
