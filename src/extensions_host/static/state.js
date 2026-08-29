/* dbox 统一用户状态 SDK
 * ---------------------------------------------------------------------------
 * 面板接入方式（一行）：
 *   <script src="/api/ext-sdk/state.js"></script>
 *   DBoxState.init({ ns: 'x' });
 *
 * 设计取舍（都是踩过坑才定的）：
 *  1) 本地优先：读永远走本地缓存（localStorage + 内存），先渲染再对账，
 *     绝不让首屏等网络——否则弱网/离线时面板会白屏或停在默认视图。
 *  2) 脏键推送：只推真正变了的键，而不是每次都把整份缓存（可能 400 条）传上去。
 *  3) 卸载落盘用 keepalive：pagehide 时普通 fetch 会被浏览器直接掐断，
 *     必须 keepalive:true 才能保证最后一次变更真的送达。
 *  4) 失败静默降级：网络/鉴权异常一律退化为纯本地行为，绝不打断 UI。
 * --------------------------------------------------------------------------- */
(function (global) {
  'use strict';

  var LS_DEVICE = 'dbox_device_id';
  var LS_PREFIX = 'dbox_state_';

  var SDK = {
    ns: 'core',
    base: '',            // 为空表示同源（由扩展宿主转发到核心）
    debounce: 1200,
    _cache: {},          // key -> { value, rev, v }
    _pending: {},        // 待推送：key -> { value, strategy, scope, cap, v }
    _timer: null,
    _device: null,
    _started: false
  };

  function _ls(scopeKey) {
    try { return global.localStorage; } catch (_) { return null; }
  }

  SDK.deviceId = function () {
    if (SDK._device) return SDK._device;
    var ls = _ls();
    var v = null;
    try { v = ls && ls.getItem(LS_DEVICE); } catch (_) {}
    if (!v) {
      v = 'dev-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 10);
      try { ls && ls.setItem(LS_DEVICE, v); } catch (_) {}
    }
    SDK._device = v;
    return v;
  };

  // 面板常嵌在 5173 的 iframe 里，token 由父窗口注入；独立打开时回退 localStorage
  SDK.token = function () {
    try {
      if (global.parent && global.parent.__dbox_token) return global.parent.__dbox_token;
    } catch (_) {}
    var ls = _ls();
    if (!ls) return '';
    try { return ls.getItem('token') || ls.getItem('dbox_token') || ''; } catch (_) { return ''; }
  };

  SDK.init = function (opts) {
    opts = opts || {};
    if (opts.ns) SDK.ns = opts.ns;
    if (opts.base !== undefined) SDK.base = opts.base;
    if (opts.debounce) SDK.debounce = opts.debounce;
    // 先用本地快照填充内存缓存，保证 get() 立即可用
    var ls = _ls();
    if (ls) {
      try {
        var raw = ls.getItem(LS_PREFIX + SDK.ns);
        if (raw) SDK._cache = JSON.parse(raw) || {};
      } catch (_) { SDK._cache = {}; }
    }
    if (!SDK._started) {
      SDK._started = true;
      global.addEventListener('pagehide', function () { SDK.flushNow(); });
      global.document.addEventListener('visibilitychange', function () {
        if (global.document.visibilityState === 'hidden') SDK.flushNow();
      });
    }
    return SDK;
  };

  function _persist() {
    var ls = _ls();
    if (!ls) return;
    try { ls.setItem(LS_PREFIX + SDK.ns, JSON.stringify(SDK._cache)); } catch (_) {}
  }

  function _headers(json) {
    var h = { 'X-Dbox-Device-Id': SDK.deviceId() };
    var t = SDK.token();
    if (t) h['Authorization'] = 'Bearer ' + t;
    if (json) h['Content-Type'] = 'application/json';
    return h;
  }

  function _url(suffix) {
    return SDK.base + '/api/user-state/' + encodeURIComponent(SDK.ns) + (suffix || '');
  }

  /* ---------------- 读（本地优先） ---------------- */

  SDK.get = function (key, def) {
    var it = SDK._cache[key];
    return (it && it.value !== undefined) ? it.value : def;
  };

  SDK.all = function () {
    var out = {};
    for (var k in SDK._cache) {
      if (Object.prototype.hasOwnProperty.call(SDK._cache, k)) out[k] = SDK._cache[k].value;
    }
    return out;
  };

  /* ---------------- 写（本地落 + 脏键排队） ---------------- */

  SDK.set = function (key, value, opts) {
    opts = opts || {};
    SDK._cache[key] = { value: value, rev: (SDK._cache[key] && SDK._cache[key].rev) || 0, v: opts.v || 1 };
    _persist();
    SDK._pending[key] = {
      value: value,
      strategy: opts.strategy || undefined,
      scope: opts.scope || 'user',
      cap: opts.cap,
      v: opts.v || 1
    };
    _schedule();
    return value;
  };

  SDK.remove = function (key) {
    delete SDK._cache[key];
    _persist();
    SDK._pending[key] = { __delete: true, scope: 'user' };
    _schedule();
  };

  function _schedule() {
    if (SDK._timer) return;
    SDK._timer = global.setTimeout(function () { SDK._timer = null; SDK.push(); }, SDK.debounce);
  }

  /* ---------------- 网络：推送 / 拉取 ---------------- */

  SDK.push = function () {
    var put = {}, del = [], has = false;
    for (var k in SDK._pending) {
      if (!Object.prototype.hasOwnProperty.call(SDK._pending, k)) continue;
      has = true;
      if (SDK._pending[k] && SDK._pending[k].__delete) del.push(k);
      else put[k] = SDK._pending[k];
    }
    SDK._pending = {};
    if (!has) return Promise.resolve(null);
    return SDK._send('POST', '/sync', { put: put, delete: del }, false).then(function (d) {
      _applyServerData(d && d.data);
      return d;
    }).catch(function () { return null; });   // 失败静默，退化为本地
  };

  SDK.pull = function () {
    return SDK._send('GET', '', null, false).then(function (d) {
      _applyServerData(d && d.data);
      return SDK.all();
    }).catch(function () { return SDK.all(); });
  };

  // 卸载/隐藏时立即落盘：keepalive 保证请求不被浏览器掐断
  SDK.flushNow = function () {
    if (SDK._timer) { global.clearTimeout(SDK._timer); SDK._timer = null; }
    var put = {}, del = [], has = false;
    for (var k in SDK._pending) {
      if (!Object.prototype.hasOwnProperty.call(SDK._pending, k)) continue;
      has = true;
      if (SDK._pending[k] && SDK._pending[k].__delete) del.push(k);
      else put[k] = SDK._pending[k];
    }
    if (!has) return;
    SDK._pending = {};
    SDK._send('POST', '/sync', { put: put, delete: del }, true).catch(function () {});
  };

  function _applyServerData(data) {
    if (!data) return;
    var keys = [];
    for (var k0 in data) {
      if (Object.prototype.hasOwnProperty.call(data, k0)) keys.push(k0);
    }
    if (!keys.length) return;   // 服务端快照为空（首台设备）时保留本地，避免误清空

    // 以服务端快照为准整体替换：服务端不返回某个键，意味着它对当前身份
    // 不可见（如 device 作用域属于别的设备）或已在别处被删除。若只是"有则更新"，
    // 本地会永久残留脏值，表现为设备间串台、已删状态复活。
    var next = {};
    keys.forEach(function (k) {
      var it = data[k] || {};
      next[k] = { value: it.value, rev: it.rev || 0, v: it.v || 1 };
    });
    // 本地尚未推送的改动优先保留（用户刚改的不能丢）
    for (var p in SDK._pending) {
      if (!Object.prototype.hasOwnProperty.call(SDK._pending, p)) continue;
      if (SDK._pending[p] && SDK._pending[p].__delete) { delete next[p]; continue; }
      if (SDK._cache[p] !== undefined) next[p] = SDK._cache[p];
    }
    SDK._cache = next;
    _persist();
  }

  SDK._send = function (method, suffix, body, keepalive) {
    var opts = { method: method, headers: _headers(body !== null), credentials: 'same-origin' };
    if (body !== null) opts.body = JSON.stringify(body);
    if (keepalive) opts.keepalive = true;
    return global.fetch(_url(suffix), opts).then(function (r) {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    });
  };

  global.DBoxState = SDK;
})(window);
