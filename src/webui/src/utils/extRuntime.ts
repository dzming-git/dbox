/**
 * 扩展面板共享运行时（框架层能力，对插件零侵入）
 *
 * 小窗（ExtensionHost 的浮动/侧边面板）与全屏（ExtensionStandalone）复用同一份 panel.html，
 * 但两者各自是独立的 srcdoc iframe 文档：切换形态等于重建文档、面板脚本从零启动，
 * 于是同一批数据要重新拉一遍（表现为切到全屏后又是「加载中 / 检测中」）。
 *
 * 这里在把 HTML 交给 iframe 之前，前置一段运行时补丁，让两种形态共用同一份数据缓存：
 *  - 面板发出的 GET 响应统一写入 sessionStorage（iframe 与父页同源，故两形态共享）；
 *  - 面板每次挂载后，对同一 URL 的「首次」请求若命中新鲜缓存则立即返回，同时后台
 *    发起真实请求刷新缓存；
 *  - 首次之后的请求（轮询、用户交互）一律直连网络，实时性不受影响。
 *
 * 结果：小窗 ↔ 全屏 只影响显示，数据与缓存一致，不再重复加载。
 */

// 缓存新鲜期：仅覆盖「小窗与全屏之间来回切换」这一瞬间，过期后照常走网络
const FRESH_MS = 15000
// 单条响应体上限，避免超大响应挤爆 sessionStorage 配额
const MAX_BODY = 512 * 1024

function buildRuntime(extId: string): string {
  const safeId = extId.replace(/[^a-zA-Z0-9_-]/g, '')
  return `<script>
(function(){
  var NS = 'dbox_ext_cache:${safeId}:';
  var FRESH = ${FRESH_MS};
  var MAX_BODY = ${MAX_BODY};
  var orig = window.fetch && window.fetch.bind(window);
  if (!orig) return;
  // 本文档内已「首绘」过的 URL：只有首次允许吃缓存，之后一律走网络
  var served = Object.create(null);

  function isGet(input, init) {
    var m = (init && init.method) || (input && typeof input !== 'string' && input.method) || 'GET';
    return String(m).toUpperCase() === 'GET';
  }
  function read(url) {
    try {
      var o = JSON.parse(sessionStorage.getItem(NS + url) || 'null');
      if (!o || typeof o.body !== 'string') return null;
      if (Date.now() - (o.t || 0) > FRESH) return null;
      return o;
    } catch (e) { return null; }
  }
  function write(url, body, ct, status) {
    if (body.length > MAX_BODY) return;
    try {
      sessionStorage.setItem(NS + url, JSON.stringify({ t: Date.now(), body: body, ct: ct, s: status }));
    } catch (e) { /* 配额不足等：缓存失败不影响功能 */ }
  }

  window.fetch = function(input, init) {
    var url = typeof input === 'string' ? input : (input && input.url) || '';
    if (!url || !isGet(input, init)) return orig(input, init);

    var net = orig(input, init).then(function(res) {
      try {
        var ct = res.headers.get('content-type') || '';
        // 只缓存可文本化的结构化响应；流式（SSE）等不参与
        if (res.ok && /json|text\\/plain/i.test(ct) && !/event-stream/i.test(ct)) {
          res.clone().text().then(function(txt) { write(url, txt, ct, res.status); }, function(){});
        }
      } catch (e) {}
      return res;
    });

    if (!served[url]) {
      served[url] = 1;
      var c = read(url);
      if (c) {
        // 后台刷新仅为把缓存写新，其失败不应冒泡成未处理拒绝
        net.catch(function(){});
        return Promise.resolve(new Response(c.body, {
          status: c.s || 200,
          headers: { 'Content-Type': c.ct || 'application/json' }
        }));
      }
    }
    return net;
  };
})();
<\/script>`
}

/** 给面板 HTML 前置共享运行时；注入失败时原样返回，绝不影响面板本体加载。 */
export function withExtRuntime(html: string, extId: string): string {
  if (!html || typeof html !== 'string' || !extId) return html
  const runtime = buildRuntime(extId)
  // 必须在面板自身脚本之前执行，故优先插到 <head> 开头
  const headIdx = html.search(/<head[^>]*>/i)
  if (headIdx >= 0) {
    const insertAt = html.indexOf('>', headIdx) + 1
    return html.slice(0, insertAt) + runtime + html.slice(insertAt)
  }
  return runtime + html
}
