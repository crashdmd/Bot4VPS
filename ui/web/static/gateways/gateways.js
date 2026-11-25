// @__NO_SIDE_EFFECTS__
function Hl(e) {
  const t = /* @__PURE__ */ Object.create(null);
  for (const n of e.split(",")) t[n] = 1;
  return (n) => n in t;
}
const Se = {}, Jt = [], kt = () => {
}, Bs = () => !1, nl = (e) => e.charCodeAt(0) === 111 && e.charCodeAt(1) === 110 && // uppercase letter
(e.charCodeAt(2) > 122 || e.charCodeAt(2) < 97), ll = (e) => e.startsWith("onUpdate:"), Ie = Object.assign, Ll = (e, t) => {
  const n = e.indexOf(t);
  n > -1 && e.splice(n, 1);
}, gi = Object.prototype.hasOwnProperty, me = (e, t) => gi.call(e, t), de = Array.isArray, qt = (e) => on(e) === "[object Map]", It = (e) => on(e) === "[object Set]", ds = (e) => on(e) === "[object Date]", fe = (e) => typeof e == "function", Pe = (e) => typeof e == "string", vt = (e) => typeof e == "symbol", $e = (e) => e !== null && typeof e == "object", Ks = (e) => ($e(e) || fe(e)) && fe(e.then) && fe(e.catch), Gs = Object.prototype.toString, on = (e) => Gs.call(e), hi = (e) => on(e).slice(8, -1), zs = (e) => on(e) === "[object Object]", jl = (e) => Pe(e) && e !== "NaN" && e[0] !== "-" && "" + parseInt(e, 10) === e, vn = /* @__PURE__ */ Hl(
  // the leading comma is intentional so empty string "" is also included
  ",key,ref,ref_for,ref_key,onVnodeBeforeMount,onVnodeMounted,onVnodeBeforeUpdate,onVnodeUpdated,onVnodeBeforeUnmount,onVnodeUnmounted"
), mi = 1e4, sl = (e) => {
  let t = /* @__PURE__ */ Object.create(null), n = 0;
  return ((o) => {
    const s = t[o];
    return s !== void 0 ? s : (++n > mi && (t = /* @__PURE__ */ Object.create(null), n = 1), t[o] = e(o));
  });
}, bi = /-\w/g, ft = /* @__PURE__ */ sl((e) => e.replace(bi, (t) => t.slice(1).toUpperCase())), yi = /\B([A-Z])/g, jt = /* @__PURE__ */ sl(
  (e) => e.replace(yi, "-$1").toLowerCase()
), Js = /* @__PURE__ */ sl((e) => e.charAt(0).toUpperCase() + e.slice(1)), vl = /* @__PURE__ */ sl((e) => e ? `on${Js(e)}` : ""), wt = (e, t) => !Object.is(e, t), Wn = (e, ...t) => {
  for (let n = 0; n < e.length; n++)
    e[n](...t);
}, Ys = (e, t, n, o = !1) => {
  Object.defineProperty(e, t, {
    configurable: !0,
    enumerable: !1,
    writable: o,
    value: n
  });
}, An = (e) => {
  const t = parseFloat(e);
  return isNaN(t) ? e : t;
};
let cs;
const ol = () => cs || (cs = typeof globalThis < "u" ? globalThis : typeof self < "u" ? self : typeof window < "u" ? window : typeof global < "u" ? global : {});
function _n(e) {
  if (de(e)) {
    const t = {};
    for (let n = 0; n < e.length; n++) {
      const o = e[n], s = Pe(o) ? $i(o) : _n(o);
      if (s)
        for (const i in s)
          t[i] = s[i];
    }
    return t;
  } else if (Pe(e) || $e(e))
    return e;
}
const wi = /;(?![^(]*\))/g, _i = /:([^]+)/, ki = /"(?:[^"\\]|\\[^])*"|'(?:[^'\\]|\\[^])*'|\\[^]|\/\*[^]*?\*\//g;
function $i(e) {
  const t = {};
  return e.replace(ki, (n) => n.startsWith("/*") ? "" : n).split(wi).forEach((n) => {
    if (n) {
      const o = n.split(_i);
      o.length > 1 && (t[o[0].trim()] = o[1].trim());
    }
  }), t;
}
function Ee(e) {
  let t = "";
  if (Pe(e))
    t = e;
  else if (de(e))
    for (let n = 0; n < e.length; n++) {
      const o = Ee(e[n]);
      o && (t += o + " ");
    }
  else if ($e(e))
    for (const n in e)
      e[n] && (t += n + " ");
  return t.trim();
}
const Ci = "itemscope,allowfullscreen,disablepictureinpicture,disableremoteplayback,formnovalidate,ismap,nomodule,novalidate,playsinline,readonly", xi = /* @__PURE__ */ Hl(Ci);
function Xs(e) {
  return !!e || e === "";
}
function Si(e, t, n) {
  if (e.length !== t.length) return !1;
  let o = !0;
  for (let s = 0; o && s < e.length; s++)
    o = Ot(e[s], t[s], n);
  return o;
}
function fs(e, t, n) {
  if (e.size !== t.size) return !1;
  const o = Array.from(t), s = new Uint8Array(o.length);
  for (const i of e) {
    let a = -1;
    for (let u = 0; u < o.length; u++)
      if (!s[u] && Ot(i, o[u], n)) {
        a = u;
        break;
      }
    if (a < 0) return !1;
    s[a] = 1;
  }
  return !0;
}
function Ti(e, t, n) {
  let o = qt(e), s = qt(t);
  if (o || s || (o = It(e), s = It(t), o || s))
    return o && s ? fs(e, t, n) : !1;
  const i = Object.keys(e).length, a = Object.keys(t).length;
  if (i !== a)
    return !1;
  for (const u in e) {
    const c = me(e, u), g = me(t, u);
    if (c && !g || !c && g || !Ot(e[u], t[u], n))
      return !1;
  }
  return vs(e) === vs(t);
}
function ps(e, t, n, o) {
  n || (n = [/* @__PURE__ */ new Map(), /* @__PURE__ */ new Map()]);
  const [s, i] = n;
  if (s.has(e) || i.has(t))
    return s.get(e) === t && i.get(t) === e;
  s.set(e, t), i.set(t, e);
  const a = o(e, t, n);
  return s.delete(e), i.delete(t), a;
}
function Ot(e, t, n) {
  if (e === t) return !0;
  let o = ds(e), s = ds(t);
  return o || s ? o && s ? e.getTime() === t.getTime() : !1 : (o = vt(e), s = vt(t), o || s ? e === t : (o = de(e), s = de(t), o || s ? o && s ? ps(e, t, n, Si) : !1 : (o = $e(e), s = $e(t), o || s ? !o || !s ? !1 : ps(e, t, n, Ti) : String(e) === String(t))));
}
function Wl(e, t) {
  return e.findIndex((n) => Ot(n, t));
}
function vs(e) {
  return Object.getPrototypeOf(e) === null && e[Symbol.toPrimitive] == null && typeof e.toString != "function" && typeof e.valueOf != "function" ? on(e) : String(e);
}
const Zs = (e) => !!(e && e.__v_isRef === !0), y = (e) => Pe(e) ? e : e == null ? "" : de(e) || $e(e) && (e.toString === Gs || !fe(e.toString)) ? Zs(e) ? y(e.value) : JSON.stringify(e, Qs, 2) : String(e), Qs = (e, t) => Zs(t) ? Qs(e, t.value) : qt(t) ? {
  [`Map(${t.size})`]: [...t.entries()].reduce(
    (n, [o, s], i) => (n[gl(o, i) + " =>"] = s, n),
    {}
  )
} : It(t) ? {
  [`Set(${t.size})`]: [...t.values()].map((n) => gl(n))
} : vt(t) ? gl(t) : $e(t) && !de(t) && !zs(t) ? String(t) : t, gl = (e, t = "") => {
  var n;
  return (
    // Symbol.description in es2019+ so we need to cast here to pass
    // the lib: es2016 check
    vt(e) ? `Symbol(${(n = e.description) != null ? n : t})` : e
  );
};
let De;
class Ei {
  // TODO isolatedDeclarations "__v_skip"
  constructor(t = !1) {
    this.detached = t, this._active = !0, this._on = 0, this.effects = [], this.cleanups = [], this._isPaused = !1, this._warnOnRun = !0, this.__v_skip = !0, !t && De && (De.active ? (this.parent = De, this.index = (De.scopes || (De.scopes = [])).push(
      this
    ) - 1) : (this._active = !1, this._warnOnRun = !1));
  }
  get active() {
    return this._active;
  }
  pause() {
    if (this._active) {
      this._isPaused = !0;
      let t, n;
      if (this.scopes) {
        const o = this.scopes.slice();
        for (t = 0, n = o.length; t < n; t++)
          o[t].pause();
      }
      for (t = 0, n = this.effects.length; t < n; t++)
        this.effects[t].pause();
    }
  }
  /**
   * Resumes the effect scope, including all child scopes and effects.
   */
  resume() {
    if (this._active && this._isPaused) {
      this._isPaused = !1;
      let t, n;
      if (this.scopes) {
        const s = this.scopes.slice();
        for (t = 0, n = s.length; t < n; t++)
          s[t].resume();
      }
      const o = this.effects.slice();
      for (t = 0, n = o.length; t < n; t++)
        o[t].resume();
    }
  }
  run(t) {
    if (this._active) {
      const n = De;
      try {
        return De = this, t();
      } finally {
        De = n;
      }
    }
  }
  /**
   * This should only be called on non-detached scopes
   * @internal
   */
  on() {
    ++this._on === 1 && (this.prevScope = De, De = this);
  }
  /**
   * This should only be called on non-detached scopes
   * @internal
   */
  off() {
    if (this._on > 0 && --this._on === 0) {
      if (De === this)
        De = this.prevScope;
      else {
        let t = De;
        for (; t; ) {
          if (t.prevScope === this) {
            t.prevScope = this.prevScope;
            break;
          }
          t = t.prevScope;
        }
      }
      this.prevScope = void 0;
    }
  }
  stop(t) {
    if (this._active) {
      this._active = !1;
      let n, o;
      for (n = 0, o = this.effects.length; n < o; n++)
        this.effects[n].stop();
      for (this.effects.length = 0, n = 0, o = this.cleanups.length; n < o; n++)
        this.cleanups[n]();
      if (this.cleanups.length = 0, this.scopes) {
        const s = this.scopes.slice();
        for (n = 0, o = s.length; n < o; n++)
          s[n].stop(!0);
        this.scopes.length = 0;
      }
      if (!this.detached && this.parent && !t) {
        const s = this.parent.scopes.pop();
        s && s !== this && (this.parent.scopes[this.index] = s, s.index = this.index);
      }
      this.parent = void 0;
    }
  }
}
function Pi() {
  return De;
}
let Te;
const hl = /* @__PURE__ */ new WeakSet();
class eo {
  constructor(t) {
    this.fn = t, this.deps = void 0, this.depsTail = void 0, this.flags = 5, this.next = void 0, this.cleanup = void 0, this.scheduler = void 0, De && (De.active ? De.effects.push(this) : this.flags &= -2);
  }
  pause() {
    this.flags |= 64;
  }
  resume() {
    this.flags & 64 && (this.flags &= -65, hl.has(this) && (hl.delete(this), this.trigger()));
  }
  /**
   * @internal
   */
  notify() {
    this.flags & 2 && !(this.flags & 32) || this.flags & 8 || no(this);
  }
  run() {
    if (!(this.flags & 1))
      return this.fn();
    this.flags |= 2, gs(this), lo(this);
    const t = Te, n = pt;
    Te = this, pt = !0;
    try {
      return this.fn();
    } finally {
      so(this), Te = t, pt = n, this.flags &= -3;
    }
  }
  stop() {
    if (this.flags & 1) {
      for (let t = this.deps; t; t = t.nextDep)
        Gl(t);
      this.deps = this.depsTail = void 0, gs(this), this.onStop && this.onStop(), this.flags &= -2;
    }
  }
  trigger() {
    this.flags & 64 ? hl.add(this) : this.scheduler ? this.scheduler() : this.runIfDirty();
  }
  /**
   * @internal
   */
  runIfDirty() {
    El(this) && this.run();
  }
  get dirty() {
    return El(this);
  }
}
let to = 0, gn, hn;
function no(e, t = !1) {
  if (e.flags |= 8, t) {
    e.next = hn, hn = e;
    return;
  }
  e.next = gn, gn = e;
}
function Bl() {
  to++;
}
function Kl() {
  if (--to > 0)
    return;
  if (hn) {
    let t = hn;
    for (hn = void 0; t; ) {
      const n = t.next;
      t.next = void 0, t.flags &= -9, t = n;
    }
  }
  let e;
  for (; gn; ) {
    let t = gn;
    for (gn = void 0; t; ) {
      const n = t.next;
      if (t.next = void 0, t.flags &= -9, t.flags & 1)
        try {
          t.trigger();
        } catch (o) {
          e || (e = o);
        }
      t = n;
    }
  }
  if (e) throw e;
}
function lo(e) {
  for (let t = e.deps; t; t = t.nextDep)
    t.version = -1, t.prevActiveLink = t.dep.activeLink, t.dep.activeLink = t;
}
function so(e) {
  let t, n = e.depsTail, o = n;
  for (; o; ) {
    const s = o.prevDep;
    o.version === -1 ? (o === n && (n = s), Gl(o), Ai(o)) : t = o, o.dep.activeLink = o.prevActiveLink, o.prevActiveLink = void 0, o = s;
  }
  e.deps = t, e.depsTail = n;
}
function El(e) {
  for (let t = e.deps; t; t = t.nextDep)
    if (t.dep.version !== t.version || t.dep.computed && (oo(t.dep.computed) || t.dep.version !== t.version))
      return !0;
  return !!e._dirty;
}
function oo(e) {
  if (e.flags & 4 && !(e.flags & 16) || (e.flags &= -17, e.globalVersion === kn) || (e.globalVersion = kn, !e.isSSR && e.flags & 128 && (!e.deps && !e._dirty || !El(e))))
    return;
  e.flags |= 2;
  const t = e.dep, n = Te, o = pt;
  Te = e, pt = !0;
  try {
    lo(e);
    const s = e.fn(e._value);
    (t.version === 0 || wt(s, e._value)) && (e.flags |= 128, e._value = s, t.version++);
  } catch (s) {
    throw t.version++, s;
  } finally {
    Te = n, pt = o, so(e), e.flags &= -3;
  }
}
function Gl(e, t = !1) {
  const { dep: n, prevSub: o, nextSub: s } = e;
  if (o && (o.nextSub = s, e.prevSub = void 0), s && (s.prevSub = o, e.nextSub = void 0), n.subs === e && (n.subs = o, !o && n.computed)) {
    n.computed.flags &= -5;
    for (let i = n.computed.deps; i; i = i.nextDep)
      Gl(i, !0);
  }
  !t && !--n.sc && n.map && n.map.delete(n.key);
}
function Ai(e) {
  const { prevDep: t, nextDep: n } = e;
  t && (t.nextDep = n, e.prevDep = void 0), n && (n.prevDep = t, e.nextDep = void 0);
}
let pt = !0;
const io = [];
function $t() {
  io.push(pt), pt = !1;
}
function Ct() {
  const e = io.pop();
  pt = e === void 0 ? !0 : e;
}
function gs(e) {
  const { cleanup: t } = e;
  if (e.cleanup = void 0, t) {
    const n = Te;
    Te = void 0;
    try {
      t();
    } finally {
      Te = n;
    }
  }
}
let kn = 0;
class Ui {
  constructor(t, n) {
    this.sub = t, this.dep = n, this.version = n.version, this.nextDep = this.prevDep = this.nextSub = this.prevSub = this.prevActiveLink = void 0;
  }
}
class zl {
  // TODO isolatedDeclarations "__v_skip"
  constructor(t) {
    this.computed = t, this.version = 0, this.activeLink = void 0, this.subs = void 0, this.map = void 0, this.key = void 0, this.sc = 0, this.__v_skip = !0;
  }
  track(t) {
    if (!Te || !pt || Te === this.computed)
      return;
    let n = this.activeLink;
    if (n === void 0 || n.sub !== Te)
      n = this.activeLink = new Ui(Te, this), Te.deps ? (n.prevDep = Te.depsTail, Te.depsTail.nextDep = n, Te.depsTail = n) : Te.deps = Te.depsTail = n, ao(n);
    else if (n.version === -1 && (n.version = this.version, n.nextDep)) {
      const o = n.nextDep;
      o.prevDep = n.prevDep, n.prevDep && (n.prevDep.nextDep = o), n.prevDep = Te.depsTail, n.nextDep = void 0, Te.depsTail.nextDep = n, Te.depsTail = n, Te.deps === n && (Te.deps = o);
    }
    return n;
  }
  trigger(t) {
    this.version++, kn++, this.notify(t);
  }
  notify(t) {
    Bl();
    try {
      for (let n = this.subs; n; n = n.prevSub)
        n.sub.notify() && n.sub.dep.notify();
    } finally {
      Kl();
    }
  }
}
function ao(e) {
  if (e.dep.sc++, e.sub.flags & 4) {
    const t = e.dep.computed;
    if (t && !e.dep.subs) {
      t.flags |= 20;
      for (let o = t.deps; o; o = o.nextDep)
        ao(o);
    }
    const n = e.dep.subs;
    n !== e && (e.prevSub = n, n && (n.nextSub = e)), e.dep.subs = e;
  }
}
const Pl = /* @__PURE__ */ new WeakMap(), Yt = /* @__PURE__ */ Symbol(
  ""
), Al = /* @__PURE__ */ Symbol(
  ""
), $n = /* @__PURE__ */ Symbol(
  ""
);
function We(e, t, n) {
  if (pt && Te) {
    let o = Pl.get(e);
    o || Pl.set(e, o = /* @__PURE__ */ new Map());
    let s = o.get(n);
    s || (o.set(n, s = new zl()), s.map = o, s.key = n), s.track();
  }
}
function At(e, t, n, o, s, i) {
  const a = Pl.get(e);
  if (!a) {
    kn++;
    return;
  }
  const u = (c) => {
    c && c.trigger();
  };
  if (Bl(), t === "clear")
    a.forEach(u);
  else {
    const c = de(e), g = c && jl(n);
    if (c && n === "length") {
      const m = Number(o);
      a.forEach((b, S) => {
        (S === "length" || S === $n || !vt(S) && S >= m) && u(b);
      });
    } else
      switch ((n !== void 0 || a.has(void 0)) && u(a.get(n)), g && u(a.get($n)), t) {
        case "add":
          c ? g && u(a.get("length")) : (u(a.get(Yt)), qt(e) && u(a.get(Al)));
          break;
        case "delete":
          c || (u(a.get(Yt)), qt(e) && u(a.get(Al)));
          break;
        case "set":
          qt(e) && u(a.get(Yt));
          break;
      }
  }
  Kl();
}
function Qt(e) {
  const t = /* @__PURE__ */ _e(e);
  return t === e || (We(t, "iterate", $n), /* @__PURE__ */ ot(e)) ? t : /* @__PURE__ */ xt(e) ? /* @__PURE__ */ Ht(e) ? t.map((n) => Lt(it(n))) : t.map(Lt) : t.map(it);
}
function il(e) {
  return We(e = /* @__PURE__ */ _e(e), "iterate", $n), e;
}
function mt(e, t) {
  return /* @__PURE__ */ xt(e) ? Lt(/* @__PURE__ */ Ht(e) ? it(t) : t) : it(t);
}
const Vi = {
  __proto__: null,
  [Symbol.iterator]() {
    return ml(this, Symbol.iterator, (e) => mt(this, e));
  },
  concat(...e) {
    return Qt(this).concat(
      ...e.map((t) => de(t) ? Qt(t) : t)
    );
  },
  entries() {
    return ml(this, "entries", (e) => (e[1] = mt(this, e[1]), e));
  },
  every(e, t) {
    return Tt(this, "every", e, t, void 0, arguments);
  },
  filter(e, t) {
    return Tt(
      this,
      "filter",
      e,
      t,
      (n) => n.map((o) => mt(this, o)),
      arguments
    );
  },
  find(e, t) {
    return Tt(
      this,
      "find",
      e,
      t,
      (n) => mt(this, n),
      arguments
    );
  },
  findIndex(e, t) {
    return Tt(this, "findIndex", e, t, void 0, arguments);
  },
  findLast(e, t) {
    return Tt(
      this,
      "findLast",
      e,
      t,
      (n) => mt(this, n),
      arguments
    );
  },
  findLastIndex(e, t) {
    return Tt(this, "findLastIndex", e, t, void 0, arguments);
  },
  // flat, flatMap could benefit from ARRAY_ITERATE but are not straight-forward to implement
  forEach(e, t) {
    return Tt(this, "forEach", e, t, void 0, arguments);
  },
  includes(...e) {
    return bl(this, "includes", e);
  },
  indexOf(...e) {
    return bl(this, "indexOf", e);
  },
  join(e) {
    return Qt(this).join(e);
  },
  // keys() iterator only reads `length`, no optimization required
  lastIndexOf(...e) {
    return bl(this, "lastIndexOf", e);
  },
  map(e, t) {
    return Tt(this, "map", e, t, void 0, arguments);
  },
  pop() {
    return rn(this, "pop");
  },
  push(...e) {
    return rn(this, "push", e);
  },
  reduce(e, ...t) {
    return ms(this, "reduce", e, t);
  },
  reduceRight(e, ...t) {
    return ms(this, "reduceRight", e, t);
  },
  shift() {
    return rn(this, "shift");
  },
  // slice could use ARRAY_ITERATE but also seems to beg for range tracking
  some(e, t) {
    return Tt(this, "some", e, t, void 0, arguments);
  },
  splice(...e) {
    return rn(this, "splice", e);
  },
  toReversed() {
    return Qt(this).toReversed();
  },
  toSorted(e) {
    return Qt(this).toSorted(e);
  },
  toSpliced(...e) {
    return Qt(this).toSpliced(...e);
  },
  unshift(...e) {
    return rn(this, "unshift", e);
  },
  values() {
    return ml(this, "values", (e) => mt(this, e));
  }
};
function ml(e, t, n) {
  const o = il(e), s = o[t], i = s.call(o);
  if (o !== e && !/* @__PURE__ */ ot(e)) {
    if (i[Symbol.toStringTag] === "Array Iterator") {
      const a = Object.create(Object.getPrototypeOf(i));
      return a.next = () => hs(i.next(), n), s !== ro[t] && Object.defineProperties(a, {
        return: {
          get() {
            const u = i.return;
            return typeof u == "function" ? u.bind(i) : u;
          }
        },
        throw: {
          get() {
            const u = i.throw;
            return typeof u == "function" ? u.bind(i) : u;
          }
        }
      }), a;
    }
    i._next = i.next, i.next = () => hs(i._next(), n);
  }
  return i;
}
function hs(e, t) {
  return e.done || (e.value = t(e.value)), e;
}
const ro = Array.prototype;
function Tt(e, t, n, o, s, i) {
  const a = il(e), u = a !== e && !/* @__PURE__ */ ot(e), c = a[t];
  if (c !== ro[t]) {
    const b = c.apply(e, i);
    return u ? it(b) : b;
  }
  let g = n;
  a !== e && (u ? g = function(b, S) {
    return n.call(this, mt(e, b), S, e);
  } : n.length > 2 && (g = function(b, S) {
    return n.call(this, b, S, e);
  }));
  const m = c.call(a, g, o);
  return u && s ? s(m) : m;
}
function ms(e, t, n, o) {
  const s = il(e), i = s !== e && !/* @__PURE__ */ ot(e);
  let a = n, u = !1;
  s !== e && (i ? (u = o.length === 0, a = function(g, m, b) {
    return u && (u = !1, g = mt(e, g)), n.call(this, g, mt(e, m), b, e);
  }) : n.length > 3 && (a = function(g, m, b) {
    return n.call(this, g, m, b, e);
  }));
  const c = s[t](a, ...o);
  return u ? mt(e, c) : c;
}
function bl(e, t, n) {
  const o = /* @__PURE__ */ _e(e);
  We(o, "iterate", $n);
  const s = o[t](...n);
  return (s === -1 || s === !1) && /* @__PURE__ */ Zl(n[0]) ? (n[0] = /* @__PURE__ */ _e(n[0]), o[t](...n)) : s;
}
function rn(e, t, n = []) {
  $t(), Bl();
  const o = (/* @__PURE__ */ _e(e))[t].apply(e, n);
  return Kl(), Ct(), o;
}
const Ii = /* @__PURE__ */ Hl("__proto__,__v_isRef,__isVue"), uo = /* @__PURE__ */ new Set(
  /* @__PURE__ */ Object.getOwnPropertyNames(Symbol).filter((e) => e !== "arguments" && e !== "caller").map((e) => Symbol[e]).filter(vt)
);
function Oi(e) {
  vt(e) || (e = String(e));
  const t = /* @__PURE__ */ _e(this);
  return We(t, "has", e), t.hasOwnProperty(e);
}
class co {
  constructor(t = !1, n = !1) {
    this._isReadonly = t, this._isShallow = n;
  }
  get(t, n, o) {
    if (n === "__v_skip") return t.__v_skip;
    const s = this._isReadonly, i = this._isShallow;
    if (n === "__v_isReactive")
      return !s;
    if (n === "__v_isReadonly")
      return s;
    if (n === "__v_isShallow")
      return i;
    if (n === "__v_raw")
      return o === (s ? i ? Wi : go : i ? vo : po).get(t) || // receiver is not the reactive proxy, but has the same prototype
      // this means the receiver is a user proxy of the reactive proxy
      Object.getPrototypeOf(t) === Object.getPrototypeOf(o) ? t : void 0;
    const a = de(t);
    if (!s) {
      let c;
      if (a && (c = Vi[n]))
        return c;
      if (n === "hasOwnProperty")
        return Oi;
    }
    const u = Reflect.get(
      t,
      n,
      // if this is a proxy wrapping a ref, return methods using the raw ref
      // as receiver so that we don't have to call `toRaw` on the ref in all
      // its class methods
      /* @__PURE__ */ Ge(t) ? t : o
    );
    if ((vt(n) ? uo.has(n) : Ii(n)) || (s || We(t, "get", n), i))
      return u;
    if (/* @__PURE__ */ Ge(u)) {
      const c = a && jl(n) ? u : u.value;
      return s && $e(c) ? /* @__PURE__ */ Vl(c) : c;
    }
    return $e(u) ? s ? /* @__PURE__ */ Vl(u) : /* @__PURE__ */ Yl(u) : u;
  }
}
class fo extends co {
  constructor(t = !1) {
    super(!1, t);
  }
  set(t, n, o, s) {
    let i = t[n];
    const a = de(t) && jl(n);
    if (!this._isShallow) {
      const g = /* @__PURE__ */ xt(i);
      if (!/* @__PURE__ */ ot(o) && !/* @__PURE__ */ xt(o) && (i = /* @__PURE__ */ _e(i), o = /* @__PURE__ */ _e(o)), !a && /* @__PURE__ */ Ge(i) && !/* @__PURE__ */ Ge(o))
        return g || (i.value = o), !0;
    }
    const u = a ? Number(n) < t.length : me(t, n), c = Reflect.set(
      t,
      n,
      o,
      /* @__PURE__ */ Ge(t) ? t : s
    );
    return t === /* @__PURE__ */ _e(s) && c && (u ? wt(o, i) && At(t, "set", n, o) : At(t, "add", n, o)), c;
  }
  deleteProperty(t, n) {
    const o = me(t, n);
    t[n];
    const s = Reflect.deleteProperty(t, n);
    return s && o && At(t, "delete", n, void 0), s;
  }
  has(t, n) {
    const o = Reflect.has(t, n);
    return (!vt(n) || !uo.has(n)) && We(t, "has", n), o;
  }
  ownKeys(t) {
    return We(
      t,
      "iterate",
      de(t) ? "length" : Yt
    ), Reflect.ownKeys(t);
  }
}
class Mi extends co {
  constructor(t = !1) {
    super(!0, t);
  }
  set(t, n) {
    return !0;
  }
  deleteProperty(t, n) {
    return !0;
  }
}
const Ri = /* @__PURE__ */ new fo(), Di = /* @__PURE__ */ new Mi(), Ni = /* @__PURE__ */ new fo(!0);
const Ul = (e) => e, Rn = (e) => Reflect.getPrototypeOf(e);
function Fi(e, t, n) {
  return function(...o) {
    const s = this.__v_raw, i = /* @__PURE__ */ _e(s), a = qt(i), u = e === "entries" || e === Symbol.iterator && a, c = e === "keys" && a, g = s[e](...o), m = n ? Ul : t ? Lt : it;
    return !t && We(
      i,
      "iterate",
      c ? Al : Yt
    ), Ie(
      // inheriting all iterator properties
      Object.create(g),
      {
        // iterator protocol
        next() {
          const { value: b, done: S } = g.next();
          return S ? { value: b, done: S } : {
            value: u ? [m(b[0]), m(b[1])] : m(b),
            done: S
          };
        }
      }
    );
  };
}
function Dn(e) {
  return function(...t) {
    return e === "delete" ? !1 : e === "clear" ? void 0 : this;
  };
}
function qi(e, t) {
  const n = {
    get(s) {
      const i = this.__v_raw, a = /* @__PURE__ */ _e(i), u = /* @__PURE__ */ _e(s);
      e || (wt(s, u) && We(a, "get", s), We(a, "get", u));
      const { has: c } = Rn(a), g = t ? Ul : e ? Lt : it;
      if (c.call(a, s))
        return g(i.get(s));
      if (c.call(a, u))
        return g(i.get(u));
      i !== a && i.get(s);
    },
    get size() {
      const s = this.__v_raw;
      return !e && We(/* @__PURE__ */ _e(s), "iterate", Yt), s.size;
    },
    has(s) {
      const i = this.__v_raw, a = /* @__PURE__ */ _e(i), u = /* @__PURE__ */ _e(s);
      return e || (wt(s, u) && We(a, "has", s), We(a, "has", u)), s === u ? i.has(s) : i.has(s) || i.has(u);
    },
    forEach(s, i) {
      const a = this, u = a.__v_raw, c = /* @__PURE__ */ _e(u), g = t ? Ul : e ? Lt : it;
      return !e && We(c, "iterate", Yt), u.forEach((m, b) => s.call(i, g(m), g(b), a));
    }
  };
  return Ie(
    n,
    e ? {
      add: Dn("add"),
      set: Dn("set"),
      delete: Dn("delete"),
      clear: Dn("clear")
    } : {
      add(s) {
        const i = /* @__PURE__ */ _e(this), a = Rn(i), u = /* @__PURE__ */ _e(s), c = !t && !/* @__PURE__ */ ot(s) && !/* @__PURE__ */ xt(s) ? u : s;
        return a.has.call(i, c) || wt(s, c) && a.has.call(i, s) || wt(u, c) && a.has.call(i, u) || (i.add(c), At(i, "add", c, c)), this;
      },
      set(s, i) {
        !t && !/* @__PURE__ */ ot(i) && !/* @__PURE__ */ xt(i) && (i = /* @__PURE__ */ _e(i));
        const a = /* @__PURE__ */ _e(this), { has: u, get: c } = Rn(a);
        let g = u.call(a, s);
        g || (s = /* @__PURE__ */ _e(s), g = u.call(a, s));
        const m = c.call(a, s);
        return a.set(s, i), g ? wt(i, m) && At(a, "set", s, i) : At(a, "add", s, i), this;
      },
      delete(s) {
        const i = /* @__PURE__ */ _e(this), { has: a, get: u } = Rn(i);
        let c = a.call(i, s);
        c || (s = /* @__PURE__ */ _e(s), c = a.call(i, s)), u && u.call(i, s);
        const g = i.delete(s);
        return c && At(i, "delete", s, void 0), g;
      },
      clear() {
        const s = /* @__PURE__ */ _e(this), i = s.size !== 0, a = s.clear();
        return i && At(
          s,
          "clear",
          void 0,
          void 0
        ), a;
      }
    }
  ), [
    "keys",
    "values",
    "entries",
    Symbol.iterator
  ].forEach((s) => {
    n[s] = Fi(s, e, t);
  }), n;
}
function Jl(e, t) {
  const n = qi(e, t);
  return (o, s, i) => s === "__v_isReactive" ? !e : s === "__v_isReadonly" ? e : s === "__v_isShallow" ? t : s === "__v_raw" ? o : Reflect.get(
    me(n, s) && s in o ? n : o,
    s,
    i
  );
}
const Hi = {
  get: /* @__PURE__ */ Jl(!1, !1)
}, Li = {
  get: /* @__PURE__ */ Jl(!1, !0)
}, ji = {
  get: /* @__PURE__ */ Jl(!0, !1)
};
const po = /* @__PURE__ */ new WeakMap(), vo = /* @__PURE__ */ new WeakMap(), go = /* @__PURE__ */ new WeakMap(), Wi = /* @__PURE__ */ new WeakMap();
function Bi(e) {
  switch (e) {
    case "Object":
    case "Array":
      return 1;
    case "Map":
    case "Set":
    case "WeakMap":
    case "WeakSet":
      return 2;
    default:
      return 0;
  }
}
// @__NO_SIDE_EFFECTS__
function Yl(e) {
  return /* @__PURE__ */ xt(e) ? e : Xl(
    e,
    !1,
    Ri,
    Hi,
    po
  );
}
// @__NO_SIDE_EFFECTS__
function Ki(e) {
  return Xl(
    e,
    !1,
    Ni,
    Li,
    vo
  );
}
// @__NO_SIDE_EFFECTS__
function Vl(e) {
  return Xl(
    e,
    !0,
    Di,
    ji,
    go
  );
}
function Xl(e, t, n, o, s) {
  if (!$e(e) || e.__v_raw && !(t && e.__v_isReactive) || e.__v_skip || !Object.isExtensible(e))
    return e;
  const i = s.get(e);
  if (i)
    return i;
  const a = Bi(hi(e));
  if (a === 0)
    return e;
  const u = new Proxy(
    e,
    a === 2 ? o : n
  );
  return s.set(e, u), u;
}
// @__NO_SIDE_EFFECTS__
function Ht(e) {
  return /* @__PURE__ */ xt(e) ? /* @__PURE__ */ Ht(e.__v_raw) : !!(e && e.__v_isReactive);
}
// @__NO_SIDE_EFFECTS__
function xt(e) {
  return !!(e && e.__v_isReadonly);
}
// @__NO_SIDE_EFFECTS__
function ot(e) {
  return !!(e && e.__v_isShallow);
}
// @__NO_SIDE_EFFECTS__
function Zl(e) {
  return e ? !!e.__v_raw : !1;
}
// @__NO_SIDE_EFFECTS__
function _e(e) {
  const t = e && e.__v_raw;
  return t ? /* @__PURE__ */ _e(t) : e;
}
function Gi(e) {
  return !me(e, "__v_skip") && Object.isExtensible(e) && Ys(e, "__v_skip", !0), e;
}
const it = (e) => $e(e) ? /* @__PURE__ */ Yl(e) : e, Lt = (e) => $e(e) ? /* @__PURE__ */ Vl(e) : e;
// @__NO_SIDE_EFFECTS__
function Ge(e) {
  return e ? e.__v_isRef === !0 : !1;
}
// @__NO_SIDE_EFFECTS__
function H(e) {
  return zi(e, !1);
}
function zi(e, t) {
  return /* @__PURE__ */ Ge(e) ? e : new Ji(e, t);
}
class Ji {
  constructor(t, n) {
    this.dep = new zl(), this.__v_isRef = !0, this.__v_isShallow = !1, this._rawValue = n ? t : /* @__PURE__ */ _e(t), this._value = n ? t : it(t), this.__v_isShallow = n;
  }
  get value() {
    return this.dep.track(), this._value;
  }
  set value(t) {
    const n = this._rawValue, o = this.__v_isShallow || /* @__PURE__ */ ot(t) || /* @__PURE__ */ xt(t);
    t = o ? t : /* @__PURE__ */ _e(t), wt(t, n) && (this._rawValue = t, this._value = o ? t : it(t), this.dep.trigger());
  }
}
function Yi(e) {
  return /* @__PURE__ */ Ge(e) ? e.value : e;
}
const Xi = {
  get: (e, t, n) => t === "__v_raw" ? e : Yi(Reflect.get(e, t, n)),
  set: (e, t, n, o) => {
    const s = e[t];
    return /* @__PURE__ */ Ge(s) && !/* @__PURE__ */ Ge(n) ? (s.value = n, !0) : Reflect.set(e, t, n, o);
  }
};
function ho(e) {
  return /* @__PURE__ */ Ht(e) ? e : new Proxy(e, Xi);
}
class Zi {
  constructor(t, n, o) {
    this.fn = t, this.setter = n, this._value = void 0, this.dep = new zl(this), this.__v_isRef = !0, this.deps = void 0, this.depsTail = void 0, this.flags = 16, this.globalVersion = kn - 1, this.next = void 0, this.effect = this, this.__v_isReadonly = !n, this.isSSR = o;
  }
  /**
   * @internal
   */
  notify() {
    if (this.flags |= 16, !(this.flags & 8) && // avoid infinite self recursion
    Te !== this)
      return no(this, !0), !0;
  }
  get value() {
    const t = this.dep.track();
    return oo(this), t && (t.version = this.dep.version), this._value;
  }
  set value(t) {
    this.setter && this.setter(t);
  }
}
// @__NO_SIDE_EFFECTS__
function Qi(e, t, n = !1) {
  let o, s;
  return fe(e) ? o = e : (o = e.get, s = e.set), new Zi(o, s, n);
}
const Nn = {}, Gn = /* @__PURE__ */ new WeakMap();
let Gt;
function ea(e, t = !1, n = Gt) {
  if (n) {
    let o = Gn.get(n);
    o || Gn.set(n, o = []), o.push(e);
  }
}
function ta(e, t, n = Se) {
  const { immediate: o, deep: s, once: i, scheduler: a, augmentJob: u, call: c } = n, g = (O) => s ? O : /* @__PURE__ */ ot(O) || s === !1 || s === 0 ? Ut(O, 1) : Ut(O);
  let m, b, S, A, Y = !1, M = !1;
  if (/* @__PURE__ */ Ge(e) ? (b = () => e.value, Y = /* @__PURE__ */ ot(e)) : /* @__PURE__ */ Ht(e) ? (b = () => g(e), Y = !0) : de(e) ? (M = !0, Y = e.some((O) => /* @__PURE__ */ Ht(O) || /* @__PURE__ */ ot(O)), b = () => e.map((O) => {
    if (/* @__PURE__ */ Ge(O))
      return O.value;
    if (/* @__PURE__ */ Ht(O))
      return g(O);
    if (fe(O))
      return c ? c(O, 2) : O();
  })) : fe(e) ? t ? b = c ? () => c(e, 2) : e : b = () => {
    if (S) {
      $t();
      try {
        S();
      } finally {
        Ct();
      }
    }
    const O = Gt;
    Gt = m;
    try {
      return c ? c(e, 3, [A]) : e(A);
    } finally {
      Gt = O;
    }
  } : b = kt, t && s) {
    const O = b, L = s === !0 ? 1 / 0 : s;
    b = () => Ut(O(), L);
  }
  const te = Pi(), X = () => {
    m.stop(), te && te.active && Ll(te.effects, m);
  };
  if (i && t) {
    const O = t;
    t = (...L) => {
      try {
        return O(...L);
      } finally {
        X();
      }
    };
  }
  let Q = M ? new Array(e.length).fill(Nn) : Nn;
  const ne = (O) => {
    if (!(!(m.flags & 1) || !m.dirty && !O))
      if (t) {
        const L = m.run();
        if (O || s || Y || (M ? L.some((V, E) => wt(V, Q[E])) : wt(L, Q))) {
          const V = Gt;
          $t();
          try {
            S && S(), Gt = m;
            const E = [
              L,
              // pass undefined as the old value when it's changed for the first time
              Q === Nn ? void 0 : M && Q[0] === Nn ? [] : Q,
              A
            ];
            Q = L, c ? c(t, 3, E) : (
              // @ts-expect-error
              t(...E)
            );
          } finally {
            Gt = V, Ct();
          }
        }
      } else
        m.run();
  };
  return u && u(ne), m = new eo(b), m.scheduler = a ? () => a(ne, !1) : ne, A = (O) => ea(O, !1, m), S = m.onStop = () => {
    const O = Gn.get(m);
    if (O) {
      if (c)
        c(O, 4);
      else
        for (const L of O) L();
      Gn.delete(m);
    }
  }, t ? o ? ne(!0) : Q = m.run() : a ? a(ne.bind(null, !0), !0) : m.run(), X.pause = m.pause.bind(m), X.resume = m.resume.bind(m), X.stop = X, X;
}
function Ut(e, t = 1 / 0, n) {
  if (t <= 0 || !$e(e) || e.__v_skip || (n = n || /* @__PURE__ */ new Map(), (n.get(e) || 0) >= t))
    return e;
  if (n.set(e, t), t--, /* @__PURE__ */ Ge(e))
    Ut(e.value, t, n);
  else if (de(e))
    for (let o = 0; o < e.length; o++)
      Ut(e[o], t, n);
  else if (It(e) || qt(e))
    e.forEach((o) => {
      Ut(o, t, n);
    });
  else if (zs(e)) {
    for (const o in e)
      Ut(e[o], t, n);
    for (const o of Object.getOwnPropertySymbols(e))
      Object.prototype.propertyIsEnumerable.call(e, o) && Ut(e[o], t, n);
  }
  return e;
}
function Un(e, t, n, o) {
  try {
    return o ? e(...o) : e();
  } catch (s) {
    al(s, t, n);
  }
}
function gt(e, t, n, o) {
  if (fe(e)) {
    const s = Un(e, t, n, o);
    return s && Ks(s) && s.catch((i) => {
      al(i, t, n, void 0, !0);
    }), s;
  }
  if (de(e)) {
    const s = [];
    for (let i = 0; i < e.length; i++)
      s.push(gt(e[i], t, n, o));
    return s;
  }
}
function al(e, t, n, o = !0, s = !1) {
  const i = t ? t.vnode : null, { errorHandler: a, throwUnhandledErrorInProduction: u } = t && t.appContext.config || Se;
  if (t) {
    let c = t.parent;
    const g = t.proxy, m = `https://vuejs.org/error-reference/#runtime-${n}`;
    for (; c; ) {
      const b = c.ec;
      if (b && !c.isUnmounted && // Async failures may outlive stopped scopes whose unmount effects
      // are deferred or discarded by Suspense.
      (!s || c.scope.active)) {
        for (let S = 0; S < b.length; S++)
          if (b[S](e, g, m) === !1)
            return;
      }
      c = c.parent;
    }
    if (a) {
      $t(), Un(a, null, 10, [
        e,
        g,
        m
      ]), Ct();
      return;
    }
  }
  na(e, n, i, o, u);
}
function na(e, t, n, o = !0, s = !1) {
  if (s)
    throw e;
  console.error(e);
}
const Ye = [];
let ct = -1;
const bt = [];
let Nt = null, en = 0;
const mo = /* @__PURE__ */ Promise.resolve();
let zn = null;
function Ql(e) {
  const t = zn || mo;
  return e ? t.then(this ? e.bind(this) : e) : t;
}
function la(e) {
  let t = ct + 1, n = Ye.length;
  for (; t < n; ) {
    const o = t + n >>> 1, s = Ye[o], i = Cn(s);
    i < e || i === e && s.flags & 2 ? t = o + 1 : n = o;
  }
  return t;
}
function es(e) {
  if (!(e.flags & 1)) {
    const t = Cn(e), n = Ye[Ye.length - 1];
    !n || // fast path when the job id is larger than the tail
    !(e.flags & 2) && t >= Cn(n) ? Ye.push(e) : Ye.splice(la(t), 0, e), e.flags |= 1, bo();
  }
}
function bo() {
  zn || (zn = mo.then(_o));
}
function sa(e) {
  if (!de(e))
    Nt && e.id === -1 ? Nt.splice(en + 1, 0, e) : e.flags & 1 || (bt.push(e), e.flags |= 1);
  else
    for (let t = 0; t < e.length; t++)
      bt.push(e[t]);
  bo();
}
function yo(e, t, n, o = ct + 1) {
  for (; o < Ye.length; o++) {
    const s = Ye[o];
    if (s && s.flags & 2) {
      if (e && s.id !== e.uid || t !== void 0 && !(s.id >= t))
        continue;
      Ye.splice(o, 1), o = e ? o - 1 : ct, s.flags & 4 && (s.flags &= -2), s(), s.flags & 4 || (s.flags &= -2);
    }
  }
}
function wo(e, t, n = 0) {
  if (bt.length) {
    let o = bt, s = 0;
    if (t) {
      o = [];
      for (let a = 0; a < bt.length; a++) {
        const u = bt[a];
        (u.i !== void 0 ? !u.i || u.i.uid < n : t.has(u)) ? bt[s++] = u : o.push(u);
      }
    }
    const i = [...new Set(o)].sort((a, u) => Cn(a) - Cn(u));
    if (bt.length = s, Nt) {
      for (let a = 0; a < i.length; a++)
        Nt.push(i[a]);
      return;
    }
    for (Nt = i, en = 0; en < Nt.length; en++) {
      const a = Nt[en];
      a.flags & 4 && (a.flags &= -2), a.flags & 8 || a(), a.flags &= -2;
    }
    Nt = null, en = 0;
  }
}
let yl = !1;
function oa(e, t) {
  if (yl) {
    e();
    return;
  }
  const n = t === void 0 ? void 0 : new Set(bt);
  e(), yl = !0;
  try {
    yo(void 0, t), wo(void 0, n, t);
  } finally {
    yl = !1;
  }
}
const Cn = (e) => e.id == null ? e.flags & 2 ? -1 : 1 / 0 : e.id;
function _o(e) {
  try {
    for (ct = 0; ct < Ye.length; ct++) {
      const t = Ye[ct];
      t && !(t.flags & 8) && (t.flags & 4 && (t.flags &= -2), Un(
        t,
        t.i,
        t.i ? 15 : 14
      ), t.flags & 4 || (t.flags &= -2));
    }
  } finally {
    for (; ct < Ye.length; ct++) {
      const t = Ye[ct];
      t && (t.flags &= -2);
    }
    ct = -1, Ye.length = 0, wo(), zn = null, (Ye.length || bt.length) && _o();
  }
}
let Ke = null, ko = null;
function Jn(e) {
  const t = Ke;
  return Ke = e, ko = e && e.type.__scopeId || null, t;
}
function Me(e, t = Ke, n) {
  if (!t || e._n)
    return e;
  const o = (...s) => {
    o._d && As(-1);
    const i = Jn(t), a = Vt.length;
    let u;
    try {
      u = e(...s);
    } finally {
      for (let c = Vt.length; c > a; c--) os();
      Jn(i), o._d && As(1);
    }
    return u;
  };
  return o._n = !0, o._c = !0, o._d = !0, o;
}
function D(e, t) {
  if (Ke === null)
    return e;
  const n = fl(Ke), o = e.dirs || (e.dirs = []);
  for (let s = 0; s < t.length; s++) {
    let [i, a, u, c = Se] = t[s];
    i && (fe(i) && (i = {
      mounted: i,
      updated: i
    }), i.deep && Ut(a), o.push({
      dir: i,
      instance: n,
      value: a,
      oldValue: void 0,
      arg: u,
      modifiers: c
    }));
  }
  return e;
}
function Bt(e, t, n, o) {
  let s = e;
  if (o === "beforeMount")
    e._mount = e;
  else if (o === "beforeUpdate") {
    const u = t && t._mount;
    u && (u._latest = e, e._mount = u);
  } else if (o === "mounted") {
    const u = e._latest;
    e._mount = e._latest = void 0, u && (s = u, u._mount = void 0);
  }
  const i = s.dirs, a = t && t.dirs;
  for (let u = 0; u < i.length; u++) {
    let c = i[u];
    a ? c.oldValue = a[u].value : o === "mounted" && c.oldValue !== void 0 && (c = Ie({}, c, { oldValue: void 0 }));
    let g = c.dir[o];
    g && ($t(), gt(g, n, 8, [
      e.el,
      c,
      s,
      t
    ]), Ct());
  }
}
function ia(e, t) {
  if (Xe) {
    let n = Xe.provides;
    const o = Xe.parent && Xe.parent.provides;
    o === n && (n = Xe.provides = Object.create(o)), n[e] = t;
  }
}
function Bn(e, t, n = !1) {
  const o = ir();
  if (o || nn) {
    let s = nn ? nn._context.provides : o ? o.parent == null || o.ce ? o.vnode.appContext && o.vnode.appContext.provides : o.parent.provides : void 0;
    if (s && e in s)
      return s[e];
    if (arguments.length > 1)
      return n && fe(t) ? t.call(o && o.proxy) : t;
  }
}
const aa = /* @__PURE__ */ Symbol.for("v-scx"), ra = () => Bn(aa);
function st(e, t, n) {
  return $o(e, t, n);
}
function $o(e, t, n = Se) {
  const { immediate: o, deep: s, flush: i, once: a } = n, u = Ie({}, n), c = t && o || !t && i !== "post";
  let g;
  if (En) {
    if (i === "sync") {
      const A = ra();
      g = A.__watcherHandles || (A.__watcherHandles = []);
    } else if (!c) {
      const A = () => {
      };
      return A.stop = kt, A.resume = kt, A.pause = kt, A;
    }
  }
  const m = Xe;
  u.call = (A, Y, M) => gt(A, m, Y, M);
  let b = !1;
  i === "post" ? u.scheduler = (A) => {
    A.i = m, je(A, m && m.suspense);
  } : i !== "sync" && (b = !0, u.scheduler = (A, Y) => {
    Y ? A() : es(A);
  }), u.augmentJob = (A) => {
    t && (A.flags |= 4), b && (A.flags |= 2, m && (A.id = m.uid, A.i = m));
  };
  const S = ta(e, t, u);
  return En && (g ? g.push(S) : c && S()), S;
}
function ua(e, t, n) {
  const o = this.proxy, s = Pe(e) ? e.includes(".") ? Co(o, e) : () => o[e] : e.bind(o, o);
  let i;
  fe(t) ? i = t : (i = t.handler, n = t);
  const a = Vn(this), u = $o(s, i.bind(o), n);
  return a(), u;
}
function Co(e, t) {
  const n = t.split(".");
  return () => {
    let o = e;
    for (let s = 0; s < n.length && o; s++)
      o = o[n[s]];
    return o;
  };
}
const Dt = /* @__PURE__ */ new WeakMap(), xo = /* @__PURE__ */ Symbol("_vte"), rl = (e) => e.__isTeleport, zt = (e) => e && (e.disabled || e.disabled === ""), da = (e) => e && (e.defer || e.defer === ""), bs = (e) => typeof SVGElement < "u" && e instanceof SVGElement, ys = (e) => typeof MathMLElement == "function" && e instanceof MathMLElement, Il = (e, t) => {
  const n = e && e.to;
  return Pe(n) ? t ? t(n) : null : n;
}, ca = {
  name: "Teleport",
  __isTeleport: !0,
  process(e, t, n, o, s, i, a, u, c, g) {
    const {
      mc: m,
      pc: b,
      pbc: S,
      o: { insert: A, querySelector: Y, createText: M, createComment: te, parentNode: X }
    } = g, Q = zt(t.props);
    let { dynamicChildren: ne } = t;
    const O = (E, C, j) => {
      E.shapeFlag & 16 && m(
        E.children,
        C,
        j,
        s,
        i,
        a,
        u,
        c
      );
    }, L = (E = t) => {
      const C = zt(E.props), j = E.target = Il(E.props, Y), Z = Ol(j, E, M, A);
      j && (a !== "svg" && bs(j) ? a = "svg" : a !== "mathml" && ys(j) && (a = "mathml"), s && s.isCE && (s.ce._teleportTargets || (s.ce._teleportTargets = /* @__PURE__ */ new Set())).add(j), C || (O(E, j, Z), cn(E, !1)));
    }, V = (E) => {
      const C = () => {
        if (Dt.get(E) === C) {
          if (Dt.delete(E), zt(E.props)) {
            const j = X(E.el) || n;
            O(E, j, E.anchor), cn(E, !0);
          }
          L(E);
        }
      };
      Dt.set(E, C), je(C, i);
    };
    if (e == null) {
      const E = t.el = M(""), C = t.anchor = M("");
      if (A(E, n, o), A(C, n, o), da(t.props) || i && i.pendingBranch) {
        V(t);
        return;
      }
      Q && (O(t, n, C), cn(t, !0)), L();
    } else {
      t.el = e.el;
      const E = t.anchor = e.anchor, C = Dt.get(e);
      if (C) {
        C.flags |= 8, Dt.delete(e), V(t);
        return;
      }
      t.targetStart = e.targetStart;
      const j = t.target = e.target, Z = t.targetAnchor = e.targetAnchor, pe = zt(e.props), be = pe ? n : j, Ue = pe ? E : Z;
      if (a === "svg" || bs(j) ? a = "svg" : (a === "mathml" || ys(j)) && (a = "mathml"), ne ? (S(
        e.dynamicChildren,
        ne,
        be,
        s,
        i,
        a,
        u
      ), ss(e, t, !0)) : c || b(
        e,
        t,
        be,
        Ue,
        s,
        i,
        a,
        u,
        !1
      ), Q)
        pe ? t.props && e.props && t.props.to !== e.props.to && (t.props.to = e.props.to) : Fn(
          t,
          n,
          E,
          g,
          1
        );
      else if ((t.props && t.props.to) !== (e.props && e.props.to)) {
        const Oe = Il(t.props, Y);
        Oe && (t.target = Oe, Fn(
          t,
          Oe,
          null,
          g,
          0
        ));
      } else pe && Fn(
        t,
        j,
        Z,
        g,
        1
      );
      cn(t, Q);
    }
  },
  remove(e, t, n, { um: o, o: { remove: s } }, i) {
    const {
      shapeFlag: a,
      children: u,
      anchor: c,
      targetStart: g,
      targetAnchor: m,
      target: b,
      props: S
    } = e, A = zt(S), Y = i || !A, M = Dt.get(e);
    if (M && (M.flags |= 8, Dt.delete(e)), b && (s(g), s(m)), i && s(c), !M && (A || b) && a & 16)
      for (let te = 0; te < u.length; te++) {
        const X = u[te];
        o(
          X,
          t,
          n,
          Y,
          !!X.dynamicChildren
        );
      }
  },
  move: Fn,
  hydrate: fa
};
function Fn(e, t, n, { o: { insert: o }, m: s }, i = 2) {
  i === 0 && (e.targetStart && o(e.targetStart, t, n), o(e.targetAnchor, t, n), n = e.targetAnchor);
  const { el: a, anchor: u, shapeFlag: c, children: g, props: m } = e, b = i === 2;
  if (b && o(a, t, n), !Dt.has(e) && (!b || zt(m)) && c & 16)
    for (let S = 0; S < g.length; S++)
      s(
        g[S],
        t,
        n,
        2
      );
  b && o(u, t, n);
}
function fa(e, t, n, o, s, i, {
  o: { nextSibling: a, parentNode: u, querySelector: c, insert: g, createText: m }
}, b) {
  function S(te, X) {
    let Q = X;
    for (; Q; ) {
      if (Q && Q.nodeType === 8) {
        if (Q.data === "teleport start anchor")
          t.targetStart = Q;
        else if (Q.data === "teleport anchor") {
          t.targetAnchor = Q, te._lpa = t.targetAnchor && a(t.targetAnchor);
          break;
        }
      }
      Q = a(Q);
    }
  }
  function A(te, X) {
    X.anchor = b(
      a(te),
      X,
      u(te),
      n,
      o,
      s,
      i
    );
  }
  const Y = t.target = Il(
    t.props,
    c
  ), M = zt(t.props);
  if (Y) {
    const te = Y._lpa || Y.firstChild;
    t.shapeFlag & 16 && (M ? (S(Y, te), A(e, t), t.targetAnchor || Ol(
      Y,
      t,
      m,
      g,
      // if target is the same as the main view, insert anchors before current node
      // to avoid hydrating mismatch
      u(e) === Y ? e : null
    )) : (t.anchor = a(e), S(Y, te), t.targetAnchor || Ol(Y, t, m, g), b(
      te && a(te),
      t,
      Y,
      n,
      o,
      s,
      i
    ))), cn(t, M);
  } else M && t.shapeFlag & 16 && (A(e, t), t.targetStart = e, t.targetAnchor = a(e));
  return t.anchor && a(t.anchor);
}
const pa = ca;
function cn(e, t) {
  const n = e.ctx;
  n && n.ut && (t ? n.ut(e.el, e.anchor) : n.ut(e.targetStart, e.targetAnchor));
}
function Ol(e, t, n, o, s = null) {
  const i = t.targetStart = n(""), a = t.targetAnchor = n("");
  return i[xo] = a, e && (o(i, e, s), o(a, e, s)), a;
}
const wl = /* @__PURE__ */ Symbol("_leaveCb");
function va(e) {
  let t = e[0];
  if (e.length > 1) {
    for (const n of e)
      if (n.type !== at) {
        t = n;
        break;
      }
  }
  return t;
}
function So(e) {
  if (!ts(e))
    return rl(e.type) && e.children ? va(e.children) : e;
  if (e.component)
    return e.component.subTree;
  const { shapeFlag: t, children: n } = e;
  if (n) {
    if (t & 16)
      return n[0];
    if (t & 32 && fe(n.default))
      return n.default();
  }
}
function mn(e, t) {
  if (e.shapeFlag & 6 && e.component) {
    e.transition = t;
    const n = e.component.subTree;
    mn(
      rl(n.type) && So(n) || n,
      t
    );
  } else if (e.shapeFlag & 128) {
    const n = e.suspense;
    if (n) {
      const o = n.isHydrating ? n.pendingBranch : n.activeBranch;
      o && mn(o, t.clone(o));
    } else
      e.ssContent.transition = t.clone(e.ssContent), e.ssFallback.transition = t.clone(e.ssFallback);
  } else if (e.transition = t, e.type === N && de(e.children)) {
    const n = Mo(e.children, !1);
    n && mn(n, t);
  }
}
function Ml(e) {
  if (e.component)
    return Ml(e.component.subTree);
  if (e.type === N) {
    const t = de(e.children) && Mo(e.children, !1);
    return t ? Ml(t) : void 0;
  }
  if (e.type !== at)
    return e;
}
// @__NO_SIDE_EFFECTS__
function qe(e, t) {
  return fe(e) ? (
    // #8236: extend call and options.name access are considered side-effects
    // by Rollup, so we have to wrap it in a pure-annotated IIFE.
    Ie({ name: e.name }, t, { setup: e })
  ) : e;
}
function To(e) {
  e.ids = [e.ids[0] + e.ids[2]++ + "-", 0, 0];
}
function ws(e, t) {
  let n;
  return !!((n = Object.getOwnPropertyDescriptor(e, t)) && !n.configurable);
}
const Yn = /* @__PURE__ */ new WeakMap();
function bn(e, t, n, o, s = !1) {
  if (de(e)) {
    e.forEach(
      (M, te) => bn(
        M,
        t && (de(t) ? t[te] : t),
        n,
        o,
        s
      )
    );
    return;
  }
  if (tn(o) && !s) {
    o.shapeFlag & 512 && o.type.__asyncResolved && o.component.subTree.component && bn(e, t, n, o.component.subTree);
    return;
  }
  const i = o.shapeFlag & 4 ? fl(o.component) : o.el, a = s ? null : i, { i: u, r: c } = e, g = t && t.r, m = u.refs === Se ? u.refs = {} : u.refs, b = u.setupState, S = /* @__PURE__ */ _e(b), A = b === Se ? Bs : (M) => ws(m, M) ? !1 : me(S, M), Y = (M, te) => !(te && ws(m, te));
  if (g != null && g !== c) {
    if (_s(t), Pe(g))
      m[g] = null, A(g) && (b[g] = null);
    else if (/* @__PURE__ */ Ge(g)) {
      const M = t;
      Y(g, M.k) && (g.value = null), M.k && (m[M.k] = null);
    }
  }
  if (fe(c))
    Un(c, u, 12, [a, m]);
  else {
    const M = Pe(c), te = /* @__PURE__ */ Ge(c);
    if (M || te) {
      const X = () => {
        if (e.f) {
          const Q = M ? A(c) ? b[c] : m[c] : Y() || !e.k ? c.value : m[e.k];
          if (s)
            de(Q) && Ll(Q, i);
          else if (de(Q))
            Q.includes(i) || Q.push(i);
          else if (M)
            m[c] = [i], A(c) && (b[c] = m[c]);
          else {
            const ne = [i];
            Y(c, e.k) && (c.value = ne), e.k && (m[e.k] = ne);
          }
        } else M ? (m[c] = a, A(c) && (b[c] = a)) : te && (Y(c, e.k) && (c.value = a), e.k && (m[e.k] = a));
      };
      if (a) {
        const Q = () => {
          X(), Yn.delete(e);
        };
        Q.id = -1, Yn.set(e, Q), je(Q, n);
      } else
        _s(e), X();
    }
  }
}
function _s(e) {
  const t = Yn.get(e);
  t && (t.flags |= 8, Yn.delete(e));
}
ol().requestIdleCallback;
ol().cancelIdleCallback;
const tn = (e) => !!e.type.__asyncLoader, ts = (e) => e.type.__isKeepAlive;
function ga(e, t) {
  Eo(e, "a", t);
}
function ha(e, t) {
  Eo(e, "da", t);
}
function Eo(e, t, n = Xe) {
  const o = e.__wdc || (e.__wdc = () => {
    let s = n;
    for (; s; ) {
      if (s.isDeactivated)
        return;
      s = s.parent;
    }
    return e();
  });
  if (xn(t, o, n), n) {
    let s = n.parent;
    for (; s && s.parent; )
      ts(s.parent.vnode) && ma(o, t, n, s), s = s.parent;
  }
}
function ma(e, t, n, o) {
  const s = xn(
    t,
    e,
    o,
    !0
    /* prepend */
  ), i = xn(
    "um",
    () => Ll(o[t], s),
    n
  );
  i.flags = 16;
}
function xn(e, t, n = Xe, o = !1) {
  if (n) {
    const s = n[e] || (n[e] = []), i = t.__weh || (t.__weh = (...a) => {
      $t();
      const u = Vn(n), c = gt(t, n, e, a);
      return u(), Ct(), c;
    });
    return o ? s.unshift(i) : s.push(i), i;
  }
}
const Mt = (e) => (t, n = Xe) => {
  (!En || e === "sp") && xn(e, (...o) => t(...o), n);
}, ba = Mt("bm"), rt = Mt("m"), ya = Mt(
  "bu"
), wa = Mt("u"), Po = Mt(
  "bum"
), Rt = Mt("um"), _a = Mt(
  "sp"
), ka = Mt("rtg"), $a = Mt("rtc");
function Ca(e, t = Xe) {
  xn("ec", e, t);
}
const xa = /* @__PURE__ */ Symbol.for("v-ndc");
function ie(e, t, n, o) {
  let s;
  const i = n, a = de(e);
  if (a || Pe(e)) {
    const u = a && /* @__PURE__ */ Ht(e);
    let c = !1, g = !1;
    u && (c = !/* @__PURE__ */ ot(e), g = /* @__PURE__ */ xt(e), e = il(e)), s = new Array(e.length);
    for (let m = 0, b = e.length; m < b; m++)
      s[m] = t(
        c ? g ? Lt(it(e[m])) : it(e[m]) : e[m],
        m,
        void 0,
        i
      );
  } else if (typeof e == "number")
    if (!Number.isInteger(e) || e < 0)
      s = [];
    else {
      s = new Array(e);
      for (let u = 0; u < e; u++)
        s[u] = t(u + 1, u, void 0, i);
    }
  else if ($e(e))
    if (e[Symbol.iterator])
      s = Array.from(
        e,
        (u, c) => t(u, c, void 0, i)
      );
    else {
      const u = Object.keys(e);
      s = new Array(u.length);
      for (let c = 0, g = u.length; c < g; c++) {
        const m = u[c];
        s[c] = t(e[m], m, c, i);
      }
    }
  else
    s = [];
  return s;
}
function Sa(e, t, n, o, s, i) {
  if (n == null && (n = {}), Ke.ce || Ke.parent && tn(Ke.parent) && Ke.parent.ce) {
    const g = n, m = Object.keys(g).length > 0;
    return f(), ge(
      N,
      null,
      [Ze("slot", g, o)],
      m ? -2 : 64
    );
  }
  let a = e[t];
  a && a._c && (a._d = !1);
  const u = Vt.length;
  f();
  let c;
  try {
    const g = a && Ao(a(n)), m = n.key || i || // slot content array of a dynamic conditional slot may have a branch
    // key attached in the `createSlots` helper, respect that
    g && g.key;
    c = ge(
      N,
      {
        key: (m && !vt(m) ? m : `_${t}`) + // #7256 force differentiate fallback content from actual content
        (!g && o ? "_fb" : "")
      },
      g || (o ? o() : []),
      g && e._ === 1 ? 64 : -2
    );
  } catch (g) {
    for (let m = Vt.length; m > u; m--) os();
    throw g;
  } finally {
    a && a._c && (a._d = !0);
  }
  return c.scopeId && (c.slotScopeIds = [c.scopeId + "-s"]), c;
}
function Ao(e) {
  return e.some((t) => cl(t) ? !(t.type === at || t.type === N && !Ao(t.children)) : !0) ? e : null;
}
const Rl = (e) => e ? Yo(e) ? fl(e) : Rl(e.parent) : null, yn = (
  // Move PURE marker to new line to workaround compiler discarding it
  // due to type annotation
  /* @__PURE__ */ Ie(/* @__PURE__ */ Object.create(null), {
    $: (e) => e,
    $el: (e) => e.vnode.el,
    $data: (e) => e.data,
    $props: (e) => e.props,
    $attrs: (e) => e.attrs,
    $slots: (e) => e.slots,
    $refs: (e) => e.refs,
    $parent: (e) => Rl(e.parent),
    $root: (e) => Rl(e.root),
    $host: (e) => e.ce,
    $emit: (e) => e.emit,
    $options: (e) => Vo(e),
    $forceUpdate: (e) => e.f || (e.f = () => {
      es(e.update);
    }),
    $nextTick: (e) => e.n || (e.n = Ql.bind(e.proxy)),
    $watch: (e) => ua.bind(e)
  })
), _l = (e, t) => e !== Se && !e.__isScriptSetup && me(e, t), Ta = {
  get({ _: e }, t) {
    if (t === "__v_skip")
      return !0;
    const { ctx: n, setupState: o, data: s, props: i, accessCache: a, type: u, appContext: c } = e;
    if (t[0] !== "$") {
      const S = a[t];
      if (S !== void 0)
        switch (S) {
          case 1:
            return o[t];
          case 2:
            return s[t];
          case 4:
            return n[t];
          case 3:
            return i[t];
        }
      else {
        if (_l(o, t))
          return a[t] = 1, o[t];
        if (s !== Se && me(s, t))
          return a[t] = 2, s[t];
        if (me(i, t))
          return a[t] = 3, i[t];
        if (n !== Se && me(n, t))
          return a[t] = 4, n[t];
        Dl && (a[t] = 0);
      }
    }
    const g = yn[t];
    let m, b;
    if (g)
      return t === "$attrs" && We(e.attrs, "get", ""), g(e);
    if (
      // css module (injected by vue-loader)
      (m = u.__cssModules) && (m = m[t])
    )
      return m;
    if (n !== Se && me(n, t))
      return a[t] = 4, n[t];
    if (
      // global properties
      b = c.config.globalProperties, me(b, t)
    )
      return b[t];
  },
  set({ _: e }, t, n) {
    const { data: o, setupState: s, ctx: i } = e;
    return _l(s, t) ? (s[t] = n, !0) : o !== Se && me(o, t) ? (o[t] = n, !0) : me(e.props, t) || t[0] === "$" && t.slice(1) in e ? !1 : (i[t] = n, !0);
  },
  has({
    _: { data: e, setupState: t, accessCache: n, ctx: o, appContext: s, props: i, type: a }
  }, u) {
    let c;
    return !!(n[u] || e !== Se && u[0] !== "$" && me(e, u) || _l(t, u) || me(i, u) || me(o, u) || me(yn, u) || me(s.config.globalProperties, u) || (c = a.__cssModules) && c[u]);
  },
  defineProperty(e, t, n) {
    return n.get != null ? e._.accessCache[t] = 0 : me(n, "value") && this.set(e, t, n.value, null), Reflect.defineProperty(e, t, n);
  }
};
function ks(e) {
  return de(e) ? e.reduce(
    (t, n) => (t[n] = null, t),
    {}
  ) : e;
}
let Dl = !0;
function Ea(e) {
  const t = Vo(e), n = e.proxy, o = e.ctx;
  Dl = !1, t.beforeCreate && $s(t.beforeCreate, e, "bc");
  const {
    // state
    data: s,
    computed: i,
    methods: a,
    watch: u,
    provide: c,
    inject: g,
    // lifecycle
    created: m,
    beforeMount: b,
    mounted: S,
    beforeUpdate: A,
    updated: Y,
    activated: M,
    deactivated: te,
    beforeDestroy: X,
    beforeUnmount: Q,
    destroyed: ne,
    unmounted: O,
    render: L,
    renderTracked: V,
    renderTriggered: E,
    errorCaptured: C,
    serverPrefetch: j,
    // public API
    expose: Z,
    inheritAttrs: pe,
    // assets
    components: be,
    directives: Ue,
    filters: Oe
  } = t;
  if (g && Pa(g, o, null), a)
    for (const d in a) {
      const r = a[d];
      fe(r) && (o[d] = r.bind(n));
    }
  if (s) {
    const d = s.call(n, n);
    $e(d) && (e.data = /* @__PURE__ */ Yl(d));
  }
  if (Dl = !0, i)
    for (const d in i) {
      const r = i[d], p = fe(r) ? r.bind(n, n) : fe(r.get) ? r.get.bind(n, n) : kt, _ = !fe(r) && fe(r.set) ? r.set.bind(n) : kt, K = ke({
        get: p,
        set: _
      });
      Object.defineProperty(o, d, {
        enumerable: !0,
        configurable: !0,
        get: () => K.value,
        set: (Ce) => K.value = Ce
      });
    }
  if (u)
    for (const d in u)
      Uo(u[d], o, n, d);
  if (c) {
    const d = fe(c) ? c.call(n) : c;
    Reflect.ownKeys(d).forEach((r) => {
      ia(r, d[r]);
    });
  }
  m && $s(m, e, "c");
  function P(d, r) {
    de(r) ? r.forEach((p) => d(p.bind(n))) : r && d(r.bind(n));
  }
  if (P(ba, b), P(rt, S), P(ya, A), P(wa, Y), P(ga, M), P(ha, te), P(Ca, C), P($a, V), P(ka, E), P(Po, Q), P(Rt, O), P(_a, j), de(Z))
    if (Z.length) {
      const d = e.exposed || (e.exposed = {});
      Z.forEach((r) => {
        Object.defineProperty(d, r, {
          get: () => n[r],
          set: (p) => n[r] = p,
          enumerable: !0
        });
      });
    } else e.exposed || (e.exposed = {});
  L && e.render === kt && (e.render = L), pe != null && (e.inheritAttrs = pe), be && (e.components = be), Ue && (e.directives = Ue), j && To(e);
}
function Pa(e, t, n = kt) {
  de(e) && (e = Nl(e));
  for (const o in e) {
    const s = e[o];
    let i;
    $e(s) ? "default" in s ? i = Bn(
      s.from || o,
      s.default,
      !0
    ) : i = Bn(s.from || o) : i = Bn(s), /* @__PURE__ */ Ge(i) ? Object.defineProperty(t, o, {
      enumerable: !0,
      configurable: !0,
      get: () => i.value,
      set: (a) => i.value = a
    }) : t[o] = i;
  }
}
function $s(e, t, n) {
  gt(
    de(e) ? e.map((o) => o.bind(t.proxy)) : e.bind(t.proxy),
    t,
    n
  );
}
function Uo(e, t, n, o) {
  let s = o.includes(".") ? Co(n, o) : () => n[o];
  if (Pe(e)) {
    const i = t[e];
    fe(i) && st(s, i);
  } else if (fe(e))
    st(s, e.bind(n));
  else if ($e(e))
    if (de(e))
      e.forEach((i) => Uo(i, t, n, o));
    else {
      const i = fe(e.handler) ? e.handler.bind(n) : t[e.handler];
      fe(i) && st(s, i, e);
    }
}
function Vo(e) {
  const t = e.type, { mixins: n, extends: o } = t, {
    mixins: s,
    optionsCache: i,
    config: { optionMergeStrategies: a }
  } = e.appContext, u = i.get(t);
  let c;
  return u ? c = u : !s.length && !n && !o ? c = t : (c = {}, s.length && s.forEach(
    (g) => Xn(c, g, a, !0)
  ), Xn(c, t, a)), $e(t) && i.set(t, c), c;
}
function Xn(e, t, n, o = !1) {
  const { mixins: s, extends: i } = t;
  i && Xn(e, i, n, !0), s && s.forEach(
    (a) => Xn(e, a, n, !0)
  );
  for (const a in t)
    if (!(o && a === "expose")) {
      const u = Aa[a] || n && n[a];
      e[a] = u ? u(e[a], t[a]) : t[a];
    }
  return e;
}
const Aa = {
  data: Cs,
  props: xs,
  emits: xs,
  // objects
  methods: fn,
  computed: fn,
  // lifecycle
  beforeCreate: Je,
  created: Je,
  beforeMount: Je,
  mounted: Je,
  beforeUpdate: Je,
  updated: Je,
  beforeDestroy: Je,
  beforeUnmount: Je,
  destroyed: Je,
  unmounted: Je,
  activated: Je,
  deactivated: Je,
  errorCaptured: Je,
  serverPrefetch: Je,
  // assets
  components: fn,
  directives: fn,
  // watch
  watch: Va,
  // provide / inject
  provide: Cs,
  inject: Ua
};
function Cs(e, t) {
  return t ? e ? function() {
    return Ie(
      fe(e) ? e.call(this, this) : e,
      fe(t) ? t.call(this, this) : t
    );
  } : t : e;
}
function Ua(e, t) {
  return fn(Nl(e), Nl(t));
}
function Nl(e) {
  if (de(e)) {
    const t = {};
    for (let n = 0; n < e.length; n++)
      t[e[n]] = e[n];
    return t;
  }
  return e;
}
function Je(e, t) {
  return e ? [...new Set([].concat(e, t))] : t;
}
function fn(e, t) {
  return e ? Ie(/* @__PURE__ */ Object.create(null), e, t) : t;
}
function xs(e, t) {
  return e ? de(e) && de(t) ? [.../* @__PURE__ */ new Set([...e, ...t])] : Ie(
    /* @__PURE__ */ Object.create(null),
    ks(e),
    ks(t ?? {})
  ) : t;
}
function Va(e, t) {
  if (!e) return t;
  if (!t) return e;
  const n = Ie(/* @__PURE__ */ Object.create(null), e);
  for (const o in t)
    n[o] = Je(e[o], t[o]);
  return n;
}
function Io() {
  return {
    app: null,
    config: {
      isNativeTag: Bs,
      performance: !1,
      globalProperties: {},
      optionMergeStrategies: {},
      errorHandler: void 0,
      warnHandler: void 0,
      compilerOptions: {}
    },
    mixins: [],
    components: {},
    directives: {},
    provides: /* @__PURE__ */ Object.create(null),
    optionsCache: /* @__PURE__ */ new WeakMap(),
    propsCache: /* @__PURE__ */ new WeakMap(),
    emitsCache: /* @__PURE__ */ new WeakMap()
  };
}
let Ia = 0;
function Oa(e, t) {
  return function(o, s = null) {
    fe(o) || (o = Ie({}, o)), s != null && !$e(s) && (s = null);
    const i = Io(), a = /* @__PURE__ */ new WeakSet(), u = [];
    let c = !1;
    const g = i.app = {
      _uid: Ia++,
      _component: o,
      _props: s,
      _container: null,
      _context: i,
      _instance: null,
      version: fr,
      get config() {
        return i.config;
      },
      set config(m) {
      },
      use(m, ...b) {
        return a.has(m) || (m && fe(m.install) ? (a.add(m), m.install(g, ...b)) : fe(m) && (a.add(m), m(g, ...b))), g;
      },
      mixin(m) {
        return i.mixins.includes(m) || i.mixins.push(m), g;
      },
      component(m, b) {
        return b ? (i.components[m] = b, g) : i.components[m];
      },
      directive(m, b) {
        return b ? (i.directives[m] = b, g) : i.directives[m];
      },
      mount(m, b, S) {
        if (!c) {
          const A = g._ceVNode || Ze(o, s);
          return A.appContext = i, S === !0 ? S = "svg" : S === !1 && (S = void 0), e(A, m, S), c = !0, g._container = m, m.__vue_app__ = g, fl(A.component);
        }
      },
      onUnmount(m) {
        u.push(m);
      },
      unmount() {
        c && (gt(
          u,
          g._instance,
          16
        ), e(null, g._container), delete g._container.__vue_app__);
      },
      provide(m, b) {
        return i.provides[m] = b, g;
      },
      runWithContext(m) {
        const b = nn;
        nn = g;
        try {
          return m();
        } finally {
          nn = b;
        }
      }
    };
    return g;
  };
}
let nn = null;
const Ma = (e, t) => t === "modelValue" || t === "model-value" ? e.modelModifiers : e[`${t}Modifiers`] || e[`${ft(t)}Modifiers`] || e[`${jt(t)}Modifiers`];
function Ra(e, t, ...n) {
  if (e.isUnmounted) return;
  const o = e.vnode.props || Se;
  let s = n;
  const i = t.startsWith("update:"), a = i && Ma(o, t.slice(7));
  a && (a.trim && (s = n.map((m) => Pe(m) ? m.trim() : m)), a.number && (s = s.map(An)));
  let u, c = o[u = vl(t)] || // also try camelCase event handler (#2249)
  o[u = vl(ft(t))];
  !c && i && (c = o[u = vl(jt(t))]), c && gt(
    c,
    e,
    6,
    s
  );
  const g = o[u + "Once"];
  if (g) {
    if (!e.emitted)
      e.emitted = {};
    else if (e.emitted[u])
      return;
    e.emitted[u] = !0, gt(
      g,
      e,
      6,
      s
    );
  }
}
const Da = /* @__PURE__ */ new WeakMap();
function Oo(e, t, n = !1) {
  const o = n ? Da : t.emitsCache, s = o.get(e);
  if (s !== void 0)
    return s;
  const i = e.emits;
  let a = {}, u = !1;
  if (!fe(e)) {
    const c = (g) => {
      const m = Oo(g, t, !0);
      m && (u = !0, Ie(a, m));
    };
    !n && t.mixins.length && t.mixins.forEach(c), e.extends && c(e.extends), e.mixins && e.mixins.forEach(c);
  }
  return !i && !u ? ($e(e) && o.set(e, null), null) : (de(i) ? i.forEach((c) => a[c] = null) : Ie(a, i), $e(e) && o.set(e, a), a);
}
function ul(e, t) {
  return !e || !nl(t) ? !1 : (t = t.slice(2), t = t === "Once" ? t : t.replace(/Once$/, ""), me(e, t[0].toLowerCase() + t.slice(1)) || me(e, jt(t)) || me(e, t));
}
function Ss(e) {
  const {
    type: t,
    vnode: n,
    proxy: o,
    withProxy: s,
    propsOptions: [i],
    slots: a,
    attrs: u,
    emit: c,
    render: g,
    renderCache: m,
    props: b,
    data: S,
    setupState: A,
    ctx: Y,
    inheritAttrs: M
  } = e, te = Jn(e);
  let X, Q;
  try {
    if (n.shapeFlag & 4) {
      const O = s || o, L = O;
      X = yt(
        g.call(
          L,
          O,
          m,
          b,
          A,
          S,
          Y
        )
      ), Q = u;
    } else {
      const O = t;
      X = yt(
        O.length > 1 ? O(
          b,
          { attrs: u, slots: a, emit: c }
        ) : O(
          b,
          null
        )
      ), Q = t.props ? u : Na(u);
    }
  } catch (O) {
    Vt.length = 0, al(O, e, 1), X = Ze(at);
  }
  let ne = X;
  if (Q && M !== !1) {
    const O = Object.keys(Q), { shapeFlag: L } = ne;
    O.length && L & 7 && (i && O.some(ll) && (Q = Fa(
      Q,
      i
    )), ne = ln(ne, Q, !1, !0));
  }
  if (n.dirs && (ne = ln(ne, null, !1, !0), ne.dirs = ne.dirs ? ne.dirs.concat(n.dirs) : n.dirs), n.transition) {
    const O = rl(ne.type) && So(ne) || ne;
    mn(O, n.transition);
  }
  return X = ne, Jn(te), X;
}
function Mo(e, t = !0) {
  let n;
  for (let o = 0; o < e.length; o++) {
    const s = e[o];
    if (cl(s)) {
      if (s.type !== at || s.children === "v-if") {
        if (n)
          return;
        n = s;
      }
    } else
      return;
  }
  return n;
}
const Na = (e) => {
  let t;
  for (const n in e)
    (n === "class" || n === "style" || nl(n)) && ((t || (t = {}))[n] = e[n]);
  return t;
}, Fa = (e, t) => {
  const n = {};
  for (const o in e)
    (!ll(o) || !(o.slice(9) in t)) && (n[o] = e[o]);
  return n;
};
function qa(e, t, n) {
  const { props: o, children: s, component: i } = e, { props: a, children: u, patchFlag: c } = t, g = i.emitsOptions;
  if (t.dirs || t.transition)
    return !0;
  if (n && c >= 0) {
    if (c & 1024)
      return !0;
    if (c & 16)
      return o ? Ts(o, a, g) : !!a;
    if (c & 8) {
      const m = t.dynamicProps;
      for (let b = 0; b < m.length; b++) {
        const S = m[b];
        if (Ro(a, o, S) && !ul(g, S))
          return !0;
      }
    }
  } else
    return (s || u) && (!u || !u.$stable) ? !0 : o === a ? !1 : o ? a ? Ts(o, a, g) : !0 : !!a;
  return !1;
}
function Ts(e, t, n) {
  const o = Object.keys(t);
  if (o.length !== Object.keys(e).length)
    return !0;
  for (let s = 0; s < o.length; s++) {
    const i = o[s];
    if (!me(e, i) || Ro(t, e, i) && !ul(n, i))
      return !0;
  }
  return !1;
}
function Ro(e, t, n) {
  const o = e[n], s = t[n];
  return n === "style" && $e(o) && $e(s) ? !Ot(o, s) : o !== s;
}
function Ha({ vnode: e, parent: t, suspense: n }, o) {
  for (; t; ) {
    const s = t.subTree;
    if (s.suspense && s.suspense.activeBranch === e && (s.suspense.vnode.el = s.el = o, e = s), s === e)
      (e = t.vnode).el = o, t = t.parent;
    else
      break;
  }
  n && n.activeBranch === e && (n.vnode.el = o);
}
const Do = {}, No = () => Object.create(Do), Fo = (e) => Object.getPrototypeOf(e) === Do;
function La(e, t, n, o = !1) {
  const s = {}, i = No();
  e.propsDefaults = /* @__PURE__ */ Object.create(null), qo(e, t, s, i);
  for (const a in e.propsOptions[0])
    a in s || (s[a] = void 0);
  n ? e.props = o ? s : /* @__PURE__ */ Ki(s) : e.type.props ? e.props = s : e.props = i, e.attrs = i;
}
function ja(e, t, n, o) {
  const {
    props: s,
    attrs: i,
    vnode: { patchFlag: a }
  } = e, u = /* @__PURE__ */ _e(s), [c] = e.propsOptions;
  let g = !1;
  if (
    // always force full diff in dev
    // - #1942 if hmr is enabled with sfc component
    // - vite#872 non-sfc component used by sfc component
    (o || a > 0) && !(a & 16)
  ) {
    if (a & 8) {
      const m = e.vnode.dynamicProps;
      for (let b = 0; b < m.length; b++) {
        let S = m[b];
        if (ul(e.emitsOptions, S))
          continue;
        const A = t[S];
        if (c)
          if (me(i, S))
            A !== i[S] && (i[S] = A, g = !0);
          else {
            const Y = ft(S);
            s[Y] = Fl(
              c,
              u,
              Y,
              A,
              e,
              !1
            );
          }
        else
          A !== i[S] && (i[S] = A, g = !0);
      }
    }
  } else {
    qo(e, t, s, i) && (g = !0);
    let m;
    for (const b in u)
      (!t || // for camelCase
      !me(t, b) && // it's possible the original props was passed in as kebab-case
      // and converted to camelCase (#955)
      ((m = jt(b)) === b || !me(t, m))) && (c ? n && // for camelCase
      (n[b] !== void 0 || // for kebab-case
      n[m] !== void 0) && (s[b] = Fl(
        c,
        u,
        b,
        void 0,
        e,
        !0
      )) : delete s[b]);
    if (i !== u)
      for (const b in i)
        (!t || !me(t, b)) && (delete i[b], g = !0);
  }
  g && At(e.attrs, "set", "");
}
function qo(e, t, n, o) {
  const [s, i] = e.propsOptions;
  let a = !1, u;
  if (t)
    for (let c in t) {
      if (vn(c))
        continue;
      const g = t[c];
      let m;
      s && me(s, m = ft(c)) ? !i || !i.includes(m) ? n[m] = g : (u || (u = {}))[m] = g : ul(e.emitsOptions, c) || (!(c in o) || g !== o[c]) && (o[c] = g, a = !0);
    }
  if (i) {
    const c = /* @__PURE__ */ _e(n), g = u || Se;
    for (let m = 0; m < i.length; m++) {
      const b = i[m];
      n[b] = Fl(
        s,
        c,
        b,
        g[b],
        e,
        !me(g, b)
      );
    }
  }
  return a;
}
function Fl(e, t, n, o, s, i) {
  const a = e[n];
  if (a != null) {
    const u = me(a, "default");
    if (u && o === void 0) {
      const c = a.default;
      if (a.type !== Function && !a.skipFactory && fe(c)) {
        const { propsDefaults: g } = s;
        if (n in g)
          o = g[n];
        else {
          const m = Vn(s);
          o = g[n] = c.call(
            null,
            t
          ), m();
        }
      } else
        o = c;
      s.ce && s.ce._setProp(n, o);
    }
    a[
      0
      /* shouldCast */
    ] && (i && !u ? o = !1 : a[
      1
      /* shouldCastTrue */
    ] && (o === "" || o === jt(n)) && (o = !0));
  }
  return o;
}
const Wa = /* @__PURE__ */ new WeakMap();
function Ho(e, t, n = !1) {
  const o = n ? Wa : t.propsCache, s = o.get(e);
  if (s)
    return s;
  const i = e.props, a = {}, u = [];
  let c = !1;
  if (!fe(e)) {
    const m = (b) => {
      c = !0;
      const [S, A] = Ho(b, t, !0);
      Ie(a, S), A && u.push(...A);
    };
    !n && t.mixins.length && t.mixins.forEach(m), e.extends && m(e.extends), e.mixins && e.mixins.forEach(m);
  }
  if (!i && !c)
    return $e(e) && o.set(e, Jt), Jt;
  if (de(i))
    for (let m = 0; m < i.length; m++) {
      const b = ft(i[m]);
      Es(b) && (a[b] = Se);
    }
  else if (i)
    for (const m in i) {
      const b = ft(m);
      if (Es(b)) {
        const S = i[m], A = a[b] = de(S) || fe(S) ? { type: S } : Ie({}, S), Y = A.type;
        let M = !1, te = !0;
        if (de(Y))
          for (let X = 0; X < Y.length; ++X) {
            const Q = Y[X], ne = fe(Q) && Q.name;
            if (ne === "Boolean") {
              M = !0;
              break;
            } else ne === "String" && (te = !1);
          }
        else
          M = fe(Y) && Y.name === "Boolean";
        A[
          0
          /* shouldCast */
        ] = M, A[
          1
          /* shouldCastTrue */
        ] = te, (M || me(A, "default")) && u.push(b);
      }
    }
  const g = [a, u];
  return $e(e) && o.set(e, g), g;
}
function Es(e) {
  return e[0] !== "$" && !vn(e);
}
const ns = (e) => e === "_" || e === "_ctx" || e === "$stable", ls = (e) => de(e) ? e.map(yt) : [yt(e)], Ba = (e, t, n) => {
  if (t._n)
    return t;
  const o = Me((...s) => ls(t(...s)), n);
  return o._c = !1, o;
}, Lo = (e, t, n) => {
  const o = e._ctx;
  for (const s in e) {
    if (ns(s)) continue;
    const i = e[s];
    if (fe(i))
      t[s] = Ba(s, i, o);
    else if (i != null) {
      const a = ls(i);
      t[s] = () => a;
    }
  }
}, jo = (e, t) => {
  const n = ls(t);
  e.slots.default = () => n;
}, Wo = (e, t, n) => {
  for (const o in t)
    (n || !ns(o)) && (e[o] = t[o]);
}, Ka = (e, t, n) => {
  const o = e.slots = No();
  if (e.vnode.shapeFlag & 32) {
    const s = t._;
    s ? (Wo(o, t, n), n && Ys(o, "_", s, !0)) : Lo(t, o);
  } else t && jo(e, t);
}, Ga = (e, t, n) => {
  const { vnode: o, slots: s } = e;
  let i = !0, a = Se;
  if (o.shapeFlag & 32) {
    const u = t._;
    u ? n && u === 1 ? i = !1 : Wo(s, t, n) : (i = !t.$stable, Lo(t, s)), a = t;
  } else t && (jo(e, t), a = { default: 1 });
  if (i)
    for (const u in s)
      !ns(u) && a[u] == null && delete s[u];
}, je = Qa;
function za(e) {
  return Ja(e);
}
function Ja(e, t) {
  const n = ol();
  n.__VUE__ = !0;
  const {
    insert: o,
    remove: s,
    patchProp: i,
    createElement: a,
    createText: u,
    createComment: c,
    setText: g,
    setElementText: m,
    parentNode: b,
    nextSibling: S,
    setScopeId: A = kt,
    insertStaticContent: Y
  } = e, M = (w, k, U, W = null, R = null, q = null, z = void 0, B = null, G = !!k.dynamicChildren) => {
    if (w === k)
      return;
    w && !un(w, k) && (W = ut(w), Ce(w, R, q, !0), w = null), k.patchFlag === -2 && (G = !1, k.dynamicChildren = null), k.dynamicChildren && w && w.dynamicChildren && w.dynamicChildren.hasOnce && (k.dynamicChildren === Jt && (k.dynamicChildren = []), k.dynamicChildren.hasOnce = !0);
    const { type: F, ref: ae, shapeFlag: ee } = k;
    switch (F) {
      case dl:
        te(w, k, U, W);
        break;
      case at:
        X(w, k, U, W);
        break;
      case $l:
        w == null && Q(k, U, W, z);
        break;
      case N:
        be(
          w,
          k,
          U,
          W,
          R,
          q,
          z,
          B,
          G
        );
        break;
      default:
        ee & 1 ? L(
          w,
          k,
          U,
          W,
          R,
          q,
          z,
          B,
          G
        ) : ee & 6 ? Ue(
          w,
          k,
          U,
          W,
          R,
          q,
          z,
          B,
          G
        ) : (ee & 64 || ee & 128) && F.process(
          w,
          k,
          U,
          W,
          R,
          q,
          z,
          B,
          G,
          dt
        );
    }
    ae != null && R ? bn(ae, w && w.ref, q, k || w, !k) : ae == null && w && w.ref != null && bn(w.ref, null, q, w, !0);
  }, te = (w, k, U, W) => {
    if (w == null)
      o(
        k.el = u(k.children),
        U,
        W
      );
    else {
      const R = k.el = w.el;
      k.children !== w.children && g(R, k.children);
    }
  }, X = (w, k, U, W) => {
    w == null ? o(
      k.el = c(k.children || ""),
      U,
      W
    ) : k.el = w.el;
  }, Q = (w, k, U, W) => {
    [w.el, w.anchor] = Y(
      w.children,
      k,
      U,
      W,
      w.el,
      w.anchor
    );
  }, ne = ({ el: w, anchor: k }, U, W) => {
    let R;
    for (; w && w !== k; )
      R = S(w), o(w, U, W), w = R;
    o(k, U, W);
  }, O = ({ el: w, anchor: k }) => {
    let U;
    for (; w && w !== k; )
      U = S(w), s(w), w = U;
    s(k);
  }, L = (w, k, U, W, R, q, z, B, G) => {
    if (k.type === "svg" ? z = "svg" : k.type === "math" && (z = "mathml"), w == null)
      V(
        k,
        U,
        W,
        R,
        q,
        z,
        B,
        G
      );
    else {
      const F = w.el && w.el._isVueCE ? w.el : null;
      try {
        F && F._beginPatch(), j(
          w,
          k,
          R,
          q,
          z,
          B,
          G
        );
      } finally {
        F && F._endPatch();
      }
    }
  }, V = (w, k, U, W, R, q, z, B) => {
    let G, F;
    const { props: ae, shapeFlag: ee, transition: re, dirs: se } = w;
    if (G = w.el = a(
      w.type,
      q,
      ae && ae.is,
      ae
    ), ee & 8 ? m(G, w.children) : ee & 16 && C(
      w.children,
      G,
      null,
      W,
      R,
      kl(w, q),
      z,
      B
    ), se && Bt(w, null, W, "created"), E(G, w, w.scopeId, z, W), ae) {
      for (const we in ae)
        we !== "value" && !vn(we) && i(G, we, null, ae[we], q, W);
      "value" in ae && i(G, "value", null, ae.value, q), (F = ae.onVnodeBeforeMount) && ht(F, W, w);
    }
    se && Bt(w, null, W, "beforeMount");
    const ve = Ya(R, re);
    ve ? re.beforeEnter(G) : re && !re.persisted && (G[Za] = !0), o(G, k, U), ((F = ae && ae.onVnodeMounted) || ve || se) && je(() => {
      F && ht(F, W, w), ve && re.enter(G), se && Bt(w, null, W, "mounted");
    }, R);
  }, E = (w, k, U, W, R) => {
    if (U && A(w, U), W)
      for (let q = 0; q < W.length; q++)
        A(w, W[q]);
    if (R) {
      let q = R.subTree;
      if (k === q || Ko(q.type) && (q.ssContent === k || q.ssFallback === k)) {
        const z = R.vnode;
        E(
          w,
          z,
          z.scopeId,
          z.slotScopeIds,
          R.parent
        );
      }
    }
  }, C = (w, k, U, W, R, q, z, B, G = 0) => {
    for (let F = G; F < w.length; F++) {
      const ae = w[F] = B ? Pt(w[F]) : yt(w[F]);
      M(
        null,
        ae,
        k,
        U,
        W,
        R,
        q,
        z,
        B
      );
    }
  }, j = (w, k, U, W, R, q, z) => {
    const B = k.el = w.el;
    let { patchFlag: G, dynamicChildren: F, dirs: ae } = k;
    G |= w.patchFlag & 16;
    const ee = w.props || Se, re = k.props || Se;
    let se;
    if (U && Kt(U, !1), (se = re.onVnodeBeforeUpdate) && ht(se, U, k, w), ae && Bt(k, w, U, "beforeUpdate"), U && Kt(U, !0), // #6385 the old vnode may be a user-wrapped non-isomorphic block
    // Force full diff when block metadata is unstable.
    F && (!w.dynamicChildren || w.dynamicChildren.length !== F.length) && (G = 0, z = !1, F = null), (ee.innerHTML && re.innerHTML == null || ee.textContent && re.textContent == null) && m(B, ""), F ? Z(
      w.dynamicChildren,
      F,
      B,
      U,
      W,
      kl(k, R),
      q
    ) : z || r(
      w,
      k,
      B,
      null,
      U,
      W,
      kl(k, R),
      q,
      !1
    ), G > 0) {
      if (G & 16)
        pe(B, ee, re, U, R);
      else if (G & 2 && ee.class !== re.class && i(B, "class", null, re.class, R), G & 4 && i(B, "style", ee.style, re.style, R), G & 8) {
        const ve = k.dynamicProps;
        for (let we = 0; we < ve.length; we++) {
          const ce = ve[we], Ae = ee[ce], Ve = re[ce];
          (Ve !== Ae || ce === "value") && i(B, ce, Ae, Ve, R, U);
        }
      }
      G & 1 && w.children !== k.children && m(B, k.children);
    } else !z && F == null && pe(B, ee, re, U, R);
    ((se = re.onVnodeUpdated) || ae) && je(() => {
      se && ht(se, U, k, w), ae && Bt(k, w, U, "updated");
    }, W);
  }, Z = (w, k, U, W, R, q, z) => {
    for (let B = 0; B < k.length; B++) {
      const G = w[B], F = k[B], ae = G.el || wn(G), ee = (
        // oldVNode may be an errored async setup() component inside Suspense
        // which will not have a mounted element
        ae && // - In the case of a Fragment, we need to provide the actual parent
        // of the Fragment itself so it can move its children.
        (G.type === N || // - In the case of different nodes, there is going to be a replacement
        // which also requires the correct parent container
        !un(G, F) || // - In the case of a component, it could contain anything.
        G.shapeFlag & 198) ? b(ae) : (
          // In other cases, the parent container is not actually used so we
          // just pass the block element here to avoid a DOM parentNode call.
          U
        )
      );
      M(
        G,
        F,
        ee,
        null,
        W,
        R,
        q,
        z,
        !0
      );
    }
  }, pe = (w, k, U, W, R) => {
    if (k !== U) {
      if (k !== Se)
        for (const q in k)
          !vn(q) && !(q in U) && i(
            w,
            q,
            k[q],
            null,
            R,
            W
          );
      for (const q in U) {
        if (vn(q)) continue;
        const z = U[q], B = k[q];
        z !== B && q !== "value" && i(w, q, B, z, R, W);
      }
      "value" in U && i(w, "value", k.value, U.value, R);
    }
  }, be = (w, k, U, W, R, q, z, B, G) => {
    const F = k.el = w ? w.el : u(""), ae = k.anchor = w ? w.anchor : u("");
    let { patchFlag: ee, dynamicChildren: re, slotScopeIds: se } = k;
    se && (B = B ? B.concat(se) : se), w == null ? (o(F, U, W), o(ae, U, W), C(
      // #10007
      // such fragment like `<></>` will be compiled into
      // a fragment which doesn't have a children.
      // In this case fallback to an empty array
      k.children || [],
      U,
      ae,
      R,
      q,
      z,
      B,
      G
    )) : ee > 0 && ee & 64 && re && // #2715 the previous fragment could've been a BAILed one as a result
    // of renderSlot() with no valid children
    w.dynamicChildren && w.dynamicChildren.length === re.length ? (Z(
      w.dynamicChildren,
      re,
      U,
      R,
      q,
      z,
      B
    ), // #2080 if the stable fragment has a key, it's a <template v-for> that may
    //  get moved around. Make sure all root level vnodes inherit el.
    // #2134 or if it's a component root, it may also get moved around
    // as the component is being moved.
    (k.key != null || R && k === R.subTree) && ss(
      w,
      k,
      !0
      /* shallow */
    )) : r(
      w,
      k,
      U,
      ae,
      R,
      q,
      z,
      B,
      G
    );
  }, Ue = (w, k, U, W, R, q, z, B, G) => {
    k.slotScopeIds = B, w == null ? k.shapeFlag & 512 ? R.ctx.activate(
      k,
      U,
      W,
      z,
      G
    ) : Oe(
      k,
      U,
      W,
      R,
      q,
      z,
      G
    ) : le(w, k, G);
  }, Oe = (w, k, U, W, R, q, z) => {
    const B = w.component = or(
      w,
      W,
      R
    );
    if (ts(w) && (B.ctx.renderer = dt), ar(B, !1, z), B.asyncDep) {
      if (R && R.registerDep(
        B,
        P,
        z,
        q
      ), !w.el) {
        const G = B.subTree = Ze(at);
        X(null, G, k, U), w.placeholder = G.el;
      }
    } else
      P(
        B,
        w,
        k,
        U,
        R,
        q,
        z
      );
  }, le = (w, k, U) => {
    const W = k.component = w.component;
    if (qa(w, k, U))
      if (W.asyncDep && !W.asyncResolved) {
        k.el = w.el, k.placeholder = w.placeholder, d(W, k, U);
        return;
      } else
        W.next = k, W.update();
    else
      k.el = w.el, k.placeholder = w.placeholder, W.vnode = k;
  }, P = (w, k, U, W, R, q, z) => {
    const B = () => {
      if (w.isMounted) {
        let { next: ee, bu: re, u: se, parent: ve, vnode: we } = w;
        {
          const Le = Bo(w);
          if (Le) {
            ee && (ee.el = we.el, d(w, ee, z)), Le.asyncDep.then(() => {
              const tt = () => {
                w.job.flags & 8 || (R && R.pendingBranch ? je(tt, R) : F());
              };
              tt.flags = 48, je(tt, R);
            });
            return;
          }
        }
        let ce = ee, Ae;
        Kt(w, !1), ee ? (ee.el = we.el, d(w, ee, z)) : ee = we, re && Wn(re), (Ae = ee.props && ee.props.onVnodeBeforeUpdate) && ht(Ae, ve, ee, we), Kt(w, !0);
        const Ve = Ss(w), Re = w.subTree;
        w.subTree = Ve, M(
          Re,
          Ve,
          // parent may have changed if it's in a teleport. a root that is a
          // pending async component only has its placeholder comment
          b(
            Re.el || wn(Re)
          ),
          // anchor may have changed if it's in a fragment
          ut(Re),
          w,
          R,
          q
        ), ee.el = Ve.el, ce === null && Ha(w, Ve.el), se && je(se, R), (Ae = ee.props && ee.props.onVnodeUpdated) && je(
          () => ht(Ae, ve, ee, we),
          R
        );
      } else {
        let ee;
        const { el: re, props: se } = k, { bm: ve, m: we, parent: ce, root: Ae, type: Ve } = w, Re = tn(k);
        Kt(w, !1), ve && Wn(ve), !Re && (ee = se && se.onVnodeBeforeMount) && ht(ee, ce, k), Kt(w, !0);
        {
          Ae.ce && Ae.ce._hasShadowRoot() && Ae.ce._injectChildStyle(
            Ve,
            w.parent ? w.parent.type : void 0
          );
          const Le = w.subTree = Ss(w);
          M(
            null,
            Le,
            U,
            W,
            w,
            R,
            q
          ), k.el = Le.el;
        }
        if (we && je(we, R), !Re && (ee = se && se.onVnodeMounted)) {
          const Le = k;
          je(
            () => ht(ee, ce, Le),
            R
          );
        }
        (k.shapeFlag & 256 || ce && tn(ce.vnode) && ce.vnode.shapeFlag & 256) && w.a && je(w.a, R), w.isMounted = !0, k = U = W = null;
      }
    };
    w.scope.on();
    const G = w.effect = new eo(B);
    w.scope.off();
    const F = w.update = G.run.bind(G), ae = w.job = G.runIfDirty.bind(G);
    ae.i = w, ae.id = w.uid, G.scheduler = () => es(ae), Kt(w, !0), F();
  }, d = (w, k, U) => {
    k.component = w;
    const W = w.vnode.props;
    w.vnode = k, w.next = null, ja(w, k.props, W, U), Ga(w, k.children, U), $t(), yo(w), Ct();
  }, r = (w, k, U, W, R, q, z, B, G = !1) => {
    const F = w && w.children, ae = w ? w.shapeFlag : 0, ee = k.children, { patchFlag: re, shapeFlag: se } = k;
    if (re > 0) {
      if (re & 128) {
        _(
          F,
          ee,
          U,
          W,
          R,
          q,
          z,
          B,
          G
        );
        return;
      } else if (re & 256) {
        p(
          F,
          ee,
          U,
          W,
          R,
          q,
          z,
          B,
          G
        );
        return;
      }
    }
    se & 8 ? (ae & 16 && St(F, R, q), ee !== F && m(U, ee)) : ae & 16 ? se & 16 ? _(
      F,
      ee,
      U,
      W,
      R,
      q,
      z,
      B,
      G
    ) : St(F, R, q, !0) : (ae & 8 && m(U, ""), se & 16 && C(
      ee,
      U,
      W,
      R,
      q,
      z,
      B,
      G
    ));
  }, p = (w, k, U, W, R, q, z, B, G) => {
    w = w || Jt, k = k || Jt;
    const F = w.length, ae = k.length, ee = Math.min(F, ae);
    let re;
    for (re = 0; re < ee; re++) {
      const se = k[re] = G ? Pt(k[re]) : yt(k[re]);
      M(
        w[re],
        se,
        U,
        null,
        R,
        q,
        z,
        B,
        G
      );
    }
    F > ae ? St(
      w,
      R,
      q,
      !0,
      !1,
      ee
    ) : C(
      k,
      U,
      W,
      R,
      q,
      z,
      B,
      G,
      ee
    );
  }, _ = (w, k, U, W, R, q, z, B, G) => {
    let F = 0;
    const ae = k.length;
    let ee = w.length - 1, re = ae - 1;
    for (; F <= ee && F <= re; ) {
      const se = w[F], ve = k[F] = G ? Pt(k[F]) : yt(k[F]);
      if (un(se, ve))
        M(
          se,
          ve,
          U,
          null,
          R,
          q,
          z,
          B,
          G
        );
      else
        break;
      F++;
    }
    for (; F <= ee && F <= re; ) {
      const se = w[ee], ve = k[re] = G ? Pt(k[re]) : yt(k[re]);
      if (un(se, ve))
        M(
          se,
          ve,
          U,
          null,
          R,
          q,
          z,
          B,
          G
        );
      else
        break;
      ee--, re--;
    }
    if (F > ee) {
      if (F <= re) {
        const se = re + 1, ve = se < ae ? k[se].el : W;
        for (; F <= re; )
          M(
            null,
            k[F] = G ? Pt(k[F]) : yt(k[F]),
            U,
            ve,
            R,
            q,
            z,
            B,
            G
          ), F++;
      }
    } else if (F > re)
      for (; F <= ee; )
        Ce(w[F], R, q, !0), F++;
    else {
      const se = F, ve = F, we = /* @__PURE__ */ new Map();
      for (F = ve; F <= re; F++) {
        const ze = k[F] = G ? Pt(k[F]) : yt(k[F]);
        ze.key != null && we.set(ze.key, F);
      }
      let ce, Ae = 0;
      const Ve = re - ve + 1;
      let Re = !1, Le = 0;
      const tt = new Array(Ve);
      for (F = 0; F < Ve; F++) tt[F] = 0;
      for (F = se; F <= ee; F++) {
        const ze = w[F];
        if (Ae >= Ve) {
          Ce(ze, R, q, !0);
          continue;
        }
        let nt;
        if (ze.key != null)
          nt = we.get(ze.key);
        else
          for (ce = ve; ce <= re; ce++)
            if (tt[ce - ve] === 0 && un(ze, k[ce])) {
              nt = ce;
              break;
            }
        nt === void 0 ? Ce(ze, R, q, !0) : (tt[nt - ve] = F + 1, nt >= Le ? Le = nt : Re = !0, M(
          ze,
          k[nt],
          U,
          null,
          R,
          q,
          z,
          B,
          G
        ), Ae++);
      }
      const an = Re ? Xa(tt) : Jt;
      for (ce = an.length - 1, F = Ve - 1; F >= 0; F--) {
        const ze = ve + F, nt = k[ze], In = k[ze + 1], On = ze + 1 < ae ? (
          // #13559, #14173 fallback to el placeholder for unresolved async component
          In.el || wn(In)
        ) : W;
        tt[F] === 0 ? M(
          null,
          nt,
          U,
          On,
          R,
          q,
          z,
          B,
          G
        ) : Re && (ce < 0 || F !== an[ce] ? K(nt, U, On, 2) : ce--);
      }
    }
  }, K = (w, k, U, W, R = null) => {
    const { el: q, type: z, transition: B, children: G, shapeFlag: F } = w;
    if (F & 6) {
      K(w.component.subTree, k, U, W);
      return;
    }
    if (F & 128) {
      w.suspense.move(k, U, W);
      return;
    }
    if (F & 64) {
      z.move(w, k, U, dt);
      return;
    }
    if (z === N) {
      o(q, k, U);
      for (let ee = 0; ee < G.length; ee++)
        K(G[ee], k, U, W);
      o(w.anchor, k, U);
      return;
    }
    if (z === $l) {
      ne(w, k, U);
      return;
    }
    if (W !== 2 && F & 1 && B)
      if (W === 0)
        B.persisted && !q[wl] ? o(q, k, U) : (B.beforeEnter(q), o(q, k, U), je(() => B.enter(q), R));
      else {
        const { leave: ee, delayLeave: re, afterLeave: se } = B, ve = () => {
          w.ctx.isUnmounted ? s(q) : o(q, k, U);
        }, we = () => {
          const ce = q._isLeaving || !!q[wl];
          q._isLeaving && q[wl](
            !0
            /* cancelled */
          ), B.persisted && !ce ? ve() : ee(q, () => {
            ve(), se && se();
          });
        };
        re ? re(q, ve, we) : we();
      }
    else
      o(q, k, U);
  }, Ce = (w, k, U, W = !1, R = !1) => {
    const {
      type: q,
      props: z,
      ref: B,
      children: G,
      dynamicChildren: F,
      shapeFlag: ae,
      patchFlag: ee,
      dirs: re,
      cacheIndex: se,
      memo: ve
    } = w;
    if ((ee === -2 || F && F.hasOnce) && (R = !1), B != null && ($t(), bn(B, null, U, w, !0), Ct()), se != null && (!w.ctx || w.ctx === k) && (k.renderCache[se] = void 0), ae & 256 && k.ctx.deactivate(w))
      return;
    const we = ae & 1 && re, ce = !tn(w);
    let Ae;
    if (ce && (Ae = z && z.onVnodeBeforeUnmount) && ht(Ae, k, w), ae & 6)
      Xt(w.component, U, W);
    else {
      if (ae & 128) {
        w.suspense.unmount(U, W);
        return;
      }
      we && Bt(w, null, k, "beforeUnmount"), ae & 64 ? w.type.remove(
        w,
        k,
        U,
        dt,
        W
      ) : F && // #5154
      // when v-once is used inside a block, setBlockTracking(-1) marks the
      // parent block with hasOnce: true
      // so that it doesn't take the fast path during unmount - otherwise
      // components nested in v-once are never unmounted.
      !F.hasOnce && // #1153: fast path should not be taken for non-stable (v-for) fragments
      (q !== N || ee > 0 && ee & 64) ? St(
        F,
        k,
        U,
        !1,
        !0
      ) : (q === N && ee & 384 || !R && ae & 16) && St(G, k, U), W && J(w);
    }
    const Ve = ve != null && se == null;
    (ce && (Ae = z && z.onVnodeUnmounted) || we || Ve) && je(() => {
      Ae && ht(Ae, k, w), we && Bt(w, null, k, "unmounted"), Ve && (w.el = null);
    }, U);
  }, J = (w) => {
    const { type: k, el: U, anchor: W, transition: R } = w, q = k === N;
    if (q && !R) {
      ye(U, W);
      return;
    }
    if (k === $l) {
      O(w), R && !R.persisted && R.afterLeave && R.afterLeave();
      return;
    }
    const z = q ? Ml(w) : w, B = () => {
      q ? b(U) && ye(U, W) : s(U), R && !R.persisted && R.afterLeave && R.afterLeave();
    };
    if (z && z.shapeFlag & 1 && R && !R.persisted) {
      const { leave: G, delayLeave: F } = R, ae = z.el, ee = () => G(ae, B);
      F ? F(ae, B, ee) : ee();
    } else
      B();
  }, ye = (w, k) => {
    let U;
    for (; w !== k; )
      U = S(w), s(w), w = U;
    s(k);
  }, Xt = (w, k, U) => {
    const { bum: W, scope: R, job: q, subTree: z, um: B, m: G, a: F } = w;
    Ps(G), Ps(F), W && Wn(W), R.stop(), q ? (q.flags |= 8, Ce(z, w, k, U)) : z && (z.transition = w.vnode.transition, Ce(z, w, k, U)), B && je(B, k);
    const ae = () => {
      w.isUnmounted = !0;
    };
    ae.flags = 16, je(ae, k);
  }, St = (w, k, U, W = !1, R = !1, q = 0) => {
    for (let z = q; z < w.length; z++)
      Ce(w[z], k, U, W, R);
  }, ut = (w) => {
    if (w.shapeFlag & 6)
      return ut(w.component.subTree);
    if (w.shapeFlag & 128)
      return w.suspense.next();
    const k = S(w.anchor || w.el), U = k && k[xo];
    return U ? S(U) : k;
  }, He = (w, k, U) => {
    const W = w && k._vnode ? void 0 : w && w.component ? w.component.uid : sr();
    oa(() => {
      w == null ? k._vnode && Ce(k._vnode, null, null, !0) : M(
        k._vnode || null,
        w,
        k,
        null,
        null,
        null,
        U
      ), k._vnode = w;
    }, W);
  }, dt = {
    p: M,
    um: Ce,
    m: K,
    r: J,
    mt: Oe,
    mc: C,
    pc: r,
    pbc: Z,
    n: ut,
    o: e
  };
  return {
    render: He,
    hydrate: void 0,
    createApp: Oa(He)
  };
}
function kl({ type: e, props: t }, n) {
  return n === "svg" && e === "foreignObject" || n === "mathml" && e === "annotation-xml" && t && t.encoding && t.encoding.includes("html") ? void 0 : n;
}
function Kt({ effect: e, job: t }, n) {
  n ? (e.flags |= 32, t.flags |= 4) : (e.flags &= -33, t.flags &= -5);
}
function Ya(e, t) {
  return (!e || e && !e.pendingBranch) && t && !t.persisted;
}
function ss(e, t, n = !1) {
  const o = e.children, s = t.children;
  if (de(o) && de(s))
    for (let i = 0; i < o.length; i++) {
      const a = o[i];
      let u = s[i];
      u.shapeFlag & 1 && !u.dynamicChildren && ((u.patchFlag <= 0 || u.patchFlag === 32) && (u = s[i] = Pt(s[i]), u.el = a.el), !n && u.patchFlag !== -2 && ss(a, u)), u.type === dl && (u.patchFlag === -1 && (u = s[i] = Pt(u)), u.el = a.el), u.type === at && !u.el && (u.el = a.el);
    }
}
function Xa(e) {
  const t = e.slice(), n = [0];
  let o, s, i, a, u;
  const c = e.length;
  for (o = 0; o < c; o++) {
    const g = e[o];
    if (g !== 0) {
      if (s = n[n.length - 1], e[s] < g) {
        t[o] = s, n.push(o);
        continue;
      }
      for (i = 0, a = n.length - 1; i < a; )
        u = i + a >> 1, e[n[u]] < g ? i = u + 1 : a = u;
      g < e[n[i]] && (i > 0 && (t[o] = n[i - 1]), n[i] = o);
    }
  }
  for (i = n.length, a = n[i - 1]; i-- > 0; )
    n[i] = a, a = t[a];
  return n;
}
function Bo(e) {
  const t = e.subTree.component;
  if (t)
    return t.asyncDep && !t.asyncResolved ? t : Bo(t);
}
function Ps(e) {
  if (e)
    for (let t = 0; t < e.length; t++)
      e[t].flags |= 8;
}
function wn(e) {
  if (e.placeholder)
    return e.placeholder;
  const t = e.component;
  if (t)
    return wn(t.subTree);
  const n = e.suspense;
  return n && n.activeBranch ? wn(n.activeBranch) : null;
}
const Ko = (e) => e.__isSuspense, Za = /* @__PURE__ */ Symbol("_deferredEnter");
function Qa(e, t) {
  t && t.pendingBranch ? de(e) ? t.effects.push(...e) : t.effects.push(e) : sa(e);
}
const N = /* @__PURE__ */ Symbol.for("v-fgt"), dl = /* @__PURE__ */ Symbol.for("v-txt"), at = /* @__PURE__ */ Symbol.for("v-cmt"), $l = /* @__PURE__ */ Symbol.for("v-stc"), Vt = [];
let et = null;
function f(e = !1) {
  Vt.push(et = e ? null : []);
}
function os() {
  Vt.pop(), et = Vt[Vt.length - 1] || null;
}
let Sn = 1;
function As(e, t = !1) {
  Sn += e, e < 0 && et && t && (et.hasOnce = !0);
}
function Go(e) {
  return e.dynamicChildren = Sn > 0 ? et || Jt : null, os(), Sn > 0 && et && et.push(e), e;
}
function h(e, t, n, o, s, i) {
  return Go(
    l(
      e,
      t,
      n,
      o,
      s,
      i,
      !0
    )
  );
}
function ge(e, t, n, o, s) {
  return Go(
    Ze(
      e,
      t,
      n,
      o,
      s,
      !0
    )
  );
}
function cl(e) {
  return e ? e.__v_isVNode === !0 : !1;
}
function un(e, t) {
  return e.type === t.type && e.key === t.key;
}
const zo = ({ key: e }) => e ?? null, Kn = ({
  ref: e,
  ref_key: t,
  ref_for: n
}) => (typeof e == "number" && (e = "" + e), e != null ? Pe(e) || /* @__PURE__ */ Ge(e) || fe(e) ? { i: Ke, r: e, k: t, f: !!n } : e : null);
function l(e, t = null, n = null, o = 0, s = null, i = e === N ? 0 : 1, a = !1, u = !1) {
  const c = {
    __v_isVNode: !0,
    __v_skip: !0,
    type: e,
    props: t,
    key: t && zo(t),
    ref: t && Kn(t),
    scopeId: ko,
    slotScopeIds: null,
    children: n,
    component: null,
    suspense: null,
    ssContent: null,
    ssFallback: null,
    dirs: null,
    transition: null,
    el: null,
    anchor: null,
    target: null,
    targetStart: null,
    targetAnchor: null,
    staticCount: 0,
    shapeFlag: i,
    patchFlag: o,
    dynamicProps: s,
    dynamicChildren: null,
    appContext: null,
    ctx: Ke
  };
  return u ? (Zn(c, n), i & 128 && e.normalize(c)) : n && (c.shapeFlag |= Pe(n) ? 8 : 16), Sn > 0 && // avoid a block node from tracking itself
  !a && // has current parent block
  et && // presence of a patch flag indicates this node needs patching on updates.
  // component nodes also should always be patched, because even if the
  // component doesn't need to update, it needs to persist the instance on to
  // the next vnode so that it can be properly unmounted later.
  (c.patchFlag > 0 || i & 6) && // the EVENTS flag is only for hydration and if it is the only flag, the
  // vnode should not be considered dynamic due to handler caching.
  c.patchFlag !== 32 && et.push(c), c;
}
const Ze = er;
function er(e, t = null, n = null, o = 0, s = null, i = !1) {
  if ((!e || e === xa) && (e = at), cl(e)) {
    const u = ln(
      e,
      t,
      !0
      /* mergeRef: true */
    );
    return n && Zn(u, n), Sn > 0 && !i && et && (u.shapeFlag & 6 ? et[et.indexOf(e)] = u : et.push(u)), u.patchFlag = -2, u;
  }
  if (cr(e) && (e = e.__vccOpts), t) {
    t = tr(t);
    let { class: u, style: c } = t;
    u && !Pe(u) && (t.class = Ee(u)), $e(c) && (/* @__PURE__ */ Zl(c) && !de(c) && (c = Ie({}, c)), t.style = _n(c));
  }
  const a = Pe(e) ? 1 : Ko(e) ? 128 : rl(e) ? 64 : $e(e) ? 4 : fe(e) ? 2 : 0;
  return l(
    e,
    t,
    n,
    o,
    s,
    a,
    i,
    !0
  );
}
function tr(e) {
  return e ? /* @__PURE__ */ Zl(e) ? Ie({}, e) : Fo(e) ? Ie({}, e[Zo] || e) : e : null;
}
function ln(e, t, n = !1, o = !1) {
  const { props: s, ref: i, patchFlag: a, children: u, transition: c } = e, g = t ? nr(s || {}, t) : s, m = {
    __v_isVNode: !0,
    __v_skip: !0,
    type: e.type,
    props: g,
    key: g && zo(g),
    ref: t && t.ref ? (
      // #2078 in the case of <component :is="vnode" ref="extra"/>
      // if the vnode itself already has a ref, cloneVNode will need to merge
      // the refs so the single vnode can be set on multiple refs
      n && i ? de(i) ? i.concat(Kn(t)) : [i, Kn(t)] : Kn(t)
    ) : i,
    scopeId: e.scopeId,
    slotScopeIds: e.slotScopeIds,
    children: u,
    target: e.target,
    targetStart: e.targetStart,
    targetAnchor: e.targetAnchor,
    staticCount: e.staticCount,
    shapeFlag: e.shapeFlag,
    // if the vnode is cloned with extra props, we can no longer assume its
    // existing patch flag to be reliable and need to add the FULL_PROPS flag.
    // note: preserve flag for fragments since they use the flag for children
    // fast paths only.
    patchFlag: t && e.type !== N ? a === -1 ? 16 : a | 16 : a,
    dynamicProps: e.dynamicProps,
    dynamicChildren: e.dynamicChildren,
    appContext: e.appContext,
    dirs: e.dirs,
    transition: c,
    // These should technically only be non-null on mounted VNodes. However,
    // they *should* be copied for kept-alive vnodes. So we just always copy
    // them since them being non-null during a mount doesn't affect the logic as
    // they will simply be overwritten.
    component: e.component,
    suspense: e.suspense,
    ssContent: e.ssContent && ln(e.ssContent),
    ssFallback: e.ssFallback && ln(e.ssFallback),
    placeholder: e.placeholder,
    el: e.el,
    anchor: e.anchor,
    ctx: e.ctx,
    ce: e.ce,
    cacheIndex: e.cacheIndex
  };
  return c && o && mn(
    m,
    c.clone(m)
  ), m;
}
function I(e = " ", t = 0) {
  return Ze(dl, null, e, t);
}
function T(e = "", t = !1) {
  return t ? (f(), ge(at, null, e)) : Ze(at, null, e);
}
function yt(e) {
  return e == null || typeof e == "boolean" ? Ze(at) : de(e) ? Ze(
    N,
    null,
    // #3666, avoid reference pollution when reusing vnode
    e.slice()
  ) : cl(e) ? Pt(e) : Ze(dl, null, String(e));
}
function Pt(e) {
  return e.el === null && e.patchFlag !== -1 || e.memo ? e : ln(e);
}
function Zn(e, t) {
  let n = 0;
  const { shapeFlag: o } = e;
  if (t == null)
    t = null;
  else if (de(t))
    n = 16;
  else if (typeof t == "object")
    if (o & 65) {
      const s = t.default;
      s && (s._c && (s._d = !1), Zn(e, s()), s._c && (s._d = !0));
      return;
    } else {
      n = 32;
      const s = t._;
      !s && !Fo(t) ? t._ctx = Ke : s === 3 && Ke && (Ke.slots._ === 1 ? t._ = 1 : (t._ = 2, e.patchFlag |= 1024));
    }
  else if (fe(t)) {
    if (o & 65) {
      Zn(e, { default: t });
      return;
    }
    t = { default: t, _ctx: Ke }, n = 32;
  } else
    t = String(t), o & 64 ? (n = 16, t = [I(t)]) : n = 8;
  e.children = t, e.shapeFlag |= n;
}
function nr(...e) {
  const t = {};
  for (let n = 0; n < e.length; n++) {
    const o = e[n];
    for (const s in o)
      if (s === "class")
        t.class !== o.class && (t.class = Ee([t.class, o.class]));
      else if (s === "style")
        t.style = _n([t.style, o.style]);
      else if (nl(s)) {
        const i = t[s], a = o[s];
        a && i !== a && !(de(i) && i.includes(a)) ? t[s] = i ? [].concat(i, a) : a : a == null && i == null && // mergeProps({ 'onUpdate:modelValue': undefined }) should not retain
        // the model listener.
        !ll(s) && (t[s] = a);
      } else s !== "" && (t[s] = o[s]);
  }
  return t;
}
function ht(e, t, n, o = null) {
  gt(e, t, 7, [
    n,
    o
  ]);
}
const lr = /* @__PURE__ */ Io();
let Jo = 0;
function sr() {
  return Jo;
}
function or(e, t, n) {
  const o = e.type, s = (t ? t.appContext : e.appContext) || lr, i = {
    uid: Jo++,
    vnode: e,
    type: o,
    parent: t,
    appContext: s,
    root: null,
    // to be immediately set
    next: null,
    subTree: null,
    // will be set synchronously right after creation
    effect: null,
    update: null,
    // will be set synchronously right after creation
    job: null,
    scope: new Ei(
      !0
      /* detached */
    ),
    render: null,
    proxy: null,
    exposed: null,
    exposeProxy: null,
    withProxy: null,
    provides: t ? t.provides : Object.create(s.provides),
    ids: t ? t.ids : ["", 0, 0],
    accessCache: null,
    renderCache: [],
    // local resolved assets
    components: null,
    directives: null,
    // resolved props and emits options
    propsOptions: Ho(o, s),
    emitsOptions: Oo(o, s),
    // emit
    emit: null,
    // to be set immediately
    emitted: null,
    // props default value
    propsDefaults: Se,
    // inheritAttrs
    inheritAttrs: o.inheritAttrs,
    // state
    ctx: Se,
    data: Se,
    props: Se,
    attrs: Se,
    slots: Se,
    refs: Se,
    setupState: Se,
    setupContext: null,
    // suspense related
    suspense: n,
    suspenseId: n ? n.pendingId : 0,
    asyncDep: null,
    asyncResolved: !1,
    // lifecycle hooks
    // not using enums here because it results in computed properties
    isMounted: !1,
    isUnmounted: !1,
    isDeactivated: !1,
    bc: null,
    c: null,
    bm: null,
    m: null,
    bu: null,
    u: null,
    um: null,
    bum: null,
    da: null,
    a: null,
    rtg: null,
    rtc: null,
    ec: null,
    sp: null
  };
  return i.ctx = { _: i }, i.root = t ? t.root : i, i.emit = Ra.bind(null, i), e.ce && e.ce(i), i;
}
let Xe = null;
const ir = () => Xe || Ke;
let Qn, Tn;
{
  const e = ol(), t = (n, o) => {
    let s;
    return (s = e[n]) || (s = e[n] = []), s.push(o), (i) => {
      s.length > 1 ? s.forEach((a) => a(i)) : s[0](i);
    };
  };
  Qn = t(
    "__VUE_INSTANCE_SETTERS__",
    (n) => Xe = n
  ), Tn = t(
    "__VUE_SSR_SETTERS__",
    (n) => En = n
  );
}
const Vn = (e) => {
  const t = Xe;
  return Qn(e), e.scope.on(), () => {
    e.scope.off(), Qn(t);
  };
}, Us = () => {
  Xe && Xe.scope.off(), Qn(null);
};
function Yo(e) {
  return e.vnode.shapeFlag & 4;
}
let En = !1;
function ar(e, t = !1, n = !1) {
  t && Tn(t);
  const { props: o, children: s } = e.vnode, i = Yo(e);
  La(e, o, i, t), Ka(e, s, n || t);
  const a = i ? rr(e, t) : void 0;
  return t && Tn(!1), a;
}
function rr(e, t) {
  const n = e.type;
  e.accessCache = /* @__PURE__ */ Object.create(null), e.proxy = new Proxy(e.ctx, Ta);
  const { setup: o } = n;
  if (o) {
    $t();
    const s = e.setupContext = o.length > 1 ? dr(e) : null, i = Vn(e), a = Un(
      o,
      e,
      0,
      [
        e.props,
        s
      ]
    ), u = Ks(a);
    if (Ct(), i(), (u || e.sp) && !tn(e) && To(e), u) {
      if (a.then(Us, Us), t)
        return a.then((c) => {
          Tn(!0);
          try {
            Vs(e, c, t);
          } finally {
            Tn(!1);
          }
        }).catch((c) => {
          al(c, e, 0, void 0, !0), e.ssrRender = (g, m) => m("<!---->");
        });
      e.asyncDep = a;
    } else
      Vs(e, a);
  } else
    Xo(e);
}
function Vs(e, t, n) {
  fe(t) ? e.type.__ssrInlineRender ? e.ssrRender = t : e.render = t : $e(t) && (e.setupState = ho(t)), Xo(e);
}
function Xo(e, t, n) {
  const o = e.type;
  e.render || (e.render = o.render || kt);
  {
    const s = Vn(e);
    $t();
    try {
      Ea(e);
    } finally {
      Ct(), s();
    }
  }
}
const Zo = /* @__PURE__ */ Symbol(), ur = {
  get(e, t) {
    return We(e, "get", ""), t === Zo ? e : e[t];
  }
};
function dr(e) {
  const t = (n) => {
    e.exposed = n || {};
  };
  return {
    attrs: new Proxy(e.attrs, ur),
    slots: e.slots,
    emit: e.emit,
    expose: t
  };
}
function fl(e) {
  return e.exposed ? e.exposeProxy || (e.exposeProxy = new Proxy(ho(Gi(e.exposed)), {
    get(t, n) {
      if (n in t)
        return t[n];
      if (n in yn)
        return yn[n](e);
    },
    has(t, n) {
      return n in t || n in yn;
    }
  })) : e.proxy;
}
function cr(e) {
  return fe(e) && "__vccOpts" in e;
}
const ke = (e, t) => /* @__PURE__ */ Qi(e, t, En), fr = "3.5.46";
let ql;
const Is = typeof window < "u" && window.trustedTypes;
if (Is)
  try {
    ql = /* @__PURE__ */ Is.createPolicy("vue", {
      createHTML: (e) => e
    });
  } catch {
  }
const Qo = ql ? (e) => ql.createHTML(e) : (e) => e, pr = "http://www.w3.org/2000/svg", vr = "http://www.w3.org/1998/Math/MathML", Et = typeof document < "u" ? document : null, Os = Et && /* @__PURE__ */ Et.createElement("template"), gr = {
  insert: (e, t, n) => {
    t.insertBefore(e, n || null);
  },
  remove: (e) => {
    const t = e.parentNode;
    t && t.removeChild(e);
  },
  createElement: (e, t, n, o) => {
    const s = t === "svg" ? Et.createElementNS(pr, e) : t === "mathml" ? Et.createElementNS(vr, e) : n ? Et.createElement(e, { is: n }) : Et.createElement(e);
    return e === "select" && o && o.multiple != null && s.setAttribute("multiple", o.multiple), s;
  },
  createText: (e) => Et.createTextNode(e),
  createComment: (e) => Et.createComment(e),
  setText: (e, t) => {
    e.nodeValue = t;
  },
  setElementText: (e, t) => {
    e.textContent = t;
  },
  parentNode: (e) => e.parentNode,
  nextSibling: (e) => e.nextSibling,
  querySelector: (e) => Et.querySelector(e),
  setScopeId(e, t) {
    e.setAttribute(t, "");
  },
  // __UNSAFE__
  // Reason: innerHTML.
  // Static content here can only come from compiled templates.
  // As long as the user only uses trusted templates, this is safe.
  insertStaticContent(e, t, n, o, s, i) {
    const a = n ? n.previousSibling : t.lastChild;
    if (s && (s === i || s.nextSibling))
      for (; t.insertBefore(s.cloneNode(!0), n), !(s === i || !(s = s.nextSibling)); )
        ;
    else {
      Os.innerHTML = Qo(
        o === "svg" ? `<svg>${e}</svg>` : o === "mathml" ? `<math>${e}</math>` : e
      );
      const u = Os.content;
      if (o === "svg" || o === "mathml") {
        const c = u.firstChild;
        for (; c.firstChild; )
          u.appendChild(c.firstChild);
        u.removeChild(c);
      }
      t.insertBefore(u, n);
    }
    return [
      // first
      a ? a.nextSibling : t.firstChild,
      // last
      n ? n.previousSibling : t.lastChild
    ];
  }
}, hr = /* @__PURE__ */ Symbol("_vtc");
function mr(e, t, n) {
  const o = e[hr];
  o && (t = (t ? [t, ...o] : [...o]).join(" ")), t == null ? e.removeAttribute("class") : n ? e.setAttribute("class", t) : e.className = t;
}
const el = /* @__PURE__ */ Symbol("_vod"), ei = /* @__PURE__ */ Symbol("_vsh"), qn = {
  // used for prop mismatch check during hydration
  name: "show",
  beforeMount(e, { value: t }, { transition: n }) {
    e[el] = e.style.display === "none" ? "" : e.style.display, n && t ? n.beforeEnter(e) : dn(e, t);
  },
  mounted(e, { value: t }, { transition: n }) {
    n && t && n.enter(e);
  },
  updated(e, { value: t, oldValue: n }, { transition: o }) {
    !t != !n && (o ? t ? (o.beforeEnter(e), dn(e, !0), o.enter(e)) : o.leave(e, () => {
      dn(e, !1);
    }) : dn(e, t));
  },
  beforeUnmount(e, { value: t }) {
    dn(e, t);
  }
};
function dn(e, t) {
  e.style.display = t ? e[el] : "none", e[ei] = !t;
}
const br = /* @__PURE__ */ Symbol(""), yr = /(?:^|;)\s*display\s*:/;
function wr(e, t, n) {
  const o = e.style, s = Pe(n);
  let i = !1;
  if (n && !s) {
    if (t)
      if (Pe(t))
        for (const a of t.split(";")) {
          const u = a.slice(0, a.indexOf(":")).trim();
          n[u] == null && pn(o, u, "");
        }
      else
        for (const a in t)
          n[a] == null && pn(o, a, "");
    for (const a in n) {
      a === "display" && (i = !0);
      const u = n[a];
      u != null ? kr(
        e,
        a,
        !Pe(t) && t ? t[a] : void 0,
        u
      ) || pn(o, a, u) : pn(o, a, "");
    }
  } else if (s) {
    if (t !== n) {
      const a = o[br];
      a && (n += ";" + a), o.cssText = n, i = yr.test(n);
    }
  } else t && e.removeAttribute("style");
  el in e && ((!s || t !== n) && (e[el] = i ? o.display : ""), e[ei] && (o.display = "none"));
}
const Hn = /\s*!important$/;
function pn(e, t, n) {
  if (de(n))
    n.forEach((o) => pn(e, t, o));
  else if (n == null && (n = ""), t.startsWith("--"))
    Hn.test(n) ? e.setProperty(t, n.replace(Hn, ""), "important") : e.setProperty(t, n);
  else {
    const o = _r(e, t);
    Hn.test(n) ? e.setProperty(
      jt(o),
      n.replace(Hn, ""),
      "important"
    ) : e[o] = n;
  }
}
const Ms = ["Webkit", "Moz", "ms"], Cl = {};
function _r(e, t) {
  const n = Cl[t];
  if (n)
    return n;
  let o = ft(t);
  if (o !== "filter" && o in e)
    return Cl[t] = o;
  o = Js(o);
  for (let s = 0; s < Ms.length; s++) {
    const i = Ms[s] + o;
    if (i in e)
      return Cl[t] = i;
  }
  return t;
}
function kr(e, t, n, o) {
  return e.tagName === "TEXTAREA" && (t === "width" || t === "height") && Pe(o) && n === o;
}
const Rs = "http://www.w3.org/1999/xlink";
function Ds(e, t, n, o, s, i = xi(t)) {
  o && t.startsWith("xlink:") ? n == null ? e.removeAttributeNS(Rs, t.slice(6, t.length)) : e.setAttributeNS(Rs, t, n) : n == null || i && !Xs(n) ? e.removeAttribute(t) : e.setAttribute(
    t,
    i ? "" : vt(n) ? String(n) : n
  );
}
function Ns(e, t, n, o, s) {
  if (t === "innerHTML" || t === "textContent") {
    n != null && (e[t] = t === "innerHTML" ? Qo(n) : n);
    return;
  }
  const i = e.tagName;
  if (t === "value" && i !== "PROGRESS" && // custom elements may use _value internally
  !i.includes("-")) {
    const u = i === "OPTION" ? e.getAttribute("value") || "" : e.value, c = n == null ? (
      // #11647: value should be set as empty string for null and undefined,
      // but <input type="checkbox"> should be set as 'on'.
      e.type === "checkbox" ? "on" : ""
    ) : String(n);
    (u !== c || !("_value" in e)) && (e.value = c), n == null && e.removeAttribute(t), e._value = n;
    return;
  }
  let a = !1;
  if (n === "" || n == null) {
    const u = typeof e[t];
    u === "boolean" ? n = Xs(n) : n == null && u === "string" ? (n = "", a = !0) : u === "number" && (n = 0, a = !0);
  }
  try {
    e[t] = n;
  } catch {
  }
  a && e.removeAttribute(s || t);
}
function Ft(e, t, n, o) {
  e.addEventListener(t, n, o);
}
function $r(e, t, n, o) {
  e.removeEventListener(t, n, o);
}
const Fs = /* @__PURE__ */ Symbol("_vei");
function Cr(e, t, n, o, s = null) {
  const i = e[Fs] || (e[Fs] = {}), a = i[t];
  if (o && a)
    a.value = o;
  else {
    const [u, c] = Tr(t);
    if (o) {
      const g = i[t] = Ar(
        o,
        s
      );
      Ft(e, u, g, c);
    } else a && ($r(e, u, a, c), i[t] = void 0);
  }
}
const xr = /(Once|Passive|Capture)$/, Sr = /^on:?(?:Once|Passive|Capture)$/;
function Tr(e) {
  let t, n;
  for (; (n = e.match(xr)) && !Sr.test(e); )
    t || (t = {}), e = e.slice(0, e.length - n[1].length), t[n[1].toLowerCase()] = !0;
  return [e[2] === ":" ? e.slice(3) : jt(e.slice(2)), t];
}
let xl = 0;
const Er = /* @__PURE__ */ Promise.resolve(), Pr = () => xl || (Er.then(() => xl = 0), xl = Date.now());
function Ar(e, t) {
  const n = (o) => {
    if (!o._vts)
      o._vts = Date.now();
    else if (o._vts <= n.attached)
      return;
    const s = n.value;
    if (de(s)) {
      const i = o.stopImmediatePropagation;
      o.stopImmediatePropagation = () => {
        i.call(o), o._stopped = !0;
      };
      const a = s.slice(), u = [o];
      for (let c = 0; c < a.length && !o._stopped; c++) {
        const g = a[c];
        g && gt(
          g,
          t,
          5,
          u
        );
      }
    } else
      gt(
        s,
        t,
        5,
        [o]
      );
  };
  return n.value = e, n.attached = Pr(), n;
}
const qs = (e) => e.charCodeAt(0) === 111 && e.charCodeAt(1) === 110 && // lowercase letter
e.charCodeAt(2) > 96 && e.charCodeAt(2) < 123, Ur = (e, t, n, o, s, i) => {
  const a = s === "svg";
  t === "class" ? mr(e, o, a) : t === "style" ? wr(e, n, o) : nl(t) ? ll(t) || Cr(e, t, n, o, i) : (t[0] === "." ? (t = t.slice(1), !0) : t[0] === "^" ? (t = t.slice(1), !1) : Vr(e, t, o, a)) ? (Ns(e, t, o), !e.tagName.includes("-") && (t === "value" || t === "checked" || t === "selected") && Ds(e, t, o, a, i, t !== "value")) : /* #11081 force set props for possible async custom element */ e._isVueCE && // #12408 check if it's declared prop or it's async custom element
  (Ir(e, t) || // @ts-expect-error _def is private
  e._def.__asyncLoader && (/[A-Z]/.test(t) || !Pe(o))) ? Ns(e, ft(t), o, i, t) : (t === "true-value" ? e._trueValue = o : t === "false-value" && (e._falseValue = o), Ds(e, t, o, a));
};
function Vr(e, t, n, o) {
  if (o)
    return !!(t === "innerHTML" || t === "textContent" || t in e && qs(t) && fe(n));
  if (t === "spellcheck" || t === "draggable" || t === "translate" || t === "autocorrect" || t === "sandbox" && e.tagName === "IFRAME" || t === "form" || t === "list" && e.tagName === "INPUT" || t === "type" && e.tagName === "TEXTAREA")
    return !1;
  if (t === "width" || t === "height") {
    const s = e.tagName;
    if (s === "IMG" || s === "VIDEO" || s === "CANVAS" || s === "SOURCE")
      return !1;
  }
  return qs(t) && Pe(n) ? !1 : t in e;
}
function Ir(e, t) {
  const n = (
    // @ts-expect-error _def is private
    e._def.props
  );
  if (!n)
    return !1;
  const o = ft(t);
  return Array.isArray(n) ? n.some((s) => ft(s) === o) : Object.keys(n).some((s) => ft(s) === o);
}
const sn = (e) => {
  const t = e.props["onUpdate:modelValue"] || !1;
  return de(t) ? (n) => Wn(t, n) : t;
};
function Or(e) {
  e.target.composing = !0;
}
function Hs(e) {
  const t = e.target;
  t.composing && (t.composing = !1, t.dispatchEvent(new Event("input")));
}
const _t = /* @__PURE__ */ Symbol("_assign"), Ln = /* @__PURE__ */ Symbol("_initialValue");
function Sl(e, t, n) {
  return t && (e = e.trim()), n && (e = An(e)), e;
}
const oe = {
  created(e, { modifiers: { lazy: t, trim: n, number: o } }, s) {
    e.parentNode && (e.type === "text" ? e[Ln] = e.defaultValue.replace(/[\r\n]/g, "") : e.type === "textarea" && (e[Ln] = e.defaultValue.replace(/\r\n?/g, `
`))), e[_t] = sn(s);
    const i = o || s.props && s.props.type === "number";
    Ft(e, t ? "change" : "input", (a) => {
      a.target.composing || e[_t](Sl(e.value, n, i));
    }), (n || i) && Ft(e, "change", () => {
      e.value = Sl(e.value, n, i);
    }), t || (Ft(e, "compositionstart", Or), Ft(e, "compositionend", Hs), Ft(e, "change", Hs));
  },
  // set value on mounted so it's after min/max for type="range"
  mounted(e, { value: t, modifiers: { trim: n, number: o } }) {
    const s = t ?? "", i = e[Ln];
    delete e[Ln], i !== void 0 && (e.type === "text" || e.type === "textarea") && e.value !== i ? e[_t](Sl(e.value, n, o)) : e.value = s;
  },
  beforeUpdate(e, { value: t, oldValue: n, modifiers: { lazy: o, trim: s, number: i } }, a) {
    if (e[_t] = sn(a), e.composing) return;
    const u = (i || e.type === "number") && !/^0\d/.test(e.value) ? An(e.value) : e.value, c = t ?? "";
    if (u === c)
      return;
    const g = e.getRootNode();
    (g instanceof Document || g instanceof ShadowRoot) && g.activeElement === e && e.type !== "range" && (o && t === n || s && e.value.trim() === c) || (e.value = c);
  }
}, Be = {
  // #4096 array checkboxes need to be deep traversed
  deep: !0,
  created(e, t, n) {
    e[_t] = sn(n), Ft(e, "change", () => {
      const o = e._modelValue, s = Pn(e), i = e.checked, a = e[_t];
      if (de(o)) {
        const u = Wl(o, s), c = u !== -1;
        if (i && !c)
          a(o.concat(s));
        else if (!i && c) {
          const g = [...o];
          g.splice(u, 1), a(g);
        }
      } else if (It(o)) {
        const u = new Set(o);
        i ? u.add(s) : u.delete(s), a(u);
      } else
        a(ti(e, i));
    });
  },
  // set initial checked on mount to wait for true-value/false-value
  mounted: Ls,
  beforeUpdate(e, t, n) {
    e[_t] = sn(n), Ls(e, t, n);
  }
};
function Ls(e, { value: t, oldValue: n }, o) {
  e._modelValue = t;
  let s;
  if (de(t))
    s = Wl(t, o.props.value) > -1;
  else if (It(t))
    s = t.has(o.props.value);
  else {
    if (t === n) return;
    s = Ot(t, ti(e, !0));
  }
  e.checked !== s && (e.checked = s);
}
const xe = {
  // <select multiple> value need to be deep traversed
  deep: !0,
  created(e, { value: t, modifiers: { number: n } }, o) {
    e._modelValue = t, Ft(e, "change", () => {
      const s = Array.prototype.filter.call(e.options, (c) => c.selected).map(
        (c) => n ? An(Pn(c)) : Pn(c)
      ), i = e.multiple, a = i ? It(e._modelValue) ? new Set(s) : s : s[0], u = e._pendingValue = [
        i,
        i ? de(a) ? s.slice() : s : a
      ];
      try {
        e[_t](a);
      } finally {
        Ql(() => {
          e._pendingValue === u && (e._pendingValue = void 0);
        });
      }
    }), e[_t] = sn(o);
  },
  // set value in mounted & updated because <select> relies on its children
  // <option>s.
  mounted(e, { value: t, modifiers: { number: n } }) {
    js(e, t, n);
  },
  beforeUpdate(e, { value: t }, n) {
    e._modelValue = t, e[_t] = sn(n);
  },
  updated(e, { value: t, modifiers: { number: n } }) {
    const o = e._pendingValue;
    e._pendingValue = void 0, (!o || o[0] !== e.multiple || !Mr(t, o[1], o[0])) && js(e, t, n);
  }
};
function Mr(e, t, n) {
  if (!n || de(e)) return Ot(e, t);
  if (It(e)) {
    if (e.size !== t.length) return !1;
    for (const o of t)
      if (!e.has(o)) return !1;
    return !0;
  }
  return !1;
}
function js(e, t, n = !1) {
  const o = e.multiple, s = de(t);
  if (!(o && !s && !It(t))) {
    for (let i = 0, a = e.options.length; i < a; i++) {
      const u = e.options[i], c = Pn(u);
      if (o)
        if (s) {
          const g = typeof c;
          g === "string" || g === "number" ? u.selected = t.some((m) => String(m) === String(c)) : u.selected = Wl(t, c) > -1;
        } else
          u.selected = t.has(c) || n && typeof c == "string" && t.has(An(c));
      else if (Ot(Pn(u), t)) {
        e.selectedIndex !== i && (e.selectedIndex = i);
        return;
      }
    }
    !o && e.selectedIndex !== -1 && (e.selectedIndex = -1);
  }
}
function Pn(e) {
  return "_value" in e ? e._value : e.value;
}
function ti(e, t) {
  const n = t ? "_trueValue" : "_falseValue";
  return n in e ? e[n] : t;
}
const Rr = ["ctrl", "shift", "alt", "meta"], Dr = {
  stop: (e) => e.stopPropagation(),
  prevent: (e) => e.preventDefault(),
  self: (e) => e.target !== e.currentTarget,
  ctrl: (e) => !e.ctrlKey,
  shift: (e) => !e.shiftKey,
  alt: (e) => !e.altKey,
  meta: (e) => !e.metaKey,
  left: (e) => "button" in e && e.button !== 0,
  middle: (e) => "button" in e && e.button !== 1,
  right: (e) => "button" in e && e.button !== 2,
  exact: (e, t) => Rr.some((n) => e[`${n}Key`] && !t.includes(n))
}, lt = (e, t) => {
  if (!e) return e;
  const n = e._withMods || (e._withMods = {}), o = t.join(".");
  return n[o] || (n[o] = ((s, ...i) => {
    for (let a = 0; a < t.length; a++) {
      const u = Dr[t[a]];
      if (u && u(s, t)) return;
    }
    return e(s, ...i);
  }));
}, Nr = {
  esc: "escape",
  space: " ",
  up: "arrow-up",
  left: "arrow-left",
  right: "arrow-right",
  down: "arrow-down",
  delete: "backspace"
}, tl = (e, t) => {
  const n = e._withKeys || (e._withKeys = {}), o = t.join(".");
  return n[o] || (n[o] = ((s) => {
    if (!("key" in s))
      return;
    const i = jt(s.key);
    if (t.some(
      (a) => a === i || Nr[a] === i
    ))
      return e(s);
  }));
}, Fr = /* @__PURE__ */ Ie({ patchProp: Ur }, gr);
let Ws;
function qr() {
  return Ws || (Ws = za(Fr));
}
const Hr = ((...e) => {
  const t = qr().createApp(...e), { mount: n } = t;
  return t.mount = (o) => {
    const s = jr(o);
    if (!s) return;
    const i = t._component;
    !fe(i) && !i.render && !i.template && (i.template = s.innerHTML), s.nodeType === 1 && (s.textContent = "");
    const a = n(s, !1, Lr(s));
    return s instanceof Element && (s.removeAttribute("v-cloak"), s.setAttribute("data-v-app", "")), a;
  }, t;
});
function Lr(e) {
  if (e instanceof SVGElement)
    return "svg";
  if (typeof MathMLElement == "function" && e instanceof MathMLElement)
    return "mathml";
}
function jr(e) {
  return Pe(e) ? document.querySelector(e) : e;
}
const Wr = [
  {
    id: "3x-ui",
    name: "3x-ui",
    author: "MHSanaei",
    repository: "MHSanaei/3x-ui",
    description: "Панель Xray для управления VPN-подключениями, пользователями, лимитами и статистикой."
  },
  {
    id: "podkop",
    name: "Podkop",
    author: "itdoginfo",
    repository: "itdoginfo/podkop",
    description: "Выборочная маршрутизация сайтов и приложений через прокси на OpenWrt (sing-box)."
  },
  {
    id: "ssclash",
    name: "SSClash-Go",
    author: "zerolabnet",
    repository: "zerolabnet/SSClash-Go",
    description: "Панель Mihomo / Clash для управления прокси и правилами маршрутизации на OpenWrt."
  },
  {
    id: "adguardhome",
    name: "AdGuard Home",
    author: "AdGuardTeam",
    repository: "AdguardTeam/AdGuardHome",
    description: "DNS-фильтр для всей сети: блокировка рекламы, трекеров и нежелательных доменов."
  }
], Br = ["title"], Kr = { class: "gw-project-links" }, Gr = ["aria-label", "href"], zr = ["href", "title"], is = /* @__PURE__ */ qe({
  __name: "ProjectInfo",
  props: {
    id: {},
    compact: { type: Boolean },
    help: { type: Boolean }
  },
  emits: ["help"],
  setup(e, { emit: t }) {
    const n = e, o = t, s = ke(() => Wr.find((a) => a.id === n.id)), i = ke(() => s.value?.repository.split("/")[0]);
    return (a, u) => s.value ? (f(), h("div", {
      key: 0,
      class: Ee(["gw-project-info", { compact: e.compact }])
    }, [
      l("p", {
        title: s.value.description
      }, y(s.value.description), 9, Br),
      l("div", Kr, [
        l("a", {
          "aria-label": "Автор проекта: " + s.value.author,
          href: "https://github.com/" + i.value,
          target: "_blank",
          rel: "noopener noreferrer"
        }, y(s.value.author), 9, Gr),
        u[1] || (u[1] = l("span", { "aria-hidden": "true" }, "·", -1)),
        l("a", {
          href: "https://github.com/" + s.value.repository,
          title: s.value.repository,
          target: "_blank",
          rel: "noopener noreferrer"
        }, "GitHub ↗", 8, zr),
        e.help ? (f(), h("button", {
          key: 0,
          type: "button",
          onClick: u[0] || (u[0] = (c) => o("help"))
        }, "Помощь")) : T("", !0)
      ])
    ], 2)) : T("", !0);
  }
}), Jr = { class: "gw-shell gw-dialog-overlay" }, Yr = ["aria-label"], Xr = { class: "gw-dialog-header" }, Zr = ["disabled"], Fe = /* @__PURE__ */ qe({
  __name: "GatewayDialog",
  props: {
    title: {},
    busy: { type: Boolean },
    wide: { type: Boolean },
    compact: { type: Boolean }
  },
  emits: ["close"],
  setup(e, { emit: t }) {
    const n = e, o = t, s = /* @__PURE__ */ H();
    let i = null;
    function a() {
      n.busy || o("close");
    }
    function u(c) {
      if (c.key === "Escape" && (c.preventDefault(), c.stopImmediatePropagation(), a()), c.key !== "Tab" || !s.value) return;
      const g = [...s.value.querySelectorAll('button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea:not(:disabled),a[href],summary,[tabindex="0"]')].filter((S) => S.getClientRects().length), m = g[0], b = g[g.length - 1];
      if (!m) {
        c.preventDefault(), s.value.focus();
        return;
      }
      c.shiftKey && (document.activeElement === m || document.activeElement === s.value) ? (c.preventDefault(), b.focus()) : !c.shiftKey && (document.activeElement === b || !s.value.contains(document.activeElement)) && (c.preventDefault(), m.focus());
    }
    return rt(async () => {
      i = document.activeElement, document.addEventListener("keydown", u, !0), await Ql(), s.value?.focus();
    }), Rt(() => {
      document.removeEventListener("keydown", u, !0), i?.isConnected && i.focus();
    }), (c, g) => (f(), ge(pa, { to: "body" }, [
      l("div", Jr, [
        l("section", {
          ref_key: "dialog",
          ref: s,
          class: Ee(["gw-panel gw-dialog", { "gw-dialog-wide": e.wide, "gw-dialog-compact": e.compact }]),
          role: "dialog",
          "aria-modal": "true",
          "aria-label": e.title,
          tabindex: "-1"
        }, [
          l("header", Xr, [
            l("h2", null, y(e.title), 1),
            l("button", {
              type: "button",
              "aria-label": "Закрыть диалог",
              disabled: e.busy,
              onClick: a
            }, "×", 8, Zr)
          ]),
          Sa(c.$slots, "default")
        ], 10, Yr)
      ])
    ]));
  }
}), Qr = {
  key: 0,
  class: "gw-error"
}, eu = { key: 1 }, tu = { class: "gw-notice" }, nu = {
  key: 0,
  class: "gw-error"
}, lu = { class: "gw-setup-steps" }, su = {
  key: 1,
  class: "gw-notice"
}, ou = { class: "gw-actions" }, iu = ["disabled"], au = ["href"], ru = { class: "gw-hint" }, uu = ["href"], du = /* @__PURE__ */ qe({
  __name: "AdGuardSetup",
  props: {
    node: {},
    bridge: {}
  },
  emits: ["close", "install", "start"],
  setup(e, { emit: t }) {
    const n = e, o = t, s = /* @__PURE__ */ H(null), i = /* @__PURE__ */ H(""), a = (u) => "http://" + (n.node.host.includes(":") ? "[" + n.node.host + "]" : n.node.host) + ":" + u + "/";
    return rt(async () => {
      try {
        s.value = await n.bridge.request("/api/gateways/" + encodeURIComponent(n.node.id) + "/adguard");
      } catch (u) {
        i.value = u.message;
      }
    }), (u, c) => (f(), ge(Fe, {
      title: "AdGuard Home: установка и настройка DNS",
      wide: !0,
      onClose: c[2] || (c[2] = (g) => o("close"))
    }, {
      default: Me(() => [
        Ze(is, { id: "adguardhome" }),
        i.value ? (f(), h("p", Qr, y(i.value), 1)) : T("", !0),
        !s.value && !i.value ? (f(), h("p", eu, "Проверяем роутер…")) : T("", !0),
        s.value ? (f(), h(N, { key: 2 }, [
          l("div", tu, [
            l("strong", null, y(s.value.installed ? "AdGuard Home установлен" : "Установка из официального GitHub-релиза"), 1),
            l("p", null, "Свободное место: " + y(s.value.free_bytes == null ? "Не определено" : (s.value.free_bytes / 1048576).toFixed(0) + " МБ") + ". Бинарный файл и журнал запросов требуют места; для небольшого flash рекомендуется внешнее хранилище.", 1),
            l("p", null, "Занятые порты: " + y(s.value.occupied_ports.filter((g) => [53, 54, 80, 443, 3e3, 5353, 8080].includes(g.port)).map((g) => g.port + "/" + g.protocol).join(", ") || "Не обнаружены") + ".", 1)
          ]),
          s.value.setup_port_busy && !s.value.configured ? (f(), h("p", nu, "Порт 3000 занят. Перед первым запуском освободите его через консоль или настройки службы.")) : T("", !0),
          l("ol", lu, [
            (f(!0), h(N, null, ie(s.value.steps, (g, m) => (f(), h("li", { key: m }, y(g), 1))), 128))
          ]),
          s.value.dns_dependencies.length ? (f(), h("p", su, "Найдены зависимости DNS: " + y(s.value.dns_dependencies.join("; ")) + ". До их изменения остановка и удаление сервиса запрещены.", 1)) : T("", !0),
          l("div", ou, [
            s.value.installed ? e.node.monitor.services?.some((g) => g.id === "adguardhome" && g.running) ? T("", !0) : (f(), h("button", {
              key: 1,
              disabled: s.value.setup_port_busy && !s.value.configured,
              class: "gw-primary",
              onClick: c[1] || (c[1] = (g) => o("start"))
            }, "Запустить сервис", 8, iu)) : (f(), h("button", {
              key: 0,
              class: "gw-primary",
              onClick: c[0] || (c[0] = (g) => o("install"))
            }, "Выбрать версию и установить")),
            s.value.installed ? (f(), h("a", {
              key: 2,
              href: a(s.value.web_port),
              target: "_blank",
              rel: "noopener noreferrer"
            }, y(s.value.configured ? "Открыть AdGuard Home" : "Открыть мастер на порту 3000") + " ↗", 9, au)) : T("", !0)
          ]),
          l("p", ru, [
            c[3] || (c[3] = I("Официальные инструкции: ", -1)),
            (f(!0), h(N, null, ie(s.value.sources, (g) => (f(), h("a", {
              key: g.url,
              href: g.url,
              target: "_blank",
              rel: "noopener noreferrer"
            }, y(g.name) + " ↗ ", 9, uu))), 128))
          ])
        ], 64)) : T("", !0)
      ]),
      _: 1
    }));
  }
}), cu = {
  key: 0,
  class: "gw-error",
  role: "alert"
}, fu = { class: "gw-change-list" }, pu = {
  key: 0,
  class: "gw-notice"
}, vu = { class: "gw-notice" }, gu = { class: "gw-actions" }, hu = ["disabled"], mu = ["disabled"], bu = { class: "gw-check" }, yu = {
  key: 0,
  class: "gw-notice"
}, wu = { class: "gw-two" }, _u = ["disabled"], ku = ["disabled"], $u = { key: 0 }, Cu = ["value"], xu = ["value"], Su = {
  key: 1,
  class: "gw-notice"
}, Tu = { class: "gw-two" }, Eu = { class: "gw-check" }, Pu = { class: "gw-two" }, Au = { class: "gw-check" }, Uu = { class: "gw-check" }, Vu = { class: "gw-check" }, Iu = {
  key: 0,
  class: "gw-notice"
}, Ou = {
  class: "gw-tabs",
  "aria-label": "Разделы firewall"
}, Mu = { class: "gw-policy-grid" }, Ru = ["onUpdate:modelValue"], Du = { class: "gw-policy-grid" }, Nu = ["onUpdate:modelValue"], Fu = { class: "gw-two" }, qu = ["onUpdate:modelValue"], Hu = ["onUpdate:modelValue"], Lu = ["open", "onInput", "onChange"], ju = { class: "gw-rule-fields" }, Wu = ["onClick"], Bu = {
  key: 0,
  class: "gw-hint"
}, Ku = ["onUpdate:modelValue"], Gu = { class: "gw-two" }, zu = ["onUpdate:modelValue"], Ju = ["value"], Yu = ["onUpdate:modelValue"], Xu = ["value"], Zu = { class: "gw-two" }, Qu = ["onUpdate:modelValue"], ed = ["value"], td = ["onUpdate:modelValue"], nd = { class: "gw-two" }, ld = ["onUpdate:modelValue"], sd = ["onUpdate:modelValue"], od = {
  key: 0,
  class: "gw-hint"
}, id = { class: "gw-section-header" }, ad = ["disabled"], rd = {
  key: 0,
  class: "gw-notice"
}, ud = {
  key: 1,
  class: "gw-hint"
}, dd = ["open", "onInput", "onChange"], cd = { class: "gw-rule-fields" }, fd = ["onClick"], pd = ["onUpdate:modelValue"], vd = { class: "gw-two" }, gd = ["onUpdate:modelValue"], hd = ["value"], md = ["onUpdate:modelValue"], bd = ["value"], yd = { class: "gw-two" }, wd = ["onUpdate:modelValue"], _d = ["onUpdate:modelValue"], kd = { class: "gw-two" }, $d = ["onUpdate:modelValue"], Cd = ["onUpdate:modelValue"], xd = ["onUpdate:modelValue"], Sd = { class: "gw-two" }, Td = ["onUpdate:modelValue"], Ed = ["onUpdate:modelValue"], Pd = {
  key: 2,
  class: "gw-hint"
}, Ad = { class: "gw-actions" }, Ud = ["disabled"], Vd = ["disabled"], Id = { key: 3 }, ni = /* @__PURE__ */ qe({
  __name: "RouterSettings",
  props: {
    node: {},
    bridge: {},
    mode: {},
    iface: {}
  },
  emits: ["close", "changed"],
  setup(e, { emit: t }) {
    const n = e, o = t, s = /* @__PURE__ */ H(null), i = /* @__PURE__ */ H({}), a = /* @__PURE__ */ H(null), u = /* @__PURE__ */ H(!1), c = /* @__PURE__ */ H(""), g = /* @__PURE__ */ H("general"), m = /* @__PURE__ */ H([]), b = /* @__PURE__ */ H(/* @__PURE__ */ new Set()), S = /* @__PURE__ */ H([]), A = /* @__PURE__ */ H(/* @__PURE__ */ new Set()), Y = ["id", "name", "src", "dest", "src_ip", "dest_ip", "proto", "src_dport", "dest_port", "enabled", "reflection"], M = { dhcp: "DHCP-сервер", dns: "DNS роутера", firewall: "Настройки firewall" }, te = (P) => String(P || "").split(/[\s,]+/).filter(Boolean), X = (P) => Array.isArray(P) ? P.join(", ") : P || "", Q = () => "/api/gateways/" + encodeURIComponent(n.node.id), ne = (P, d, r = "POST") => n.bridge.request(Q() + P, { method: r, headers: { "Content-Type": "application/json" }, body: JSON.stringify(d) });
    function O(P) {
      const d = s.value.dns.find((r) => r.id === P) || {};
      i.value = { ...d, port: d.port ?? "53", server: X(d.server), cachesize: d.cachesize ?? "150", domain: d.domain || "", local: d.local || "", noresolv: d.noresolv === "1", rebind_protection: d.rebind_protection !== "0", domainneeded: d.domainneeded === "1", boguspriv: d.boguspriv !== "0" };
    }
    async function L() {
      u.value = !0;
      try {
        if (s.value = await n.bridge.request(Q() + "/network"), n.mode === "dns") O(s.value.dns[0]?.id);
        else if (n.mode === "dhcp") {
          const P = s.value.dhcp.find((d) => d.interface === n.iface);
          i.value = { ignore: !P || P.ignore === "1", start: P?.start ?? "100", limit: P?.limit ?? "150", leasetime: P?.leasetime || "12h", dns: X(P?.dns) };
        } else {
          const P = s.value.firewall;
          i.value = { redirectsSupported: Array.isArray(P.redirects), redirects: (P.redirects || []).filter((d) => !d.target || d.target === "DNAT").map((d) => ({ ...d })), defaults: { input: "REJECT", output: "ACCEPT", forward: "REJECT", ...P.defaults }, zones: P.zones.map((d) => ({ ...d })), rules: P.rules.map((d) => ({ ...d, editable: !d.target || ["ACCEPT", "REJECT", "DROP"].includes(d.target) })) };
        }
      } catch (P) {
        c.value = P.message;
      } finally {
        u.value = !1;
      }
    }
    function V(P) {
      const d = i.value.rules[P];
      d.id && m.value.push(d.id), i.value.rules.splice(P, 1);
    }
    function E(P) {
      P.id && b.value.add(P.id);
    }
    function C() {
      g.value = "rules", i.value.rules.push({ name: "", src: "lan", dest: "", proto: "tcp", dest_port: "", target: "ACCEPT", enabled: "1", editable: !0 });
    }
    function j() {
      g.value = "redirects", i.value.redirects.push({ name: "", src: "wan", dest: "lan", proto: ["tcp", "udp"], src_dport: "", dest_ip: "", dest_port: "", enabled: "1", reflection: "1" });
    }
    function Z(P) {
      const d = i.value.redirects[P];
      d.id && S.value.push(d.id), i.value.redirects.splice(P, 1);
    }
    function pe(P) {
      P.id && A.value.add(P.id);
    }
    function be(P, d) {
      const r = {};
      for (const p of d) P[p] !== void 0 && (r[p] = P[p] === "" ? null : P[p]);
      return r;
    }
    async function Ue(P = n.mode) {
      u.value = !0, c.value = "";
      try {
        const d = { config_hash: s.value.settings_hash }, r = i.value;
        P === "dhcp" && Object.assign(d, { interface: n.iface, settings: { ignore: r.ignore ? "1" : "0", start: String(r.start), limit: String(r.limit), leasetime: r.leasetime, dns: te(r.dns) } }), P === "dns" && Object.assign(d, { section: r.id, settings: { port: String(r.port), server: te(r.server), cachesize: String(r.cachesize), domain: r.domain || null, local: r.local || null, noresolv: r.noresolv ? "1" : "0", rebind_protection: r.rebind_protection ? "1" : "0", domainneeded: r.domainneeded ? "1" : "0", boguspriv: r.boguspriv ? "1" : "0" } }), P === "firewall" && Object.assign(d, { settings: be(r.defaults, ["input", "output", "forward", "synflood_protect"]), zones: r.zones.map((p) => be(p, ["id", "input", "output", "forward", "masq", "mtu_fix"])), rules: r.rules.filter((p) => !p.id || b.value.has(p.id)).map((p) => be(p, ["id", "name", "src", "dest", "src_ip", "dest_ip", "proto", "dest_port", "target", "enabled"])), deleted_rules: m.value }), P === "firewall" && r.redirectsSupported && Object.assign(d, { redirects: r.redirects.filter((p) => !p.id || A.value.has(p.id)).map((p) => be(p, Y)), deleted_redirects: S.value }), a.value = await ne("/network/plan", { action: P, data: d });
      } catch (d) {
        c.value = d.message;
      } finally {
        u.value = !1;
      }
    }
    async function Oe() {
      u.value = !0;
      try {
        const P = a.value, d = await ne("/router-operations", { plan_token: P.plan_token, confirmed: !0 });
        a.value = null, o("close"), n.bridge.task({ taskId: d.task_id, title: P.title, cancellable: !1, onDone: async () => o("changed") });
      } catch (P) {
        c.value = P.message;
      } finally {
        u.value = !1;
      }
    }
    function le() {
      const P = a.value?.plan_token;
      a.value = null, c.value = "", P && ne("/operation-plans/" + encodeURIComponent(P), {}, "DELETE").catch((d) => {
        c.value = d.message;
      });
    }
    return rt(() => {
      L();
    }), (P, d) => (f(), ge(Fe, {
      title: a.value ? "Проверка изменений" : M[e.mode] + (e.iface ? " · " + e.iface : ""),
      wide: !0,
      busy: u.value,
      onClose: d[21] || (d[21] = (r) => a.value ? le() : o("close"))
    }, {
      default: Me(() => [
        c.value ? (f(), h("p", cu, y(c.value), 1)) : T("", !0),
        a.value ? (f(), h(N, { key: 1 }, [
          l("ul", fu, [
            (f(!0), h(N, null, ie(a.value.summary, (r, p) => (f(), h("li", { key: p }, y(r), 1))), 128))
          ]),
          a.value.warnings?.length ? (f(), h("section", pu, [
            d[22] || (d[22] = l("h3", null, "Последствия изменений", -1)),
            l("ul", null, [
              (f(!0), h(N, null, ie(a.value.warnings, (r, p) => (f(), h("li", { key: p }, y(r), 1))), 128))
            ])
          ])) : T("", !0),
          l("p", vu, "Если панель не подтвердит результат в течение " + y(a.value.rollback_seconds) + " секунд, роутер вернёт прежнюю конфигурацию. Изменения, сделанные параллельно в LuCI, не будут перезаписаны.", 1),
          l("div", gu, [
            l("button", {
              class: "gw-primary",
              disabled: u.value,
              onClick: Oe
            }, "Да, применить", 8, hu),
            l("button", {
              disabled: u.value,
              onClick: le
            }, "Назад", 8, mu)
          ])
        ], 64)) : s.value ? (f(), h("form", {
          key: 2,
          class: "gw-form",
          onSubmit: d[20] || (d[20] = lt((r) => Ue(), ["prevent"]))
        }, [
          e.mode === "dhcp" ? (f(), h(N, { key: 0 }, [
            l("label", bu, [
              D(l("input", {
                "onUpdate:modelValue": d[0] || (d[0] = (r) => i.value.ignore = r),
                type: "checkbox"
              }, null, 512), [
                [Be, i.value.ignore]
              ]),
              I(" Выключить DHCP-сервер на " + y(e.iface), 1)
            ]),
            i.value.ignore ? T("", !0) : (f(), h("p", yu, "В одном сегменте должен работать один DHCP-сервер. При наличии основного роутера оставьте DHCP здесь выключенным.")),
            l("div", wu, [
              l("label", null, [
                d[23] || (d[23] = I("Начальный адрес (смещение в подсети)", -1)),
                D(l("input", {
                  "onUpdate:modelValue": d[1] || (d[1] = (r) => i.value.start = r),
                  type: "number",
                  min: "0",
                  disabled: i.value.ignore,
                  required: ""
                }, null, 8, _u), [
                  [oe, i.value.start]
                ])
              ]),
              l("label", null, [
                d[24] || (d[24] = I("Количество адресов", -1)),
                D(l("input", {
                  "onUpdate:modelValue": d[2] || (d[2] = (r) => i.value.limit = r),
                  type: "number",
                  min: "1",
                  disabled: i.value.ignore,
                  required: ""
                }, null, 8, ku), [
                  [oe, i.value.limit]
                ])
              ])
            ]),
            l("label", null, [
              d[25] || (d[25] = I("Время аренды", -1)),
              D(l("input", {
                "onUpdate:modelValue": d[3] || (d[3] = (r) => i.value.leasetime = r),
                placeholder: "12h"
              }, null, 512), [
                [oe, i.value.leasetime]
              ])
            ]),
            l("label", null, [
              d[26] || (d[26] = I("DNS для DHCP-клиентов (IPv4)", -1)),
              D(l("input", {
                "onUpdate:modelValue": d[4] || (d[4] = (r) => i.value.dns = r),
                placeholder: "Пусто — адрес роутера"
              }, null, 512), [
                [oe, i.value.dns]
              ]),
              d[27] || (d[27] = l("small", null, "Меняется только DHCP option 6. Другие опции, статические аренды и настройки IPv6 сохраняются. Клиенты получат изменение при обновлении аренды.", -1))
            ])
          ], 64)) : T("", !0),
          e.mode === "dns" ? (f(), h(N, { key: 1 }, [
            d[40] || (d[40] = l("p", { class: "gw-hint" }, "DNS подключения WAN задаётся в его настройках. Здесь — локальный DNS-сервис dnsmasq и серверы, на которые он отправляет запросы.", -1)),
            s.value.dns.length > 1 ? (f(), h("label", $u, [
              d[28] || (d[28] = I("Экземпляр dnsmasq", -1)),
              l("select", {
                value: i.value.id,
                onChange: d[5] || (d[5] = (r) => O(r.target.value))
              }, [
                (f(!0), h(N, null, ie(s.value.dns, (r) => (f(), h("option", {
                  key: r.id,
                  value: r.id
                }, y(r.id), 9, xu))), 128))
              ], 40, Cu)
            ])) : T("", !0),
            s.value.dns.length ? (f(), h(N, { key: 2 }, [
              l("div", Tu, [
                l("label", null, [
                  d[29] || (d[29] = I("Порт DNS", -1)),
                  D(l("input", {
                    "onUpdate:modelValue": d[6] || (d[6] = (r) => i.value.port = r),
                    type: "number",
                    min: "0",
                    max: "65535",
                    required: ""
                  }, null, 512), [
                    [oe, i.value.port]
                  ]),
                  d[30] || (d[30] = l("small", null, "53 — обычный DNS; 0 отключает только DNS.", -1))
                ]),
                l("label", null, [
                  d[31] || (d[31] = I("Размер кэша", -1)),
                  D(l("input", {
                    "onUpdate:modelValue": d[7] || (d[7] = (r) => i.value.cachesize = r),
                    type: "number",
                    min: "0",
                    required: ""
                  }, null, 512), [
                    [oe, i.value.cachesize]
                  ])
                ])
              ]),
              l("label", null, [
                d[32] || (d[32] = I("Внешние DNS-серверы", -1)),
                D(l("textarea", {
                  "onUpdate:modelValue": d[8] || (d[8] = (r) => i.value.server = r),
                  rows: "3",
                  placeholder: `1.1.1.1
127.0.0.1#5353
/example.org/192.168.1.2`
                }, null, 512), [
                  [oe, i.value.server]
                ]),
                d[33] || (d[33] = l("small", null, "По одному серверу на строку; адрес#порт, /домен/адрес#порт.", -1))
              ]),
              l("label", Eu, [
                D(l("input", {
                  "onUpdate:modelValue": d[9] || (d[9] = (r) => i.value.noresolv = r),
                  type: "checkbox"
                }, null, 512), [
                  [Be, i.value.noresolv]
                ]),
                d[34] || (d[34] = I(" Использовать только указанные upstream (не получать DNS от WAN)", -1))
              ]),
              l("div", Pu, [
                l("label", null, [
                  d[35] || (d[35] = I("Локальный домен", -1)),
                  D(l("input", {
                    "onUpdate:modelValue": d[10] || (d[10] = (r) => i.value.domain = r),
                    placeholder: "lan"
                  }, null, 512), [
                    [oe, i.value.domain]
                  ])
                ]),
                l("label", null, [
                  d[36] || (d[36] = I("Локальная зона", -1)),
                  D(l("input", {
                    "onUpdate:modelValue": d[11] || (d[11] = (r) => i.value.local = r),
                    placeholder: "/lan/"
                  }, null, 512), [
                    [oe, i.value.local]
                  ])
                ])
              ]),
              l("label", Au, [
                D(l("input", {
                  "onUpdate:modelValue": d[12] || (d[12] = (r) => i.value.rebind_protection = r),
                  type: "checkbox"
                }, null, 512), [
                  [Be, i.value.rebind_protection]
                ]),
                d[37] || (d[37] = I(" Защита DNS rebinding", -1))
              ]),
              l("label", Uu, [
                D(l("input", {
                  "onUpdate:modelValue": d[13] || (d[13] = (r) => i.value.domainneeded = r),
                  type: "checkbox"
                }, null, 512), [
                  [Be, i.value.domainneeded]
                ]),
                d[38] || (d[38] = I(" Не отправлять имена без домена", -1))
              ]),
              l("label", Vu, [
                D(l("input", {
                  "onUpdate:modelValue": d[14] || (d[14] = (r) => i.value.boguspriv = r),
                  type: "checkbox"
                }, null, 512), [
                  [Be, i.value.boguspriv]
                ]),
                d[39] || (d[39] = I(" Не отправлять обратные запросы частных адресов", -1))
              ]),
              i.value.nftset || i.value.ipset ? (f(), h("p", Iu, "dnsmasq использует наборы для маршрутизации. При переходе на AdGuard Home сохраните путь запросов через dnsmasq для нужных доменов.")) : T("", !0)
            ], 64)) : (f(), h("p", Su, "dnsmasq не настроен. Сначала установите или настройте его в LuCI."))
          ], 64)) : T("", !0),
          e.mode === "firewall" ? (f(), h(N, { key: 2 }, [
            d[85] || (d[85] = l("p", { class: "gw-hint" }, "Основные политики, зоны, правила трафика и перенаправления портов. Расширенные параметры и специальные правила NAT сохраняются.", -1)),
            l("nav", Ou, [
              l("button", {
                type: "button",
                class: Ee({ on: g.value === "general" }),
                onClick: d[15] || (d[15] = (r) => g.value = "general")
              }, "Общие настройки", 2),
              l("button", {
                type: "button",
                class: Ee({ on: g.value === "zones" }),
                onClick: d[16] || (d[16] = (r) => g.value = "zones")
              }, "Зоны (" + y(i.value.zones.length) + ")", 3),
              l("button", {
                type: "button",
                class: Ee({ on: g.value === "rules" }),
                onClick: d[17] || (d[17] = (r) => g.value = "rules")
              }, "Правила трафика (" + y(i.value.rules.length) + ")", 3),
              l("button", {
                type: "button",
                class: Ee({ on: g.value === "redirects" }),
                onClick: d[18] || (d[18] = (r) => g.value = "redirects")
              }, "Перенаправление портов (" + y(i.value.redirects.length) + ")", 3)
            ]),
            D(l("section", null, [
              d[42] || (d[42] = l("h3", null, "Политики по умолчанию", -1)),
              d[43] || (d[43] = l("p", { class: "gw-hint" }, "Применяются к трафику, для которого не задано отдельное правило.", -1)),
              l("div", Mu, [
                (f(), h(N, null, ie(["input", "output", "forward"], (r) => l("label", { key: r }, [
                  I(y({ input: "Входящие", output: "Исходящие", forward: "Пересылка" }[r]), 1),
                  D(l("select", {
                    "onUpdate:modelValue": (p) => i.value.defaults[r] = p
                  }, [...d[41] || (d[41] = [
                    l("option", null, "ACCEPT", -1),
                    l("option", null, "REJECT", -1),
                    l("option", null, "DROP", -1)
                  ])], 8, Ru), [
                    [xe, i.value.defaults[r]]
                  ])
                ])), 64))
              ])
            ], 512), [
              [qn, g.value === "general"]
            ]),
            D(l("section", null, [
              d[49] || (d[49] = l("h3", null, "Зоны", -1)),
              d[50] || (d[50] = l("p", { class: "gw-hint" }, "Политики для групп сетевых интерфейсов. Правила отдельных соединений находятся на вкладке «Правила трафика».", -1)),
              (f(!0), h(N, null, ie(i.value.zones, (r) => (f(), h("article", {
                key: r.id,
                class: "gw-settings-row"
              }, [
                l("h4", null, y(r.name) + " · " + y(X(r.network)), 1),
                l("div", Du, [
                  (f(), h(N, null, ie(["input", "output", "forward"], (p) => l("label", { key: p }, [
                    I(y({ input: "Входящие", output: "Исходящие", forward: "Пересылка" }[p]), 1),
                    D(l("select", {
                      "onUpdate:modelValue": (_) => r[p] = _
                    }, [...d[44] || (d[44] = [
                      l("option", null, "ACCEPT", -1),
                      l("option", null, "REJECT", -1),
                      l("option", null, "DROP", -1)
                    ])], 8, Nu), [
                      [xe, r[p]]
                    ])
                  ])), 64))
                ]),
                l("div", Fu, [
                  l("label", null, [
                    d[46] || (d[46] = I("NAT (маскарадинг)", -1)),
                    D(l("select", {
                      "onUpdate:modelValue": (p) => r.masq = p
                    }, [...d[45] || (d[45] = [
                      l("option", { value: void 0 }, "По умолчанию", -1),
                      l("option", { value: "1" }, "Включён", -1),
                      l("option", { value: "0" }, "Выключен", -1)
                    ])], 8, qu), [
                      [xe, r.masq]
                    ])
                  ]),
                  l("label", null, [
                    d[48] || (d[48] = I("Коррекция MSS", -1)),
                    D(l("select", {
                      "onUpdate:modelValue": (p) => r.mtu_fix = p
                    }, [...d[47] || (d[47] = [
                      l("option", { value: void 0 }, "По умолчанию", -1),
                      l("option", { value: "1" }, "Включён", -1),
                      l("option", { value: "0" }, "Выключен", -1)
                    ])], 8, Hu), [
                      [xe, r.mtu_fix]
                    ])
                  ])
                ])
              ]))), 128))
            ], 512), [
              [qn, g.value === "zones"]
            ]),
            D(l("section", null, [
              l("header", { class: "gw-section-header" }, [
                d[51] || (d[51] = l("h3", null, "Правила трафика", -1)),
                l("button", {
                  type: "button",
                  onClick: C
                }, "Добавить правило")
              ]),
              (f(!0), h(N, null, ie(i.value.rules, (r, p) => (f(), h("details", {
                key: r.id || p,
                open: !r.id,
                class: "gw-settings-rule",
                onInput: (_) => E(r),
                onChange: (_) => E(r)
              }, [
                l("summary", null, [
                  l("strong", null, y(r.name || r.id || "Новое правило"), 1),
                  l("span", null, y(r.src || "Роутер") + " → " + y(r.dest || "Роутер") + " · " + y(X(r.proto) || "all") + " " + y(r.dest_port || "") + " · " + y(r.target || "ACCEPT"), 1),
                  l("small", null, y(r.enabled === "0" ? "Выключено" : "Включено"), 1)
                ]),
                l("div", ju, [
                  l("button", {
                    type: "button",
                    class: "gw-danger",
                    onClick: (_) => V(Number(p))
                  }, "Удалить правило", 8, Wu),
                  r.editable ? (f(), h(N, { key: 1 }, [
                    l("label", null, [
                      d[52] || (d[52] = I("Название", -1)),
                      D(l("input", {
                        "onUpdate:modelValue": (_) => r.name = _
                      }, null, 8, Ku), [
                        [oe, r.name]
                      ])
                    ]),
                    l("div", Gu, [
                      l("label", null, [
                        d[55] || (d[55] = I("Исходная зона", -1)),
                        D(l("select", {
                          "onUpdate:modelValue": (_) => r.src = _
                        }, [
                          d[53] || (d[53] = l("option", { value: "" }, "Сам роутер", -1)),
                          d[54] || (d[54] = l("option", { value: "*" }, "Любая", -1)),
                          (f(!0), h(N, null, ie(i.value.zones, (_) => (f(), h("option", {
                            key: _.id,
                            value: _.name
                          }, y(_.name), 9, Ju))), 128))
                        ], 8, zu), [
                          [xe, r.src]
                        ])
                      ]),
                      l("label", null, [
                        d[58] || (d[58] = I("Зона назначения", -1)),
                        D(l("select", {
                          "onUpdate:modelValue": (_) => r.dest = _
                        }, [
                          d[56] || (d[56] = l("option", { value: "" }, "Сам роутер", -1)),
                          d[57] || (d[57] = l("option", { value: "*" }, "Любая", -1)),
                          (f(!0), h(N, null, ie(i.value.zones, (_) => (f(), h("option", {
                            key: _.id,
                            value: _.name
                          }, y(_.name), 9, Xu))), 128))
                        ], 8, Yu), [
                          [xe, r.dest]
                        ])
                      ])
                    ]),
                    l("div", Zu, [
                      l("label", null, [
                        d[64] || (d[64] = I("Протокол", -1)),
                        D(l("select", {
                          "onUpdate:modelValue": (_) => r.proto = _
                        }, [
                          Array.isArray(r.proto) ? (f(), h("option", {
                            key: 0,
                            value: r.proto
                          }, y(X(r.proto)), 9, ed)) : T("", !0),
                          d[59] || (d[59] = l("option", null, "tcp", -1)),
                          d[60] || (d[60] = l("option", null, "udp", -1)),
                          d[61] || (d[61] = l("option", null, "icmp", -1)),
                          d[62] || (d[62] = l("option", null, "icmpv6", -1)),
                          d[63] || (d[63] = l("option", null, "all", -1))
                        ], 8, Qu), [
                          [xe, r.proto]
                        ])
                      ]),
                      l("label", null, [
                        d[65] || (d[65] = I("Порт назначения", -1)),
                        D(l("input", {
                          "onUpdate:modelValue": (_) => r.dest_port = _,
                          placeholder: "443 или 1000-2000"
                        }, null, 8, td), [
                          [oe, r.dest_port]
                        ])
                      ])
                    ]),
                    l("div", nd, [
                      l("label", null, [
                        d[67] || (d[67] = I("Действие", -1)),
                        D(l("select", {
                          "onUpdate:modelValue": (_) => r.target = _
                        }, [...d[66] || (d[66] = [
                          l("option", null, "ACCEPT", -1),
                          l("option", null, "REJECT", -1),
                          l("option", null, "DROP", -1)
                        ])], 8, ld), [
                          [xe, r.target]
                        ])
                      ]),
                      l("label", null, [
                        d[69] || (d[69] = I("Состояние", -1)),
                        D(l("select", {
                          "onUpdate:modelValue": (_) => r.enabled = _
                        }, [...d[68] || (d[68] = [
                          l("option", { value: void 0 }, "Включено по умолчанию", -1),
                          l("option", { value: "1" }, "Включено", -1),
                          l("option", { value: "0" }, "Выключено", -1)
                        ])], 8, sd), [
                          [xe, r.enabled]
                        ])
                      ])
                    ])
                  ], 64)) : (f(), h("p", Bu, y(r.target) + " · Расширенное правило. Редактирование доступно в LuCI.", 1))
                ])
              ], 40, Lu))), 128)),
              i.value.rules.length ? T("", !0) : (f(), h("p", od, "Правила трафика не настроены."))
            ], 512), [
              [qn, g.value === "rules"]
            ]),
            D(l("section", null, [
              l("header", id, [
                d[70] || (d[70] = l("h3", null, "Перенаправление портов", -1)),
                l("button", {
                  type: "button",
                  disabled: !i.value.redirectsSupported,
                  onClick: j
                }, "Добавить перенаправление", 8, ad)
              ]),
              i.value.redirectsSupported ? (f(), h("p", ud, "Внешний порт → IP устройства и внутренний порт. Изменения применяются после проверки плана.")) : (f(), h("p", rd, "Обновите интеграцию Bot4VPS на шлюзе для управления перенаправлениями портов.")),
              (f(!0), h(N, null, ie(i.value.redirects, (r, p) => (f(), h("details", {
                key: r.id || p,
                open: !r.id,
                class: "gw-settings-rule",
                onInput: (_) => pe(r),
                onChange: (_) => pe(r)
              }, [
                l("summary", null, [
                  l("strong", null, y(r.name || r.id || "Новое перенаправление"), 1),
                  l("span", null, y(r.src) + ":" + y(r.src_dport) + " → " + y(r.dest_ip || "Роутер") + ":" + y(r.dest_port || r.src_dport) + " · " + y(X(r.proto) || "TCP и UDP"), 1),
                  l("small", null, y(r.enabled === "0" ? "Выключено" : "Включено"), 1)
                ]),
                l("div", cd, [
                  l("button", {
                    type: "button",
                    class: "gw-danger",
                    onClick: (_) => Z(Number(p))
                  }, "Удалить перенаправление", 8, fd),
                  l("label", null, [
                    d[71] || (d[71] = I("Название", -1)),
                    D(l("input", {
                      "onUpdate:modelValue": (_) => r.name = _
                    }, null, 8, pd), [
                      [oe, r.name]
                    ])
                  ]),
                  l("div", vd, [
                    l("label", null, [
                      d[72] || (d[72] = I("Исходная зона", -1)),
                      D(l("select", {
                        "onUpdate:modelValue": (_) => r.src = _
                      }, [
                        (f(!0), h(N, null, ie(i.value.zones, (_) => (f(), h("option", {
                          key: _.id,
                          value: _.name
                        }, y(_.name), 9, hd))), 128))
                      ], 8, gd), [
                        [xe, r.src]
                      ])
                    ]),
                    l("label", null, [
                      d[73] || (d[73] = I("Зона назначения", -1)),
                      D(l("select", {
                        "onUpdate:modelValue": (_) => r.dest = _
                      }, [
                        (f(!0), h(N, null, ie(i.value.zones, (_) => (f(), h("option", {
                          key: _.id,
                          value: _.name
                        }, y(_.name), 9, bd))), 128))
                      ], 8, md), [
                        [xe, r.dest]
                      ])
                    ])
                  ]),
                  l("div", yd, [
                    l("label", null, [
                      d[74] || (d[74] = I("Внешний порт", -1)),
                      D(l("input", {
                        "onUpdate:modelValue": (_) => r.src_dport = _,
                        placeholder: "443 или 1000-2000"
                      }, null, 8, wd), [
                        [oe, r.src_dport]
                      ])
                    ]),
                    l("label", null, [
                      d[75] || (d[75] = I("IP устройства назначения", -1)),
                      D(l("input", {
                        "onUpdate:modelValue": (_) => r.dest_ip = _,
                        placeholder: "192.168.1.10"
                      }, null, 8, _d), [
                        [oe, r.dest_ip]
                      ])
                    ])
                  ]),
                  l("div", kd, [
                    l("label", null, [
                      d[76] || (d[76] = I("Внутренний порт", -1)),
                      D(l("input", {
                        "onUpdate:modelValue": (_) => r.dest_port = _,
                        placeholder: "Пусто — внешний порт"
                      }, null, 8, $d), [
                        [oe, r.dest_port]
                      ])
                    ]),
                    l("label", null, [
                      d[78] || (d[78] = I("Протокол", -1)),
                      D(l("select", {
                        "onUpdate:modelValue": (_) => r.proto = _
                      }, [...d[77] || (d[77] = [
                        l("option", { value: ["tcp", "udp"] }, "TCP и UDP", -1),
                        l("option", { value: "tcp" }, "TCP", -1),
                        l("option", { value: "udp" }, "UDP", -1)
                      ])], 8, Cd), [
                        [xe, r.proto]
                      ])
                    ])
                  ]),
                  l("label", null, [
                    d[79] || (d[79] = I("Разрешённый IP источника", -1)),
                    D(l("input", {
                      "onUpdate:modelValue": (_) => r.src_ip = _,
                      placeholder: "Пусто — любой адрес; можно CIDR"
                    }, null, 8, xd), [
                      [oe, r.src_ip]
                    ])
                  ]),
                  l("div", Sd, [
                    l("label", null, [
                      d[81] || (d[81] = I("Состояние", -1)),
                      D(l("select", {
                        "onUpdate:modelValue": (_) => r.enabled = _
                      }, [...d[80] || (d[80] = [
                        l("option", { value: void 0 }, "Включено по умолчанию", -1),
                        l("option", { value: "1" }, "Включено", -1),
                        l("option", { value: "0" }, "Выключено", -1)
                      ])], 8, Td), [
                        [xe, r.enabled]
                      ])
                    ]),
                    l("label", null, [
                      d[83] || (d[83] = I("NAT loopback", -1)),
                      D(l("select", {
                        "onUpdate:modelValue": (_) => r.reflection = _
                      }, [...d[82] || (d[82] = [
                        l("option", { value: void 0 }, "По умолчанию", -1),
                        l("option", { value: "1" }, "Включён", -1),
                        l("option", { value: "0" }, "Выключен", -1)
                      ])], 8, Ed), [
                        [xe, r.reflection]
                      ]),
                      d[84] || (d[84] = l("small", null, "Доступ из LAN через внешний адрес.", -1))
                    ])
                  ])
                ])
              ], 40, dd))), 128)),
              i.value.redirectsSupported && !i.value.redirects.length ? (f(), h("p", Pd, "Перенаправления не настроены.")) : T("", !0)
            ], 512), [
              [qn, g.value === "redirects"]
            ])
          ], 64)) : T("", !0),
          l("div", Ad, [
            l("button", {
              class: "gw-primary",
              disabled: u.value || e.mode === "dns" && !s.value.dns.length
            }, "Проверить изменения", 8, Ud),
            l("button", {
              type: "button",
              disabled: u.value,
              onClick: d[19] || (d[19] = (r) => o("close"))
            }, "Закрыть", 8, Vd)
          ])
        ], 32)) : u.value ? (f(), h("p", Id, "Получаем конфигурацию…")) : T("", !0)
      ]),
      _: 1
    }, 8, ["title", "busy"]));
  }
}), Od = { class: "gw-network" }, Md = { class: "gw-section-header" }, Rd = { class: "gw-actions" }, Dd = ["disabled"], Nd = ["disabled"], Fd = {
  key: 0,
  class: "gw-error",
  role: "alert"
}, qd = ["aria-busy"], Hd = { class: "gw-interface-name" }, Ld = { key: 0 }, jd = { class: "gw-interface-info" }, Wd = { key: 0 }, Bd = { class: "gw-interface-state" }, Kd = { class: "gw-interface-actions" }, Gd = ["disabled", "onClick"], zd = ["disabled", "onClick"], Jd = ["disabled", "onClick"], Yd = ["disabled", "title", "onClick"], Xd = {
  key: 1,
  class: "gw-hint"
}, Zd = { class: "gw-section-header gw-routes-heading" }, Qd = ["disabled"], ec = {
  key: 2,
  class: "gw-table-wrap"
}, tc = {
  key: 3,
  class: "gw-hint"
}, nc = { class: "gw-two" }, lc = ["readonly"], sc = { key: 0 }, oc = ["value"], ic = { class: "gw-two" }, ac = ["required", "placeholder"], rc = ["required", "placeholder"], uc = { class: "gw-two" }, dc = { class: "gw-network-extra" }, cc = { class: "gw-two" }, fc = { class: "gw-check" }, pc = { class: "gw-check" }, vc = {
  key: 0,
  class: "gw-check"
}, gc = { key: 4 }, hc = { class: "gw-section-header" }, mc = { class: "gw-section-header" }, bc = ["onClick"], yc = ["onUpdate:modelValue"], wc = { class: "gw-two" }, _c = ["onUpdate:modelValue"], kc = ["onUpdate:modelValue"], $c = ["onUpdate:modelValue"], Cc = { class: "gw-two" }, xc = ["onUpdate:modelValue"], Sc = ["onUpdate:modelValue", "placeholder"], Tc = { class: "gw-check" }, Ec = ["onUpdate:modelValue"], Pc = {
  key: 5,
  class: "gw-error",
  role: "alert"
}, Ac = { class: "gw-actions" }, Uc = ["disabled"], Vc = ["disabled"], Ic = ["disabled"], Oc = { class: "gw-section-header" }, Mc = ["onClick"], Rc = { class: "gw-two" }, Dc = ["onUpdate:modelValue"], Nc = ["onUpdate:modelValue"], Fc = ["value"], qc = { class: "gw-two" }, Hc = ["onUpdate:modelValue"], Lc = ["onUpdate:modelValue"], jc = { class: "gw-two" }, Wc = ["onUpdate:modelValue"], Bc = ["onUpdate:modelValue"], Kc = { class: "gw-check" }, Gc = ["onUpdate:modelValue"], zc = {
  key: 0,
  class: "gw-hint"
}, Jc = {
  key: 1,
  class: "gw-error",
  role: "alert"
}, Yc = { class: "gw-actions" }, Xc = ["disabled"], Zc = ["disabled"], Qc = { class: "gw-change-list" }, ef = {
  key: 0,
  class: "gw-notice"
}, tf = {
  key: 1,
  class: "gw-error",
  role: "alert"
}, nf = { class: "gw-actions" }, lf = ["disabled"], sf = ["disabled"], of = /* @__PURE__ */ qe({
  __name: "NetworkEditor",
  props: {
    node: {},
    bridge: {}
  },
  emits: ["changed"],
  setup(e, { emit: t }) {
    const n = e, o = t, s = /* @__PURE__ */ H({ interfaces: [], routes: [], devices: [] }), i = /* @__PURE__ */ H(!1), a = /* @__PURE__ */ H(!1), u = /* @__PURE__ */ H(""), c = /* @__PURE__ */ H(null), g = /* @__PURE__ */ H(null), m = /* @__PURE__ */ H(""), b = /* @__PURE__ */ H(null), S = /* @__PURE__ */ H(!1), A = /* @__PURE__ */ H([]), Y = ke(() => [.../* @__PURE__ */ new Set([...s.value.devices || [], ...b.value?.device ? [b.value.device] : []])]);
    let M = !0;
    const te = () => "/api/gateways/" + encodeURIComponent(n.node.id), X = (d, r, p = "POST") => n.bridge.request(te() + d, { method: p, headers: { "Content-Type": "application/json" }, body: JSON.stringify(r) }), Q = (d) => Array.isArray(d) ? d.join(", ") : d || "", ne = (d) => d.split(/[\s,]+/).filter(Boolean), O = (d) => d === "" || d == null ? null : String(d);
    function L(d) {
      return n.node.monitor.interfaces?.find((r) => r.name === d.name) || d;
    }
    function V(d) {
      return d.ipaddr === n.node.host || d.runtime_addresses?.includes(n.node.host);
    }
    async function E() {
      i.value = !0, u.value = "";
      try {
        const d = await n.bridge.request(te() + "/network");
        M && (s.value = d);
      } catch (d) {
        M && (u.value = d.message);
      } finally {
        M && (i.value = !1);
      }
    }
    async function C(d) {
      if (!a.value) {
        a.value = !0, u.value = "";
        try {
          await d();
        } catch (r) {
          u.value = r.message;
        } finally {
          a.value = !1;
        }
      }
    }
    function j(d) {
      u.value = "", b.value = {
        existing: !!d,
        name: d?.name || "",
        proto: d?.proto || "dhcp",
        device: d?.device || "",
        ipaddr: d?.ipaddr || "",
        netmask: d?.netmask || "255.255.255.0",
        gateway: d?.gateway || "",
        dns: Q(d?.dns),
        metric: d?.metric || "",
        mtu: d?.mtu || "",
        defaultroute: d?.defaultroute !== "0",
        peerdns: d?.peerdns !== "0",
        auto: d?.auto !== "0",
        username: d?.username || "",
        password: "",
        private_key: "",
        has_password: !!d?.has_password,
        has_private_key: !!d?.has_private_key,
        addresses: Q(d?.addresses),
        listen_port: d?.listen_port || "",
        peers: (d?.peers || []).map((r) => ({ ...r, allowed_ips: Q(r.allowed_ips), preshared_key: "", route_allowed_ips: r.route_allowed_ips === "1" }))
      };
    }
    async function Z(d, r) {
      await C(async () => {
        const p = await X("/network/plan", { action: d, data: { ...r, config_hash: s.value.config_hash } });
        b.value = null, S.value = !1, c.value = p;
      });
    }
    async function pe() {
      const d = b.value, r = {
        proto: d.proto,
        device: O(d.device),
        dns: ne(d.dns),
        metric: O(d.metric),
        mtu: O(d.mtu),
        auto: d.auto ? "1" : "0",
        defaultroute: d.defaultroute ? "1" : "0",
        peerdns: d.peerdns ? "1" : "0"
      };
      d.proto === "static" && Object.assign(r, { ipaddr: d.ipaddr, netmask: d.netmask, gateway: O(d.gateway) }), d.proto === "pppoe" && (r.username = d.username, d.password && (r.password = d.password));
      const p = { interface: d.name, settings: r };
      d.proto === "wireguard" && (r.addresses = ne(d.addresses), r.listen_port = O(d.listen_port), d.private_key && (r.private_key = d.private_key), p.peers = d.peers.map((_) => {
        const K = {
          public_key: _.public_key,
          endpoint_host: O(_.endpoint_host),
          endpoint_port: O(_.endpoint_port),
          allowed_ips: ne(_.allowed_ips || ""),
          persistent_keepalive: O(_.persistent_keepalive),
          route_allowed_ips: _.route_allowed_ips ? "1" : "0",
          description: O(_.description)
        };
        return _.id && (K.id = _.id), _.preshared_key && (K.preshared_key = _.preshared_key), K;
      })), await Z("edit", p);
    }
    function be() {
      u.value = "", A.value = s.value.routes.map((d) => ({
        interface: d.interface || "",
        target: d.target || "",
        netmask: d.netmask || "255.255.255.255",
        gateway: d.gateway || "",
        metric: d.metric || "",
        table: d.table || "",
        onlink: d.onlink === "1"
      })), S.value = !0;
    }
    function Ue() {
      A.value.push({ interface: s.value.interfaces[0]?.name || "", target: "", netmask: "", gateway: "", metric: "", table: "", onlink: !1 });
    }
    async function Oe() {
      await Z("routes", { routes: A.value.map((d) => ({
        interface: d.interface,
        target: d.target,
        netmask: O(d.netmask),
        gateway: O(d.gateway),
        metric: O(d.metric),
        table: O(d.table),
        onlink: d.onlink ? "1" : "0"
      })) });
    }
    async function le() {
      await C(async () => {
        const d = c.value, r = await X("/router-operations", { plan_token: d.plan_token, confirmed: !0 });
        c.value = null, n.bridge.task({
          taskId: r.task_id,
          title: d.title + (d.interface ? " " + d.interface : ""),
          cancellable: !1,
          onDone: async () => {
            await E(), o("changed");
          }
        });
      });
    }
    function P() {
      const d = c.value?.plan_token;
      c.value = null, u.value = "", d && X("/operation-plans/" + encodeURIComponent(d), {}, "DELETE").catch((r) => {
        u.value = r.message;
      });
    }
    return rt(() => {
      E();
    }), Rt(() => {
      M = !1, b.value = null;
    }), (d, r) => (f(), h(N, null, [
      l("section", Od, [
        l("header", Md, [
          r[26] || (r[26] = l("div", null, [
            l("h3", null, "Подключения"),
            l("p", { class: "gw-hint" }, "LAN, WAN и туннели · настройки и состояние")
          ], -1)),
          l("div", Rd, [
            l("button", {
              disabled: i.value || a.value,
              onClick: E
            }, "Обновить", 8, Dd),
            l("button", {
              disabled: i.value || a.value || !s.value.config_hash,
              onClick: r[0] || (r[0] = (p) => j())
            }, "Добавить подключение", 8, Nd)
          ])
        ]),
        u.value && !b.value && !S.value && !c.value ? (f(), h("p", Fd, y(u.value), 1)) : T("", !0),
        l("div", {
          class: "gw-interface-list",
          "aria-busy": i.value
        }, [
          (f(!0), h(N, null, ie(s.value.interfaces, (p) => (f(), h("article", {
            key: p.name,
            class: "gw-interface"
          }, [
            l("div", Hd, [
              l("h4", null, y(p.name), 1),
              V(p) ? (f(), h("small", Ld, "Доступ к панели")) : T("", !0)
            ]),
            l("div", jd, [
              l("span", null, y(p.proto) + " · " + y(p.device || p.runtime_device || "—"), 1),
              l("strong", null, y(L(p).addresses?.join(", ") || p.runtime_addresses?.join(", ") || p.ipaddr || Q(p.addresses) || "Без адреса"), 1),
              p.gateway ? (f(), h("small", Wd, "Шлюз " + y(p.gateway), 1)) : T("", !0)
            ]),
            l("div", Bd, [
              l("span", {
                class: Ee(["gw-status", L(p).up ? "good" : "warn"])
              }, y(L(p).up ? "Подключён" : L(p).pending ? "Подключается" : "Отключён"), 3)
            ]),
            l("div", Kd, [
              l("button", {
                disabled: a.value,
                onClick: (_) => j(p)
              }, "Настроить", 8, Gd),
              l("button", {
                disabled: a.value,
                onClick: (_) => {
                  m.value = p.name, g.value = "dhcp";
                }
              }, "DHCP", 8, zd),
              L(p).up ? (f(), h("button", {
                key: 0,
                disabled: a.value,
                onClick: (_) => Z("reconnect", { interface: p.name })
              }, "Переподключить", 8, Jd)) : T("", !0),
              l("button", {
                disabled: a.value || V(p) && L(p).up,
                title: V(p) ? "Интерфейс доступа изменяется через форму с откатом" : "",
                onClick: (_) => Z(L(p).up ? "down" : "up", { interface: p.name })
              }, y(L(p).up ? "Отключить" : "Подключить"), 9, Yd)
            ])
          ]))), 128))
        ], 8, qd),
        s.value.interfaces.length ? T("", !0) : (f(), h("p", Xd, y(i.value ? "Получаем состояние сети…" : "Интерфейсы не найдены."), 1)),
        l("header", Zd, [
          r[27] || (r[27] = l("div", null, [
            l("h3", null, "Статические маршруты IPv4"),
            l("p", { class: "gw-hint" }, "Автоматические маршруты создаются протоколами подключений")
          ], -1)),
          l("button", {
            disabled: a.value || i.value || !s.value.config_hash,
            onClick: be
          }, "Настроить маршруты", 8, Qd)
        ]),
        s.value.routes.length ? (f(), h("div", ec, [
          l("table", null, [
            r[28] || (r[28] = l("thead", null, [
              l("tr", null, [
                l("th", null, "Сеть"),
                l("th", null, "Через шлюз"),
                l("th", null, "Интерфейс"),
                l("th", null, "Метрика")
              ])
            ], -1)),
            l("tbody", null, [
              (f(!0), h(N, null, ie(s.value.routes, (p) => (f(), h("tr", {
                key: p.id
              }, [
                l("td", null, [
                  I(y(p.target), 1),
                  l("small", null, y(p.netmask), 1)
                ]),
                l("td", null, y(p.gateway || "Напрямую"), 1),
                l("td", null, y(p.interface), 1),
                l("td", null, y(p.metric || "0"), 1)
              ]))), 128))
            ])
          ])
        ])) : (f(), h("p", tc, "Статические маршруты не заданы."))
      ]),
      g.value ? (f(), ge(ni, {
        key: 0,
        node: e.node,
        bridge: e.bridge,
        mode: g.value,
        iface: g.value === "dhcp" ? m.value : void 0,
        onClose: r[1] || (r[1] = (p) => g.value = null),
        onChanged: r[2] || (r[2] = (p) => {
          E(), o("changed");
        })
      }, null, 8, ["node", "bridge", "mode", "iface"])) : T("", !0),
      b.value ? (f(), ge(Fe, {
        key: 1,
        title: b.value.existing ? "Настройка " + b.value.name : "Новое подключение",
        wide: !0,
        busy: a.value,
        onClose: r[23] || (r[23] = (p) => {
          b.value = null, u.value = "";
        })
      }, {
        default: Me(() => [
          l("form", {
            class: "gw-form gw-network-form",
            onSubmit: lt(pe, ["prevent"])
          }, [
            l("div", nc, [
              l("label", null, [
                r[29] || (r[29] = I("Имя интерфейса", -1)),
                D(l("input", {
                  "onUpdate:modelValue": r[3] || (r[3] = (p) => b.value.name = p),
                  required: "",
                  pattern: "[A-Za-z][A-Za-z0-9_]{0,30}",
                  readonly: b.value.existing,
                  placeholder: "wan, lan, wg0"
                }, null, 8, lc), [
                  [oe, b.value.name]
                ])
              ]),
              l("label", null, [
                r[31] || (r[31] = I("Протокол", -1)),
                D(l("select", {
                  "onUpdate:modelValue": r[4] || (r[4] = (p) => b.value.proto = p)
                }, [...r[30] || (r[30] = [
                  l("option", { value: "dhcp" }, "DHCP-клиент", -1),
                  l("option", { value: "static" }, "Статический адрес", -1),
                  l("option", { value: "pppoe" }, "PPPoE", -1),
                  l("option", { value: "wireguard" }, "WireGuard", -1),
                  l("option", { value: "none" }, "Без протокола", -1)
                ])], 512), [
                  [xe, b.value.proto]
                ])
              ])
            ]),
            b.value.proto !== "wireguard" ? (f(), h("label", sc, [
              r[33] || (r[33] = I("Сетевое устройство", -1)),
              D(l("select", {
                "onUpdate:modelValue": r[5] || (r[5] = (p) => b.value.device = p)
              }, [
                r[32] || (r[32] = l("option", { value: "" }, "Автоматически", -1)),
                (f(!0), h(N, null, ie(Y.value, (p) => (f(), h("option", {
                  key: p,
                  value: p
                }, y(p), 9, oc))), 128))
              ], 512), [
                [xe, b.value.device]
              ])
            ])) : T("", !0),
            b.value.proto === "static" ? (f(), h(N, { key: 1 }, [
              l("div", ic, [
                l("label", null, [
                  r[34] || (r[34] = I("IPv4-адрес", -1)),
                  D(l("input", {
                    "onUpdate:modelValue": r[6] || (r[6] = (p) => b.value.ipaddr = p),
                    required: "",
                    placeholder: "192.168.1.2"
                  }, null, 512), [
                    [oe, b.value.ipaddr]
                  ])
                ]),
                l("label", null, [
                  r[35] || (r[35] = I("Маска подсети", -1)),
                  D(l("input", {
                    "onUpdate:modelValue": r[7] || (r[7] = (p) => b.value.netmask = p),
                    required: "",
                    placeholder: "255.255.255.0"
                  }, null, 512), [
                    [oe, b.value.netmask]
                  ])
                ])
              ]),
              l("label", null, [
                r[36] || (r[36] = I("IPv4-шлюз", -1)),
                D(l("input", {
                  "onUpdate:modelValue": r[8] || (r[8] = (p) => b.value.gateway = p),
                  placeholder: "192.168.1.1"
                }, null, 512), [
                  [oe, b.value.gateway]
                ])
              ])
            ], 64)) : T("", !0),
            b.value.proto === "pppoe" ? (f(), h(N, { key: 2 }, [
              l("label", null, [
                r[37] || (r[37] = I("Логин PPPoE", -1)),
                D(l("input", {
                  "onUpdate:modelValue": r[9] || (r[9] = (p) => b.value.username = p),
                  required: "",
                  autocomplete: "off"
                }, null, 512), [
                  [oe, b.value.username]
                ])
              ]),
              l("label", null, [
                r[38] || (r[38] = I("Пароль PPPoE", -1)),
                D(l("input", {
                  "onUpdate:modelValue": r[10] || (r[10] = (p) => b.value.password = p),
                  type: "password",
                  autocomplete: "off",
                  required: !b.value.has_password,
                  placeholder: b.value.has_password ? "Пустое поле сохраняет текущий пароль" : ""
                }, null, 8, ac), [
                  [oe, b.value.password]
                ])
              ])
            ], 64)) : T("", !0),
            b.value.proto === "wireguard" ? (f(), h(N, { key: 3 }, [
              l("label", null, [
                r[39] || (r[39] = I("Приватный ключ WireGuard", -1)),
                D(l("input", {
                  "onUpdate:modelValue": r[11] || (r[11] = (p) => b.value.private_key = p),
                  type: "password",
                  autocomplete: "off",
                  required: !b.value.has_private_key,
                  placeholder: b.value.has_private_key ? "Пустое поле сохраняет текущий ключ" : ""
                }, null, 8, rc), [
                  [oe, b.value.private_key]
                ])
              ]),
              l("div", uc, [
                l("label", null, [
                  r[40] || (r[40] = I("Адреса туннеля", -1)),
                  D(l("input", {
                    "onUpdate:modelValue": r[12] || (r[12] = (p) => b.value.addresses = p),
                    required: "",
                    placeholder: "10.10.0.2/24"
                  }, null, 512), [
                    [oe, b.value.addresses]
                  ])
                ]),
                l("label", null, [
                  r[41] || (r[41] = I("Порт WireGuard", -1)),
                  D(l("input", {
                    "onUpdate:modelValue": r[13] || (r[13] = (p) => b.value.listen_port = p),
                    type: "number",
                    min: "1",
                    max: "65535",
                    placeholder: "Автоматически"
                  }, null, 512), [
                    [oe, b.value.listen_port]
                  ])
                ])
              ])
            ], 64)) : T("", !0),
            l("label", null, [
              r[42] || (r[42] = I("DNS-серверы", -1)),
              D(l("input", {
                "onUpdate:modelValue": r[14] || (r[14] = (p) => b.value.dns = p),
                placeholder: "1.1.1.1, 8.8.8.8"
              }, null, 512), [
                [oe, b.value.dns]
              ]),
              r[43] || (r[43] = l("small", null, "Несколько адресов разделяются пробелами или запятыми", -1))
            ]),
            l("details", dc, [
              r[49] || (r[49] = l("summary", null, "Дополнительные параметры", -1)),
              l("div", cc, [
                l("label", null, [
                  r[44] || (r[44] = I("Метрика маршрута", -1)),
                  D(l("input", {
                    "onUpdate:modelValue": r[15] || (r[15] = (p) => b.value.metric = p),
                    type: "number",
                    min: "0",
                    placeholder: "По умолчанию"
                  }, null, 512), [
                    [oe, b.value.metric]
                  ])
                ]),
                l("label", null, [
                  r[45] || (r[45] = I("MTU", -1)),
                  D(l("input", {
                    "onUpdate:modelValue": r[16] || (r[16] = (p) => b.value.mtu = p),
                    type: "number",
                    min: "576",
                    max: "65535",
                    placeholder: "По умолчанию"
                  }, null, 512), [
                    [oe, b.value.mtu]
                  ])
                ])
              ]),
              l("label", fc, [
                D(l("input", {
                  "onUpdate:modelValue": r[17] || (r[17] = (p) => b.value.auto = p),
                  type: "checkbox"
                }, null, 512), [
                  [Be, b.value.auto]
                ]),
                r[46] || (r[46] = I(" Подключать при загрузке роутера", -1))
              ]),
              l("label", pc, [
                D(l("input", {
                  "onUpdate:modelValue": r[18] || (r[18] = (p) => b.value.defaultroute = p),
                  type: "checkbox"
                }, null, 512), [
                  [Be, b.value.defaultroute]
                ]),
                r[47] || (r[47] = I(" Использовать маршрут по умолчанию", -1))
              ]),
              b.value.proto === "dhcp" || b.value.proto === "pppoe" ? (f(), h("label", vc, [
                D(l("input", {
                  "onUpdate:modelValue": r[19] || (r[19] = (p) => b.value.peerdns = p),
                  type: "checkbox"
                }, null, 512), [
                  [Be, b.value.peerdns]
                ]),
                r[48] || (r[48] = I(" Получать DNS от подключения", -1))
              ])) : T("", !0)
            ]),
            b.value.proto === "wireguard" ? (f(), h("section", gc, [
              l("header", hc, [
                r[50] || (r[50] = l("h3", null, "Пиры WireGuard", -1)),
                l("button", {
                  type: "button",
                  onClick: r[20] || (r[20] = (p) => b.value.peers.push({ public_key: "", allowed_ips: "", endpoint_host: "", endpoint_port: "", persistent_keepalive: "", preshared_key: "", route_allowed_ips: !0 }))
                }, "Добавить пир")
              ]),
              (f(!0), h(N, null, ie(b.value.peers, (p, _) => (f(), h("article", {
                key: p.id || _,
                class: "gw-peer-form"
              }, [
                l("div", mc, [
                  l("h4", null, "Пир " + y(Number(_) + 1), 1),
                  l("button", {
                    type: "button",
                    onClick: (K) => b.value.peers.splice(_, 1)
                  }, "Удалить пир", 8, bc)
                ]),
                l("label", null, [
                  r[51] || (r[51] = I("Публичный ключ", -1)),
                  D(l("input", {
                    "onUpdate:modelValue": (K) => p.public_key = K,
                    required: "",
                    autocomplete: "off"
                  }, null, 8, yc), [
                    [oe, p.public_key]
                  ])
                ]),
                l("div", wc, [
                  l("label", null, [
                    r[52] || (r[52] = I("Endpoint", -1)),
                    D(l("input", {
                      "onUpdate:modelValue": (K) => p.endpoint_host = K,
                      placeholder: "vpn.example.org"
                    }, null, 8, _c), [
                      [oe, p.endpoint_host]
                    ])
                  ]),
                  l("label", null, [
                    r[53] || (r[53] = I("Порт", -1)),
                    D(l("input", {
                      "onUpdate:modelValue": (K) => p.endpoint_port = K,
                      type: "number",
                      min: "1",
                      max: "65535"
                    }, null, 8, kc), [
                      [oe, p.endpoint_port]
                    ])
                  ])
                ]),
                l("label", null, [
                  r[54] || (r[54] = I("Разрешённые сети", -1)),
                  D(l("input", {
                    "onUpdate:modelValue": (K) => p.allowed_ips = K,
                    required: "",
                    placeholder: "0.0.0.0/0, ::/0"
                  }, null, 8, $c), [
                    [oe, p.allowed_ips]
                  ])
                ]),
                l("div", Cc, [
                  l("label", null, [
                    r[55] || (r[55] = I("Keepalive, секунд", -1)),
                    D(l("input", {
                      "onUpdate:modelValue": (K) => p.persistent_keepalive = K,
                      type: "number",
                      min: "0",
                      max: "65535",
                      placeholder: "25"
                    }, null, 8, xc), [
                      [oe, p.persistent_keepalive]
                    ])
                  ]),
                  l("label", null, [
                    r[56] || (r[56] = I("Общий ключ, необязательно", -1)),
                    D(l("input", {
                      "onUpdate:modelValue": (K) => p.preshared_key = K,
                      type: "password",
                      autocomplete: "off",
                      placeholder: p.has_preshared_key ? "Пустое поле сохраняет текущий ключ" : ""
                    }, null, 8, Sc), [
                      [oe, p.preshared_key]
                    ])
                  ])
                ]),
                l("label", Tc, [
                  D(l("input", {
                    "onUpdate:modelValue": (K) => p.route_allowed_ips = K,
                    type: "checkbox"
                  }, null, 8, Ec), [
                    [Be, p.route_allowed_ips]
                  ]),
                  r[57] || (r[57] = I(" Создать маршруты для разрешённых сетей", -1))
                ])
              ]))), 128))
            ])) : T("", !0),
            r[58] || (r[58] = l("p", { class: "gw-hint" }, "Перед применением вы увидите изменения. Если панель не подтвердит доступность, роутер восстановит прежнюю сеть.", -1)),
            u.value ? (f(), h("p", Pc, y(u.value), 1)) : T("", !0),
            l("div", Ac, [
              l("button", {
                class: "gw-primary",
                disabled: a.value
              }, "Проверить изменения", 8, Uc),
              l("button", {
                type: "button",
                disabled: a.value,
                onClick: r[21] || (r[21] = (p) => b.value = null)
              }, "Отмена", 8, Vc),
              b.value.existing ? (f(), h("button", {
                key: 0,
                type: "button",
                disabled: a.value,
                onClick: r[22] || (r[22] = (p) => Z("delete", { interface: b.value.name }))
              }, "Удалить интерфейс", 8, Ic)) : T("", !0)
            ])
          ], 32)
        ]),
        _: 1
      }, 8, ["title", "busy"])) : T("", !0),
      S.value ? (f(), ge(Fe, {
        key: 2,
        title: "Статические маршруты IPv4",
        wide: !0,
        busy: a.value,
        onClose: r[25] || (r[25] = (p) => {
          S.value = !1, u.value = "";
        })
      }, {
        default: Me(() => [
          l("form", {
            class: "gw-form",
            onSubmit: lt(Oe, ["prevent"])
          }, [
            (f(!0), h(N, null, ie(A.value, (p, _) => (f(), h("article", {
              key: _,
              class: "gw-route-form"
            }, [
              l("div", Oc, [
                l("h4", null, "Маршрут " + y(Number(_) + 1), 1),
                l("button", {
                  type: "button",
                  onClick: (K) => A.value.splice(_, 1)
                }, "Удалить маршрут", 8, Mc)
              ]),
              l("div", Rc, [
                l("label", null, [
                  r[59] || (r[59] = I("Сеть назначения", -1)),
                  D(l("input", {
                    "onUpdate:modelValue": (K) => p.target = K,
                    required: "",
                    placeholder: "10.20.0.0/24"
                  }, null, 8, Dc), [
                    [oe, p.target]
                  ])
                ]),
                l("label", null, [
                  r[60] || (r[60] = I("Интерфейс", -1)),
                  D(l("select", {
                    "onUpdate:modelValue": (K) => p.interface = K
                  }, [
                    (f(!0), h(N, null, ie(s.value.interfaces, (K) => (f(), h("option", {
                      key: K.name,
                      value: K.name
                    }, y(K.name), 9, Fc))), 128))
                  ], 8, Nc), [
                    [xe, p.interface]
                  ])
                ])
              ]),
              l("div", qc, [
                l("label", null, [
                  r[61] || (r[61] = I("Через шлюз", -1)),
                  D(l("input", {
                    "onUpdate:modelValue": (K) => p.gateway = K,
                    placeholder: "Напрямую, если пусто"
                  }, null, 8, Hc), [
                    [oe, p.gateway]
                  ])
                ]),
                l("label", null, [
                  r[62] || (r[62] = I("Маска, если в адресе нет /префикса", -1)),
                  D(l("input", {
                    "onUpdate:modelValue": (K) => p.netmask = K,
                    placeholder: "255.255.255.0"
                  }, null, 8, Lc), [
                    [oe, p.netmask]
                  ])
                ])
              ]),
              l("div", jc, [
                l("label", null, [
                  r[63] || (r[63] = I("Метрика", -1)),
                  D(l("input", {
                    "onUpdate:modelValue": (K) => p.metric = K,
                    type: "number",
                    min: "0"
                  }, null, 8, Wc), [
                    [oe, p.metric]
                  ])
                ]),
                l("label", null, [
                  r[64] || (r[64] = I("Таблица маршрутов", -1)),
                  D(l("input", {
                    "onUpdate:modelValue": (K) => p.table = K,
                    type: "number",
                    min: "0",
                    placeholder: "Основная"
                  }, null, 8, Bc), [
                    [oe, p.table]
                  ])
                ])
              ]),
              l("label", Kc, [
                D(l("input", {
                  "onUpdate:modelValue": (K) => p.onlink = K,
                  type: "checkbox"
                }, null, 8, Gc), [
                  [Be, p.onlink]
                ]),
                r[65] || (r[65] = I(" Шлюз доступен напрямую", -1))
              ])
            ]))), 128)),
            l("button", {
              type: "button",
              onClick: Ue
            }, "Добавить маршрут"),
            A.value.length ? T("", !0) : (f(), h("p", zc, "Статические маршруты будут отсутствовать. Автоматические маршруты сохраняются.")),
            u.value ? (f(), h("p", Jc, y(u.value), 1)) : T("", !0),
            l("div", Yc, [
              l("button", {
                class: "gw-primary",
                disabled: a.value
              }, "Проверить изменения", 8, Xc),
              l("button", {
                type: "button",
                disabled: a.value,
                onClick: r[24] || (r[24] = (p) => S.value = !1)
              }, "Отмена", 8, Zc)
            ])
          ], 32)
        ]),
        _: 1
      }, 8, ["busy"])) : T("", !0),
      c.value ? (f(), ge(Fe, {
        key: 3,
        title: "Проверка сетевых изменений",
        busy: a.value,
        onClose: P
      }, {
        default: Me(() => [
          l("h3", null, y(c.value.title) + " " + y(c.value.interface), 1),
          l("ul", Qc, [
            (f(!0), h(N, null, ie(c.value.summary, (p, _) => (f(), h("li", { key: _ }, y(p), 1))), 128))
          ]),
          c.value.address_changes ? (f(), h("p", ef, [
            r[66] || (r[66] = I("Адрес подключения изменится на ", -1)),
            l("strong", null, y(c.value.new_api_host), 1),
            r[67] || (r[67] = I(". Панель проверит новый адрес и сохранит его после успешного применения.", -1))
          ])) : T("", !0),
          l("p", null, "Роутер ждёт подтверждения до " + y(c.value.rollback_seconds) + " секунд. Если панель потеряет связь, прежняя конфигурация будет восстановлена автоматически.", 1),
          u.value ? (f(), h("p", tf, y(u.value), 1)) : T("", !0),
          l("div", nf, [
            l("button", {
              class: "gw-primary",
              disabled: a.value,
              onClick: le
            }, "Да, применить изменения", 8, lf),
            l("button", {
              disabled: a.value,
              onClick: P
            }, "Отмена", 8, sf)
          ])
        ]),
        _: 1
      }, 8, ["busy"])) : T("", !0)
    ], 64));
  }
}), af = { class: "gw-packages" }, rf = { class: "gw-section-header" }, uf = { class: "gw-hint" }, df = ["disabled"], cf = {
  key: 0,
  class: "gw-error",
  role: "alert"
}, ff = { class: "gw-package-filters" }, pf = { class: "gw-segment" }, vf = ["disabled"], gf = {
  key: 1,
  class: "gw-notice"
}, hf = ["aria-busy"], mf = { class: "gw-package-table" }, bf = { key: 0 }, yf = {
  key: 0,
  class: "gw-status good"
}, wf = ["disabled", "onClick"], _f = {
  key: 2,
  class: "gw-hint"
}, kf = { class: "gw-pagination" }, $f = { class: "gw-hint" }, Cf = { class: "gw-actions" }, xf = ["disabled"], Sf = ["disabled"], Tf = { class: "gw-plan-output" }, Ef = {
  key: 0,
  class: "gw-error",
  role: "alert"
}, Pf = { class: "gw-actions" }, Af = ["disabled"], Uf = ["disabled"], Vf = /* @__PURE__ */ qe({
  __name: "PackageManager",
  props: {
    node: {},
    bridge: {},
    initialQuery: {}
  },
  emits: ["changed"],
  setup(e, { emit: t }) {
    const n = e, o = t, s = /* @__PURE__ */ H(n.initialQuery || ""), i = /* @__PURE__ */ H(!1), a = /* @__PURE__ */ H(!1), u = /* @__PURE__ */ H(!1), c = /* @__PURE__ */ H(""), g = /* @__PURE__ */ H({ items: [], total: 0, offset: 0, has_indexes: !1 }), m = /* @__PURE__ */ H(null);
    let b, S = 0;
    const A = () => "/api/gateways/" + encodeURIComponent(n.node.id), Y = (V, E, C = "POST") => n.bridge.request(A() + V, { method: C, headers: { "Content-Type": "application/json" }, body: JSON.stringify(E) });
    async function M(V = 0) {
      const E = ++S;
      a.value = !0, c.value = "";
      try {
        const C = await n.bridge.request(A() + "/packages?query=" + encodeURIComponent(s.value) + "&installed=" + i.value + "&offset=" + V);
        E === S && (g.value = C);
      } catch (C) {
        E === S && (c.value = C.message);
      } finally {
        E === S && (a.value = !1);
      }
    }
    async function te(V) {
      const E = await Y("/router-operations", { plan_token: V.plan_token, confirmed: !0 });
      m.value = null, n.bridge.task({
        taskId: E.task_id,
        title: V.action === "refresh" ? "Обновление списка пакетов" : "Установка " + V.package,
        cancellable: !1,
        onDone: async () => {
          await M(), o("changed");
        }
      });
    }
    async function X() {
      if (!u.value) {
        u.value = !0, c.value = "";
        try {
          const V = await Y("/packages/plan", { action: "refresh" });
          await te(V);
        } catch (V) {
          c.value = V.message;
        } finally {
          u.value = !1;
        }
      }
    }
    async function Q(V) {
      if (!u.value) {
        u.value = !0, c.value = "";
        try {
          m.value = await Y("/packages/plan", { action: "install", package: V });
        } catch (E) {
          c.value = E.message;
        } finally {
          u.value = !1;
        }
      }
    }
    async function ne() {
      if (!u.value) {
        u.value = !0, c.value = "";
        try {
          await te(m.value);
        } catch (V) {
          c.value = V.message;
        } finally {
          u.value = !1;
        }
      }
    }
    function O(V) {
      i.value = V, M();
    }
    function L() {
      const V = m.value?.plan_token;
      m.value = null, c.value = "", V && Y("/operation-plans/" + encodeURIComponent(V), {}, "DELETE").catch((E) => {
        c.value = E.message;
      });
    }
    return st(s, () => {
      b && clearTimeout(b), b = setTimeout(() => {
        M();
      }, 300);
    }), rt(() => {
      M();
    }), Rt(() => {
      S++, b && clearTimeout(b);
    }), (V, E) => (f(), h(N, null, [
      l("section", af, [
        l("header", rf, [
          l("div", null, [
            E[6] || (E[6] = l("h3", null, "Пакетный менеджер", -1)),
            l("p", uf, y(g.value.manager || "OpenWrt") + " · " + y(g.value.installed_count ?? "—") + " установленных пакетов", 1)
          ]),
          l("button", {
            disabled: u.value,
            onClick: X
          }, "Обновить список пакетов", 8, df)
        ]),
        E[8] || (E[8] = l("p", { class: "gw-hint" }, "Обновляется каталог репозиториев. Установленные пакеты и прошивка автоматически не обновляются.", -1)),
        c.value && !m.value ? (f(), h("div", cf, y(c.value), 1)) : T("", !0),
        l("div", ff, [
          l("div", pf, [
            l("button", {
              class: Ee({ on: !i.value }),
              onClick: E[0] || (E[0] = (C) => O(!1))
            }, "Доступные", 2),
            l("button", {
              class: Ee({ on: i.value }),
              onClick: E[1] || (E[1] = (C) => O(!0))
            }, "Установленные", 2)
          ]),
          l("form", {
            onSubmit: E[3] || (E[3] = lt((C) => M(), ["prevent"]))
          }, [
            D(l("input", {
              "onUpdate:modelValue": E[2] || (E[2] = (C) => s.value = C),
              type: "search",
              "aria-label": "Поиск пакетов",
              placeholder: "Название или описание пакета…",
              maxlength: "100"
            }, null, 512), [
              [oe, s.value]
            ]),
            l("button", { disabled: a.value }, "Найти", 8, vf)
          ], 32)
        ]),
        !g.value.has_indexes && !a.value ? (f(), h("p", gf, "Список доступных пакетов ещё не загружен. Нажмите «Обновить список пакетов» — ход загрузки появится в журнале.")) : T("", !0),
        l("div", {
          class: "gw-table-wrap",
          "aria-busy": a.value
        }, [
          l("table", mf, [
            E[7] || (E[7] = l("thead", null, [
              l("tr", null, [
                l("th", null, "Пакет"),
                l("th", null, "Версия"),
                l("th")
              ])
            ], -1)),
            l("tbody", null, [
              (f(!0), h(N, null, ie(g.value.items, (C) => (f(), h("tr", {
                key: C.name
              }, [
                l("td", null, [
                  l("strong", null, y(C.name), 1),
                  l("small", null, y(C.description), 1)
                ]),
                l("td", null, [
                  l("span", null, y(C.installed_version || C.version), 1),
                  C.installed_version && C.installed_version !== C.version ? (f(), h("small", bf, "В каталоге: " + y(C.version), 1)) : T("", !0)
                ]),
                l("td", null, [
                  C.installed_version ? (f(), h("span", yf, "Установлен")) : (f(), h("button", {
                    key: 1,
                    disabled: u.value || a.value,
                    onClick: (j) => Q(C.name)
                  }, "Установить", 8, wf))
                ])
              ]))), 128))
            ])
          ])
        ], 8, hf),
        g.value.items.length ? T("", !0) : (f(), h("p", _f, y(a.value ? "Загружаем пакеты…" : s.value ? "По вашему запросу пакеты не найдены." : "Пакетов в этом списке нет."), 1)),
        l("footer", kf, [
          l("span", $f, y(a.value ? "Загрузка…" : g.value.total ? g.value.offset + 1 + "–" + Math.min(g.value.offset + g.value.items.length, g.value.total) + " из " + g.value.total : "0 пакетов"), 1),
          l("div", Cf, [
            l("button", {
              disabled: a.value || g.value.offset === 0,
              onClick: E[4] || (E[4] = (C) => M(Math.max(0, g.value.offset - 40)))
            }, "Назад", 8, xf),
            l("button", {
              disabled: a.value || g.value.offset + 40 >= g.value.total,
              onClick: E[5] || (E[5] = (C) => M(g.value.offset + 40))
            }, "Далее", 8, Sf)
          ])
        ])
      ]),
      m.value ? (f(), ge(Fe, {
        key: 0,
        title: "Установить " + m.value.package + "?",
        busy: u.value,
        onClose: L
      }, {
        default: Me(() => [
          E[9] || (E[9] = l("p", null, "Пакетный менеджер рассчитает и установит необходимые зависимости из настроенных репозиториев роутера.", -1)),
          l("pre", Tf, y(m.value.summary.join(`
`)), 1),
          E[10] || (E[10] = l("p", { class: "gw-hint" }, "Установочные скрипты пакетов могут менять настройки и запускать службы. Автоматическая замена уже установленных пакетов отключена.", -1)),
          c.value ? (f(), h("p", Ef, y(c.value), 1)) : T("", !0),
          l("div", Pf, [
            l("button", {
              class: "gw-primary",
              disabled: u.value,
              onClick: ne
            }, "Да, установить", 8, Af),
            l("button", {
              disabled: u.value,
              onClick: L
            }, "Отмена", 8, Uf)
          ])
        ]),
        _: 1
      }, 8, ["title", "busy"])) : T("", !0)
    ], 64));
  }
}), If = { class: "gw-traffic-overview" }, Of = { class: "gw-section-header" }, Mf = { class: "gw-traffic-tools" }, Rf = {
  key: 0,
  class: "gw-chart-note"
}, Df = { class: "gw-traffic-grid" }, Nf = { class: "gw-section-header" }, Ff = { class: "gw-traffic-speeds" }, qf = { class: "gw-rx" }, Hf = { class: "gw-tx" }, Lf = ["onPointermove", "onPointerleave"], jf = ["aria-label"], Wf = ["y1", "y2"], Bf = ["d"], Kf = ["d"], Gf = {
  key: 0,
  class: "gw-chart-empty"
}, zf = {
  key: 1,
  class: "gw-chart-tip"
}, Jf = { class: "gw-traffic-total" }, Yf = { class: "gw-hint gw-counter-note" }, Xf = /* @__PURE__ */ qe({
  __name: "TrafficCharts",
  props: {
    monitor: {},
    nodeId: {},
    bridge: {}
  },
  setup(e) {
    const t = ["lan", "wan"], n = e, o = /* @__PURE__ */ H(3600), s = /* @__PURE__ */ H({ lan: null, wan: null }), i = /* @__PURE__ */ H(null), a = /* @__PURE__ */ H("");
    let u = !0, c = 0, g;
    async function m() {
      if (!n.bridge || !n.nodeId) return;
      const O = ++c;
      try {
        const L = await n.bridge.request("/api/gateways/" + encodeURIComponent(n.nodeId) + "/traffic?seconds=" + o.value);
        u && O === c && Array.isArray(L.traffic_history) && (i.value = L.traffic_history, a.value = "");
      } catch (L) {
        u && O === c && (a.value = L instanceof Error ? L.message : String(L));
      }
    }
    st([o, () => n.nodeId], () => {
      s.value = { lan: null, wan: null }, i.value = null, m();
    }, { immediate: !0 }), rt(() => {
      g = setInterval(() => {
        document.hidden || m();
      }, 3e4);
    }), Rt(() => {
      u = !1, c++, clearInterval(g);
    });
    const b = (O, L = !1) => {
      if (O == null) return "—";
      const V = ["Б", "КБ", "МБ", "ГБ", "ТБ"];
      let E = Number(O), C = 0;
      for (; E >= 1024 && C < V.length - 1; )
        E /= 1024, C++;
      return (E < 10 ? E.toFixed(1) : Math.round(E)) + " " + V[C] + (L ? "/с" : "");
    }, S = ke(() => {
      const O = i.value ?? n.monitor.traffic_history ?? [], L = O.at(-1)?.at || Date.now() / 1e3;
      return O.filter((V) => V.at >= L - o.value);
    }), A = ke(() => S.value.at(-1)?.at || n.monitor.checked_at || Date.now() / 1e3), Y = ke(() => A.value - o.value), M = (O) => new Date(O * 1e3).toLocaleString("ru-RU", o.value >= 43200 ? { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" } : { hour: "2-digit", minute: "2-digit" });
    function te(O) {
      return Math.max(1, ...S.value.flatMap((L) => [L[O]?.rx_bps || 0, L[O]?.tx_bps || 0]));
    }
    function X(O, L) {
      let V = "", E = !1;
      const C = te(O);
      return S.value.forEach((j) => {
        const Z = j[O]?.[L];
        if (typeof Z != "number") {
          E = !1;
          return;
        }
        const pe = 10 + (j.at - Y.value) / o.value * 580, be = 132 - Z / C * 112;
        V += (E ? " L" : " M") + pe.toFixed(1) + " " + be.toFixed(1), E = !0;
      }), V;
    }
    function Q(O, L) {
      if (!S.value.length) {
        s.value[L] = null;
        return;
      }
      const V = O.currentTarget.getBoundingClientRect(), E = Y.value + Math.max(0, Math.min(1, (O.clientX - V.left) / V.width)) * o.value;
      s.value[L] = S.value.reduce((C, j, Z) => Math.abs(j.at - E) < Math.abs(S.value[C].at - E) ? Z : C, 0);
    }
    function ne(O) {
      const L = s.value[O];
      return L == null ? null : S.value[L];
    }
    return (O, L) => (f(), h("section", If, [
      l("header", Of, [
        L[3] || (L[3] = l("h3", null, "Трафик сети", -1)),
        l("div", Mf, [
          L[2] || (L[2] = l("p", { class: "gw-hint" }, "Скорость и объём данных через LAN и WAN", -1)),
          D(l("select", {
            "onUpdate:modelValue": L[0] || (L[0] = (V) => o.value = V),
            "aria-label": "Период графиков"
          }, [...L[1] || (L[1] = [
            l("option", { value: 3600 }, "Час", -1),
            l("option", { value: 21600 }, "6 часов", -1),
            l("option", { value: 43200 }, "12 часов", -1),
            l("option", { value: 86400 }, "Сутки", -1)
          ])], 512), [
            [xe, o.value]
          ])
        ])
      ]),
      a.value ? (f(), h("p", Rf, y(a.value), 1)) : T("", !0),
      l("div", Df, [
        (f(), h(N, null, ie(t, (V) => l("article", {
          key: V,
          class: "gw-panel gw-traffic-card"
        }, [
          l("header", Nf, [
            l("h3", null, y(V.toUpperCase()), 1),
            l("span", {
              class: Ee(["gw-status", e.monitor.traffic?.[V]?.up ? "good" : "warn"])
            }, y(e.monitor.traffic?.[V]?.up ? "Подключён" : "Отключён"), 3)
          ]),
          l("div", Ff, [
            l("span", qf, "↓ " + y(b(e.monitor.traffic?.[V]?.rx_bps, !0)), 1),
            l("span", Hf, "↑ " + y(b(e.monitor.traffic?.[V]?.tx_bps, !0)), 1)
          ]),
          l("div", {
            class: "gw-traffic-plot",
            onPointermove: (E) => Q(E, V),
            onPointerleave: (E) => s.value[V] = null
          }, [
            (f(), h("svg", {
              viewBox: "0 0 600 148",
              preserveAspectRatio: "none",
              role: "img",
              "aria-label": "Скорость трафика " + V.toUpperCase()
            }, [
              (f(), h(N, null, ie([20, 76, 132], (E) => l("line", {
                key: E,
                x1: "10",
                y1: E,
                x2: "590",
                y2: E,
                class: "gw-chart-grid"
              }, null, 8, Wf)), 64)),
              l("path", {
                d: X(V, "rx_bps"),
                class: "gw-chart-rx"
              }, null, 8, Bf),
              l("path", {
                d: X(V, "tx_bps"),
                class: "gw-chart-tx"
              }, null, 8, Kf)
            ], 8, jf)),
            S.value.length < 2 ? (f(), h("div", Gf, "Накапливаем данные графика")) : T("", !0),
            ne(V) ? (f(), h("div", zf, y(new Date(ne(V).at * 1e3).toLocaleTimeString()) + " · ↓ " + y(b(ne(V)[V]?.rx_bps, !0)) + " · ↑ " + y(b(ne(V)[V]?.tx_bps, !0)), 1)) : T("", !0)
          ], 40, Lf),
          l("div", Jf, [
            l("div", null, [
              L[4] || (L[4] = l("span", null, "Получено", -1)),
              l("strong", null, y(b(e.monitor.traffic?.[V]?.rx_bytes)), 1)
            ]),
            l("div", null, [
              L[5] || (L[5] = l("span", null, "Передано", -1)),
              l("strong", null, y(b(e.monitor.traffic?.[V]?.tx_bytes)), 1)
            ])
          ])
        ])), 64))
      ]),
      l("p", Yf, "Графики: " + y(M(Y.value)) + " — " + y(M(A.value)) + ". Объём данных — с последней загрузки / сброса счётчиков", 1)
    ]));
  }
});
function Ne(e) {
  if (e == null || e === "" || typeof e == "boolean") return null;
  const t = Number(e);
  return Number.isFinite(t) ? t : null;
}
function as(e, t) {
  return !Number.isInteger(e) || e < 1 ? null : t === "2g" ? e <= 14 ? e === 14 ? 2484 : 2407 + e * 5 : null : t === "6g" ? e <= 233 ? e === 2 ? 5935 : 5950 + e * 5 : null : t === "5g" && e <= 196 ? (e >= 182 ? 4e3 : 5e3) + e * 5 : null;
}
function Zf(e, t) {
  const n = e?.frequencies?.length ? e.frequencies : t?.frequencies || [], o = Ne(t?.frequency) || Ne(n[0]?.mhz || n[0]?.frequency), s = t?.band || (o ? o < 3e3 ? "2g" : o >= 5925 ? "6g" : "5g" : null);
  return (e?.networks || []).map((i) => {
    let a = Ne(i.channel), u = Ne(i.frequency) || Ne(i.mhz);
    const c = ["2g", "5g", "6g"].includes(String(i.band)) ? String(i.band) : [2, 5, 6].includes(Number(i.band)) ? String(i.band) + "g" : s;
    if (!u && a) {
      const m = n.find((b) => {
        const S = Ne(b.mhz || b.frequency);
        return Ne(b.channel) === a && (!c || S != null && (S < 3e3 ? "2g" : S >= 5925 ? "6g" : "5g") === c);
      });
      u = Ne(m?.mhz || m?.frequency) || as(a, c);
    }
    !a && u && (a = u === 2484 ? 14 : u === 5935 ? 2 : (u - (u < 3e3 ? 2407 : u >= 5955 ? 5950 : u < 5e3 ? 4e3 : 5e3)) / 5);
    let g = Ne(i.signal);
    return g != null && g >= 2147483648 && g <= 4294967295 && (g -= 4294967296), { ...i, ssid: String(i.ssid ?? ""), bssid: String(i.bssid ?? ""), channel: a, frequency: u, signal: g };
  }).sort((i, a) => (a.signal ?? -200) - (i.signal ?? -200));
}
function jn(e, t) {
  return e > 1e3 ? e : as(e, t < 3e3 ? "2g" : t >= 5925 ? "6g" : "5g") || t;
}
function Qf(e) {
  const t = e.ht_operation || {}, n = String(t.secondary_channel_offset || "").toLowerCase();
  let o = n === "above" || n === "below" ? 40 : 20, s = e.frequency + (n === "above" ? 10 : n === "below" ? -10 : 0), i = !!e.ht_operation && Ne(t.channel_width) != null || ["above", "below"].includes(n);
  for (const a of ["vht_operation", "he_operation", "eht_operation"]) {
    const u = e[a], c = Ne(u?.channel_width);
    if (u && c === 20 && o === 20 && (i = !0), !u || c == null || c <= (a === "vht_operation" ? 40 : 20)) continue;
    const g = Ne(u.center_freq_1), m = Ne(u.center_freq_2);
    if (g != null) {
      if (c === 8080 && m != null)
        return [g, m].map((b) => ({ center: jn(b, e.frequency), width: 80, known: !0 }));
      if ([40, 80, 160, 320].includes(c)) {
        if (o = c, s = jn(g, e.frequency), i = !0, (c === 160 || c === 320) && m != null && m > 0) {
          const b = jn(m, e.frequency);
          (c === 320 || Math.abs(b - s) === 40) && (s = b);
        }
        if (c === 80 && m != null && m !== 0) {
          const b = jn(m, e.frequency), S = Math.abs(b - s);
          if (S === 40)
            o = 160, s = b;
          else if (S > 40) return [s, b].map((A) => ({ center: A, width: 80, known: !0 }));
        }
      }
    }
  }
  return [{ center: s, width: o, known: i }];
}
const ep = { class: "gw-channel-charts" }, tp = { class: "gw-spectrum-card" }, np = { class: "gw-spectrum-plot" }, lp = ["viewBox"], sp = ["y1", "x2", "y2"], op = ["y"], ip = ["x"], ap = { key: 1 }, rp = ["x", "y"], up = ["aria-label", "onMouseenter", "onFocus"], dp = ["x", "y", "width", "height", "fill"], cp = ["x1", "x2"], fp = ["opacity", "aria-label", "onMouseenter", "onFocus", "onClick", "onKeydown"], pp = ["d", "fill", "stroke", "stroke-width"], vp = ["x", "y"], gp = ["x"], hp = ["x"], mp = {
  key: 0,
  class: "gw-spectrum-empty"
}, bp = {
  class: "gw-spectrum-detail",
  role: "status",
  "aria-live": "polite"
}, yp = ["title"], wp = {
  class: "gw-spectrum-key",
  "aria-label": "Легенда графика"
}, _p = { key: 0 }, kp = { key: 2 }, $p = { class: "gw-spectrum-legend" }, Cp = ["aria-pressed", "onMouseenter", "onFocus", "onClick"], xp = /* @__PURE__ */ qe({
  __name: "WirelessChannels",
  props: {
    data: {},
    radio: {}
  },
  setup(e) {
    const t = e, n = /* @__PURE__ */ H(null), o = /* @__PURE__ */ H(null), s = /* @__PURE__ */ H(null), i = ke(() => o.value || n.value), a = window.matchMedia("(max-width:600px)"), u = /* @__PURE__ */ H(a.matches), c = () => {
      u.value = a.matches;
    };
    rt(() => a.addEventListener("change", c)), Rt(() => a.removeEventListener("change", c));
    const g = ke(() => u.value ? 520 : 900), m = 48, b = ke(() => g.value - 48), S = 26, A = 244, Y = (le) => typeof le == "number" && Number.isFinite(le);
    function M(le) {
      let P = 0;
      for (const d of le) P = P * 31 + d.charCodeAt(0) >>> 0;
      return `hsl(${(Math.imul(P, 2654435761) >>> 0) % 360} 65% 56%)`;
    }
    const te = ke(() => (t.data.networks || []).filter((le) => Y(le.frequency) && Y(le.signal)).map((le, P) => ({ ...le, id: (le.bssid || P) + ":" + le.frequency, color: M(le.bssid || le.ssid || String(P)), segments: Qf(le) })).sort((le, P) => le.signal - P.signal));
    st(() => t.data.networks, () => {
      n.value && !te.value.some((le) => le.id === n.value) && (n.value = null), o.value = null, s.value = null;
    });
    const X = ke(() => {
      const le = /* @__PURE__ */ new Map(), P = (d, r) => (le.has(d) || le.set(d, { frequency: d, channel: r, count: 0, busy_pct: null, noise: null }), le.get(d));
      for (const d of t.data.frequencies || []) {
        const r = Ne(d.mhz || d.frequency);
        r != null && P(r, d.channel);
      }
      for (const d of t.data.networks || []) Y(d.frequency) && P(d.frequency, d.channel).count++;
      for (const d of t.data.survey || []) {
        const r = Ne(d.frequency);
        if (r == null) continue;
        const p = r < 3e3 ? "2g" : r >= 5925 ? "6g" : "5g", _ = r === 2484 ? 14 : r === 5935 ? 2 : (r - (p === "2g" ? 2407 : p === "6g" ? 5950 : r < 5e3 ? 4e3 : 5e3)) / 5;
        Object.assign(P(r, _), d, { busy_pct: Ne(d.busy_pct) });
      }
      return [...le.values()].sort((d, r) => d.frequency - r.frequency);
    }), Q = ke(() => {
      const le = [...X.value.map((P) => P.frequency), ...te.value.flatMap((P) => P.segments.flatMap((d) => [d.center - d.width / 2, d.center + d.width / 2]))];
      return le.length ? [Math.min(...le) - 5, Math.max(...le) + 5] : [2400, 2490];
    }), ne = (le) => m + (le - Q.value[0]) / Math.max(1, Q.value[1] - Q.value[0]) * (b.value - m), O = (le) => A - (Math.max(-100, Math.min(-20, le)) + 100) / 80 * (A - S), L = (le) => A - Math.max(0, Math.min(100, le)) / 100 * (A - S), V = ke(() => X.value.filter((le, P) => P % Math.max(1, Math.ceil(X.value.length / (u.value ? 8 : 18))) === 0)), E = ke(() => X.value.some((le) => Y(le.busy_pct))), C = ke(() => Math.max(3, Math.min(20, (b.value - m) / Math.max(1, X.value.length) * 0.5))), j = ke(() => X.value.find((le) => le.in_use)?.frequency || Ne(t.radio?.frequency) || as(Number(t.radio?.runtime_channel || t.radio?.channel), t.radio?.band)), Z = ke(() => te.value.find((le) => le.id === i.value));
    function pe(le, P) {
      const d = ne(P.center - P.width / 2), r = ne(P.center + P.width / 2), p = O(le.signal), _ = Math.min((r - d) / 4, (b.value - m) * 5 / (Q.value[1] - Q.value[0]));
      return `M${d},${A} L${d + _},${p} L${r - _},${p} L${r},${A} Z`;
    }
    const be = (le) => le.segments.every((P) => P.known) ? le.segments.map((P) => P.width).join("+") + " МГц" : "ширина неизвестна (контур 20 МГц)", Ue = (le) => {
      n.value = n.value === le.id ? null : le.id;
    }, Oe = ke(() => Z.value ? `${Z.value.ssid || "Скрытая сеть"} · канал ${Z.value.channel} · ${Z.value.signal} dBm · ${be(Z.value)}` : s.value ? `Канал ${s.value.channel} · ${s.value.frequency} МГц · ${s.value.busy_pct == null ? "нет измерения занятости" : "занятость " + s.value.busy_pct + "%"}${s.value.noise == null ? "" : " · шум " + s.value.noise + " dBm"} · сетей: ${s.value.count}` : "Наведите на сеть или столбик. Нажмите на название сети, чтобы выделить её.");
    return (le, P) => (f(), h("section", ep, [
      l("article", tp, [
        l("header", null, [
          P[7] || (P[7] = l("h3", null, "Wi-Fi каналы и соседние сети", -1)),
          l("span", null, y(te.value.length) + " сетей на графике", 1)
        ]),
        l("div", np, [
          (f(), h("svg", {
            viewBox: `0 0 ${g.value} 282`,
            role: "img",
            "aria-label": "Каналы и уровень сигнала соседних Wi-Fi сетей",
            onMouseleave: P[4] || (P[4] = (d) => {
              o.value = null, s.value = null;
            })
          }, [
            (f(), h(N, null, ie([-100, -80, -60, -40, -20], (d) => l("g", { key: d }, [
              l("line", {
                x1: m,
                y1: O(d),
                x2: b.value,
                y2: O(d),
                class: "gw-spectrum-grid"
              }, null, 8, sp),
              l("text", {
                x: "40",
                y: O(d) + 4,
                "text-anchor": "end"
              }, y(d), 9, op)
            ])), 64)),
            P[8] || (P[8] = l("text", {
              x: "8",
              y: "14"
            }, "dBm", -1)),
            E.value ? (f(), h("text", {
              key: 0,
              x: g.value - 8,
              y: "14",
              "text-anchor": "end"
            }, "%", 8, ip)) : T("", !0),
            E.value ? (f(), h("g", ap, [
              (f(), h(N, null, ie([0, 25, 50, 75, 100], (d) => l("text", {
                key: d,
                x: b.value + 8,
                y: L(d) + 4
              }, y(d), 9, rp)), 64))
            ])) : T("", !0),
            (f(!0), h(N, null, ie(X.value.filter((d) => Y(d.busy_pct)), (d) => (f(), h("g", {
              key: d.frequency,
              class: "gw-spectrum-occupancy",
              tabindex: "0",
              role: "button",
              "aria-label": `Канал ${d.channel}, занятость ${d.busy_pct}%`,
              onMouseenter: (r) => {
                s.value = d, o.value = null;
              },
              onMouseleave: P[0] || (P[0] = (r) => s.value = null),
              onFocus: (r) => {
                s.value = d, o.value = null;
              },
              onBlur: P[1] || (P[1] = (r) => s.value = null)
            }, [
              l("rect", {
                x: ne(d.frequency) - C.value / 2,
                y: L(d.busy_pct),
                width: C.value,
                height: Math.max(1, A - L(d.busy_pct)),
                rx: "2",
                fill: d.busy_pct >= 70 ? "#e4b56c" : "#62c7a7",
                "fill-opacity": "0.45"
              }, null, 8, dp)
            ], 40, up))), 128)),
            j.value ? (f(), h("line", {
              key: 2,
              x1: ne(j.value),
              y1: S,
              x2: ne(j.value),
              y2: A,
              class: "gw-spectrum-current"
            }, null, 8, cp)) : T("", !0),
            (f(!0), h(N, null, ie(te.value, (d) => (f(), h("g", {
              key: d.id,
              opacity: i.value && i.value !== d.id ? 0.2 : 1,
              class: "gw-spectrum-peer",
              tabindex: "0",
              role: "button",
              "aria-label": `${d.ssid || "Скрытая сеть"}, канал ${d.channel}, ${d.signal} dBm`,
              onMouseenter: (r) => {
                o.value = d.id, s.value = null;
              },
              onMouseleave: P[2] || (P[2] = (r) => o.value = null),
              onFocus: (r) => {
                o.value = d.id, s.value = null;
              },
              onBlur: P[3] || (P[3] = (r) => o.value = null),
              onClick: (r) => Ue(d),
              onKeydown: [
                tl(lt((r) => Ue(d), ["prevent"]), ["enter"]),
                tl(lt((r) => Ue(d), ["prevent"]), ["space"])
              ]
            }, [
              (f(!0), h(N, null, ie(d.segments, (r, p) => (f(), h("path", {
                key: p,
                d: pe(d, r),
                fill: d.color,
                "fill-opacity": "0.13",
                stroke: d.color,
                "stroke-width": i.value === d.id ? 3 : 1.5
              }, null, 8, pp))), 128)),
              l("text", {
                x: ne(d.frequency),
                y: O(d.signal) - 5,
                "text-anchor": "middle",
                style: _n({ fill: d.color }),
                class: "gw-spectrum-ssid"
              }, y((d.ssid || "Скрытая сеть").slice(0, u.value ? 12 : 20)), 13, vp)
            ], 40, fp))), 128)),
            (f(!0), h(N, null, ie(V.value, (d) => (f(), h("g", {
              key: d.frequency
            }, [
              l("text", {
                x: ne(d.frequency),
                y: "263",
                "text-anchor": "middle"
              }, y(d.channel), 9, gp)
            ]))), 128)),
            l("text", {
              x: b.value,
              y: "279",
              "text-anchor": "end"
            }, "Канал", 8, hp)
          ], 40, lp)),
          te.value.length ? T("", !0) : (f(), h("p", mp, y(e.data.networks?.length ? "Сети найдены, но драйвер не сообщил канал или уровень сигнала." : "Соседние сети не найдены"), 1))
        ]),
        l("div", bp, [
          l("span", { title: Oe.value }, y(Oe.value), 9, yp)
        ]),
        l("div", wp, [
          P[13] || (P[13] = l("span", null, [
            l("i", { class: "gw-key-line" }),
            I("Контуры — сигнал сетей, шкала слева (dBm)")
          ], -1)),
          j.value ? (f(), h("span", _p, [...P[9] || (P[9] = [
            l("i", { class: "gw-key-current" }, null, -1),
            I("Пунктир — текущий канал", -1)
          ])])) : T("", !0),
          E.value ? (f(), h(N, { key: 1 }, [
            P[10] || (P[10] = l("span", null, [
              l("i", { class: "gw-key-busy" }),
              I("Зелёный — занятость менее 70%")
            ], -1)),
            P[11] || (P[11] = l("span", null, [
              l("i", { class: "gw-key-crowded" }),
              I("Жёлтый — занятость от 70%")
            ], -1)),
            P[12] || (P[12] = l("span", null, "Столбики — занятость эфира, шкала справа (%)", -1))
          ], 64)) : (f(), h("span", kp, "Измерения занятости от драйвера отсутствуют"))
        ]),
        l("div", $p, [
          (f(!0), h(N, null, ie(te.value, (d) => (f(), h("button", {
            key: d.id,
            class: Ee({ on: n.value === d.id }),
            "aria-pressed": n.value === d.id,
            onMouseenter: (r) => {
              o.value = d.id, s.value = null;
            },
            onMouseleave: P[5] || (P[5] = (r) => o.value = null),
            onFocus: (r) => {
              o.value = d.id, s.value = null;
            },
            onBlur: P[6] || (P[6] = (r) => o.value = null),
            onClick: (r) => Ue(d)
          }, [
            l("i", {
              style: _n({ background: d.color })
            }, null, 4),
            l("span", null, y(d.ssid || "Скрытая сеть"), 1),
            l("small", null, y(d.signal) + " dBm", 1)
          ], 42, Cp))), 128))
        ]),
        P[14] || (P[14] = l("p", { class: "gw-chart-note" }, "Высота контура — сила сигнала, ширина — полоса сети. Если ширина неизвестна, показан контур 20 МГц. Занятость измеряется драйвером; число сетей не заменяет это измерение.", -1))
      ])
    ]));
  }
}), Sp = { class: "gw-wireless" }, Tp = { class: "gw-section-header" }, Ep = ["disabled"], Pp = {
  key: 0,
  class: "gw-error",
  role: "alert"
}, Ap = {
  key: 1,
  class: "gw-hint"
}, Up = { class: "gw-section-header" }, Vp = { class: "gw-hint" }, Ip = { key: 0 }, Op = { class: "gw-actions" }, Mp = ["disabled", "onClick"], Rp = ["disabled", "onClick"], Dp = { class: "gw-table-wrap" }, Np = { class: "gw-check" }, Fp = { class: "gw-two" }, qp = ["value"], Hp = ["value", "disabled"], Lp = ["value"], jp = { class: "gw-two" }, Wp = ["value"], Bp = ["value"], Kp = ["value"], Gp = ["value"], zp = { class: "gw-rule-fields" }, Jp = { class: "gw-check" }, Yp = ["onUpdate:modelValue"], Xp = ["onUpdate:modelValue"], Zp = ["onUpdate:modelValue"], Qp = ["value"], ev = ["value"], tv = { key: 0 }, nv = ["onUpdate:modelValue", "required", "placeholder"], lv = {
  key: 1,
  class: "gw-hint"
}, sv = { class: "gw-wifi-networks" }, ov = ["onUpdate:modelValue", "value"], iv = { class: "gw-two" }, av = { class: "gw-check" }, rv = ["onUpdate:modelValue"], uv = { class: "gw-check" }, dv = ["onUpdate:modelValue"], cv = {
  key: 0,
  class: "gw-error",
  role: "alert"
}, fv = { class: "gw-actions" }, pv = ["disabled"], vv = ["disabled"], gv = { class: "gw-change-list" }, hv = { class: "gw-hint" }, mv = {
  key: 0,
  class: "gw-error",
  role: "alert"
}, bv = { class: "gw-actions" }, yv = ["disabled"], wv = ["disabled"], _v = { class: "gw-section-header" }, kv = { class: "gw-hint" }, $v = ["disabled"], Cv = {
  key: 0,
  class: "gw-error",
  role: "alert"
}, xv = {
  class: "gw-tabs",
  "aria-label": "Результаты сканирования"
}, Sv = { class: "gw-table-wrap" }, Tv = {
  key: 0,
  class: "gw-hint"
}, Ev = /* @__PURE__ */ qe({
  __name: "WirelessEditor",
  props: {
    node: {},
    bridge: {}
  },
  emits: ["changed"],
  setup(e, { emit: t }) {
    const n = e, o = t, s = /* @__PURE__ */ H({ radios: [], networks: [] }), i = /* @__PURE__ */ H(!1), a = /* @__PURE__ */ H(!1), u = /* @__PURE__ */ H(""), c = /* @__PURE__ */ H(null), g = /* @__PURE__ */ H(null), m = /* @__PURE__ */ H(!1), b = /* @__PURE__ */ H(null), S = /* @__PURE__ */ H(null), A = /* @__PURE__ */ H(""), Y = /* @__PURE__ */ H("channels");
    let M = !0;
    const te = () => "/api/gateways/" + encodeURIComponent(n.node.id), X = (r, p, _ = "POST") => n.bridge.request(te() + r, { method: _, headers: { "Content-Type": "application/json" }, body: JSON.stringify(p) }), Q = (r) => Array.isArray(r) ? r : r ? String(r).split(/\s+/) : [], ne = { none: "Без защиты", psk2: "WPA2-PSK", "psk2+ccmp": "WPA2-PSK (CCMP)", "psk-mixed": "WPA/WPA2-PSK", sae: "WPA3-SAE", "sae-mixed": "WPA2/WPA3", "sae+ccmp": "WPA3-SAE (CCMP)", "sae-mixed+ccmp": "WPA2/WPA3 (CCMP)" }, O = (r) => typeof r == "number" ? (r / 1e3).toFixed(3) + " ГГц" : "—", L = (r) => ({ "2g": "2,4 ГГц", "5g": "5 ГГц", "6g": "6 ГГц" })[r.band] || O(r.frequency), V = ke(() => Zf(S.value, b.value));
    function E(r) {
      return r.encryption?.enabled ? r.encryption.wpa?.length ? "WPA " + r.encryption.wpa.join("/") : "Защищена" : "Открытая";
    }
    async function C() {
      i.value = !0, u.value = "";
      try {
        const r = await n.bridge.request(te() + "/wireless");
        M && (s.value = r);
      } catch (r) {
        M && (u.value = r.message);
      } finally {
        M && (i.value = !1);
      }
    }
    function j(r) {
      u.value = "", c.value = {
        ...r,
        original: r,
        disabled: r.disabled === "1",
        channel: r.channel || "auto",
        country: r.country || "",
        txpower: r.txpower || "",
        htmode: r.htmode || "NOHT",
        interfaces: r.interfaces.map((p) => ({ ...p, original: p, disabled: p.disabled === "1", hidden: p.hidden === "1", isolate: p.isolate === "1", network: Q(p.network), ssid: p.ssid || "", encryption: p.encryption || "none", key: "" }))
      };
    }
    const Z = (r) => {
      try {
        return new Intl.DisplayNames(["ru"], { type: "region" }).of(r) || r;
      } catch {
        return r;
      }
    }, pe = (r) => {
      const p = /^(HT|VHT|HE|EHT)(\d+)$/.exec(r);
      return p ? `${p[2]} МГц · Wi-Fi ${{ HT: "4 (HT)", VHT: "5 (VHT)", HE: "6 (HE)", EHT: "7 (EHT)" }[p[1]]}` : "20 МГц · без расширений HT";
    };
    function be() {
      c.value = null, u.value = "";
    }
    function Ue(r, p, _, K = []) {
      const Ce = {};
      for (const J of _) {
        const ye = K.includes(J) ? r[J] ? "1" : "0" : r[J] === "" ? null : r[J], Xt = K.includes(J) ? p[J] === "1" ? "1" : "0" : J === "network" ? Q(p[J]) : p[J] ?? (J === "channel" ? "auto" : J === "encryption" ? "none" : J === "htmode" ? "NOHT" : null);
        JSON.stringify(ye) !== JSON.stringify(Xt) && (Ce[J] = ye);
      }
      return Ce;
    }
    async function Oe() {
      a.value = !0, u.value = "";
      try {
        const r = c.value, p = {
          config_hash: s.value.config_hash,
          radio: r.name,
          settings: Ue(r, r.original, ["disabled", "channel", "country", "txpower", "htmode"], ["disabled"]),
          interfaces: r.interfaces.map((_) => {
            const K = Ue(_, _.original, ["disabled", "ssid", "encryption", "hidden", "isolate", "network"], ["disabled", "hidden", "isolate"]);
            return _.key && _.encryption !== "none" && (K.key = _.key), { id: _.id, settings: K };
          }).filter((_) => Object.keys(_.settings).length)
        };
        g.value = await X("/network/plan", { action: "wireless", data: p });
        for (const _ of r.interfaces) _.key = "";
      } catch (r) {
        u.value = r.message;
      } finally {
        a.value = !1;
      }
    }
    function le() {
      const r = g.value?.plan_token;
      g.value = null, u.value = "", r && X("/operation-plans/" + encodeURIComponent(r), {}, "DELETE").catch((p) => {
        u.value = p.message;
      });
    }
    async function P() {
      a.value = !0, u.value = "";
      try {
        const r = await X("/router-operations", { plan_token: g.value.plan_token, confirmed: !0 });
        g.value = null, be(), n.bridge.task({ taskId: r.task_id, title: "Настройка Wi-Fi", cancellable: !1, onDone: async () => {
          await C(), o("changed");
        } });
      } catch (r) {
        u.value = r.message;
      } finally {
        a.value = !1;
      }
    }
    async function d(r) {
      if (!m.value) {
        b.value?.name !== r.name && (S.value = null), b.value = r, m.value = !0, A.value = "";
        try {
          const p = await X("/wireless/" + encodeURIComponent(r.name) + "/scan", {});
          M && (S.value = p);
        } catch (p) {
          M && (A.value = p.message);
        } finally {
          M && (m.value = !1);
        }
      }
    }
    return rt(() => {
      C();
    }), Rt(() => {
      M = !1, c.value = null;
    }), (r, p) => (f(), h(N, null, [
      l("section", Sp, [
        l("header", Tp, [
          p[9] || (p[9] = l("div", null, [
            l("h3", null, "Беспроводные сети"),
            l("p", { class: "gw-hint" }, "Радиомодули, сети Wi-Fi и обзор каналов")
          ], -1)),
          l("button", {
            disabled: i.value || a.value,
            onClick: C
          }, "Обновить", 8, Ep)
        ]),
        u.value && !c.value && !g.value ? (f(), h("p", Pp, y(u.value), 1)) : T("", !0),
        !s.value.radios.length && !u.value ? (f(), h("p", Ap, y(i.value ? "Получаем настройки Wi-Fi…" : "На шлюзе нет настроенных радиомодулей Wi-Fi."), 1)) : T("", !0),
        (f(!0), h(N, null, ie(s.value.radios, (_) => (f(), h("section", {
          key: _.name,
          class: "gw-radio"
        }, [
          l("header", Up, [
            l("div", null, [
              l("h3", null, y(_.name) + " · " + y(L(_)), 1),
              l("p", Vp, [
                I(y(_.up ? "Работает" : _.disabled === "1" ? "Выключен" : "Не активен") + " · Канал " + y(_.runtime_channel || _.channel || "Авто"), 1),
                _.htmode ? (f(), h("span", Ip, " · " + y(_.htmode), 1)) : T("", !0)
              ])
            ]),
            l("div", Op, [
              l("button", {
                disabled: a.value || m.value || !_.up,
                onClick: (K) => d(_)
              }, "Просмотр каналов", 8, Mp),
              l("button", {
                disabled: a.value || m.value,
                onClick: (K) => j(_)
              }, "Настроить Wi-Fi", 8, Rp)
            ])
          ]),
          l("div", Dp, [
            l("table", null, [
              p[10] || (p[10] = l("thead", null, [
                l("tr", null, [
                  l("th", null, "Сеть"),
                  l("th", null, "Режим"),
                  l("th", null, "Защита"),
                  l("th", null, "Подключение"),
                  l("th", null, "Состояние")
                ])
              ], -1)),
              l("tbody", null, [
                (f(!0), h(N, null, ie(_.interfaces, (K) => (f(), h("tr", {
                  key: K.id
                }, [
                  l("td", null, [
                    l("strong", null, y(K.ssid || K.id), 1),
                    l("small", null, y(K.ifname || K.id), 1)
                  ]),
                  l("td", null, y(K.mode === "ap" ? "Точка доступа" : K.mode === "sta" ? "Клиент" : K.mode), 1),
                  l("td", null, y(ne[K.encryption || "none"] || K.encryption), 1),
                  l("td", null, y(Q(K.network).join(", ") || "Без привязки"), 1),
                  l("td", null, [
                    l("span", {
                      class: Ee(["gw-status", _.up && K.disabled !== "1" ? "good" : "warn"])
                    }, y(K.disabled === "1" ? "Выключена" : _.up ? "Включена" : "Не активна"), 3)
                  ])
                ]))), 128))
              ])
            ])
          ])
        ]))), 128))
      ]),
      c.value && !g.value ? (f(), ge(Fe, {
        key: 0,
        title: "Настройки Wi-Fi · " + c.value.name,
        wide: !0,
        compact: !0,
        busy: a.value,
        onClose: be
      }, {
        default: Me(() => [
          l("form", {
            class: "gw-form",
            onSubmit: lt(Oe, ["prevent"])
          }, [
            l("label", Np, [
              D(l("input", {
                "onUpdate:modelValue": p[0] || (p[0] = (_) => c.value.disabled = _),
                type: "checkbox"
              }, null, 512), [
                [Be, c.value.disabled]
              ]),
              p[11] || (p[11] = I(" Выключить радиомодуль", -1))
            ]),
            l("div", Fp, [
              l("label", null, [
                p[13] || (p[13] = I("Канал", -1)),
                D(l("select", {
                  "onUpdate:modelValue": p[1] || (p[1] = (_) => c.value.channel = _)
                }, [
                  p[12] || (p[12] = l("option", { value: "auto" }, "Автоматически", -1)),
                  c.value.channel !== "auto" && !c.value.frequencies.some((_) => String(_.channel) === c.value.channel) ? (f(), h("option", {
                    key: 0,
                    value: c.value.channel
                  }, y(c.value.channel) + " (текущий)", 9, qp)) : T("", !0),
                  (f(!0), h(N, null, ie(c.value.frequencies, (_) => (f(), h("option", {
                    key: _.channel,
                    value: String(_.channel),
                    disabled: _.restricted
                  }, y(_.channel) + " · " + y(O(_.mhz || _.frequency)) + y(_.restricted ? " · Недоступен" : ""), 9, Hp))), 128))
                ], 512), [
                  [xe, c.value.channel]
                ])
              ]),
              l("label", null, [
                p[14] || (p[14] = I("Ширина канала", -1)),
                D(l("select", {
                  "onUpdate:modelValue": p[2] || (p[2] = (_) => c.value.htmode = _)
                }, [
                  (f(!0), h(N, null, ie([.../* @__PURE__ */ new Set([c.value.original.htmode || "NOHT", ...c.value.htmodes])], (_) => (f(), h("option", {
                    key: String(_),
                    value: _
                  }, y(pe(String(_))), 9, Lp))), 128))
                ], 512), [
                  [xe, c.value.htmode]
                ])
              ])
            ]),
            p[28] || (p[28] = l("p", { class: "gw-hint gw-mode-help" }, "HT — Wi-Fi 4, VHT — Wi-Fi 5, HE — Wi-Fi 6, EHT — Wi-Fi 7. Более широкая полоса может повысить скорость, но занимает больше эфира; на загруженных 2,4 ГГц обычно удобнее 20 МГц.", -1)),
            l("div", jp, [
              l("label", null, [
                p[17] || (p[17] = I("Страна", -1)),
                D(l("select", {
                  "onUpdate:modelValue": p[3] || (p[3] = (_) => c.value.country = _),
                  "aria-label": "Страна"
                }, [
                  p[15] || (p[15] = l("option", { value: "" }, "По умолчанию", -1)),
                  p[16] || (p[16] = l("option", { value: "00" }, "00 · Всемирный регуляторный домен", -1)),
                  c.value.country && c.value.country !== "00" && !c.value.countries?.some((_) => _.code === c.value.country) ? (f(), h("option", {
                    key: 0,
                    value: c.value.country,
                    disabled: ""
                  }, y(c.value.country) + " · текущее значение", 9, Wp)) : T("", !0),
                  (f(!0), h(N, null, ie(c.value.countries || [], (_) => (f(), h("option", {
                    key: _.code,
                    value: _.code
                  }, y(_.code) + " · " + y(Z(_.code)), 9, Bp))), 128))
                ], 512), [
                  [xe, c.value.country]
                ])
              ]),
              l("label", null, [
                p[19] || (p[19] = I("Мощность передатчика", -1)),
                D(l("select", {
                  "onUpdate:modelValue": p[4] || (p[4] = (_) => c.value.txpower = _),
                  "aria-label": "Мощность передатчика"
                }, [
                  p[18] || (p[18] = l("option", { value: "" }, "Автоматически", -1)),
                  c.value.txpower && !c.value.txpowers?.some((_) => String(_.dbm) === String(c.value.txpower)) ? (f(), h("option", {
                    key: 0,
                    value: c.value.txpower,
                    disabled: ""
                  }, y(c.value.txpower) + " dBm · текущее значение", 9, Kp)) : T("", !0),
                  (f(!0), h(N, null, ie(c.value.txpowers || [], (_) => (f(), h("option", {
                    key: _.dbm,
                    value: String(_.dbm)
                  }, y(_.dbm) + " dBm · " + y(_.mw) + " мВт", 9, Gp))), 128))
                ], 512), [
                  [xe, c.value.txpower]
                ]),
                p[20] || (p[20] = l("small", null, "Только значения драйвера; ограничения выбранной страны применяет OpenWrt.", -1))
              ])
            ]),
            p[29] || (p[29] = l("h3", null, "Сети на радиомодуле", -1)),
            (f(!0), h(N, null, ie(c.value.interfaces, (_) => (f(), h("details", {
              key: _.id,
              class: "gw-wifi-form",
              open: ""
            }, [
              l("summary", null, y(_.ssid || _.id) + " · " + y(_.mode === "ap" ? "Точка доступа" : _.mode === "sta" ? "Клиент" : _.mode), 1),
              l("div", zp, [
                l("label", Jp, [
                  D(l("input", {
                    "onUpdate:modelValue": (K) => _.disabled = K,
                    type: "checkbox"
                  }, null, 8, Yp), [
                    [Be, _.disabled]
                  ]),
                  p[21] || (p[21] = I(" Выключить эту сеть", -1))
                ]),
                l("label", null, [
                  p[22] || (p[22] = I("Имя сети (SSID)", -1)),
                  D(l("input", {
                    "onUpdate:modelValue": (K) => _.ssid = K,
                    required: "",
                    maxlength: "32"
                  }, null, 8, Xp), [
                    [oe, _.ssid]
                  ])
                ]),
                l("label", null, [
                  p[23] || (p[23] = I("Защита", -1)),
                  D(l("select", {
                    "onUpdate:modelValue": (K) => _.encryption = K
                  }, [
                    ne[_.original.encryption] ? T("", !0) : (f(), h("option", {
                      key: 0,
                      value: _.original.encryption
                    }, y(_.original.encryption) + " (текущая)", 9, Qp)),
                    (f(), h(N, null, ie(ne, (K, Ce) => l("option", {
                      key: Ce,
                      value: Ce
                    }, y(K), 9, ev)), 64))
                  ], 8, Zp), [
                    [xe, _.encryption]
                  ])
                ]),
                _.encryption !== "none" && ne[_.encryption] ? (f(), h("label", tv, [
                  p[24] || (p[24] = I("Пароль Wi-Fi", -1)),
                  D(l("input", {
                    "onUpdate:modelValue": (K) => _.key = K,
                    type: "password",
                    autocomplete: "new-password",
                    minlength: "8",
                    maxlength: "64",
                    required: !_.has_key,
                    placeholder: _.has_key ? "Оставьте пустым, чтобы сохранить текущий" : ""
                  }, null, 8, nv), [
                    [oe, _.key]
                  ])
                ])) : T("", !0),
                _.encryption === "none" ? (f(), h("p", lv, "Сеть будет открытой, сохранённый пароль будет удалён.")) : T("", !0),
                l("fieldset", sv, [
                  p[25] || (p[25] = l("legend", null, "Сетевые подключения", -1)),
                  (f(!0), h(N, null, ie(s.value.networks, (K) => (f(), h("label", {
                    key: K,
                    class: "gw-check"
                  }, [
                    D(l("input", {
                      "onUpdate:modelValue": (Ce) => _.network = Ce,
                      type: "checkbox",
                      value: K
                    }, null, 8, ov), [
                      [Be, _.network]
                    ]),
                    I(" " + y(K), 1)
                  ]))), 128))
                ]),
                l("div", iv, [
                  l("label", av, [
                    D(l("input", {
                      "onUpdate:modelValue": (K) => _.hidden = K,
                      type: "checkbox"
                    }, null, 8, rv), [
                      [Be, _.hidden]
                    ]),
                    p[26] || (p[26] = I(" Скрыть SSID", -1))
                  ]),
                  l("label", uv, [
                    D(l("input", {
                      "onUpdate:modelValue": (K) => _.isolate = K,
                      type: "checkbox"
                    }, null, 8, dv), [
                      [Be, _.isolate]
                    ]),
                    p[27] || (p[27] = I(" Изолировать клиентов", -1))
                  ])
                ])
              ])
            ]))), 128)),
            p[30] || (p[30] = l("p", { class: "gw-hint" }, "Применение временно отключит беспроводных клиентов. При потере доступа панель не подтвердит изменения, и роутер восстановит прежний Wi-Fi.", -1)),
            u.value ? (f(), h("p", cv, y(u.value), 1)) : T("", !0),
            l("div", fv, [
              l("button", {
                class: "gw-primary",
                disabled: a.value
              }, "Проверить изменения", 8, pv),
              l("button", {
                type: "button",
                disabled: a.value,
                onClick: be
              }, "Отмена", 8, vv)
            ])
          ], 32)
        ]),
        _: 1
      }, 8, ["title", "busy"])) : T("", !0),
      g.value ? (f(), ge(Fe, {
        key: 1,
        title: "Проверка изменений Wi-Fi",
        busy: a.value,
        onClose: le
      }, {
        default: Me(() => [
          l("ul", gv, [
            (f(!0), h(N, null, ie(g.value.summary, (_, K) => (f(), h("li", { key: K }, y(_), 1))), 128))
          ]),
          l("p", hv, "Откат при отсутствии подтверждения: " + y(g.value.rollback_seconds) + " секунд.", 1),
          u.value ? (f(), h("p", mv, y(u.value), 1)) : T("", !0),
          l("div", bv, [
            l("button", {
              class: "gw-primary",
              disabled: a.value,
              onClick: P
            }, "Да, применить", 8, yv),
            l("button", {
              disabled: a.value,
              onClick: le
            }, "Назад", 8, wv)
          ])
        ]),
        _: 1
      }, 8, ["busy"])) : T("", !0),
      b.value ? (f(), ge(Fe, {
        key: 2,
        title: "Обзор каналов · " + b.value.name,
        wide: !0,
        busy: m.value,
        onClose: p[8] || (p[8] = (_) => b.value = null)
      }, {
        default: Me(() => [
          l("header", _v, [
            l("p", kv, y(m.value ? "Сканируем эфир…" : S.value ? "Последнее сканирование: " + new Date(S.value.scanned_at * 1e3).toLocaleTimeString("ru-RU") : A.value ? "Сканирование не выполнено" : "Ожидание запуска сканирования"), 1),
            l("button", {
              disabled: m.value,
              onClick: p[5] || (p[5] = (_) => d(b.value))
            }, y(m.value ? "Сканирование…" : "Сканировать снова"), 9, $v)
          ]),
          p[32] || (p[32] = l("p", { class: "gw-hint" }, "Во время сканирования Wi-Fi может ненадолго замедлиться. Список показывает сети, видимые этому роутеру.", -1)),
          A.value ? (f(), h("p", Cv, y(A.value), 1)) : T("", !0),
          S.value ? (f(), h(N, { key: 1 }, [
            l("nav", xv, [
              l("button", {
                class: Ee({ on: Y.value === "channels" }),
                onClick: p[6] || (p[6] = (_) => Y.value = "channels")
              }, "Каналы", 2),
              l("button", {
                class: Ee({ on: Y.value === "networks" }),
                onClick: p[7] || (p[7] = (_) => Y.value = "networks")
              }, "Соседние сети (" + y(V.value.length) + ")", 3)
            ]),
            Y.value === "channels" ? (f(), ge(xp, {
              key: 0,
              data: { ...S.value, networks: V.value },
              radio: b.value
            }, null, 8, ["data", "radio"])) : (f(), h(N, { key: 1 }, [
              l("div", Sv, [
                l("table", null, [
                  p[31] || (p[31] = l("thead", null, [
                    l("tr", null, [
                      l("th", null, "Сеть"),
                      l("th", null, "Канал"),
                      l("th", null, "Частота"),
                      l("th", null, "Сигнал"),
                      l("th", null, "Защита")
                    ])
                  ], -1)),
                  l("tbody", null, [
                    (f(!0), h(N, null, ie(V.value, (_) => (f(), h("tr", {
                      key: _.bssid + ":" + _.frequency
                    }, [
                      l("td", null, [
                        I(y(_.ssid || "Скрытая сеть"), 1),
                        l("small", null, y(_.bssid), 1)
                      ]),
                      l("td", null, y(_.channel), 1),
                      l("td", null, y(O(_.frequency)), 1),
                      l("td", null, y(_.signal == null ? "—" : _.signal + " dBm"), 1),
                      l("td", null, y(E(_)), 1)
                    ]))), 128))
                  ])
                ])
              ]),
              V.value.length ? T("", !0) : (f(), h("p", Tv, "Соседние сети не найдены."))
            ], 64))
          ], 64)) : T("", !0)
        ]),
        _: 1
      }, 8, ["title", "busy"])) : T("", !0)
    ], 64));
  }
}), Pv = { class: "gw-section-header" }, Av = { class: "gw-actions" }, Uv = ["disabled"], Vv = ["disabled"], Iv = {
  class: "gw-hint",
  "aria-live": "polite"
}, Ov = {
  key: 0,
  class: "gw-hint",
  role: "status"
}, Mv = { class: "gw-service-list" }, Rv = { class: "gw-service-info" }, Dv = { key: 1 }, Nv = ["title"], Fv = ["title"], qv = {
  key: 0,
  class: "gw-next-version"
}, Hv = { class: "gw-service-state" }, Lv = { class: "gw-service-actions" }, jv = ["disabled", "onClick"], Wv = ["disabled", "onClick"], Bv = ["disabled", "title", "onClick"], Kv = ["disabled", "onClick"], Gv = ["disabled", "onClick"], zv = ["disabled", "onClick"], Jv = ["disabled", "onClick"], Yv = {
  key: 0,
  class: "gw-hint"
}, Xv = { class: "gw-version-field" }, Zv = ["disabled"], Qv = {
  key: 0,
  class: "gw-error",
  role: "alert"
}, eg = { class: "gw-actions" }, tg = ["disabled"], ng = ["disabled"], lg = /* @__PURE__ */ qe({
  __name: "GatewayServices",
  props: {
    node: {},
    bridge: {},
    busy: { type: Boolean },
    revision: {},
    updating: {}
  },
  emits: ["catalog", "firewallRestart", "settings", "help", "openAdguard", "action", "update", "pending", "resume", "webAccess"],
  setup(e, { emit: t }) {
    const n = e, o = t, s = /* @__PURE__ */ H({}), i = /* @__PURE__ */ H(!1), a = /* @__PURE__ */ H(""), u = /* @__PURE__ */ H(null), c = ke(() => n.node.monitor.services || []), g = { dnsmasq: "Локальный DNS и DHCP", firewall: "Защита роутера и правила трафика", podkop: "Выборочная маршрутизация через sing-box", ssclash: "Clash / Mihomo и правила маршрутизации", adguardhome: "Фильтрация DNS и блокировка рекламы" }, m = /* @__PURE__ */ H(null), b = /* @__PURE__ */ H(!1), S = /* @__PURE__ */ H("");
    function A(V) {
      const E = s.value[V.id]?.fingerprint;
      E && (S.value = "", m.value = { id: V.id, name: V.name, fingerprint: E, version: "" });
    }
    async function Y() {
      const V = m.value, E = n.node.id;
      if (!(!V || b.value)) {
        b.value = !0, S.value = "";
        try {
          await n.bridge.request("/api/gateways/" + encodeURIComponent(E) + "/services/" + V.id + "/version", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ version: V.version, fingerprint: V.fingerprint, confirmed: !0 }) }), m.value = null, await L();
        } catch (C) {
          S.value = C instanceof Error ? C.message : String(C);
        } finally {
          b.value = !1;
        }
      }
    }
    let M = 0;
    Rt(() => {
      M++;
    });
    function te(V) {
      return n.updating?.[V] || (s.value[V]?.stage ? { stage: s.value[V].stage, task_id: s.value[V]?.task_id || void 0 } : void 0);
    }
    function X(V) {
      return te(V)?.stage === "prepare" ? "Подготовка…" : te(V)?.stage === "apply" ? "Обновление…" : te(V)?.stage === "review" ? s.value[V]?.plan ? "Продолжить обновление" : "Ожидает подтверждения" : "Обновить до " + s.value[V]?.latest;
    }
    function Q(V) {
      return n.busy || i.value || !!a.value || !!te(V) && !(te(V)?.stage === "review" && s.value[V]?.plan);
    }
    function ne(V) {
      const E = s.value[V]?.plan;
      te(V)?.stage === "review" && E ? o("resume", E) : o("update", V);
    }
    function O(V) {
      if (["dnsmasq", "firewall"].includes(V)) return "";
      if (i.value) return "Проверяю обновления…";
      if (a.value) return "Не удалось проверить обновления";
      const E = s.value[V];
      return E?.available ? "Есть обновление до " + E.latest : E?.status === "current_cached" ? "Актуальная среди сохранённых версий" : E?.warning ? "Проверка не завершена" : E?.status === "newer" ? "Установленная версия новее доступного релиза" : E?.current && E.latest ? "Актуальная версия" : "Обновления не проверены";
    }
    async function L(V = !1) {
      const E = ++M;
      V || (i.value = !0), a.value = "";
      try {
        const C = await n.bridge.request("/api/gateways/" + encodeURIComponent(n.node.id) + "/service-updates");
        if (E === M) {
          s.value = C.services || {}, u.value = C.checked_at || Math.floor(Date.now() / 1e3);
          for (const [j, Z] of Object.entries(s.value)) Z.task_id && Z.stage && o("pending", j, { stage: Z.stage, task_id: Z.task_id });
        }
      } catch (C) {
        E === M && (a.value = C instanceof Error ? C.message : String(C));
      } finally {
        E === M && (i.value = !1);
      }
    }
    return st(() => n.revision, () => {
      L(!0);
    }), st(() => n.node.id, () => {
      s.value = {}, u.value = null, m.value = null, L();
    }, { immediate: !0 }), (V, E) => (f(), h(N, null, [
      l("header", Pv, [
        E[6] || (E[6] = l("div", null, [
          l("h3", null, "Сервисы из GitHub"),
          l("p", { class: "gw-hint" }, "Podkop, SSClash-Go и AdGuard Home · версии и резервные комплекты")
        ], -1)),
        l("div", Av, [
          l("button", {
            disabled: e.busy || i.value,
            onClick: E[0] || (E[0] = (C) => L())
          }, y(i.value ? "Проверяю…" : "Проверить обновления"), 9, Uv),
          l("button", {
            class: "gw-primary",
            disabled: e.busy,
            onClick: E[1] || (E[1] = (C) => o("catalog"))
          }, "Установить сервис", 8, Vv)
        ])
      ]),
      l("p", Iv, y(i.value ? "Проверяю установленные версии и совместимые официальные релизы…" : a.value ? "Проверка не завершена." : u.value ? "Проверено в " + new Date(u.value * 1e3).toLocaleTimeString("ru-RU") : "Версии ещё не проверены."), 1),
      a.value ? (f(), h("p", Ov, y(a.value), 1)) : T("", !0),
      E[9] || (E[9] = l("div", {
        class: "gw-service-columns",
        "aria-hidden": "true"
      }, [
        l("span", null, "Сервис"),
        l("span", null, "Версия"),
        l("span", null, "Статус"),
        l("span", null, "Действия")
      ], -1)),
      l("div", Mv, [
        (f(!0), h(N, null, ie(c.value, (C) => (f(), h("article", {
          key: C.id,
          class: "gw-service-row"
        }, [
          l("div", Rv, [
            l("h3", null, y(C.name), 1),
            ["podkop", "ssclash", "adguardhome"].includes(C.id) ? (f(), ge(is, {
              key: 0,
              id: C.id,
              compact: "",
              help: C.id === "adguardhome",
              onHelp: E[2] || (E[2] = (j) => o("help"))
            }, null, 8, ["id", "help"])) : (f(), h("p", Dv, y(g[C.id]), 1)),
            s.value[C.id]?.warning ? (f(), h("p", {
              key: 2,
              class: "gw-hint gw-version-warning",
              role: "status",
              title: s.value[C.id]?.warning || void 0
            }, y(s.value[C.id]?.warning), 9, Nv)) : T("", !0)
          ]),
          l("div", {
            class: "gw-service-versions",
            title: (s.value[C.id]?.installed_version || s.value[C.id]?.current || C.version || "—") + (s.value[C.id]?.available ? " → " + s.value[C.id]?.latest : "")
          }, [
            l("span", null, y(s.value[C.id]?.installed_version || s.value[C.id]?.current || C.version || "—"), 1),
            s.value[C.id]?.available ? (f(), h("span", qv, "→ " + y(s.value[C.id]?.latest), 1)) : T("", !0)
          ], 8, Fv),
          l("div", Hv, [
            l("span", {
              class: Ee(["gw-status", C.running ? "good" : "warn"])
            }, y(C.running ? "Работает" : "Остановлена"), 3),
            O(C.id) ? (f(), h("span", {
              key: 0,
              class: Ee(["gw-status", i.value || a.value || s.value[C.id]?.warning || s.value[C.id]?.available ? "warn" : "good"])
            }, y(O(C.id)), 3)) : T("", !0)
          ]),
          l("div", Lv, [
            ["ssclash", "adguardhome"].includes(C.id) && !s.value[C.id]?.current && s.value[C.id]?.fingerprint ? (f(), h("button", {
              key: 0,
              disabled: e.busy || i.value || b.value,
              onClick: (j) => A(C)
            }, "Указать установленную версию", 8, jv)) : T("", !0),
            l("button", {
              disabled: e.busy,
              onClick: (j) => C.id === "adguardhome" ? o("openAdguard") : o("settings", C)
            }, y(C.id === "adguardhome" ? "Открыть AdGuard Home" : "Настроить" + (["podkop", "ssclash"].includes(C.id) ? " ↗" : "")), 9, Wv),
            e.node.monitor.capabilities?.controls?.available ? (f(), h(N, { key: 1 }, [
              s.value[C.id]?.available || te(C.id) ? (f(), h("button", {
                key: 0,
                class: "gw-update-button",
                disabled: Q(C.id),
                title: "Обновить до " + s.value[C.id]?.latest,
                onClick: (j) => ne(C.id)
              }, y(X(C.id)), 9, Bv)) : T("", !0),
              C.id === "ssclash" && C.managed ? (f(), h("button", {
                key: 1,
                disabled: e.busy || !!te(C.id),
                onClick: (j) => o("webAccess", C.web_scope === "wan" ? "lan" : "wan")
              }, y(C.web_scope === "wan" ? "Только LAN" : "Доступ из WAN"), 9, Kv)) : T("", !0),
              C.running || C.id === "firewall" ? (f(), h("button", {
                key: 2,
                disabled: e.busy || !!te(C.id),
                onClick: (j) => C.id === "firewall" ? o("firewallRestart") : o("action", C.id, "restart")
              }, "Перезапустить", 8, Gv)) : T("", !0),
              ["dnsmasq", "firewall"].includes(C.id) ? T("", !0) : (f(), h("button", {
                key: 3,
                disabled: e.busy || !!te(C.id),
                onClick: (j) => o("action", C.id, C.running ? "stop" : "start")
              }, y(C.running ? "Остановить" : "Запустить"), 9, zv)),
              ["podkop", "ssclash"].includes(C.id) || C.id === "adguardhome" && C.managed ? (f(), h("button", {
                key: 4,
                class: "gw-danger",
                disabled: e.busy || !!te(C.id),
                onClick: (j) => o("action", C.id, "remove")
              }, "Удалить", 8, Jv)) : T("", !0)
            ], 64)) : T("", !0)
          ])
        ]))), 128)),
        c.value.length ? T("", !0) : (f(), h("p", Yv, "Установленные сервисы пока не определены."))
      ]),
      m.value ? (f(), ge(Fe, {
        key: 1,
        title: "Установленная версия · " + m.value.name,
        onClose: E[5] || (E[5] = (C) => !b.value && (m.value = null))
      }, {
        default: Me(() => [
          E[8] || (E[8] = l("p", { class: "gw-hint" }, "Укажите версию, которая сейчас показана в интерфейсе сервиса. Сохраняется только запись о версии; сервис и настройки не меняются.", -1)),
          l("label", Xv, [
            E[7] || (E[7] = I("Установленная версия", -1)),
            D(l("input", {
              "onUpdate:modelValue": E[3] || (E[3] = (C) => m.value.version = C),
              placeholder: "Например, 7.7.4",
              inputmode: "decimal",
              disabled: b.value
            }, null, 8, Zv), [
              [
                oe,
                m.value.version,
                void 0,
                { trim: !0 }
              ]
            ])
          ]),
          S.value ? (f(), h("p", Qv, y(S.value), 1)) : T("", !0),
          l("div", eg, [
            l("button", {
              class: "gw-primary",
              disabled: b.value || !/^v?[0-9]+[.][0-9]+[.][0-9]+$/.test(m.value.version),
              onClick: Y
            }, y(b.value ? "Сохраняю…" : "Подтвердить версию"), 9, tg),
            l("button", {
              disabled: b.value,
              onClick: E[4] || (E[4] = (C) => m.value = null)
            }, "Отмена", 8, ng)
          ])
        ]),
        _: 1
      }, 8, ["title"])) : T("", !0)
    ], 64));
  }
}), sg = { class: "gw-header" }, og = { class: "gw-eyebrow" }, ig = { class: "gw-title-with-icon" }, ag = { class: "gw-actions" }, rg = ["disabled"], ug = ["href"], dg = /* @__PURE__ */ qe({
  __name: "GatewayHeader",
  props: {
    node: {},
    busy: { type: Boolean }
  },
  emits: ["console"],
  setup(e, { emit: t }) {
    const n = t;
    return (o, s) => (f(), h("header", sg, [
      l("div", null, [
        l("span", og, "OPENWRT " + y(e.node.monitor.board?.release?.version), 1),
        l("h2", ig, [
          s[1] || (s[1] = l("span", {
            class: "gw-router-icon",
            "aria-hidden": "true"
          }, [
            l("svg", {
              viewBox: "0 0 24 24",
              width: "20",
              height: "20"
            }, [
              l("rect", {
                x: "3",
                y: "11",
                width: "18",
                height: "9",
                rx: "2"
              }),
              l("path", { d: "M7 11V5m10 6V5M5 6a10 10 0 0 1 14 0M8 8a6 6 0 0 1 8 0M7 16h.01M11 16h.01" })
            ])
          ], -1)),
          I(y(e.node.name), 1)
        ]),
        l("p", null, y(e.node.monitor.board?.model || e.node.host) + " · " + y(e.node.host), 1)
      ]),
      l("div", ag, [
        l("button", {
          "aria-label": "Открыть консоль шлюза",
          disabled: e.busy,
          onClick: s[0] || (s[0] = (i) => n("console"))
        }, "Консоль", 8, rg),
        l("a", {
          href: e.node.luci_url,
          target: "_blank",
          rel: "noopener noreferrer"
        }, "LuCI ↗", 8, ug)
      ])
    ]));
  }
}), cg = { class: "gw-backups" }, fg = { class: "gw-section-header" }, pg = ["disabled"], vg = {
  key: 0,
  class: "gw-notice"
}, gg = {
  key: 1,
  class: "gw-error",
  role: "alert"
}, hg = {
  key: 2,
  class: "gw-notice"
}, mg = { class: "gw-backup-restore" }, bg = { class: "gw-section-header" }, yg = { class: "gw-backup-upload" }, wg = ["disabled"], _g = ["disabled"], kg = { class: "gw-backup-picker" }, $g = ["disabled"], Cg = {
  key: 0,
  value: ""
}, xg = ["value"], Sg = ["disabled"], Tg = {
  key: 3,
  class: "gw-notice gw-backup-reboot"
}, Eg = { class: "gw-actions" }, Pg = ["disabled"], Ag = ["href"], Ug = ["href"], Vg = {
  key: 0,
  class: "gw-error",
  role: "alert"
}, Ig = { key: 1 }, Og = { class: "gw-change-list" }, Mg = { class: "gw-actions" }, Rg = ["disabled"], Dg = ["disabled"], Ng = /* @__PURE__ */ qe({
  __name: "GatewayBackups",
  props: {
    node: {},
    bridge: {}
  },
  setup(e) {
    const t = e, n = /* @__PURE__ */ H([]), o = /* @__PURE__ */ H(""), s = /* @__PURE__ */ H(!1), i = /* @__PURE__ */ H(!1), a = /* @__PURE__ */ H(""), u = /* @__PURE__ */ H(null), c = /* @__PURE__ */ H(null), g = /* @__PURE__ */ H(!1), m = /* @__PURE__ */ H(null);
    let b = !0, S;
    const A = "/api/gateways/" + encodeURIComponent(t.node.id) + "/backups", Y = (C, j) => t.bridge.request(C, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(j) }), M = (C) => C < 1024 * 1024 ? Math.round(C / 1024) + " КБ" : (C / 1024 / 1024).toFixed(1) + " МБ";
    function te() {
      m.value?.click();
    }
    async function X() {
      try {
        const C = await t.bridge.request(A);
        if (!b) return;
        n.value = C.items, i.value = C.available, u.value = C.task?.id || null, g.value = C.reboot_required === !0, n.value.some((j) => j.id === o.value) || (o.value = n.value[0]?.id || ""), u.value && (S = setTimeout(X, 2e3));
      } catch (C) {
        b && (a.value = C instanceof Error ? C.message : String(C));
      }
    }
    function Q(C, j, Z) {
      u.value = C, t.bridge.task({ taskId: C, title: j, cancellable: !1, onDone: async () => {
        if (b) {
          try {
            const pe = await t.bridge.request("/api/tasks/" + encodeURIComponent(C));
            pe.result?.success === !1 && (a.value = pe.result.error || "Операция завершилась с ошибкой");
          } catch (pe) {
            a.value = pe instanceof Error ? pe.message : String(pe);
          }
          clearTimeout(S), await X();
        }
      } }), clearTimeout(S), S = setTimeout(X, 2e3);
    }
    async function ne() {
      s.value = !0, a.value = "";
      try {
        const C = await Y(A + "/create", {});
        b && Q(C.task_id, "Резервная копия настроек OpenWrt", "create");
      } catch (C) {
        a.value = C instanceof Error ? C.message : String(C);
      } finally {
        s.value = !1;
      }
    }
    async function O(C) {
      const j = C.target, Z = j.files?.[0];
      if (Z) {
        s.value = !0, a.value = "";
        try {
          const pe = new FormData();
          pe.append("file", Z);
          const be = await t.bridge.request(A + "/upload", { method: "POST", body: pe });
          if (!b) return;
          await X(), o.value = be.archive.id;
        } catch (pe) {
          a.value = pe instanceof Error ? pe.message : String(pe);
        } finally {
          j.value = "", s.value = !1;
        }
      }
    }
    async function L(C) {
      s.value = !0, a.value = "";
      try {
        const j = await Y(A + "/plan", { action: C, archive_id: C === "restore" ? o.value : null });
        b ? c.value = j : t.bridge.request(A + "/plans/" + encodeURIComponent(j.plan_token), { method: "DELETE" }).catch(() => {
        });
      } catch (j) {
        a.value = j instanceof Error ? j.message : String(j);
      } finally {
        s.value = !1;
      }
    }
    async function V() {
      if (c.value) {
        s.value = !0;
        try {
          await t.bridge.request(A + "/plans/" + encodeURIComponent(c.value.plan_token), { method: "DELETE" }), c.value = null;
        } catch (C) {
          a.value = C instanceof Error ? C.message : String(C);
        } finally {
          s.value = !1;
        }
      }
    }
    async function E() {
      if (!c.value) return;
      s.value = !0, a.value = "";
      const C = c.value;
      try {
        const j = await Y(A + "/apply", { plan_token: C.plan_token, confirmed: !0 });
        b && (c.value = null, Q(j.task_id, C.action === "restore" ? "Восстановление настроек OpenWrt" : "Перезагрузка шлюза", C.action));
      } catch (j) {
        a.value = j instanceof Error ? j.message : String(j);
      } finally {
        s.value = !1;
      }
    }
    return rt(X), Po(() => {
      b = !1, clearTimeout(S), c.value && t.bridge.request(A + "/plans/" + encodeURIComponent(c.value.plan_token), { method: "DELETE" }).catch(() => {
      });
    }), (C, j) => (f(), h(N, null, [
      l("section", cg, [
        l("header", fg, [
          j[4] || (j[4] = l("div", null, [
            l("h3", null, "Резервные копии"),
            l("p", { class: "gw-hint" }, "Штатный архив настроек OpenWrt. Прошивка и пакеты в копию не входят.")
          ], -1)),
          l("button", {
            class: "gw-primary",
            disabled: s.value || !!u.value || !i.value,
            onClick: ne
          }, "Создать копию на панели", 8, pg)
        ]),
        i.value ? T("", !0) : (f(), h("p", vg, "Для создания и восстановления нужен управляемый API Bot4VPS. Настройте его во вкладке «Доступ».")),
        a.value && !c.value ? (f(), h("p", gg, y(a.value), 1)) : T("", !0),
        u.value ? (f(), h("p", hg, [
          j[5] || (j[5] = I("Выполняется операция шлюза. ", -1)),
          l("button", {
            onClick: j[0] || (j[0] = (Z) => Q(u.value, "Операция резервного копирования"))
          }, "Показать задачу")
        ])) : T("", !0),
        l("div", mg, [
          l("header", bg, [
            j[6] || (j[6] = l("div", null, [
              l("h3", null, "Восстановление"),
              l("p", { class: "gw-hint" }, "Выберите любую копию на панели или загрузите свой архив из LuCI.")
            ], -1)),
            l("div", yg, [
              l("button", {
                disabled: s.value || !!u.value,
                onClick: te
              }, "Загрузить свой архив", 8, wg),
              l("input", {
                ref_key: "uploadInput",
                ref: m,
                type: "file",
                accept: ".tar.gz,.tgz",
                hidden: "",
                disabled: s.value || !!u.value,
                onChange: O
              }, null, 40, _g)
            ])
          ]),
          l("div", kg, [
            l("label", null, [
              j[7] || (j[7] = I("Архив на панели", -1)),
              D(l("select", {
                "onUpdate:modelValue": j[1] || (j[1] = (Z) => o.value = Z),
                disabled: s.value || !!u.value
              }, [
                n.value.length ? T("", !0) : (f(), h("option", Cg, "Сохранённых копий пока нет")),
                (f(!0), h(N, null, ie(n.value, (Z) => (f(), h("option", {
                  key: Z.id,
                  value: Z.id
                }, y(Z.filename) + " · " + y(M(Z.size)), 9, xg))), 128))
              ], 8, $g), [
                [xe, o.value]
              ])
            ]),
            l("button", {
              disabled: s.value || !!u.value || !o.value || !i.value,
              onClick: j[2] || (j[2] = (Z) => L("restore"))
            }, "Восстановить", 8, Sg)
          ]),
          j[8] || (j[8] = l("p", { class: "gw-hint" }, "Копии общие для всех шлюзов. Архив содержит настройки и может содержать пароли и ключи. Скачать или удалить копии можно в «Файлы → Копии шлюзов».", -1))
        ]),
        g.value ? (f(), h("div", Tg, [
          j[9] || (j[9] = l("p", null, "Файлы настроек восстановлены. Для применения требуется перезагрузка.", -1)),
          l("div", Eg, [
            l("button", {
              disabled: s.value || !!u.value,
              onClick: j[3] || (j[3] = (Z) => L("reboot"))
            }, "Перезагрузить и применить", 8, Pg),
            l("a", {
              href: e.node.luci_url,
              target: "_blank",
              rel: "noopener noreferrer"
            }, "Открыть LuCI ↗", 8, Ag)
          ])
        ])) : (f(), h("a", {
          key: 4,
          class: "gw-hint",
          href: e.node.luci_url,
          target: "_blank",
          rel: "noopener noreferrer"
        }, "Открыть LuCI ↗", 8, Ug))
      ]),
      c.value ? (f(), ge(Fe, {
        key: 0,
        title: c.value.action === "restore" ? "План восстановления" : "Подтверждение перезагрузки",
        busy: s.value,
        onClose: V
      }, {
        default: Me(() => [
          a.value ? (f(), h("p", Vg, y(a.value), 1)) : T("", !0),
          c.value.action === "restore" ? (f(), h("p", Ig, [
            l("strong", null, y(c.value.filename), 1),
            I(" · " + y(c.value.files) + " файлов", 1)
          ])) : T("", !0),
          l("ul", Og, [
            (f(!0), h(N, null, ie(c.value.warnings, (Z) => (f(), h("li", { key: Z }, y(Z), 1))), 128))
          ]),
          l("div", Mg, [
            l("button", {
              class: "gw-primary",
              disabled: s.value,
              onClick: E
            }, y(c.value.action === "restore" ? "Да, восстановить настройки" : "Да, перезагрузить шлюз"), 9, Rg),
            l("button", {
              disabled: s.value,
              onClick: V
            }, "Отмена", 8, Dg)
          ])
        ]),
        _: 1
      }, 8, ["title", "busy"])) : T("", !0)
    ], 64));
  }
}), Fg = {
  key: 0,
  class: "gw-error",
  role: "alert"
}, qg = { key: 1 }, Hg = { key: 0 }, Lg = {
  key: 4,
  class: "gw-notice"
}, jg = { key: 5 }, Wg = { key: 6 }, Bg = { class: "gw-actions" }, Kg = ["disabled"], Gg = ["disabled"], zg = /* @__PURE__ */ qe({
  __name: "OperationPlan",
  props: {
    operation: {},
    busy: { type: Boolean },
    error: {}
  },
  emits: ["apply", "cancel"],
  setup(e, { emit: t }) {
    const n = t, o = { install: "Установка", update: "Обновление", web_access: "Доступ веб-панели", remove: "Удаление", start: "Запуск", stop: "Остановка", restart: "Перезапуск" };
    return (s, i) => (f(), ge(Fe, {
      title: "План операции",
      busy: e.busy,
      onClose: i[2] || (i[2] = (a) => n("cancel"))
    }, {
      default: Me(() => [
        e.error ? (f(), h("p", Fg, y(e.error), 1)) : T("", !0),
        l("h2", null, y(o[e.operation.action]) + " " + y(e.operation.service) + " " + y(e.operation.version || ""), 1),
        e.operation.network_check ? (f(), h("p", qg, "После действия панель проверит API и состояние службы. Если подтверждение не придёт, будет выполнено восстановление.")) : T("", !0),
        e.operation.action === "remove" ? (f(), h(N, { key: 2 }, [
          i[3] || (i[3] = l("h3", null, "Будет удалено", -1)),
          l("ul", null, [
            (f(!0), h(N, null, ie(e.operation.removed, (a) => (f(), h("li", { key: a }, y(a), 1))), 128))
          ])
        ], 64)) : T("", !0),
        ["install", "update"].includes(e.operation.action) ? (f(), h(N, { key: 3 }, [
          i[4] || (i[4] = l("p", null, "Файлы передаются с панели. GitHub на роутере не используется.", -1)),
          e.operation.action === "update" ? (f(), h("p", Hg, "Конфигурация и автозапуск сохраняются. Работающая служба будет остановлена на время обновления и запущена снова. Подготовлен резерв исходной версии для отката.")) : T("", !0),
          l("ul", null, [
            (f(!0), h(N, null, ie(e.operation.changes, (a) => (f(), h("li", {
              key: a.package
            }, y(a.package) + ": " + y(a.before || "не установлен") + " → " + y(a.after), 1))), 128))
          ])
        ], 64)) : T("", !0),
        e.operation.warnings?.length ? (f(), h("section", Lg, [
          i[5] || (i[5] = l("h3", null, "Последствия изменений", -1)),
          l("ul", null, [
            (f(!0), h(N, null, ie(e.operation.warnings, (a) => (f(), h("li", { key: a }, y(a), 1))), 128))
          ])
        ])) : T("", !0),
        e.operation.preserved.length ? (f(), h("p", jg, "Сохранятся: " + y(e.operation.preserved.join(", ")) + ".", 1)) : T("", !0),
        e.operation.keep_backup ? (f(), h("p", Wg, "Конфигурация сохраняется в резервную копию; путь будет в журнале.")) : T("", !0),
        l("div", Bg, [
          l("button", {
            class: "gw-primary",
            disabled: e.busy,
            onClick: i[0] || (i[0] = (a) => n("apply"))
          }, "Да, выполнить показанный план", 8, Kg),
          l("button", {
            disabled: e.busy,
            onClick: i[1] || (i[1] = (a) => n("cancel"))
          }, "Отмена", 8, Gg)
        ])
      ]),
      _: 1
    }, 8, ["busy"]));
  }
}), Jg = {
  key: 0,
  class: "gw-error",
  role: "alert"
}, Yg = { class: "gw-actions" }, Xg = ["disabled"], Zg = ["disabled"], Qg = /* @__PURE__ */ qe({
  __name: "IntegrationUpdate",
  props: {
    plan: {},
    busy: { type: Boolean },
    error: {}
  },
  emits: ["apply", "cancel"],
  setup(e, { emit: t }) {
    const n = t;
    return (o, s) => (f(), ge(Fe, {
      title: "Обновление интеграции · " + e.plan.name,
      compact: !0,
      busy: e.busy,
      onClose: s[2] || (s[2] = (i) => n("cancel"))
    }, {
      default: Me(() => [
        e.error ? (f(), h("p", Jg, y(e.error), 1)) : T("", !0),
        (f(!0), h(N, null, ie(e.plan.warnings, (i) => (f(), h("p", {
          key: i,
          class: "gw-notice"
        }, y(i), 1))), 128)),
        l("details", null, [
          l("summary", null, "Компоненты для обновления (" + y(e.plan.files.length) + ")", 1),
          l("ul", null, [
            (f(!0), h(N, null, ie(e.plan.files, (i) => (f(), h("li", { key: i }, y(i), 1))), 128))
          ])
        ]),
        l("div", Yg, [
          l("button", {
            class: "gw-primary",
            disabled: e.busy,
            onClick: s[0] || (s[0] = (i) => n("apply"))
          }, "Да, обновить интеграцию", 8, Xg),
          l("button", {
            disabled: e.busy,
            onClick: s[1] || (s[1] = (i) => n("cancel"))
          }, "Отмена", 8, Zg)
        ])
      ]),
      _: 1
    }, 8, ["title", "busy"]));
  }
}), eh = { class: "gw-pin-detail" }, th = { class: "gw-actions" }, nh = ["disabled"], lh = ["disabled"], sh = /* @__PURE__ */ qe({
  __name: "TlsTrust",
  props: {
    change: {},
    busy: { type: Boolean }
  },
  emits: ["apply", "cancel"],
  setup(e, { emit: t }) {
    const n = t;
    return (o, s) => (f(), ge(Fe, {
      title: "Изменение доверия HTTPS",
      busy: e.busy,
      onClose: s[2] || (s[2] = (i) => n("cancel"))
    }, {
      default: Me(() => [
        l("div", eh, [
          s[5] || (s[5] = l("p", null, "Изменяется сохранённый отпечаток сертификата API.", -1)),
          l("p", null, [
            s[3] || (s[3] = I("Прежний: ", -1)),
            l("code", null, y(e.change.previous), 1)
          ]),
          l("p", null, [
            s[4] || (s[4] = I("Новый: ", -1)),
            l("code", null, y(e.change.next || "Проверка стандартной цепочки сертификатов"), 1)
          ]),
          s[6] || (s[6] = l("p", null, "Подтвердите изменение после проверки сертификата роутера.", -1))
        ]),
        l("div", th, [
          l("button", {
            class: "gw-primary",
            disabled: e.busy,
            onClick: s[0] || (s[0] = (i) => n("apply"))
          }, "Да, принять изменение", 8, nh),
          l("button", {
            disabled: e.busy,
            onClick: s[1] || (s[1] = (i) => n("cancel"))
          }, "Отмена", 8, lh)
        ])
      ]),
      _: 1
    }, 8, ["busy"]));
  }
}), oh = {
  key: 0,
  class: "gw-error",
  role: "alert"
}, ih = {
  key: 1,
  class: "gw-hint"
}, ah = { class: "gw-change-list" }, rh = {
  key: 0,
  class: "gw-notice"
}, uh = { class: "gw-notice" }, dh = { class: "gw-actions" }, ch = ["disabled"], fh = ["disabled"], ph = ["disabled"], vh = /* @__PURE__ */ qe({
  __name: "FirewallRestart",
  props: {
    node: {},
    bridge: {}
  },
  emits: ["close", "changed"],
  setup(e, { emit: t }) {
    const n = e, o = t, s = /* @__PURE__ */ H(!1), i = /* @__PURE__ */ H(""), a = /* @__PURE__ */ H(null), u = "/api/gateways/" + encodeURIComponent(n.node.id), c = (S, A, Y = "POST") => n.bridge.request(u + S, {
      method: Y,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(A)
    });
    async function g() {
      s.value = !0, i.value = "";
      try {
        const S = await n.bridge.request(u + "/network");
        if (!S.settings_hash) throw new Error("Не удалось прочитать актуальные настройки firewall");
        a.value = await c("/network/plan", { action: "firewall_restart", data: { config_hash: S.settings_hash } });
      } catch (S) {
        i.value = S.message;
      } finally {
        s.value = !1;
      }
    }
    async function m() {
      if (!(s.value || !a.value)) {
        s.value = !0, i.value = "";
        try {
          const S = a.value, A = await c("/router-operations", { plan_token: S.plan_token, confirmed: !0 });
          a.value = null, o("close"), n.bridge.task({ taskId: A.task_id, title: S.title, cancellable: !1, onDone: async () => o("changed") });
        } catch (S) {
          i.value = S.message;
        } finally {
          s.value = !1;
        }
      }
    }
    async function b() {
      if (!s.value) {
        s.value = !0, i.value = "";
        try {
          a.value && await c("/operation-plans/" + encodeURIComponent(a.value.plan_token), {}, "DELETE"), a.value = null, o("close");
        } catch (S) {
          i.value = S.message;
        } finally {
          s.value = !1;
        }
      }
    }
    return rt(() => {
      g();
    }), (S, A) => (f(), ge(Fe, {
      title: "Перезапуск firewall",
      busy: s.value,
      onClose: b
    }, {
      default: Me(() => [
        i.value ? (f(), h("p", oh, y(i.value), 1)) : T("", !0),
        s.value && !a.value ? (f(), h("p", ih, "Получаем план перезапуска…")) : T("", !0),
        a.value ? (f(), h(N, { key: 2 }, [
          l("ul", ah, [
            (f(!0), h(N, null, ie(a.value.summary, (Y, M) => (f(), h("li", { key: M }, y(Y), 1))), 128))
          ]),
          a.value.warnings?.length ? (f(), h("ul", rh, [
            (f(!0), h(N, null, ie(a.value.warnings, (Y, M) => (f(), h("li", { key: M }, y(Y), 1))), 128))
          ])) : T("", !0),
          l("p", uh, "Панель проверит связь. Если подтверждение не придёт в течение " + y(a.value.rollback_seconds) + " секунд, роутер восстановит прежнюю конфигурацию.", 1)
        ], 64)) : T("", !0),
        l("div", dh, [
          a.value ? (f(), h("button", {
            key: 0,
            class: "gw-primary",
            disabled: s.value,
            onClick: m
          }, "Перезапустить", 8, ch)) : i.value ? (f(), h("button", {
            key: 1,
            disabled: s.value,
            onClick: g
          }, "Повторить", 8, fh)) : T("", !0),
          l("button", {
            disabled: s.value,
            onClick: b
          }, "Отмена", 8, ph)
        ])
      ]),
      _: 1
    }, 8, ["busy"]));
  }
}), gh = {
  key: 0,
  class: "gw-error",
  role: "alert"
}, hh = { class: "gw-tabs" }, mh = { class: "gw-two" }, bh = { class: "gw-actions" }, yh = ["disabled"], wh = ["disabled"], _h = { class: "gw-detected" }, kh = { key: 0 }, $h = { class: "gw-panel" }, Ch = { key: 0 }, xh = { key: 1 }, Sh = { class: "gw-actions" }, Th = ["disabled"], Eh = ["disabled"], Ph = ["disabled"], Ah = {
  key: 0,
  class: "gw-panel"
}, Uh = { key: 0 }, Vh = { class: "gw-header" }, Ih = {
  key: 0,
  class: "gw-empty"
}, Oh = {
  key: 2,
  class: "server-table-wrap gw-server-table-wrap"
}, Mh = { class: "server-table gw-server-table" }, Rh = ["onClick", "onKeydown"], Dh = { class: "server-name-cell" }, Nh = { class: "gw-server-identity" }, Fh = ["title"], qh = { class: "server-host-cell" }, Hh = { class: "gw-server-sensors" }, Lh = { class: "gw-card-stats" }, jh = { class: "gw-server-traffic" }, Wh = {
  key: 1,
  class: "gw-detail"
}, Bh = ["disabled"], Kh = {
  key: 0,
  class: "gw-error"
}, Gh = {
  key: 1,
  class: "gw-hint"
}, zh = { class: "gw-tabs" }, Jh = ["onClick"], Yh = { class: "gw-metrics" }, Xh = { class: "gw-panel" }, Zh = { class: "gw-panel" }, Qh = { class: "gw-panel" }, em = { class: "gw-panel" }, tm = { class: "gw-panel" }, nm = { key: 0 }, lm = { class: "gw-clients-section" }, sm = { class: "gw-section-header" }, om = { class: "gw-table-wrap" }, im = {
  key: 0,
  class: "gw-hint"
}, am = {
  key: 1,
  class: "gw-pagination"
}, rm = { class: "gw-hint" }, um = { class: "gw-actions" }, dm = ["disabled"], cm = { "aria-live": "polite" }, fm = ["disabled"], pm = {
  key: 0,
  class: "gw-hint",
  role: "status"
}, vm = {
  key: 1,
  class: "gw-error",
  role: "alert"
}, gm = { class: "gw-catalog-list" }, hm = { class: "gw-catalog-summary" }, mm = {
  key: 0,
  class: "gw-status good"
}, bm = { class: "gw-catalog-body" }, ym = { class: "gw-catalog-controls" }, wm = { class: "gw-field" }, _m = ["onUpdate:modelValue", "disabled"], km = {
  key: 0,
  value: ""
}, $m = { class: "gw-actions" }, Cm = ["disabled", "onClick"], xm = ["disabled", "onClick"], Sm = { class: "gw-hint" }, Tm = {
  key: 0,
  class: "gw-hint"
}, Em = {
  key: 1,
  class: "gw-hint"
}, Pm = { class: "gw-reserve-settings" }, Am = { class: "gw-check" }, Um = { class: "gw-actions" }, Vm = ["disabled"], Im = {
  key: 0,
  class: "gw-hint",
  role: "status"
}, Om = {
  key: 12,
  class: "gw-panel"
}, Mm = { class: "gw-actions" }, Rm = ["disabled"], Dm = { class: "gw-log" }, Nm = {
  key: 13,
  class: "gw-access"
}, Fm = {
  key: 0,
  class: "gw-section-header"
}, qm = ["disabled"], Hm = ["disabled"], Lm = { class: "gw-section-header" }, jm = ["disabled"], Wm = {
  key: 2,
  class: "gw-hint",
  role: "status"
}, Bm = { class: "gw-access-columns" }, Km = { class: "gw-hint" }, Gm = ["href"], zm = { class: "gw-actions" }, Jm = ["disabled"], Ym = { class: "gw-two" }, Xm = { key: 0 }, Zm = ["placeholder"], Qm = { key: 1 }, e1 = { class: "gw-actions" }, t1 = ["disabled"], n1 = {
  key: 0,
  style: { "margin-top": "24px" }
}, l1 = {
  key: 0,
  class: "gw-hint"
}, s1 = {
  key: 0,
  class: "gw-hint"
}, o1 = { class: "gw-actions" }, i1 = ["disabled"], a1 = ["disabled"], Tl = "bot4vps_gateway_location", r1 = /* @__PURE__ */ qe({
  __name: "Gateways",
  props: {
    bridge: {},
    wizard: { type: Boolean },
    initialPlan: {}
  },
  setup(e) {
    const t = /* @__PURE__ */ H(!1), n = /* @__PURE__ */ H(null), o = /* @__PURE__ */ H(null), s = e;
    function i() {
      if (s.wizard || s.initialPlan?.return_node_id) return null;
      try {
        const x = JSON.parse(sessionStorage.getItem(Tl) || "null");
        return x && typeof x.nodeId == "string" && ["overview", "network", "wifi", "services", "packages", "backups", "logs", "access"].includes(x.tab) ? x : null;
      } catch {
        return null;
      }
    }
    const a = i(), u = /* @__PURE__ */ H([]), c = /* @__PURE__ */ H(s.wizard ? null : s.initialPlan?.return_node_id || a?.nodeId || null), g = /* @__PURE__ */ H(!1), m = /* @__PURE__ */ H(""), b = /* @__PURE__ */ H(s.wizard), S = /* @__PURE__ */ H("ssh"), A = /* @__PURE__ */ H(s.initialPlan), Y = /* @__PURE__ */ H(!1), M = /* @__PURE__ */ H(a?.tab || "overview"), te = /* @__PURE__ */ H(""), X = /* @__PURE__ */ H("");
    st([c, M], ([x, v]) => {
      if (!s.wizard)
        try {
          x ? sessionStorage.setItem(Tl, JSON.stringify({ nodeId: x, tab: v })) : sessionStorage.removeItem(Tl);
        } catch {
        }
    }, { immediate: !0 });
    const Q = /* @__PURE__ */ H(""), ne = /* @__PURE__ */ H(0), O = /* @__PURE__ */ H(null), L = /* @__PURE__ */ H(null), V = /* @__PURE__ */ H(!1), E = /* @__PURE__ */ H(!1), C = /* @__PURE__ */ H(3), j = /* @__PURE__ */ H(null), Z = /* @__PURE__ */ H({}), pe = /* @__PURE__ */ new Set(), be = (x, v) => x + ":" + v;
    function Ue(x) {
      const v = /* @__PURE__ */ new Set();
      let $ = !1;
      for (const ue of x) for (const he of ue.service_update_tasks || [])
        v.add(he.task_id), Z.value[be(ue.id, he.service)] = { stage: he.stage, task_id: he.task_id };
      for (const [ue, he] of Object.entries(Z.value)) he.stage !== "review" && he.task_id && !v.has(he.task_id) && (delete Z.value[ue], ue.startsWith((J.value?.id || "") + ":") && ($ = !0));
      $ && M.value === "services" && ne.value++;
    }
    const Oe = ke(() => Object.fromEntries(Object.entries(Z.value).filter(([x]) => x.startsWith((J.value?.id || "") + ":")).map(([x, v]) => [x.split(":").at(-1), v]))), le = /* @__PURE__ */ H(!1), P = /* @__PURE__ */ H([]), d = /* @__PURE__ */ H({ podkop: [], ssclash: [], adguardhome: [] }), r = /* @__PURE__ */ H({ podkop: "", ssclash: "", adguardhome: "" }), p = /* @__PURE__ */ H({ name: "", host: "", port: 22, user: "root", password: "", url: "", username: "", tls_sha256: "" }), _ = /* @__PURE__ */ H({ user: "root", port: 22, auth_type: "password", password: "", key_path: "" }), K = /* @__PURE__ */ H(null), Ce = /* @__PURE__ */ H(null), J = ke(() => u.value.find((x) => x.id === c.value)), ye = ke(() => J.value?.monitor || {}), Xt = ke(() => Object.values(ye.value.wireguard || {})), St = /* @__PURE__ */ H(""), ut = /* @__PURE__ */ H(""), He = /* @__PURE__ */ H(1), dt = 20, Wt = ke(() => (ye.value.clients || []).filter((x) => [x.hostname, x.ipaddr, x.macaddr].join(" ").toLowerCase().includes(ut.value.toLowerCase()))), w = ke(() => Math.max(1, Math.ceil(Wt.value.length / dt))), k = ke(() => Wt.value.slice((He.value - 1) * dt, He.value * dt));
    st(ut, () => {
      He.value = 1;
    }), st(w, (x) => {
      He.value = Math.min(He.value, x);
    }), st(c, () => {
      ut.value = "", He.value = 1;
    });
    function U(x) {
      x.id === "firewall" ? n.value = "firewall" : x.id === "dnsmasq" ? n.value = "dns" : x.id === "adguardhome" ? t.value = !0 : ee(x);
    }
    const W = ke(() => u.value.filter((x) => (x.name + " " + x.host + " " + (x.monitor.board?.model || "")).toLowerCase().includes(St.value.toLowerCase()))), R = [{ id: "overview", name: "Обзор" }, { id: "network", name: "Сеть" }, { id: "wifi", name: "Wi-Fi" }, { id: "services", name: "Службы" }, { id: "packages", name: "Пакеты" }, { id: "backups", name: "Резервные копии" }, { id: "logs", name: "Журнал" }, { id: "access", name: "Доступ" }];
    let q, z = !0;
    const B = (x, v, $ = "POST") => s.bridge.request(x, { method: $, headers: { "Content-Type": "application/json" }, body: JSON.stringify(v) }), G = (x) => x == null ? "—" : x > 1073741824 ? (x / 1073741824).toFixed(1) + " ГБ" : x > 1048576 ? (x / 1048576).toFixed(1) + " МБ" : x > 1024 ? (x / 1024).toFixed(1) + " КБ" : x + " Б", F = (x) => x ? Math.floor(x / 86400) + " д " + Math.floor(x % 86400 / 3600) + " ч" : "—";
    async function ae() {
      const x = J.value;
      if (!x) return;
      const v = window.open("about:blank", "_blank");
      try {
        const $ = await s.bridge.request("/api/gateways/" + encodeURIComponent(x.id) + "/adguard"), he = "http://" + (x.host.includes(":") ? "[" + x.host + "]" : x.host) + ":" + ($.web_port || 3e3) + "/";
        v ? (v.opener = null, v.location.href = he) : m.value = "Браузер заблокировал открытие сервиса";
      } catch ($) {
        v?.close(), m.value = $ instanceof Error ? $.message : String($);
      }
    }
    function ee(x) {
      x.id === "ssclash" || x.id === "adguardhome" ? window.open(re(x), "_blank", "noopener,noreferrer") : window.open(new URL("/cgi-bin/luci/admin/services/" + (x.id === "podkop" ? "podkop" : ""), J.value.luci_url).href, "_blank", "noopener,noreferrer");
    }
    function re(x) {
      const v = J.value.host.includes(":") ? "[" + J.value.host + "]" : J.value.host, $ = Number(x.web_port) || (x.id === "adguardhome" ? 3e3 : 9091);
      return (x.web_https ? "https://" : "http://") + v + ":" + $ + "/";
    }
    async function se() {
      try {
        const x = await s.bridge.request("/api/gateways");
        if (x.enabled === !1) {
          s.bridge.navigate("dashboard");
          return;
        }
        u.value = x.gateways || [], c.value && !u.value.some((v) => v.id === c.value) && (c.value = null, M.value = "overview"), Ue(u.value), s.bridge.changed();
      } catch (x) {
        m.value = x.message;
      }
    }
    async function ve() {
      if (!(document.hidden || g.value || b.value))
        try {
          const x = await s.bridge.request("/api/gateways/status");
          if (!z || !Array.isArray(x.gateways)) return;
          if (x.gateways.length !== u.value.length || x.gateways.some((v) => !u.value.some(($) => $.id === v.id))) {
            await se();
            return;
          }
          for (const v of x.gateways) {
            const $ = u.value.find((ue) => ue.id === v.id);
            $.monitor = { ...$.monitor, ...v.monitor };
          }
          Ue(x.gateways);
        } catch (x) {
          z && (m.value = x instanceof Error ? x.message : String(x));
        }
    }
    function we() {
      !document.hidden && !b.value && !s.wizard && se();
    }
    async function ce(x) {
      if (!g.value) {
        g.value = !0, m.value = "";
        try {
          await x();
        } catch (v) {
          m.value = v.message;
        } finally {
          g.value = !1;
        }
      }
    }
    async function Ae() {
      await ce(async () => {
        if (S.value === "api") {
          const v = await B("/api/gateways/manual", {
            name: p.value.name,
            url: p.value.url,
            username: p.value.username,
            password: p.value.password,
            tls_sha256: p.value.tls_sha256 || null
          });
          p.value.password = "", b.value = !1, c.value = v.id, await se(), s.bridge.navigate("gateways"), s.bridge.close?.();
          return;
        }
        const x = await B("/api/gateways/probe", {
          name: p.value.name,
          host: p.value.host,
          port: Number(p.value.port),
          user: p.value.user,
          password: p.value.password,
          auth_type: "password"
        });
        if (p.value.password = "", x.node_type !== "openwrt") throw new Error("На этом устройстве OpenWrt не обнаружен. Добавьте его в разделе «Серверы».");
        A.value = x;
      });
    }
    async function Ve(x) {
      await ce(async () => {
        const v = await B("/api/gateways/bootstrap/" + encodeURIComponent(A.value.draft_token), { decision: x });
        if (x === "no") {
          A.value = null, b.value = !1, s.bridge.close?.();
          return;
        }
        if (x === "manual") {
          Y.value = !0;
          return;
        }
        b.value = !1, s.bridge.task({
          taskId: v.task_id,
          title: "Подключение шлюза",
          cancellable: !1,
          onDone: async ($) => {
            ($.status === "success" || $.status === "success_warn") && (await se(), s.bridge.navigate("gateways"));
          },
          renderResult: ($, ue) => {
            const he = document.createElement("p");
            he.textContent = ["success", "success_warn"].includes($.status) ? $.status === "success_warn" ? "Шлюз подключён и сохранён. Есть предупреждения — проверьте журнал задачи и вкладку «Доступ». Повторное подключение не требуется." : "Управление доступом: LuCI → Службы → Bot4VPS. Секрет в журнал не записывается." : "Подключение не завершено. Проверьте журнал и настройки роутера.", ue.replaceChildren(he);
          }
        }), s.bridge.close?.();
      });
    }
    async function Re(x) {
      n.value = null, t.value = !1, M.value = x, m.value = "", X.value = "", V.value = !1, x === "logs" && J.value && await ce(async () => {
        te.value = (await s.bridge.request("/api/gateways/" + J.value.id + "/logs")).output;
      }), x === "access" && J.value && (p.value.name = J.value.name, p.value.url = J.value.api_url, p.value.username = J.value.api_username, p.value.tls_sha256 = J.value.tls_sha256 || "", p.value.password = "", _.value = { user: J.value.ssh_user || "root", port: J.value.ssh_port || 22, auth_type: J.value.ssh_auth_type || "password", password: "", key_path: "" });
    }
    async function Le(x, v, $, ue, he) {
      const Qe = J.value?.id;
      Qe && await ce(async () => {
        const Zt = await B("/api/gateways/" + Qe + "/services/" + x + "/plan", { action: v, keep_backup: !0, bundle_id: $ || null, rollback_bundle_id: ue || null, web_scope: he || null });
        if (!z || J.value?.id !== Qe) {
          await B("/api/gateways/" + Qe + "/operation-plans/" + encodeURIComponent(Zt.plan_token), {}, "DELETE");
          return;
        }
        L.value = Zt, j.value = Qe, le.value = V.value, V.value = !1;
      });
    }
    function tt(x, v, $, ue) {
      const he = be(x, v);
      Z.value[he] = { stage: ue, task_id: $ }, !pe.has($) && (pe.add($), s.bridge.task({ taskId: $, title: ue === "prepare" ? "Подготовка обновления " + v : "Обновление " + v, cancellable: !1, onDone: async () => {
        try {
          const Qe = await s.bridge.request("/api/tasks/" + encodeURIComponent($));
          if (Z.value[he]?.task_id && Z.value[he].task_id !== $) return;
          if (!Qe.success) {
            z && J.value?.id === x && (m.value = Qe.error || "Обновление завершилось с ошибкой. Проверьте журнал задачи."), delete Z.value[he];
            return;
          }
          if (ue === "prepare") {
            if (!z || J.value?.id !== x) {
              delete Z.value[he];
              return;
            }
            const Zt = JSON.parse(Qe.result.output);
            if (Zt.review_prepared) {
              const vi = await s.bridge.request("/api/gateways/" + x + "/services/" + v + "/update-plan?task_id=" + encodeURIComponent($));
              if (Z.value[he]?.task_id && Z.value[he].task_id !== $) return;
              if (!z || J.value?.id !== x) {
                delete Z.value[he];
                return;
              }
              an(vi);
            } else await Le(v, "update", Zt.bundle_id, Zt.rollback_bundle_id);
            L.value?.action === "update" && L.value.service === v && j.value === x ? Z.value[he] = { stage: "review", task_id: L.value.preparation_task_id || $ } : delete Z.value[he];
          } else
            delete Z.value[he], z && (await se(), await Mn(), ne.value++);
        } catch (Qe) {
          (!Z.value[he]?.task_id || Z.value[he].task_id === $) && delete Z.value[he], z && J.value?.id === x && (m.value = Qe instanceof Error ? Qe.message : String(Qe));
        }
      } }));
    }
    function an(x) {
      const v = J.value?.id;
      !v || x.node_id && x.node_id !== v || (L.value = x, j.value = v, Z.value[be(v, x.service)] = { stage: "review", task_id: x.preparation_task_id || void 0 });
    }
    function ze(x, v) {
      J.value && v.task_id && (Z.value[be(J.value.id, x)] = { stage: v.stage, task_id: v.task_id });
    }
    async function nt(x) {
      const v = J.value?.id;
      if (!v || g.value || Z.value[be(v, x)]) return;
      const $ = be(v, x);
      Z.value[$] = { stage: "prepare" }, await ce(async () => {
        try {
          const ue = await B("/api/gateways/" + v + "/services/" + x + "/update-bundle", {});
          tt(v, x, ue.task_id, "prepare");
        } catch (ue) {
          throw delete Z.value[$], ue;
        }
      });
    }
    async function In() {
      await ce(async () => {
        const x = await B("/api/gateways/" + J.value.id + "/bootstrap/finalize", {});
        s.bridge.task({ taskId: x.task_id, title: "Фиксация подключения", cancellable: !1, onDone: se });
      });
    }
    async function On() {
      const x = J.value;
      x && await ce(async () => {
        const v = await B("/api/gateways/" + x.id + "/integration/plan", {});
        Ce.value = { ...v, nodeId: x.id, name: x.name };
      });
    }
    function li() {
      const x = Ce.value;
      Ce.value = null, x && B("/api/gateways/" + x.nodeId + "/integration/plans/" + encodeURIComponent(x.plan_token), {}, "DELETE").catch((v) => {
        m.value = v instanceof Error ? v.message : String(v);
      });
    }
    async function si() {
      const x = Ce.value;
      x && await ce(async () => {
        const v = await B("/api/gateways/" + x.nodeId + "/integration", { plan_token: x.plan_token, confirmed: !0 });
        Ce.value = null, s.bridge.task({ taskId: v.task_id, title: "Обновление интеграции Bot4VPS", cancellable: !1, onDone: async () => {
          z && (await se(), ne.value++);
        } });
      });
    }
    async function oi() {
      const x = L.value?.plan_token, v = j.value || J.value?.id;
      L.value?.action === "update" && v && delete Z.value[be(v, L.value.service)];
      const $ = L.value?.action === "update";
      if (L.value = null, j.value = null, m.value = "", le.value && (V.value = !0), le.value = !1, x && v)
        try {
          await B("/api/gateways/" + encodeURIComponent(v) + "/operation-plans/" + encodeURIComponent(x), {}, "DELETE");
        } catch (ue) {
          m.value = ue instanceof Error ? ue.message : String(ue);
        } finally {
          $ && ne.value++;
        }
    }
    async function ii() {
      const x = L.value, v = j.value || J.value?.id;
      !x || !v || await ce(async () => {
        const $ = await B("/api/gateways/" + v + "/operations", { plan_token: x.plan_token, confirmed: !0 }), ue = x.service;
        if (L.value = null, j.value = null, x.action === "update") {
          tt(v, ue, $.task_id, "apply");
          return;
        }
        s.bridge.task({
          taskId: $.task_id,
          title: "Операция: " + ue,
          cancellable: !1,
          onDone: async () => {
            await se(), await Mn(), ne.value++;
          },
          onResultClosed: (he) => {
            z && J.value?.id === v && ue === "adguardhome" && x.action === "install" && ["success", "success_warn"].includes(he.status) && (t.value = !0);
          }
        });
      });
    }
    async function Mn() {
      const x = await s.bridge.request("/api/gateways/reserve");
      E.value = x.settings.enabled, C.value = x.settings.keep, P.value = x.bundles;
    }
    async function rs() {
      V.value = !0, await ce(async () => {
        await Mn(), await Promise.all(["podkop", "ssclash", "adguardhome"].map(async (x) => {
          const v = await s.bridge.request("/api/gateways/catalog/" + x + "?node_id=" + encodeURIComponent(J.value.id));
          d.value[x] = v.versions, v.versions.includes(r.value[x]) || (r.value[x] = v.versions[0] || "");
        }));
      });
    }
    async function ai() {
      await ce(async () => {
        await B("/api/gateways/reserve", { enabled: E.value, keep: Number(C.value) }, "PUT"), X.value = E.value ? "Резервирование включено. Службы на роутере не устанавливаются и не обновляются." : "Автоматическое резервирование отключено. Сохранённые резервные версии останутся на панели.";
      });
    }
    async function ri(x) {
      await ce(async () => {
        const v = await B("/api/gateways/" + J.value.id + "/bundles", { profile: x, version: r.value[x] });
        s.bridge.task({
          taskId: v.task_id,
          title: "Подготовка комплекта " + x,
          cancellable: !1,
          onDone: async () => {
            await Mn();
          }
        });
      });
    }
    function pl(x) {
      return P.value.find((v) => v.profile === x && v.version === r.value[x] && v.platform.release?.version === ye.value.board?.release?.version && v.platform.release?.target === ye.value.board?.release?.target && v.complete);
    }
    async function ui() {
      const x = J.value?.id;
      if (!x) return;
      const v = J.value.tls_sha256, $ = p.value.tls_sha256 || null;
      if (v && v !== $) {
        K.value = { nodeId: x, previous: v, next: $ };
        return;
      }
      await us(!1);
    }
    async function us(x) {
      const v = J.value?.id;
      !v || x && K.value?.nodeId !== v || (K.value = null, await ce(async () => {
        await B("/api/gateways/" + v + "/credentials", {
          name: p.value.name,
          url: p.value.url,
          username: p.value.username,
          password: p.value.password,
          tls_sha256: p.value.tls_sha256 || null,
          tls_pin_confirmed: x
        }, "PUT"), p.value.password = "", X.value = "Доступ проверен и сохранён", await se();
      }));
    }
    async function di() {
      if (!J.value.ssh_configured) {
        await Re("access"), m.value = "Сначала сохраните SSH-доступ для консоли.";
        return;
      }
      await ce(async () => {
        await s.bridge.console?.(J.value);
      });
    }
    async function ci() {
      await ce(async () => {
        await B("/api/gateways/" + J.value.id + "/ssh", { ..._.value, password: _.value.password || null }, "PUT"), _.value.password = "", X.value = "SSH-доступ проверен и сохранён. Пароль зашифрован мастер-ключом панели.", await se();
      });
    }
    async function fi() {
      await ce(async () => {
        O.value = await s.bridge.request("/api/gateways/" + J.value.id + "/deletion-plan");
      });
    }
    async function pi() {
      await ce(async () => {
        const x = await B("/api/gateways/" + J.value.id, { confirmed: !0, plan_token: O.value.plan_token }, "DELETE");
        O.value = null, s.bridge.task({
          taskId: x.task_id,
          title: "Удаление шлюза и отзыв API",
          cancellable: !1,
          onDone: async () => {
            c.value = null, await se();
          },
          renderResult: (v, $) => {
            const ue = document.createElement("p");
            ue.textContent = v.status === "success" ? "Удаление шлюза завершено. Результат очистки Bot4VPS — в журнале задачи. Настройки роутера и установленные службы сохранены." : "Отзыв доступа или очистка интеграции не завершены. Запись шлюза сохранена; проверьте журнал задачи.", $.replaceChildren(ue);
          }
        });
      });
    }
    return rt(() => {
      s.wizard || (se().then(() => {
        if (z && J.value) return Re(M.value);
      }), q = setInterval(() => {
        ve();
      }, 5e3), document.addEventListener("visibilitychange", we));
    }), Rt(() => {
      z = !1, q && clearInterval(q), document.removeEventListener("visibilitychange", we), p.value.password = "", _.value.password = "";
    }), (x, v) => (f(), h("div", {
      class: Ee(["gw-shell", { "gw-wizard": e.wizard }])
    }, [
      m.value ? (f(), h("div", gh, y(m.value), 1)) : T("", !0),
      Ce.value ? (f(), ge(Qg, {
        key: 1,
        plan: Ce.value,
        busy: g.value,
        error: m.value,
        onCancel: li,
        onApply: si
      }, null, 8, ["plan", "busy", "error"])) : T("", !0),
      K.value ? (f(), ge(sh, {
        key: 2,
        change: K.value,
        busy: g.value,
        onCancel: v[0] || (v[0] = ($) => K.value = null),
        onApply: v[1] || (v[1] = ($) => us(!0))
      }, null, 8, ["change", "busy"])) : T("", !0),
      b.value ? (f(), h(N, { key: 3 }, [
        v[67] || (v[67] = l("header", { class: "gw-header" }, [
          l("div", null, [
            l("span", { class: "gw-eyebrow" }, "НОВОЕ ПОДКЛЮЧЕНИЕ"),
            l("h2", null, "Добавить шлюз"),
            l("p", null, "Подключение OpenWrt к вашей инфраструктуре")
          ])
        ], -1)),
        A.value ? (f(), h(N, { key: 1 }, [
          l("div", _h, [
            v[61] || (v[61] = l("span", { class: "gw-status good" }, "OpenWrt обнаружен", -1)),
            l("h3", null, y(A.value.board.model), 1),
            A.value.name ? (f(), h("p", kh, "Имя шлюза: " + y(A.value.name), 1)) : T("", !0),
            l("p", null, y(A.value.board.release?.version) + " · " + y(A.value.board.release?.target), 1)
          ]),
          l("div", $h, [
            v[63] || (v[63] = l("h3", null, "Для подключения панель выполнит", -1)),
            l("ul", null, [
              (f(!0), h(N, null, ie(A.value.missing_packages, ($) => (f(), h("li", { key: $ }, [
                v[62] || (v[62] = I("Установит пакет ", -1)),
                l("strong", null, y($), 1)
              ]))), 128)),
              A.value.missing_packages?.length ? T("", !0) : (f(), h("li", Ch, "Необходимые пакеты уже установлены")),
              (f(!0), h(N, null, ie(A.value.changes, ($) => (f(), h("li", { key: $ }, y($), 1))), 128)),
              A.value.https_configuration_required ? (f(), h("li", xh, "Включит HTTPS на адресе LAN")) : T("", !0)
            ]),
            v[64] || (v[64] = l("p", { class: "gw-hint" }, "Прошивка и установленные пакеты не обновляются. Сетевые интерфейсы не перенастраиваются. Ход настройки будет виден в журнале.", -1))
          ]),
          l("div", Sh, [
            l("button", {
              class: "gw-primary",
              disabled: g.value,
              onClick: v[14] || (v[14] = ($) => Ve("automatic"))
            }, "Да, настроить автоматически", 8, Th),
            l("button", {
              disabled: g.value,
              onClick: v[15] || (v[15] = ($) => Ve("no"))
            }, "Нет", 8, Eh),
            l("button", {
              disabled: g.value,
              onClick: v[16] || (v[16] = ($) => Ve("manual"))
            }, "Настроить самостоятельно", 8, Ph)
          ]),
          Y.value ? (f(), h("div", Ah, [
            v[66] || (v[66] = l("h3", null, "Самостоятельная настройка", -1)),
            A.value.manual.commands.length ? (f(), h("pre", Uh, y(A.value.manual.commands.join(`
`)), 1)) : T("", !0),
            l("ol", null, [
              (f(!0), h(N, null, ie(A.value.manual.steps, ($) => (f(), h("li", { key: $ }, y($), 1))), 128))
            ]),
            l("details", null, [
              v[65] || (v[65] = l("summary", null, "Права мониторинга rpcd", -1)),
              l("pre", null, y(JSON.stringify(A.value.manual.acl, null, 2)), 1)
            ]),
            l("button", {
              onClick: v[17] || (v[17] = ($) => {
                S.value = "api", A.value = null;
              })
            }, "Указать данные API")
          ])) : T("", !0)
        ], 64)) : (f(), h(N, { key: 0 }, [
          l("div", hh, [
            l("button", {
              class: Ee({ on: S.value === "ssh" }),
              onClick: v[2] || (v[2] = ($) => S.value = "ssh")
            }, "Настроить автоматически", 2),
            l("button", {
              class: Ee({ on: S.value === "api" }),
              onClick: v[3] || (v[3] = ($) => S.value = "api")
            }, "API уже настроен", 2)
          ]),
          l("form", {
            class: "gw-form",
            onSubmit: lt(Ae, ["prevent"])
          }, [
            l("label", null, [
              v[51] || (v[51] = I("Имя шлюза", -1)),
              D(l("input", {
                "onUpdate:modelValue": v[4] || (v[4] = ($) => p.value.name = $),
                placeholder: "Определится по модели роутера",
                maxlength: "100"
              }, null, 512), [
                [oe, p.value.name]
              ])
            ]),
            S.value === "ssh" ? (f(), h(N, { key: 0 }, [
              l("label", null, [
                v[52] || (v[52] = I("Адрес роутера", -1)),
                D(l("input", {
                  "onUpdate:modelValue": v[5] || (v[5] = ($) => p.value.host = $),
                  required: "",
                  placeholder: "192.168.1.1"
                }, null, 512), [
                  [oe, p.value.host]
                ])
              ]),
              l("div", mh, [
                l("label", null, [
                  v[53] || (v[53] = I("SSH-порт", -1)),
                  D(l("input", {
                    "onUpdate:modelValue": v[6] || (v[6] = ($) => p.value.port = $),
                    required: "",
                    type: "number",
                    min: "1",
                    max: "65535"
                  }, null, 512), [
                    [oe, p.value.port]
                  ])
                ]),
                l("label", null, [
                  v[54] || (v[54] = I("Логин", -1)),
                  D(l("input", {
                    "onUpdate:modelValue": v[7] || (v[7] = ($) => p.value.user = $),
                    required: "",
                    autocomplete: "username"
                  }, null, 512), [
                    [oe, p.value.user]
                  ])
                ])
              ]),
              l("label", null, [
                v[55] || (v[55] = I("SSH-пароль", -1)),
                D(l("input", {
                  "onUpdate:modelValue": v[8] || (v[8] = ($) => p.value.password = $),
                  required: "",
                  type: "password",
                  autocomplete: "off"
                }, null, 512), [
                  [oe, p.value.password]
                ])
              ]),
              v[56] || (v[56] = l("p", { class: "gw-hint" }, "Сначала панель проверит устройство и покажет необходимые изменения. Проверка ничего не устанавливает.", -1))
            ], 64)) : (f(), h(N, { key: 1 }, [
              l("label", null, [
                v[57] || (v[57] = I("HTTPS API", -1)),
                D(l("input", {
                  "onUpdate:modelValue": v[9] || (v[9] = ($) => p.value.url = $),
                  required: "",
                  type: "url",
                  placeholder: "https://192.168.1.1/ubus"
                }, null, 512), [
                  [oe, p.value.url]
                ])
              ]),
              l("label", null, [
                v[58] || (v[58] = I("Логин API", -1)),
                D(l("input", {
                  "onUpdate:modelValue": v[10] || (v[10] = ($) => p.value.username = $),
                  required: "",
                  autocomplete: "username"
                }, null, 512), [
                  [oe, p.value.username]
                ])
              ]),
              l("label", null, [
                v[59] || (v[59] = I("Секрет API", -1)),
                D(l("input", {
                  "onUpdate:modelValue": v[11] || (v[11] = ($) => p.value.password = $),
                  required: "",
                  type: "password",
                  autocomplete: "off"
                }, null, 512), [
                  [oe, p.value.password]
                ])
              ]),
              l("label", null, [
                v[60] || (v[60] = I("SHA-256 сертификата", -1)),
                D(l("input", {
                  "onUpdate:modelValue": v[12] || (v[12] = ($) => p.value.tls_sha256 = $),
                  placeholder: "Для собственного сертификата роутера"
                }, null, 512), [
                  [oe, p.value.tls_sha256]
                ])
              ])
            ], 64)),
            l("div", bh, [
              l("button", {
                class: "gw-primary",
                disabled: g.value
              }, y(g.value ? "Проверяем…" : S.value === "ssh" ? "Проверить роутер" : "Проверить и подключить"), 9, yh),
              l("button", {
                type: "button",
                onClick: v[13] || (v[13] = ($) => {
                  b.value = !1, e.bridge.close?.();
                }),
                disabled: g.value
              }, "Отмена", 8, wh)
            ])
          ], 32)
        ], 64))
      ], 64)) : e.wizard ? T("", !0) : (f(), h(N, { key: 4 }, [
        J.value ? T("", !0) : (f(), h(N, { key: 0 }, [
          l("header", Vh, [
            l("div", null, [
              v[68] || (v[68] = l("span", { class: "gw-eyebrow" }, "СЕТЬ И МАРШРУТИЗАЦИЯ", -1)),
              v[69] || (v[69] = l("h1", null, "Шлюзы", -1)),
              l("p", null, "OpenWrt · " + y(u.value.length) + " подключений", 1)
            ]),
            l("button", {
              class: "gw-primary",
              onClick: v[18] || (v[18] = ($) => e.bridge.add?.())
            }, "Добавить шлюз")
          ]),
          u.value.length ? T("", !0) : (f(), h("div", Ih, [
            v[70] || (v[70] = l("div", { class: "gw-empty-icon" }, "⌘", -1)),
            v[71] || (v[71] = l("h2", null, "Подключите ваш OpenWrt", -1)),
            v[72] || (v[72] = l("p", null, "Обзор сети, состояние служб и операции с понятным журналом.", -1)),
            l("button", {
              class: "gw-primary",
              onClick: v[19] || (v[19] = ($) => e.bridge.add?.())
            }, "Добавить шлюз")
          ])),
          u.value.length > 3 ? D((f(), h("input", {
            key: 1,
            "onUpdate:modelValue": v[20] || (v[20] = ($) => St.value = $),
            class: "gw-node-search",
            type: "search",
            "aria-label": "Поиск шлюзов",
            placeholder: "Найти шлюз по имени или адресу"
          }, null, 512)), [
            [oe, St.value]
          ]) : T("", !0),
          W.value.length ? (f(), h("div", Oh, [
            l("table", Mh, [
              v[77] || (v[77] = l("thead", null, [
                l("tr", null, [
                  l("th", null, "Имя шлюза"),
                  l("th", null, "Адрес / OpenWrt"),
                  l("th", null, "Статус"),
                  l("th", null, "Нагрузка"),
                  l("th", null, "Трафик LAN / WAN")
                ])
              ], -1)),
              l("tbody", null, [
                (f(!0), h(N, null, ie(W.value, ($) => (f(), h("tr", {
                  key: $.id,
                  class: "server-table-row",
                  tabindex: "0",
                  role: "button",
                  onClick: (ue) => {
                    c.value = $.id, M.value = "overview", m.value = "";
                  },
                  onKeydown: [
                    tl(lt((ue) => {
                      c.value = $.id, M.value = "overview", m.value = "";
                    }, ["prevent"]), ["enter"]),
                    tl(lt((ue) => {
                      c.value = $.id, M.value = "overview", m.value = "";
                    }, ["prevent"]), ["space"])
                  ]
                }, [
                  l("td", Dh, [
                    l("div", Nh, [
                      v[73] || (v[73] = l("span", {
                        class: "gw-router-icon",
                        "aria-hidden": "true"
                      }, [
                        l("svg", {
                          viewBox: "0 0 24 24",
                          width: "20",
                          height: "20"
                        }, [
                          l("rect", {
                            x: "3",
                            y: "11",
                            width: "18",
                            height: "9",
                            rx: "2"
                          }),
                          l("path", { d: "M7 11V5m10 6V5M5 6a10 10 0 0 1 14 0M8 8a6 6 0 0 1 8 0M7 16h.01M11 16h.01" })
                        ])
                      ], -1)),
                      l("strong", {
                        title: $.name
                      }, y($.name), 9, Fh)
                    ])
                  ]),
                  l("td", qh, [
                    l("span", null, y($.host), 1),
                    l("small", null, "OpenWrt " + y($.monitor.board?.release?.version || "—"), 1)
                  ]),
                  l("td", null, [
                    l("span", {
                      class: Ee(["gw-status", $.monitor.ok ? "good" : "warn"])
                    }, y($.monitor.ok ? $.monitor.stale ? "Данные устарели" : "На связи" : "Нет доступа к API"), 3)
                  ]),
                  l("td", Hh, [
                    l("div", Lh, [
                      l("span", null, [
                        v[74] || (v[74] = I("CPU ", -1)),
                        l("b", null, y($.monitor.cpu_pct == null ? "—" : $.monitor.cpu_pct + "%"), 1)
                      ]),
                      l("span", null, [
                        v[75] || (v[75] = I("RAM ", -1)),
                        l("b", null, y($.monitor.ram_pct == null ? "—" : $.monitor.ram_pct + "%"), 1)
                      ]),
                      l("span", null, [
                        v[76] || (v[76] = I("SoC ", -1)),
                        l("b", null, y($.monitor.temperature == null ? "—" : $.monitor.temperature + "°C"), 1)
                      ])
                    ])
                  ]),
                  l("td", jh, [
                    l("span", null, "LAN ↓ " + y(G($.monitor.traffic?.lan?.rx_bps)) + "/с · ↑ " + y(G($.monitor.traffic?.lan?.tx_bps)) + "/с", 1),
                    l("span", null, "WAN ↓ " + y(G($.monitor.traffic?.wan?.rx_bps)) + "/с · ↑ " + y(G($.monitor.traffic?.wan?.tx_bps)) + "/с", 1)
                  ])
                ], 40, Rh))), 128))
              ])
            ])
          ])) : T("", !0)
        ], 64)),
        J.value ? (f(), h("section", Wh, [
          l("button", {
            class: "gw-back-link",
            disabled: g.value,
            onClick: v[21] || (v[21] = ($) => {
              c.value = null, V.value = !1;
            })
          }, "← Все шлюзы", 8, Bh),
          Ze(dg, {
            node: J.value,
            busy: g.value,
            onConsole: di
          }, null, 8, ["node", "busy"]),
          ye.value.ok ? T("", !0) : (f(), h("p", Kh, y(ye.value.error) + ". " + y(ye.value.error_code === "permission" ? "Проверьте доступ в LuCI или укажите новый секрет во вкладке «Доступ»." : "Проверьте доступность API роутера. Панель повторит проверку автоматически."), 1)),
          J.value.bootstrap_state === "commit_pending" ? (f(), h("p", Gh, "Шлюз подключён. Фиксация транзакции не подтверждена; завершите её во вкладке «Доступ».")) : T("", !0),
          l("div", zh, [
            (f(), h(N, null, ie(R, ($) => l("button", {
              key: $.id,
              class: Ee({ on: M.value === $.id }),
              onClick: (ue) => Re($.id)
            }, y($.name), 11, Jh)), 64))
          ]),
          M.value === "overview" ? (f(), h(N, { key: 2 }, [
            l("div", Yh, [
              l("div", Xh, [
                v[78] || (v[78] = l("span", null, "Загрузка CPU", -1)),
                l("strong", null, y(ye.value.cpu_pct == null ? "—" : ye.value.cpu_pct + "%"), 1)
              ]),
              l("div", Zh, [
                v[79] || (v[79] = l("span", null, "Оперативная память", -1)),
                l("strong", null, y(ye.value.ram_pct == null ? "—" : ye.value.ram_pct + "%"), 1),
                l("small", null, y(G(ye.value.ram_used)) + " / " + y(G(ye.value.ram_total)), 1)
              ]),
              l("div", Qh, [
                v[80] || (v[80] = l("span", null, "Свободное место", -1)),
                l("strong", null, y(G(ye.value.storage_free)), 1),
                l("small", null, "из " + y(G(ye.value.storage_total)), 1)
              ]),
              l("div", em, [
                v[81] || (v[81] = l("span", null, "Время работы", -1)),
                l("strong", null, y(F(ye.value.uptime)), 1)
              ]),
              l("div", tm, [
                v[82] || (v[82] = l("span", null, "Температура", -1)),
                l("strong", null, y(ye.value.temperature == null ? "Нет датчика" : ye.value.temperature + "°C"), 1),
                ye.value.temperature_support?.virtual ? (f(), h("small", nm, "Виртуальная машина")) : T("", !0),
                ye.value.temperature_support?.package ? (f(), h("button", {
                  key: 1,
                  onClick: v[22] || (v[22] = ($) => {
                    Q.value = ye.value.temperature_support.package, Re("packages");
                  })
                }, "Проверить пакет датчика")) : T("", !0)
              ])
            ]),
            Ze(Xf, {
              monitor: ye.value,
              "node-id": J.value.id,
              bridge: e.bridge
            }, null, 8, ["monitor", "node-id", "bridge"])
          ], 64)) : T("", !0),
          M.value === "network" ? (f(), h(N, { key: 3 }, [
            (f(), ge(of, {
              key: J.value.id,
              node: J.value,
              bridge: e.bridge,
              onChanged: se
            }, null, 8, ["node", "bridge"])),
            l("section", lm, [
              l("header", sm, [
                l("div", null, [
                  l("h3", null, [
                    v[83] || (v[83] = I("DHCP-клиенты ", -1)),
                    l("small", null, y(ye.value.clients?.length || 0), 1)
                  ]),
                  v[84] || (v[84] = l("p", { class: "gw-hint" }, "Аренда DHCP не подтверждает текущую доступность клиента.", -1))
                ]),
                D(l("input", {
                  "onUpdate:modelValue": v[23] || (v[23] = ($) => ut.value = $),
                  type: "search",
                  "aria-label": "Поиск DHCP-клиентов",
                  placeholder: "Имя, IP или MAC"
                }, null, 512), [
                  [oe, ut.value]
                ])
              ]),
              l("div", om, [
                l("table", null, [
                  v[85] || (v[85] = l("thead", null, [
                    l("tr", null, [
                      l("th", null, "Клиент"),
                      l("th", null, "IP-адрес"),
                      l("th", null, "MAC-адрес")
                    ])
                  ], -1)),
                  l("tbody", null, [
                    (f(!0), h(N, null, ie(k.value, ($) => (f(), h("tr", {
                      key: $.macaddr + ":" + $.ipaddr
                    }, [
                      l("td", null, y($.hostname || "Без имени"), 1),
                      l("td", null, y($.ipaddr), 1),
                      l("td", null, y($.macaddr), 1)
                    ]))), 128))
                  ])
                ])
              ]),
              Wt.value.length ? T("", !0) : (f(), h("p", im, y(ut.value ? "Клиенты не найдены" : "Нет данных об арендах"), 1)),
              Wt.value.length ? (f(), h("footer", am, [
                l("span", rm, y((He.value - 1) * dt + 1) + "–" + y(Math.min(He.value * dt, Wt.value.length)) + " из " + y(Wt.value.length), 1),
                l("div", um, [
                  l("button", {
                    disabled: He.value === 1,
                    onClick: v[24] || (v[24] = ($) => He.value--)
                  }, "Назад", 8, dm),
                  l("span", cm, y(He.value) + " / " + y(w.value), 1),
                  l("button", {
                    disabled: He.value >= w.value,
                    onClick: v[25] || (v[25] = ($) => He.value++)
                  }, "Далее", 8, fm)
                ])
              ])) : T("", !0)
            ])
          ], 64)) : T("", !0),
          M.value === "wifi" ? (f(), ge(Ev, {
            key: J.value.id,
            node: J.value,
            bridge: e.bridge,
            onChanged: se
          }, null, 8, ["node", "bridge"])) : T("", !0),
          M.value === "services" ? (f(), ge(lg, {
            key: J.value.id,
            revision: ne.value,
            node: J.value,
            bridge: e.bridge,
            busy: g.value,
            updating: Oe.value,
            onPending: ze,
            onResume: an,
            onWebAccess: v[26] || (v[26] = ($) => Le("ssclash", "web_access", void 0, void 0, $)),
            onCatalog: rs,
            onSettings: U,
            onHelp: v[27] || (v[27] = ($) => t.value = !0),
            onOpenAdguard: ae,
            onAction: Le,
            onFirewallRestart: v[28] || (v[28] = ($) => o.value = J.value),
            onUpdate: nt
          }, null, 8, ["revision", "node", "bridge", "busy", "updating"])) : T("", !0),
          M.value === "backups" ? (f(), ge(Ng, {
            key: J.value.id,
            node: J.value,
            bridge: e.bridge
          }, null, 8, ["node", "bridge"])) : T("", !0),
          o.value ? (f(), ge(vh, {
            key: 7,
            node: o.value,
            bridge: e.bridge,
            onClose: v[29] || (v[29] = ($) => o.value = null),
            onChanged: se
          }, null, 8, ["node", "bridge"])) : T("", !0),
          n.value ? (f(), ge(ni, {
            key: 8,
            node: J.value,
            bridge: e.bridge,
            mode: n.value,
            onClose: v[30] || (v[30] = ($) => n.value = null),
            onChanged: se
          }, null, 8, ["node", "bridge", "mode"])) : T("", !0),
          V.value ? (f(), ge(Fe, {
            key: 9,
            title: "Установка служб",
            wide: !0,
            compact: !0,
            onClose: v[34] || (v[34] = ($) => {
              V.value = !1, m.value = "";
            })
          }, {
            default: Me(() => [
              v[91] || (v[91] = l("p", { class: "gw-hint" }, "Готовые комплекты с зависимостями для вашего OpenWrt. Скачивание на панель и установка на роутер выполняются отдельно.", -1)),
              g.value ? (f(), h("p", pm, "Получаем совместимые версии…")) : T("", !0),
              m.value ? (f(), h("p", vm, y(m.value), 1)) : T("", !0),
              l("div", gm, [
                (f(), h(N, null, ie(["podkop", "ssclash", "adguardhome"], ($) => l("details", {
                  key: $,
                  class: "gw-catalog-item"
                }, [
                  l("summary", hm, [
                    l("div", null, [
                      l("h3", null, y($ === "podkop" ? "Podkop" : $ === "ssclash" ? "SSClash-Go" : "AdGuard Home"), 1),
                      Ze(is, { id: $ }, null, 8, ["id"])
                    ]),
                    ye.value.services?.some((ue) => ue.id === $) ? (f(), h("span", mm, "Установлен")) : T("", !0)
                  ]),
                  l("div", bm, [
                    l("div", ym, [
                      l("label", wm, [
                        v[86] || (v[86] = I("Версия", -1)),
                        D(l("select", {
                          "onUpdate:modelValue": (ue) => r.value[$] = ue,
                          disabled: g.value
                        }, [
                          (f(!0), h(N, null, ie(d.value[$], (ue) => (f(), h("option", { key: ue }, y(ue), 1))), 128)),
                          d.value[$]?.length ? T("", !0) : (f(), h("option", km, y(g.value ? "Загружаем версии…" : "Нет совместимых версий"), 1))
                        ], 8, _m), [
                          [xe, r.value[$]]
                        ])
                      ]),
                      l("div", $m, [
                        pl($) ? (f(), h("button", {
                          key: 1,
                          disabled: g.value || ye.value.services?.some((ue) => ue.id === $),
                          class: "gw-primary",
                          onClick: (ue) => Le($, "install", pl($).id)
                        }, "Установить", 8, xm)) : (f(), h("button", {
                          key: 0,
                          disabled: g.value || !r.value[$],
                          onClick: (ue) => ri($)
                        }, "Скачать комплект на панель", 8, Cm)),
                        $ === "adguardhome" ? (f(), h("button", {
                          key: 2,
                          onClick: v[31] || (v[31] = (ue) => {
                            V.value = !1, t.value = !0;
                          })
                        }, "Настроить DNS")) : T("", !0)
                      ])
                    ]),
                    l("p", Sm, y(pl($) ? "Комплект сохранён на панели — установка доступна без GitHub." : "Панель скачает файлы и все совместимые зависимости."), 1),
                    $ === "adguardhome" ? (f(), h("p", Tm, "Установка не переключает DNS и DHCP.")) : T("", !0),
                    ye.value.services?.some((ue) => ue.id === $) ? (f(), h("p", Em, "Обновление установленной службы доступно в списке сервисов, если найдена новая совместимая версия.")) : T("", !0)
                  ])
                ])), 64))
              ]),
              l("section", Pm, [
                v[89] || (v[89] = l("h3", null, "Резерв версий на панели", -1)),
                l("label", Am, [
                  D(l("input", {
                    "onUpdate:modelValue": v[32] || (v[32] = ($) => E.value = $),
                    type: "checkbox"
                  }, null, 512), [
                    [Be, E.value]
                  ]),
                  v[87] || (v[87] = I(" Хранить установочные комплекты резервно", -1))
                ]),
                v[90] || (v[90] = l("p", { class: "gw-hint" }, "Резерв позволяет устанавливать сервисы при недоступном GitHub. Скачивание не запускает установку или обновление на роутере.", -1)),
                l("div", Um, [
                  D(l("select", {
                    "onUpdate:modelValue": v[33] || (v[33] = ($) => C.value = $),
                    "aria-label": "Количество резервных версий"
                  }, [...v[88] || (v[88] = [
                    l("option", { value: 2 }, "2 последние совместимые версии", -1),
                    l("option", { value: 3 }, "3 последние совместимые версии", -1)
                  ])], 512), [
                    [xe, C.value]
                  ]),
                  l("button", {
                    disabled: g.value,
                    onClick: ai
                  }, "Сохранить настройки", 8, Vm)
                ]),
                X.value ? (f(), h("p", Im, y(X.value), 1)) : T("", !0)
              ])
            ]),
            _: 1
          })) : T("", !0),
          t.value ? (f(), ge(du, {
            key: 10,
            node: J.value,
            bridge: e.bridge,
            onClose: v[35] || (v[35] = ($) => t.value = !1),
            onInstall: v[36] || (v[36] = ($) => {
              t.value = !1, rs();
            }),
            onStart: v[37] || (v[37] = ($) => {
              t.value = !1, Le("adguardhome", "start");
            })
          }, null, 8, ["node", "bridge"])) : T("", !0),
          M.value === "packages" ? (f(), ge(Vf, {
            key: J.value.id,
            node: J.value,
            bridge: e.bridge,
            "initial-query": Q.value,
            onChanged: se
          }, null, 8, ["node", "bridge", "initial-query"])) : T("", !0),
          M.value === "logs" ? (f(), h("div", Om, [
            l("div", Mm, [
              v[92] || (v[92] = l("h3", null, "Системный журнал", -1)),
              l("button", {
                disabled: g.value,
                onClick: v[38] || (v[38] = ($) => Re("logs"))
              }, "Обновить", 8, Rm)
            ]),
            l("pre", Dm, y(te.value || "Нет записей"), 1)
          ])) : T("", !0),
          M.value === "access" ? (f(), h("section", Nm, [
            J.value.managed && J.value.ssh_configured ? (f(), h("div", Fm, [
              v[93] || (v[93] = l("p", { class: "gw-hint" }, "RPC-компоненты и интерфейс LuCI Bot4VPS", -1)),
              l("button", {
                disabled: g.value,
                onClick: On
              }, "Обновить интеграцию Bot4VPS", 8, qm)
            ])) : T("", !0),
            J.value.bootstrap_state === "commit_pending" ? (f(), h("button", {
              key: 1,
              disabled: g.value,
              onClick: In
            }, "Завершить фиксацию подключения", 8, Hm)) : T("", !0),
            l("header", Lm, [
              v[94] || (v[94] = l("div", null, [
                l("h3", null, "Доступ к шлюзу"),
                l("p", { class: "gw-hint" }, "Данные API и SSH для подключения панели")
              ], -1)),
              l("button", {
                class: "gw-danger",
                disabled: g.value,
                onClick: fi
              }, y(J.value.deletion_pending ? "Повторить отзыв и удаление" : "Удалить шлюз"), 9, jm)
            ]),
            X.value ? (f(), h("p", Wm, y(X.value), 1)) : T("", !0),
            l("div", Bm, [
              l("form", {
                class: "gw-form",
                onSubmit: lt(ui, ["prevent"])
              }, [
                v[101] || (v[101] = l("h4", null, "API OpenWrt", -1)),
                l("p", Km, [
                  v[95] || (v[95] = I("Управление секретом: ", -1)),
                  l("a", {
                    href: J.value.access_url,
                    target: "_blank",
                    rel: "noopener noreferrer"
                  }, "LuCI → Службы → Bot4VPS ↗", 8, Gm)
                ]),
                l("label", null, [
                  v[96] || (v[96] = I("Имя шлюза", -1)),
                  D(l("input", {
                    "onUpdate:modelValue": v[39] || (v[39] = ($) => p.value.name = $),
                    placeholder: "Определится по модели роутера",
                    maxlength: "100"
                  }, null, 512), [
                    [oe, p.value.name]
                  ])
                ]),
                l("label", null, [
                  v[97] || (v[97] = I("Адрес API", -1)),
                  D(l("input", {
                    "onUpdate:modelValue": v[40] || (v[40] = ($) => p.value.url = $),
                    required: ""
                  }, null, 512), [
                    [oe, p.value.url]
                  ])
                ]),
                l("label", null, [
                  v[98] || (v[98] = I("Логин API", -1)),
                  D(l("input", {
                    "onUpdate:modelValue": v[41] || (v[41] = ($) => p.value.username = $),
                    required: ""
                  }, null, 512), [
                    [oe, p.value.username]
                  ])
                ]),
                l("label", null, [
                  v[99] || (v[99] = I("Новый секрет", -1)),
                  D(l("input", {
                    "onUpdate:modelValue": v[42] || (v[42] = ($) => p.value.password = $),
                    type: "password",
                    required: "",
                    autocomplete: "off"
                  }, null, 512), [
                    [oe, p.value.password]
                  ])
                ]),
                l("label", null, [
                  v[100] || (v[100] = I("SHA-256 сертификата", -1)),
                  D(l("input", {
                    "onUpdate:modelValue": v[43] || (v[43] = ($) => p.value.tls_sha256 = $)
                  }, null, 512), [
                    [oe, p.value.tls_sha256]
                  ])
                ]),
                l("div", zm, [
                  l("button", {
                    class: "gw-primary",
                    disabled: g.value
                  }, "Проверить и сохранить API", 8, Jm)
                ])
              ], 32),
              l("form", {
                class: "gw-form",
                onSubmit: lt(ci, ["prevent"])
              }, [
                v[108] || (v[108] = l("h4", null, "SSH для консоли", -1)),
                v[109] || (v[109] = l("p", { class: "gw-hint" }, "Пароль хранится зашифрованным мастер-ключом панели.", -1)),
                l("div", Ym, [
                  l("label", null, [
                    v[102] || (v[102] = I("SSH-логин", -1)),
                    D(l("input", {
                      "onUpdate:modelValue": v[44] || (v[44] = ($) => _.value.user = $),
                      required: ""
                    }, null, 512), [
                      [oe, _.value.user]
                    ])
                  ]),
                  l("label", null, [
                    v[103] || (v[103] = I("SSH-порт", -1)),
                    D(l("input", {
                      "onUpdate:modelValue": v[45] || (v[45] = ($) => _.value.port = $),
                      type: "number",
                      min: "1",
                      max: "65535",
                      required: ""
                    }, null, 512), [
                      [oe, _.value.port]
                    ])
                  ])
                ]),
                l("label", null, [
                  v[105] || (v[105] = I("Авторизация", -1)),
                  D(l("select", {
                    "onUpdate:modelValue": v[46] || (v[46] = ($) => _.value.auth_type = $)
                  }, [...v[104] || (v[104] = [
                    l("option", { value: "password" }, "Пароль", -1),
                    l("option", { value: "key" }, "SSH-ключ панели", -1)
                  ])], 512), [
                    [xe, _.value.auth_type]
                  ])
                ]),
                _.value.auth_type === "password" ? (f(), h("label", Xm, [
                  v[106] || (v[106] = I("SSH-пароль", -1)),
                  D(l("input", {
                    "onUpdate:modelValue": v[47] || (v[47] = ($) => _.value.password = $),
                    type: "password",
                    autocomplete: "off",
                    placeholder: J.value.ssh_configured ? "Оставьте пустым, чтобы сохранить текущий" : ""
                  }, null, 8, Zm), [
                    [oe, _.value.password]
                  ])
                ])) : (f(), h("label", Qm, [
                  v[107] || (v[107] = I("Путь к SSH-ключу", -1)),
                  D(l("input", {
                    "onUpdate:modelValue": v[48] || (v[48] = ($) => _.value.key_path = $),
                    placeholder: "/opt/bot4vps/keys/имя_ключа"
                  }, null, 512), [
                    [oe, _.value.key_path]
                  ])
                ])),
                l("div", e1, [
                  l("button", {
                    class: "gw-primary",
                    disabled: g.value
                  }, "Проверить и сохранить SSH", 8, t1)
                ])
              ], 32)
            ])
          ])) : T("", !0),
          M.value === "network" ? (f(), h(N, { key: 14 }, [
            Xt.value.length ? (f(), h("section", n1, [
              v[111] || (v[111] = l("h3", null, "WireGuard", -1)),
              (f(!0), h(N, null, ie(Xt.value, ($) => (f(), h("div", {
                key: $.name,
                class: "gw-panel"
              }, [
                l("h3", null, y($.name), 1),
                $.peers.length ? T("", !0) : (f(), h("p", l1, "Пиры не настроены")),
                (f(!0), h(N, null, ie($.peers, (ue, he) => (f(), h("div", {
                  key: he,
                  style: { "margin-top": "12px" }
                }, [
                  l("span", {
                    class: Ee(["gw-status", ue.recent_handshake ? "good" : "warn"])
                  }, y(ue.recent_handshake ? "Недавний handshake" : "Нет недавнего handshake"), 3),
                  l("p", null, y(ue.endpoint === "(none)" ? "Endpoint не определён" : ue.endpoint) + " · ↓ " + y(G(ue.rx_bytes)) + " · ↑ " + y(G(ue.tx_bytes)), 1)
                ]))), 128)),
                v[110] || (v[110] = l("p", { class: "gw-hint" }, "Handshake показывает обмен ключами за последние 3 минуты. Простаивающий туннель может не обмениваться пакетами.", -1))
              ]))), 128))
            ])) : T("", !0)
          ], 64)) : T("", !0)
        ])) : T("", !0)
      ], 64)),
      O.value ? (f(), ge(Fe, {
        key: 5,
        title: "Удаление шлюза",
        busy: g.value,
        onClose: v[50] || (v[50] = ($) => O.value = null)
      }, {
        default: Me(() => [
          l("h2", null, "Удалить " + y(O.value.name) + "?", 1),
          l("ol", null, [
            (f(!0), h(N, null, ie(O.value.steps, ($) => (f(), h("li", { key: $ }, y($), 1))), 128))
          ]),
          l("p", null, "Сохранятся: " + y(O.value.preserved.join(", ")) + ".", 1),
          O.value.manual ? (f(), h("p", s1, "Для вручную настроенного API может потребоваться отзыв учётной записи в LuCI. Без подтверждения отзыва панель сохранит запись.")) : T("", !0),
          l("div", o1, [
            l("button", {
              class: "gw-primary",
              disabled: g.value,
              onClick: pi
            }, "Да, отозвать доступ и удалить", 8, i1),
            l("button", {
              disabled: g.value,
              onClick: v[49] || (v[49] = ($) => O.value = null)
            }, "Отмена", 8, a1)
          ])
        ]),
        _: 1
      }, 8, ["busy"])) : T("", !0),
      L.value ? (f(), ge(zg, {
        key: 6,
        operation: L.value,
        busy: g.value,
        error: m.value,
        onApply: ii,
        onCancel: oi
      }, null, 8, ["operation", "busy", "error"])) : T("", !0)
    ], 2));
  }
});
function u1(e, t, n = !1, o = null) {
  const s = Hr(r1, { bridge: t, wizard: n, initialPlan: o });
  return s.mount(e), () => s.unmount();
}
export {
  u1 as mount
};
