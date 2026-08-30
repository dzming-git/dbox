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

  /* ---------------- 信息流续读（feed）----------------
   * 把「服务端唯一真相源 + 换设备接着看」沉淀为框架能力，插件不必各写一遍。
   *
   * 约定键位（ns 仍按插件隔离）：
   *   feed:<name>:items    union_by_id  内容缓存，服务端权威，多设备取并集
   *   feed:<name>:anchor   lww          视口锚点（条目 id + 卡片内偏移）
   *   feed:<name>:read_at  max          已读边界，只前进不被旧值回退
   *   feed:<name>:cursor   max          分页游标，只前进
   *
   * 为什么锚点记「条目 id」而不是 scrollTop：
   *   不同设备屏宽不同、卡片高度不同，像素偏移跨设备没有意义。记 id，恢复时
   *   按 id 找到元素再算位置，才能做到换设备接着看。
   *
   * 为什么 anchor 默认在 user 层（跨设备共享）：
   *   需求就是「换个设备打开，直接继续」。若插件希望各设备各看各的（如信息流
   *   各自停在不同处），传 anchorScope:'device' 即可。
   * ------------------------------------------------------------------ */

  function _esc(s) {
    if (global.CSS && global.CSS.escape) return global.CSS.escape(String(s));
    return String(s).replace(/["\\]/g, '\\$&');
  }

  SDK.feed = function (name, opts) {
    opts = opts || {};
    var K = {
      items: 'feed:' + name + ':items',
      anchor: 'feed:' + name + ':anchor',
      readAt: 'feed:' + name + ':read_at',
      cursor: 'feed:' + name + ':cursor'
    };
    var idAttr = opts.idAttr || 'data-id';
    var cap = opts.cap || 400;
    var idKeys = opts.idKeys || null;
    var orderKey = opts.orderKey || null;
    var anchorScope = (opts.anchorScope === 'device') ? 'device' : 'user';
    var throttle = opts.throttle || 200;
    var container = opts.container || null;
    var lease = opts.lease ? SDK.lease(name) : null;

    var _saveTimer = null;
    var _restoreTimers = [];
    var _userScrolled = false;
    var _restoring = false;
    var _bound = false;

    function cont() {
      return container || opts.container;
    }

    /* ---- 锚点：捕获视口顶部第一个足够可见的条目 ---- */
    function capture() {
      var c = cont();
      if (!c) return null;
      var cr = c.getBoundingClientRect();
      var nodes = c.querySelectorAll(opts.itemSelector || '[data-id]');
      for (var i = 0; i < nodes.length; i++) {
        var r = nodes[i].getBoundingClientRect();
        if (r.bottom > cr.top + 4) {
          var id = nodes[i].getAttribute(idAttr);
          if (!id) continue;
          return { id: String(id), offset: Math.max(0, r.top - cr.top), at: Date.now() };
        }
      }
      return null;
    }

    function timeOfId(id) {
      var c = cont();
      // 优先用插件给的时间回调
      if (typeof opts.timeOf === 'function') {
        try { return opts.timeOf(id) || null; } catch (_) { return null; }
      }
      // 其次从 DOM 属性取
      if (c && opts.timeAttr) {
        var el = c.querySelector('[' + idAttr + '="' + _esc(id) + '"]');
        if (el) {
          var t = el.getAttribute(opts.timeAttr);
          if (t) return t;
        }
      }
      return null;
    }

    // 取条目的排序时间戳（规范字段 order），用于 merge 同 id 取较新一份
    function _tsOf(it) {
      if (!it || typeof it !== 'object') return 0;
      var v = it.order;
      if (v == null) return 0;
      var t = Date.parse(v);
      return isNaN(t) ? 0 : t;
    }

    // 把插件领域对象映射成 union_by_id 的规范记录 { id, order, ...领域字段 }。
    // 字段映射只在入口边界做一次，服务端合并层完全不关心插件字段名。
    function _norm(it) {
      var o = {};
      for (var p in it) {
        if (Object.prototype.hasOwnProperty.call(it, p)) o[p] = it[p];
      }
      var rawId = idKeys ? null : it.id;
      if (idKeys) {
        for (var k = 0; k < idKeys.length; k++) {
          var v = it[idKeys[k]];
          if (v !== undefined && v !== null && v !== '') { rawId = v; break; }
        }
      }
      o.id = String(rawId != null ? rawId : '');
      o.order = orderKey ? it[orderKey] : undefined;
      return o;
    }

    function saveAnchor() {
      var a = capture();
      if (!a) return null;
      // 主控门控：开启 lease 后只有主控设备才推精确锚点，非主控设备只留本地，
      // 避免多设备同时滚动时锚点交替覆盖（抖动）。read_at 是单调 max，仍照常推进。
      if (!lease || lease.mine()) {
        SDK.set(K.anchor, a, { strategy: 'lww', scope: anchorScope });
      }
      // 已读边界用时间而非 id：max 策略只前进，另一台设备往回看也不会拉低
      var t = timeOfId(a.id);
      if (t) SDK.set(K.readAt, t, { strategy: 'max' });
      if (typeof opts.onAnchor === 'function') {
        try { opts.onAnchor(a); } catch (_) {}
      }
      return a;
    }

    function scheduleSave() {
      if (_saveTimer) return;
      _saveTimer = global.setTimeout(function () {
        _saveTimer = null;
        saveAnchor();
      }, throttle);
    }

    /* ---- 锚点：恢复位置 ---- */
    function restoreOnce(a) {
      var c = cont();
      if (!c || !a || !a.id) return false;
      var el = c.querySelector('[' + idAttr + '="' + _esc(a.id) + '"]');
      if (!el) return false;
      var r = el.getBoundingClientRect();
      var cr = c.getBoundingClientRect();
      var abs = r.top - cr.top + c.scrollTop;
      c.scrollTop = Math.max(0, abs - (a.offset || 0));
      return true;
    }

    // 图片等异步资源加载完成后会顶开布局，首次定位常被冲掉，故做几次补偿定位；
    // 用户一旦自己滚动就立刻让位，绝不抢用户的操作。
    function restore(anchor) {
      var a = anchor || SDK.get(K.anchor);
      if (!a) return false;
      _userScrolled = false;
      _restoring = true;   // 抑制恢复期间（含程序化 scrollTop 触发的）scroll 事件
      _restoreTimers.forEach(global.clearTimeout);
      _restoreTimers = [];
      var ok = restoreOnce(a);
      [60, 200, 500, 1000].forEach(function (d) {
        _restoreTimers.push(global.setTimeout(function () {
          if (_userScrolled) return;
          restoreOnce(a);
        }, d));
      });
      // 补偿窗口结束后才重新接受滚动（用户可自由操作）
      _restoreTimers.push(global.setTimeout(function () { _restoring = false; }, 1300));
      return ok;
    }

    function onScroll() {
      if (_restoring) return;   // 程序化定位引发的滚动事件不能算作「用户滚动」
      _userScrolled = true;
      scheduleSave();
    }

    var api = {
      keys: K,

      /* ---- 内容缓存（服务端权威） ---- */
      items: function () {
        var v = SDK.get(K.items);
        return Array.isArray(v) ? v : [];
      },

      // 合并新内容：入口处把领域对象规范成 {id, order, ...载荷}（见 _norm），
      // 本地按 id 去重、同 id 用 order 取较新一份，再写回服务端（union_by_id
      // 在服务端再并一次）。本地语义对齐服务端，避免本地渲染与权威值分叉。
      // 注意：规范记录直接携带领域字段，渲染时读领域字段即可，无需拆包。
      merge: function (list, prepend) {
        if (!Array.isArray(list) || !list.length) return this.items();
        var cur = this.items();                 // 已是规范记录
        var seen = {}, pos = {}, out = [];
        var incoming = list.map(_norm);
        var src = prepend ? incoming.concat(cur) : cur.concat(incoming);
        for (var i = 0; i < src.length; i++) {
          var it = src[i];
          if (!it || !it.id) { if (it) out.push(it); continue; }
          var id = String(it.id);
          if (!seen[id]) {
            seen[id] = true;
            pos[id] = out.length;
            out.push(it);
          } else if (_tsOf(it) > _tsOf(out[pos[id]])) {
            out[pos[id]] = it;   // order 较新，覆盖
          }
        }
        if (out.length > cap) out = out.slice(0, cap);
        SDK.set(K.items, out, { strategy: 'union_by_id', cap: cap });
        return out;
      },

      /* ---- 锚点 ---- */
      capture: capture,
      anchor: function () { return SDK.get(K.anchor); },
      saveAnchor: saveAnchor,
      restore: restore,
      clearAnchor: function () { SDK.remove(K.anchor); },

      /* ---- 已读边界 ---- */
      readAt: function () { return SDK.get(K.readAt); },
      markRead: function (t) {
        if (!t) return;
        SDK.set(K.readAt, t, { strategy: 'max' });
      },
      isRead: function (t) {
        var b = this.readAt();
        if (!b || !t) return false;
        var bt = Date.parse(b), tt = Date.parse(t);
        if (isNaN(bt) || isNaN(tt)) return false;
        return tt <= bt;
      },

      /* ---- 分页游标 ---- */
      cursor: function () { return SDK.get(K.cursor); },
      setCursor: function (c) {
        if (!c) return;
        SDK.set(K.cursor, c, { strategy: 'max' });
      },

      /* ---- 主控租约（opts.lease 启用时有效） ---- */
      lease: lease,
      isMaster: function () { return lease ? lease.mine() : true; },
      takeOver: function () { if (lease) lease.acquire(); return api; },

      /* ---- 生命周期 ---- */
      bind: function () {
        var c = cont();
        if (!c || _bound) return api;
        _bound = true;
        c.addEventListener('scroll', onScroll, { passive: true });
        return api;
      },
      destroy: function () {
        var c = cont();
        if (c && _bound) c.removeEventListener('scroll', onScroll);
        _bound = false;
        if (_saveTimer) { global.clearTimeout(_saveTimer); _saveTimer = null; }
        _restoreTimers.forEach(global.clearTimeout);
        _restoreTimers = [];
        return api;
      }
    };

    if (opts.autoBind !== false) api.bind();
    return api;
  };

  /* ---------------- 主控租约（lease）----------------
   * 解决多设备同时滚动导致的「位置抖动 / 陈旧写回」：
   *   两台设备都在滚时，朴素 lww 按到达顺序决胜会让锚点来回跳；更常见的是
   *   一台空闲设备把陈旧位置推回、覆盖掉当前正在看的那台的进度。
   *
   * 做法：租约是 UserState 里的一个普通键（lww），值 { deviceId, at }。
   *   - acquire() 抢占主控权（写入并立即推送，不等防抖）；
   *   - owner()/mine() 判断当前主控是不是本设备；
   *   - 插件据此门控「精确位置」类写入：非主控只写本地、不推服务端。
   *
   * 约定（重要）：acquire 必须绑在「刻意使用」的时机——打开/刷新视图、面板重新显示、
   * 点击接管。**绝不能绑在 scroll 上**，否则两台设备交替抢占，抖动依旧。
   *
   * 当前是客户端门控：服务端仍会接受过期设备的写（单人阅读场景已足够，且零风险）。
   * 若要服务端硬栅栏，可在 user_state 写接口加 lease_rev 校验（rev 本就单调递增）。
   * ------------------------------------------------------------------ */

  SDK.lease = function (name) {
    var K = 'feed:' + name + ':lease';
    var api = {
      key: K,
      acquire: function () {
        SDK.set(K, { deviceId: SDK.deviceId(), at: Date.now() }, { strategy: 'lww' });
        SDK.push();   // 抢占要尽快生效，不等防抖
        return api;
      },
      owner: function () {
        var v = SDK.get(K);
        return (v && v.deviceId) || null;
      },
      mine: function () {
        var o = api.owner();
        return !!o && o === SDK.deviceId();
      },
      // 与服务端对账后再判断（用于「面板重新显示 / 被别的设备接管」时刷新指示灯）
      refresh: function () {
        return SDK.pull().then(function () { return api.mine(); });
      }
    };
    return api;
  };

  global.DBoxState = SDK;
})(window);
