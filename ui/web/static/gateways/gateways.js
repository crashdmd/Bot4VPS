// @__NO_SIDE_EFFECTS__
function Gl(e) {
  const t = /* @__PURE__ */ Object.create(null);
  for (const n of e.split(",")) t[n] = 1;
  return (n) => n in t;
}
const _e = {}, Zt = [], xt = () => {
}, eo = () => !1, ol = (e) => e.charCodeAt(0) === 111 && e.charCodeAt(1) === 110 && // uppercase letter
(e.charCodeAt(2) > 122 || e.charCodeAt(2) < 97), il = (e) => e.startsWith("onUpdate:"), De = Object.assign, zl = (e, t) => {
  const n = e.indexOf(t);
  n > -1 && e.splice(n, 1);
}, Vi = Object.prototype.hasOwnProperty, we = (e, t) => Vi.call(e, t), pe = Array.isArray, Lt = (e) => rn(e) === "[object Map]", Rt = (e) => rn(e) === "[object Set]", bs = (e) => rn(e) === "[object Date]", ge = (e) => typeof e == "function", Ee = (e) => typeof e == "string", ht = (e) => typeof e == "symbol", Ve = (e) => e !== null && typeof e == "object", to = (e) => (Ve(e) || ge(e)) && ge(e.then) && ge(e.catch), no = Object.prototype.toString, rn = (e) => no.call(e), Pi = (e) => rn(e).slice(8, -1), lo = (e) => rn(e) === "[object Object]", Jl = (e) => Ee(e) && e !== "NaN" && e[0] !== "-" && "" + parseInt(e, 10) === e, bn = /* @__PURE__ */ Gl(
  // the leading comma is intentional so empty string "" is also included
  ",key,ref,ref_for,ref_key,onVnodeBeforeMount,onVnodeMounted,onVnodeBeforeUpdate,onVnodeUpdated,onVnodeBeforeUnmount,onVnodeUnmounted"
), Ui = 1e4, al = (e) => {
  let t = /* @__PURE__ */ Object.create(null), n = 0;
  return ((o) => {
    const s = t[o];
    return s !== void 0 ? s : (++n > Ui && (t = /* @__PURE__ */ Object.create(null), n = 1), t[o] = e(o));
  });
}, Ai = /-\w/g, ut = /* @__PURE__ */ al((e) => e.replace(Ai, (t) => t.slice(1).toUpperCase())), Ei = /\B([A-Z])/g, Dt = /* @__PURE__ */ al(
  (e) => e.replace(Ei, "-$1").toLowerCase()
), so = /* @__PURE__ */ al((e) => e.charAt(0).toUpperCase() + e.slice(1)), yl = /* @__PURE__ */ al((e) => e ? `on${so(e)}` : ""), Le = (e, t) => !Object.is(e, t), Gn = (e, ...t) => {
  for (let n = 0; n < e.length; n++)
    e[n](...t);
}, oo = (e, t, n, o = !1) => {
  Object.defineProperty(e, t, {
    configurable: !0,
    enumerable: !1,
    writable: o,
    value: n
  });
}, En = (e) => {
  const t = parseFloat(e);
  return isNaN(t) ? e : t;
};
let ys;
const rl = () => ys || (ys = typeof globalThis < "u" ? globalThis : typeof self < "u" ? self : typeof window < "u" ? window : typeof global < "u" ? global : {});
function jt(e) {
  if (pe(e)) {
    const t = {};
    for (let n = 0; n < e.length; n++) {
      const o = e[n], s = Ee(o) ? Ri(o) : jt(o);
      if (s)
        for (const i in s)
          t[i] = s[i];
    }
    return t;
  } else if (Ee(e) || Ve(e))
    return e;
}
const Ii = /;(?![^(]*\))/g, Mi = /:([^]+)/, Oi = /"(?:[^"\\]|\\[^])*"|'(?:[^'\\]|\\[^])*'|\\[^]|\/\*[^]*?\*\//g;
function Ri(e) {
  const t = {};
  return e.replace(Oi, (n) => n.startsWith("/*") ? "" : n).split(Ii).forEach((n) => {
    if (n) {
      const o = n.split(Mi);
      o.length > 1 && (t[o[0].trim()] = o[1].trim());
    }
  }), t;
}
function Te(e) {
  let t = "";
  if (Ee(e))
    t = e;
  else if (pe(e))
    for (let n = 0; n < e.length; n++) {
      const o = Te(e[n]);
      o && (t += o + " ");
    }
  else if (Ve(e))
    for (const n in e)
      e[n] && (t += n + " ");
  return t.trim();
}
const Di = "itemscope,allowfullscreen,disablepictureinpicture,disableremoteplayback,formnovalidate,ismap,nomodule,novalidate,playsinline,readonly", Fi = /* @__PURE__ */ Gl(Di);
function io(e) {
  return !!e || e === "";
}
function qi(e, t, n) {
  if (e.length !== t.length) return !1;
  let o = !0;
  for (let s = 0; o && s < e.length; s++)
    o = mt(e[s], t[s], n);
  return o;
}
function ws(e, t, n) {
  if (e.size !== t.size) return !1;
  const o = Array.from(t), s = new Uint8Array(o.length);
  for (const i of e) {
    let a = -1;
    for (let u = 0; u < o.length; u++)
      if (!s[u] && mt(i, o[u], n)) {
        a = u;
        break;
      }
    if (a < 0) return !1;
    s[a] = 1;
  }
  return !0;
}
function Ni(e, t, n) {
  let o = Lt(e), s = Lt(t);
  if (o || s || (o = Rt(e), s = Rt(t), o || s))
    return o && s ? ws(e, t, n) : !1;
  const i = Object.keys(e).length, a = Object.keys(t).length;
  if (i !== a)
    return !1;
  for (const u in e) {
    const c = we(e, u), g = we(t, u);
    if (c && !g || !c && g || !mt(e[u], t[u], n))
      return !1;
  }
  return ks(e) === ks(t);
}
function _s(e, t, n, o) {
  n || (n = [/* @__PURE__ */ new Map(), /* @__PURE__ */ new Map()]);
  const [s, i] = n;
  if (s.has(e) || i.has(t))
    return s.get(e) === t && i.get(t) === e;
  s.set(e, t), i.set(t, e);
  const a = o(e, t, n);
  return s.delete(e), i.delete(t), a;
}
function mt(e, t, n) {
  if (e === t) return !0;
  let o = bs(e), s = bs(t);
  return o || s ? o && s ? e.getTime() === t.getTime() : !1 : (o = ht(e), s = ht(t), o || s ? e === t : (o = pe(e), s = pe(t), o || s ? o && s ? _s(e, t, n, qi) : !1 : (o = Ve(e), s = Ve(t), o || s ? !o || !s ? !1 : _s(e, t, n, Ni) : String(e) === String(t))));
}
function Yl(e, t) {
  return e.findIndex((n) => mt(n, t));
}
function ks(e) {
  return Object.getPrototypeOf(e) === null && e[Symbol.toPrimitive] == null && typeof e.toString != "function" && typeof e.valueOf != "function" ? rn(e) : String(e);
}
const ao = (e) => !!(e && e.__v_isRef === !0), b = (e) => Ee(e) ? e : e == null ? "" : pe(e) || Ve(e) && (e.toString === no || !ge(e.toString)) ? ao(e) ? b(e.value) : JSON.stringify(e, ro, 2) : String(e), ro = (e, t) => ao(t) ? ro(e, t.value) : Lt(t) ? {
  [`Map(${t.size})`]: [...t.entries()].reduce(
    (n, [o, s], i) => (n[wl(o, i) + " =>"] = s, n),
    {}
  )
} : Rt(t) ? {
  [`Set(${t.size})`]: [...t.values()].map((n) => wl(n))
} : ht(t) ? wl(t) : Ve(t) && !pe(t) && !lo(t) ? String(t) : t, wl = (e, t = "") => {
  var n;
  return (
    // Symbol.description in es2019+ so we need to cast here to pass
    // the lib: es2016 check
    ht(e) ? `Symbol(${(n = e.description) != null ? n : t})` : e
  );
};
let Ne;
class Hi {
  // TODO isolatedDeclarations "__v_skip"
  constructor(t = !1) {
    this.detached = t, this._active = !0, this._on = 0, this.effects = [], this.cleanups = [], this._isPaused = !1, this._warnOnRun = !0, this.__v_skip = !0, !t && Ne && (Ne.active ? (this.parent = Ne, this.index = (Ne.scopes || (Ne.scopes = [])).push(
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
      const n = Ne;
      try {
        return Ne = this, t();
      } finally {
        Ne = n;
      }
    }
  }
  /**
   * This should only be called on non-detached scopes
   * @internal
   */
  on() {
    ++this._on === 1 && (this.prevScope = Ne, Ne = this);
  }
  /**
   * This should only be called on non-detached scopes
   * @internal
   */
  off() {
    if (this._on > 0 && --this._on === 0) {
      if (Ne === this)
        Ne = this.prevScope;
      else {
        let t = Ne;
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
function Li() {
  return Ne;
}
let Ue;
const _l = /* @__PURE__ */ new WeakSet();
class uo {
  constructor(t) {
    this.fn = t, this.deps = void 0, this.depsTail = void 0, this.flags = 5, this.next = void 0, this.cleanup = void 0, this.scheduler = void 0, Ne && (Ne.active ? Ne.effects.push(this) : this.flags &= -2);
  }
  pause() {
    this.flags |= 64;
  }
  resume() {
    this.flags & 64 && (this.flags &= -65, _l.has(this) && (_l.delete(this), this.trigger()));
  }
  /**
   * @internal
   */
  notify() {
    this.flags & 2 && !(this.flags & 32) || this.flags & 8 || fo(this);
  }
  run() {
    if (!(this.flags & 1))
      return this.fn();
    this.flags |= 2, $s(this), po(this);
    const t = Ue, n = gt;
    Ue = this, gt = !0;
    try {
      return this.fn();
    } finally {
      vo(this), Ue = t, gt = n, this.flags &= -3;
    }
  }
  stop() {
    if (this.flags & 1) {
      for (let t = this.deps; t; t = t.nextDep)
        Ql(t);
      this.deps = this.depsTail = void 0, $s(this), this.onStop && this.onStop(), this.flags &= -2;
    }
  }
  trigger() {
    this.flags & 64 ? _l.add(this) : this.scheduler ? this.scheduler() : this.runIfDirty();
  }
  /**
   * @internal
   */
  runIfDirty() {
    Ml(this) && this.run();
  }
  get dirty() {
    return Ml(this);
  }
}
let co = 0, yn, wn;
function fo(e, t = !1) {
  if (e.flags |= 8, t) {
    e.next = wn, wn = e;
    return;
  }
  e.next = yn, yn = e;
}
function Xl() {
  co++;
}
function Zl() {
  if (--co > 0)
    return;
  if (wn) {
    let t = wn;
    for (wn = void 0; t; ) {
      const n = t.next;
      t.next = void 0, t.flags &= -9, t = n;
    }
  }
  let e;
  for (; yn; ) {
    let t = yn;
    for (yn = void 0; t; ) {
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
function po(e) {
  for (let t = e.deps; t; t = t.nextDep)
    t.version = -1, t.prevActiveLink = t.dep.activeLink, t.dep.activeLink = t;
}
function vo(e) {
  let t, n = e.depsTail, o = n;
  for (; o; ) {
    const s = o.prevDep;
    o.version === -1 ? (o === n && (n = s), Ql(o), ji(o)) : t = o, o.dep.activeLink = o.prevActiveLink, o.prevActiveLink = void 0, o = s;
  }
  e.deps = t, e.depsTail = n;
}
function Ml(e) {
  for (let t = e.deps; t; t = t.nextDep)
    if (t.dep.version !== t.version || t.dep.computed && (go(t.dep.computed) || t.dep.version !== t.version))
      return !0;
  return !!e._dirty;
}
function go(e) {
  if (e.flags & 4 && !(e.flags & 16) || (e.flags &= -17, e.globalVersion === xn) || (e.globalVersion = xn, !e.isSSR && e.flags & 128 && (!e.deps && !e._dirty || !Ml(e))))
    return;
  e.flags |= 2;
  const t = e.dep, n = Ue, o = gt;
  Ue = e, gt = !0;
  try {
    po(e);
    const s = e.fn(e._value);
    (t.version === 0 || Le(s, e._value)) && (e.flags |= 128, e._value = s, t.version++);
  } catch (s) {
    throw t.version++, s;
  } finally {
    Ue = n, gt = o, vo(e), e.flags &= -3;
  }
}
function Ql(e, t = !1) {
  const { dep: n, prevSub: o, nextSub: s } = e;
  if (o && (o.nextSub = s, e.prevSub = void 0), s && (s.prevSub = o, e.nextSub = void 0), n.subs === e && (n.subs = o, !o && n.computed)) {
    n.computed.flags &= -5;
    for (let i = n.computed.deps; i; i = i.nextDep)
      Ql(i, !0);
  }
  !t && !--n.sc && n.map && n.map.delete(n.key);
}
function ji(e) {
  const { prevDep: t, nextDep: n } = e;
  t && (t.nextDep = n, e.prevDep = void 0), n && (n.prevDep = t, e.nextDep = void 0);
}
let gt = !0;
const ho = [];
function St() {
  ho.push(gt), gt = !1;
}
function Tt() {
  const e = ho.pop();
  gt = e === void 0 ? !0 : e;
}
function $s(e) {
  const { cleanup: t } = e;
  if (e.cleanup = void 0, t) {
    const n = Ue;
    Ue = void 0;
    try {
      t();
    } finally {
      Ue = n;
    }
  }
}
let xn = 0;
class Wi {
  constructor(t, n) {
    this.sub = t, this.dep = n, this.version = n.version, this.nextDep = this.prevDep = this.nextSub = this.prevSub = this.prevActiveLink = void 0;
  }
}
class ul {
  // TODO isolatedDeclarations "__v_skip"
  constructor(t) {
    this.computed = t, this.version = 0, this.activeLink = void 0, this.subs = void 0, this.map = void 0, this.key = void 0, this.sc = 0, this.__v_skip = !0;
  }
  track(t) {
    if (!Ue || !gt || Ue === this.computed)
      return;
    let n = this.activeLink;
    if (n === void 0 || n.sub !== Ue)
      n = this.activeLink = new Wi(Ue, this), Ue.deps ? (n.prevDep = Ue.depsTail, Ue.depsTail.nextDep = n, Ue.depsTail = n) : Ue.deps = Ue.depsTail = n, mo(n);
    else if (n.version === -1 && (n.version = this.version, n.nextDep)) {
      const o = n.nextDep;
      o.prevDep = n.prevDep, n.prevDep && (n.prevDep.nextDep = o), n.prevDep = Ue.depsTail, n.nextDep = void 0, Ue.depsTail.nextDep = n, Ue.depsTail = n, Ue.deps === n && (Ue.deps = o);
    }
    return n;
  }
  trigger(t) {
    this.version++, xn++, this.notify(t);
  }
  notify(t) {
    Xl();
    try {
      for (let n = this.subs; n; n = n.prevSub)
        n.sub.notify() && n.sub.dep.notify();
    } finally {
      Zl();
    }
  }
}
function mo(e) {
  if (e.dep.sc++, e.sub.flags & 4) {
    const t = e.dep.computed;
    if (t && !e.dep.subs) {
      t.flags |= 20;
      for (let o = t.deps; o; o = o.nextDep)
        mo(o);
    }
    const n = e.dep.subs;
    n !== e && (e.prevSub = n, n && (n.nextSub = e)), e.dep.subs = e;
  }
}
const Ol = /* @__PURE__ */ new WeakMap(), Qt = /* @__PURE__ */ Symbol(
  ""
), Rl = /* @__PURE__ */ Symbol(
  ""
), Sn = /* @__PURE__ */ Symbol(
  ""
);
function Ge(e, t, n) {
  if (gt && Ue) {
    let o = Ol.get(e);
    o || Ol.set(e, o = /* @__PURE__ */ new Map());
    let s = o.get(n);
    s || (o.set(n, s = new ul()), s.map = o, s.key = n), s.track();
  }
}
function Et(e, t, n, o, s, i) {
  const a = Ol.get(e);
  if (!a) {
    xn++;
    return;
  }
  const u = (c) => {
    c && c.trigger();
  };
  if (Xl(), t === "clear")
    a.forEach(u);
  else {
    const c = pe(e), g = c && Jl(n);
    if (c && n === "length") {
      const m = Number(o);
      a.forEach((w, A) => {
        (A === "length" || A === Sn || !ht(A) && A >= m) && u(w);
      });
    } else
      switch ((n !== void 0 || a.has(void 0)) && u(a.get(n)), g && u(a.get(Sn)), t) {
        case "add":
          c ? g && u(a.get("length")) : (u(a.get(Qt)), Lt(e) && u(a.get(Rl)));
          break;
        case "delete":
          c || (u(a.get(Qt)), Lt(e) && u(a.get(Rl)));
          break;
        case "set":
          Lt(e) && u(a.get(Qt));
          break;
      }
  }
  Zl();
}
function tn(e) {
  const t = /* @__PURE__ */ Ce(e);
  return t === e || (Ge(t, "iterate", Sn), /* @__PURE__ */ dt(e)) ? t : /* @__PURE__ */ Vt(e) ? /* @__PURE__ */ Wt(e) ? t.map((n) => Bt(ct(n))) : t.map(Bt) : t.map(ct);
}
function dl(e) {
  return Ge(e = /* @__PURE__ */ Ce(e), "iterate", Sn), e;
}
function kt(e, t) {
  return /* @__PURE__ */ Vt(e) ? Bt(/* @__PURE__ */ Wt(e) ? ct(t) : t) : ct(t);
}
const Bi = {
  __proto__: null,
  [Symbol.iterator]() {
    return kl(this, Symbol.iterator, (e) => kt(this, e));
  },
  concat(...e) {
    return tn(this).concat(
      ...e.map((t) => pe(t) ? tn(t) : t)
    );
  },
  entries() {
    return kl(this, "entries", (e) => (e[1] = kt(this, e[1]), e));
  },
  every(e, t) {
    return Pt(this, "every", e, t, void 0, arguments);
  },
  filter(e, t) {
    return Pt(
      this,
      "filter",
      e,
      t,
      (n) => n.map((o) => kt(this, o)),
      arguments
    );
  },
  find(e, t) {
    return Pt(
      this,
      "find",
      e,
      t,
      (n) => kt(this, n),
      arguments
    );
  },
  findIndex(e, t) {
    return Pt(this, "findIndex", e, t, void 0, arguments);
  },
  findLast(e, t) {
    return Pt(
      this,
      "findLast",
      e,
      t,
      (n) => kt(this, n),
      arguments
    );
  },
  findLastIndex(e, t) {
    return Pt(this, "findLastIndex", e, t, void 0, arguments);
  },
  // flat, flatMap could benefit from ARRAY_ITERATE but are not straight-forward to implement
  forEach(e, t) {
    return Pt(this, "forEach", e, t, void 0, arguments);
  },
  includes(...e) {
    return $l(this, "includes", e);
  },
  indexOf(...e) {
    return $l(this, "indexOf", e);
  },
  join(e) {
    return tn(this).join(e);
  },
  // keys() iterator only reads `length`, no optimization required
  lastIndexOf(...e) {
    return $l(this, "lastIndexOf", e);
  },
  map(e, t) {
    return Pt(this, "map", e, t, void 0, arguments);
  },
  pop() {
    return dn(this, "pop");
  },
  push(...e) {
    return dn(this, "push", e);
  },
  reduce(e, ...t) {
    return xs(this, "reduce", e, t);
  },
  reduceRight(e, ...t) {
    return xs(this, "reduceRight", e, t);
  },
  shift() {
    return dn(this, "shift");
  },
  // slice could use ARRAY_ITERATE but also seems to beg for range tracking
  some(e, t) {
    return Pt(this, "some", e, t, void 0, arguments);
  },
  splice(...e) {
    return dn(this, "splice", e);
  },
  toReversed() {
    return tn(this).toReversed();
  },
  toSorted(e) {
    return tn(this).toSorted(e);
  },
  toSpliced(...e) {
    return tn(this).toSpliced(...e);
  },
  unshift(...e) {
    return dn(this, "unshift", e);
  },
  values() {
    return kl(this, "values", (e) => kt(this, e));
  }
};
function kl(e, t, n) {
  const o = dl(e), s = o[t], i = s.call(o);
  if (o !== e && !/* @__PURE__ */ dt(e)) {
    if (i[Symbol.toStringTag] === "Array Iterator") {
      const a = Object.create(Object.getPrototypeOf(i));
      return a.next = () => Cs(i.next(), n), s !== bo[t] && Object.defineProperties(a, {
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
    i._next = i.next, i.next = () => Cs(i._next(), n);
  }
  return i;
}
function Cs(e, t) {
  return e.done || (e.value = t(e.value)), e;
}
const bo = Array.prototype;
function Pt(e, t, n, o, s, i) {
  const a = dl(e), u = a !== e && !/* @__PURE__ */ dt(e), c = a[t];
  if (c !== bo[t]) {
    const w = c.apply(e, i);
    return u ? ct(w) : w;
  }
  let g = n;
  a !== e && (u ? g = function(w, A) {
    return n.call(this, kt(e, w), A, e);
  } : n.length > 2 && (g = function(w, A) {
    return n.call(this, w, A, e);
  }));
  const m = c.call(a, g, o);
  return u && s ? s(m) : m;
}
function xs(e, t, n, o) {
  const s = dl(e), i = s !== e && !/* @__PURE__ */ dt(e);
  let a = n, u = !1;
  s !== e && (i ? (u = o.length === 0, a = function(g, m, w) {
    return u && (u = !1, g = kt(e, g)), n.call(this, g, kt(e, m), w, e);
  }) : n.length > 3 && (a = function(g, m, w) {
    return n.call(this, g, m, w, e);
  }));
  const c = s[t](a, ...o);
  return u ? kt(e, c) : c;
}
function $l(e, t, n) {
  const o = /* @__PURE__ */ Ce(e);
  Ge(o, "iterate", Sn);
  const s = o[t](...n);
  return (s === -1 || s === !1) && /* @__PURE__ */ ls(n[0]) ? (n[0] = /* @__PURE__ */ Ce(n[0]), o[t](...n)) : s;
}
function dn(e, t, n = []) {
  St(), Xl();
  const o = (/* @__PURE__ */ Ce(e))[t].apply(e, n);
  return Zl(), Tt(), o;
}
const Ki = /* @__PURE__ */ Gl("__proto__,__v_isRef,__isVue"), yo = /* @__PURE__ */ new Set(
  /* @__PURE__ */ Object.getOwnPropertyNames(Symbol).filter((e) => e !== "arguments" && e !== "caller").map((e) => Symbol[e]).filter(ht)
);
function Gi(e) {
  ht(e) || (e = String(e));
  const t = /* @__PURE__ */ Ce(this);
  return Ge(t, "has", e), t.hasOwnProperty(e);
}
class wo {
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
      return o === (s ? i ? la : Co : i ? $o : ko).get(t) || // receiver is not the reactive proxy, but has the same prototype
      // this means the receiver is a user proxy of the reactive proxy
      Object.getPrototypeOf(t) === Object.getPrototypeOf(o) ? t : void 0;
    const a = pe(t);
    if (!s) {
      let c;
      if (a && (c = Bi[n]))
        return c;
      if (n === "hasOwnProperty")
        return Gi;
    }
    const u = Reflect.get(
      t,
      n,
      // if this is a proxy wrapping a ref, return methods using the raw ref
      // as receiver so that we don't have to call `toRaw` on the ref in all
      // its class methods
      /* @__PURE__ */ Je(t) ? t : o
    );
    if ((ht(n) ? yo.has(n) : Ki(n)) || (s || Ge(t, "get", n), i))
      return u;
    if (/* @__PURE__ */ Je(u)) {
      const c = a && Jl(n) ? u : u.value;
      return s && Ve(c) ? /* @__PURE__ */ Fl(c) : c;
    }
    return Ve(u) ? s ? /* @__PURE__ */ Fl(u) : /* @__PURE__ */ ts(u) : u;
  }
}
class _o extends wo {
  constructor(t = !1) {
    super(!1, t);
  }
  set(t, n, o, s) {
    let i = t[n];
    const a = pe(t) && Jl(n);
    if (!this._isShallow) {
      const g = /* @__PURE__ */ Vt(i);
      if (!/* @__PURE__ */ dt(o) && !/* @__PURE__ */ Vt(o) && (i = /* @__PURE__ */ Ce(i), o = /* @__PURE__ */ Ce(o)), !a && /* @__PURE__ */ Je(i) && !/* @__PURE__ */ Je(o))
        return g || (i.value = o), !0;
    }
    const u = a ? Number(n) < t.length : we(t, n), c = Reflect.set(
      t,
      n,
      o,
      /* @__PURE__ */ Je(t) ? t : s
    );
    return t === /* @__PURE__ */ Ce(s) && c && (u ? Le(o, i) && Et(t, "set", n, o) : Et(t, "add", n, o)), c;
  }
  deleteProperty(t, n) {
    const o = we(t, n);
    t[n];
    const s = Reflect.deleteProperty(t, n);
    return s && o && Et(t, "delete", n, void 0), s;
  }
  has(t, n) {
    const o = Reflect.has(t, n);
    return (!ht(n) || !yo.has(n)) && Ge(t, "has", n), o;
  }
  ownKeys(t) {
    return Ge(
      t,
      "iterate",
      pe(t) ? "length" : Qt
    ), Reflect.ownKeys(t);
  }
}
class zi extends wo {
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
const Ji = /* @__PURE__ */ new _o(), Yi = /* @__PURE__ */ new zi(), Xi = /* @__PURE__ */ new _o(!0);
const Dl = (e) => e, Fn = (e) => Reflect.getPrototypeOf(e);
function Zi(e, t, n) {
  return function(...o) {
    const s = this.__v_raw, i = /* @__PURE__ */ Ce(s), a = Lt(i), u = e === "entries" || e === Symbol.iterator && a, c = e === "keys" && a, g = s[e](...o), m = n ? Dl : t ? Bt : ct;
    return !t && Ge(
      i,
      "iterate",
      c ? Rl : Qt
    ), De(
      // inheriting all iterator properties
      Object.create(g),
      {
        // iterator protocol
        next() {
          const { value: w, done: A } = g.next();
          return A ? { value: w, done: A } : {
            value: u ? [m(w[0]), m(w[1])] : m(w),
            done: A
          };
        }
      }
    );
  };
}
function qn(e) {
  return function(...t) {
    return e === "delete" ? !1 : e === "clear" ? void 0 : this;
  };
}
function Qi(e, t) {
  const n = {
    get(s) {
      const i = this.__v_raw, a = /* @__PURE__ */ Ce(i), u = /* @__PURE__ */ Ce(s);
      e || (Le(s, u) && Ge(a, "get", s), Ge(a, "get", u));
      const { has: c } = Fn(a), g = t ? Dl : e ? Bt : ct;
      if (c.call(a, s))
        return g(i.get(s));
      if (c.call(a, u))
        return g(i.get(u));
      i !== a && i.get(s);
    },
    get size() {
      const s = this.__v_raw;
      return !e && Ge(/* @__PURE__ */ Ce(s), "iterate", Qt), s.size;
    },
    has(s) {
      const i = this.__v_raw, a = /* @__PURE__ */ Ce(i), u = /* @__PURE__ */ Ce(s);
      return e || (Le(s, u) && Ge(a, "has", s), Ge(a, "has", u)), s === u ? i.has(s) : i.has(s) || i.has(u);
    },
    forEach(s, i) {
      const a = this, u = a.__v_raw, c = /* @__PURE__ */ Ce(u), g = t ? Dl : e ? Bt : ct;
      return !e && Ge(c, "iterate", Qt), u.forEach((m, w) => s.call(i, g(m), g(w), a));
    }
  };
  return De(
    n,
    e ? {
      add: qn("add"),
      set: qn("set"),
      delete: qn("delete"),
      clear: qn("clear")
    } : {
      add(s) {
        const i = /* @__PURE__ */ Ce(this), a = Fn(i), u = /* @__PURE__ */ Ce(s), c = !t && !/* @__PURE__ */ dt(s) && !/* @__PURE__ */ Vt(s) ? u : s;
        return a.has.call(i, c) || Le(s, c) && a.has.call(i, s) || Le(u, c) && a.has.call(i, u) || (i.add(c), Et(i, "add", c, c)), this;
      },
      set(s, i) {
        !t && !/* @__PURE__ */ dt(i) && !/* @__PURE__ */ Vt(i) && (i = /* @__PURE__ */ Ce(i));
        const a = /* @__PURE__ */ Ce(this), { has: u, get: c } = Fn(a);
        let g = u.call(a, s);
        g || (s = /* @__PURE__ */ Ce(s), g = u.call(a, s));
        const m = c.call(a, s);
        return a.set(s, i), g ? Le(i, m) && Et(a, "set", s, i) : Et(a, "add", s, i), this;
      },
      delete(s) {
        const i = /* @__PURE__ */ Ce(this), { has: a, get: u } = Fn(i);
        let c = a.call(i, s);
        c || (s = /* @__PURE__ */ Ce(s), c = a.call(i, s)), u && u.call(i, s);
        const g = i.delete(s);
        return c && Et(i, "delete", s, void 0), g;
      },
      clear() {
        const s = /* @__PURE__ */ Ce(this), i = s.size !== 0, a = s.clear();
        return i && Et(
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
    n[s] = Zi(s, e, t);
  }), n;
}
function es(e, t) {
  const n = Qi(e, t);
  return (o, s, i) => s === "__v_isReactive" ? !e : s === "__v_isReadonly" ? e : s === "__v_isShallow" ? t : s === "__v_raw" ? o : Reflect.get(
    we(n, s) && s in o ? n : o,
    s,
    i
  );
}
const ea = {
  get: /* @__PURE__ */ es(!1, !1)
}, ta = {
  get: /* @__PURE__ */ es(!1, !0)
}, na = {
  get: /* @__PURE__ */ es(!0, !1)
};
const ko = /* @__PURE__ */ new WeakMap(), $o = /* @__PURE__ */ new WeakMap(), Co = /* @__PURE__ */ new WeakMap(), la = /* @__PURE__ */ new WeakMap();
function sa(e) {
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
function ts(e) {
  return /* @__PURE__ */ Vt(e) ? e : ns(
    e,
    !1,
    Ji,
    ea,
    ko
  );
}
// @__NO_SIDE_EFFECTS__
function oa(e) {
  return ns(
    e,
    !1,
    Xi,
    ta,
    $o
  );
}
// @__NO_SIDE_EFFECTS__
function Fl(e) {
  return ns(
    e,
    !0,
    Yi,
    na,
    Co
  );
}
function ns(e, t, n, o, s) {
  if (!Ve(e) || e.__v_raw && !(t && e.__v_isReactive) || e.__v_skip || !Object.isExtensible(e))
    return e;
  const i = s.get(e);
  if (i)
    return i;
  const a = sa(Pi(e));
  if (a === 0)
    return e;
  const u = new Proxy(
    e,
    a === 2 ? o : n
  );
  return s.set(e, u), u;
}
// @__NO_SIDE_EFFECTS__
function Wt(e) {
  return /* @__PURE__ */ Vt(e) ? /* @__PURE__ */ Wt(e.__v_raw) : !!(e && e.__v_isReactive);
}
// @__NO_SIDE_EFFECTS__
function Vt(e) {
  return !!(e && e.__v_isReadonly);
}
// @__NO_SIDE_EFFECTS__
function dt(e) {
  return !!(e && e.__v_isShallow);
}
// @__NO_SIDE_EFFECTS__
function ls(e) {
  return e ? !!e.__v_raw : !1;
}
// @__NO_SIDE_EFFECTS__
function Ce(e) {
  const t = e && e.__v_raw;
  return t ? /* @__PURE__ */ Ce(t) : e;
}
function ia(e) {
  return !we(e, "__v_skip") && Object.isExtensible(e) && oo(e, "__v_skip", !0), e;
}
const ct = (e) => Ve(e) ? /* @__PURE__ */ ts(e) : e, Bt = (e) => Ve(e) ? /* @__PURE__ */ Fl(e) : e;
// @__NO_SIDE_EFFECTS__
function Je(e) {
  return e ? e.__v_isRef === !0 : !1;
}
// @__NO_SIDE_EFFECTS__
function D(e) {
  return aa(e, !1);
}
function aa(e, t) {
  return /* @__PURE__ */ Je(e) ? e : new ra(e, t);
}
class ra {
  constructor(t, n) {
    this.dep = new ul(), this.__v_isRef = !0, this.__v_isShallow = !1, this._rawValue = n ? t : /* @__PURE__ */ Ce(t), this._value = n ? t : ct(t), this.__v_isShallow = n;
  }
  get value() {
    return this.dep.track(), this._value;
  }
  set value(t) {
    const n = this._rawValue, o = this.__v_isShallow || /* @__PURE__ */ dt(t) || /* @__PURE__ */ Vt(t);
    t = o ? t : /* @__PURE__ */ Ce(t), Le(t, n) && (this._rawValue = t, this._value = o ? t : ct(t), this.dep.trigger());
  }
}
function ua(e) {
  return /* @__PURE__ */ Je(e) ? e.value : e;
}
const da = {
  get: (e, t, n) => t === "__v_raw" ? e : ua(Reflect.get(e, t, n)),
  set: (e, t, n, o) => {
    const s = e[t];
    return /* @__PURE__ */ Je(s) && !/* @__PURE__ */ Je(n) ? (s.value = n, !0) : Reflect.set(e, t, n, o);
  }
};
function xo(e) {
  return /* @__PURE__ */ Wt(e) ? e : new Proxy(e, da);
}
class ca {
  constructor(t) {
    this.__v_isRef = !0, this._value = void 0;
    const n = this.dep = new ul(), { get: o, set: s } = t(n.track.bind(n), n.trigger.bind(n));
    this._get = o, this._set = s;
  }
  get value() {
    return this._value = this._get();
  }
  set value(t) {
    this._set(t);
  }
}
function fa(e) {
  return new ca(e);
}
class pa {
  constructor(t, n, o) {
    this.fn = t, this.setter = n, this._value = void 0, this.dep = new ul(this), this.__v_isRef = !0, this.deps = void 0, this.depsTail = void 0, this.flags = 16, this.globalVersion = xn - 1, this.next = void 0, this.effect = this, this.__v_isReadonly = !n, this.isSSR = o;
  }
  /**
   * @internal
   */
  notify() {
    if (this.flags |= 16, !(this.flags & 8) && // avoid infinite self recursion
    Ue !== this)
      return fo(this, !0), !0;
  }
  get value() {
    const t = this.dep.track();
    return go(this), t && (t.version = this.dep.version), this._value;
  }
  set value(t) {
    this.setter && this.setter(t);
  }
}
// @__NO_SIDE_EFFECTS__
function va(e, t, n = !1) {
  let o, s;
  return ge(e) ? o = e : (o = e.get, s = e.set), new pa(o, s, n);
}
const Nn = {}, Yn = /* @__PURE__ */ new WeakMap();
let Yt;
function ga(e, t = !1, n = Yt) {
  if (n) {
    let o = Yn.get(n);
    o || Yn.set(n, o = []), o.push(e);
  }
}
function ha(e, t, n = _e) {
  const { immediate: o, deep: s, once: i, scheduler: a, augmentJob: u, call: c } = n, g = (j) => s ? j : /* @__PURE__ */ dt(j) || s === !1 || s === 0 ? It(j, 1) : It(j);
  let m, w, A, V, L = !1, R = !1;
  if (/* @__PURE__ */ Je(e) ? (w = () => e.value, L = /* @__PURE__ */ dt(e)) : /* @__PURE__ */ Wt(e) ? (w = () => g(e), L = !0) : pe(e) ? (R = !0, L = e.some((j) => /* @__PURE__ */ Wt(j) || /* @__PURE__ */ dt(j)), w = () => e.map((j) => {
    if (/* @__PURE__ */ Je(j))
      return j.value;
    if (/* @__PURE__ */ Wt(j))
      return g(j);
    if (ge(j))
      return c ? c(j, 2) : j();
  })) : ge(e) ? t ? w = c ? () => c(e, 2) : e : w = () => {
    if (A) {
      St();
      try {
        A();
      } finally {
        Tt();
      }
    }
    const j = Yt;
    Yt = m;
    try {
      return c ? c(e, 3, [V]) : e(V);
    } finally {
      Yt = j;
    }
  } : w = xt, t && s) {
    const j = w, le = s === !0 ? 1 / 0 : s;
    w = () => It(j(), le);
  }
  const ne = Li(), X = () => {
    m.stop(), ne && ne.active && zl(ne.effects, m);
  };
  if (i && t) {
    const j = t;
    t = (...le) => {
      try {
        return j(...le);
      } finally {
        X();
      }
    };
  }
  let Z = R ? new Array(e.length).fill(Nn) : Nn;
  const ee = (j) => {
    if (!(!(m.flags & 1) || !m.dirty && !j))
      if (t) {
        const le = m.run();
        if (j || s || L || (R ? le.some((Q, I) => Le(Q, Z[I])) : Le(le, Z))) {
          const Q = Yt;
          St();
          try {
            A && A(), Yt = m;
            const I = [
              le,
              // pass undefined as the old value when it's changed for the first time
              Z === Nn ? void 0 : R && Z[0] === Nn ? [] : Z,
              V
            ];
            Z = le, c ? c(t, 3, I) : (
              // @ts-expect-error
              t(...I)
            );
          } finally {
            Yt = Q, Tt();
          }
        }
      } else
        m.run();
  };
  return u && u(ee), m = new uo(w), m.scheduler = a ? () => a(ee, !1) : ee, V = (j) => ga(j, !1, m), A = m.onStop = () => {
    const j = Yn.get(m);
    if (j) {
      if (c)
        c(j, 4);
      else
        for (const le of j) le();
      Yn.delete(m);
    }
  }, t ? o ? ee(!0) : Z = m.run() : a ? a(ee.bind(null, !0), !0) : m.run(), X.pause = m.pause.bind(m), X.resume = m.resume.bind(m), X.stop = X, X;
}
function It(e, t = 1 / 0, n) {
  if (t <= 0 || !Ve(e) || e.__v_skip || (n = n || /* @__PURE__ */ new Map(), (n.get(e) || 0) >= t))
    return e;
  if (n.set(e, t), t--, /* @__PURE__ */ Je(e))
    It(e.value, t, n);
  else if (pe(e))
    for (let o = 0; o < e.length; o++)
      It(e[o], t, n);
  else if (Rt(e) || Lt(e))
    e.forEach((o) => {
      It(o, t, n);
    });
  else if (lo(e)) {
    for (const o in e)
      It(e[o], t, n);
    for (const o of Object.getOwnPropertySymbols(e))
      Object.prototype.propertyIsEnumerable.call(e, o) && It(e[o], t, n);
  }
  return e;
}
function In(e, t, n, o) {
  try {
    return o ? e(...o) : e();
  } catch (s) {
    cl(s, t, n);
  }
}
function bt(e, t, n, o) {
  if (ge(e)) {
    const s = In(e, t, n, o);
    return s && to(s) && s.catch((i) => {
      cl(i, t, n, void 0, !0);
    }), s;
  }
  if (pe(e)) {
    const s = [];
    for (let i = 0; i < e.length; i++)
      s.push(bt(e[i], t, n, o));
    return s;
  }
}
function cl(e, t, n, o = !0, s = !1) {
  const i = t ? t.vnode : null, { errorHandler: a, throwUnhandledErrorInProduction: u } = t && t.appContext.config || _e;
  if (t) {
    let c = t.parent;
    const g = t.proxy, m = `https://vuejs.org/error-reference/#runtime-${n}`;
    for (; c; ) {
      const w = c.ec;
      if (w && !c.isUnmounted && // Async failures may outlive stopped scopes whose unmount effects
      // are deferred or discarded by Suspense.
      (!s || c.scope.active)) {
        for (let A = 0; A < w.length; A++)
          if (w[A](e, g, m) === !1)
            return;
      }
      c = c.parent;
    }
    if (a) {
      St(), In(a, null, 10, [
        e,
        g,
        m
      ]), Tt();
      return;
    }
  }
  ma(e, n, i, o, u);
}
function ma(e, t, n, o = !0, s = !1) {
  if (s)
    throw e;
  console.error(e);
}
const Qe = [];
let pt = -1;
const $t = [];
let Ht = null, nn = 0;
const So = /* @__PURE__ */ Promise.resolve();
let Xn = null;
function ss(e) {
  const t = Xn || So;
  return e ? t.then(this ? e.bind(this) : e) : t;
}
function ba(e) {
  let t = pt + 1, n = Qe.length;
  for (; t < n; ) {
    const o = t + n >>> 1, s = Qe[o], i = Tn(s);
    i < e || i === e && s.flags & 2 ? t = o + 1 : n = o;
  }
  return t;
}
function os(e) {
  if (!(e.flags & 1)) {
    const t = Tn(e), n = Qe[Qe.length - 1];
    !n || // fast path when the job id is larger than the tail
    !(e.flags & 2) && t >= Tn(n) ? Qe.push(e) : Qe.splice(ba(t), 0, e), e.flags |= 1, To();
  }
}
function To() {
  Xn || (Xn = So.then(Uo));
}
function ya(e) {
  if (!pe(e))
    Ht && e.id === -1 ? Ht.splice(nn + 1, 0, e) : e.flags & 1 || ($t.push(e), e.flags |= 1);
  else
    for (let t = 0; t < e.length; t++)
      $t.push(e[t]);
  To();
}
function Vo(e, t, n, o = pt + 1) {
  for (; o < Qe.length; o++) {
    const s = Qe[o];
    if (s && s.flags & 2) {
      if (e && s.id !== e.uid || t !== void 0 && !(s.id >= t))
        continue;
      Qe.splice(o, 1), o = e ? o - 1 : pt, s.flags & 4 && (s.flags &= -2), s(), s.flags & 4 || (s.flags &= -2);
    }
  }
}
function Po(e, t, n = 0) {
  if ($t.length) {
    let o = $t, s = 0;
    if (t) {
      o = [];
      for (let a = 0; a < $t.length; a++) {
        const u = $t[a];
        (u.i !== void 0 ? !u.i || u.i.uid < n : t.has(u)) ? $t[s++] = u : o.push(u);
      }
    }
    const i = [...new Set(o)].sort((a, u) => Tn(a) - Tn(u));
    if ($t.length = s, Ht) {
      for (let a = 0; a < i.length; a++)
        Ht.push(i[a]);
      return;
    }
    for (Ht = i, nn = 0; nn < Ht.length; nn++) {
      const a = Ht[nn];
      a.flags & 4 && (a.flags &= -2), a.flags & 8 || a(), a.flags &= -2;
    }
    Ht = null, nn = 0;
  }
}
let Cl = !1;
function wa(e, t) {
  if (Cl) {
    e();
    return;
  }
  const n = t === void 0 ? void 0 : new Set($t);
  e(), Cl = !0;
  try {
    Vo(void 0, t), Po(void 0, n, t);
  } finally {
    Cl = !1;
  }
}
const Tn = (e) => e.id == null ? e.flags & 2 ? -1 : 1 / 0 : e.id;
function Uo(e) {
  try {
    for (pt = 0; pt < Qe.length; pt++) {
      const t = Qe[pt];
      t && !(t.flags & 8) && (t.flags & 4 && (t.flags &= -2), In(
        t,
        t.i,
        t.i ? 15 : 14
      ), t.flags & 4 || (t.flags &= -2));
    }
  } finally {
    for (; pt < Qe.length; pt++) {
      const t = Qe[pt];
      t && (t.flags &= -2);
    }
    pt = -1, Qe.length = 0, Po(), Xn = null, (Qe.length || $t.length) && Uo();
  }
}
let ze = null, Ao = null;
function Zn(e) {
  const t = ze;
  return ze = e, Ao = e && e.type.__scopeId || null, t;
}
function Ie(e, t = ze, n) {
  if (!t || e._n)
    return e;
  const o = (...s) => {
    o._d && Fs(-1);
    const i = Zn(t), a = Ot.length;
    let u;
    try {
      u = e(...s);
    } finally {
      for (let c = Ot.length; c > a; c--) cs();
      Zn(i), o._d && Fs(1);
    }
    return u;
  };
  return o._n = !0, o._c = !0, o._d = !0, o;
}
function H(e, t) {
  if (ze === null)
    return e;
  const n = hl(ze), o = e.dirs || (e.dirs = []);
  for (let s = 0; s < t.length; s++) {
    let [i, a, u, c = _e] = t[s];
    i && (ge(i) && (i = {
      mounted: i,
      updated: i
    }), i.deep && It(a), o.push({
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
function zt(e, t, n, o) {
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
    a ? c.oldValue = a[u].value : o === "mounted" && c.oldValue !== void 0 && (c = De({}, c, { oldValue: void 0 }));
    let g = c.dir[o];
    g && (St(), bt(g, n, 8, [
      e.el,
      c,
      s,
      t
    ]), Tt());
  }
}
function _a(e, t) {
  if (et) {
    let n = et.provides;
    const o = et.parent && et.parent.provides;
    o === n && (n = et.provides = Object.create(o)), n[e] = t;
  }
}
function zn(e, t, n = !1) {
  const o = ii();
  if (o || sn) {
    let s = sn ? sn._context.provides : o ? o.parent == null || o.ce ? o.vnode.appContext && o.vnode.appContext.provides : o.parent.provides : void 0;
    if (s && e in s)
      return s[e];
    if (arguments.length > 1)
      return n && ge(t) ? t.call(o && o.proxy) : t;
  }
}
const ka = /* @__PURE__ */ Symbol.for("v-scx"), $a = () => zn(ka);
function Ca(e, t) {
  return is(
    e,
    null,
    { flush: "sync" }
  );
}
function We(e, t, n) {
  return is(e, t, n);
}
function is(e, t, n = _e) {
  const { immediate: o, deep: s, flush: i, once: a } = n, u = De({}, n), c = t && o || !t && i !== "post";
  let g;
  if (An) {
    if (i === "sync") {
      const V = $a();
      g = V.__watcherHandles || (V.__watcherHandles = []);
    } else if (!c) {
      const V = () => {
      };
      return V.stop = xt, V.resume = xt, V.pause = xt, V;
    }
  }
  const m = et;
  u.call = (V, L, R) => bt(V, m, L, R);
  let w = !1;
  i === "post" ? u.scheduler = (V) => {
    V.i = m, Ke(V, m && m.suspense);
  } : i !== "sync" && (w = !0, u.scheduler = (V, L) => {
    L ? V() : os(V);
  }), u.augmentJob = (V) => {
    t && (V.flags |= 4), w && (V.flags |= 2, m && (V.id = m.uid, V.i = m));
  };
  const A = ha(e, t, u);
  return An && (g ? g.push(A) : c && A()), A;
}
function xa(e, t, n) {
  const o = this.proxy, s = Ee(e) ? e.includes(".") ? Eo(o, e) : () => o[e] : e.bind(o, o);
  let i;
  ge(t) ? i = t : (i = t.handler, n = t);
  const a = Mn(this), u = is(s, i.bind(o), n);
  return a(), u;
}
function Eo(e, t) {
  const n = t.split(".");
  return () => {
    let o = e;
    for (let s = 0; s < n.length && o; s++)
      o = o[n[s]];
    return o;
  };
}
const Nt = /* @__PURE__ */ new WeakMap(), Io = /* @__PURE__ */ Symbol("_vte"), fl = (e) => e.__isTeleport, Xt = (e) => e && (e.disabled || e.disabled === ""), Sa = (e) => e && (e.defer || e.defer === ""), Ss = (e) => typeof SVGElement < "u" && e instanceof SVGElement, Ts = (e) => typeof MathMLElement == "function" && e instanceof MathMLElement, ql = (e, t) => {
  const n = e && e.to;
  return Ee(n) ? t ? t(n) : null : n;
}, Ta = {
  name: "Teleport",
  __isTeleport: !0,
  process(e, t, n, o, s, i, a, u, c, g) {
    const {
      mc: m,
      pc: w,
      pbc: A,
      o: { insert: V, querySelector: L, createText: R, createComment: ne, parentNode: X }
    } = g, Z = Xt(t.props);
    let { dynamicChildren: ee } = t;
    const j = (I, E, P) => {
      I.shapeFlag & 16 && m(
        I.children,
        E,
        P,
        s,
        i,
        a,
        u,
        c
      );
    }, le = (I = t) => {
      const E = Xt(I.props), P = I.target = ql(I.props, L), S = Nl(P, I, R, V);
      P && (a !== "svg" && Ss(P) ? a = "svg" : a !== "mathml" && Ts(P) && (a = "mathml"), s && s.isCE && (s.ce._teleportTargets || (s.ce._teleportTargets = /* @__PURE__ */ new Set())).add(P), E || (j(I, P, S), vn(I, !1)));
    }, Q = (I) => {
      const E = () => {
        if (Nt.get(I) === E) {
          if (Nt.delete(I), Xt(I.props)) {
            const P = X(I.el) || n;
            j(I, P, I.anchor), vn(I, !0);
          }
          le(I);
        }
      };
      Nt.set(I, E), Ke(E, i);
    };
    if (e == null) {
      const I = t.el = R(""), E = t.anchor = R("");
      if (V(I, n, o), V(E, n, o), Sa(t.props) || i && i.pendingBranch) {
        Q(t);
        return;
      }
      Z && (j(t, n, E), vn(t, !0)), le();
    } else {
      t.el = e.el;
      const I = t.anchor = e.anchor, E = Nt.get(e);
      if (E) {
        E.flags |= 8, Nt.delete(e), Q(t);
        return;
      }
      t.targetStart = e.targetStart;
      const P = t.target = e.target, S = t.targetAnchor = e.targetAnchor, C = Xt(e.props), ie = C ? n : P, ke = C ? I : S;
      if (a === "svg" || Ss(P) ? a = "svg" : (a === "mathml" || Ts(P)) && (a = "mathml"), ee ? (A(
        e.dynamicChildren,
        ee,
        ie,
        s,
        i,
        a,
        u
      ), ds(e, t, !0)) : c || w(
        e,
        t,
        ie,
        ke,
        s,
        i,
        a,
        u,
        !1
      ), Z)
        C ? t.props && e.props && t.props.to !== e.props.to && (t.props.to = e.props.to) : Hn(
          t,
          n,
          I,
          g,
          1
        );
      else if ((t.props && t.props.to) !== (e.props && e.props.to)) {
        const ae = ql(t.props, L);
        ae && (t.target = ae, Hn(
          t,
          ae,
          null,
          g,
          0
        ));
      } else C && Hn(
        t,
        P,
        S,
        g,
        1
      );
      vn(t, Z);
    }
  },
  remove(e, t, n, { um: o, o: { remove: s } }, i) {
    const {
      shapeFlag: a,
      children: u,
      anchor: c,
      targetStart: g,
      targetAnchor: m,
      target: w,
      props: A
    } = e, V = Xt(A), L = i || !V, R = Nt.get(e);
    if (R && (R.flags |= 8, Nt.delete(e)), w && (s(g), s(m)), i && s(c), !R && (V || w) && a & 16)
      for (let ne = 0; ne < u.length; ne++) {
        const X = u[ne];
        o(
          X,
          t,
          n,
          L,
          !!X.dynamicChildren
        );
      }
  },
  move: Hn,
  hydrate: Va
};
function Hn(e, t, n, { o: { insert: o }, m: s }, i = 2) {
  i === 0 && (e.targetStart && o(e.targetStart, t, n), o(e.targetAnchor, t, n), n = e.targetAnchor);
  const { el: a, anchor: u, shapeFlag: c, children: g, props: m } = e, w = i === 2;
  if (w && o(a, t, n), !Nt.has(e) && (!w || Xt(m)) && c & 16)
    for (let A = 0; A < g.length; A++)
      s(
        g[A],
        t,
        n,
        2
      );
  w && o(u, t, n);
}
function Va(e, t, n, o, s, i, {
  o: { nextSibling: a, parentNode: u, querySelector: c, insert: g, createText: m }
}, w) {
  function A(ne, X) {
    let Z = X;
    for (; Z; ) {
      if (Z && Z.nodeType === 8) {
        if (Z.data === "teleport start anchor")
          t.targetStart = Z;
        else if (Z.data === "teleport anchor") {
          t.targetAnchor = Z, ne._lpa = t.targetAnchor && a(t.targetAnchor);
          break;
        }
      }
      Z = a(Z);
    }
  }
  function V(ne, X) {
    X.anchor = w(
      a(ne),
      X,
      u(ne),
      n,
      o,
      s,
      i
    );
  }
  const L = t.target = ql(
    t.props,
    c
  ), R = Xt(t.props);
  if (L) {
    const ne = L._lpa || L.firstChild;
    t.shapeFlag & 16 && (R ? (A(L, ne), V(e, t), t.targetAnchor || Nl(
      L,
      t,
      m,
      g,
      // if target is the same as the main view, insert anchors before current node
      // to avoid hydrating mismatch
      u(e) === L ? e : null
    )) : (t.anchor = a(e), A(L, ne), t.targetAnchor || Nl(L, t, m, g), w(
      ne && a(ne),
      t,
      L,
      n,
      o,
      s,
      i
    ))), vn(t, R);
  } else R && t.shapeFlag & 16 && (V(e, t), t.targetStart = e, t.targetAnchor = a(e));
  return t.anchor && a(t.anchor);
}
const Pa = Ta;
function vn(e, t) {
  const n = e.ctx;
  n && n.ut && (t ? n.ut(e.el, e.anchor) : n.ut(e.targetStart, e.targetAnchor));
}
function Nl(e, t, n, o, s = null) {
  const i = t.targetStart = n(""), a = t.targetAnchor = n("");
  return i[Io] = a, e && (o(i, e, s), o(a, e, s)), a;
}
const xl = /* @__PURE__ */ Symbol("_leaveCb");
function Ua(e) {
  let t = e[0];
  if (e.length > 1) {
    for (const n of e)
      if (n.type !== ft) {
        t = n;
        break;
      }
  }
  return t;
}
function Mo(e) {
  if (!as(e))
    return fl(e.type) && e.children ? Ua(e.children) : e;
  if (e.component)
    return e.component.subTree;
  const { shapeFlag: t, children: n } = e;
  if (n) {
    if (t & 16)
      return n[0];
    if (t & 32 && ge(n.default))
      return n.default();
  }
}
function _n(e, t) {
  if (e.shapeFlag & 6 && e.component) {
    e.transition = t;
    const n = e.component.subTree;
    _n(
      fl(n.type) && Mo(n) || n,
      t
    );
  } else if (e.shapeFlag & 128) {
    const n = e.suspense;
    if (n) {
      const o = n.isHydrating ? n.pendingBranch : n.activeBranch;
      o && _n(o, t.clone(o));
    } else
      e.ssContent.transition = t.clone(e.ssContent), e.ssFallback.transition = t.clone(e.ssFallback);
  } else if (e.transition = t, e.type === q && pe(e.children)) {
    const n = Wo(e.children, !1);
    n && _n(n, t);
  }
}
function Hl(e) {
  if (e.component)
    return Hl(e.component.subTree);
  if (e.type === q) {
    const t = pe(e.children) && Wo(e.children, !1);
    return t ? Hl(t) : void 0;
  }
  if (e.type !== ft)
    return e;
}
// @__NO_SIDE_EFFECTS__
function Me(e, t) {
  return ge(e) ? (
    // #8236: extend call and options.name access are considered side-effects
    // by Rollup, so we have to wrap it in a pure-annotated IIFE.
    De({ name: e.name }, t, { setup: e })
  ) : e;
}
function Oo(e) {
  e.ids = [e.ids[0] + e.ids[2]++ + "-", 0, 0];
}
function Vs(e, t) {
  let n;
  return !!((n = Object.getOwnPropertyDescriptor(e, t)) && !n.configurable);
}
const Qn = /* @__PURE__ */ new WeakMap();
function kn(e, t, n, o, s = !1) {
  if (pe(e)) {
    e.forEach(
      (R, ne) => kn(
        R,
        t && (pe(t) ? t[ne] : t),
        n,
        o,
        s
      )
    );
    return;
  }
  if (ln(o) && !s) {
    o.shapeFlag & 512 && o.type.__asyncResolved && o.component.subTree.component && kn(e, t, n, o.component.subTree);
    return;
  }
  const i = o.shapeFlag & 4 ? hl(o.component) : o.el, a = s ? null : i, { i: u, r: c } = e, g = t && t.r, m = u.refs === _e ? u.refs = {} : u.refs, w = u.setupState, A = /* @__PURE__ */ Ce(w), V = w === _e ? eo : (R) => Vs(m, R) ? !1 : we(A, R), L = (R, ne) => !(ne && Vs(m, ne));
  if (g != null && g !== c) {
    if (Ps(t), Ee(g))
      m[g] = null, V(g) && (w[g] = null);
    else if (/* @__PURE__ */ Je(g)) {
      const R = t;
      L(g, R.k) && (g.value = null), R.k && (m[R.k] = null);
    }
  }
  if (ge(c))
    In(c, u, 12, [a, m]);
  else {
    const R = Ee(c), ne = /* @__PURE__ */ Je(c);
    if (R || ne) {
      const X = () => {
        if (e.f) {
          const Z = R ? V(c) ? w[c] : m[c] : L() || !e.k ? c.value : m[e.k];
          if (s)
            pe(Z) && zl(Z, i);
          else if (pe(Z))
            Z.includes(i) || Z.push(i);
          else if (R)
            m[c] = [i], V(c) && (w[c] = m[c]);
          else {
            const ee = [i];
            L(c, e.k) && (c.value = ee), e.k && (m[e.k] = ee);
          }
        } else R ? (m[c] = a, V(c) && (w[c] = a)) : ne && (L(c, e.k) && (c.value = a), e.k && (m[e.k] = a));
      };
      if (a) {
        const Z = () => {
          X(), Qn.delete(e);
        };
        Z.id = -1, Qn.set(e, Z), Ke(Z, n);
      } else
        Ps(e), X();
    }
  }
}
function Ps(e) {
  const t = Qn.get(e);
  t && (t.flags |= 8, Qn.delete(e));
}
rl().requestIdleCallback;
rl().cancelIdleCallback;
const ln = (e) => !!e.type.__asyncLoader, as = (e) => e.type.__isKeepAlive;
function Aa(e, t) {
  Ro(e, "a", t);
}
function Ea(e, t) {
  Ro(e, "da", t);
}
function Ro(e, t, n = et) {
  const o = e.__wdc || (e.__wdc = () => {
    let s = n;
    for (; s; ) {
      if (s.isDeactivated)
        return;
      s = s.parent;
    }
    return e();
  });
  if (Vn(t, o, n), n) {
    let s = n.parent;
    for (; s && s.parent; )
      as(s.parent.vnode) && Ia(o, t, n, s), s = s.parent;
  }
}
function Ia(e, t, n, o) {
  const s = Vn(
    t,
    e,
    o,
    !0
    /* prepend */
  ), i = Vn(
    "um",
    () => zl(o[t], s),
    n
  );
  i.flags = 16;
}
function Vn(e, t, n = et, o = !1) {
  if (n) {
    const s = n[e] || (n[e] = []), i = t.__weh || (t.__weh = (...a) => {
      St();
      const u = Mn(n), c = bt(t, n, e, a);
      return u(), Tt(), c;
    });
    return o ? s.unshift(i) : s.push(i), i;
  }
}
const Ft = (e) => (t, n = et) => {
  (!An || e === "sp") && Vn(e, (...o) => t(...o), n);
}, Ma = Ft("bm"), ot = Ft("m"), Oa = Ft(
  "bu"
), Ra = Ft("u"), Do = Ft(
  "bum"
), yt = Ft("um"), Da = Ft(
  "sp"
), Fa = Ft("rtg"), qa = Ft("rtc");
function Na(e, t = et) {
  Vn("ec", e, t);
}
const Ha = /* @__PURE__ */ Symbol.for("v-ndc");
function oe(e, t, n, o) {
  let s;
  const i = n, a = pe(e);
  if (a || Ee(e)) {
    const u = a && /* @__PURE__ */ Wt(e);
    let c = !1, g = !1;
    u && (c = !/* @__PURE__ */ dt(e), g = /* @__PURE__ */ Vt(e), e = dl(e)), s = new Array(e.length);
    for (let m = 0, w = e.length; m < w; m++)
      s[m] = t(
        c ? g ? Bt(ct(e[m])) : ct(e[m]) : e[m],
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
  else if (Ve(e))
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
function La(e, t, n, o, s, i) {
  if (n == null && (n = {}), ze.ce || ze.parent && ln(ze.parent) && ze.parent.ce) {
    const g = n, m = Object.keys(g).length > 0;
    return f(), me(
      q,
      null,
      [Ae("slot", g, o)],
      m ? -2 : 64
    );
  }
  let a = e[t];
  a && a._c && (a._d = !1);
  const u = Ot.length;
  f();
  let c;
  try {
    const g = a && Fo(a(n)), m = n.key || i || // slot content array of a dynamic conditional slot may have a branch
    // key attached in the `createSlots` helper, respect that
    g && g.key;
    c = me(
      q,
      {
        key: (m && !ht(m) ? m : `_${t}`) + // #7256 force differentiate fallback content from actual content
        (!g && o ? "_fb" : "")
      },
      g || (o ? o() : []),
      g && e._ === 1 ? 64 : -2
    );
  } catch (g) {
    for (let m = Ot.length; m > u; m--) cs();
    throw g;
  } finally {
    a && a._c && (a._d = !0);
  }
  return c.scopeId && (c.slotScopeIds = [c.scopeId + "-s"]), c;
}
function Fo(e) {
  return e.some((t) => gl(t) ? !(t.type === ft || t.type === q && !Fo(t.children)) : !0) ? e : null;
}
const Ll = (e) => e ? ai(e) ? hl(e) : Ll(e.parent) : null, $n = (
  // Move PURE marker to new line to workaround compiler discarding it
  // due to type annotation
  /* @__PURE__ */ De(/* @__PURE__ */ Object.create(null), {
    $: (e) => e,
    $el: (e) => e.vnode.el,
    $data: (e) => e.data,
    $props: (e) => e.props,
    $attrs: (e) => e.attrs,
    $slots: (e) => e.slots,
    $refs: (e) => e.refs,
    $parent: (e) => Ll(e.parent),
    $root: (e) => Ll(e.root),
    $host: (e) => e.ce,
    $emit: (e) => e.emit,
    $options: (e) => No(e),
    $forceUpdate: (e) => e.f || (e.f = () => {
      os(e.update);
    }),
    $nextTick: (e) => e.n || (e.n = ss.bind(e.proxy)),
    $watch: (e) => xa.bind(e)
  })
), Sl = (e, t) => e !== _e && !e.__isScriptSetup && we(e, t), ja = {
  get({ _: e }, t) {
    if (t === "__v_skip")
      return !0;
    const { ctx: n, setupState: o, data: s, props: i, accessCache: a, type: u, appContext: c } = e;
    if (t[0] !== "$") {
      const A = a[t];
      if (A !== void 0)
        switch (A) {
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
        if (Sl(o, t))
          return a[t] = 1, o[t];
        if (s !== _e && we(s, t))
          return a[t] = 2, s[t];
        if (we(i, t))
          return a[t] = 3, i[t];
        if (n !== _e && we(n, t))
          return a[t] = 4, n[t];
        jl && (a[t] = 0);
      }
    }
    const g = $n[t];
    let m, w;
    if (g)
      return t === "$attrs" && Ge(e.attrs, "get", ""), g(e);
    if (
      // css module (injected by vue-loader)
      (m = u.__cssModules) && (m = m[t])
    )
      return m;
    if (n !== _e && we(n, t))
      return a[t] = 4, n[t];
    if (
      // global properties
      w = c.config.globalProperties, we(w, t)
    )
      return w[t];
  },
  set({ _: e }, t, n) {
    const { data: o, setupState: s, ctx: i } = e;
    return Sl(s, t) ? (s[t] = n, !0) : o !== _e && we(o, t) ? (o[t] = n, !0) : we(e.props, t) || t[0] === "$" && t.slice(1) in e ? !1 : (i[t] = n, !0);
  },
  has({
    _: { data: e, setupState: t, accessCache: n, ctx: o, appContext: s, props: i, type: a }
  }, u) {
    let c;
    return !!(n[u] || e !== _e && u[0] !== "$" && we(e, u) || Sl(t, u) || we(i, u) || we(o, u) || we($n, u) || we(s.config.globalProperties, u) || (c = a.__cssModules) && c[u]);
  },
  defineProperty(e, t, n) {
    return n.get != null ? e._.accessCache[t] = 0 : we(n, "value") && this.set(e, t, n.value, null), Reflect.defineProperty(e, t, n);
  }
};
function Us(e) {
  return pe(e) ? e.reduce(
    (t, n) => (t[n] = null, t),
    {}
  ) : e;
}
let jl = !0;
function Wa(e) {
  const t = No(e), n = e.proxy, o = e.ctx;
  jl = !1, t.beforeCreate && As(t.beforeCreate, e, "bc");
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
    beforeMount: w,
    mounted: A,
    beforeUpdate: V,
    updated: L,
    activated: R,
    deactivated: ne,
    beforeDestroy: X,
    beforeUnmount: Z,
    destroyed: ee,
    unmounted: j,
    render: le,
    renderTracked: Q,
    renderTriggered: I,
    errorCaptured: E,
    serverPrefetch: P,
    // public API
    expose: S,
    inheritAttrs: C,
    // assets
    components: ie,
    directives: ke,
    filters: ae
  } = t;
  if (g && Ba(g, o, null), a)
    for (const d in a) {
      const r = a[d];
      ge(r) && (o[d] = r.bind(n));
    }
  if (s) {
    const d = s.call(n, n);
    Ve(d) && (e.data = /* @__PURE__ */ ts(d));
  }
  if (jl = !0, i)
    for (const d in i) {
      const r = i[d], v = ge(r) ? r.bind(n, n) : ge(r.get) ? r.get.bind(n, n) : xt, _ = !ge(r) && ge(r.set) ? r.set.bind(n) : xt, J = he({
        get: v,
        set: _
      });
      Object.defineProperty(o, d, {
        enumerable: !0,
        configurable: !0,
        get: () => J.value,
        set: (Pe) => J.value = Pe
      });
    }
  if (u)
    for (const d in u)
      qo(u[d], o, n, d);
  if (c) {
    const d = ge(c) ? c.call(n) : c;
    Reflect.ownKeys(d).forEach((r) => {
      _a(r, d[r]);
    });
  }
  m && As(m, e, "c");
  function U(d, r) {
    pe(r) ? r.forEach((v) => d(v.bind(n))) : r && d(r.bind(n));
  }
  if (U(Ma, w), U(ot, A), U(Oa, V), U(Ra, L), U(Aa, R), U(Ea, ne), U(Na, E), U(qa, Q), U(Fa, I), U(Do, Z), U(yt, j), U(Da, P), pe(S))
    if (S.length) {
      const d = e.exposed || (e.exposed = {});
      S.forEach((r) => {
        Object.defineProperty(d, r, {
          get: () => n[r],
          set: (v) => n[r] = v,
          enumerable: !0
        });
      });
    } else e.exposed || (e.exposed = {});
  le && e.render === xt && (e.render = le), C != null && (e.inheritAttrs = C), ie && (e.components = ie), ke && (e.directives = ke), P && Oo(e);
}
function Ba(e, t, n = xt) {
  pe(e) && (e = Wl(e));
  for (const o in e) {
    const s = e[o];
    let i;
    Ve(s) ? "default" in s ? i = zn(
      s.from || o,
      s.default,
      !0
    ) : i = zn(s.from || o) : i = zn(s), /* @__PURE__ */ Je(i) ? Object.defineProperty(t, o, {
      enumerable: !0,
      configurable: !0,
      get: () => i.value,
      set: (a) => i.value = a
    }) : t[o] = i;
  }
}
function As(e, t, n) {
  bt(
    pe(e) ? e.map((o) => o.bind(t.proxy)) : e.bind(t.proxy),
    t,
    n
  );
}
function qo(e, t, n, o) {
  let s = o.includes(".") ? Eo(n, o) : () => n[o];
  if (Ee(e)) {
    const i = t[e];
    ge(i) && We(s, i);
  } else if (ge(e))
    We(s, e.bind(n));
  else if (Ve(e))
    if (pe(e))
      e.forEach((i) => qo(i, t, n, o));
    else {
      const i = ge(e.handler) ? e.handler.bind(n) : t[e.handler];
      ge(i) && We(s, i, e);
    }
}
function No(e) {
  const t = e.type, { mixins: n, extends: o } = t, {
    mixins: s,
    optionsCache: i,
    config: { optionMergeStrategies: a }
  } = e.appContext, u = i.get(t);
  let c;
  return u ? c = u : !s.length && !n && !o ? c = t : (c = {}, s.length && s.forEach(
    (g) => el(c, g, a, !0)
  ), el(c, t, a)), Ve(t) && i.set(t, c), c;
}
function el(e, t, n, o = !1) {
  const { mixins: s, extends: i } = t;
  i && el(e, i, n, !0), s && s.forEach(
    (a) => el(e, a, n, !0)
  );
  for (const a in t)
    if (!(o && a === "expose")) {
      const u = Ka[a] || n && n[a];
      e[a] = u ? u(e[a], t[a]) : t[a];
    }
  return e;
}
const Ka = {
  data: Es,
  props: Is,
  emits: Is,
  // objects
  methods: gn,
  computed: gn,
  // lifecycle
  beforeCreate: Ze,
  created: Ze,
  beforeMount: Ze,
  mounted: Ze,
  beforeUpdate: Ze,
  updated: Ze,
  beforeDestroy: Ze,
  beforeUnmount: Ze,
  destroyed: Ze,
  unmounted: Ze,
  activated: Ze,
  deactivated: Ze,
  errorCaptured: Ze,
  serverPrefetch: Ze,
  // assets
  components: gn,
  directives: gn,
  // watch
  watch: za,
  // provide / inject
  provide: Es,
  inject: Ga
};
function Es(e, t) {
  return t ? e ? function() {
    return De(
      ge(e) ? e.call(this, this) : e,
      ge(t) ? t.call(this, this) : t
    );
  } : t : e;
}
function Ga(e, t) {
  return gn(Wl(e), Wl(t));
}
function Wl(e) {
  if (pe(e)) {
    const t = {};
    for (let n = 0; n < e.length; n++)
      t[e[n]] = e[n];
    return t;
  }
  return e;
}
function Ze(e, t) {
  return e ? [...new Set([].concat(e, t))] : t;
}
function gn(e, t) {
  return e ? De(/* @__PURE__ */ Object.create(null), e, t) : t;
}
function Is(e, t) {
  return e ? pe(e) && pe(t) ? [.../* @__PURE__ */ new Set([...e, ...t])] : De(
    /* @__PURE__ */ Object.create(null),
    Us(e),
    Us(t ?? {})
  ) : t;
}
function za(e, t) {
  if (!e) return t;
  if (!t) return e;
  const n = De(/* @__PURE__ */ Object.create(null), e);
  for (const o in t)
    n[o] = Ze(e[o], t[o]);
  return n;
}
function Ho() {
  return {
    app: null,
    config: {
      isNativeTag: eo,
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
let Ja = 0;
function Ya(e, t) {
  return function(o, s = null) {
    ge(o) || (o = De({}, o)), s != null && !Ve(s) && (s = null);
    const i = Ho(), a = /* @__PURE__ */ new WeakSet(), u = [];
    let c = !1;
    const g = i.app = {
      _uid: Ja++,
      _component: o,
      _props: s,
      _container: null,
      _context: i,
      _instance: null,
      version: Sr,
      get config() {
        return i.config;
      },
      set config(m) {
      },
      use(m, ...w) {
        return a.has(m) || (m && ge(m.install) ? (a.add(m), m.install(g, ...w)) : ge(m) && (a.add(m), m(g, ...w))), g;
      },
      mixin(m) {
        return i.mixins.includes(m) || i.mixins.push(m), g;
      },
      component(m, w) {
        return w ? (i.components[m] = w, g) : i.components[m];
      },
      directive(m, w) {
        return w ? (i.directives[m] = w, g) : i.directives[m];
      },
      mount(m, w, A) {
        if (!c) {
          const V = g._ceVNode || Ae(o, s);
          return V.appContext = i, A === !0 ? A = "svg" : A === !1 && (A = void 0), e(V, m, A), c = !0, g._container = m, m.__vue_app__ = g, hl(V.component);
        }
      },
      onUnmount(m) {
        u.push(m);
      },
      unmount() {
        c && (bt(
          u,
          g._instance,
          16
        ), e(null, g._container), delete g._container.__vue_app__);
      },
      provide(m, w) {
        return i.provides[m] = w, g;
      },
      runWithContext(m) {
        const w = sn;
        sn = g;
        try {
          return m();
        } finally {
          sn = w;
        }
      }
    };
    return g;
  };
}
let sn = null;
function Xa(e, t, n = _e) {
  const o = ii(), s = ut(t), i = Dt(t), a = Lo(e, s), u = fa((c, g) => {
    let m, w = _e, A;
    return Ca(() => {
      const V = e[s];
      Le(m, V) && (m = V, g());
    }), {
      get() {
        return c(), n.get ? n.get(m) : m;
      },
      set(V) {
        const L = n.set ? n.set(V) : V;
        if (!Le(L, m) && !(w !== _e && Le(V, w)))
          return;
        const R = o.vnode.props, ne = !!(R && // check if parent has passed v-model
        (t in R || s in R || i in R) && (`onUpdate:${t}` in R || `onUpdate:${s}` in R || `onUpdate:${i}` in R));
        ne || (m = V, g()), o.emit(`update:${t}`, L), Le(V, w) && (Le(V, L) && !Le(L, A) || // #13524: browsers differ in when they flush microtasks between
        // event listeners. If a v-model listener emits an intermediate value
        // and a following listener restores the model to its previous prop
        // value before parent updates are flushed, the parent render can be
        // deduped as having no prop change. Force a local update so DOM state
        // such as an input's value is synchronized back to the current model.
        ne && w !== _e && !Le(L, m)) && g(), w = V, A = L;
      }
    };
  });
  return u[Symbol.iterator] = () => {
    let c = 0;
    return {
      next() {
        return c < 2 ? { value: c++ ? a || _e : u, done: !1 } : { done: !0 };
      }
    };
  }, u;
}
const Lo = (e, t) => t === "modelValue" || t === "model-value" ? e.modelModifiers : e[`${t}Modifiers`] || e[`${ut(t)}Modifiers`] || e[`${Dt(t)}Modifiers`];
function Za(e, t, ...n) {
  if (e.isUnmounted) return;
  const o = e.vnode.props || _e;
  let s = n;
  const i = t.startsWith("update:"), a = i && Lo(o, t.slice(7));
  a && (a.trim && (s = n.map((m) => Ee(m) ? m.trim() : m)), a.number && (s = s.map(En)));
  let u, c = o[u = yl(t)] || // also try camelCase event handler (#2249)
  o[u = yl(ut(t))];
  !c && i && (c = o[u = yl(Dt(t))]), c && bt(
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
    e.emitted[u] = !0, bt(
      g,
      e,
      6,
      s
    );
  }
}
const Qa = /* @__PURE__ */ new WeakMap();
function jo(e, t, n = !1) {
  const o = n ? Qa : t.emitsCache, s = o.get(e);
  if (s !== void 0)
    return s;
  const i = e.emits;
  let a = {}, u = !1;
  if (!ge(e)) {
    const c = (g) => {
      const m = jo(g, t, !0);
      m && (u = !0, De(a, m));
    };
    !n && t.mixins.length && t.mixins.forEach(c), e.extends && c(e.extends), e.mixins && e.mixins.forEach(c);
  }
  return !i && !u ? (Ve(e) && o.set(e, null), null) : (pe(i) ? i.forEach((c) => a[c] = null) : De(a, i), Ve(e) && o.set(e, a), a);
}
function pl(e, t) {
  return !e || !ol(t) ? !1 : (t = t.slice(2), t = t === "Once" ? t : t.replace(/Once$/, ""), we(e, t[0].toLowerCase() + t.slice(1)) || we(e, Dt(t)) || we(e, t));
}
function Ms(e) {
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
    props: w,
    data: A,
    setupState: V,
    ctx: L,
    inheritAttrs: R
  } = e, ne = Zn(e);
  let X, Z;
  try {
    if (n.shapeFlag & 4) {
      const j = s || o, le = j;
      X = Ct(
        g.call(
          le,
          j,
          m,
          w,
          V,
          A,
          L
        )
      ), Z = u;
    } else {
      const j = t;
      X = Ct(
        j.length > 1 ? j(
          w,
          { attrs: u, slots: a, emit: c }
        ) : j(
          w,
          null
        )
      ), Z = t.props ? u : er(u);
    }
  } catch (j) {
    Ot.length = 0, cl(j, e, 1), X = Ae(ft);
  }
  let ee = X;
  if (Z && R !== !1) {
    const j = Object.keys(Z), { shapeFlag: le } = ee;
    j.length && le & 7 && (i && j.some(il) && (Z = tr(
      Z,
      i
    )), ee = on(ee, Z, !1, !0));
  }
  if (n.dirs && (ee = on(ee, null, !1, !0), ee.dirs = ee.dirs ? ee.dirs.concat(n.dirs) : n.dirs), n.transition) {
    const j = fl(ee.type) && Mo(ee) || ee;
    _n(j, n.transition);
  }
  return X = ee, Zn(ne), X;
}
function Wo(e, t = !0) {
  let n;
  for (let o = 0; o < e.length; o++) {
    const s = e[o];
    if (gl(s)) {
      if (s.type !== ft || s.children === "v-if") {
        if (n)
          return;
        n = s;
      }
    } else
      return;
  }
  return n;
}
const er = (e) => {
  let t;
  for (const n in e)
    (n === "class" || n === "style" || ol(n)) && ((t || (t = {}))[n] = e[n]);
  return t;
}, tr = (e, t) => {
  const n = {};
  for (const o in e)
    (!il(o) || !(o.slice(9) in t)) && (n[o] = e[o]);
  return n;
};
function nr(e, t, n) {
  const { props: o, children: s, component: i } = e, { props: a, children: u, patchFlag: c } = t, g = i.emitsOptions;
  if (t.dirs || t.transition)
    return !0;
  if (n && c >= 0) {
    if (c & 1024)
      return !0;
    if (c & 16)
      return o ? Os(o, a, g) : !!a;
    if (c & 8) {
      const m = t.dynamicProps;
      for (let w = 0; w < m.length; w++) {
        const A = m[w];
        if (Bo(a, o, A) && !pl(g, A))
          return !0;
      }
    }
  } else
    return (s || u) && (!u || !u.$stable) ? !0 : o === a ? !1 : o ? a ? Os(o, a, g) : !0 : !!a;
  return !1;
}
function Os(e, t, n) {
  const o = Object.keys(t);
  if (o.length !== Object.keys(e).length)
    return !0;
  for (let s = 0; s < o.length; s++) {
    const i = o[s];
    if (!we(e, i) || Bo(t, e, i) && !pl(n, i))
      return !0;
  }
  return !1;
}
function Bo(e, t, n) {
  const o = e[n], s = t[n];
  return n === "style" && Ve(o) && Ve(s) ? !mt(o, s) : o !== s;
}
function lr({ vnode: e, parent: t, suspense: n }, o) {
  for (; t; ) {
    const s = t.subTree;
    if (s.suspense && s.suspense.activeBranch === e && (s.suspense.vnode.el = s.el = o, e = s), s === e)
      (e = t.vnode).el = o, t = t.parent;
    else
      break;
  }
  n && n.activeBranch === e && (n.vnode.el = o);
}
const Ko = {}, Go = () => Object.create(Ko), zo = (e) => Object.getPrototypeOf(e) === Ko;
function sr(e, t, n, o = !1) {
  const s = {}, i = Go();
  e.propsDefaults = /* @__PURE__ */ Object.create(null), Jo(e, t, s, i);
  for (const a in e.propsOptions[0])
    a in s || (s[a] = void 0);
  n ? e.props = o ? s : /* @__PURE__ */ oa(s) : e.type.props ? e.props = s : e.props = i, e.attrs = i;
}
function or(e, t, n, o) {
  const {
    props: s,
    attrs: i,
    vnode: { patchFlag: a }
  } = e, u = /* @__PURE__ */ Ce(s), [c] = e.propsOptions;
  let g = !1;
  if (
    // always force full diff in dev
    // - #1942 if hmr is enabled with sfc component
    // - vite#872 non-sfc component used by sfc component
    (o || a > 0) && !(a & 16)
  ) {
    if (a & 8) {
      const m = e.vnode.dynamicProps;
      for (let w = 0; w < m.length; w++) {
        let A = m[w];
        if (pl(e.emitsOptions, A))
          continue;
        const V = t[A];
        if (c)
          if (we(i, A))
            V !== i[A] && (i[A] = V, g = !0);
          else {
            const L = ut(A);
            s[L] = Bl(
              c,
              u,
              L,
              V,
              e,
              !1
            );
          }
        else
          V !== i[A] && (i[A] = V, g = !0);
      }
    }
  } else {
    Jo(e, t, s, i) && (g = !0);
    let m;
    for (const w in u)
      (!t || // for camelCase
      !we(t, w) && // it's possible the original props was passed in as kebab-case
      // and converted to camelCase (#955)
      ((m = Dt(w)) === w || !we(t, m))) && (c ? n && // for camelCase
      (n[w] !== void 0 || // for kebab-case
      n[m] !== void 0) && (s[w] = Bl(
        c,
        u,
        w,
        void 0,
        e,
        !0
      )) : delete s[w]);
    if (i !== u)
      for (const w in i)
        (!t || !we(t, w)) && (delete i[w], g = !0);
  }
  g && Et(e.attrs, "set", "");
}
function Jo(e, t, n, o) {
  const [s, i] = e.propsOptions;
  let a = !1, u;
  if (t)
    for (let c in t) {
      if (bn(c))
        continue;
      const g = t[c];
      let m;
      s && we(s, m = ut(c)) ? !i || !i.includes(m) ? n[m] = g : (u || (u = {}))[m] = g : pl(e.emitsOptions, c) || (!(c in o) || g !== o[c]) && (o[c] = g, a = !0);
    }
  if (i) {
    const c = /* @__PURE__ */ Ce(n), g = u || _e;
    for (let m = 0; m < i.length; m++) {
      const w = i[m];
      n[w] = Bl(
        s,
        c,
        w,
        g[w],
        e,
        !we(g, w)
      );
    }
  }
  return a;
}
function Bl(e, t, n, o, s, i) {
  const a = e[n];
  if (a != null) {
    const u = we(a, "default");
    if (u && o === void 0) {
      const c = a.default;
      if (a.type !== Function && !a.skipFactory && ge(c)) {
        const { propsDefaults: g } = s;
        if (n in g)
          o = g[n];
        else {
          const m = Mn(s);
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
    ] && (o === "" || o === Dt(n)) && (o = !0));
  }
  return o;
}
const ir = /* @__PURE__ */ new WeakMap();
function Yo(e, t, n = !1) {
  const o = n ? ir : t.propsCache, s = o.get(e);
  if (s)
    return s;
  const i = e.props, a = {}, u = [];
  let c = !1;
  if (!ge(e)) {
    const m = (w) => {
      c = !0;
      const [A, V] = Yo(w, t, !0);
      De(a, A), V && u.push(...V);
    };
    !n && t.mixins.length && t.mixins.forEach(m), e.extends && m(e.extends), e.mixins && e.mixins.forEach(m);
  }
  if (!i && !c)
    return Ve(e) && o.set(e, Zt), Zt;
  if (pe(i))
    for (let m = 0; m < i.length; m++) {
      const w = ut(i[m]);
      Rs(w) && (a[w] = _e);
    }
  else if (i)
    for (const m in i) {
      const w = ut(m);
      if (Rs(w)) {
        const A = i[m], V = a[w] = pe(A) || ge(A) ? { type: A } : De({}, A), L = V.type;
        let R = !1, ne = !0;
        if (pe(L))
          for (let X = 0; X < L.length; ++X) {
            const Z = L[X], ee = ge(Z) && Z.name;
            if (ee === "Boolean") {
              R = !0;
              break;
            } else ee === "String" && (ne = !1);
          }
        else
          R = ge(L) && L.name === "Boolean";
        V[
          0
          /* shouldCast */
        ] = R, V[
          1
          /* shouldCastTrue */
        ] = ne, (R || we(V, "default")) && u.push(w);
      }
    }
  const g = [a, u];
  return Ve(e) && o.set(e, g), g;
}
function Rs(e) {
  return e[0] !== "$" && !bn(e);
}
const rs = (e) => e === "_" || e === "_ctx" || e === "$stable", us = (e) => pe(e) ? e.map(Ct) : [Ct(e)], ar = (e, t, n) => {
  if (t._n)
    return t;
  const o = Ie((...s) => us(t(...s)), n);
  return o._c = !1, o;
}, Xo = (e, t, n) => {
  const o = e._ctx;
  for (const s in e) {
    if (rs(s)) continue;
    const i = e[s];
    if (ge(i))
      t[s] = ar(s, i, o);
    else if (i != null) {
      const a = us(i);
      t[s] = () => a;
    }
  }
}, Zo = (e, t) => {
  const n = us(t);
  e.slots.default = () => n;
}, Qo = (e, t, n) => {
  for (const o in t)
    (n || !rs(o)) && (e[o] = t[o]);
}, rr = (e, t, n) => {
  const o = e.slots = Go();
  if (e.vnode.shapeFlag & 32) {
    const s = t._;
    s ? (Qo(o, t, n), n && oo(o, "_", s, !0)) : Xo(t, o);
  } else t && Zo(e, t);
}, ur = (e, t, n) => {
  const { vnode: o, slots: s } = e;
  let i = !0, a = _e;
  if (o.shapeFlag & 32) {
    const u = t._;
    u ? n && u === 1 ? i = !1 : Qo(s, t, n) : (i = !t.$stable, Xo(t, s)), a = t;
  } else t && (Zo(e, t), a = { default: 1 });
  if (i)
    for (const u in s)
      !rs(u) && a[u] == null && delete s[u];
}, Ke = gr;
function dr(e) {
  return cr(e);
}
function cr(e, t) {
  const n = rl();
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
    parentNode: w,
    nextSibling: A,
    setScopeId: V = xt,
    insertStaticContent: L
  } = e, R = (y, k, O, G = null, N = null, W = null, te = void 0, Y = null, K = !!k.dynamicChildren) => {
    if (y === k)
      return;
    y && !cn(y, k) && (G = at(y), Pe(y, N, W, !0), y = null), k.patchFlag === -2 && (K = !1, k.dynamicChildren = null), k.dynamicChildren && y && y.dynamicChildren && y.dynamicChildren.hasOnce && (k.dynamicChildren === Zt && (k.dynamicChildren = []), k.dynamicChildren.hasOnce = !0);
    const { type: F, ref: ue, shapeFlag: se } = k;
    switch (F) {
      case vl:
        ne(y, k, O, G);
        break;
      case ft:
        X(y, k, O, G);
        break;
      case Vl:
        y == null && Z(k, O, G, te);
        break;
      case q:
        ie(
          y,
          k,
          O,
          G,
          N,
          W,
          te,
          Y,
          K
        );
        break;
      default:
        se & 1 ? le(
          y,
          k,
          O,
          G,
          N,
          W,
          te,
          Y,
          K
        ) : se & 6 ? ke(
          y,
          k,
          O,
          G,
          N,
          W,
          te,
          Y,
          K
        ) : (se & 64 || se & 128) && F.process(
          y,
          k,
          O,
          G,
          N,
          W,
          te,
          Y,
          K,
          wt
        );
    }
    ue != null && N ? kn(ue, y && y.ref, W, k || y, !k) : ue == null && y && y.ref != null && kn(y.ref, null, W, y, !0);
  }, ne = (y, k, O, G) => {
    if (y == null)
      o(
        k.el = u(k.children),
        O,
        G
      );
    else {
      const N = k.el = y.el;
      k.children !== y.children && g(N, k.children);
    }
  }, X = (y, k, O, G) => {
    y == null ? o(
      k.el = c(k.children || ""),
      O,
      G
    ) : k.el = y.el;
  }, Z = (y, k, O, G) => {
    [y.el, y.anchor] = L(
      y.children,
      k,
      O,
      G,
      y.el,
      y.anchor
    );
  }, ee = ({ el: y, anchor: k }, O, G) => {
    let N;
    for (; y && y !== k; )
      N = A(y), o(y, O, G), y = N;
    o(k, O, G);
  }, j = ({ el: y, anchor: k }) => {
    let O;
    for (; y && y !== k; )
      O = A(y), s(y), y = O;
    s(k);
  }, le = (y, k, O, G, N, W, te, Y, K) => {
    if (k.type === "svg" ? te = "svg" : k.type === "math" && (te = "mathml"), y == null)
      Q(
        k,
        O,
        G,
        N,
        W,
        te,
        Y,
        K
      );
    else {
      const F = y.el && y.el._isVueCE ? y.el : null;
      try {
        F && F._beginPatch(), P(
          y,
          k,
          N,
          W,
          te,
          Y,
          K
        );
      } finally {
        F && F._endPatch();
      }
    }
  }, Q = (y, k, O, G, N, W, te, Y) => {
    let K, F;
    const { props: ue, shapeFlag: se, transition: de, dirs: ve } = y;
    if (K = y.el = a(
      y.type,
      W,
      ue && ue.is,
      ue
    ), se & 8 ? m(K, y.children) : se & 16 && E(
      y.children,
      K,
      null,
      G,
      N,
      Tl(y, W),
      te,
      Y
    ), ve && zt(y, null, G, "created"), I(K, y, y.scopeId, te, G), ue) {
      for (const Se in ue)
        Se !== "value" && !bn(Se) && i(K, Se, null, ue[Se], W, G);
      "value" in ue && i(K, "value", null, ue.value, W), (F = ue.onVnodeBeforeMount) && _t(F, G, y);
    }
    ve && zt(y, null, G, "beforeMount");
    const fe = fr(N, de);
    fe ? de.beforeEnter(K) : de && !de.persisted && (K[vr] = !0), o(K, k, O), ((F = ue && ue.onVnodeMounted) || fe || ve) && Ke(() => {
      F && _t(F, G, y), fe && de.enter(K), ve && zt(y, null, G, "mounted");
    }, N);
  }, I = (y, k, O, G, N) => {
    if (O && V(y, O), G)
      for (let W = 0; W < G.length; W++)
        V(y, G[W]);
    if (N) {
      let W = N.subTree;
      if (k === W || ti(W.type) && (W.ssContent === k || W.ssFallback === k)) {
        const te = N.vnode;
        I(
          y,
          te,
          te.scopeId,
          te.slotScopeIds,
          N.parent
        );
      }
    }
  }, E = (y, k, O, G, N, W, te, Y, K = 0) => {
    for (let F = K; F < y.length; F++) {
      const ue = y[F] = Y ? At(y[F]) : Ct(y[F]);
      R(
        null,
        ue,
        k,
        O,
        G,
        N,
        W,
        te,
        Y
      );
    }
  }, P = (y, k, O, G, N, W, te) => {
    const Y = k.el = y.el;
    let { patchFlag: K, dynamicChildren: F, dirs: ue } = k;
    K |= y.patchFlag & 16;
    const se = y.props || _e, de = k.props || _e;
    let ve;
    if (O && Jt(O, !1), (ve = de.onVnodeBeforeUpdate) && _t(ve, O, k, y), ue && zt(k, y, O, "beforeUpdate"), O && Jt(O, !0), // #6385 the old vnode may be a user-wrapped non-isomorphic block
    // Force full diff when block metadata is unstable.
    F && (!y.dynamicChildren || y.dynamicChildren.length !== F.length) && (K = 0, te = !1, F = null), (se.innerHTML && de.innerHTML == null || se.textContent && de.textContent == null) && m(Y, ""), F ? S(
      y.dynamicChildren,
      F,
      Y,
      O,
      G,
      Tl(k, N),
      W
    ) : te || r(
      y,
      k,
      Y,
      null,
      O,
      G,
      Tl(k, N),
      W,
      !1
    ), K > 0) {
      if (K & 16)
        C(Y, se, de, O, N);
      else if (K & 2 && se.class !== de.class && i(Y, "class", null, de.class, N), K & 4 && i(Y, "style", se.style, de.style, N), K & 8) {
        const fe = k.dynamicProps;
        for (let Se = 0; Se < fe.length; Se++) {
          const $e = fe[Se], be = se[$e], Oe = de[$e];
          (Oe !== be || $e === "value") && i(Y, $e, be, Oe, N, O);
        }
      }
      K & 1 && y.children !== k.children && m(Y, k.children);
    } else !te && F == null && C(Y, se, de, O, N);
    ((ve = de.onVnodeUpdated) || ue) && Ke(() => {
      ve && _t(ve, O, k, y), ue && zt(k, y, O, "updated");
    }, G);
  }, S = (y, k, O, G, N, W, te) => {
    for (let Y = 0; Y < k.length; Y++) {
      const K = y[Y], F = k[Y], ue = K.el || Cn(K), se = (
        // oldVNode may be an errored async setup() component inside Suspense
        // which will not have a mounted element
        ue && // - In the case of a Fragment, we need to provide the actual parent
        // of the Fragment itself so it can move its children.
        (K.type === q || // - In the case of different nodes, there is going to be a replacement
        // which also requires the correct parent container
        !cn(K, F) || // - In the case of a component, it could contain anything.
        K.shapeFlag & 198) ? w(ue) : (
          // In other cases, the parent container is not actually used so we
          // just pass the block element here to avoid a DOM parentNode call.
          O
        )
      );
      R(
        K,
        F,
        se,
        null,
        G,
        N,
        W,
        te,
        !0
      );
    }
  }, C = (y, k, O, G, N) => {
    if (k !== O) {
      if (k !== _e)
        for (const W in k)
          !bn(W) && !(W in O) && i(
            y,
            W,
            k[W],
            null,
            N,
            G
          );
      for (const W in O) {
        if (bn(W)) continue;
        const te = O[W], Y = k[W];
        te !== Y && W !== "value" && i(y, W, Y, te, N, G);
      }
      "value" in O && i(y, "value", k.value, O.value, N);
    }
  }, ie = (y, k, O, G, N, W, te, Y, K) => {
    const F = k.el = y ? y.el : u(""), ue = k.anchor = y ? y.anchor : u("");
    let { patchFlag: se, dynamicChildren: de, slotScopeIds: ve } = k;
    ve && (Y = Y ? Y.concat(ve) : ve), y == null ? (o(F, O, G), o(ue, O, G), E(
      // #10007
      // such fragment like `<></>` will be compiled into
      // a fragment which doesn't have a children.
      // In this case fallback to an empty array
      k.children || [],
      O,
      ue,
      N,
      W,
      te,
      Y,
      K
    )) : se > 0 && se & 64 && de && // #2715 the previous fragment could've been a BAILed one as a result
    // of renderSlot() with no valid children
    y.dynamicChildren && y.dynamicChildren.length === de.length ? (S(
      y.dynamicChildren,
      de,
      O,
      N,
      W,
      te,
      Y
    ), // #2080 if the stable fragment has a key, it's a <template v-for> that may
    //  get moved around. Make sure all root level vnodes inherit el.
    // #2134 or if it's a component root, it may also get moved around
    // as the component is being moved.
    (k.key != null || N && k === N.subTree) && ds(
      y,
      k,
      !0
      /* shallow */
    )) : r(
      y,
      k,
      O,
      ue,
      N,
      W,
      te,
      Y,
      K
    );
  }, ke = (y, k, O, G, N, W, te, Y, K) => {
    k.slotScopeIds = Y, y == null ? k.shapeFlag & 512 ? N.ctx.activate(
      k,
      O,
      G,
      te,
      K
    ) : ae(
      k,
      O,
      G,
      N,
      W,
      te,
      K
    ) : z(y, k, K);
  }, ae = (y, k, O, G, N, W, te) => {
    const Y = y.component = wr(
      y,
      G,
      N
    );
    if (as(y) && (Y.ctx.renderer = wt), _r(Y, !1, te), Y.asyncDep) {
      if (N && N.registerDep(
        Y,
        U,
        te,
        W
      ), !y.el) {
        const K = Y.subTree = Ae(ft);
        X(null, K, k, O), y.placeholder = K.el;
      }
    } else
      U(
        Y,
        y,
        k,
        O,
        N,
        W,
        te
      );
  }, z = (y, k, O) => {
    const G = k.component = y.component;
    if (nr(y, k, O))
      if (G.asyncDep && !G.asyncResolved) {
        k.el = y.el, k.placeholder = y.placeholder, d(G, k, O);
        return;
      } else
        G.next = k, G.update();
    else
      k.el = y.el, k.placeholder = y.placeholder, G.vnode = k;
  }, U = (y, k, O, G, N, W, te) => {
    const Y = () => {
      if (y.isMounted) {
        let { next: se, bu: de, u: ve, parent: fe, vnode: Se } = y;
        {
          const qe = ei(y);
          if (qe) {
            se && (se.el = Se.el, d(y, se, te)), qe.asyncDep.then(() => {
              const Xe = () => {
                y.job.flags & 8 || (N && N.pendingBranch ? Ke(Xe, N) : F());
              };
              Xe.flags = 48, Ke(Xe, N);
            });
            return;
          }
        }
        let $e = se, be;
        Jt(y, !1), se ? (se.el = Se.el, d(y, se, te)) : se = Se, de && Gn(de), (be = se.props && se.props.onVnodeBeforeUpdate) && _t(be, fe, se, Se), Jt(y, !0);
        const Oe = Ms(y), Ye = y.subTree;
        y.subTree = Oe, R(
          Ye,
          Oe,
          // parent may have changed if it's in a teleport. a root that is a
          // pending async component only has its placeholder comment
          w(
            Ye.el || Cn(Ye)
          ),
          // anchor may have changed if it's in a fragment
          at(Ye),
          y,
          N,
          W
        ), se.el = Oe.el, $e === null && lr(y, Oe.el), ve && Ke(ve, N), (be = se.props && se.props.onVnodeUpdated) && Ke(
          () => _t(be, fe, se, Se),
          N
        );
      } else {
        let se;
        const { el: de, props: ve } = k, { bm: fe, m: Se, parent: $e, root: be, type: Oe } = y, Ye = ln(k);
        Jt(y, !1), fe && Gn(fe), !Ye && (se = ve && ve.onVnodeBeforeMount) && _t(se, $e, k), Jt(y, !0);
        {
          be.ce && be.ce._hasShadowRoot() && be.ce._injectChildStyle(
            Oe,
            y.parent ? y.parent.type : void 0
          );
          const qe = y.subTree = Ms(y);
          R(
            null,
            qe,
            O,
            G,
            y,
            N,
            W
          ), k.el = qe.el;
        }
        if (Se && Ke(Se, N), !Ye && (se = ve && ve.onVnodeMounted)) {
          const qe = k;
          Ke(
            () => _t(se, $e, qe),
            N
          );
        }
        (k.shapeFlag & 256 || $e && ln($e.vnode) && $e.vnode.shapeFlag & 256) && y.a && Ke(y.a, N), y.isMounted = !0, k = O = G = null;
      }
    };
    y.scope.on();
    const K = y.effect = new uo(Y);
    y.scope.off();
    const F = y.update = K.run.bind(K), ue = y.job = K.runIfDirty.bind(K);
    ue.i = y, ue.id = y.uid, K.scheduler = () => os(ue), Jt(y, !0), F();
  }, d = (y, k, O) => {
    k.component = y;
    const G = y.vnode.props;
    y.vnode = k, y.next = null, or(y, k.props, G, O), ur(y, k.children, O), St(), Vo(y), Tt();
  }, r = (y, k, O, G, N, W, te, Y, K = !1) => {
    const F = y && y.children, ue = y ? y.shapeFlag : 0, se = k.children, { patchFlag: de, shapeFlag: ve } = k;
    if (de > 0) {
      if (de & 128) {
        _(
          F,
          se,
          O,
          G,
          N,
          W,
          te,
          Y,
          K
        );
        return;
      } else if (de & 256) {
        v(
          F,
          se,
          O,
          G,
          N,
          W,
          te,
          Y,
          K
        );
        return;
      }
    }
    ve & 8 ? (ue & 16 && it(F, N, W), se !== F && m(O, se)) : ue & 16 ? ve & 16 ? _(
      F,
      se,
      O,
      G,
      N,
      W,
      te,
      Y,
      K
    ) : it(F, N, W, !0) : (ue & 8 && m(O, ""), ve & 16 && E(
      se,
      O,
      G,
      N,
      W,
      te,
      Y,
      K
    ));
  }, v = (y, k, O, G, N, W, te, Y, K) => {
    y = y || Zt, k = k || Zt;
    const F = y.length, ue = k.length, se = Math.min(F, ue);
    let de;
    for (de = 0; de < se; de++) {
      const ve = k[de] = K ? At(k[de]) : Ct(k[de]);
      R(
        y[de],
        ve,
        O,
        null,
        N,
        W,
        te,
        Y,
        K
      );
    }
    F > ue ? it(
      y,
      N,
      W,
      !0,
      !1,
      se
    ) : E(
      k,
      O,
      G,
      N,
      W,
      te,
      Y,
      K,
      se
    );
  }, _ = (y, k, O, G, N, W, te, Y, K) => {
    let F = 0;
    const ue = k.length;
    let se = y.length - 1, de = ue - 1;
    for (; F <= se && F <= de; ) {
      const ve = y[F], fe = k[F] = K ? At(k[F]) : Ct(k[F]);
      if (cn(ve, fe))
        R(
          ve,
          fe,
          O,
          null,
          N,
          W,
          te,
          Y,
          K
        );
      else
        break;
      F++;
    }
    for (; F <= se && F <= de; ) {
      const ve = y[se], fe = k[de] = K ? At(k[de]) : Ct(k[de]);
      if (cn(ve, fe))
        R(
          ve,
          fe,
          O,
          null,
          N,
          W,
          te,
          Y,
          K
        );
      else
        break;
      se--, de--;
    }
    if (F > se) {
      if (F <= de) {
        const ve = de + 1, fe = ve < ue ? k[ve].el : G;
        for (; F <= de; )
          R(
            null,
            k[F] = K ? At(k[F]) : Ct(k[F]),
            O,
            fe,
            N,
            W,
            te,
            Y,
            K
          ), F++;
      }
    } else if (F > de)
      for (; F <= se; )
        Pe(y[F], N, W, !0), F++;
    else {
      const ve = F, fe = F, Se = /* @__PURE__ */ new Map();
      for (F = fe; F <= de; F++) {
        const Be = k[F] = K ? At(k[F]) : Ct(k[F]);
        Be.key != null && Se.set(Be.key, F);
      }
      let $e, be = 0;
      const Oe = de - fe + 1;
      let Ye = !1, qe = 0;
      const Xe = new Array(Oe);
      for (F = 0; F < Oe; F++) Xe[F] = 0;
      for (F = ve; F <= se; F++) {
        const Be = y[F];
        if (be >= Oe) {
          Pe(Be, N, W, !0);
          continue;
        }
        let rt;
        if (Be.key != null)
          rt = Se.get(Be.key);
        else
          for ($e = fe; $e <= de; $e++)
            if (Xe[$e - fe] === 0 && cn(Be, k[$e])) {
              rt = $e;
              break;
            }
        rt === void 0 ? Pe(Be, N, W, !0) : (Xe[rt - fe] = F + 1, rt >= qe ? qe = rt : Ye = !0, R(
          Be,
          k[rt],
          O,
          null,
          N,
          W,
          te,
          Y,
          K
        ), be++);
      }
      const un = Ye ? pr(Xe) : Zt;
      for ($e = un.length - 1, F = Oe - 1; F >= 0; F--) {
        const Be = fe + F, rt = k[Be], On = k[Be + 1], Rn = Be + 1 < ue ? (
          // #13559, #14173 fallback to el placeholder for unresolved async component
          On.el || Cn(On)
        ) : G;
        Xe[F] === 0 ? R(
          null,
          rt,
          O,
          Rn,
          N,
          W,
          te,
          Y,
          K
        ) : Ye && ($e < 0 || F !== un[$e] ? J(rt, O, Rn, 2) : $e--);
      }
    }
  }, J = (y, k, O, G, N = null) => {
    const { el: W, type: te, transition: Y, children: K, shapeFlag: F } = y;
    if (F & 6) {
      J(y.component.subTree, k, O, G);
      return;
    }
    if (F & 128) {
      y.suspense.move(k, O, G);
      return;
    }
    if (F & 64) {
      te.move(y, k, O, wt);
      return;
    }
    if (te === q) {
      o(W, k, O);
      for (let se = 0; se < K.length; se++)
        J(K[se], k, O, G);
      o(y.anchor, k, O);
      return;
    }
    if (te === Vl) {
      ee(y, k, O);
      return;
    }
    if (G !== 2 && F & 1 && Y)
      if (G === 0)
        Y.persisted && !W[xl] ? o(W, k, O) : (Y.beforeEnter(W), o(W, k, O), Ke(() => Y.enter(W), N));
      else {
        const { leave: se, delayLeave: de, afterLeave: ve } = Y, fe = () => {
          y.ctx.isUnmounted ? s(W) : o(W, k, O);
        }, Se = () => {
          const $e = W._isLeaving || !!W[xl];
          W._isLeaving && W[xl](
            !0
            /* cancelled */
          ), Y.persisted && !$e ? fe() : se(W, () => {
            fe(), ve && ve();
          });
        };
        de ? de(W, fe, Se) : Se();
      }
    else
      o(W, k, O);
  }, Pe = (y, k, O, G = !1, N = !1) => {
    const {
      type: W,
      props: te,
      ref: Y,
      children: K,
      dynamicChildren: F,
      shapeFlag: ue,
      patchFlag: se,
      dirs: de,
      cacheIndex: ve,
      memo: fe
    } = y;
    if ((se === -2 || F && F.hasOnce) && (N = !1), Y != null && (St(), kn(Y, null, O, y, !0), Tt()), ve != null && (!y.ctx || y.ctx === k) && (k.renderCache[ve] = void 0), ue & 256 && k.ctx.deactivate(y))
      return;
    const Se = ue & 1 && de, $e = !ln(y);
    let be;
    if ($e && (be = te && te.onVnodeBeforeUnmount) && _t(be, k, y), ue & 6)
      qt(y.component, O, G);
    else {
      if (ue & 128) {
        y.suspense.unmount(O, G);
        return;
      }
      Se && zt(y, null, k, "beforeUnmount"), ue & 64 ? y.type.remove(
        y,
        k,
        O,
        wt,
        G
      ) : F && // #5154
      // when v-once is used inside a block, setBlockTracking(-1) marks the
      // parent block with hasOnce: true
      // so that it doesn't take the fast path during unmount - otherwise
      // components nested in v-once are never unmounted.
      !F.hasOnce && // #1153: fast path should not be taken for non-stable (v-for) fragments
      (W !== q || se > 0 && se & 64) ? it(
        F,
        k,
        O,
        !1,
        !0
      ) : (W === q && se & 384 || !N && ue & 16) && it(K, k, O), G && B(y);
    }
    const Oe = fe != null && ve == null;
    ($e && (be = te && te.onVnodeUnmounted) || Se || Oe) && Ke(() => {
      be && _t(be, k, y), Se && zt(y, null, k, "unmounted"), Oe && (y.el = null);
    }, O);
  }, B = (y) => {
    const { type: k, el: O, anchor: G, transition: N } = y, W = k === q;
    if (W && !N) {
      Fe(O, G);
      return;
    }
    if (k === Vl) {
      j(y), N && !N.persisted && N.afterLeave && N.afterLeave();
      return;
    }
    const te = W ? Hl(y) : y, Y = () => {
      W ? w(O) && Fe(O, G) : s(O), N && !N.persisted && N.afterLeave && N.afterLeave();
    };
    if (te && te.shapeFlag & 1 && N && !N.persisted) {
      const { leave: K, delayLeave: F } = N, ue = te.el, se = () => K(ue, Y);
      F ? F(ue, Y, se) : se();
    } else
      Y();
  }, Fe = (y, k) => {
    let O;
    for (; y !== k; )
      O = A(y), s(y), y = O;
    s(k);
  }, qt = (y, k, O) => {
    const { bum: G, scope: N, job: W, subTree: te, um: Y, m: K, a: F } = y;
    Ds(K), Ds(F), G && Gn(G), N.stop(), W ? (W.flags |= 8, Pe(te, y, k, O)) : te && (te.transition = y.vnode.transition, Pe(te, y, k, O)), Y && Ke(Y, k);
    const ue = () => {
      y.isUnmounted = !0;
    };
    ue.flags = 16, Ke(ue, k);
  }, it = (y, k, O, G = !1, N = !1, W = 0) => {
    for (let te = W; te < y.length; te++)
      Pe(y[te], k, O, G, N);
  }, at = (y) => {
    if (y.shapeFlag & 6)
      return at(y.component.subTree);
    if (y.shapeFlag & 128)
      return y.suspense.next();
    const k = A(y.anchor || y.el), O = k && k[Io];
    return O ? A(O) : k;
  }, Gt = (y, k, O) => {
    const G = y && k._vnode ? void 0 : y && y.component ? y.component.uid : yr();
    wa(() => {
      y == null ? k._vnode && Pe(k._vnode, null, null, !0) : R(
        k._vnode || null,
        y,
        k,
        null,
        null,
        null,
        O
      ), k._vnode = y;
    }, G);
  }, wt = {
    p: R,
    um: Pe,
    m: J,
    r: B,
    mt: ae,
    mc: E,
    pc: r,
    pbc: S,
    n: at,
    o: e
  };
  return {
    render: Gt,
    hydrate: void 0,
    createApp: Ya(Gt)
  };
}
function Tl({ type: e, props: t }, n) {
  return n === "svg" && e === "foreignObject" || n === "mathml" && e === "annotation-xml" && t && t.encoding && t.encoding.includes("html") ? void 0 : n;
}
function Jt({ effect: e, job: t }, n) {
  n ? (e.flags |= 32, t.flags |= 4) : (e.flags &= -33, t.flags &= -5);
}
function fr(e, t) {
  return (!e || e && !e.pendingBranch) && t && !t.persisted;
}
function ds(e, t, n = !1) {
  const o = e.children, s = t.children;
  if (pe(o) && pe(s))
    for (let i = 0; i < o.length; i++) {
      const a = o[i];
      let u = s[i];
      u.shapeFlag & 1 && !u.dynamicChildren && ((u.patchFlag <= 0 || u.patchFlag === 32) && (u = s[i] = At(s[i]), u.el = a.el), !n && u.patchFlag !== -2 && ds(a, u)), u.type === vl && (u.patchFlag === -1 && (u = s[i] = At(u)), u.el = a.el), u.type === ft && !u.el && (u.el = a.el);
    }
}
function pr(e) {
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
function ei(e) {
  const t = e.subTree.component;
  if (t)
    return t.asyncDep && !t.asyncResolved ? t : ei(t);
}
function Ds(e) {
  if (e)
    for (let t = 0; t < e.length; t++)
      e[t].flags |= 8;
}
function Cn(e) {
  if (e.placeholder)
    return e.placeholder;
  const t = e.component;
  if (t)
    return Cn(t.subTree);
  const n = e.suspense;
  return n && n.activeBranch ? Cn(n.activeBranch) : null;
}
const ti = (e) => e.__isSuspense, vr = /* @__PURE__ */ Symbol("_deferredEnter");
function gr(e, t) {
  t && t.pendingBranch ? pe(e) ? t.effects.push(...e) : t.effects.push(e) : ya(e);
}
const q = /* @__PURE__ */ Symbol.for("v-fgt"), vl = /* @__PURE__ */ Symbol.for("v-txt"), ft = /* @__PURE__ */ Symbol.for("v-cmt"), Vl = /* @__PURE__ */ Symbol.for("v-stc"), Ot = [];
let lt = null;
function f(e = !1) {
  Ot.push(lt = e ? null : []);
}
function cs() {
  Ot.pop(), lt = Ot[Ot.length - 1] || null;
}
let Pn = 1;
function Fs(e, t = !1) {
  Pn += e, e < 0 && lt && t && (lt.hasOnce = !0);
}
function ni(e) {
  return e.dynamicChildren = Pn > 0 ? lt || Zt : null, cs(), Pn > 0 && lt && lt.push(e), e;
}
function h(e, t, n, o, s, i) {
  return ni(
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
function me(e, t, n, o, s) {
  return ni(
    Ae(
      e,
      t,
      n,
      o,
      s,
      !0
    )
  );
}
function gl(e) {
  return e ? e.__v_isVNode === !0 : !1;
}
function cn(e, t) {
  return e.type === t.type && e.key === t.key;
}
const li = ({ key: e }) => e ?? null, Jn = ({
  ref: e,
  ref_key: t,
  ref_for: n
}) => (typeof e == "number" && (e = "" + e), e != null ? Ee(e) || /* @__PURE__ */ Je(e) || ge(e) ? { i: ze, r: e, k: t, f: !!n } : e : null);
function l(e, t = null, n = null, o = 0, s = null, i = e === q ? 0 : 1, a = !1, u = !1) {
  const c = {
    __v_isVNode: !0,
    __v_skip: !0,
    type: e,
    props: t,
    key: t && li(t),
    ref: t && Jn(t),
    scopeId: Ao,
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
    ctx: ze
  };
  return u ? (tl(c, n), i & 128 && e.normalize(c)) : n && (c.shapeFlag |= Ee(n) ? 8 : 16), Pn > 0 && // avoid a block node from tracking itself
  !a && // has current parent block
  lt && // presence of a patch flag indicates this node needs patching on updates.
  // component nodes also should always be patched, because even if the
  // component doesn't need to update, it needs to persist the instance on to
  // the next vnode so that it can be properly unmounted later.
  (c.patchFlag > 0 || i & 6) && // the EVENTS flag is only for hydration and if it is the only flag, the
  // vnode should not be considered dynamic due to handler caching.
  c.patchFlag !== 32 && lt.push(c), c;
}
const Ae = hr;
function hr(e, t = null, n = null, o = 0, s = null, i = !1) {
  if ((!e || e === Ha) && (e = ft), gl(e)) {
    const u = on(
      e,
      t,
      !0
      /* mergeRef: true */
    );
    return n && tl(u, n), Pn > 0 && !i && lt && (u.shapeFlag & 6 ? lt[lt.indexOf(e)] = u : lt.push(u)), u.patchFlag = -2, u;
  }
  if (xr(e) && (e = e.__vccOpts), t) {
    t = mr(t);
    let { class: u, style: c } = t;
    u && !Ee(u) && (t.class = Te(u)), Ve(c) && (/* @__PURE__ */ ls(c) && !pe(c) && (c = De({}, c)), t.style = jt(c));
  }
  const a = Ee(e) ? 1 : ti(e) ? 128 : fl(e) ? 64 : Ve(e) ? 4 : ge(e) ? 2 : 0;
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
function mr(e) {
  return e ? /* @__PURE__ */ ls(e) ? De({}, e) : zo(e) ? De({}, e[ui] || e) : e : null;
}
function on(e, t, n = !1, o = !1) {
  const { props: s, ref: i, patchFlag: a, children: u, transition: c } = e, g = t ? si(s || {}, t) : s, m = {
    __v_isVNode: !0,
    __v_skip: !0,
    type: e.type,
    props: g,
    key: g && li(g),
    ref: t && t.ref ? (
      // #2078 in the case of <component :is="vnode" ref="extra"/>
      // if the vnode itself already has a ref, cloneVNode will need to merge
      // the refs so the single vnode can be set on multiple refs
      n && i ? pe(i) ? i.concat(Jn(t)) : [i, Jn(t)] : Jn(t)
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
    patchFlag: t && e.type !== q ? a === -1 ? 16 : a | 16 : a,
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
    ssContent: e.ssContent && on(e.ssContent),
    ssFallback: e.ssFallback && on(e.ssFallback),
    placeholder: e.placeholder,
    el: e.el,
    anchor: e.anchor,
    ctx: e.ctx,
    ce: e.ce,
    cacheIndex: e.cacheIndex
  };
  return c && o && _n(
    m,
    c.clone(m)
  ), m;
}
function M(e = " ", t = 0) {
  return Ae(vl, null, e, t);
}
function x(e = "", t = !1) {
  return t ? (f(), me(ft, null, e)) : Ae(ft, null, e);
}
function Ct(e) {
  return e == null || typeof e == "boolean" ? Ae(ft) : pe(e) ? Ae(
    q,
    null,
    // #3666, avoid reference pollution when reusing vnode
    e.slice()
  ) : gl(e) ? At(e) : Ae(vl, null, String(e));
}
function At(e) {
  return e.el === null && e.patchFlag !== -1 || e.memo ? e : on(e);
}
function tl(e, t) {
  let n = 0;
  const { shapeFlag: o } = e;
  if (t == null)
    t = null;
  else if (pe(t))
    n = 16;
  else if (typeof t == "object")
    if (o & 65) {
      const s = t.default;
      s && (s._c && (s._d = !1), tl(e, s()), s._c && (s._d = !0));
      return;
    } else {
      n = 32;
      const s = t._;
      !s && !zo(t) ? t._ctx = ze : s === 3 && ze && (ze.slots._ === 1 ? t._ = 1 : (t._ = 2, e.patchFlag |= 1024));
    }
  else if (ge(t)) {
    if (o & 65) {
      tl(e, { default: t });
      return;
    }
    t = { default: t, _ctx: ze }, n = 32;
  } else
    t = String(t), o & 64 ? (n = 16, t = [M(t)]) : n = 8;
  e.children = t, e.shapeFlag |= n;
}
function si(...e) {
  const t = {};
  for (let n = 0; n < e.length; n++) {
    const o = e[n];
    for (const s in o)
      if (s === "class")
        t.class !== o.class && (t.class = Te([t.class, o.class]));
      else if (s === "style")
        t.style = jt([t.style, o.style]);
      else if (ol(s)) {
        const i = t[s], a = o[s];
        a && i !== a && !(pe(i) && i.includes(a)) ? t[s] = i ? [].concat(i, a) : a : a == null && i == null && // mergeProps({ 'onUpdate:modelValue': undefined }) should not retain
        // the model listener.
        !il(s) && (t[s] = a);
      } else s !== "" && (t[s] = o[s]);
  }
  return t;
}
function _t(e, t, n, o = null) {
  bt(e, t, 7, [
    n,
    o
  ]);
}
const br = /* @__PURE__ */ Ho();
let oi = 0;
function yr() {
  return oi;
}
function wr(e, t, n) {
  const o = e.type, s = (t ? t.appContext : e.appContext) || br, i = {
    uid: oi++,
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
    scope: new Hi(
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
    propsOptions: Yo(o, s),
    emitsOptions: jo(o, s),
    // emit
    emit: null,
    // to be set immediately
    emitted: null,
    // props default value
    propsDefaults: _e,
    // inheritAttrs
    inheritAttrs: o.inheritAttrs,
    // state
    ctx: _e,
    data: _e,
    props: _e,
    attrs: _e,
    slots: _e,
    refs: _e,
    setupState: _e,
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
  return i.ctx = { _: i }, i.root = t ? t.root : i, i.emit = Za.bind(null, i), e.ce && e.ce(i), i;
}
let et = null;
const ii = () => et || ze;
let nl, Un;
{
  const e = rl(), t = (n, o) => {
    let s;
    return (s = e[n]) || (s = e[n] = []), s.push(o), (i) => {
      s.length > 1 ? s.forEach((a) => a(i)) : s[0](i);
    };
  };
  nl = t(
    "__VUE_INSTANCE_SETTERS__",
    (n) => et = n
  ), Un = t(
    "__VUE_SSR_SETTERS__",
    (n) => An = n
  );
}
const Mn = (e) => {
  const t = et;
  return nl(e), e.scope.on(), () => {
    e.scope.off(), nl(t);
  };
}, qs = () => {
  et && et.scope.off(), nl(null);
};
function ai(e) {
  return e.vnode.shapeFlag & 4;
}
let An = !1;
function _r(e, t = !1, n = !1) {
  t && Un(t);
  const { props: o, children: s } = e.vnode, i = ai(e);
  sr(e, o, i, t), rr(e, s, n || t);
  const a = i ? kr(e, t) : void 0;
  return t && Un(!1), a;
}
function kr(e, t) {
  const n = e.type;
  e.accessCache = /* @__PURE__ */ Object.create(null), e.proxy = new Proxy(e.ctx, ja);
  const { setup: o } = n;
  if (o) {
    St();
    const s = e.setupContext = o.length > 1 ? Cr(e) : null, i = Mn(e), a = In(
      o,
      e,
      0,
      [
        e.props,
        s
      ]
    ), u = to(a);
    if (Tt(), i(), (u || e.sp) && !ln(e) && Oo(e), u) {
      if (a.then(qs, qs), t)
        return a.then((c) => {
          Un(!0);
          try {
            Ns(e, c, t);
          } finally {
            Un(!1);
          }
        }).catch((c) => {
          cl(c, e, 0, void 0, !0), e.ssrRender = (g, m) => m("<!---->");
        });
      e.asyncDep = a;
    } else
      Ns(e, a);
  } else
    ri(e);
}
function Ns(e, t, n) {
  ge(t) ? e.type.__ssrInlineRender ? e.ssrRender = t : e.render = t : Ve(t) && (e.setupState = xo(t)), ri(e);
}
function ri(e, t, n) {
  const o = e.type;
  e.render || (e.render = o.render || xt);
  {
    const s = Mn(e);
    St();
    try {
      Wa(e);
    } finally {
      Tt(), s();
    }
  }
}
const ui = /* @__PURE__ */ Symbol(), $r = {
  get(e, t) {
    return Ge(e, "get", ""), t === ui ? e : e[t];
  }
};
function Cr(e) {
  const t = (n) => {
    e.exposed = n || {};
  };
  return {
    attrs: new Proxy(e.attrs, $r),
    slots: e.slots,
    emit: e.emit,
    expose: t
  };
}
function hl(e) {
  return e.exposed ? e.exposeProxy || (e.exposeProxy = new Proxy(xo(ia(e.exposed)), {
    get(t, n) {
      if (n in t)
        return t[n];
      if (n in $n)
        return $n[n](e);
    },
    has(t, n) {
      return n in t || n in $n;
    }
  })) : e.proxy;
}
function xr(e) {
  return ge(e) && "__vccOpts" in e;
}
const he = (e, t) => /* @__PURE__ */ va(e, t, An), Sr = "3.5.46";
let Kl;
const Hs = typeof window < "u" && window.trustedTypes;
if (Hs)
  try {
    Kl = /* @__PURE__ */ Hs.createPolicy("vue", {
      createHTML: (e) => e
    });
  } catch {
  }
const di = Kl ? (e) => Kl.createHTML(e) : (e) => e, Tr = "http://www.w3.org/2000/svg", Vr = "http://www.w3.org/1998/Math/MathML", Ut = typeof document < "u" ? document : null, Ls = Ut && /* @__PURE__ */ Ut.createElement("template"), Pr = {
  insert: (e, t, n) => {
    t.insertBefore(e, n || null);
  },
  remove: (e) => {
    const t = e.parentNode;
    t && t.removeChild(e);
  },
  createElement: (e, t, n, o) => {
    const s = t === "svg" ? Ut.createElementNS(Tr, e) : t === "mathml" ? Ut.createElementNS(Vr, e) : n ? Ut.createElement(e, { is: n }) : Ut.createElement(e);
    return e === "select" && o && o.multiple != null && s.setAttribute("multiple", o.multiple), s;
  },
  createText: (e) => Ut.createTextNode(e),
  createComment: (e) => Ut.createComment(e),
  setText: (e, t) => {
    e.nodeValue = t;
  },
  setElementText: (e, t) => {
    e.textContent = t;
  },
  parentNode: (e) => e.parentNode,
  nextSibling: (e) => e.nextSibling,
  querySelector: (e) => Ut.querySelector(e),
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
      Ls.innerHTML = di(
        o === "svg" ? `<svg>${e}</svg>` : o === "mathml" ? `<math>${e}</math>` : e
      );
      const u = Ls.content;
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
}, Ur = /* @__PURE__ */ Symbol("_vtc");
function Ar(e, t, n) {
  const o = e[Ur];
  o && (t = (t ? [t, ...o] : [...o]).join(" ")), t == null ? e.removeAttribute("class") : n ? e.setAttribute("class", t) : e.className = t;
}
const ll = /* @__PURE__ */ Symbol("_vod"), ci = /* @__PURE__ */ Symbol("_vsh"), hn = {
  // used for prop mismatch check during hydration
  name: "show",
  beforeMount(e, { value: t }, { transition: n }) {
    e[ll] = e.style.display === "none" ? "" : e.style.display, n && t ? n.beforeEnter(e) : fn(e, t);
  },
  mounted(e, { value: t }, { transition: n }) {
    n && t && n.enter(e);
  },
  updated(e, { value: t, oldValue: n }, { transition: o }) {
    !t != !n && (o ? t ? (o.beforeEnter(e), fn(e, !0), o.enter(e)) : o.leave(e, () => {
      fn(e, !1);
    }) : fn(e, t));
  },
  beforeUnmount(e, { value: t }) {
    fn(e, t);
  }
};
function fn(e, t) {
  e.style.display = t ? e[ll] : "none", e[ci] = !t;
}
const Er = /* @__PURE__ */ Symbol(""), Ir = /(?:^|;)\s*display\s*:/;
function Mr(e, t, n) {
  const o = e.style, s = Ee(n);
  let i = !1;
  if (n && !s) {
    if (t)
      if (Ee(t))
        for (const a of t.split(";")) {
          const u = a.slice(0, a.indexOf(":")).trim();
          n[u] == null && mn(o, u, "");
        }
      else
        for (const a in t)
          n[a] == null && mn(o, a, "");
    for (const a in n) {
      a === "display" && (i = !0);
      const u = n[a];
      u != null ? Rr(
        e,
        a,
        !Ee(t) && t ? t[a] : void 0,
        u
      ) || mn(o, a, u) : mn(o, a, "");
    }
  } else if (s) {
    if (t !== n) {
      const a = o[Er];
      a && (n += ";" + a), o.cssText = n, i = Ir.test(n);
    }
  } else t && e.removeAttribute("style");
  ll in e && ((!s || t !== n) && (e[ll] = i ? o.display : ""), e[ci] && (o.display = "none"));
}
const Ln = /\s*!important$/;
function mn(e, t, n) {
  if (pe(n))
    n.forEach((o) => mn(e, t, o));
  else if (n == null && (n = ""), t.startsWith("--"))
    Ln.test(n) ? e.setProperty(t, n.replace(Ln, ""), "important") : e.setProperty(t, n);
  else {
    const o = Or(e, t);
    Ln.test(n) ? e.setProperty(
      Dt(o),
      n.replace(Ln, ""),
      "important"
    ) : e[o] = n;
  }
}
const js = ["Webkit", "Moz", "ms"], Pl = {};
function Or(e, t) {
  const n = Pl[t];
  if (n)
    return n;
  let o = ut(t);
  if (o !== "filter" && o in e)
    return Pl[t] = o;
  o = so(o);
  for (let s = 0; s < js.length; s++) {
    const i = js[s] + o;
    if (i in e)
      return Pl[t] = i;
  }
  return t;
}
function Rr(e, t, n, o) {
  return e.tagName === "TEXTAREA" && (t === "width" || t === "height") && Ee(o) && n === o;
}
const Ws = "http://www.w3.org/1999/xlink";
function Bs(e, t, n, o, s, i = Fi(t)) {
  o && t.startsWith("xlink:") ? n == null ? e.removeAttributeNS(Ws, t.slice(6, t.length)) : e.setAttributeNS(Ws, t, n) : n == null || i && !io(n) ? e.removeAttribute(t) : e.setAttribute(
    t,
    i ? "" : ht(n) ? String(n) : n
  );
}
function Ks(e, t, n, o, s) {
  if (t === "innerHTML" || t === "textContent") {
    n != null && (e[t] = t === "innerHTML" ? di(n) : n);
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
    u === "boolean" ? n = io(n) : n == null && u === "string" ? (n = "", a = !0) : u === "number" && (n = 0, a = !0);
  }
  try {
    e[t] = n;
  } catch {
  }
  a && e.removeAttribute(s || t);
}
function Mt(e, t, n, o) {
  e.addEventListener(t, n, o);
}
function Dr(e, t, n, o) {
  e.removeEventListener(t, n, o);
}
const Gs = /* @__PURE__ */ Symbol("_vei");
function Fr(e, t, n, o, s = null) {
  const i = e[Gs] || (e[Gs] = {}), a = i[t];
  if (o && a)
    a.value = o;
  else {
    const [u, c] = Hr(t);
    if (o) {
      const g = i[t] = Wr(
        o,
        s
      );
      Mt(e, u, g, c);
    } else a && (Dr(e, u, a, c), i[t] = void 0);
  }
}
const qr = /(Once|Passive|Capture)$/, Nr = /^on:?(?:Once|Passive|Capture)$/;
function Hr(e) {
  let t, n;
  for (; (n = e.match(qr)) && !Nr.test(e); )
    t || (t = {}), e = e.slice(0, e.length - n[1].length), t[n[1].toLowerCase()] = !0;
  return [e[2] === ":" ? e.slice(3) : Dt(e.slice(2)), t];
}
let Ul = 0;
const Lr = /* @__PURE__ */ Promise.resolve(), jr = () => Ul || (Lr.then(() => Ul = 0), Ul = Date.now());
function Wr(e, t) {
  const n = (o) => {
    if (!o._vts)
      o._vts = Date.now();
    else if (o._vts <= n.attached)
      return;
    const s = n.value;
    if (pe(s)) {
      const i = o.stopImmediatePropagation;
      o.stopImmediatePropagation = () => {
        i.call(o), o._stopped = !0;
      };
      const a = s.slice(), u = [o];
      for (let c = 0; c < a.length && !o._stopped; c++) {
        const g = a[c];
        g && bt(
          g,
          t,
          5,
          u
        );
      }
    } else
      bt(
        s,
        t,
        5,
        [o]
      );
  };
  return n.value = e, n.attached = jr(), n;
}
const zs = (e) => e.charCodeAt(0) === 111 && e.charCodeAt(1) === 110 && // lowercase letter
e.charCodeAt(2) > 96 && e.charCodeAt(2) < 123, Br = (e, t, n, o, s, i) => {
  const a = s === "svg";
  t === "class" ? Ar(e, o, a) : t === "style" ? Mr(e, n, o) : ol(t) ? il(t) || Fr(e, t, n, o, i) : (t[0] === "." ? (t = t.slice(1), !0) : t[0] === "^" ? (t = t.slice(1), !1) : Kr(e, t, o, a)) ? (Ks(e, t, o), !e.tagName.includes("-") && (t === "value" || t === "checked" || t === "selected") && Bs(e, t, o, a, i, t !== "value")) : /* #11081 force set props for possible async custom element */ e._isVueCE && // #12408 check if it's declared prop or it's async custom element
  (Gr(e, t) || // @ts-expect-error _def is private
  e._def.__asyncLoader && (/[A-Z]/.test(t) || !Ee(o))) ? Ks(e, ut(t), o, i, t) : (t === "true-value" ? e._trueValue = o : t === "false-value" && (e._falseValue = o), Bs(e, t, o, a));
};
function Kr(e, t, n, o) {
  if (o)
    return !!(t === "innerHTML" || t === "textContent" || t in e && zs(t) && ge(n));
  if (t === "spellcheck" || t === "draggable" || t === "translate" || t === "autocorrect" || t === "sandbox" && e.tagName === "IFRAME" || t === "form" || t === "list" && e.tagName === "INPUT" || t === "type" && e.tagName === "TEXTAREA")
    return !1;
  if (t === "width" || t === "height") {
    const s = e.tagName;
    if (s === "IMG" || s === "VIDEO" || s === "CANVAS" || s === "SOURCE")
      return !1;
  }
  return zs(t) && Ee(n) ? !1 : t in e;
}
function Gr(e, t) {
  const n = (
    // @ts-expect-error _def is private
    e._def.props
  );
  if (!n)
    return !1;
  const o = ut(t);
  return Array.isArray(n) ? n.some((s) => ut(s) === o) : Object.keys(n).some((s) => ut(s) === o);
}
const Kt = (e) => {
  const t = e.props["onUpdate:modelValue"] || !1;
  return pe(t) ? (n) => Gn(t, n) : t;
};
function zr(e) {
  e.target.composing = !0;
}
function Js(e) {
  const t = e.target;
  t.composing && (t.composing = !1, t.dispatchEvent(new Event("input")));
}
const st = /* @__PURE__ */ Symbol("_assign"), jn = /* @__PURE__ */ Symbol("_initialValue");
function Al(e, t, n) {
  return t && (e = e.trim()), n && (e = En(e)), e;
}
const re = {
  created(e, { modifiers: { lazy: t, trim: n, number: o } }, s) {
    e.parentNode && (e.type === "text" ? e[jn] = e.defaultValue.replace(/[\r\n]/g, "") : e.type === "textarea" && (e[jn] = e.defaultValue.replace(/\r\n?/g, `
`))), e[st] = Kt(s);
    const i = o || s.props && s.props.type === "number";
    Mt(e, t ? "change" : "input", (a) => {
      a.target.composing || e[st](Al(e.value, n, i));
    }), (n || i) && Mt(e, "change", () => {
      e.value = Al(e.value, n, i);
    }), t || (Mt(e, "compositionstart", zr), Mt(e, "compositionend", Js), Mt(e, "change", Js));
  },
  // set value on mounted so it's after min/max for type="range"
  mounted(e, { value: t, modifiers: { trim: n, number: o } }) {
    const s = t ?? "", i = e[jn];
    delete e[jn], i !== void 0 && (e.type === "text" || e.type === "textarea") && e.value !== i ? e[st](Al(e.value, n, o)) : e.value = s;
  },
  beforeUpdate(e, { value: t, oldValue: n, modifiers: { lazy: o, trim: s, number: i } }, a) {
    if (e[st] = Kt(a), e.composing) return;
    const u = (i || e.type === "number") && !/^0\d/.test(e.value) ? En(e.value) : e.value, c = t ?? "";
    if (u === c)
      return;
    const g = e.getRootNode();
    (g instanceof Document || g instanceof ShadowRoot) && g.activeElement === e && e.type !== "range" && (o && t === n || s && e.value.trim() === c) || (e.value = c);
  }
}, je = {
  // #4096 array checkboxes need to be deep traversed
  deep: !0,
  created(e, t, n) {
    e[st] = Kt(n), Mt(e, "change", () => {
      const o = e._modelValue, s = an(e), i = e.checked, a = e[st];
      if (pe(o)) {
        const u = Yl(o, s), c = u !== -1;
        if (i && !c)
          a(o.concat(s));
        else if (!i && c) {
          const g = [...o];
          g.splice(u, 1), a(g);
        }
      } else if (Rt(o)) {
        const u = new Set(o);
        i ? u.add(s) : u.delete(s), a(u);
      } else
        a(fi(e, i));
    });
  },
  // set initial checked on mount to wait for true-value/false-value
  mounted: Ys,
  beforeUpdate(e, t, n) {
    e[st] = Kt(n), Ys(e, t, n);
  }
};
function Ys(e, { value: t, oldValue: n }, o) {
  e._modelValue = t;
  let s;
  if (pe(t))
    s = Yl(t, o.props.value) > -1;
  else if (Rt(t))
    s = t.has(o.props.value);
  else {
    if (t === n) return;
    s = mt(t, fi(e, !0));
  }
  e.checked !== s && (e.checked = s);
}
const Jr = {
  created(e, { value: t }, n) {
    e.checked = mt(t, n.props.value), e[st] = Kt(n), Mt(e, "change", () => {
      e[st](an(e));
    });
  },
  beforeUpdate(e, { value: t, oldValue: n }, o) {
    e[st] = Kt(o), t !== n && (e.checked = mt(t, o.props.value));
  }
}, xe = {
  // <select multiple> value need to be deep traversed
  deep: !0,
  created(e, { value: t, modifiers: { number: n } }, o) {
    e._modelValue = t, Mt(e, "change", () => {
      const s = Array.prototype.filter.call(e.options, (c) => c.selected).map(
        (c) => n ? En(an(c)) : an(c)
      ), i = e.multiple, a = i ? Rt(e._modelValue) ? new Set(s) : s : s[0], u = e._pendingValue = [
        i,
        i ? pe(a) ? s.slice() : s : a
      ];
      try {
        e[st](a);
      } finally {
        ss(() => {
          e._pendingValue === u && (e._pendingValue = void 0);
        });
      }
    }), e[st] = Kt(o);
  },
  // set value in mounted & updated because <select> relies on its children
  // <option>s.
  mounted(e, { value: t, modifiers: { number: n } }) {
    Xs(e, t, n);
  },
  beforeUpdate(e, { value: t }, n) {
    e._modelValue = t, e[st] = Kt(n);
  },
  updated(e, { value: t, modifiers: { number: n } }) {
    const o = e._pendingValue;
    e._pendingValue = void 0, (!o || o[0] !== e.multiple || !Yr(t, o[1], o[0])) && Xs(e, t, n);
  }
};
function Yr(e, t, n) {
  if (!n || pe(e)) return mt(e, t);
  if (Rt(e)) {
    if (e.size !== t.length) return !1;
    for (const o of t)
      if (!e.has(o)) return !1;
    return !0;
  }
  return !1;
}
function Xs(e, t, n = !1) {
  const o = e.multiple, s = pe(t);
  if (!(o && !s && !Rt(t))) {
    for (let i = 0, a = e.options.length; i < a; i++) {
      const u = e.options[i], c = an(u);
      if (o)
        if (s) {
          const g = typeof c;
          g === "string" || g === "number" ? u.selected = t.some((m) => String(m) === String(c)) : u.selected = Yl(t, c) > -1;
        } else
          u.selected = t.has(c) || n && typeof c == "string" && t.has(En(c));
      else if (mt(an(u), t)) {
        e.selectedIndex !== i && (e.selectedIndex = i);
        return;
      }
    }
    !o && e.selectedIndex !== -1 && (e.selectedIndex = -1);
  }
}
function an(e) {
  return "_value" in e ? e._value : e.value;
}
function fi(e, t) {
  const n = t ? "_trueValue" : "_falseValue";
  return n in e ? e[n] : t;
}
const Xr = {
  created(e, t, n) {
    Wn(e, t, n, null, "created");
  },
  mounted(e, t, n) {
    Wn(e, t, n, null, "mounted");
  },
  beforeUpdate(e, t, n, o) {
    Wn(e, t, n, o, "beforeUpdate");
  },
  updated(e, t, n, o) {
    Wn(e, t, n, o, "updated");
  }
};
function Zr(e, t) {
  switch (e) {
    case "SELECT":
      return xe;
    case "TEXTAREA":
      return re;
    default:
      switch (t) {
        case "checkbox":
          return je;
        case "radio":
          return Jr;
        default:
          return re;
      }
  }
}
function Wn(e, t, n, o, s) {
  const a = Zr(
    e.tagName,
    n.props && n.props.type
  )[s];
  a && a(e, t, n, o);
}
const Qr = ["ctrl", "shift", "alt", "meta"], eu = {
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
  exact: (e, t) => Qr.some((n) => e[`${n}Key`] && !t.includes(n))
}, tt = (e, t) => {
  if (!e) return e;
  const n = e._withMods || (e._withMods = {}), o = t.join(".");
  return n[o] || (n[o] = ((s, ...i) => {
    for (let a = 0; a < t.length; a++) {
      const u = eu[t[a]];
      if (u && u(s, t)) return;
    }
    return e(s, ...i);
  }));
}, tu = {
  esc: "escape",
  space: " ",
  up: "arrow-up",
  left: "arrow-left",
  right: "arrow-right",
  down: "arrow-down",
  delete: "backspace"
}, sl = (e, t) => {
  const n = e._withKeys || (e._withKeys = {}), o = t.join(".");
  return n[o] || (n[o] = ((s) => {
    if (!("key" in s))
      return;
    const i = Dt(s.key);
    if (t.some(
      (a) => a === i || tu[a] === i
    ))
      return e(s);
  }));
}, nu = /* @__PURE__ */ De({ patchProp: Br }, Pr);
let Zs;
function lu() {
  return Zs || (Zs = dr(nu));
}
const su = ((...e) => {
  const t = lu().createApp(...e), { mount: n } = t;
  return t.mount = (o) => {
    const s = iu(o);
    if (!s) return;
    const i = t._component;
    !ge(i) && !i.render && !i.template && (i.template = s.innerHTML), s.nodeType === 1 && (s.textContent = "");
    const a = n(s, !1, ou(s));
    return s instanceof Element && (s.removeAttribute("v-cloak"), s.setAttribute("data-v-app", "")), a;
  }, t;
});
function ou(e) {
  if (e instanceof SVGElement)
    return "svg";
  if (typeof MathMLElement == "function" && e instanceof MathMLElement)
    return "mathml";
}
function iu(e) {
  return Ee(e) ? document.querySelector(e) : e;
}
const au = [
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
], ru = ["title"], uu = { class: "gw-project-links" }, du = ["aria-label", "href"], cu = ["href", "title"], fs = /* @__PURE__ */ Me({
  __name: "ProjectInfo",
  props: {
    id: {},
    compact: { type: Boolean },
    help: { type: Boolean }
  },
  emits: ["help"],
  setup(e, { emit: t }) {
    const n = e, o = t, s = he(() => au.find((a) => a.id === n.id)), i = he(() => s.value?.repository.split("/")[0]);
    return (a, u) => s.value ? (f(), h("div", {
      key: 0,
      class: Te(["gw-project-info", { compact: e.compact }])
    }, [
      l("p", {
        title: s.value.description
      }, b(s.value.description), 9, ru),
      l("div", uu, [
        l("a", {
          "aria-label": "Автор проекта: " + s.value.author,
          href: "https://github.com/" + i.value,
          target: "_blank",
          rel: "noopener noreferrer"
        }, b(s.value.author), 9, du),
        u[1] || (u[1] = l("span", { "aria-hidden": "true" }, "·", -1)),
        l("a", {
          href: "https://github.com/" + s.value.repository,
          title: s.value.repository,
          target: "_blank",
          rel: "noopener noreferrer"
        }, "GitHub ↗", 8, cu),
        e.help ? (f(), h("button", {
          key: 0,
          type: "button",
          onClick: u[0] || (u[0] = (c) => o("help"))
        }, "Помощь")) : x("", !0)
      ])
    ], 2)) : x("", !0);
  }
}), fu = { class: "gw-shell gw-dialog-overlay" }, pu = ["aria-label"], vu = { class: "gw-dialog-header" }, gu = ["disabled"], Re = /* @__PURE__ */ Me({
  __name: "GatewayDialog",
  props: {
    title: {},
    busy: { type: Boolean },
    wide: { type: Boolean },
    compact: { type: Boolean }
  },
  emits: ["close"],
  setup(e, { emit: t }) {
    const n = e, o = t, s = /* @__PURE__ */ D();
    let i = null;
    function a() {
      n.busy || o("close");
    }
    function u(c) {
      if (c.key === "Escape" && (c.preventDefault(), c.stopImmediatePropagation(), a()), c.key !== "Tab" || !s.value) return;
      const g = [...s.value.querySelectorAll('button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea:not(:disabled),a[href],summary,[tabindex="0"]')].filter((A) => A.getClientRects().length), m = g[0], w = g[g.length - 1];
      if (!m) {
        c.preventDefault(), s.value.focus();
        return;
      }
      c.shiftKey && (document.activeElement === m || document.activeElement === s.value) ? (c.preventDefault(), w.focus()) : !c.shiftKey && (document.activeElement === w || !s.value.contains(document.activeElement)) && (c.preventDefault(), m.focus());
    }
    return ot(async () => {
      i = document.activeElement, document.addEventListener("keydown", u, !0), await ss(), s.value?.focus();
    }), yt(() => {
      document.removeEventListener("keydown", u, !0), i?.isConnected && i.focus();
    }), (c, g) => (f(), me(Pa, { to: "body" }, [
      l("div", fu, [
        l("section", {
          ref_key: "dialog",
          ref: s,
          class: Te(["gw-panel gw-dialog", { "gw-dialog-wide": e.wide, "gw-dialog-compact": e.compact }]),
          role: "dialog",
          "aria-modal": "true",
          "aria-label": e.title,
          tabindex: "-1"
        }, [
          l("header", vu, [
            l("h2", null, b(e.title), 1),
            l("button", {
              type: "button",
              "aria-label": "Закрыть диалог",
              disabled: e.busy,
              onClick: a
            }, "×", 8, gu)
          ]),
          La(c.$slots, "default")
        ], 10, pu)
      ])
    ]));
  }
}), hu = {
  key: 0,
  class: "gw-error"
}, mu = { key: 1 }, bu = { class: "gw-notice" }, yu = {
  key: 0,
  class: "gw-error"
}, wu = { class: "gw-setup-steps" }, _u = {
  key: 1,
  class: "gw-notice"
}, ku = { class: "gw-actions" }, $u = ["disabled"], Cu = ["href"], xu = { class: "gw-hint" }, Su = ["href"], Tu = /* @__PURE__ */ Me({
  __name: "AdGuardSetup",
  props: {
    node: {},
    bridge: {}
  },
  emits: ["close", "install", "start"],
  setup(e, { emit: t }) {
    const n = e, o = t, s = /* @__PURE__ */ D(null), i = /* @__PURE__ */ D(""), a = (u) => "http://" + (n.node.host.includes(":") ? "[" + n.node.host + "]" : n.node.host) + ":" + u + "/";
    return ot(async () => {
      try {
        s.value = await n.bridge.request("/api/gateways/" + encodeURIComponent(n.node.id) + "/adguard");
      } catch (u) {
        i.value = u.message;
      }
    }), (u, c) => (f(), me(Re, {
      title: "AdGuard Home: установка и настройка DNS",
      wide: !0,
      onClose: c[2] || (c[2] = (g) => o("close"))
    }, {
      default: Ie(() => [
        Ae(fs, { id: "adguardhome" }),
        i.value ? (f(), h("p", hu, b(i.value), 1)) : x("", !0),
        !s.value && !i.value ? (f(), h("p", mu, "Проверяем роутер…")) : x("", !0),
        s.value ? (f(), h(q, { key: 2 }, [
          l("div", bu, [
            l("strong", null, b(s.value.installed ? "AdGuard Home установлен" : "Установка из официального GitHub-релиза"), 1),
            l("p", null, "Свободное место: " + b(s.value.free_bytes == null ? "Не определено" : (s.value.free_bytes / 1048576).toFixed(0) + " МБ") + ". Бинарный файл и журнал запросов требуют места; для небольшого flash рекомендуется внешнее хранилище.", 1),
            l("p", null, "Занятые порты: " + b(s.value.occupied_ports.filter((g) => [53, 54, 80, 443, 3e3, 5353, 8080].includes(g.port)).map((g) => g.port + "/" + g.protocol).join(", ") || "Не обнаружены") + ".", 1)
          ]),
          s.value.setup_port_busy && !s.value.configured ? (f(), h("p", yu, "Порт 3000 занят. Перед первым запуском освободите его через консоль или настройки службы.")) : x("", !0),
          l("ol", wu, [
            (f(!0), h(q, null, oe(s.value.steps, (g, m) => (f(), h("li", { key: m }, b(g), 1))), 128))
          ]),
          s.value.dns_dependencies.length ? (f(), h("p", _u, "Найдены зависимости DNS: " + b(s.value.dns_dependencies.join("; ")) + ". До их изменения остановка и удаление сервиса запрещены.", 1)) : x("", !0),
          l("div", ku, [
            s.value.installed ? e.node.monitor.services?.some((g) => g.id === "adguardhome" && g.running) ? x("", !0) : (f(), h("button", {
              key: 1,
              disabled: s.value.setup_port_busy && !s.value.configured,
              class: "gw-primary",
              onClick: c[1] || (c[1] = (g) => o("start"))
            }, "Запустить сервис", 8, $u)) : (f(), h("button", {
              key: 0,
              class: "gw-primary",
              onClick: c[0] || (c[0] = (g) => o("install"))
            }, "Выбрать версию и установить")),
            s.value.installed ? (f(), h("a", {
              key: 2,
              href: a(s.value.web_port),
              target: "_blank",
              rel: "noopener noreferrer"
            }, b(s.value.configured ? "Открыть AdGuard Home" : "Открыть мастер на порту 3000") + " ↗", 9, Cu)) : x("", !0)
          ]),
          l("p", xu, [
            c[3] || (c[3] = M("Официальные инструкции: ", -1)),
            (f(!0), h(q, null, oe(s.value.sources, (g) => (f(), h("a", {
              key: g.url,
              href: g.url,
              target: "_blank",
              rel: "noopener noreferrer"
            }, b(g.name) + " ↗ ", 9, Su))), 128))
          ])
        ], 64)) : x("", !0)
      ]),
      _: 1
    }));
  }
}), Vu = {
  key: 0,
  class: "gw-error",
  role: "alert"
}, Pu = { class: "gw-change-list" }, Uu = {
  key: 0,
  class: "gw-notice"
}, Au = { class: "gw-notice" }, Eu = { class: "gw-actions" }, Iu = ["disabled"], Mu = ["disabled"], Ou = {
  key: 0,
  class: "gw-hint"
}, Ru = ["required", "readonly"], Du = { class: "gw-check" }, Fu = {
  key: 0,
  class: "gw-notice"
}, qu = { class: "gw-two" }, Nu = ["disabled"], Hu = ["disabled"], Lu = { key: 0 }, ju = ["value"], Wu = ["value"], Bu = {
  key: 1,
  class: "gw-notice"
}, Ku = { class: "gw-two" }, Gu = { class: "gw-check" }, zu = { class: "gw-two" }, Ju = { class: "gw-check" }, Yu = { class: "gw-check" }, Xu = { class: "gw-check" }, Zu = {
  key: 0,
  class: "gw-notice"
}, Qu = {
  class: "gw-tabs",
  "aria-label": "Разделы firewall"
}, ed = { class: "gw-policy-grid" }, td = ["onUpdate:modelValue"], nd = { class: "gw-policy-grid" }, ld = ["onUpdate:modelValue"], sd = { class: "gw-two" }, od = ["onUpdate:modelValue"], id = ["onUpdate:modelValue"], ad = ["open", "onInput", "onChange"], rd = { class: "gw-rule-fields" }, ud = ["onClick"], dd = {
  key: 0,
  class: "gw-hint"
}, cd = ["onUpdate:modelValue"], fd = { class: "gw-two" }, pd = ["onUpdate:modelValue"], vd = ["value"], gd = ["onUpdate:modelValue"], hd = ["value"], md = { class: "gw-two" }, bd = ["onUpdate:modelValue"], yd = ["value"], wd = ["onUpdate:modelValue"], _d = { class: "gw-two" }, kd = ["onUpdate:modelValue"], $d = ["onUpdate:modelValue"], Cd = {
  key: 0,
  class: "gw-hint"
}, xd = { class: "gw-section-header" }, Sd = ["disabled"], Td = {
  key: 0,
  class: "gw-notice"
}, Vd = {
  key: 1,
  class: "gw-hint"
}, Pd = ["open", "onInput", "onChange"], Ud = { class: "gw-rule-fields" }, Ad = ["onClick"], Ed = ["onUpdate:modelValue"], Id = { class: "gw-two" }, Md = ["onUpdate:modelValue"], Od = ["value"], Rd = ["onUpdate:modelValue"], Dd = ["value"], Fd = { class: "gw-two" }, qd = ["onUpdate:modelValue"], Nd = ["onUpdate:modelValue"], Hd = { class: "gw-two" }, Ld = ["onUpdate:modelValue"], jd = ["onUpdate:modelValue"], Wd = ["onUpdate:modelValue"], Bd = { class: "gw-two" }, Kd = ["onUpdate:modelValue"], Gd = ["onUpdate:modelValue"], zd = {
  key: 2,
  class: "gw-hint"
}, Jd = { class: "gw-actions" }, Yd = ["disabled"], Xd = ["disabled"], Zd = { key: 3 }, ps = /* @__PURE__ */ Me({
  __name: "RouterSettings",
  props: {
    node: {},
    bridge: {},
    mode: {},
    iface: {},
    reservationForm: {},
    onTaskDone: { type: Function }
  },
  emits: ["close", "changed"],
  setup(e, { emit: t }) {
    const n = e, o = t, s = /* @__PURE__ */ D(null), i = /* @__PURE__ */ D({}), a = /* @__PURE__ */ D(null), u = /* @__PURE__ */ D(!1), c = /* @__PURE__ */ D(""), g = /* @__PURE__ */ D("general"), m = /* @__PURE__ */ D([]), w = /* @__PURE__ */ D(/* @__PURE__ */ new Set()), A = /* @__PURE__ */ D([]), V = /* @__PURE__ */ D(/* @__PURE__ */ new Set()), L = ["id", "name", "src", "dest", "src_ip", "dest_ip", "proto", "src_dport", "dest_port", "enabled", "reflection"], R = { dhcp: "DHCP-сервер", dns: "Настройки DNSMasq", firewall: "Настройки Firewall", dhcp_reservation: { add: "Закрепить IPv4-адрес", edit: "Изменить статическую DHCP-аренду", delete: "Удалить статическую DHCP-аренду" }[n.reservationForm?.mode || "add"] }, ne = (U) => String(U || "").split(/[\s,]+/).filter(Boolean), X = (U) => Array.isArray(U) ? U.join(", ") : U || "", Z = () => "/api/gateways/" + encodeURIComponent(n.node.id), ee = (U, d, r = "POST") => n.bridge.request(Z() + U, { method: r, headers: { "Content-Type": "application/json" }, body: JSON.stringify(d) });
    function j(U) {
      const d = s.value.dns.find((r) => r.id === U) || {};
      i.value = { ...d, port: d.port ?? "53", server: X(d.server), cachesize: d.cachesize ?? "150", domain: d.domain || "", local: d.local || "", noresolv: d.noresolv === "1", rebind_protection: d.rebind_protection !== "0", domainneeded: d.domainneeded === "1", boguspriv: d.boguspriv !== "0" };
    }
    async function le() {
      u.value = !0;
      try {
        if (s.value = await n.bridge.request(Z() + "/network"), n.mode === "dns") j(s.value.dns[0]?.id);
        else if (n.mode === "dhcp") {
          const U = s.value.dhcp.find((d) => d.interface === n.iface);
          i.value = { ignore: !U || U.ignore === "1", start: U?.start ?? "100", limit: U?.limit ?? "150", leasetime: U?.leasetime || "12h", dns: X(U?.dns) };
        } else {
          const U = s.value.firewall;
          i.value = { redirectsSupported: Array.isArray(U.redirects), redirects: (U.redirects || []).filter((d) => !d.target || d.target === "DNAT").map((d) => ({ ...d })), defaults: { input: "REJECT", output: "ACCEPT", forward: "REJECT", ...U.defaults }, zones: U.zones.map((d) => ({ ...d })), rules: U.rules.map((d) => ({ ...d, editable: !d.target || ["ACCEPT", "REJECT", "DROP"].includes(d.target) })) };
        }
      } catch (U) {
        c.value = U.message;
      } finally {
        u.value = !1;
      }
    }
    function Q(U) {
      const d = i.value.rules[U];
      d.id && m.value.push(d.id), i.value.rules.splice(U, 1);
    }
    function I(U) {
      U.id && w.value.add(U.id);
    }
    function E() {
      g.value = "rules", i.value.rules.push({ name: "", src: "lan", dest: "", proto: "tcp", dest_port: "", target: "ACCEPT", enabled: "1", editable: !0 });
    }
    function P() {
      g.value = "redirects", i.value.redirects.push({ name: "", src: "wan", dest: "lan", proto: ["tcp", "udp"], src_dport: "", dest_ip: "", dest_port: "", enabled: "1", reflection: "1" });
    }
    function S(U) {
      const d = i.value.redirects[U];
      d.id && A.value.push(d.id), i.value.redirects.splice(U, 1);
    }
    function C(U) {
      U.id && V.value.add(U.id);
    }
    function ie(U, d) {
      const r = {};
      for (const v of d) U[v] !== void 0 && (r[v] = U[v] === "" ? null : U[v]);
      return r;
    }
    async function ke(U = n.mode) {
      u.value = !0, c.value = "";
      try {
        const d = { config_hash: s.value.settings_hash }, r = i.value;
        if (U === "dhcp_reservation" && n.reservationForm) {
          const { mode: v, reservation: _ } = n.reservationForm;
          d.mode = v, _ && (d.section = _.id), v !== "delete" && (d.settings = { ip: r.ip, mac: r.mac, name: r.name || null });
        }
        U === "dhcp" && Object.assign(d, { interface: n.iface, settings: { ignore: r.ignore ? "1" : "0", start: String(r.start), limit: String(r.limit), leasetime: r.leasetime, dns: ne(r.dns) } }), U === "dns" && Object.assign(d, { section: r.id, settings: { port: String(r.port), server: ne(r.server), cachesize: String(r.cachesize), domain: r.domain || null, local: r.local || null, noresolv: r.noresolv ? "1" : "0", rebind_protection: r.rebind_protection ? "1" : "0", domainneeded: r.domainneeded ? "1" : "0", boguspriv: r.boguspriv ? "1" : "0" } }), U === "firewall" && Object.assign(d, { settings: ie(r.defaults, ["input", "output", "forward", "synflood_protect"]), zones: r.zones.map((v) => ie(v, ["id", "input", "output", "forward", "masq", "mtu_fix"])), rules: r.rules.filter((v) => !v.id || w.value.has(v.id)).map((v) => ie(v, ["id", "name", "src", "dest", "src_ip", "dest_ip", "proto", "dest_port", "target", "enabled"])), deleted_rules: m.value }), U === "firewall" && r.redirectsSupported && Object.assign(d, { redirects: r.redirects.filter((v) => !v.id || V.value.has(v.id)).map((v) => ie(v, L)), deleted_redirects: A.value }), a.value = await ee("/network/plan", { action: U, data: d });
      } catch (d) {
        c.value = d.message;
      } finally {
        u.value = !1;
      }
    }
    async function ae() {
      u.value = !0;
      try {
        const U = a.value, d = await ee("/router-operations", { plan_token: U.plan_token, confirmed: !0 }), r = n.onTaskDone ?? (() => o("changed"));
        a.value = null, o("close", !0), n.bridge.task({ taskId: d.task_id, title: U.title, cancellable: !1, onDone: r });
      } catch (U) {
        c.value = U.message;
      } finally {
        u.value = !1;
      }
    }
    function z() {
      const U = a.value?.plan_token;
      a.value = null, c.value = "", U && ee("/operation-plans/" + encodeURIComponent(U), {}, "DELETE").catch((d) => {
        c.value = d.message;
      });
    }
    return ot(() => {
      const U = n.reservationForm;
      if (!U) {
        le();
        return;
      }
      const { reservation: d, lease: r } = U;
      s.value = { settings_hash: U.configHash };
      const v = r?.hostname === "*" ? "" : r?.hostname;
      i.value = {
        name: d?.name || v || "",
        ip: d?.ip || r?.ipaddr || "",
        mac: d?.mac.join(" ") || r?.macaddr || ""
      };
    }), (U, d) => (f(), me(Re, {
      title: a.value ? "Проверка изменений" : R[e.mode] + (e.iface ? " · " + e.iface : ""),
      wide: !0,
      busy: u.value,
      onClose: d[24] || (d[24] = (r) => a.value ? z() : o("close"))
    }, {
      default: Ie(() => [
        c.value ? (f(), h("p", Vu, b(c.value), 1)) : x("", !0),
        a.value ? (f(), h(q, { key: 1 }, [
          l("ul", Pu, [
            (f(!0), h(q, null, oe(a.value.summary, (r, v) => (f(), h("li", { key: v }, b(r), 1))), 128))
          ]),
          a.value.warnings?.length ? (f(), h("section", Uu, [
            d[25] || (d[25] = l("h3", null, "Последствия изменений", -1)),
            l("ul", null, [
              (f(!0), h(q, null, oe(a.value.warnings, (r, v) => (f(), h("li", { key: v }, b(r), 1))), 128))
            ])
          ])) : x("", !0),
          l("p", Au, "Если панель не подтвердит результат в течение " + b(a.value.rollback_seconds) + " секунд, роутер вернёт прежнюю конфигурацию. Изменения, сделанные параллельно в LuCI, не будут перезаписаны.", 1),
          l("div", Eu, [
            l("button", {
              class: "gw-primary",
              disabled: u.value,
              onClick: ae
            }, "Да, применить", 8, Iu),
            l("button", {
              disabled: u.value,
              onClick: z
            }, "Назад", 8, Mu)
          ])
        ], 64)) : s.value ? (f(), h("form", {
          key: 2,
          class: "gw-form",
          onSubmit: d[23] || (d[23] = tt((r) => ke(), ["prevent"]))
        }, [
          e.reservationForm?.mode === "delete" ? (f(), h(q, { key: 0 }, [
            l("p", null, [
              M(b(i.value.name || "Без имени") + " · " + b(i.value.ip), 1),
              i.value.mac ? (f(), h(q, { key: 0 }, [
                M(" · " + b(i.value.mac), 1)
              ], 64)) : x("", !0)
            ]),
            e.reservationForm.reservation?.shared_ipv6 ? (f(), h("p", Ou, "Настройки IPv6 этой записи сохранятся.")) : x("", !0)
          ], 64)) : e.mode === "dhcp_reservation" ? (f(), h(q, { key: 1 }, [
            l("label", null, [
              d[26] || (d[26] = M("Имя устройства", -1)),
              H(l("input", {
                "onUpdate:modelValue": d[0] || (d[0] = (r) => i.value.name = r),
                maxlength: "63"
              }, null, 512), [
                [
                  re,
                  i.value.name,
                  void 0,
                  { trim: !0 }
                ]
              ])
            ]),
            l("label", null, [
              d[27] || (d[27] = M("MAC-адрес", -1)),
              H(l("input", {
                "onUpdate:modelValue": d[1] || (d[1] = (r) => i.value.mac = r),
                maxlength: "256",
                required: e.reservationForm?.mode === "add" || !!e.reservationForm?.reservation?.mac.length,
                readonly: e.reservationForm?.reservation?.shared_ipv6
              }, null, 8, Ru), [
                [
                  re,
                  i.value.mac,
                  void 0,
                  { trim: !0 }
                ]
              ]),
              l("small", null, b(e.reservationForm?.reservation?.shared_ipv6 ? "MAC используется также для IPv6" : "Несколько адресов можно указать через пробел"), 1)
            ]),
            l("label", null, [
              d[28] || (d[28] = M("IPv4-адрес", -1)),
              H(l("input", {
                "onUpdate:modelValue": d[2] || (d[2] = (r) => i.value.ip = r),
                inputmode: "decimal",
                placeholder: "192.168.1.10",
                maxlength: "15",
                required: ""
              }, null, 512), [
                [
                  re,
                  i.value.ip,
                  void 0,
                  { trim: !0 }
                ]
              ])
            ])
          ], 64)) : x("", !0),
          e.mode === "dhcp" ? (f(), h(q, { key: 2 }, [
            l("label", Du, [
              H(l("input", {
                "onUpdate:modelValue": d[3] || (d[3] = (r) => i.value.ignore = r),
                type: "checkbox"
              }, null, 512), [
                [je, i.value.ignore]
              ]),
              M(" Выключить DHCP-сервер на " + b(e.iface), 1)
            ]),
            i.value.ignore ? x("", !0) : (f(), h("p", Fu, "В одном сегменте должен работать один DHCP-сервер. При наличии основного роутера оставьте DHCP здесь выключенным.")),
            l("div", qu, [
              l("label", null, [
                d[29] || (d[29] = M("Начальный адрес (смещение в подсети)", -1)),
                H(l("input", {
                  "onUpdate:modelValue": d[4] || (d[4] = (r) => i.value.start = r),
                  type: "number",
                  min: "0",
                  disabled: i.value.ignore,
                  required: ""
                }, null, 8, Nu), [
                  [re, i.value.start]
                ])
              ]),
              l("label", null, [
                d[30] || (d[30] = M("Количество адресов", -1)),
                H(l("input", {
                  "onUpdate:modelValue": d[5] || (d[5] = (r) => i.value.limit = r),
                  type: "number",
                  min: "1",
                  disabled: i.value.ignore,
                  required: ""
                }, null, 8, Hu), [
                  [re, i.value.limit]
                ])
              ])
            ]),
            l("label", null, [
              d[31] || (d[31] = M("Время аренды", -1)),
              H(l("input", {
                "onUpdate:modelValue": d[6] || (d[6] = (r) => i.value.leasetime = r),
                placeholder: "12h"
              }, null, 512), [
                [re, i.value.leasetime]
              ])
            ]),
            l("label", null, [
              d[32] || (d[32] = M("DNS для DHCP-клиентов (IPv4)", -1)),
              H(l("input", {
                "onUpdate:modelValue": d[7] || (d[7] = (r) => i.value.dns = r),
                placeholder: "Пусто — адрес роутера"
              }, null, 512), [
                [re, i.value.dns]
              ]),
              d[33] || (d[33] = l("small", null, "Меняется только DHCP option 6. Другие опции, статические аренды и настройки IPv6 сохраняются. Клиенты получат изменение при обновлении аренды.", -1))
            ])
          ], 64)) : x("", !0),
          e.mode === "dns" ? (f(), h(q, { key: 3 }, [
            d[46] || (d[46] = l("p", { class: "gw-hint" }, "DNS подключения WAN задаётся в его настройках. Здесь — локальный DNS-сервис dnsmasq и серверы, на которые он отправляет запросы.", -1)),
            s.value.dns.length > 1 ? (f(), h("label", Lu, [
              d[34] || (d[34] = M("Экземпляр dnsmasq", -1)),
              l("select", {
                value: i.value.id,
                onChange: d[8] || (d[8] = (r) => j(r.target.value))
              }, [
                (f(!0), h(q, null, oe(s.value.dns, (r) => (f(), h("option", {
                  key: r.id,
                  value: r.id
                }, b(r.id), 9, Wu))), 128))
              ], 40, ju)
            ])) : x("", !0),
            s.value.dns.length ? (f(), h(q, { key: 2 }, [
              l("div", Ku, [
                l("label", null, [
                  d[35] || (d[35] = M("Порт DNS", -1)),
                  H(l("input", {
                    "onUpdate:modelValue": d[9] || (d[9] = (r) => i.value.port = r),
                    type: "number",
                    min: "0",
                    max: "65535",
                    required: ""
                  }, null, 512), [
                    [re, i.value.port]
                  ]),
                  d[36] || (d[36] = l("small", null, "53 — обычный DNS; 0 отключает только DNS.", -1))
                ]),
                l("label", null, [
                  d[37] || (d[37] = M("Размер кэша", -1)),
                  H(l("input", {
                    "onUpdate:modelValue": d[10] || (d[10] = (r) => i.value.cachesize = r),
                    type: "number",
                    min: "0",
                    required: ""
                  }, null, 512), [
                    [re, i.value.cachesize]
                  ])
                ])
              ]),
              l("label", null, [
                d[38] || (d[38] = M("Внешние DNS-серверы", -1)),
                H(l("textarea", {
                  "onUpdate:modelValue": d[11] || (d[11] = (r) => i.value.server = r),
                  rows: "3",
                  placeholder: `1.1.1.1
127.0.0.1#5353
/example.org/192.168.1.2`
                }, null, 512), [
                  [re, i.value.server]
                ]),
                d[39] || (d[39] = l("small", null, "По одному серверу на строку; адрес#порт, /домен/адрес#порт.", -1))
              ]),
              l("label", Gu, [
                H(l("input", {
                  "onUpdate:modelValue": d[12] || (d[12] = (r) => i.value.noresolv = r),
                  type: "checkbox"
                }, null, 512), [
                  [je, i.value.noresolv]
                ]),
                d[40] || (d[40] = M(" Использовать только указанные upstream (не получать DNS от WAN)", -1))
              ]),
              l("div", zu, [
                l("label", null, [
                  d[41] || (d[41] = M("Локальный домен", -1)),
                  H(l("input", {
                    "onUpdate:modelValue": d[13] || (d[13] = (r) => i.value.domain = r),
                    placeholder: "lan"
                  }, null, 512), [
                    [re, i.value.domain]
                  ])
                ]),
                l("label", null, [
                  d[42] || (d[42] = M("Локальная зона", -1)),
                  H(l("input", {
                    "onUpdate:modelValue": d[14] || (d[14] = (r) => i.value.local = r),
                    placeholder: "/lan/"
                  }, null, 512), [
                    [re, i.value.local]
                  ])
                ])
              ]),
              l("label", Ju, [
                H(l("input", {
                  "onUpdate:modelValue": d[15] || (d[15] = (r) => i.value.rebind_protection = r),
                  type: "checkbox"
                }, null, 512), [
                  [je, i.value.rebind_protection]
                ]),
                d[43] || (d[43] = M(" Защита DNS rebinding", -1))
              ]),
              l("label", Yu, [
                H(l("input", {
                  "onUpdate:modelValue": d[16] || (d[16] = (r) => i.value.domainneeded = r),
                  type: "checkbox"
                }, null, 512), [
                  [je, i.value.domainneeded]
                ]),
                d[44] || (d[44] = M(" Не отправлять имена без домена", -1))
              ]),
              l("label", Xu, [
                H(l("input", {
                  "onUpdate:modelValue": d[17] || (d[17] = (r) => i.value.boguspriv = r),
                  type: "checkbox"
                }, null, 512), [
                  [je, i.value.boguspriv]
                ]),
                d[45] || (d[45] = M(" Не отправлять обратные запросы частных адресов", -1))
              ]),
              i.value.nftset || i.value.ipset ? (f(), h("p", Zu, "dnsmasq использует наборы для маршрутизации. При переходе на AdGuard Home сохраните путь запросов через dnsmasq для нужных доменов.")) : x("", !0)
            ], 64)) : (f(), h("p", Bu, "dnsmasq не настроен. Сначала установите или настройте его в LuCI."))
          ], 64)) : x("", !0),
          e.mode === "firewall" ? (f(), h(q, { key: 4 }, [
            d[91] || (d[91] = l("p", { class: "gw-hint" }, "Основные политики, зоны, правила трафика и перенаправления портов. Расширенные параметры и специальные правила NAT сохраняются.", -1)),
            l("nav", Qu, [
              l("button", {
                type: "button",
                class: Te({ on: g.value === "general" }),
                onClick: d[18] || (d[18] = (r) => g.value = "general")
              }, "Общие настройки", 2),
              l("button", {
                type: "button",
                class: Te({ on: g.value === "zones" }),
                onClick: d[19] || (d[19] = (r) => g.value = "zones")
              }, "Зоны (" + b(i.value.zones.length) + ")", 3),
              l("button", {
                type: "button",
                class: Te({ on: g.value === "rules" }),
                onClick: d[20] || (d[20] = (r) => g.value = "rules")
              }, "Правила трафика (" + b(i.value.rules.length) + ")", 3),
              l("button", {
                type: "button",
                class: Te({ on: g.value === "redirects" }),
                onClick: d[21] || (d[21] = (r) => g.value = "redirects")
              }, "Перенаправление портов (" + b(i.value.redirects.length) + ")", 3)
            ]),
            H(l("section", null, [
              d[48] || (d[48] = l("h3", null, "Политики по умолчанию", -1)),
              d[49] || (d[49] = l("p", { class: "gw-hint" }, "Применяются к трафику, для которого не задано отдельное правило.", -1)),
              l("div", ed, [
                (f(), h(q, null, oe(["input", "output", "forward"], (r) => l("label", { key: r }, [
                  M(b({ input: "Входящие", output: "Исходящие", forward: "Пересылка" }[r]), 1),
                  H(l("select", {
                    "onUpdate:modelValue": (v) => i.value.defaults[r] = v
                  }, [...d[47] || (d[47] = [
                    l("option", null, "ACCEPT", -1),
                    l("option", null, "REJECT", -1),
                    l("option", null, "DROP", -1)
                  ])], 8, td), [
                    [xe, i.value.defaults[r]]
                  ])
                ])), 64))
              ])
            ], 512), [
              [hn, g.value === "general"]
            ]),
            H(l("section", null, [
              d[55] || (d[55] = l("h3", null, "Зоны", -1)),
              d[56] || (d[56] = l("p", { class: "gw-hint" }, "Политики для групп сетевых интерфейсов. Правила отдельных соединений находятся на вкладке «Правила трафика».", -1)),
              (f(!0), h(q, null, oe(i.value.zones, (r) => (f(), h("article", {
                key: r.id,
                class: "gw-settings-row"
              }, [
                l("h4", null, b(r.name) + " · " + b(X(r.network)), 1),
                l("div", nd, [
                  (f(), h(q, null, oe(["input", "output", "forward"], (v) => l("label", { key: v }, [
                    M(b({ input: "Входящие", output: "Исходящие", forward: "Пересылка" }[v]), 1),
                    H(l("select", {
                      "onUpdate:modelValue": (_) => r[v] = _
                    }, [...d[50] || (d[50] = [
                      l("option", null, "ACCEPT", -1),
                      l("option", null, "REJECT", -1),
                      l("option", null, "DROP", -1)
                    ])], 8, ld), [
                      [xe, r[v]]
                    ])
                  ])), 64))
                ]),
                l("div", sd, [
                  l("label", null, [
                    d[52] || (d[52] = M("NAT (маскарадинг)", -1)),
                    H(l("select", {
                      "onUpdate:modelValue": (v) => r.masq = v
                    }, [...d[51] || (d[51] = [
                      l("option", { value: void 0 }, "По умолчанию", -1),
                      l("option", { value: "1" }, "Включён", -1),
                      l("option", { value: "0" }, "Выключен", -1)
                    ])], 8, od), [
                      [xe, r.masq]
                    ])
                  ]),
                  l("label", null, [
                    d[54] || (d[54] = M("Коррекция MSS", -1)),
                    H(l("select", {
                      "onUpdate:modelValue": (v) => r.mtu_fix = v
                    }, [...d[53] || (d[53] = [
                      l("option", { value: void 0 }, "По умолчанию", -1),
                      l("option", { value: "1" }, "Включён", -1),
                      l("option", { value: "0" }, "Выключен", -1)
                    ])], 8, id), [
                      [xe, r.mtu_fix]
                    ])
                  ])
                ])
              ]))), 128))
            ], 512), [
              [hn, g.value === "zones"]
            ]),
            H(l("section", null, [
              l("header", { class: "gw-section-header" }, [
                d[57] || (d[57] = l("h3", null, "Правила трафика", -1)),
                l("button", {
                  type: "button",
                  onClick: E
                }, "Добавить правило")
              ]),
              (f(!0), h(q, null, oe(i.value.rules, (r, v) => (f(), h("details", {
                key: r.id || v,
                open: !r.id,
                class: "gw-settings-rule",
                onInput: (_) => I(r),
                onChange: (_) => I(r)
              }, [
                l("summary", null, [
                  l("strong", null, b(r.name || r.id || "Новое правило"), 1),
                  l("span", null, b(r.src || "Роутер") + " → " + b(r.dest || "Роутер") + " · " + b(X(r.proto) || "all") + " " + b(r.dest_port || "") + " · " + b(r.target || "ACCEPT"), 1),
                  l("small", null, b(r.enabled === "0" ? "Выключено" : "Включено"), 1)
                ]),
                l("div", rd, [
                  l("button", {
                    type: "button",
                    class: "gw-danger",
                    onClick: (_) => Q(Number(v))
                  }, "Удалить правило", 8, ud),
                  r.editable ? (f(), h(q, { key: 1 }, [
                    l("label", null, [
                      d[58] || (d[58] = M("Название", -1)),
                      H(l("input", {
                        "onUpdate:modelValue": (_) => r.name = _
                      }, null, 8, cd), [
                        [re, r.name]
                      ])
                    ]),
                    l("div", fd, [
                      l("label", null, [
                        d[61] || (d[61] = M("Исходная зона", -1)),
                        H(l("select", {
                          "onUpdate:modelValue": (_) => r.src = _
                        }, [
                          d[59] || (d[59] = l("option", { value: "" }, "Сам роутер", -1)),
                          d[60] || (d[60] = l("option", { value: "*" }, "Любая", -1)),
                          (f(!0), h(q, null, oe(i.value.zones, (_) => (f(), h("option", {
                            key: _.id,
                            value: _.name
                          }, b(_.name), 9, vd))), 128))
                        ], 8, pd), [
                          [xe, r.src]
                        ])
                      ]),
                      l("label", null, [
                        d[64] || (d[64] = M("Зона назначения", -1)),
                        H(l("select", {
                          "onUpdate:modelValue": (_) => r.dest = _
                        }, [
                          d[62] || (d[62] = l("option", { value: "" }, "Сам роутер", -1)),
                          d[63] || (d[63] = l("option", { value: "*" }, "Любая", -1)),
                          (f(!0), h(q, null, oe(i.value.zones, (_) => (f(), h("option", {
                            key: _.id,
                            value: _.name
                          }, b(_.name), 9, hd))), 128))
                        ], 8, gd), [
                          [xe, r.dest]
                        ])
                      ])
                    ]),
                    l("div", md, [
                      l("label", null, [
                        d[70] || (d[70] = M("Протокол", -1)),
                        H(l("select", {
                          "onUpdate:modelValue": (_) => r.proto = _
                        }, [
                          Array.isArray(r.proto) ? (f(), h("option", {
                            key: 0,
                            value: r.proto
                          }, b(X(r.proto)), 9, yd)) : x("", !0),
                          d[65] || (d[65] = l("option", null, "tcp", -1)),
                          d[66] || (d[66] = l("option", null, "udp", -1)),
                          d[67] || (d[67] = l("option", null, "icmp", -1)),
                          d[68] || (d[68] = l("option", null, "icmpv6", -1)),
                          d[69] || (d[69] = l("option", null, "all", -1))
                        ], 8, bd), [
                          [xe, r.proto]
                        ])
                      ]),
                      l("label", null, [
                        d[71] || (d[71] = M("Порт назначения", -1)),
                        H(l("input", {
                          "onUpdate:modelValue": (_) => r.dest_port = _,
                          placeholder: "443 или 1000-2000"
                        }, null, 8, wd), [
                          [re, r.dest_port]
                        ])
                      ])
                    ]),
                    l("div", _d, [
                      l("label", null, [
                        d[73] || (d[73] = M("Действие", -1)),
                        H(l("select", {
                          "onUpdate:modelValue": (_) => r.target = _
                        }, [...d[72] || (d[72] = [
                          l("option", null, "ACCEPT", -1),
                          l("option", null, "REJECT", -1),
                          l("option", null, "DROP", -1)
                        ])], 8, kd), [
                          [xe, r.target]
                        ])
                      ]),
                      l("label", null, [
                        d[75] || (d[75] = M("Состояние", -1)),
                        H(l("select", {
                          "onUpdate:modelValue": (_) => r.enabled = _
                        }, [...d[74] || (d[74] = [
                          l("option", { value: void 0 }, "Включено по умолчанию", -1),
                          l("option", { value: "1" }, "Включено", -1),
                          l("option", { value: "0" }, "Выключено", -1)
                        ])], 8, $d), [
                          [xe, r.enabled]
                        ])
                      ])
                    ])
                  ], 64)) : (f(), h("p", dd, b(r.target) + " · Расширенное правило. Редактирование доступно в LuCI.", 1))
                ])
              ], 40, ad))), 128)),
              i.value.rules.length ? x("", !0) : (f(), h("p", Cd, "Правила трафика не настроены."))
            ], 512), [
              [hn, g.value === "rules"]
            ]),
            H(l("section", null, [
              l("header", xd, [
                d[76] || (d[76] = l("h3", null, "Перенаправление портов", -1)),
                l("button", {
                  type: "button",
                  disabled: !i.value.redirectsSupported,
                  onClick: P
                }, "Добавить перенаправление", 8, Sd)
              ]),
              i.value.redirectsSupported ? (f(), h("p", Vd, "Внешний порт → IP устройства и внутренний порт. Изменения применяются после проверки плана.")) : (f(), h("p", Td, "Обновите интеграцию Bot4VPS на шлюзе для управления перенаправлениями портов.")),
              (f(!0), h(q, null, oe(i.value.redirects, (r, v) => (f(), h("details", {
                key: r.id || v,
                open: !r.id,
                class: "gw-settings-rule",
                onInput: (_) => C(r),
                onChange: (_) => C(r)
              }, [
                l("summary", null, [
                  l("strong", null, b(r.name || r.id || "Новое перенаправление"), 1),
                  l("span", null, b(r.src) + ":" + b(r.src_dport) + " → " + b(r.dest_ip || "Роутер") + ":" + b(r.dest_port || r.src_dport) + " · " + b(X(r.proto) || "TCP и UDP"), 1),
                  l("small", null, b(r.enabled === "0" ? "Выключено" : "Включено"), 1)
                ]),
                l("div", Ud, [
                  l("button", {
                    type: "button",
                    class: "gw-danger",
                    onClick: (_) => S(Number(v))
                  }, "Удалить перенаправление", 8, Ad),
                  l("label", null, [
                    d[77] || (d[77] = M("Название", -1)),
                    H(l("input", {
                      "onUpdate:modelValue": (_) => r.name = _
                    }, null, 8, Ed), [
                      [re, r.name]
                    ])
                  ]),
                  l("div", Id, [
                    l("label", null, [
                      d[78] || (d[78] = M("Исходная зона", -1)),
                      H(l("select", {
                        "onUpdate:modelValue": (_) => r.src = _
                      }, [
                        (f(!0), h(q, null, oe(i.value.zones, (_) => (f(), h("option", {
                          key: _.id,
                          value: _.name
                        }, b(_.name), 9, Od))), 128))
                      ], 8, Md), [
                        [xe, r.src]
                      ])
                    ]),
                    l("label", null, [
                      d[79] || (d[79] = M("Зона назначения", -1)),
                      H(l("select", {
                        "onUpdate:modelValue": (_) => r.dest = _
                      }, [
                        (f(!0), h(q, null, oe(i.value.zones, (_) => (f(), h("option", {
                          key: _.id,
                          value: _.name
                        }, b(_.name), 9, Dd))), 128))
                      ], 8, Rd), [
                        [xe, r.dest]
                      ])
                    ])
                  ]),
                  l("div", Fd, [
                    l("label", null, [
                      d[80] || (d[80] = M("Внешний порт", -1)),
                      H(l("input", {
                        "onUpdate:modelValue": (_) => r.src_dport = _,
                        placeholder: "443 или 1000-2000"
                      }, null, 8, qd), [
                        [re, r.src_dport]
                      ])
                    ]),
                    l("label", null, [
                      d[81] || (d[81] = M("IP устройства назначения", -1)),
                      H(l("input", {
                        "onUpdate:modelValue": (_) => r.dest_ip = _,
                        placeholder: "192.168.1.10"
                      }, null, 8, Nd), [
                        [re, r.dest_ip]
                      ])
                    ])
                  ]),
                  l("div", Hd, [
                    l("label", null, [
                      d[82] || (d[82] = M("Внутренний порт", -1)),
                      H(l("input", {
                        "onUpdate:modelValue": (_) => r.dest_port = _,
                        placeholder: "Пусто — внешний порт"
                      }, null, 8, Ld), [
                        [re, r.dest_port]
                      ])
                    ]),
                    l("label", null, [
                      d[84] || (d[84] = M("Протокол", -1)),
                      H(l("select", {
                        "onUpdate:modelValue": (_) => r.proto = _
                      }, [...d[83] || (d[83] = [
                        l("option", { value: ["tcp", "udp"] }, "TCP и UDP", -1),
                        l("option", { value: "tcp" }, "TCP", -1),
                        l("option", { value: "udp" }, "UDP", -1)
                      ])], 8, jd), [
                        [xe, r.proto]
                      ])
                    ])
                  ]),
                  l("label", null, [
                    d[85] || (d[85] = M("Разрешённый IP источника", -1)),
                    H(l("input", {
                      "onUpdate:modelValue": (_) => r.src_ip = _,
                      placeholder: "Пусто — любой адрес; можно CIDR"
                    }, null, 8, Wd), [
                      [re, r.src_ip]
                    ])
                  ]),
                  l("div", Bd, [
                    l("label", null, [
                      d[87] || (d[87] = M("Состояние", -1)),
                      H(l("select", {
                        "onUpdate:modelValue": (_) => r.enabled = _
                      }, [...d[86] || (d[86] = [
                        l("option", { value: void 0 }, "Включено по умолчанию", -1),
                        l("option", { value: "1" }, "Включено", -1),
                        l("option", { value: "0" }, "Выключено", -1)
                      ])], 8, Kd), [
                        [xe, r.enabled]
                      ])
                    ]),
                    l("label", null, [
                      d[89] || (d[89] = M("NAT loopback", -1)),
                      H(l("select", {
                        "onUpdate:modelValue": (_) => r.reflection = _
                      }, [...d[88] || (d[88] = [
                        l("option", { value: void 0 }, "По умолчанию", -1),
                        l("option", { value: "1" }, "Включён", -1),
                        l("option", { value: "0" }, "Выключен", -1)
                      ])], 8, Gd), [
                        [xe, r.reflection]
                      ]),
                      d[90] || (d[90] = l("small", null, "Доступ из LAN через внешний адрес.", -1))
                    ])
                  ])
                ])
              ], 40, Pd))), 128)),
              i.value.redirectsSupported && !i.value.redirects.length ? (f(), h("p", zd, "Перенаправления не настроены.")) : x("", !0)
            ], 512), [
              [hn, g.value === "redirects"]
            ])
          ], 64)) : x("", !0),
          l("div", Jd, [
            l("button", {
              class: "gw-primary",
              disabled: u.value || e.mode === "dns" && !s.value.dns.length
            }, "Проверить изменения", 8, Yd),
            l("button", {
              type: "button",
              disabled: u.value,
              onClick: d[22] || (d[22] = (r) => o("close"))
            }, "Закрыть", 8, Xd)
          ])
        ], 32)) : u.value ? (f(), h("p", Zd, "Получаем конфигурацию…")) : x("", !0)
      ]),
      _: 1
    }, 8, ["title", "busy"]));
  }
}), Qd = { class: "gw-password" }, ec = ["type"], tc = ["aria-label", "title", "aria-pressed"], vt = /* @__PURE__ */ Me({
  inheritAttrs: !1,
  __name: "PasswordInput",
  props: {
    modelValue: { required: !0 },
    modelModifiers: {}
  },
  emits: ["update:modelValue"],
  setup(e) {
    const t = Xa(e, "modelValue"), n = /* @__PURE__ */ D(!1);
    return We(t, (o) => {
      o || (n.value = !1);
    }), (o, s) => (f(), h("span", Qd, [
      H(l("input", si(o.$attrs, {
        "onUpdate:modelValue": s[0] || (s[0] = (i) => t.value = i),
        type: n.value ? "text" : "password",
        spellcheck: "false",
        autocapitalize: "off"
      }), null, 16, ec), [
        [Xr, t.value]
      ]),
      l("button", {
        type: "button",
        class: "gw-password-eye",
        "aria-label": n.value ? "Скрыть введённое" : "Показать введённое",
        title: n.value ? "Скрыть введённое" : "Показать введённое",
        "aria-pressed": n.value,
        onClick: s[1] || (s[1] = tt((i) => n.value = !n.value, ["prevent"]))
      }, "👁", 8, tc)
    ]));
  }
}), nc = { class: "gw-network" }, lc = { class: "gw-section-header" }, sc = { class: "gw-actions" }, oc = ["disabled"], ic = ["disabled"], ac = {
  key: 0,
  class: "gw-error",
  role: "alert"
}, rc = ["aria-busy"], uc = { class: "gw-interface-name" }, dc = { key: 0 }, cc = { class: "gw-interface-info" }, fc = { key: 0 }, pc = { class: "gw-interface-state" }, vc = { class: "gw-interface-actions" }, gc = ["disabled", "onClick"], hc = ["disabled", "onClick"], mc = ["disabled", "onClick"], bc = ["disabled", "title", "onClick"], yc = {
  key: 1,
  class: "gw-hint"
}, wc = { class: "gw-section-header gw-routes-heading" }, _c = ["disabled"], kc = {
  key: 2,
  class: "gw-table-wrap"
}, $c = {
  key: 3,
  class: "gw-hint"
}, Cc = { class: "gw-two" }, xc = ["readonly"], Sc = { key: 0 }, Tc = ["value"], Vc = { class: "gw-two" }, Pc = { class: "gw-two" }, Uc = { class: "gw-network-extra" }, Ac = { class: "gw-two" }, Ec = { class: "gw-check" }, Ic = { class: "gw-check" }, Mc = {
  key: 0,
  class: "gw-check"
}, Oc = { key: 4 }, Rc = { class: "gw-section-header" }, Dc = { class: "gw-section-header" }, Fc = ["onClick"], qc = ["onUpdate:modelValue"], Nc = { class: "gw-two" }, Hc = ["onUpdate:modelValue"], Lc = ["onUpdate:modelValue"], jc = ["onUpdate:modelValue"], Wc = { class: "gw-two" }, Bc = ["onUpdate:modelValue"], Kc = { class: "gw-check" }, Gc = ["onUpdate:modelValue"], zc = {
  key: 5,
  class: "gw-error",
  role: "alert"
}, Jc = { class: "gw-actions" }, Yc = ["disabled"], Xc = ["disabled"], Zc = ["disabled"], Qc = { class: "gw-section-header" }, ef = ["onClick"], tf = { class: "gw-two" }, nf = ["onUpdate:modelValue"], lf = ["onUpdate:modelValue"], sf = ["value"], of = { class: "gw-two" }, af = ["onUpdate:modelValue"], rf = ["onUpdate:modelValue"], uf = { class: "gw-two" }, df = ["onUpdate:modelValue"], cf = ["onUpdate:modelValue"], ff = { class: "gw-check" }, pf = ["onUpdate:modelValue"], vf = {
  key: 0,
  class: "gw-hint"
}, gf = {
  key: 1,
  class: "gw-error",
  role: "alert"
}, hf = { class: "gw-actions" }, mf = ["disabled"], bf = ["disabled"], yf = { class: "gw-change-list" }, wf = {
  key: 0,
  class: "gw-notice"
}, _f = {
  key: 1,
  class: "gw-error",
  role: "alert"
}, kf = { class: "gw-actions" }, $f = ["disabled"], Cf = ["disabled"], xf = /* @__PURE__ */ Me({
  __name: "NetworkEditor",
  props: {
    node: {},
    bridge: {}
  },
  emits: ["changed"],
  setup(e, { emit: t }) {
    const n = e, o = t, s = /* @__PURE__ */ D({ interfaces: [], routes: [], devices: [] }), i = /* @__PURE__ */ D(!1), a = /* @__PURE__ */ D(!1), u = /* @__PURE__ */ D(""), c = /* @__PURE__ */ D(null), g = /* @__PURE__ */ D(null), m = /* @__PURE__ */ D(""), w = /* @__PURE__ */ D(null), A = /* @__PURE__ */ D(!1), V = /* @__PURE__ */ D([]), L = he(() => [.../* @__PURE__ */ new Set([...s.value.devices || [], ...w.value?.device ? [w.value.device] : []])]);
    let R = !0;
    const ne = () => "/api/gateways/" + encodeURIComponent(n.node.id), X = (d, r, v = "POST") => n.bridge.request(ne() + d, { method: v, headers: { "Content-Type": "application/json" }, body: JSON.stringify(r) }), Z = (d) => Array.isArray(d) ? d.join(", ") : d || "", ee = (d) => d.split(/[\s,]+/).filter(Boolean), j = (d) => d === "" || d == null ? null : String(d);
    function le(d) {
      return n.node.monitor.interfaces?.find((r) => r.name === d.name) || d;
    }
    function Q(d) {
      return d.ipaddr === n.node.host || d.runtime_addresses?.includes(n.node.host);
    }
    async function I() {
      i.value = !0, u.value = "";
      try {
        const d = await n.bridge.request(ne() + "/network");
        R && (s.value = d);
      } catch (d) {
        R && (u.value = d.message);
      } finally {
        R && (i.value = !1);
      }
    }
    async function E(d) {
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
    function P(d) {
      u.value = "", w.value = {
        existing: !!d,
        name: d?.name || "",
        proto: d?.proto || "dhcp",
        device: d?.device || "",
        ipaddr: d?.ipaddr || "",
        netmask: d?.netmask || "255.255.255.0",
        gateway: d?.gateway || "",
        dns: Z(d?.dns),
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
        addresses: Z(d?.addresses),
        listen_port: d?.listen_port || "",
        peers: (d?.peers || []).map((r) => ({ ...r, allowed_ips: Z(r.allowed_ips), preshared_key: "", route_allowed_ips: r.route_allowed_ips === "1" }))
      };
    }
    async function S(d, r) {
      await E(async () => {
        const v = await X("/network/plan", { action: d, data: { ...r, config_hash: s.value.config_hash } });
        w.value = null, A.value = !1, c.value = v;
      });
    }
    async function C() {
      const d = w.value, r = {
        proto: d.proto,
        device: j(d.device),
        dns: ee(d.dns),
        metric: j(d.metric),
        mtu: j(d.mtu),
        auto: d.auto ? "1" : "0",
        defaultroute: d.defaultroute ? "1" : "0",
        peerdns: d.peerdns ? "1" : "0"
      };
      d.proto === "static" && Object.assign(r, { ipaddr: d.ipaddr, netmask: d.netmask, gateway: j(d.gateway) }), d.proto === "pppoe" && (r.username = d.username, d.password && (r.password = d.password));
      const v = { interface: d.name, settings: r };
      d.proto === "wireguard" && (r.addresses = ee(d.addresses), r.listen_port = j(d.listen_port), d.private_key && (r.private_key = d.private_key), v.peers = d.peers.map((_) => {
        const J = {
          public_key: _.public_key,
          endpoint_host: j(_.endpoint_host),
          endpoint_port: j(_.endpoint_port),
          allowed_ips: ee(_.allowed_ips || ""),
          persistent_keepalive: j(_.persistent_keepalive),
          route_allowed_ips: _.route_allowed_ips ? "1" : "0",
          description: j(_.description)
        };
        return _.id && (J.id = _.id), _.preshared_key && (J.preshared_key = _.preshared_key), J;
      })), await S("edit", v);
    }
    function ie() {
      u.value = "", V.value = s.value.routes.map((d) => ({
        interface: d.interface || "",
        target: d.target || "",
        netmask: d.netmask || "255.255.255.255",
        gateway: d.gateway || "",
        metric: d.metric || "",
        table: d.table || "",
        onlink: d.onlink === "1"
      })), A.value = !0;
    }
    function ke() {
      V.value.push({ interface: s.value.interfaces[0]?.name || "", target: "", netmask: "", gateway: "", metric: "", table: "", onlink: !1 });
    }
    async function ae() {
      await S("routes", { routes: V.value.map((d) => ({
        interface: d.interface,
        target: d.target,
        netmask: j(d.netmask),
        gateway: j(d.gateway),
        metric: j(d.metric),
        table: j(d.table),
        onlink: d.onlink ? "1" : "0"
      })) });
    }
    async function z() {
      await E(async () => {
        const d = c.value, r = await X("/router-operations", { plan_token: d.plan_token, confirmed: !0 });
        c.value = null, n.bridge.task({
          taskId: r.task_id,
          title: d.title + (d.interface ? " " + d.interface : ""),
          cancellable: !1,
          onDone: async () => {
            await I(), o("changed");
          }
        });
      });
    }
    function U() {
      const d = c.value?.plan_token;
      c.value = null, u.value = "", d && X("/operation-plans/" + encodeURIComponent(d), {}, "DELETE").catch((r) => {
        u.value = r.message;
      });
    }
    return ot(() => {
      I();
    }), yt(() => {
      R = !1, w.value = null;
    }), (d, r) => (f(), h(q, null, [
      l("section", nc, [
        l("header", lc, [
          r[26] || (r[26] = l("div", null, [
            l("h3", null, "Подключения"),
            l("p", { class: "gw-hint" }, "LAN, WAN и туннели · настройки и состояние")
          ], -1)),
          l("div", sc, [
            l("button", {
              disabled: i.value || a.value,
              onClick: I
            }, "Обновить", 8, oc),
            l("button", {
              disabled: i.value || a.value || !s.value.config_hash,
              onClick: r[0] || (r[0] = (v) => P())
            }, "Добавить подключение", 8, ic)
          ])
        ]),
        u.value && !w.value && !A.value && !c.value ? (f(), h("p", ac, b(u.value), 1)) : x("", !0),
        l("div", {
          class: "gw-interface-list",
          "aria-busy": i.value
        }, [
          (f(!0), h(q, null, oe(s.value.interfaces, (v) => (f(), h("article", {
            key: v.name,
            class: "gw-interface"
          }, [
            l("div", uc, [
              l("h4", null, b(v.name), 1),
              Q(v) ? (f(), h("small", dc, "Доступ к панели")) : x("", !0)
            ]),
            l("div", cc, [
              l("span", null, b(v.proto) + " · " + b(v.device || v.runtime_device || "—"), 1),
              l("strong", null, b(le(v).addresses?.join(", ") || v.runtime_addresses?.join(", ") || v.ipaddr || Z(v.addresses) || "Без адреса"), 1),
              v.gateway ? (f(), h("small", fc, "Шлюз " + b(v.gateway), 1)) : x("", !0)
            ]),
            l("div", pc, [
              l("span", {
                class: Te(["gw-status", le(v).up ? "good" : "warn"])
              }, b(le(v).up ? "Подключён" : le(v).pending ? "Подключается" : "Отключён"), 3)
            ]),
            l("div", vc, [
              l("button", {
                disabled: a.value,
                onClick: (_) => P(v)
              }, "Настроить", 8, gc),
              l("button", {
                disabled: a.value,
                onClick: (_) => {
                  m.value = v.name, g.value = "dhcp";
                }
              }, "DHCP", 8, hc),
              le(v).up ? (f(), h("button", {
                key: 0,
                disabled: a.value,
                onClick: (_) => S("reconnect", { interface: v.name })
              }, "Переподключить", 8, mc)) : x("", !0),
              l("button", {
                disabled: a.value || Q(v) && le(v).up,
                title: Q(v) ? "Интерфейс доступа изменяется через форму с откатом" : "",
                onClick: (_) => S(le(v).up ? "down" : "up", { interface: v.name })
              }, b(le(v).up ? "Отключить" : "Подключить"), 9, bc)
            ])
          ]))), 128))
        ], 8, rc),
        s.value.interfaces.length ? x("", !0) : (f(), h("p", yc, b(i.value ? "Получаем состояние сети…" : "Интерфейсы не найдены."), 1)),
        l("header", wc, [
          r[27] || (r[27] = l("div", null, [
            l("h3", null, "Статические маршруты IPv4"),
            l("p", { class: "gw-hint" }, "Автоматические маршруты создаются протоколами подключений")
          ], -1)),
          l("button", {
            disabled: a.value || i.value || !s.value.config_hash,
            onClick: ie
          }, "Настроить маршруты", 8, _c)
        ]),
        s.value.routes.length ? (f(), h("div", kc, [
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
              (f(!0), h(q, null, oe(s.value.routes, (v) => (f(), h("tr", {
                key: v.id
              }, [
                l("td", null, [
                  M(b(v.target), 1),
                  l("small", null, b(v.netmask), 1)
                ]),
                l("td", null, b(v.gateway || "Напрямую"), 1),
                l("td", null, b(v.interface), 1),
                l("td", null, b(v.metric || "0"), 1)
              ]))), 128))
            ])
          ])
        ])) : (f(), h("p", $c, "Статические маршруты не заданы."))
      ]),
      g.value ? (f(), me(ps, {
        key: 0,
        node: e.node,
        bridge: e.bridge,
        mode: g.value,
        iface: g.value === "dhcp" ? m.value : void 0,
        onClose: r[1] || (r[1] = (v) => g.value = null),
        onChanged: r[2] || (r[2] = (v) => {
          I(), o("changed");
        })
      }, null, 8, ["node", "bridge", "mode", "iface"])) : x("", !0),
      w.value ? (f(), me(Re, {
        key: 1,
        title: w.value.existing ? "Настройка " + w.value.name : "Новое подключение",
        wide: !0,
        busy: a.value,
        onClose: r[23] || (r[23] = (v) => {
          w.value = null, u.value = "";
        })
      }, {
        default: Ie(() => [
          l("form", {
            class: "gw-form gw-network-form",
            onSubmit: tt(C, ["prevent"])
          }, [
            l("div", Cc, [
              l("label", null, [
                r[29] || (r[29] = M("Имя интерфейса", -1)),
                H(l("input", {
                  "onUpdate:modelValue": r[3] || (r[3] = (v) => w.value.name = v),
                  required: "",
                  pattern: "[A-Za-z][A-Za-z0-9_]{0,30}",
                  readonly: w.value.existing,
                  placeholder: "wan, lan, wg0"
                }, null, 8, xc), [
                  [re, w.value.name]
                ])
              ]),
              l("label", null, [
                r[31] || (r[31] = M("Протокол", -1)),
                H(l("select", {
                  "onUpdate:modelValue": r[4] || (r[4] = (v) => w.value.proto = v)
                }, [...r[30] || (r[30] = [
                  l("option", { value: "dhcp" }, "DHCP-клиент", -1),
                  l("option", { value: "static" }, "Статический адрес", -1),
                  l("option", { value: "pppoe" }, "PPPoE", -1),
                  l("option", { value: "wireguard" }, "WireGuard", -1),
                  l("option", { value: "none" }, "Без протокола", -1)
                ])], 512), [
                  [xe, w.value.proto]
                ])
              ])
            ]),
            w.value.proto !== "wireguard" ? (f(), h("label", Sc, [
              r[33] || (r[33] = M("Сетевое устройство", -1)),
              H(l("select", {
                "onUpdate:modelValue": r[5] || (r[5] = (v) => w.value.device = v)
              }, [
                r[32] || (r[32] = l("option", { value: "" }, "Автоматически", -1)),
                (f(!0), h(q, null, oe(L.value, (v) => (f(), h("option", {
                  key: v,
                  value: v
                }, b(v), 9, Tc))), 128))
              ], 512), [
                [xe, w.value.device]
              ])
            ])) : x("", !0),
            w.value.proto === "static" ? (f(), h(q, { key: 1 }, [
              l("div", Vc, [
                l("label", null, [
                  r[34] || (r[34] = M("IPv4-адрес", -1)),
                  H(l("input", {
                    "onUpdate:modelValue": r[6] || (r[6] = (v) => w.value.ipaddr = v),
                    required: "",
                    placeholder: "192.168.1.2"
                  }, null, 512), [
                    [re, w.value.ipaddr]
                  ])
                ]),
                l("label", null, [
                  r[35] || (r[35] = M("Маска подсети", -1)),
                  H(l("input", {
                    "onUpdate:modelValue": r[7] || (r[7] = (v) => w.value.netmask = v),
                    required: "",
                    placeholder: "255.255.255.0"
                  }, null, 512), [
                    [re, w.value.netmask]
                  ])
                ])
              ]),
              l("label", null, [
                r[36] || (r[36] = M("IPv4-шлюз", -1)),
                H(l("input", {
                  "onUpdate:modelValue": r[8] || (r[8] = (v) => w.value.gateway = v),
                  placeholder: "192.168.1.1"
                }, null, 512), [
                  [re, w.value.gateway]
                ])
              ])
            ], 64)) : x("", !0),
            w.value.proto === "pppoe" ? (f(), h(q, { key: 2 }, [
              l("label", null, [
                r[37] || (r[37] = M("Логин PPPoE", -1)),
                H(l("input", {
                  "onUpdate:modelValue": r[9] || (r[9] = (v) => w.value.username = v),
                  required: "",
                  autocomplete: "off"
                }, null, 512), [
                  [re, w.value.username]
                ])
              ]),
              l("label", null, [
                r[38] || (r[38] = M("Пароль PPPoE", -1)),
                Ae(vt, {
                  modelValue: w.value.password,
                  "onUpdate:modelValue": r[10] || (r[10] = (v) => w.value.password = v),
                  autocomplete: "off",
                  required: !w.value.has_password,
                  placeholder: w.value.has_password ? "Пустое поле сохраняет текущий пароль" : ""
                }, null, 8, ["modelValue", "required", "placeholder"])
              ])
            ], 64)) : x("", !0),
            w.value.proto === "wireguard" ? (f(), h(q, { key: 3 }, [
              l("label", null, [
                r[39] || (r[39] = M("Приватный ключ WireGuard", -1)),
                Ae(vt, {
                  modelValue: w.value.private_key,
                  "onUpdate:modelValue": r[11] || (r[11] = (v) => w.value.private_key = v),
                  autocomplete: "off",
                  required: !w.value.has_private_key,
                  placeholder: w.value.has_private_key ? "Пустое поле сохраняет текущий ключ" : ""
                }, null, 8, ["modelValue", "required", "placeholder"])
              ]),
              l("div", Pc, [
                l("label", null, [
                  r[40] || (r[40] = M("Адреса туннеля", -1)),
                  H(l("input", {
                    "onUpdate:modelValue": r[12] || (r[12] = (v) => w.value.addresses = v),
                    required: "",
                    placeholder: "10.10.0.2/24"
                  }, null, 512), [
                    [re, w.value.addresses]
                  ])
                ]),
                l("label", null, [
                  r[41] || (r[41] = M("Порт WireGuard", -1)),
                  H(l("input", {
                    "onUpdate:modelValue": r[13] || (r[13] = (v) => w.value.listen_port = v),
                    type: "number",
                    min: "1",
                    max: "65535",
                    placeholder: "Автоматически"
                  }, null, 512), [
                    [re, w.value.listen_port]
                  ])
                ])
              ])
            ], 64)) : x("", !0),
            l("label", null, [
              r[42] || (r[42] = M("DNS-серверы", -1)),
              H(l("input", {
                "onUpdate:modelValue": r[14] || (r[14] = (v) => w.value.dns = v),
                placeholder: "1.1.1.1, 8.8.8.8"
              }, null, 512), [
                [re, w.value.dns]
              ]),
              r[43] || (r[43] = l("small", null, "Несколько адресов разделяются пробелами или запятыми", -1))
            ]),
            l("details", Uc, [
              r[49] || (r[49] = l("summary", null, "Дополнительные параметры", -1)),
              l("div", Ac, [
                l("label", null, [
                  r[44] || (r[44] = M("Метрика маршрута", -1)),
                  H(l("input", {
                    "onUpdate:modelValue": r[15] || (r[15] = (v) => w.value.metric = v),
                    type: "number",
                    min: "0",
                    placeholder: "По умолчанию"
                  }, null, 512), [
                    [re, w.value.metric]
                  ])
                ]),
                l("label", null, [
                  r[45] || (r[45] = M("MTU", -1)),
                  H(l("input", {
                    "onUpdate:modelValue": r[16] || (r[16] = (v) => w.value.mtu = v),
                    type: "number",
                    min: "576",
                    max: "65535",
                    placeholder: "По умолчанию"
                  }, null, 512), [
                    [re, w.value.mtu]
                  ])
                ])
              ]),
              l("label", Ec, [
                H(l("input", {
                  "onUpdate:modelValue": r[17] || (r[17] = (v) => w.value.auto = v),
                  type: "checkbox"
                }, null, 512), [
                  [je, w.value.auto]
                ]),
                r[46] || (r[46] = M(" Подключать при загрузке роутера", -1))
              ]),
              l("label", Ic, [
                H(l("input", {
                  "onUpdate:modelValue": r[18] || (r[18] = (v) => w.value.defaultroute = v),
                  type: "checkbox"
                }, null, 512), [
                  [je, w.value.defaultroute]
                ]),
                r[47] || (r[47] = M(" Использовать маршрут по умолчанию", -1))
              ]),
              w.value.proto === "dhcp" || w.value.proto === "pppoe" ? (f(), h("label", Mc, [
                H(l("input", {
                  "onUpdate:modelValue": r[19] || (r[19] = (v) => w.value.peerdns = v),
                  type: "checkbox"
                }, null, 512), [
                  [je, w.value.peerdns]
                ]),
                r[48] || (r[48] = M(" Получать DNS от подключения", -1))
              ])) : x("", !0)
            ]),
            w.value.proto === "wireguard" ? (f(), h("section", Oc, [
              l("header", Rc, [
                r[50] || (r[50] = l("h3", null, "Пиры WireGuard", -1)),
                l("button", {
                  type: "button",
                  onClick: r[20] || (r[20] = (v) => w.value.peers.push({ public_key: "", allowed_ips: "", endpoint_host: "", endpoint_port: "", persistent_keepalive: "", preshared_key: "", route_allowed_ips: !0 }))
                }, "Добавить пир")
              ]),
              (f(!0), h(q, null, oe(w.value.peers, (v, _) => (f(), h("article", {
                key: v.id || _,
                class: "gw-peer-form"
              }, [
                l("div", Dc, [
                  l("h4", null, "Пир " + b(Number(_) + 1), 1),
                  l("button", {
                    type: "button",
                    onClick: (J) => w.value.peers.splice(_, 1)
                  }, "Удалить пир", 8, Fc)
                ]),
                l("label", null, [
                  r[51] || (r[51] = M("Публичный ключ", -1)),
                  H(l("input", {
                    "onUpdate:modelValue": (J) => v.public_key = J,
                    required: "",
                    autocomplete: "off"
                  }, null, 8, qc), [
                    [re, v.public_key]
                  ])
                ]),
                l("div", Nc, [
                  l("label", null, [
                    r[52] || (r[52] = M("Endpoint", -1)),
                    H(l("input", {
                      "onUpdate:modelValue": (J) => v.endpoint_host = J,
                      placeholder: "vpn.example.org"
                    }, null, 8, Hc), [
                      [re, v.endpoint_host]
                    ])
                  ]),
                  l("label", null, [
                    r[53] || (r[53] = M("Порт", -1)),
                    H(l("input", {
                      "onUpdate:modelValue": (J) => v.endpoint_port = J,
                      type: "number",
                      min: "1",
                      max: "65535"
                    }, null, 8, Lc), [
                      [re, v.endpoint_port]
                    ])
                  ])
                ]),
                l("label", null, [
                  r[54] || (r[54] = M("Разрешённые сети", -1)),
                  H(l("input", {
                    "onUpdate:modelValue": (J) => v.allowed_ips = J,
                    required: "",
                    placeholder: "0.0.0.0/0, ::/0"
                  }, null, 8, jc), [
                    [re, v.allowed_ips]
                  ])
                ]),
                l("div", Wc, [
                  l("label", null, [
                    r[55] || (r[55] = M("Keepalive, секунд", -1)),
                    H(l("input", {
                      "onUpdate:modelValue": (J) => v.persistent_keepalive = J,
                      type: "number",
                      min: "0",
                      max: "65535",
                      placeholder: "25"
                    }, null, 8, Bc), [
                      [re, v.persistent_keepalive]
                    ])
                  ]),
                  l("label", null, [
                    r[56] || (r[56] = M("Общий ключ, необязательно", -1)),
                    Ae(vt, {
                      modelValue: v.preshared_key,
                      "onUpdate:modelValue": (J) => v.preshared_key = J,
                      autocomplete: "off",
                      placeholder: v.has_preshared_key ? "Пустое поле сохраняет текущий ключ" : ""
                    }, null, 8, ["modelValue", "onUpdate:modelValue", "placeholder"])
                  ])
                ]),
                l("label", Kc, [
                  H(l("input", {
                    "onUpdate:modelValue": (J) => v.route_allowed_ips = J,
                    type: "checkbox"
                  }, null, 8, Gc), [
                    [je, v.route_allowed_ips]
                  ]),
                  r[57] || (r[57] = M(" Создать маршруты для разрешённых сетей", -1))
                ])
              ]))), 128))
            ])) : x("", !0),
            r[58] || (r[58] = l("p", { class: "gw-hint" }, "Перед применением вы увидите изменения. Если панель не подтвердит доступность, роутер восстановит прежнюю сеть.", -1)),
            u.value ? (f(), h("p", zc, b(u.value), 1)) : x("", !0),
            l("div", Jc, [
              l("button", {
                class: "gw-primary",
                disabled: a.value
              }, "Проверить изменения", 8, Yc),
              l("button", {
                type: "button",
                disabled: a.value,
                onClick: r[21] || (r[21] = (v) => w.value = null)
              }, "Отмена", 8, Xc),
              w.value.existing ? (f(), h("button", {
                key: 0,
                type: "button",
                disabled: a.value,
                onClick: r[22] || (r[22] = (v) => S("delete", { interface: w.value.name }))
              }, "Удалить интерфейс", 8, Zc)) : x("", !0)
            ])
          ], 32)
        ]),
        _: 1
      }, 8, ["title", "busy"])) : x("", !0),
      A.value ? (f(), me(Re, {
        key: 2,
        title: "Статические маршруты IPv4",
        wide: !0,
        busy: a.value,
        onClose: r[25] || (r[25] = (v) => {
          A.value = !1, u.value = "";
        })
      }, {
        default: Ie(() => [
          l("form", {
            class: "gw-form",
            onSubmit: tt(ae, ["prevent"])
          }, [
            (f(!0), h(q, null, oe(V.value, (v, _) => (f(), h("article", {
              key: _,
              class: "gw-route-form"
            }, [
              l("div", Qc, [
                l("h4", null, "Маршрут " + b(Number(_) + 1), 1),
                l("button", {
                  type: "button",
                  onClick: (J) => V.value.splice(_, 1)
                }, "Удалить маршрут", 8, ef)
              ]),
              l("div", tf, [
                l("label", null, [
                  r[59] || (r[59] = M("Сеть назначения", -1)),
                  H(l("input", {
                    "onUpdate:modelValue": (J) => v.target = J,
                    required: "",
                    placeholder: "10.20.0.0/24"
                  }, null, 8, nf), [
                    [re, v.target]
                  ])
                ]),
                l("label", null, [
                  r[60] || (r[60] = M("Интерфейс", -1)),
                  H(l("select", {
                    "onUpdate:modelValue": (J) => v.interface = J
                  }, [
                    (f(!0), h(q, null, oe(s.value.interfaces, (J) => (f(), h("option", {
                      key: J.name,
                      value: J.name
                    }, b(J.name), 9, sf))), 128))
                  ], 8, lf), [
                    [xe, v.interface]
                  ])
                ])
              ]),
              l("div", of, [
                l("label", null, [
                  r[61] || (r[61] = M("Через шлюз", -1)),
                  H(l("input", {
                    "onUpdate:modelValue": (J) => v.gateway = J,
                    placeholder: "Напрямую, если пусто"
                  }, null, 8, af), [
                    [re, v.gateway]
                  ])
                ]),
                l("label", null, [
                  r[62] || (r[62] = M("Маска, если в адресе нет /префикса", -1)),
                  H(l("input", {
                    "onUpdate:modelValue": (J) => v.netmask = J,
                    placeholder: "255.255.255.0"
                  }, null, 8, rf), [
                    [re, v.netmask]
                  ])
                ])
              ]),
              l("div", uf, [
                l("label", null, [
                  r[63] || (r[63] = M("Метрика", -1)),
                  H(l("input", {
                    "onUpdate:modelValue": (J) => v.metric = J,
                    type: "number",
                    min: "0"
                  }, null, 8, df), [
                    [re, v.metric]
                  ])
                ]),
                l("label", null, [
                  r[64] || (r[64] = M("Таблица маршрутов", -1)),
                  H(l("input", {
                    "onUpdate:modelValue": (J) => v.table = J,
                    type: "number",
                    min: "0",
                    placeholder: "Основная"
                  }, null, 8, cf), [
                    [re, v.table]
                  ])
                ])
              ]),
              l("label", ff, [
                H(l("input", {
                  "onUpdate:modelValue": (J) => v.onlink = J,
                  type: "checkbox"
                }, null, 8, pf), [
                  [je, v.onlink]
                ]),
                r[65] || (r[65] = M(" Шлюз доступен напрямую", -1))
              ])
            ]))), 128)),
            l("button", {
              type: "button",
              onClick: ke
            }, "Добавить маршрут"),
            V.value.length ? x("", !0) : (f(), h("p", vf, "Статические маршруты будут отсутствовать. Автоматические маршруты сохраняются.")),
            u.value ? (f(), h("p", gf, b(u.value), 1)) : x("", !0),
            l("div", hf, [
              l("button", {
                class: "gw-primary",
                disabled: a.value
              }, "Проверить изменения", 8, mf),
              l("button", {
                type: "button",
                disabled: a.value,
                onClick: r[24] || (r[24] = (v) => A.value = !1)
              }, "Отмена", 8, bf)
            ])
          ], 32)
        ]),
        _: 1
      }, 8, ["busy"])) : x("", !0),
      c.value ? (f(), me(Re, {
        key: 3,
        title: "Проверка сетевых изменений",
        busy: a.value,
        onClose: U
      }, {
        default: Ie(() => [
          l("h3", null, b(c.value.title) + " " + b(c.value.interface), 1),
          l("ul", yf, [
            (f(!0), h(q, null, oe(c.value.summary, (v, _) => (f(), h("li", { key: _ }, b(v), 1))), 128))
          ]),
          c.value.address_changes ? (f(), h("p", wf, [
            r[66] || (r[66] = M("Адрес подключения изменится на ", -1)),
            l("strong", null, b(c.value.new_api_host), 1),
            r[67] || (r[67] = M(". Панель проверит новый адрес и сохранит его после успешного применения.", -1))
          ])) : x("", !0),
          l("p", null, "Роутер ждёт подтверждения до " + b(c.value.rollback_seconds) + " секунд. Если панель потеряет связь, прежняя конфигурация будет восстановлена автоматически.", 1),
          u.value ? (f(), h("p", _f, b(u.value), 1)) : x("", !0),
          l("div", kf, [
            l("button", {
              class: "gw-primary",
              disabled: a.value,
              onClick: z
            }, "Да, применить изменения", 8, $f),
            l("button", {
              disabled: a.value,
              onClick: U
            }, "Отмена", 8, Cf)
          ])
        ]),
        _: 1
      }, 8, ["busy"])) : x("", !0)
    ], 64));
  }
}), Sf = { class: "gw-packages" }, Tf = { class: "gw-section-header" }, Vf = { class: "gw-hint" }, Pf = ["disabled"], Uf = {
  key: 0,
  class: "gw-error",
  role: "alert"
}, Af = { class: "gw-package-filters" }, Ef = { class: "gw-segment" }, If = ["disabled"], Mf = {
  key: 1,
  class: "gw-notice"
}, Of = ["aria-busy"], Rf = { class: "gw-package-table" }, Df = { key: 0 }, Ff = {
  key: 0,
  class: "gw-status good"
}, qf = ["disabled", "onClick"], Nf = {
  key: 2,
  class: "gw-hint"
}, Hf = { class: "gw-pagination" }, Lf = { class: "gw-hint" }, jf = { class: "gw-actions" }, Wf = ["disabled"], Bf = ["disabled"], Kf = { class: "gw-plan-output" }, Gf = {
  key: 0,
  class: "gw-error",
  role: "alert"
}, zf = { class: "gw-actions" }, Jf = ["disabled"], Yf = ["disabled"], Xf = /* @__PURE__ */ Me({
  __name: "PackageManager",
  props: {
    node: {},
    bridge: {},
    initialQuery: {}
  },
  emits: ["changed"],
  setup(e, { emit: t }) {
    const n = e, o = t, s = /* @__PURE__ */ D(n.initialQuery || ""), i = /* @__PURE__ */ D(!1), a = /* @__PURE__ */ D(!1), u = /* @__PURE__ */ D(!1), c = /* @__PURE__ */ D(""), g = /* @__PURE__ */ D({ items: [], total: 0, offset: 0, has_indexes: !1 }), m = /* @__PURE__ */ D(null);
    let w, A = 0;
    const V = () => "/api/gateways/" + encodeURIComponent(n.node.id), L = (Q, I, E = "POST") => n.bridge.request(V() + Q, { method: E, headers: { "Content-Type": "application/json" }, body: JSON.stringify(I) });
    async function R(Q = 0) {
      const I = ++A;
      a.value = !0, c.value = "";
      try {
        const E = await n.bridge.request(V() + "/packages?query=" + encodeURIComponent(s.value) + "&installed=" + i.value + "&offset=" + Q);
        I === A && (g.value = E);
      } catch (E) {
        I === A && (c.value = E.message);
      } finally {
        I === A && (a.value = !1);
      }
    }
    async function ne(Q) {
      const I = await L("/router-operations", { plan_token: Q.plan_token, confirmed: !0 });
      m.value = null, n.bridge.task({
        taskId: I.task_id,
        title: Q.action === "refresh" ? "Обновление списка пакетов" : "Установка " + Q.package,
        cancellable: !1,
        onDone: async () => {
          await R(), o("changed");
        }
      });
    }
    async function X() {
      if (!u.value) {
        u.value = !0, c.value = "";
        try {
          const Q = await L("/packages/plan", { action: "refresh" });
          await ne(Q);
        } catch (Q) {
          c.value = Q.message;
        } finally {
          u.value = !1;
        }
      }
    }
    async function Z(Q) {
      if (!u.value) {
        u.value = !0, c.value = "";
        try {
          m.value = await L("/packages/plan", { action: "install", package: Q });
        } catch (I) {
          c.value = I.message;
        } finally {
          u.value = !1;
        }
      }
    }
    async function ee() {
      if (!u.value) {
        u.value = !0, c.value = "";
        try {
          await ne(m.value);
        } catch (Q) {
          c.value = Q.message;
        } finally {
          u.value = !1;
        }
      }
    }
    function j(Q) {
      i.value = Q, R();
    }
    function le() {
      const Q = m.value?.plan_token;
      m.value = null, c.value = "", Q && L("/operation-plans/" + encodeURIComponent(Q), {}, "DELETE").catch((I) => {
        c.value = I.message;
      });
    }
    return We(s, () => {
      w && clearTimeout(w), w = setTimeout(() => {
        R();
      }, 300);
    }), ot(() => {
      R();
    }), yt(() => {
      A++, w && clearTimeout(w);
    }), (Q, I) => (f(), h(q, null, [
      l("section", Sf, [
        l("header", Tf, [
          l("div", null, [
            I[6] || (I[6] = l("h3", null, "Пакетный менеджер", -1)),
            l("p", Vf, b(g.value.manager || "OpenWrt") + " · " + b(g.value.installed_count ?? "—") + " установленных пакетов", 1)
          ]),
          l("button", {
            disabled: u.value,
            onClick: X
          }, "Обновить список пакетов", 8, Pf)
        ]),
        I[8] || (I[8] = l("p", { class: "gw-hint" }, "Обновляется каталог репозиториев. Установленные пакеты и прошивка автоматически не обновляются.", -1)),
        c.value && !m.value ? (f(), h("div", Uf, b(c.value), 1)) : x("", !0),
        l("div", Af, [
          l("div", Ef, [
            l("button", {
              class: Te({ on: !i.value }),
              onClick: I[0] || (I[0] = (E) => j(!1))
            }, "Доступные", 2),
            l("button", {
              class: Te({ on: i.value }),
              onClick: I[1] || (I[1] = (E) => j(!0))
            }, "Установленные", 2)
          ]),
          l("form", {
            onSubmit: I[3] || (I[3] = tt((E) => R(), ["prevent"]))
          }, [
            H(l("input", {
              "onUpdate:modelValue": I[2] || (I[2] = (E) => s.value = E),
              type: "search",
              "aria-label": "Поиск пакетов",
              placeholder: "Название или описание пакета…",
              maxlength: "100"
            }, null, 512), [
              [re, s.value]
            ]),
            l("button", { disabled: a.value }, "Найти", 8, If)
          ], 32)
        ]),
        !g.value.has_indexes && !a.value ? (f(), h("p", Mf, "Список доступных пакетов ещё не загружен. Нажмите «Обновить список пакетов» — ход загрузки появится в журнале.")) : x("", !0),
        l("div", {
          class: "gw-table-wrap",
          "aria-busy": a.value
        }, [
          l("table", Rf, [
            I[7] || (I[7] = l("thead", null, [
              l("tr", null, [
                l("th", null, "Пакет"),
                l("th", null, "Версия"),
                l("th")
              ])
            ], -1)),
            l("tbody", null, [
              (f(!0), h(q, null, oe(g.value.items, (E) => (f(), h("tr", {
                key: E.name
              }, [
                l("td", null, [
                  l("strong", null, b(E.name), 1),
                  l("small", null, b(E.description), 1)
                ]),
                l("td", null, [
                  l("span", null, b(E.installed_version || E.version), 1),
                  E.installed_version && E.installed_version !== E.version ? (f(), h("small", Df, "В каталоге: " + b(E.version), 1)) : x("", !0)
                ]),
                l("td", null, [
                  E.installed_version ? (f(), h("span", Ff, "Установлен")) : (f(), h("button", {
                    key: 1,
                    disabled: u.value || a.value,
                    onClick: (P) => Z(E.name)
                  }, "Установить", 8, qf))
                ])
              ]))), 128))
            ])
          ])
        ], 8, Of),
        g.value.items.length ? x("", !0) : (f(), h("p", Nf, b(a.value ? "Загружаем пакеты…" : s.value ? "По вашему запросу пакеты не найдены." : "Пакетов в этом списке нет."), 1)),
        l("footer", Hf, [
          l("span", Lf, b(a.value ? "Загрузка…" : g.value.total ? g.value.offset + 1 + "–" + Math.min(g.value.offset + g.value.items.length, g.value.total) + " из " + g.value.total : "0 пакетов"), 1),
          l("div", jf, [
            l("button", {
              disabled: a.value || g.value.offset === 0,
              onClick: I[4] || (I[4] = (E) => R(Math.max(0, g.value.offset - 40)))
            }, "Назад", 8, Wf),
            l("button", {
              disabled: a.value || g.value.offset + 40 >= g.value.total,
              onClick: I[5] || (I[5] = (E) => R(g.value.offset + 40))
            }, "Далее", 8, Bf)
          ])
        ])
      ]),
      m.value ? (f(), me(Re, {
        key: 0,
        title: "Установить " + m.value.package + "?",
        busy: u.value,
        onClose: le
      }, {
        default: Ie(() => [
          I[9] || (I[9] = l("p", null, "Пакетный менеджер рассчитает и установит необходимые зависимости из настроенных репозиториев роутера.", -1)),
          l("pre", Kf, b(m.value.summary.join(`
`)), 1),
          I[10] || (I[10] = l("p", { class: "gw-hint" }, "Установочные скрипты пакетов могут менять настройки и запускать службы. Автоматическая замена уже установленных пакетов отключена.", -1)),
          c.value ? (f(), h("p", Gf, b(c.value), 1)) : x("", !0),
          l("div", zf, [
            l("button", {
              class: "gw-primary",
              disabled: u.value,
              onClick: ee
            }, "Да, установить", 8, Jf),
            l("button", {
              disabled: u.value,
              onClick: le
            }, "Отмена", 8, Yf)
          ])
        ]),
        _: 1
      }, 8, ["title", "busy"])) : x("", !0)
    ], 64));
  }
}), Zf = { class: "gw-traffic-overview" }, Qf = { class: "gw-section-header" }, ep = { class: "gw-traffic-tools" }, tp = {
  key: 0,
  value: 900
}, np = {
  key: 0,
  class: "gw-chart-note"
}, lp = { class: "gw-traffic-grid" }, sp = { class: "gw-section-header" }, op = { class: "gw-traffic-speeds" }, ip = { class: "gw-rx" }, ap = { class: "gw-tx" }, rp = ["onPointermove", "onPointerleave"], up = ["aria-label"], dp = ["y1", "y2"], cp = ["d"], fp = ["d"], pp = {
  key: 0,
  class: "gw-chart-empty"
}, vp = {
  key: 1,
  class: "gw-chart-tip"
}, gp = { class: "gw-traffic-total" }, hp = { class: "gw-hint gw-counter-note" }, mp = /* @__PURE__ */ Me({
  __name: "TrafficCharts",
  props: {
    monitor: {},
    nodeId: {},
    bridge: {}
  },
  setup(e) {
    const t = ["lan", "wan"], n = e, o = /* @__PURE__ */ D(null), s = /* @__PURE__ */ D({ lan: null, wan: null }), i = /* @__PURE__ */ D(null), a = /* @__PURE__ */ D(""), u = /* @__PURE__ */ D(!1), c = he({
      get: () => o.value ?? (u.value ? 900 : 3600),
      set: (Q) => {
        o.value = Q;
      }
    });
    let g = !0, m = 0, w;
    async function A() {
      if (!n.bridge || !n.nodeId) return;
      const Q = ++m;
      try {
        const I = await n.bridge.request("/api/gateways/" + encodeURIComponent(n.nodeId) + "/traffic?seconds=" + c.value);
        g && Q === m && Array.isArray(I.traffic_history) && (i.value = I.traffic_history, u.value = Array.isArray(I.available_periods) && I.available_periods.includes(900), a.value = "");
      } catch (I) {
        g && Q === m && (a.value = I instanceof Error ? I.message : String(I));
      }
    }
    We([c, () => n.nodeId], () => {
      s.value = { lan: null, wan: null }, i.value = null, A();
    }, { immediate: !0 }), ot(() => {
      w = setInterval(() => {
        document.hidden || A();
      }, 3e4);
    }), yt(() => {
      g = !1, m++, clearInterval(w);
    });
    const V = (Q, I = !1) => {
      if (Q == null) return "—";
      const E = ["Б", "КБ", "МБ", "ГБ", "ТБ"];
      let P = Number(Q), S = 0;
      for (; P >= 1024 && S < E.length - 1; )
        P /= 1024, S++;
      return (P < 10 ? P.toFixed(1) : Math.round(P)) + " " + E[S] + (I ? "/с" : "");
    }, L = he(() => {
      const Q = i.value ?? n.monitor.traffic_history ?? [], I = Q.at(-1)?.at || Date.now() / 1e3;
      return Q.filter((E) => E.at >= I - c.value);
    }), R = he(() => L.value.at(-1)?.at || n.monitor.checked_at || Date.now() / 1e3), ne = he(() => R.value - c.value), X = (Q) => new Date(Q * 1e3).toLocaleString("ru-RU", c.value >= 43200 ? { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" } : { hour: "2-digit", minute: "2-digit" });
    function Z(Q) {
      return Math.max(1, ...L.value.flatMap((I) => [I[Q]?.rx_bps || 0, I[Q]?.tx_bps || 0]));
    }
    function ee(Q, I) {
      let E = "", P = !1;
      const S = Z(Q);
      return L.value.forEach((C) => {
        const ie = C[Q]?.[I];
        if (typeof ie != "number") {
          P = !1;
          return;
        }
        const ke = 10 + (C.at - ne.value) / c.value * 580, ae = 132 - ie / S * 112;
        E += (P ? " L" : " M") + ke.toFixed(1) + " " + ae.toFixed(1), P = !0;
      }), E;
    }
    function j(Q, I) {
      if (!L.value.length) {
        s.value[I] = null;
        return;
      }
      const E = Q.currentTarget.getBoundingClientRect(), P = ne.value + Math.max(0, Math.min(1, (Q.clientX - E.left) / E.width)) * c.value;
      s.value[I] = L.value.reduce((S, C, ie) => Math.abs(C.at - P) < Math.abs(L.value[S].at - P) ? ie : S, 0);
    }
    function le(Q) {
      const I = s.value[Q];
      return I == null ? null : L.value[I];
    }
    return (Q, I) => (f(), h("section", Zf, [
      l("header", Qf, [
        I[6] || (I[6] = l("h3", null, "Трафик сети", -1)),
        l("div", ep, [
          I[5] || (I[5] = l("p", { class: "gw-hint" }, "Скорость и объём данных через LAN и WAN", -1)),
          H(l("select", {
            "onUpdate:modelValue": I[0] || (I[0] = (E) => c.value = E),
            "aria-label": "Период графиков"
          }, [
            u.value ? (f(), h("option", tp, "15 минут")) : x("", !0),
            I[1] || (I[1] = l("option", { value: 3600 }, "Час", -1)),
            I[2] || (I[2] = l("option", { value: 21600 }, "6 часов", -1)),
            I[3] || (I[3] = l("option", { value: 43200 }, "12 часов", -1)),
            I[4] || (I[4] = l("option", { value: 86400 }, "Сутки", -1))
          ], 512), [
            [xe, c.value]
          ])
        ])
      ]),
      a.value ? (f(), h("p", np, b(a.value), 1)) : x("", !0),
      l("div", lp, [
        (f(), h(q, null, oe(t, (E) => l("article", {
          key: E,
          class: "gw-panel gw-traffic-card"
        }, [
          l("header", sp, [
            l("h3", null, b(E.toUpperCase()), 1),
            l("span", {
              class: Te(["gw-status", e.monitor.traffic?.[E]?.up ? "good" : "warn"])
            }, b(e.monitor.traffic?.[E]?.up ? "Подключён" : "Отключён"), 3)
          ]),
          l("div", op, [
            l("span", ip, "↓ " + b(V(e.monitor.traffic?.[E]?.rx_bps, !0)), 1),
            l("span", ap, "↑ " + b(V(e.monitor.traffic?.[E]?.tx_bps, !0)), 1)
          ]),
          l("div", {
            class: "gw-traffic-plot",
            onPointermove: (P) => j(P, E),
            onPointerleave: (P) => s.value[E] = null
          }, [
            (f(), h("svg", {
              viewBox: "0 0 600 148",
              preserveAspectRatio: "none",
              role: "img",
              "aria-label": "Скорость трафика " + E.toUpperCase()
            }, [
              (f(), h(q, null, oe([20, 76, 132], (P) => l("line", {
                key: P,
                x1: "10",
                y1: P,
                x2: "590",
                y2: P,
                class: "gw-chart-grid"
              }, null, 8, dp)), 64)),
              l("path", {
                d: ee(E, "rx_bps"),
                class: "gw-chart-rx"
              }, null, 8, cp),
              l("path", {
                d: ee(E, "tx_bps"),
                class: "gw-chart-tx"
              }, null, 8, fp)
            ], 8, up)),
            L.value.length < 2 ? (f(), h("div", pp, "Накапливаем данные графика")) : x("", !0),
            le(E) ? (f(), h("div", vp, b(new Date(le(E).at * 1e3).toLocaleTimeString()) + " · ↓ " + b(V(le(E)[E]?.rx_bps, !0)) + " · ↑ " + b(V(le(E)[E]?.tx_bps, !0)), 1)) : x("", !0)
          ], 40, rp),
          l("div", gp, [
            l("div", null, [
              I[7] || (I[7] = l("span", null, "Получено", -1)),
              l("strong", null, b(V(e.monitor.traffic?.[E]?.rx_bytes)), 1)
            ]),
            l("div", null, [
              I[8] || (I[8] = l("span", null, "Передано", -1)),
              l("strong", null, b(V(e.monitor.traffic?.[E]?.tx_bytes)), 1)
            ])
          ])
        ])), 64))
      ]),
      l("p", hp, "Графики: " + b(X(ne.value)) + " — " + b(X(R.value)) + ". Объём данных — с последней загрузки / сброса счётчиков", 1)
    ]));
  }
}), bp = {
  key: 0,
  class: "active-sessions",
  "aria-label": "Активные сеансы"
}, yp = { class: "sessions-disclosure" }, wp = { class: "sessions-summary" }, _p = { class: "sessions-totals" }, kp = { class: "sessions-total" }, $p = { class: "sessions-total" }, Cp = { class: "sessions-content" }, xp = { class: "sessions-filter" }, Sp = ["value"], Tp = ["title"], Vp = { class: "sessions-horizontal" }, Pp = {
  class: "sessions-table",
  role: "table",
  "aria-label": "Активные соединения"
}, Up = ["title"], Ap = ["title"], Ep = ["title"], Ip = {
  class: "session-rx",
  role: "cell"
}, Mp = {
  class: "session-tx",
  role: "cell"
}, Op = {
  key: 0,
  class: "gw-hint",
  role: "status"
}, Bn = 32, El = 15, Qs = 4, Rp = /* @__PURE__ */ Me({
  __name: "ActiveSessions",
  props: {
    nodeId: {},
    bridge: {},
    collect: { type: Boolean }
  },
  setup(e) {
    const t = e, n = /* @__PURE__ */ D(), o = /* @__PURE__ */ D(!1), s = /* @__PURE__ */ D(!0), i = {
      warming: "Сравниваем первые замеры трафика…",
      integration: "Обновите интеграцию Bot4VPS во вкладке «Доступ».",
      accounting: "На OpenWrt выключен учёт байтов соединений.",
      unavailable: "Счётчики соединений шлюза сейчас недоступны.",
      networks: "Шлюз не сообщил адреса локальных сетей."
    }, a = /* @__PURE__ */ D(""), u = /* @__PURE__ */ D(""), c = /* @__PURE__ */ D("all"), g = /* @__PURE__ */ D(), m = /* @__PURE__ */ new Map(), w = /* @__PURE__ */ D([]), A = /* @__PURE__ */ new Map(), V = /* @__PURE__ */ D([]), L = /* @__PURE__ */ D(0), R = he(() => u.value.trim().toLocaleLowerCase("ru")), ne = he(() => w.value.filter(
      (ae) => (c.value === "all" || ae.via_fake_ip === (c.value === "fake")) && (!a.value || ae.device_ip === a.value) && (!R.value || [ae.name, ae.domain, ae.destination_ip, ae.observed_ip].some((z) => z?.toLocaleLowerCase("ru").includes(R.value)))
    )), X = he(() => Math.max(0, Math.min(
      Math.floor(L.value / Bn),
      ne.value.length - El
    ) - Qs)), Z = he(() => Math.min(ne.value.length, X.value + El + 2 * Qs + 1));
    We([a, u, c], () => {
      L.value = 0, g.value?.scrollTo(0, 0);
    });
    const ee = he(() => o.value ? "Не удалось получить сеансы. Повторяем запрос." : n.value?.status !== "ready" ? n.value ? i[n.value.status] : "Получаем счётчики шлюза…" : n.value.connections ? ne.value.length ? "" : a.value || R.value || c.value !== "all" ? "Совпадений нет." : "Соединений пока нет." : "Получаем список соединений…");
    function j(ae) {
      const z = ae.name || ae.domain || ae.destination_ip || ae.observed_ip || "—";
      return ae.domain && ae.destination_ip ? z + " (" + ae.destination_ip + ")" : z;
    }
    function le(ae) {
      return ae.device_name ? ae.device_name + " (" + ae.device_ip + ")" : ae.device_ip;
    }
    function Q(ae) {
      return ae.domain && ae.domain !== ae.name ? j(ae) + " · " + ae.domain : j(ae);
    }
    const I = new Intl.NumberFormat("ru-RU", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
    function E(ae) {
      return ae === void 0 ? "—" : ae > 0 && ae < 1e5 ? "<0,1" : I.format(ae / 1e6);
    }
    let P = !1, S, C;
    async function ie() {
      if (!P || !t.collect || C || !s.value) return;
      const ae = new AbortController();
      C = ae;
      try {
        const z = await t.bridge.request(
          `/api/gateways/${encodeURIComponent(t.nodeId)}/active-sessions?view=connections`,
          { signal: ae.signal }
        );
        if (!ae.signal.aborted) {
          n.value = z, o.value = !1;
          let U = !1;
          for (const d of z.connections || []) {
            m.set(d.id, d);
            const r = A.get(d.device_ip);
            (!r || d.device_name && d.device_name !== r.device_name) && (A.set(d.device_ip, d), U = !0);
          }
          U && (V.value = [...A.values()]), z.connections?.length && (w.value = [...m.values()]);
        }
      } catch (z) {
        ae.signal.aborted || (s.value = z?.status !== 404, n.value = void 0, o.value = !0);
      } finally {
        C === ae && (C = void 0), P && t.collect && s.value && !ae.signal.aborted && (S = setTimeout(ie, o.value || n.value?.status === "integration" ? 1e4 : 3e3));
      }
    }
    function ke() {
      clearTimeout(S), C?.abort(), C = void 0;
    }
    return ot(() => {
      P = !0, ie();
    }), yt(() => {
      P = !1, ke();
    }), We(() => t.collect, (ae) => {
      ae ? ie() : ke();
    }), (ae, z) => s.value ? (f(), h("section", bp, [
      l("details", yp, [
        l("summary", wp, [
          z[6] || (z[6] = l("span", { class: "sessions-header" }, [
            l("span", {
              class: "session-arrow",
              "aria-hidden": "true"
            }, "›"),
            l("strong", null, "Активные сеансы"),
            l("span", { class: "sessions-caption" }, "Мбит/с · обновление каждые 3 с")
          ], -1)),
          l("span", _p, [
            l("span", kp, [
              z[4] || (z[4] = M("WAN ", -1)),
              l("b", null, "↓ " + b(E(n.value?.wan?.rx_bps)) + " · ↑ " + b(E(n.value?.wan?.tx_bps)), 1)
            ]),
            l("span", $p, [
              z[5] || (z[5] = M("Устройства ", -1)),
              l("b", null, "↓ " + b(E(n.value?.total?.rx_bps)) + " · ↑ " + b(E(n.value?.total?.tx_bps)), 1)
            ])
          ])
        ]),
        l("div", Cp, [
          l("div", xp, [
            H(l("select", {
              "onUpdate:modelValue": z[0] || (z[0] = (U) => a.value = U),
              "aria-label": "Фильтр по устройству"
            }, [
              z[7] || (z[7] = l("option", { value: "" }, "Все устройства", -1)),
              (f(!0), h(q, null, oe(V.value, (U) => (f(), h("option", {
                key: U.device_ip,
                value: U.device_ip
              }, b(le(U)), 9, Sp))), 128))
            ], 512), [
              [xe, a.value]
            ]),
            H(l("input", {
              "onUpdate:modelValue": z[1] || (z[1] = (U) => u.value = U),
              type: "search",
              "aria-label": "Фильтр по назначению",
              placeholder: "Сервис, домен или IP"
            }, null, 512), [
              [re, u.value]
            ]),
            H(l("select", {
              "onUpdate:modelValue": z[2] || (z[2] = (U) => c.value = U),
              "aria-label": "Фильтр по маршруту"
            }, [...z[8] || (z[8] = [
              l("option", { value: "all" }, "Все маршруты", -1),
              l("option", { value: "direct" }, "Напрямую", -1),
              l("option", { value: "fake" }, "Через Fake-IP", -1)
            ])], 512), [
              [xe, c.value]
            ]),
            l("span", {
              class: "session-limit",
              title: n.value?.offloaded || n.value?.truncated ? "Часть трафика может отсутствовать" : "Скорости по последнему замеру"
            }, b(n.value?.offloaded || n.value?.truncated ? "Последний замер · неполный трафик" : "Скорости по последнему замеру"), 9, Tp)
          ]),
          l("div", Vp, [
            l("div", {
              ref_key: "viewport",
              ref: g,
              class: "sessions-scroll",
              tabindex: "0",
              style: jt({ "--session-row-height": Bn + "px", "--session-rows": El }),
              "aria-label": "Список активных соединений",
              onScroll: z[3] || (z[3] = (U) => L.value = g.value?.scrollTop || 0)
            }, [
              l("div", Pp, [
                z[9] || (z[9] = l("div", {
                  class: "session-grid session-labels",
                  role: "row"
                }, [
                  l("span", { role: "columnheader" }, "Устройство"),
                  l("span", { role: "columnheader" }, "Назначение"),
                  l("span", { role: "columnheader" }, "Маршрут"),
                  l("span", {
                    role: "columnheader",
                    title: "Последний замер по соединению"
                  }, "↓ Приём"),
                  l("span", {
                    role: "columnheader",
                    title: "Последний замер по соединению"
                  }, "↑ Передача")
                ], -1)),
                X.value ? (f(), h("div", {
                  key: 0,
                  "aria-hidden": "true",
                  style: jt({ height: X.value * Bn + "px" })
                }, null, 4)) : x("", !0),
                (f(!0), h(q, null, oe(ne.value.slice(X.value, Z.value), (U) => (f(), h("div", {
                  key: U.id,
                  class: "session-grid session-connection",
                  role: "row"
                }, [
                  l("span", {
                    class: "session-name",
                    role: "cell",
                    title: le(U)
                  }, b(le(U)), 9, Up),
                  l("span", {
                    role: "cell",
                    title: Q(U)
                  }, b(j(U)), 9, Ap),
                  l("span", {
                    class: "session-route",
                    role: "cell",
                    title: U.via_fake_ip ? "Адрес подменён Fake-IP" : "Обращение к реальному IP"
                  }, b(U.via_fake_ip ? "Через Fake-IP" : "Напрямую"), 9, Ep),
                  l("b", Ip, b(E(U.rx_bps)), 1),
                  l("b", Mp, b(E(U.tx_bps)), 1)
                ]))), 128)),
                Z.value < ne.value.length ? (f(), h("div", {
                  key: 1,
                  "aria-hidden": "true",
                  style: jt({ height: (ne.value.length - Z.value) * Bn + "px" })
                }, null, 4)) : x("", !0)
              ]),
              ee.value ? (f(), h("p", Op, b(ee.value), 1)) : x("", !0)
            ], 36)
          ])
        ])
      ])
    ])) : x("", !0);
  }
}), Dp = (e, t) => {
  const n = e.__vccOpts || e;
  for (const [o, s] of t)
    n[o] = s;
  return n;
}, Fp = /* @__PURE__ */ Dp(Rp, [["__scopeId", "data-v-cada2594"]]);
function He(e) {
  if (e == null || e === "" || typeof e == "boolean") return null;
  const t = Number(e);
  return Number.isFinite(t) ? t : null;
}
function vs(e, t) {
  return !Number.isInteger(e) || e < 1 ? null : t === "2g" ? e <= 14 ? e === 14 ? 2484 : 2407 + e * 5 : null : t === "6g" ? e <= 233 ? e === 2 ? 5935 : 5950 + e * 5 : null : t === "5g" && e <= 196 ? (e >= 182 ? 4e3 : 5e3) + e * 5 : null;
}
function qp(e, t) {
  const n = e?.frequencies?.length ? e.frequencies : t?.frequencies || [], o = He(t?.frequency) || He(n[0]?.mhz || n[0]?.frequency), s = t?.band || (o ? o < 3e3 ? "2g" : o >= 5925 ? "6g" : "5g" : null);
  return (e?.networks || []).map((i) => {
    let a = He(i.channel), u = He(i.frequency) || He(i.mhz);
    const c = ["2g", "5g", "6g"].includes(String(i.band)) ? String(i.band) : [2, 5, 6].includes(Number(i.band)) ? String(i.band) + "g" : s;
    if (!u && a) {
      const m = n.find((w) => {
        const A = He(w.mhz || w.frequency);
        return He(w.channel) === a && (!c || A != null && (A < 3e3 ? "2g" : A >= 5925 ? "6g" : "5g") === c);
      });
      u = He(m?.mhz || m?.frequency) || vs(a, c);
    }
    !a && u && (a = u === 2484 ? 14 : u === 5935 ? 2 : (u - (u < 3e3 ? 2407 : u >= 5955 ? 5950 : u < 5e3 ? 4e3 : 5e3)) / 5);
    let g = He(i.signal);
    return g != null && g >= 2147483648 && g <= 4294967295 && (g -= 4294967296), { ...i, ssid: String(i.ssid ?? ""), bssid: String(i.bssid ?? ""), channel: a, frequency: u, signal: g };
  }).sort((i, a) => (a.signal ?? -200) - (i.signal ?? -200));
}
function Kn(e, t) {
  return e > 1e3 ? e : vs(e, t < 3e3 ? "2g" : t >= 5925 ? "6g" : "5g") || t;
}
function Np(e) {
  const t = e.ht_operation || {}, n = String(t.secondary_channel_offset || "").toLowerCase();
  let o = n === "above" || n === "below" ? 40 : 20, s = e.frequency + (n === "above" ? 10 : n === "below" ? -10 : 0), i = !!e.ht_operation && He(t.channel_width) != null || ["above", "below"].includes(n);
  for (const a of ["vht_operation", "he_operation", "eht_operation"]) {
    const u = e[a], c = He(u?.channel_width);
    if (u && c === 20 && o === 20 && (i = !0), !u || c == null || c <= (a === "vht_operation" ? 40 : 20)) continue;
    const g = He(u.center_freq_1), m = He(u.center_freq_2);
    if (g != null) {
      if (c === 8080 && m != null)
        return [g, m].map((w) => ({ center: Kn(w, e.frequency), width: 80, known: !0 }));
      if ([40, 80, 160, 320].includes(c)) {
        if (o = c, s = Kn(g, e.frequency), i = !0, (c === 160 || c === 320) && m != null && m > 0) {
          const w = Kn(m, e.frequency);
          (c === 320 || Math.abs(w - s) === 40) && (s = w);
        }
        if (c === 80 && m != null && m !== 0) {
          const w = Kn(m, e.frequency), A = Math.abs(w - s);
          if (A === 40)
            o = 160, s = w;
          else if (A > 40) return [s, w].map((V) => ({ center: V, width: 80, known: !0 }));
        }
      }
    }
  }
  return [{ center: s, width: o, known: i }];
}
const Hp = { class: "gw-channel-charts" }, Lp = { class: "gw-spectrum-card" }, jp = { class: "gw-spectrum-plot" }, Wp = ["viewBox"], Bp = ["y1", "x2", "y2"], Kp = ["y"], Gp = ["x"], zp = { key: 1 }, Jp = ["x", "y"], Yp = ["aria-label", "onMouseenter", "onFocus"], Xp = ["x", "y", "width", "height", "fill"], Zp = ["x1", "x2"], Qp = ["opacity", "aria-label", "onMouseenter", "onFocus", "onClick", "onKeydown"], ev = ["d", "fill", "stroke", "stroke-width"], tv = ["x", "y"], nv = ["x"], lv = ["x"], sv = {
  key: 0,
  class: "gw-spectrum-empty"
}, ov = {
  class: "gw-spectrum-detail",
  role: "status",
  "aria-live": "polite"
}, iv = ["title"], av = {
  class: "gw-spectrum-key",
  "aria-label": "Легенда графика"
}, rv = { key: 0 }, uv = { key: 2 }, dv = { class: "gw-spectrum-legend" }, cv = ["aria-pressed", "onMouseenter", "onFocus", "onClick"], fv = /* @__PURE__ */ Me({
  __name: "WirelessChannels",
  props: {
    data: {},
    radio: {}
  },
  setup(e) {
    const t = e, n = /* @__PURE__ */ D(null), o = /* @__PURE__ */ D(null), s = /* @__PURE__ */ D(null), i = he(() => o.value || n.value), a = window.matchMedia("(max-width:600px)"), u = /* @__PURE__ */ D(a.matches), c = () => {
      u.value = a.matches;
    };
    ot(() => a.addEventListener("change", c)), yt(() => a.removeEventListener("change", c));
    const g = he(() => u.value ? 520 : 900), m = 48, w = he(() => g.value - 48), A = 26, V = 244, L = (z) => typeof z == "number" && Number.isFinite(z);
    function R(z) {
      let U = 0;
      for (const d of z) U = U * 31 + d.charCodeAt(0) >>> 0;
      return `hsl(${(Math.imul(U, 2654435761) >>> 0) % 360} 65% 56%)`;
    }
    const ne = he(() => (t.data.networks || []).filter((z) => L(z.frequency) && L(z.signal)).map((z, U) => ({ ...z, id: (z.bssid || U) + ":" + z.frequency, color: R(z.bssid || z.ssid || String(U)), segments: Np(z) })).sort((z, U) => z.signal - U.signal));
    We(() => t.data.networks, () => {
      n.value && !ne.value.some((z) => z.id === n.value) && (n.value = null), o.value = null, s.value = null;
    });
    const X = he(() => {
      const z = /* @__PURE__ */ new Map(), U = (d, r) => (z.has(d) || z.set(d, { frequency: d, channel: r, count: 0, busy_pct: null, noise: null }), z.get(d));
      for (const d of t.data.frequencies || []) {
        const r = He(d.mhz || d.frequency);
        r != null && U(r, d.channel);
      }
      for (const d of t.data.networks || []) L(d.frequency) && U(d.frequency, d.channel).count++;
      for (const d of t.data.survey || []) {
        const r = He(d.frequency);
        if (r == null) continue;
        const v = r < 3e3 ? "2g" : r >= 5925 ? "6g" : "5g", _ = r === 2484 ? 14 : r === 5935 ? 2 : (r - (v === "2g" ? 2407 : v === "6g" ? 5950 : r < 5e3 ? 4e3 : 5e3)) / 5;
        Object.assign(U(r, _), d, { busy_pct: He(d.busy_pct) });
      }
      return [...z.values()].sort((d, r) => d.frequency - r.frequency);
    }), Z = he(() => {
      const z = [...X.value.map((U) => U.frequency), ...ne.value.flatMap((U) => U.segments.flatMap((d) => [d.center - d.width / 2, d.center + d.width / 2]))];
      return z.length ? [Math.min(...z) - 5, Math.max(...z) + 5] : [2400, 2490];
    }), ee = (z) => m + (z - Z.value[0]) / Math.max(1, Z.value[1] - Z.value[0]) * (w.value - m), j = (z) => V - (Math.max(-100, Math.min(-20, z)) + 100) / 80 * (V - A), le = (z) => V - Math.max(0, Math.min(100, z)) / 100 * (V - A), Q = he(() => X.value.filter((z, U) => U % Math.max(1, Math.ceil(X.value.length / (u.value ? 8 : 18))) === 0)), I = he(() => X.value.some((z) => L(z.busy_pct))), E = he(() => Math.max(3, Math.min(20, (w.value - m) / Math.max(1, X.value.length) * 0.5))), P = he(() => X.value.find((z) => z.in_use)?.frequency || He(t.radio?.frequency) || vs(Number(t.radio?.runtime_channel || t.radio?.channel), t.radio?.band)), S = he(() => ne.value.find((z) => z.id === i.value));
    function C(z, U) {
      const d = ee(U.center - U.width / 2), r = ee(U.center + U.width / 2), v = j(z.signal), _ = Math.min((r - d) / 4, (w.value - m) * 5 / (Z.value[1] - Z.value[0]));
      return `M${d},${V} L${d + _},${v} L${r - _},${v} L${r},${V} Z`;
    }
    const ie = (z) => z.segments.every((U) => U.known) ? z.segments.map((U) => U.width).join("+") + " МГц" : "ширина неизвестна (контур 20 МГц)", ke = (z) => {
      n.value = n.value === z.id ? null : z.id;
    }, ae = he(() => S.value ? `${S.value.ssid || "Скрытая сеть"} · канал ${S.value.channel} · ${S.value.signal} dBm · ${ie(S.value)}` : s.value ? `Канал ${s.value.channel} · ${s.value.frequency} МГц · ${s.value.busy_pct == null ? "нет измерения занятости" : "занятость " + s.value.busy_pct + "%"}${s.value.noise == null ? "" : " · шум " + s.value.noise + " dBm"} · сетей: ${s.value.count}` : "Наведите на сеть или столбик. Нажмите на название сети, чтобы выделить её.");
    return (z, U) => (f(), h("section", Hp, [
      l("article", Lp, [
        l("header", null, [
          U[7] || (U[7] = l("h3", null, "Wi-Fi каналы и соседние сети", -1)),
          l("span", null, b(ne.value.length) + " сетей на графике", 1)
        ]),
        l("div", jp, [
          (f(), h("svg", {
            viewBox: `0 0 ${g.value} 282`,
            role: "img",
            "aria-label": "Каналы и уровень сигнала соседних Wi-Fi сетей",
            onMouseleave: U[4] || (U[4] = (d) => {
              o.value = null, s.value = null;
            })
          }, [
            (f(), h(q, null, oe([-100, -80, -60, -40, -20], (d) => l("g", { key: d }, [
              l("line", {
                x1: m,
                y1: j(d),
                x2: w.value,
                y2: j(d),
                class: "gw-spectrum-grid"
              }, null, 8, Bp),
              l("text", {
                x: "40",
                y: j(d) + 4,
                "text-anchor": "end"
              }, b(d), 9, Kp)
            ])), 64)),
            U[8] || (U[8] = l("text", {
              x: "8",
              y: "14"
            }, "dBm", -1)),
            I.value ? (f(), h("text", {
              key: 0,
              x: g.value - 8,
              y: "14",
              "text-anchor": "end"
            }, "%", 8, Gp)) : x("", !0),
            I.value ? (f(), h("g", zp, [
              (f(), h(q, null, oe([0, 25, 50, 75, 100], (d) => l("text", {
                key: d,
                x: w.value + 8,
                y: le(d) + 4
              }, b(d), 9, Jp)), 64))
            ])) : x("", !0),
            (f(!0), h(q, null, oe(X.value.filter((d) => L(d.busy_pct)), (d) => (f(), h("g", {
              key: d.frequency,
              class: "gw-spectrum-occupancy",
              tabindex: "0",
              role: "button",
              "aria-label": `Канал ${d.channel}, занятость ${d.busy_pct}%`,
              onMouseenter: (r) => {
                s.value = d, o.value = null;
              },
              onMouseleave: U[0] || (U[0] = (r) => s.value = null),
              onFocus: (r) => {
                s.value = d, o.value = null;
              },
              onBlur: U[1] || (U[1] = (r) => s.value = null)
            }, [
              l("rect", {
                x: ee(d.frequency) - E.value / 2,
                y: le(d.busy_pct),
                width: E.value,
                height: Math.max(1, V - le(d.busy_pct)),
                rx: "2",
                fill: d.busy_pct >= 70 ? "#e4b56c" : "#62c7a7",
                "fill-opacity": "0.45"
              }, null, 8, Xp)
            ], 40, Yp))), 128)),
            P.value ? (f(), h("line", {
              key: 2,
              x1: ee(P.value),
              y1: A,
              x2: ee(P.value),
              y2: V,
              class: "gw-spectrum-current"
            }, null, 8, Zp)) : x("", !0),
            (f(!0), h(q, null, oe(ne.value, (d) => (f(), h("g", {
              key: d.id,
              opacity: i.value && i.value !== d.id ? 0.2 : 1,
              class: "gw-spectrum-peer",
              tabindex: "0",
              role: "button",
              "aria-label": `${d.ssid || "Скрытая сеть"}, канал ${d.channel}, ${d.signal} dBm`,
              onMouseenter: (r) => {
                o.value = d.id, s.value = null;
              },
              onMouseleave: U[2] || (U[2] = (r) => o.value = null),
              onFocus: (r) => {
                o.value = d.id, s.value = null;
              },
              onBlur: U[3] || (U[3] = (r) => o.value = null),
              onClick: (r) => ke(d),
              onKeydown: [
                sl(tt((r) => ke(d), ["prevent"]), ["enter"]),
                sl(tt((r) => ke(d), ["prevent"]), ["space"])
              ]
            }, [
              (f(!0), h(q, null, oe(d.segments, (r, v) => (f(), h("path", {
                key: v,
                d: C(d, r),
                fill: d.color,
                "fill-opacity": "0.13",
                stroke: d.color,
                "stroke-width": i.value === d.id ? 3 : 1.5
              }, null, 8, ev))), 128)),
              l("text", {
                x: ee(d.frequency),
                y: j(d.signal) - 5,
                "text-anchor": "middle",
                style: jt({ fill: d.color }),
                class: "gw-spectrum-ssid"
              }, b((d.ssid || "Скрытая сеть").slice(0, u.value ? 12 : 20)), 13, tv)
            ], 40, Qp))), 128)),
            (f(!0), h(q, null, oe(Q.value, (d) => (f(), h("g", {
              key: d.frequency
            }, [
              l("text", {
                x: ee(d.frequency),
                y: "263",
                "text-anchor": "middle"
              }, b(d.channel), 9, nv)
            ]))), 128)),
            l("text", {
              x: w.value,
              y: "279",
              "text-anchor": "end"
            }, "Канал", 8, lv)
          ], 40, Wp)),
          ne.value.length ? x("", !0) : (f(), h("p", sv, b(e.data.networks?.length ? "Сети найдены, но драйвер не сообщил канал или уровень сигнала." : "Соседние сети не найдены"), 1))
        ]),
        l("div", ov, [
          l("span", { title: ae.value }, b(ae.value), 9, iv)
        ]),
        l("div", av, [
          U[13] || (U[13] = l("span", null, [
            l("i", { class: "gw-key-line" }),
            M("Контуры — сигнал сетей, шкала слева (dBm)")
          ], -1)),
          P.value ? (f(), h("span", rv, [...U[9] || (U[9] = [
            l("i", { class: "gw-key-current" }, null, -1),
            M("Пунктир — текущий канал", -1)
          ])])) : x("", !0),
          I.value ? (f(), h(q, { key: 1 }, [
            U[10] || (U[10] = l("span", null, [
              l("i", { class: "gw-key-busy" }),
              M("Зелёный — занятость менее 70%")
            ], -1)),
            U[11] || (U[11] = l("span", null, [
              l("i", { class: "gw-key-crowded" }),
              M("Жёлтый — занятость от 70%")
            ], -1)),
            U[12] || (U[12] = l("span", null, "Столбики — занятость эфира, шкала справа (%)", -1))
          ], 64)) : (f(), h("span", uv, "Измерения занятости от драйвера отсутствуют"))
        ]),
        l("div", dv, [
          (f(!0), h(q, null, oe(ne.value, (d) => (f(), h("button", {
            key: d.id,
            class: Te({ on: n.value === d.id }),
            "aria-pressed": n.value === d.id,
            onMouseenter: (r) => {
              o.value = d.id, s.value = null;
            },
            onMouseleave: U[5] || (U[5] = (r) => o.value = null),
            onFocus: (r) => {
              o.value = d.id, s.value = null;
            },
            onBlur: U[6] || (U[6] = (r) => o.value = null),
            onClick: (r) => ke(d)
          }, [
            l("i", {
              style: jt({ background: d.color })
            }, null, 4),
            l("span", null, b(d.ssid || "Скрытая сеть"), 1),
            l("small", null, b(d.signal) + " dBm", 1)
          ], 42, cv))), 128))
        ]),
        U[14] || (U[14] = l("p", { class: "gw-chart-note" }, "Высота контура — сила сигнала, ширина — полоса сети. Если ширина неизвестна, показан контур 20 МГц. Занятость измеряется драйвером; число сетей не заменяет это измерение.", -1))
      ])
    ]));
  }
}), pv = { class: "gw-wireless" }, vv = { class: "gw-section-header" }, gv = ["disabled"], hv = {
  key: 0,
  class: "gw-error",
  role: "alert"
}, mv = {
  key: 1,
  class: "gw-hint"
}, bv = { class: "gw-section-header" }, yv = { class: "gw-hint" }, wv = { key: 0 }, _v = { class: "gw-actions" }, kv = ["disabled", "onClick"], $v = ["disabled", "onClick"], Cv = { class: "gw-table-wrap" }, xv = { class: "gw-check" }, Sv = { class: "gw-two" }, Tv = ["value"], Vv = ["value", "disabled"], Pv = ["value"], Uv = { class: "gw-two" }, Av = ["value"], Ev = ["value"], Iv = ["value"], Mv = ["value"], Ov = { class: "gw-rule-fields" }, Rv = { class: "gw-check" }, Dv = ["onUpdate:modelValue"], Fv = ["onUpdate:modelValue"], qv = ["onUpdate:modelValue"], Nv = ["value"], Hv = ["value"], Lv = { key: 0 }, jv = {
  key: 1,
  class: "gw-hint"
}, Wv = { class: "gw-wifi-networks" }, Bv = ["onUpdate:modelValue", "value"], Kv = { class: "gw-two" }, Gv = { class: "gw-check" }, zv = ["onUpdate:modelValue"], Jv = { class: "gw-check" }, Yv = ["onUpdate:modelValue"], Xv = {
  key: 0,
  class: "gw-error",
  role: "alert"
}, Zv = { class: "gw-actions" }, Qv = ["disabled"], eg = ["disabled"], tg = { class: "gw-change-list" }, ng = { class: "gw-hint" }, lg = {
  key: 0,
  class: "gw-error",
  role: "alert"
}, sg = { class: "gw-actions" }, og = ["disabled"], ig = ["disabled"], ag = { class: "gw-section-header" }, rg = { class: "gw-hint" }, ug = ["disabled"], dg = {
  key: 0,
  class: "gw-error",
  role: "alert"
}, cg = {
  class: "gw-tabs",
  "aria-label": "Результаты сканирования"
}, fg = { class: "gw-table-wrap" }, pg = {
  key: 0,
  class: "gw-hint"
}, vg = /* @__PURE__ */ Me({
  __name: "WirelessEditor",
  props: {
    node: {},
    bridge: {}
  },
  emits: ["changed"],
  setup(e, { emit: t }) {
    const n = e, o = t, s = /* @__PURE__ */ D({ radios: [], networks: [] }), i = /* @__PURE__ */ D(!1), a = /* @__PURE__ */ D(!1), u = /* @__PURE__ */ D(""), c = /* @__PURE__ */ D(null), g = /* @__PURE__ */ D(null), m = /* @__PURE__ */ D(!1), w = /* @__PURE__ */ D(null), A = /* @__PURE__ */ D(null), V = /* @__PURE__ */ D(""), L = /* @__PURE__ */ D("channels");
    let R = !0;
    const ne = () => "/api/gateways/" + encodeURIComponent(n.node.id), X = (r, v, _ = "POST") => n.bridge.request(ne() + r, { method: _, headers: { "Content-Type": "application/json" }, body: JSON.stringify(v) }), Z = (r) => Array.isArray(r) ? r : r ? String(r).split(/\s+/) : [], ee = { none: "Без защиты", psk2: "WPA2-PSK", "psk2+ccmp": "WPA2-PSK (CCMP)", "psk-mixed": "WPA/WPA2-PSK", sae: "WPA3-SAE", "sae-mixed": "WPA2/WPA3", "sae+ccmp": "WPA3-SAE (CCMP)", "sae-mixed+ccmp": "WPA2/WPA3 (CCMP)" }, j = (r) => typeof r == "number" ? (r / 1e3).toFixed(3) + " ГГц" : "—", le = (r) => ({ "2g": "2,4 ГГц", "5g": "5 ГГц", "6g": "6 ГГц" })[r.band] || j(r.frequency), Q = he(() => qp(A.value, w.value));
    function I(r) {
      return r.encryption?.enabled ? r.encryption.wpa?.length ? "WPA " + r.encryption.wpa.join("/") : "Защищена" : "Открытая";
    }
    async function E() {
      i.value = !0, u.value = "";
      try {
        const r = await n.bridge.request(ne() + "/wireless");
        R && (s.value = r);
      } catch (r) {
        R && (u.value = r.message);
      } finally {
        R && (i.value = !1);
      }
    }
    function P(r) {
      u.value = "", c.value = {
        ...r,
        original: r,
        disabled: r.disabled === "1",
        channel: r.channel || "auto",
        country: r.country || "",
        txpower: r.txpower || "",
        htmode: r.htmode || "NOHT",
        interfaces: r.interfaces.map((v) => ({ ...v, original: v, disabled: v.disabled === "1", hidden: v.hidden === "1", isolate: v.isolate === "1", network: Z(v.network), ssid: v.ssid || "", encryption: v.encryption || "none", key: "" }))
      };
    }
    const S = (r) => {
      try {
        return new Intl.DisplayNames(["ru"], { type: "region" }).of(r) || r;
      } catch {
        return r;
      }
    }, C = (r) => {
      const v = /^(HT|VHT|HE|EHT)(\d+)$/.exec(r);
      return v ? `${v[2]} МГц · Wi-Fi ${{ HT: "4 (HT)", VHT: "5 (VHT)", HE: "6 (HE)", EHT: "7 (EHT)" }[v[1]]}` : "20 МГц · без расширений HT";
    };
    function ie() {
      c.value = null, u.value = "";
    }
    function ke(r, v, _, J = []) {
      const Pe = {};
      for (const B of _) {
        const Fe = J.includes(B) ? r[B] ? "1" : "0" : r[B] === "" ? null : r[B], qt = J.includes(B) ? v[B] === "1" ? "1" : "0" : B === "network" ? Z(v[B]) : v[B] ?? (B === "channel" ? "auto" : B === "encryption" ? "none" : B === "htmode" ? "NOHT" : null);
        JSON.stringify(Fe) !== JSON.stringify(qt) && (Pe[B] = Fe);
      }
      return Pe;
    }
    async function ae() {
      a.value = !0, u.value = "";
      try {
        const r = c.value, v = {
          config_hash: s.value.config_hash,
          radio: r.name,
          settings: ke(r, r.original, ["disabled", "channel", "country", "txpower", "htmode"], ["disabled"]),
          interfaces: r.interfaces.map((_) => {
            const J = ke(_, _.original, ["disabled", "ssid", "encryption", "hidden", "isolate", "network"], ["disabled", "hidden", "isolate"]);
            return _.key && _.encryption !== "none" && (J.key = _.key), { id: _.id, settings: J };
          }).filter((_) => Object.keys(_.settings).length)
        };
        g.value = await X("/network/plan", { action: "wireless", data: v });
        for (const _ of r.interfaces) _.key = "";
      } catch (r) {
        u.value = r.message;
      } finally {
        a.value = !1;
      }
    }
    function z() {
      const r = g.value?.plan_token;
      g.value = null, u.value = "", r && X("/operation-plans/" + encodeURIComponent(r), {}, "DELETE").catch((v) => {
        u.value = v.message;
      });
    }
    async function U() {
      a.value = !0, u.value = "";
      try {
        const r = await X("/router-operations", { plan_token: g.value.plan_token, confirmed: !0 });
        g.value = null, ie(), n.bridge.task({ taskId: r.task_id, title: "Настройка Wi-Fi", cancellable: !1, onDone: async () => {
          await E(), o("changed");
        } });
      } catch (r) {
        u.value = r.message;
      } finally {
        a.value = !1;
      }
    }
    async function d(r) {
      if (!m.value) {
        w.value?.name !== r.name && (A.value = null), w.value = r, m.value = !0, V.value = "";
        try {
          const v = await X("/wireless/" + encodeURIComponent(r.name) + "/scan", {});
          R && (A.value = v);
        } catch (v) {
          R && (V.value = v.message);
        } finally {
          R && (m.value = !1);
        }
      }
    }
    return ot(() => {
      E();
    }), yt(() => {
      R = !1, c.value = null;
    }), (r, v) => (f(), h(q, null, [
      l("section", pv, [
        l("header", vv, [
          v[9] || (v[9] = l("div", null, [
            l("h3", null, "Беспроводные сети"),
            l("p", { class: "gw-hint" }, "Радиомодули, сети Wi-Fi и обзор каналов")
          ], -1)),
          l("button", {
            disabled: i.value || a.value,
            onClick: E
          }, "Обновить", 8, gv)
        ]),
        u.value && !c.value && !g.value ? (f(), h("p", hv, b(u.value), 1)) : x("", !0),
        !s.value.radios.length && !u.value ? (f(), h("p", mv, b(i.value ? "Получаем настройки Wi-Fi…" : "На шлюзе нет настроенных радиомодулей Wi-Fi."), 1)) : x("", !0),
        (f(!0), h(q, null, oe(s.value.radios, (_) => (f(), h("section", {
          key: _.name,
          class: "gw-radio"
        }, [
          l("header", bv, [
            l("div", null, [
              l("h3", null, b(_.name) + " · " + b(le(_)), 1),
              l("p", yv, [
                M(b(_.up ? "Работает" : _.disabled === "1" ? "Выключен" : "Не активен") + " · Канал " + b(_.runtime_channel || _.channel || "Авто"), 1),
                _.htmode ? (f(), h("span", wv, " · " + b(_.htmode), 1)) : x("", !0)
              ])
            ]),
            l("div", _v, [
              l("button", {
                disabled: a.value || m.value || !_.up,
                onClick: (J) => d(_)
              }, "Просмотр каналов", 8, kv),
              l("button", {
                disabled: a.value || m.value,
                onClick: (J) => P(_)
              }, "Настроить Wi-Fi", 8, $v)
            ])
          ]),
          l("div", Cv, [
            l("table", null, [
              v[10] || (v[10] = l("thead", null, [
                l("tr", null, [
                  l("th", null, "Сеть"),
                  l("th", null, "Режим"),
                  l("th", null, "Защита"),
                  l("th", null, "Подключение"),
                  l("th", null, "Состояние")
                ])
              ], -1)),
              l("tbody", null, [
                (f(!0), h(q, null, oe(_.interfaces, (J) => (f(), h("tr", {
                  key: J.id
                }, [
                  l("td", null, [
                    l("strong", null, b(J.ssid || J.id), 1),
                    l("small", null, b(J.ifname || J.id), 1)
                  ]),
                  l("td", null, b(J.mode === "ap" ? "Точка доступа" : J.mode === "sta" ? "Клиент" : J.mode), 1),
                  l("td", null, b(ee[J.encryption || "none"] || J.encryption), 1),
                  l("td", null, b(Z(J.network).join(", ") || "Без привязки"), 1),
                  l("td", null, [
                    l("span", {
                      class: Te(["gw-status", _.up && J.disabled !== "1" ? "good" : "warn"])
                    }, b(J.disabled === "1" ? "Выключена" : _.up ? "Включена" : "Не активна"), 3)
                  ])
                ]))), 128))
              ])
            ])
          ])
        ]))), 128))
      ]),
      c.value && !g.value ? (f(), me(Re, {
        key: 0,
        title: "Настройки Wi-Fi · " + c.value.name,
        wide: !0,
        compact: !0,
        busy: a.value,
        onClose: ie
      }, {
        default: Ie(() => [
          l("form", {
            class: "gw-form",
            onSubmit: tt(ae, ["prevent"])
          }, [
            l("label", xv, [
              H(l("input", {
                "onUpdate:modelValue": v[0] || (v[0] = (_) => c.value.disabled = _),
                type: "checkbox"
              }, null, 512), [
                [je, c.value.disabled]
              ]),
              v[11] || (v[11] = M(" Выключить радиомодуль", -1))
            ]),
            l("div", Sv, [
              l("label", null, [
                v[13] || (v[13] = M("Канал", -1)),
                H(l("select", {
                  "onUpdate:modelValue": v[1] || (v[1] = (_) => c.value.channel = _)
                }, [
                  v[12] || (v[12] = l("option", { value: "auto" }, "Автоматически", -1)),
                  c.value.channel !== "auto" && !c.value.frequencies.some((_) => String(_.channel) === c.value.channel) ? (f(), h("option", {
                    key: 0,
                    value: c.value.channel
                  }, b(c.value.channel) + " (текущий)", 9, Tv)) : x("", !0),
                  (f(!0), h(q, null, oe(c.value.frequencies, (_) => (f(), h("option", {
                    key: _.channel,
                    value: String(_.channel),
                    disabled: _.restricted
                  }, b(_.channel) + " · " + b(j(_.mhz || _.frequency)) + b(_.restricted ? " · Недоступен" : ""), 9, Vv))), 128))
                ], 512), [
                  [xe, c.value.channel]
                ])
              ]),
              l("label", null, [
                v[14] || (v[14] = M("Ширина канала", -1)),
                H(l("select", {
                  "onUpdate:modelValue": v[2] || (v[2] = (_) => c.value.htmode = _)
                }, [
                  (f(!0), h(q, null, oe([.../* @__PURE__ */ new Set([c.value.original.htmode || "NOHT", ...c.value.htmodes])], (_) => (f(), h("option", {
                    key: String(_),
                    value: _
                  }, b(C(String(_))), 9, Pv))), 128))
                ], 512), [
                  [xe, c.value.htmode]
                ])
              ])
            ]),
            v[28] || (v[28] = l("p", { class: "gw-hint gw-mode-help" }, "HT — Wi-Fi 4, VHT — Wi-Fi 5, HE — Wi-Fi 6, EHT — Wi-Fi 7. Более широкая полоса может повысить скорость, но занимает больше эфира; на загруженных 2,4 ГГц обычно удобнее 20 МГц.", -1)),
            l("div", Uv, [
              l("label", null, [
                v[17] || (v[17] = M("Страна", -1)),
                H(l("select", {
                  "onUpdate:modelValue": v[3] || (v[3] = (_) => c.value.country = _),
                  "aria-label": "Страна"
                }, [
                  v[15] || (v[15] = l("option", { value: "" }, "По умолчанию", -1)),
                  v[16] || (v[16] = l("option", { value: "00" }, "00 · Всемирный регуляторный домен", -1)),
                  c.value.country && c.value.country !== "00" && !c.value.countries?.some((_) => _.code === c.value.country) ? (f(), h("option", {
                    key: 0,
                    value: c.value.country,
                    disabled: ""
                  }, b(c.value.country) + " · текущее значение", 9, Av)) : x("", !0),
                  (f(!0), h(q, null, oe(c.value.countries || [], (_) => (f(), h("option", {
                    key: _.code,
                    value: _.code
                  }, b(_.code) + " · " + b(S(_.code)), 9, Ev))), 128))
                ], 512), [
                  [xe, c.value.country]
                ])
              ]),
              l("label", null, [
                v[19] || (v[19] = M("Мощность передатчика", -1)),
                H(l("select", {
                  "onUpdate:modelValue": v[4] || (v[4] = (_) => c.value.txpower = _),
                  "aria-label": "Мощность передатчика"
                }, [
                  v[18] || (v[18] = l("option", { value: "" }, "Автоматически", -1)),
                  c.value.txpower && !c.value.txpowers?.some((_) => String(_.dbm) === String(c.value.txpower)) ? (f(), h("option", {
                    key: 0,
                    value: c.value.txpower,
                    disabled: ""
                  }, b(c.value.txpower) + " dBm · текущее значение", 9, Iv)) : x("", !0),
                  (f(!0), h(q, null, oe(c.value.txpowers || [], (_) => (f(), h("option", {
                    key: _.dbm,
                    value: String(_.dbm)
                  }, b(_.dbm) + " dBm · " + b(_.mw) + " мВт", 9, Mv))), 128))
                ], 512), [
                  [xe, c.value.txpower]
                ]),
                v[20] || (v[20] = l("small", null, "Только значения драйвера; ограничения выбранной страны применяет OpenWrt.", -1))
              ])
            ]),
            v[29] || (v[29] = l("h3", null, "Сети на радиомодуле", -1)),
            (f(!0), h(q, null, oe(c.value.interfaces, (_) => (f(), h("details", {
              key: _.id,
              class: "gw-wifi-form",
              open: ""
            }, [
              l("summary", null, b(_.ssid || _.id) + " · " + b(_.mode === "ap" ? "Точка доступа" : _.mode === "sta" ? "Клиент" : _.mode), 1),
              l("div", Ov, [
                l("label", Rv, [
                  H(l("input", {
                    "onUpdate:modelValue": (J) => _.disabled = J,
                    type: "checkbox"
                  }, null, 8, Dv), [
                    [je, _.disabled]
                  ]),
                  v[21] || (v[21] = M(" Выключить эту сеть", -1))
                ]),
                l("label", null, [
                  v[22] || (v[22] = M("Имя сети (SSID)", -1)),
                  H(l("input", {
                    "onUpdate:modelValue": (J) => _.ssid = J,
                    required: "",
                    maxlength: "32"
                  }, null, 8, Fv), [
                    [re, _.ssid]
                  ])
                ]),
                l("label", null, [
                  v[23] || (v[23] = M("Защита", -1)),
                  H(l("select", {
                    "onUpdate:modelValue": (J) => _.encryption = J
                  }, [
                    ee[_.original.encryption] ? x("", !0) : (f(), h("option", {
                      key: 0,
                      value: _.original.encryption
                    }, b(_.original.encryption) + " (текущая)", 9, Nv)),
                    (f(), h(q, null, oe(ee, (J, Pe) => l("option", {
                      key: Pe,
                      value: Pe
                    }, b(J), 9, Hv)), 64))
                  ], 8, qv), [
                    [xe, _.encryption]
                  ])
                ]),
                _.encryption !== "none" && ee[_.encryption] ? (f(), h("label", Lv, [
                  v[24] || (v[24] = M("Пароль Wi-Fi", -1)),
                  Ae(vt, {
                    modelValue: _.key,
                    "onUpdate:modelValue": (J) => _.key = J,
                    autocomplete: "new-password",
                    minlength: "8",
                    maxlength: "64",
                    required: !_.has_key,
                    placeholder: _.has_key ? "Оставьте пустым, чтобы сохранить текущий" : ""
                  }, null, 8, ["modelValue", "onUpdate:modelValue", "required", "placeholder"])
                ])) : x("", !0),
                _.encryption === "none" ? (f(), h("p", jv, "Сеть будет открытой, сохранённый пароль будет удалён.")) : x("", !0),
                l("fieldset", Wv, [
                  v[25] || (v[25] = l("legend", null, "Сетевые подключения", -1)),
                  (f(!0), h(q, null, oe(s.value.networks, (J) => (f(), h("label", {
                    key: J,
                    class: "gw-check"
                  }, [
                    H(l("input", {
                      "onUpdate:modelValue": (Pe) => _.network = Pe,
                      type: "checkbox",
                      value: J
                    }, null, 8, Bv), [
                      [je, _.network]
                    ]),
                    M(" " + b(J), 1)
                  ]))), 128))
                ]),
                l("div", Kv, [
                  l("label", Gv, [
                    H(l("input", {
                      "onUpdate:modelValue": (J) => _.hidden = J,
                      type: "checkbox"
                    }, null, 8, zv), [
                      [je, _.hidden]
                    ]),
                    v[26] || (v[26] = M(" Скрыть SSID", -1))
                  ]),
                  l("label", Jv, [
                    H(l("input", {
                      "onUpdate:modelValue": (J) => _.isolate = J,
                      type: "checkbox"
                    }, null, 8, Yv), [
                      [je, _.isolate]
                    ]),
                    v[27] || (v[27] = M(" Изолировать клиентов", -1))
                  ])
                ])
              ])
            ]))), 128)),
            v[30] || (v[30] = l("p", { class: "gw-hint" }, "Применение временно отключит беспроводных клиентов. При потере доступа панель не подтвердит изменения, и роутер восстановит прежний Wi-Fi.", -1)),
            u.value ? (f(), h("p", Xv, b(u.value), 1)) : x("", !0),
            l("div", Zv, [
              l("button", {
                class: "gw-primary",
                disabled: a.value
              }, "Проверить изменения", 8, Qv),
              l("button", {
                type: "button",
                disabled: a.value,
                onClick: ie
              }, "Отмена", 8, eg)
            ])
          ], 32)
        ]),
        _: 1
      }, 8, ["title", "busy"])) : x("", !0),
      g.value ? (f(), me(Re, {
        key: 1,
        title: "Проверка изменений Wi-Fi",
        busy: a.value,
        onClose: z
      }, {
        default: Ie(() => [
          l("ul", tg, [
            (f(!0), h(q, null, oe(g.value.summary, (_, J) => (f(), h("li", { key: J }, b(_), 1))), 128))
          ]),
          l("p", ng, "Откат при отсутствии подтверждения: " + b(g.value.rollback_seconds) + " секунд.", 1),
          u.value ? (f(), h("p", lg, b(u.value), 1)) : x("", !0),
          l("div", sg, [
            l("button", {
              class: "gw-primary",
              disabled: a.value,
              onClick: U
            }, "Да, применить", 8, og),
            l("button", {
              disabled: a.value,
              onClick: z
            }, "Назад", 8, ig)
          ])
        ]),
        _: 1
      }, 8, ["busy"])) : x("", !0),
      w.value ? (f(), me(Re, {
        key: 2,
        title: "Обзор каналов · " + w.value.name,
        wide: !0,
        busy: m.value,
        onClose: v[8] || (v[8] = (_) => w.value = null)
      }, {
        default: Ie(() => [
          l("header", ag, [
            l("p", rg, b(m.value ? "Сканируем эфир…" : A.value ? "Последнее сканирование: " + new Date(A.value.scanned_at * 1e3).toLocaleTimeString("ru-RU") : V.value ? "Сканирование не выполнено" : "Ожидание запуска сканирования"), 1),
            l("button", {
              disabled: m.value,
              onClick: v[5] || (v[5] = (_) => d(w.value))
            }, b(m.value ? "Сканирование…" : "Сканировать снова"), 9, ug)
          ]),
          v[32] || (v[32] = l("p", { class: "gw-hint" }, "Во время сканирования Wi-Fi может ненадолго замедлиться. Список показывает сети, видимые этому роутеру.", -1)),
          V.value ? (f(), h("p", dg, b(V.value), 1)) : x("", !0),
          A.value ? (f(), h(q, { key: 1 }, [
            l("nav", cg, [
              l("button", {
                class: Te({ on: L.value === "channels" }),
                onClick: v[6] || (v[6] = (_) => L.value = "channels")
              }, "Каналы", 2),
              l("button", {
                class: Te({ on: L.value === "networks" }),
                onClick: v[7] || (v[7] = (_) => L.value = "networks")
              }, "Соседние сети (" + b(Q.value.length) + ")", 3)
            ]),
            L.value === "channels" ? (f(), me(fv, {
              key: 0,
              data: { ...A.value, networks: Q.value },
              radio: w.value
            }, null, 8, ["data", "radio"])) : (f(), h(q, { key: 1 }, [
              l("div", fg, [
                l("table", null, [
                  v[31] || (v[31] = l("thead", null, [
                    l("tr", null, [
                      l("th", null, "Сеть"),
                      l("th", null, "Канал"),
                      l("th", null, "Частота"),
                      l("th", null, "Сигнал"),
                      l("th", null, "Защита")
                    ])
                  ], -1)),
                  l("tbody", null, [
                    (f(!0), h(q, null, oe(Q.value, (_) => (f(), h("tr", {
                      key: _.bssid + ":" + _.frequency
                    }, [
                      l("td", null, [
                        M(b(_.ssid || "Скрытая сеть"), 1),
                        l("small", null, b(_.bssid), 1)
                      ]),
                      l("td", null, b(_.channel), 1),
                      l("td", null, b(j(_.frequency)), 1),
                      l("td", null, b(_.signal == null ? "—" : _.signal + " dBm"), 1),
                      l("td", null, b(I(_)), 1)
                    ]))), 128))
                  ])
                ])
              ]),
              Q.value.length ? x("", !0) : (f(), h("p", pg, "Соседние сети не найдены."))
            ], 64))
          ], 64)) : x("", !0)
        ]),
        _: 1
      }, 8, ["title", "busy"])) : x("", !0)
    ], 64));
  }
}), gg = { class: "gw-package-filters" }, hg = {
  class: "gw-segment",
  role: "group",
  "aria-label": "Список DHCP-аренд"
}, mg = ["aria-pressed"], bg = ["aria-pressed"], yg = ["disabled"], wg = {
  key: 0,
  class: "gw-hint",
  role: "status"
}, _g = {
  key: 1,
  class: "gw-hint"
}, kg = {
  key: 2,
  class: "gw-hint",
  role: "status"
}, $g = {
  key: 3,
  class: "gw-hint"
}, Cg = {
  key: 4,
  class: "gw-table-wrap"
}, xg = { class: "gw-dhcp-table" }, Sg = {
  key: 0,
  scope: "col"
}, Tg = { class: "gw-dhcp-kind" }, Vg = ["disabled", "onClick"], Pg = { key: 0 }, Ug = { class: "gw-actions" }, Ag = ["disabled", "onClick"], Eg = ["disabled", "onClick"], Ig = {
  key: 5,
  class: "gw-hint"
}, Mg = {
  key: 6,
  class: "gw-hint"
}, Og = {
  key: 7,
  class: "gw-pagination gw-dhcp-pagination"
}, Rg = { class: "gw-hint" }, Dg = { class: "gw-actions" }, Fg = ["disabled"], qg = { "aria-live": "polite" }, Ng = ["disabled"], pn = 20, Hg = /* @__PURE__ */ Me({
  __name: "DhcpLeases",
  props: {
    node: {},
    bridge: {},
    busy: { type: Boolean },
    revision: {},
    onTaskDone: { type: Function }
  },
  emits: ["close"],
  setup(e, { emit: t }) {
    const n = e, o = t, s = /* @__PURE__ */ D(null), i = /* @__PURE__ */ D(!1), a = /* @__PURE__ */ D(""), u = /* @__PURE__ */ D(null), c = /* @__PURE__ */ D("issued"), g = /* @__PURE__ */ D(""), m = /* @__PURE__ */ D(1);
    let w = 0;
    const A = he(() => n.node.monitor.ok && !n.node.monitor.stale), V = he(() => A.value && !!n.node.monitor.capabilities?.controls?.available && !!s.value && !i.value && !n.busy && !a.value), L = he(() => n.node.monitor.clients || []), R = he(() => n.node.monitor.capabilities?.clients?.available ?? Array.isArray(n.node.monitor.clients)), ne = he(() => s.value?.reservations || []), X = he(() => {
      const P = c.value === "static" ? ne.value.map((C) => ({ key: C.id, name: C.name, ip: C.ip, mac: C.mac.join(", "), reservation: C, kind: "static" })) : L.value.map((C) => ({ key: C.macaddr + ":" + C.ipaddr, name: C.hostname === "*" ? "" : C.hostname, ip: C.ipaddr, mac: C.macaddr, lease: C, kind: Q(C) })), S = g.value.trim().toLowerCase();
      return P.filter((C) => [C.name, C.ip, C.mac].some((ie) => ie?.toLowerCase().includes(S)));
    }), Z = he(() => Math.max(1, Math.ceil(X.value.length / pn))), ee = he(() => X.value.slice((m.value - 1) * pn, m.value * pn));
    We([g, c], () => {
      m.value = 1;
    }), We(Z, (P) => {
      m.value = Math.min(m.value, P);
    });
    async function j() {
      const P = ++w;
      if (i.value = !1, a.value = "", !!A.value) {
        i.value = !0;
        try {
          const S = await n.bridge.request("/api/gateways/" + encodeURIComponent(n.node.id) + "/network");
          if (P !== w) return;
          s.value = Array.isArray(S.dhcp_reservations) && typeof S.settings_hash == "string" ? { hash: S.settings_hash, reservations: S.dhcp_reservations } : null;
        } catch (S) {
          P === w && (a.value = S instanceof Error ? S.message : String(S));
        } finally {
          P === w && (i.value = !1);
        }
      }
    }
    We([A, () => n.revision], () => {
      j();
    }, { immediate: !0 }), yt(() => {
      w++;
    });
    function le(P, S, C) {
      !V.value || !s.value || (u.value = { configHash: s.value.hash, mode: P, reservation: S, lease: C });
    }
    function Q(P) {
      if (!s.value || i.value || a.value) return "unknown";
      const S = P.macaddr?.toLowerCase();
      return P.ipaddr && ne.value.some((C) => C.ip === P.ipaddr && (!C.mac.length || C.mac.some((ie) => ie.toLowerCase() === S))) ? "static" : "issued";
    }
    function I(P) {
      const S = P.macaddr?.toLowerCase();
      return ne.value.some((C) => C.ip === P.ipaddr || C.mac.some((ie) => ie.toLowerCase() === S));
    }
    function E(P) {
      P ? o("close") : u.value = null;
    }
    return (P, S) => u.value ? (f(), me(ps, {
      key: 1,
      node: e.node,
      bridge: e.bridge,
      mode: "dhcp_reservation",
      "reservation-form": u.value,
      "on-task-done": e.onTaskDone,
      onClose: E
    }, null, 8, ["node", "bridge", "reservation-form", "on-task-done"])) : (f(), me(Re, {
      key: 0,
      title: "DHCP-аренды",
      wide: "",
      onClose: S[6] || (S[6] = (C) => o("close"))
    }, {
      default: Ie(() => [
        l("div", gg, [
          l("div", hg, [
            l("button", {
              type: "button",
              class: Te({ on: c.value === "issued" }),
              "aria-pressed": c.value === "issued",
              onClick: S[0] || (S[0] = (C) => c.value = "issued")
            }, "Текущие", 10, mg),
            l("button", {
              type: "button",
              class: Te({ on: c.value === "static" }),
              "aria-pressed": c.value === "static",
              onClick: S[1] || (S[1] = (C) => c.value = "static")
            }, "Статические", 10, bg)
          ]),
          H(l("input", {
            "onUpdate:modelValue": S[2] || (S[2] = (C) => g.value = C),
            type: "search",
            "aria-label": "Поиск DHCP-аренд",
            placeholder: "Имя, IP или MAC"
          }, null, 512), [
            [re, g.value]
          ]),
          l("button", {
            class: "gw-primary",
            disabled: !V.value,
            onClick: S[3] || (S[3] = (C) => le("add"))
          }, "Закрепить IPv4 вручную", 8, yg)
        ]),
        a.value ? (f(), h("p", wg, [
          M("Не удалось определить тип аренды: " + b(a.value) + " ", 1),
          l("button", { onClick: j }, "Повторить")
        ])) : A.value ? i.value ? (f(), h("p", kg, "Загрузка статических аренд…")) : s.value ? x("", !0) : (f(), h("p", $g, "Тип аренды недоступен. Обновите интеграцию Bot4VPS во вкладке «Доступ».")) : (f(), h("p", _g, "Шлюз недоступен. Показаны последние полученные данные.")),
        ee.value.length ? (f(), h("div", Cg, [
          l("table", xg, [
            l("thead", null, [
              l("tr", null, [
                S[7] || (S[7] = l("th", { scope: "col" }, "Устройство", -1)),
                S[8] || (S[8] = l("th", { scope: "col" }, "IPv4-адрес", -1)),
                S[9] || (S[9] = l("th", { scope: "col" }, "MAC-адрес", -1)),
                S[10] || (S[10] = l("th", { scope: "col" }, "Тип аренды", -1)),
                c.value === "static" ? (f(), h("th", Sg, "Действия")) : x("", !0)
              ])
            ]),
            l("tbody", null, [
              (f(!0), h(q, null, oe(ee.value, (C) => (f(), h("tr", {
                key: C.key
              }, [
                l("td", null, b(C.name || "Без имени"), 1),
                l("td", null, b(C.ip || "—"), 1),
                l("td", null, b(C.mac || "—"), 1),
                l("td", Tg, [
                  l("div", {
                    class: Te(["gw-dhcp-kind-body", { "is-static": C.kind === "static" }])
                  }, [
                    l("span", {
                      class: Te(["gw-dhcp-marker", C.kind])
                    }, b(C.kind === "static" ? "Статическая" : C.kind === "issued" ? "Аренда" : "—"), 3),
                    "lease" in C && C.kind === "issued" && C.lease.macaddr && C.lease.ipaddr && !I(C.lease) ? (f(), h("button", {
                      key: 0,
                      disabled: !V.value,
                      onClick: (ie) => le("add", void 0, C.lease)
                    }, "Закрепить IP", 8, Vg)) : x("", !0)
                  ], 2)
                ]),
                "reservation" in C ? (f(), h("td", Pg, [
                  l("div", Ug, [
                    l("button", {
                      disabled: !V.value,
                      onClick: (ie) => le("edit", C.reservation)
                    }, "Изменить", 8, Ag),
                    l("button", {
                      class: "gw-danger",
                      disabled: !V.value,
                      onClick: (ie) => le("delete", C.reservation)
                    }, "Удалить", 8, Eg)
                  ])
                ])) : x("", !0)
              ]))), 128))
            ])
          ])
        ])) : c.value === "issued" && !R.value ? (f(), h("p", Ig, "Данные о выданных IPv4-адресах недоступны.")) : c.value === "issued" || s.value ? (f(), h("p", Mg, b(g.value.trim() ? "Аренды не найдены" : c.value === "issued" ? "Нет выданных IPv4-адресов" : "Нет статических IPv4-аренд"), 1)) : x("", !0),
        Z.value > 1 ? (f(), h("footer", Og, [
          l("span", Rg, b((m.value - 1) * pn + 1) + "–" + b(Math.min(m.value * pn, X.value.length)) + " из " + b(X.value.length), 1),
          l("div", Dg, [
            l("button", {
              disabled: m.value === 1,
              onClick: S[4] || (S[4] = (C) => m.value--)
            }, "Назад", 8, Fg),
            l("span", qg, b(m.value) + " / " + b(Z.value), 1),
            l("button", {
              disabled: m.value === Z.value,
              onClick: S[5] || (S[5] = (C) => m.value++)
            }, "Далее", 8, Ng)
          ])
        ])) : x("", !0)
      ]),
      _: 1
    }));
  }
}), Lg = { class: "gw-section-header" }, jg = { class: "gw-actions" }, Wg = ["disabled"], Bg = ["disabled"], Kg = {
  class: "gw-hint",
  "aria-live": "polite"
}, Gg = {
  key: 0,
  class: "gw-hint",
  role: "status"
}, zg = { class: "gw-service-list" }, Jg = {
  key: 0,
  class: "gw-service-row"
}, Yg = { class: "gw-service-info" }, Xg = { key: 1 }, Zg = ["title"], Qg = ["title"], eh = {
  key: 0,
  class: "gw-next-version"
}, th = { class: "gw-service-state" }, nh = { class: "gw-service-actions" }, lh = ["disabled", "onClick"], sh = ["disabled", "onClick"], oh = ["disabled", "title", "onClick"], ih = ["disabled", "onClick"], ah = ["disabled", "onClick"], rh = ["disabled", "onClick"], uh = ["disabled", "onClick"], dh = {
  key: 1,
  class: "gw-service-row gw-service-row-dhcp"
}, ch = { class: "gw-service-actions" }, fh = ["disabled"], ph = { class: "gw-version-field" }, vh = ["disabled"], gh = {
  key: 0,
  class: "gw-error",
  role: "alert"
}, hh = { class: "gw-actions" }, mh = ["disabled"], bh = ["disabled"], yh = /* @__PURE__ */ Me({
  __name: "GatewayServices",
  props: {
    node: {},
    bridge: {},
    busy: { type: Boolean },
    revision: {},
    updating: {}
  },
  emits: ["changed", "catalog", "firewallRestart", "settings", "help", "openAdguard", "action", "update", "pending", "resume", "webAccess"],
  setup(e, { emit: t }) {
    const n = e, o = t, s = /* @__PURE__ */ D({}), i = /* @__PURE__ */ D(!1), a = /* @__PURE__ */ D(""), u = /* @__PURE__ */ D(null), c = he(() => {
      const P = [...n.node.monitor.services || []], S = P.findIndex((ie) => ie?.id === "firewall"), C = P.findIndex((ie) => ie?.id === "dnsmasq");
      return P.splice((S < 0 ? C : S) + 1, 0, null), P;
    }), g = /* @__PURE__ */ D(!1), m = /* @__PURE__ */ D(0);
    function w() {
      m.value++, o("changed");
    }
    const A = { dnsmasq: "Локальный DNS и DHCP", firewall: "Защита роутера и правила трафика", podkop: "Выборочная маршрутизация через sing-box", ssclash: "Clash / Mihomo и правила маршрутизации", adguardhome: "Фильтрация DNS и блокировка рекламы" }, V = /* @__PURE__ */ D(null), L = /* @__PURE__ */ D(!1), R = /* @__PURE__ */ D("");
    function ne(P) {
      const S = s.value[P.id]?.fingerprint;
      S && (R.value = "", V.value = { id: P.id, name: P.name, fingerprint: S, version: "" });
    }
    async function X() {
      const P = V.value, S = n.node.id;
      if (!(!P || L.value)) {
        L.value = !0, R.value = "";
        try {
          await n.bridge.request("/api/gateways/" + encodeURIComponent(S) + "/services/" + P.id + "/version", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ version: P.version, fingerprint: P.fingerprint, confirmed: !0 }) }), V.value = null, await E();
        } catch (C) {
          R.value = C instanceof Error ? C.message : String(C);
        } finally {
          L.value = !1;
        }
      }
    }
    let Z = 0;
    yt(() => {
      Z++;
    });
    function ee(P) {
      return n.updating?.[P] || (s.value[P]?.stage ? { stage: s.value[P].stage, task_id: s.value[P]?.task_id || void 0 } : void 0);
    }
    function j(P) {
      return ee(P)?.stage === "prepare" ? "Подготовка…" : ee(P)?.stage === "apply" ? "Обновление…" : ee(P)?.stage === "review" ? s.value[P]?.plan ? "Продолжить обновление" : "Ожидает подтверждения" : "Обновить до " + s.value[P]?.latest;
    }
    function le(P) {
      return n.busy || i.value || !!a.value || !!ee(P) && !(ee(P)?.stage === "review" && s.value[P]?.plan);
    }
    function Q(P) {
      const S = s.value[P]?.plan;
      ee(P)?.stage === "review" && S ? o("resume", S) : o("update", P);
    }
    function I(P) {
      if (["dnsmasq", "firewall"].includes(P)) return "";
      if (i.value) return "Проверяю обновления…";
      if (a.value) return "Не удалось проверить обновления";
      const S = s.value[P];
      return S?.available ? "Есть обновление до " + S.latest : S?.status === "current_cached" ? "Актуальная среди сохранённых версий" : S?.warning ? "Проверка не завершена" : S?.status === "newer" ? "Установленная версия новее доступного релиза" : S?.current && S.latest ? "Актуальная версия" : "Обновления не проверены";
    }
    async function E(P = !1) {
      const S = ++Z;
      P || (i.value = !0), a.value = "";
      try {
        const C = await n.bridge.request("/api/gateways/" + encodeURIComponent(n.node.id) + "/service-updates");
        if (S === Z) {
          s.value = C.services || {}, u.value = C.checked_at || Math.floor(Date.now() / 1e3);
          for (const [ie, ke] of Object.entries(s.value)) ke.task_id && ke.stage && o("pending", ie, { stage: ke.stage, task_id: ke.task_id });
        }
      } catch (C) {
        S === Z && (a.value = C instanceof Error ? C.message : String(C));
      } finally {
        S === Z && (i.value = !1);
      }
    }
    return We(() => n.revision, () => {
      E(!0);
    }), We(() => n.node.id, () => {
      s.value = {}, u.value = null, V.value = null, E();
    }, { immediate: !0 }), (P, S) => (f(), h(q, null, [
      l("header", Lg, [
        S[8] || (S[8] = l("div", null, [
          l("h3", null, "Сервисы из GitHub"),
          l("p", { class: "gw-hint" }, "Podkop, SSClash-Go и AdGuard Home · версии и резервные комплекты")
        ], -1)),
        l("div", jg, [
          l("button", {
            disabled: e.busy || i.value,
            onClick: S[0] || (S[0] = (C) => E())
          }, b(i.value ? "Проверяю…" : "Проверить обновления"), 9, Wg),
          l("button", {
            class: "gw-primary",
            disabled: e.busy,
            onClick: S[1] || (S[1] = (C) => o("catalog"))
          }, "Установить сервис", 8, Bg)
        ])
      ]),
      l("p", Kg, b(i.value ? "Проверяю установленные версии и совместимые официальные релизы…" : a.value ? "Проверка не завершена." : u.value ? "Проверено в " + new Date(u.value * 1e3).toLocaleTimeString("ru-RU") : "Версии ещё не проверены."), 1),
      a.value ? (f(), h("p", Gg, b(a.value), 1)) : x("", !0),
      S[12] || (S[12] = l("div", {
        class: "gw-service-columns",
        "aria-hidden": "true"
      }, [
        l("span", null, "Сервис"),
        l("span", null, "Версия"),
        l("span", null, "Статус"),
        l("span", null, "Действия")
      ], -1)),
      l("div", zg, [
        (f(!0), h(q, null, oe(c.value, (C) => (f(), h(q, {
          key: C?.id || "dhcp-leases"
        }, [
          C ? (f(), h("article", Jg, [
            l("div", Yg, [
              l("h3", null, b(C.id === "dnsmasq" ? "DNSMasq" : C.id === "firewall" ? "Firewall" : C.name), 1),
              ["podkop", "ssclash", "adguardhome"].includes(C.id) ? (f(), me(fs, {
                key: 0,
                id: C.id,
                compact: "",
                help: C.id === "adguardhome",
                onHelp: S[2] || (S[2] = (ie) => o("help"))
              }, null, 8, ["id", "help"])) : (f(), h("p", Xg, b(A[C.id]), 1)),
              s.value[C.id]?.warning ? (f(), h("p", {
                key: 2,
                class: "gw-hint gw-version-warning",
                role: "status",
                title: s.value[C.id]?.warning || void 0
              }, b(s.value[C.id]?.warning), 9, Zg)) : x("", !0)
            ]),
            l("div", {
              class: "gw-service-versions",
              title: (s.value[C.id]?.installed_version || s.value[C.id]?.current || C.version || "—") + (s.value[C.id]?.available ? " → " + s.value[C.id]?.latest : "")
            }, [
              l("span", null, b(s.value[C.id]?.installed_version || s.value[C.id]?.current || C.version || "—"), 1),
              s.value[C.id]?.available ? (f(), h("span", eh, "→ " + b(s.value[C.id]?.latest), 1)) : x("", !0)
            ], 8, Qg),
            l("div", th, [
              l("span", {
                class: Te(["gw-status", C.running ? "good" : "warn"])
              }, b(C.running ? "Работает" : "Остановлена"), 3),
              I(C.id) ? (f(), h("span", {
                key: 0,
                class: Te(["gw-status", i.value || a.value || s.value[C.id]?.warning || s.value[C.id]?.available ? "warn" : "good"])
              }, b(I(C.id)), 3)) : x("", !0)
            ]),
            l("div", nh, [
              ["ssclash", "adguardhome"].includes(C.id) && !s.value[C.id]?.current && s.value[C.id]?.fingerprint ? (f(), h("button", {
                key: 0,
                disabled: e.busy || i.value || L.value,
                onClick: (ie) => ne(C)
              }, "Указать установленную версию", 8, lh)) : x("", !0),
              l("button", {
                disabled: e.busy,
                onClick: (ie) => C.id === "adguardhome" ? o("openAdguard") : o("settings", C)
              }, b(C.id === "adguardhome" ? "Открыть AdGuard Home" : "Настроить" + (["podkop", "ssclash"].includes(C.id) ? " ↗" : "")), 9, sh),
              e.node.monitor.capabilities?.controls?.available ? (f(), h(q, { key: 1 }, [
                s.value[C.id]?.available || ee(C.id) ? (f(), h("button", {
                  key: 0,
                  class: "gw-update-button",
                  disabled: le(C.id),
                  title: "Обновить до " + s.value[C.id]?.latest,
                  onClick: (ie) => Q(C.id)
                }, b(j(C.id)), 9, oh)) : x("", !0),
                C.id === "ssclash" && C.managed ? (f(), h("button", {
                  key: 1,
                  disabled: e.busy || !!ee(C.id),
                  onClick: (ie) => o("webAccess", C.web_scope === "wan" ? "lan" : "wan")
                }, b(C.web_scope === "wan" ? "Только LAN" : "Доступ из WAN"), 9, ih)) : x("", !0),
                C.running || C.id === "firewall" ? (f(), h("button", {
                  key: 2,
                  disabled: e.busy || !!ee(C.id),
                  onClick: (ie) => C.id === "firewall" ? o("firewallRestart") : o("action", C.id, "restart")
                }, "Перезапустить", 8, ah)) : x("", !0),
                ["dnsmasq", "firewall"].includes(C.id) ? x("", !0) : (f(), h("button", {
                  key: 3,
                  disabled: e.busy || !!ee(C.id),
                  onClick: (ie) => o("action", C.id, C.running ? "stop" : "start")
                }, b(C.running ? "Остановить" : "Запустить"), 9, rh)),
                ["podkop", "ssclash"].includes(C.id) || C.id === "adguardhome" && C.managed ? (f(), h("button", {
                  key: 4,
                  class: "gw-danger",
                  disabled: e.busy || !!ee(C.id),
                  onClick: (ie) => o("action", C.id, "remove")
                }, "Удалить", 8, uh)) : x("", !0)
              ], 64)) : x("", !0)
            ])
          ])) : (f(), h("article", dh, [
            S[9] || (S[9] = l("div", { class: "gw-service-info" }, [
              l("h3", null, "DHCP-аренды")
            ], -1)),
            l("div", ch, [
              l("button", {
                disabled: e.busy,
                "aria-label": "Открыть DHCP-аренды",
                "aria-haspopup": "dialog",
                onClick: S[3] || (S[3] = (ie) => g.value = !0)
              }, "Открыть", 8, fh)
            ])
          ]))
        ], 64))), 128))
      ]),
      g.value ? (f(), me(Hg, {
        key: 1,
        node: e.node,
        bridge: e.bridge,
        busy: e.busy,
        revision: m.value,
        "on-task-done": w,
        onClose: S[4] || (S[4] = (C) => g.value = !1)
      }, null, 8, ["node", "bridge", "busy", "revision"])) : x("", !0),
      V.value ? (f(), me(Re, {
        key: 2,
        title: "Установленная версия · " + V.value.name,
        onClose: S[7] || (S[7] = (C) => !L.value && (V.value = null))
      }, {
        default: Ie(() => [
          S[11] || (S[11] = l("p", { class: "gw-hint" }, "Укажите версию, которая сейчас показана в интерфейсе сервиса. Сохраняется только запись о версии; сервис и настройки не меняются.", -1)),
          l("label", ph, [
            S[10] || (S[10] = M("Установленная версия", -1)),
            H(l("input", {
              "onUpdate:modelValue": S[5] || (S[5] = (C) => V.value.version = C),
              placeholder: "Например, 7.7.4",
              inputmode: "decimal",
              disabled: L.value
            }, null, 8, vh), [
              [
                re,
                V.value.version,
                void 0,
                { trim: !0 }
              ]
            ])
          ]),
          R.value ? (f(), h("p", gh, b(R.value), 1)) : x("", !0),
          l("div", hh, [
            l("button", {
              class: "gw-primary",
              disabled: L.value || !/^v?[0-9]+[.][0-9]+[.][0-9]+$/.test(V.value.version),
              onClick: X
            }, b(L.value ? "Сохраняю…" : "Подтвердить версию"), 9, mh),
            l("button", {
              disabled: L.value,
              onClick: S[6] || (S[6] = (C) => V.value = null)
            }, "Отмена", 8, bh)
          ])
        ]),
        _: 1
      }, 8, ["title"])) : x("", !0)
    ], 64));
  }
}), wh = { class: "gw-header" }, _h = { class: "gw-eyebrow" }, kh = { class: "gw-title-with-icon" }, $h = { class: "gw-actions" }, Ch = ["disabled"], xh = ["href"], Sh = /* @__PURE__ */ Me({
  __name: "GatewayHeader",
  props: {
    node: {},
    busy: { type: Boolean }
  },
  emits: ["console"],
  setup(e, { emit: t }) {
    const n = t;
    return (o, s) => (f(), h("header", wh, [
      l("div", null, [
        l("span", _h, "OPENWRT " + b(e.node.monitor.board?.release?.version), 1),
        l("h2", kh, [
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
          M(b(e.node.name), 1)
        ]),
        l("p", null, b(e.node.monitor.board?.model || e.node.host) + " · " + b(e.node.host), 1)
      ]),
      l("div", $h, [
        l("button", {
          "aria-label": "Открыть консоль шлюза",
          disabled: e.busy,
          onClick: s[0] || (s[0] = (i) => n("console"))
        }, "Консоль", 8, Ch),
        l("a", {
          href: e.node.luci_url,
          target: "_blank",
          rel: "noopener noreferrer"
        }, "LuCI ↗", 8, xh)
      ])
    ]));
  }
}), Th = { class: "gw-backups" }, Vh = { class: "gw-section-header" }, Ph = ["disabled"], Uh = {
  key: 0,
  class: "gw-notice"
}, Ah = {
  key: 1,
  class: "gw-error",
  role: "alert"
}, Eh = {
  key: 2,
  class: "gw-notice"
}, Ih = { class: "gw-backup-restore" }, Mh = { class: "gw-section-header" }, Oh = { class: "gw-backup-upload" }, Rh = ["disabled"], Dh = ["disabled"], Fh = { class: "gw-backup-picker" }, qh = ["disabled"], Nh = {
  key: 0,
  value: ""
}, Hh = ["value"], Lh = ["disabled"], jh = {
  key: 3,
  class: "gw-notice gw-backup-reboot"
}, Wh = { class: "gw-actions" }, Bh = ["disabled"], Kh = ["href"], Gh = ["href"], zh = {
  key: 0,
  class: "gw-error",
  role: "alert"
}, Jh = { key: 1 }, Yh = { class: "gw-change-list" }, Xh = { class: "gw-actions" }, Zh = ["disabled"], Qh = ["disabled"], em = /* @__PURE__ */ Me({
  __name: "GatewayBackups",
  props: {
    node: {},
    bridge: {}
  },
  setup(e) {
    const t = e, n = /* @__PURE__ */ D([]), o = /* @__PURE__ */ D(""), s = /* @__PURE__ */ D(!1), i = /* @__PURE__ */ D(!1), a = /* @__PURE__ */ D(""), u = /* @__PURE__ */ D(null), c = /* @__PURE__ */ D(null), g = /* @__PURE__ */ D(!1), m = /* @__PURE__ */ D(null);
    let w = !0, A;
    const V = "/api/gateways/" + encodeURIComponent(t.node.id) + "/backups", L = (E, P) => t.bridge.request(E, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(P) }), R = (E) => E < 1024 * 1024 ? Math.round(E / 1024) + " КБ" : (E / 1024 / 1024).toFixed(1) + " МБ";
    function ne() {
      m.value?.click();
    }
    async function X() {
      try {
        const E = await t.bridge.request(V);
        if (!w) return;
        n.value = E.items, i.value = E.available, u.value = E.task?.id || null, g.value = E.reboot_required === !0, n.value.some((P) => P.id === o.value) || (o.value = n.value[0]?.id || ""), u.value && (A = setTimeout(X, 2e3));
      } catch (E) {
        w && (a.value = E instanceof Error ? E.message : String(E));
      }
    }
    function Z(E, P, S) {
      u.value = E, t.bridge.task({ taskId: E, title: P, cancellable: !1, onDone: async () => {
        if (w) {
          try {
            const C = await t.bridge.request("/api/tasks/" + encodeURIComponent(E));
            C.result?.success === !1 && (a.value = C.result.error || "Операция завершилась с ошибкой");
          } catch (C) {
            a.value = C instanceof Error ? C.message : String(C);
          }
          clearTimeout(A), await X();
        }
      } }), clearTimeout(A), A = setTimeout(X, 2e3);
    }
    async function ee() {
      s.value = !0, a.value = "";
      try {
        const E = await L(V + "/create", {});
        w && Z(E.task_id, "Резервная копия настроек OpenWrt", "create");
      } catch (E) {
        a.value = E instanceof Error ? E.message : String(E);
      } finally {
        s.value = !1;
      }
    }
    async function j(E) {
      const P = E.target, S = P.files?.[0];
      if (S) {
        s.value = !0, a.value = "";
        try {
          const C = new FormData();
          C.append("file", S);
          const ie = await t.bridge.request(V + "/upload", { method: "POST", body: C });
          if (!w) return;
          await X(), o.value = ie.archive.id;
        } catch (C) {
          a.value = C instanceof Error ? C.message : String(C);
        } finally {
          P.value = "", s.value = !1;
        }
      }
    }
    async function le(E) {
      s.value = !0, a.value = "";
      try {
        const P = await L(V + "/plan", { action: E, archive_id: E === "restore" ? o.value : null });
        w ? c.value = P : t.bridge.request(V + "/plans/" + encodeURIComponent(P.plan_token), { method: "DELETE" }).catch(() => {
        });
      } catch (P) {
        a.value = P instanceof Error ? P.message : String(P);
      } finally {
        s.value = !1;
      }
    }
    async function Q() {
      if (c.value) {
        s.value = !0;
        try {
          await t.bridge.request(V + "/plans/" + encodeURIComponent(c.value.plan_token), { method: "DELETE" }), c.value = null;
        } catch (E) {
          a.value = E instanceof Error ? E.message : String(E);
        } finally {
          s.value = !1;
        }
      }
    }
    async function I() {
      if (!c.value) return;
      s.value = !0, a.value = "";
      const E = c.value;
      try {
        const P = await L(V + "/apply", { plan_token: E.plan_token, confirmed: !0 });
        w && (c.value = null, Z(P.task_id, E.action === "restore" ? "Восстановление настроек OpenWrt" : "Перезагрузка шлюза", E.action));
      } catch (P) {
        a.value = P instanceof Error ? P.message : String(P);
      } finally {
        s.value = !1;
      }
    }
    return ot(X), Do(() => {
      w = !1, clearTimeout(A), c.value && t.bridge.request(V + "/plans/" + encodeURIComponent(c.value.plan_token), { method: "DELETE" }).catch(() => {
      });
    }), (E, P) => (f(), h(q, null, [
      l("section", Th, [
        l("header", Vh, [
          P[4] || (P[4] = l("div", null, [
            l("h3", null, "Резервные копии"),
            l("p", { class: "gw-hint" }, "Штатный архив настроек OpenWrt. Прошивка и пакеты в копию не входят.")
          ], -1)),
          l("button", {
            class: "gw-primary",
            disabled: s.value || !!u.value || !i.value,
            onClick: ee
          }, "Создать копию на панели", 8, Ph)
        ]),
        i.value ? x("", !0) : (f(), h("p", Uh, "Для создания и восстановления нужен управляемый API Bot4VPS. Настройте его во вкладке «Доступ».")),
        a.value && !c.value ? (f(), h("p", Ah, b(a.value), 1)) : x("", !0),
        u.value ? (f(), h("p", Eh, [
          P[5] || (P[5] = M("Выполняется операция шлюза. ", -1)),
          l("button", {
            onClick: P[0] || (P[0] = (S) => Z(u.value, "Операция резервного копирования"))
          }, "Показать задачу")
        ])) : x("", !0),
        l("div", Ih, [
          l("header", Mh, [
            P[6] || (P[6] = l("div", null, [
              l("h3", null, "Восстановление"),
              l("p", { class: "gw-hint" }, "Выберите любую копию на панели или загрузите свой архив из LuCI.")
            ], -1)),
            l("div", Oh, [
              l("button", {
                disabled: s.value || !!u.value,
                onClick: ne
              }, "Загрузить свой архив", 8, Rh),
              l("input", {
                ref_key: "uploadInput",
                ref: m,
                type: "file",
                accept: ".tar.gz,.tgz",
                hidden: "",
                disabled: s.value || !!u.value,
                onChange: j
              }, null, 40, Dh)
            ])
          ]),
          l("div", Fh, [
            l("label", null, [
              P[7] || (P[7] = M("Архив на панели", -1)),
              H(l("select", {
                "onUpdate:modelValue": P[1] || (P[1] = (S) => o.value = S),
                disabled: s.value || !!u.value
              }, [
                n.value.length ? x("", !0) : (f(), h("option", Nh, "Сохранённых копий пока нет")),
                (f(!0), h(q, null, oe(n.value, (S) => (f(), h("option", {
                  key: S.id,
                  value: S.id
                }, b(S.filename) + " · " + b(R(S.size)), 9, Hh))), 128))
              ], 8, qh), [
                [xe, o.value]
              ])
            ]),
            l("button", {
              disabled: s.value || !!u.value || !o.value || !i.value,
              onClick: P[2] || (P[2] = (S) => le("restore"))
            }, "Восстановить", 8, Lh)
          ]),
          P[8] || (P[8] = l("p", { class: "gw-hint" }, "Копии общие для всех шлюзов. Архив содержит настройки и может содержать пароли и ключи. Скачать или удалить копии можно в «Файлы → Копии шлюзов».", -1))
        ]),
        g.value ? (f(), h("div", jh, [
          P[9] || (P[9] = l("p", null, "Файлы настроек восстановлены. Для применения требуется перезагрузка.", -1)),
          l("div", Wh, [
            l("button", {
              disabled: s.value || !!u.value,
              onClick: P[3] || (P[3] = (S) => le("reboot"))
            }, "Перезагрузить и применить", 8, Bh),
            l("a", {
              href: e.node.luci_url,
              target: "_blank",
              rel: "noopener noreferrer"
            }, "Открыть LuCI ↗", 8, Kh)
          ])
        ])) : (f(), h("a", {
          key: 4,
          class: "gw-hint",
          href: e.node.luci_url,
          target: "_blank",
          rel: "noopener noreferrer"
        }, "Открыть LuCI ↗", 8, Gh))
      ]),
      c.value ? (f(), me(Re, {
        key: 0,
        title: c.value.action === "restore" ? "План восстановления" : "Подтверждение перезагрузки",
        busy: s.value,
        onClose: Q
      }, {
        default: Ie(() => [
          a.value ? (f(), h("p", zh, b(a.value), 1)) : x("", !0),
          c.value.action === "restore" ? (f(), h("p", Jh, [
            l("strong", null, b(c.value.filename), 1),
            M(" · " + b(c.value.files) + " файлов", 1)
          ])) : x("", !0),
          l("ul", Yh, [
            (f(!0), h(q, null, oe(c.value.warnings, (S) => (f(), h("li", { key: S }, b(S), 1))), 128))
          ]),
          l("div", Xh, [
            l("button", {
              class: "gw-primary",
              disabled: s.value,
              onClick: I
            }, b(c.value.action === "restore" ? "Да, восстановить настройки" : "Да, перезагрузить шлюз"), 9, Zh),
            l("button", {
              disabled: s.value,
              onClick: Q
            }, "Отмена", 8, Qh)
          ])
        ]),
        _: 1
      }, 8, ["title", "busy"])) : x("", !0)
    ], 64));
  }
}), tm = {
  key: 0,
  class: "gw-error",
  role: "alert"
}, nm = { key: 1 }, lm = { key: 0 }, sm = {
  key: 4,
  class: "gw-notice"
}, om = { key: 5 }, im = { key: 6 }, am = { class: "gw-actions" }, rm = ["disabled"], um = ["disabled"], dm = /* @__PURE__ */ Me({
  __name: "OperationPlan",
  props: {
    operation: {},
    busy: { type: Boolean },
    error: {}
  },
  emits: ["apply", "cancel"],
  setup(e, { emit: t }) {
    const n = t, o = { install: "Установка", update: "Обновление", web_access: "Доступ веб-панели", remove: "Удаление", start: "Запуск", stop: "Остановка", restart: "Перезапуск" };
    return (s, i) => (f(), me(Re, {
      title: "План операции",
      busy: e.busy,
      onClose: i[2] || (i[2] = (a) => n("cancel"))
    }, {
      default: Ie(() => [
        e.error ? (f(), h("p", tm, b(e.error), 1)) : x("", !0),
        l("h2", null, b(o[e.operation.action]) + " " + b(e.operation.service) + " " + b(e.operation.version || ""), 1),
        e.operation.network_check ? (f(), h("p", nm, "После действия панель проверит API и состояние службы. Если подтверждение не придёт, будет выполнено восстановление.")) : x("", !0),
        e.operation.action === "remove" ? (f(), h(q, { key: 2 }, [
          i[3] || (i[3] = l("h3", null, "Будет удалено", -1)),
          l("ul", null, [
            (f(!0), h(q, null, oe(e.operation.removed, (a) => (f(), h("li", { key: a }, b(a), 1))), 128))
          ])
        ], 64)) : x("", !0),
        ["install", "update"].includes(e.operation.action) ? (f(), h(q, { key: 3 }, [
          i[4] || (i[4] = l("p", null, "Файлы передаются с панели. GitHub на роутере не используется.", -1)),
          e.operation.action === "update" ? (f(), h("p", lm, "Конфигурация и автозапуск сохраняются. Работающая служба будет остановлена на время обновления и запущена снова. Подготовлен резерв исходной версии для отката.")) : x("", !0),
          l("ul", null, [
            (f(!0), h(q, null, oe(e.operation.changes, (a) => (f(), h("li", {
              key: a.package
            }, b(a.package) + ": " + b(a.before || "не установлен") + " → " + b(a.after), 1))), 128))
          ])
        ], 64)) : x("", !0),
        e.operation.warnings?.length ? (f(), h("section", sm, [
          i[5] || (i[5] = l("h3", null, "Последствия изменений", -1)),
          l("ul", null, [
            (f(!0), h(q, null, oe(e.operation.warnings, (a) => (f(), h("li", { key: a }, b(a), 1))), 128))
          ])
        ])) : x("", !0),
        e.operation.preserved.length ? (f(), h("p", om, "Сохранятся: " + b(e.operation.preserved.join(", ")) + ".", 1)) : x("", !0),
        e.operation.keep_backup ? (f(), h("p", im, "Конфигурация сохраняется в резервную копию; путь будет в журнале.")) : x("", !0),
        l("div", am, [
          l("button", {
            class: "gw-primary",
            disabled: e.busy,
            onClick: i[0] || (i[0] = (a) => n("apply"))
          }, "Да, выполнить показанный план", 8, rm),
          l("button", {
            disabled: e.busy,
            onClick: i[1] || (i[1] = (a) => n("cancel"))
          }, "Отмена", 8, um)
        ])
      ]),
      _: 1
    }, 8, ["busy"]));
  }
}), cm = {
  key: 0,
  class: "gw-error",
  role: "alert"
}, fm = { class: "gw-actions" }, pm = ["disabled"], vm = ["disabled"], gm = /* @__PURE__ */ Me({
  __name: "IntegrationUpdate",
  props: {
    plan: {},
    busy: { type: Boolean },
    error: {}
  },
  emits: ["apply", "cancel"],
  setup(e, { emit: t }) {
    const n = t;
    return (o, s) => (f(), me(Re, {
      title: "Обновление интеграции · " + e.plan.name,
      compact: !0,
      busy: e.busy,
      onClose: s[2] || (s[2] = (i) => n("cancel"))
    }, {
      default: Ie(() => [
        e.error ? (f(), h("p", cm, b(e.error), 1)) : x("", !0),
        (f(!0), h(q, null, oe(e.plan.warnings, (i) => (f(), h("p", {
          key: i,
          class: "gw-notice"
        }, b(i), 1))), 128)),
        l("details", null, [
          l("summary", null, "Компоненты для обновления (" + b(e.plan.files.length) + ")", 1),
          l("ul", null, [
            (f(!0), h(q, null, oe(e.plan.files, (i) => (f(), h("li", { key: i }, b(i), 1))), 128))
          ])
        ]),
        l("div", fm, [
          l("button", {
            class: "gw-primary",
            disabled: e.busy,
            onClick: s[0] || (s[0] = (i) => n("apply"))
          }, "Да, обновить интеграцию", 8, pm),
          l("button", {
            disabled: e.busy,
            onClick: s[1] || (s[1] = (i) => n("cancel"))
          }, "Отмена", 8, vm)
        ])
      ]),
      _: 1
    }, 8, ["title", "busy"]));
  }
}), hm = { class: "gw-pin-detail" }, mm = { class: "gw-actions" }, bm = ["disabled"], ym = ["disabled"], wm = /* @__PURE__ */ Me({
  __name: "TlsTrust",
  props: {
    change: {},
    busy: { type: Boolean }
  },
  emits: ["apply", "cancel"],
  setup(e, { emit: t }) {
    const n = t;
    return (o, s) => (f(), me(Re, {
      title: "Изменение доверия HTTPS",
      busy: e.busy,
      onClose: s[2] || (s[2] = (i) => n("cancel"))
    }, {
      default: Ie(() => [
        l("div", hm, [
          s[5] || (s[5] = l("p", null, "Изменяется сохранённый отпечаток сертификата API.", -1)),
          l("p", null, [
            s[3] || (s[3] = M("Прежний: ", -1)),
            l("code", null, b(e.change.previous), 1)
          ]),
          l("p", null, [
            s[4] || (s[4] = M("Новый: ", -1)),
            l("code", null, b(e.change.next || "Проверка стандартной цепочки сертификатов"), 1)
          ]),
          s[6] || (s[6] = l("p", null, "Подтвердите изменение после проверки сертификата роутера.", -1))
        ]),
        l("div", mm, [
          l("button", {
            class: "gw-primary",
            disabled: e.busy,
            onClick: s[0] || (s[0] = (i) => n("apply"))
          }, "Да, принять изменение", 8, bm),
          l("button", {
            disabled: e.busy,
            onClick: s[1] || (s[1] = (i) => n("cancel"))
          }, "Отмена", 8, ym)
        ])
      ]),
      _: 1
    }, 8, ["busy"]));
  }
}), _m = {
  key: 0,
  class: "gw-error",
  role: "alert"
}, km = {
  key: 1,
  class: "gw-hint"
}, $m = { class: "gw-change-list" }, Cm = {
  key: 0,
  class: "gw-notice"
}, xm = { class: "gw-notice" }, Sm = { class: "gw-actions" }, Tm = ["disabled"], Vm = ["disabled"], Pm = ["disabled"], Um = /* @__PURE__ */ Me({
  __name: "FirewallRestart",
  props: {
    node: {},
    bridge: {}
  },
  emits: ["close", "changed"],
  setup(e, { emit: t }) {
    const n = e, o = t, s = /* @__PURE__ */ D(!1), i = /* @__PURE__ */ D(""), a = /* @__PURE__ */ D(null), u = "/api/gateways/" + encodeURIComponent(n.node.id), c = (A, V, L = "POST") => n.bridge.request(u + A, {
      method: L,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(V)
    });
    async function g() {
      s.value = !0, i.value = "";
      try {
        const A = await n.bridge.request(u + "/network");
        if (!A.settings_hash) throw new Error("Не удалось прочитать актуальные настройки firewall");
        a.value = await c("/network/plan", { action: "firewall_restart", data: { config_hash: A.settings_hash } });
      } catch (A) {
        i.value = A.message;
      } finally {
        s.value = !1;
      }
    }
    async function m() {
      if (!(s.value || !a.value)) {
        s.value = !0, i.value = "";
        try {
          const A = a.value, V = await c("/router-operations", { plan_token: A.plan_token, confirmed: !0 });
          a.value = null, o("close"), n.bridge.task({ taskId: V.task_id, title: A.title, cancellable: !1, onDone: async () => o("changed") });
        } catch (A) {
          i.value = A.message;
        } finally {
          s.value = !1;
        }
      }
    }
    async function w() {
      if (!s.value) {
        s.value = !0, i.value = "";
        try {
          a.value && await c("/operation-plans/" + encodeURIComponent(a.value.plan_token), {}, "DELETE"), a.value = null, o("close");
        } catch (A) {
          i.value = A.message;
        } finally {
          s.value = !1;
        }
      }
    }
    return ot(() => {
      g();
    }), (A, V) => (f(), me(Re, {
      title: "Перезапуск firewall",
      busy: s.value,
      onClose: w
    }, {
      default: Ie(() => [
        i.value ? (f(), h("p", _m, b(i.value), 1)) : x("", !0),
        s.value && !a.value ? (f(), h("p", km, "Получаем план перезапуска…")) : x("", !0),
        a.value ? (f(), h(q, { key: 2 }, [
          l("ul", $m, [
            (f(!0), h(q, null, oe(a.value.summary, (L, R) => (f(), h("li", { key: R }, b(L), 1))), 128))
          ]),
          a.value.warnings?.length ? (f(), h("ul", Cm, [
            (f(!0), h(q, null, oe(a.value.warnings, (L, R) => (f(), h("li", { key: R }, b(L), 1))), 128))
          ])) : x("", !0),
          l("p", xm, "Панель проверит связь. Если подтверждение не придёт в течение " + b(a.value.rollback_seconds) + " секунд, роутер восстановит прежнюю конфигурацию.", 1)
        ], 64)) : x("", !0),
        l("div", Sm, [
          a.value ? (f(), h("button", {
            key: 0,
            class: "gw-primary",
            disabled: s.value,
            onClick: m
          }, "Перезапустить", 8, Tm)) : i.value ? (f(), h("button", {
            key: 1,
            disabled: s.value,
            onClick: g
          }, "Повторить", 8, Vm)) : x("", !0),
          l("button", {
            disabled: s.value,
            onClick: w
          }, "Отмена", 8, Pm)
        ])
      ]),
      _: 1
    }, 8, ["busy"]));
  }
}), Am = {
  key: 0,
  class: "gw-error",
  role: "alert"
}, Em = { key: 0 }, Im = {
  key: 1,
  class: "gw-error",
  role: "alert"
}, Mm = { class: "gw-actions" }, Om = ["disabled"], Rm = { class: "gw-tabs" }, Dm = { class: "gw-two" }, Fm = { class: "gw-actions" }, qm = ["disabled"], Nm = ["disabled"], Hm = { class: "gw-detected" }, Lm = { key: 0 }, jm = {
  key: 0,
  class: "gw-root-warning"
}, Wm = { class: "gw-panel" }, Bm = { key: 0 }, Km = { key: 1 }, Gm = { class: "gw-actions" }, zm = ["disabled"], Jm = ["disabled"], Ym = ["disabled"], Xm = {
  key: 1,
  class: "gw-panel"
}, Zm = { key: 0 }, Qm = { class: "gw-header" }, e1 = {
  key: 0,
  class: "gw-empty"
}, t1 = {
  key: 2,
  class: "server-table-wrap gw-server-table-wrap"
}, n1 = { class: "server-table gw-server-table" }, l1 = ["onClick", "onKeydown"], s1 = { class: "server-name-cell" }, o1 = { class: "gw-server-identity" }, i1 = ["title"], a1 = { class: "server-host-cell" }, r1 = { class: "gw-server-sensors" }, u1 = { class: "gw-card-stats" }, d1 = { class: "gw-server-traffic" }, c1 = {
  key: 1,
  class: "gw-detail"
}, f1 = ["disabled"], p1 = {
  key: 0,
  class: "gw-error"
}, v1 = {
  key: 1,
  class: "gw-hint"
}, g1 = {
  key: 2,
  class: "gw-root-warning",
  role: "status"
}, h1 = { class: "gw-tabs" }, m1 = ["onClick"], b1 = { class: "gw-metrics" }, y1 = { class: "gw-panel" }, w1 = { class: "gw-panel" }, _1 = { class: "gw-panel" }, k1 = { class: "gw-panel" }, $1 = { class: "gw-panel" }, C1 = { key: 0 }, x1 = {
  key: 0,
  class: "gw-hint",
  role: "status"
}, S1 = {
  key: 1,
  class: "gw-error",
  role: "alert"
}, T1 = { class: "gw-catalog-list" }, V1 = { class: "gw-catalog-summary" }, P1 = {
  key: 0,
  class: "gw-status good"
}, U1 = { class: "gw-catalog-body" }, A1 = { class: "gw-catalog-controls" }, E1 = { class: "gw-field" }, I1 = ["onUpdate:modelValue", "disabled"], M1 = {
  key: 0,
  value: ""
}, O1 = { class: "gw-actions" }, R1 = ["disabled", "onClick"], D1 = ["disabled", "onClick"], F1 = { class: "gw-hint" }, q1 = {
  key: 0,
  class: "gw-hint"
}, N1 = {
  key: 1,
  class: "gw-hint"
}, H1 = { class: "gw-reserve-settings" }, L1 = { class: "gw-check" }, j1 = { class: "gw-actions" }, W1 = ["disabled"], B1 = {
  key: 0,
  class: "gw-hint",
  role: "status"
}, K1 = {
  key: 13,
  class: "gw-panel"
}, G1 = { class: "gw-actions" }, z1 = ["disabled"], J1 = { class: "gw-log" }, Y1 = {
  key: 14,
  class: "gw-access"
}, X1 = {
  key: 0,
  class: "gw-section-header gw-access-tools"
}, Z1 = {
  key: 0,
  class: "gw-hint"
}, Q1 = { class: "gw-actions" }, eb = ["disabled"], tb = ["disabled"], nb = ["disabled"], lb = { class: "gw-section-header" }, sb = ["disabled"], ob = {
  key: 2,
  class: "gw-hint"
}, ib = {
  key: 3,
  class: "gw-hint",
  role: "status"
}, ab = { class: "gw-access-columns" }, rb = { class: "gw-hint" }, ub = ["href"], db = { class: "gw-actions" }, cb = ["disabled"], fb = { class: "gw-two" }, pb = ["disabled"], vb = { key: 0 }, gb = { key: 1 }, hb = { class: "gw-actions" }, mb = ["disabled"], bb = {
  key: 0,
  style: { "margin-top": "24px" }
}, yb = {
  key: 0,
  class: "gw-hint"
}, wb = {
  key: 0,
  class: "gw-hint"
}, _b = { class: "gw-actions" }, kb = ["disabled"], $b = ["disabled"], Il = "bot4vps_gateway_location", Cb = /* @__PURE__ */ Me({
  __name: "Gateways",
  props: {
    bridge: {},
    wizard: { type: Boolean },
    initialPlan: {}
  },
  setup(e) {
    const t = /* @__PURE__ */ D(!1), n = /* @__PURE__ */ D(null), o = /* @__PURE__ */ D(null), s = e;
    function i() {
      if (s.wizard || !s.initialPlan?.restore_location || s.initialPlan?.return_node_id) return null;
      try {
        const T = JSON.parse(sessionStorage.getItem(Il) || "null");
        return T && typeof T.nodeId == "string" && ["overview", "network", "wifi", "services", "packages", "backups", "logs", "access"].includes(T.tab) ? T : null;
      } catch {
        return null;
      }
    }
    const a = i(), u = /* @__PURE__ */ D([]), c = /* @__PURE__ */ D(s.wizard ? null : s.initialPlan?.return_node_id || a?.nodeId || null), g = /* @__PURE__ */ D(!1), m = /* @__PURE__ */ D(""), w = /* @__PURE__ */ D(s.wizard), A = /* @__PURE__ */ D("ssh"), V = /* @__PURE__ */ D(s.initialPlan), L = /* @__PURE__ */ D(!1), R = /* @__PURE__ */ D(a?.tab || "overview"), ne = /* @__PURE__ */ D(""), X = /* @__PURE__ */ D("");
    We([c, R], ([T, p]) => {
      if (!s.wizard)
        try {
          T ? sessionStorage.setItem(Il, JSON.stringify({ nodeId: T, tab: p })) : sessionStorage.removeItem(Il);
        } catch {
        }
    }, { immediate: !0 });
    const Z = /* @__PURE__ */ D(""), ee = /* @__PURE__ */ D(0), j = /* @__PURE__ */ D(null), le = /* @__PURE__ */ D(null), Q = /* @__PURE__ */ D(!1), I = /* @__PURE__ */ D(!1), E = /* @__PURE__ */ D(3), P = /* @__PURE__ */ D(null), S = /* @__PURE__ */ D({}), C = /* @__PURE__ */ new Set(), ie = (T, p) => T + ":" + p;
    function ke(T) {
      const p = /* @__PURE__ */ new Set();
      let $ = !1;
      for (const ce of T) for (const ye of ce.service_update_tasks || [])
        p.add(ye.task_id), S.value[ie(ce.id, ye.service)] = { stage: ye.stage, task_id: ye.task_id };
      for (const [ce, ye] of Object.entries(S.value)) ye.stage !== "review" && ye.task_id && !p.has(ye.task_id) && (delete S.value[ce], ce.startsWith((B.value?.id || "") + ":") && ($ = !0));
      $ && R.value === "services" && ee.value++;
    }
    const ae = he(() => Object.fromEntries(Object.entries(S.value).filter(([T]) => T.startsWith((B.value?.id || "") + ":")).map(([T, p]) => [T.split(":").at(-1), p]))), z = /* @__PURE__ */ D(!1), U = /* @__PURE__ */ D([]), d = /* @__PURE__ */ D({ podkop: [], ssclash: [], adguardhome: [] }), r = /* @__PURE__ */ D({ podkop: "", ssclash: "", adguardhome: "" }), v = /* @__PURE__ */ D({ name: "", host: "", port: 22, user: "root", password: "", url: "", username: "", tls_sha256: "" });
    We(A, () => {
      v.value.password = "";
    });
    const _ = /* @__PURE__ */ D({ user: "root", port: 22, auth_type: "password", password: "", key_path: "" }), J = /* @__PURE__ */ D(null), Pe = /* @__PURE__ */ D(null), B = he(() => u.value.find((T) => T.id === c.value)), Fe = /* @__PURE__ */ D({ current_password: "", password: "", confirmation: "" }), qt = /* @__PURE__ */ D(!1), it = /* @__PURE__ */ D(""), at = /* @__PURE__ */ D(), Gt = he(() => at.value && at.value.id === B.value?.id ? at.value.configured : B.value?.root_password_configured);
    let wt = 0;
    async function ml() {
      const T = B.value;
      if (!T || T.ssh_user !== "root" || !T.ssh_configured) return;
      const p = ++wt;
      try {
        const $ = await s.bridge.request("/api/gateways/" + T.id + "/root-password");
        Y && B.value?.id === T.id && p === wt && (at.value = { id: T.id, configured: $.configured });
      } catch {
      }
    }
    We(() => B.value?.id, () => {
      at.value = void 0, qt.value = !1, Fe.value = { current_password: "", password: "", confirmation: "" }, ml();
    });
    const y = he(() => B.value?.monitor || {}), k = he(() => Object.values(y.value.wireguard || {})), O = /* @__PURE__ */ D("");
    function G(T) {
      T.id === "firewall" ? n.value = "firewall" : T.id === "dnsmasq" ? n.value = "dns" : T.id === "adguardhome" ? t.value = !0 : de(T);
    }
    const N = he(() => u.value.filter((T) => (T.name + " " + T.host + " " + (T.monitor.board?.model || "")).toLowerCase().includes(O.value.toLowerCase()))), W = [{ id: "overview", name: "Обзор" }, { id: "network", name: "Сеть" }, { id: "wifi", name: "Wi-Fi" }, { id: "services", name: "Службы" }, { id: "packages", name: "Пакеты" }, { id: "backups", name: "Резервные копии" }, { id: "logs", name: "Журнал" }, { id: "access", name: "Доступ" }];
    let te, Y = !0;
    const K = (T, p, $ = "POST") => s.bridge.request(T, { method: $, headers: { "Content-Type": "application/json" }, body: JSON.stringify(p) }), F = (T) => T == null ? "—" : T > 1073741824 ? (T / 1073741824).toFixed(1) + " ГБ" : T > 1048576 ? (T / 1048576).toFixed(1) + " МБ" : T > 1024 ? (T / 1024).toFixed(1) + " КБ" : T + " Б", ue = (T) => T ? Math.floor(T / 86400) + " д " + Math.floor(T % 86400 / 3600) + " ч" : "—";
    async function se() {
      const T = B.value;
      if (!T) return;
      const p = window.open("about:blank", "_blank");
      try {
        const $ = await s.bridge.request("/api/gateways/" + encodeURIComponent(T.id) + "/adguard"), ye = "http://" + (T.host.includes(":") ? "[" + T.host + "]" : T.host) + ":" + ($.web_port || 3e3) + "/";
        p ? (p.opener = null, p.location.href = ye) : m.value = "Браузер заблокировал открытие сервиса";
      } catch ($) {
        p?.close(), m.value = $ instanceof Error ? $.message : String($);
      }
    }
    function de(T) {
      T.id === "ssclash" || T.id === "adguardhome" ? window.open(ve(T), "_blank", "noopener,noreferrer") : window.open(new URL("/cgi-bin/luci/admin/services/" + (T.id === "podkop" ? "podkop" : ""), B.value.luci_url).href, "_blank", "noopener,noreferrer");
    }
    function ve(T) {
      const p = B.value.host.includes(":") ? "[" + B.value.host + "]" : B.value.host, $ = Number(T.web_port) || (T.id === "adguardhome" ? 3e3 : 9091);
      return (T.web_https ? "https://" : "http://") + p + ":" + $ + "/";
    }
    async function fe() {
      try {
        const T = await s.bridge.request("/api/gateways");
        if (T.enabled === !1) {
          s.bridge.navigate("dashboard");
          return;
        }
        u.value = T.gateways || [], c.value && !u.value.some((p) => p.id === c.value) && (c.value = null, R.value = "overview"), ke(u.value), s.bridge.changed();
      } catch (T) {
        m.value = T.message;
      }
    }
    async function Se() {
      if (!(document.hidden || g.value || w.value))
        try {
          const T = await s.bridge.request("/api/gateways/status");
          if (!Y || !Array.isArray(T.gateways)) return;
          if (T.gateways.length !== u.value.length || T.gateways.some((p) => !u.value.some(($) => $.id === p.id))) {
            await fe();
            return;
          }
          for (const p of T.gateways) {
            const $ = u.value.find((ce) => ce.id === p.id);
            $.monitor = { ...$.monitor, ...p.monitor };
          }
          ke(T.gateways);
        } catch (T) {
          Y && (m.value = T instanceof Error ? T.message : String(T));
        }
    }
    function $e() {
      !document.hidden && !w.value && !s.wizard && (fe(), ml());
    }
    async function be(T) {
      if (!g.value) {
        g.value = !0, m.value = "";
        try {
          await T();
        } catch (p) {
          m.value = p.message;
        } finally {
          g.value = !1;
        }
      }
    }
    async function Oe() {
      await be(async () => {
        if (A.value === "api") {
          const p = await K("/api/gateways/manual", {
            name: v.value.name,
            url: v.value.url,
            username: v.value.username,
            password: v.value.password,
            tls_sha256: v.value.tls_sha256 || null
          });
          v.value.password = "", w.value = !1, c.value = p.id, await fe(), s.bridge.navigate("gateways"), s.bridge.close?.();
          return;
        }
        const T = await K("/api/gateways/probe", {
          name: v.value.name,
          host: v.value.host,
          port: Number(v.value.port),
          user: v.value.user,
          password: v.value.password,
          auth_type: "password"
        });
        if (v.value.password = "", T.node_type !== "openwrt") throw new Error("На этом устройстве OpenWrt не обнаружен. Добавьте его в разделе «Серверы».");
        V.value = T;
      });
    }
    async function Ye(T) {
      await be(async () => {
        const p = await K("/api/gateways/bootstrap/" + encodeURIComponent(V.value.draft_token), { decision: T });
        if (T === "no") {
          V.value = null, w.value = !1, s.bridge.close?.();
          return;
        }
        if (T === "manual") {
          L.value = !0;
          return;
        }
        w.value = !1, s.bridge.task({
          taskId: p.task_id,
          title: "Подключение шлюза",
          cancellable: !1,
          onDone: async ($) => {
            ($.status === "success" || $.status === "success_warn") && (await fe(), s.bridge.navigate("gateways"));
          },
          renderResult: ($, ce) => {
            const ye = document.createElement("p");
            ye.textContent = ["success", "success_warn"].includes($.status) ? $.status === "success_warn" ? "Шлюз подключён и сохранён. Есть предупреждения — проверьте журнал задачи и вкладку «Доступ». Повторное подключение не требуется." : "Управление доступом: LuCI → Службы → Bot4VPS. Секрет в журнал не записывается." : "Подключение не завершено. Проверьте журнал и настройки роутера.", ce.replaceChildren(ye);
          }
        }), s.bridge.close?.();
      });
    }
    async function qe(T) {
      n.value = null, t.value = !1, R.value = T, m.value = "", X.value = "", Q.value = !1, T === "logs" && B.value && await be(async () => {
        ne.value = (await s.bridge.request("/api/gateways/" + B.value.id + "/logs")).output;
      }), T === "access" && B.value && (v.value.name = B.value.name, v.value.url = B.value.api_url, v.value.username = B.value.api_username, v.value.tls_sha256 = B.value.tls_sha256 || "", v.value.password = "", _.value = { user: B.value.ssh_user || "root", port: B.value.ssh_port || 22, auth_type: B.value.ssh_auth_type || "password", password: "", key_path: "" });
    }
    async function Xe(T, p, $, ce, ye) {
      const nt = B.value?.id;
      nt && await be(async () => {
        const en = await K("/api/gateways/" + nt + "/services/" + T + "/plan", { action: p, keep_backup: !0, bundle_id: $ || null, rollback_bundle_id: ce || null, web_scope: ye || null });
        if (!Y || B.value?.id !== nt) {
          await K("/api/gateways/" + nt + "/operation-plans/" + encodeURIComponent(en.plan_token), {}, "DELETE");
          return;
        }
        le.value = en, P.value = nt, z.value = Q.value, Q.value = !1;
      });
    }
    function un(T, p, $, ce) {
      const ye = ie(T, p);
      S.value[ye] = { stage: ce, task_id: $ }, !C.has($) && (C.add($), s.bridge.task({ taskId: $, title: ce === "prepare" ? "Подготовка обновления " + p : "Обновление " + p, cancellable: !1, onDone: async () => {
        try {
          const nt = await s.bridge.request("/api/tasks/" + encodeURIComponent($));
          if (S.value[ye]?.task_id && S.value[ye].task_id !== $) return;
          if (!nt.success) {
            Y && B.value?.id === T && (m.value = nt.error || "Обновление завершилось с ошибкой. Проверьте журнал задачи."), delete S.value[ye];
            return;
          }
          if (ce === "prepare") {
            if (!Y || B.value?.id !== T) {
              delete S.value[ye];
              return;
            }
            const en = JSON.parse(nt.result.output);
            if (en.review_prepared) {
              const Ti = await s.bridge.request("/api/gateways/" + T + "/services/" + p + "/update-plan?task_id=" + encodeURIComponent($));
              if (S.value[ye]?.task_id && S.value[ye].task_id !== $) return;
              if (!Y || B.value?.id !== T) {
                delete S.value[ye];
                return;
              }
              Be(Ti);
            } else await Xe(p, "update", en.bundle_id, en.rollback_bundle_id);
            le.value?.action === "update" && le.value.service === p && P.value === T ? S.value[ye] = { stage: "review", task_id: le.value.preparation_task_id || $ } : delete S.value[ye];
          } else
            delete S.value[ye], Y && (await fe(), await Dn(), ee.value++);
        } catch (nt) {
          (!S.value[ye]?.task_id || S.value[ye].task_id === $) && delete S.value[ye], Y && B.value?.id === T && (m.value = nt instanceof Error ? nt.message : String(nt));
        }
      } }));
    }
    function Be(T) {
      const p = B.value?.id;
      !p || T.node_id && T.node_id !== p || (le.value = T, P.value = p, S.value[ie(p, T.service)] = { stage: "review", task_id: T.preparation_task_id || void 0 });
    }
    function rt(T, p) {
      B.value && p.task_id && (S.value[ie(B.value.id, T)] = { stage: p.stage, task_id: p.task_id });
    }
    async function On(T) {
      const p = B.value?.id;
      if (!p || g.value || S.value[ie(p, T)]) return;
      const $ = ie(p, T);
      S.value[$] = { stage: "prepare" }, await be(async () => {
        try {
          const ce = await K("/api/gateways/" + p + "/services/" + T + "/update-bundle", {});
          un(p, T, ce.task_id, "prepare");
        } catch (ce) {
          throw delete S.value[$], ce;
        }
      });
    }
    async function Rn() {
      await be(async () => {
        const T = await K("/api/gateways/" + B.value.id + "/bootstrap/finalize", {});
        s.bridge.task({ taskId: T.task_id, title: "Фиксация подключения", cancellable: !1, onDone: fe });
      });
    }
    async function pi() {
      const T = B.value;
      T && await be(async () => {
        const p = await K("/api/gateways/" + T.id + "/integration/plan", {});
        Pe.value = { ...p, nodeId: T.id, name: T.name };
      });
    }
    function vi() {
      const T = Pe.value;
      Pe.value = null, T && K("/api/gateways/" + T.nodeId + "/integration/plans/" + encodeURIComponent(T.plan_token), {}, "DELETE").catch((p) => {
        m.value = p instanceof Error ? p.message : String(p);
      });
    }
    async function gi() {
      const T = Pe.value;
      T && await be(async () => {
        const p = await K("/api/gateways/" + T.nodeId + "/integration", { plan_token: T.plan_token, confirmed: !0 });
        Pe.value = null, s.bridge.task({ taskId: p.task_id, title: "Обновление интеграции Bot4VPS", cancellable: !1, onDone: async () => {
          Y && (await fe(), ee.value++);
        } });
      });
    }
    async function hi() {
      const T = le.value?.plan_token, p = P.value || B.value?.id;
      le.value?.action === "update" && p && delete S.value[ie(p, le.value.service)];
      const $ = le.value?.action === "update";
      if (le.value = null, P.value = null, m.value = "", z.value && (Q.value = !0), z.value = !1, T && p)
        try {
          await K("/api/gateways/" + encodeURIComponent(p) + "/operation-plans/" + encodeURIComponent(T), {}, "DELETE");
        } catch (ce) {
          m.value = ce instanceof Error ? ce.message : String(ce);
        } finally {
          $ && ee.value++;
        }
    }
    async function mi() {
      const T = le.value, p = P.value || B.value?.id;
      !T || !p || await be(async () => {
        const $ = await K("/api/gateways/" + p + "/operations", { plan_token: T.plan_token, confirmed: !0 }), ce = T.service;
        if (le.value = null, P.value = null, T.action === "update") {
          un(p, ce, $.task_id, "apply");
          return;
        }
        s.bridge.task({
          taskId: $.task_id,
          title: "Операция: " + ce,
          cancellable: !1,
          onDone: async () => {
            await fe(), await Dn(), ee.value++;
          },
          onResultClosed: (ye) => {
            Y && B.value?.id === p && ce === "adguardhome" && T.action === "install" && ["success", "success_warn"].includes(ye.status) && (t.value = !0);
          }
        });
      });
    }
    async function Dn() {
      const T = await s.bridge.request("/api/gateways/reserve");
      I.value = T.settings.enabled, E.value = T.settings.keep, U.value = T.bundles;
    }
    async function gs() {
      Q.value = !0, await be(async () => {
        await Dn(), await Promise.all(["podkop", "ssclash", "adguardhome"].map(async (T) => {
          const p = await s.bridge.request("/api/gateways/catalog/" + T + "?node_id=" + encodeURIComponent(B.value.id));
          d.value[T] = p.versions, p.versions.includes(r.value[T]) || (r.value[T] = p.versions[0] || "");
        }));
      });
    }
    async function bi() {
      await be(async () => {
        await K("/api/gateways/reserve", { enabled: I.value, keep: Number(E.value) }, "PUT"), X.value = I.value ? "Резервирование включено. Службы на роутере не устанавливаются и не обновляются." : "Автоматическое резервирование отключено. Сохранённые резервные версии останутся на панели.";
      });
    }
    async function yi(T) {
      await be(async () => {
        const p = await K("/api/gateways/" + B.value.id + "/bundles", { profile: T, version: r.value[T] });
        s.bridge.task({
          taskId: p.task_id,
          title: "Подготовка комплекта " + T,
          cancellable: !1,
          onDone: async () => {
            await Dn();
          }
        });
      });
    }
    function bl(T) {
      return U.value.find((p) => p.profile === T && p.version === r.value[T] && p.platform.release?.version === y.value.board?.release?.version && p.platform.release?.target === y.value.board?.release?.target && p.complete);
    }
    async function wi() {
      const T = B.value?.id;
      if (!T) return;
      const p = B.value.tls_sha256, $ = v.value.tls_sha256 || null;
      if (p && p !== $) {
        J.value = { nodeId: T, previous: p, next: $ };
        return;
      }
      await hs(!1);
    }
    async function hs(T) {
      const p = B.value?.id;
      !p || T && J.value?.nodeId !== p || (J.value = null, await be(async () => {
        await K("/api/gateways/" + p + "/credentials", {
          name: v.value.name,
          url: v.value.url,
          username: v.value.username,
          password: v.value.password,
          tls_sha256: v.value.tls_sha256 || null,
          tls_pin_confirmed: T
        }, "PUT"), v.value.password = "", X.value = "Доступ проверен и сохранён", await fe();
      }));
    }
    async function _i() {
      if (!B.value.ssh_configured) {
        await qe("access"), m.value = "Сначала сохраните SSH-доступ для консоли.";
        return;
      }
      await be(async () => {
        await s.bridge.console?.(B.value);
      });
    }
    async function ki() {
      await be(async () => {
        const T = await K("/api/gateways/" + B.value.id + "/ssh", { ..._.value, password: _.value.password || null }, "PUT");
        ++wt, at.value = { id: T.id, configured: T.root_password_configured }, _.value.password = "", X.value = "SSH-доступ проверен и сохранён.", await fe();
      });
    }
    function $i() {
      it.value = "", Fe.value = { current_password: "", password: "", confirmation: "" }, qt.value = !0;
    }
    function ms() {
      Fe.value = { current_password: "", password: "", confirmation: "" }, qt.value = !1;
    }
    async function Ci() {
      const T = B.value;
      if (!(!T || g.value)) {
        if (it.value = "", Fe.value.password !== Fe.value.confirmation) {
          it.value = "Пароли не совпадают.";
          return;
        }
        g.value = !0;
        try {
          const p = await K("/api/gateways/" + T.id + "/root-password", Fe.value, "PUT");
          ++wt, at.value = { id: T.id, configured: p.root_password_configured }, ms(), X.value = p.ssh_auth_type === "key" ? "Пароль root изменён. Консоль подключается по SSH-ключу." : "Пароль root и SSH для консоли обновлены.", await fe(), B.value?.id === T.id && (_.value.auth_type = p.ssh_auth_type);
        } catch (p) {
          it.value = p.message;
        } finally {
          g.value = !1;
        }
      }
    }
    async function xi() {
      await be(async () => {
        j.value = await s.bridge.request("/api/gateways/" + B.value.id + "/deletion-plan");
      });
    }
    async function Si() {
      await be(async () => {
        const T = await K("/api/gateways/" + B.value.id, { confirmed: !0, plan_token: j.value.plan_token }, "DELETE");
        j.value = null, s.bridge.task({
          taskId: T.task_id,
          title: "Удаление шлюза и отзыв API",
          cancellable: !1,
          onDone: async () => {
            c.value = null, await fe();
          },
          renderResult: (p, $) => {
            const ce = document.createElement("p");
            ce.textContent = p.status === "success" ? "Удаление шлюза завершено. Результат очистки Bot4VPS — в журнале задачи. Настройки роутера и установленные службы сохранены." : "Отзыв доступа или очистка интеграции не завершены. Запись шлюза сохранена; проверьте журнал задачи.", $.replaceChildren(ce);
          }
        });
      });
    }
    return ot(() => {
      s.wizard || (fe().then(() => {
        if (Y && B.value) return qe(R.value);
      }), te = setInterval(() => {
        Se();
      }, 5e3), document.addEventListener("visibilitychange", $e));
    }), yt(() => {
      Y = !1, te && clearInterval(te), document.removeEventListener("visibilitychange", $e), v.value.password = "", _.value.password = "";
    }), (T, p) => (f(), h("div", {
      class: Te(["gw-shell", { "gw-wizard": e.wizard }])
    }, [
      m.value ? (f(), h("div", Am, b(m.value), 1)) : x("", !0),
      Pe.value ? (f(), me(gm, {
        key: 1,
        plan: Pe.value,
        busy: g.value,
        error: m.value,
        onCancel: vi,
        onApply: gi
      }, null, 8, ["plan", "busy", "error"])) : x("", !0),
      J.value ? (f(), me(wm, {
        key: 2,
        change: J.value,
        busy: g.value,
        onCancel: p[0] || (p[0] = ($) => J.value = null),
        onApply: p[1] || (p[1] = ($) => hs(!0))
      }, null, 8, ["change", "busy"])) : x("", !0),
      qt.value ? (f(), me(Re, {
        key: 3,
        title: Gt.value === !1 ? "Задать пароль root" : "Сменить пароль root",
        busy: g.value,
        compact: "",
        onClose: ms
      }, {
        default: Ie(() => [
          l("form", {
            class: "gw-form",
            onSubmit: tt(Ci, ["prevent"])
          }, [
            Gt.value !== !1 ? (f(), h("label", Em, [
              p[52] || (p[52] = M("Текущий пароль", -1)),
              Ae(vt, {
                modelValue: Fe.value.current_password,
                "onUpdate:modelValue": p[2] || (p[2] = ($) => Fe.value.current_password = $),
                required: "",
                autocomplete: "current-password",
                disabled: g.value
              }, null, 8, ["modelValue", "disabled"])
            ])) : x("", !0),
            l("label", null, [
              p[53] || (p[53] = M("Новый пароль", -1)),
              Ae(vt, {
                modelValue: Fe.value.password,
                "onUpdate:modelValue": p[3] || (p[3] = ($) => Fe.value.password = $),
                required: "",
                autocomplete: "new-password",
                disabled: g.value
              }, null, 8, ["modelValue", "disabled"])
            ]),
            l("label", null, [
              p[54] || (p[54] = M("Повторите пароль", -1)),
              Ae(vt, {
                modelValue: Fe.value.confirmation,
                "onUpdate:modelValue": p[4] || (p[4] = ($) => Fe.value.confirmation = $),
                required: "",
                autocomplete: "new-password",
                disabled: g.value
              }, null, 8, ["modelValue", "disabled"])
            ]),
            it.value ? (f(), h("p", Im, b(it.value), 1)) : x("", !0),
            l("div", Mm, [
              l("button", {
                class: "gw-primary",
                disabled: g.value
              }, b(g.value ? "Сохраняем…" : "Сохранить"), 9, Om)
            ])
          ], 32)
        ]),
        _: 1
      }, 8, ["title", "busy"])) : x("", !0),
      w.value ? (f(), h(q, { key: 4 }, [
        p[71] || (p[71] = l("header", { class: "gw-header" }, [
          l("div", null, [
            l("span", { class: "gw-eyebrow" }, "НОВОЕ ПОДКЛЮЧЕНИЕ"),
            l("h2", null, "Добавить шлюз"),
            l("p", null, "Подключение OpenWrt к вашей инфраструктуре")
          ])
        ], -1)),
        V.value ? (f(), h(q, { key: 1 }, [
          l("div", Hm, [
            p[65] || (p[65] = l("span", { class: "gw-status good" }, "OpenWrt обнаружен", -1)),
            l("h3", null, b(V.value.board.model), 1),
            V.value.name ? (f(), h("p", Lm, "Имя шлюза: " + b(V.value.name), 1)) : x("", !0),
            l("p", null, b(V.value.board.release?.version) + " · " + b(V.value.board.release?.target), 1)
          ]),
          V.value.board.root_password_configured === !1 ? (f(), h("div", jm, "Пароль root не задан. После подключения задайте его во вкладке «Доступ».")) : x("", !0),
          l("div", Wm, [
            p[67] || (p[67] = l("h3", null, "Для подключения панель выполнит", -1)),
            l("ul", null, [
              (f(!0), h(q, null, oe(V.value.missing_packages, ($) => (f(), h("li", { key: $ }, [
                p[66] || (p[66] = M("Установит пакет ", -1)),
                l("strong", null, b($), 1)
              ]))), 128)),
              V.value.missing_packages?.length ? x("", !0) : (f(), h("li", Bm, "Необходимые пакеты уже установлены")),
              (f(!0), h(q, null, oe(V.value.changes, ($) => (f(), h("li", { key: $ }, b($), 1))), 128)),
              V.value.https_configuration_required ? (f(), h("li", Km, "Включит HTTPS на адресе LAN")) : x("", !0)
            ]),
            p[68] || (p[68] = l("p", { class: "gw-hint" }, "Прошивка и установленные пакеты не обновляются. Сетевые интерфейсы не перенастраиваются. Ход настройки будет виден в журнале.", -1))
          ]),
          l("div", Gm, [
            l("button", {
              class: "gw-primary",
              disabled: g.value,
              onClick: p[17] || (p[17] = ($) => Ye("automatic"))
            }, "Да, настроить автоматически", 8, zm),
            l("button", {
              disabled: g.value,
              onClick: p[18] || (p[18] = ($) => Ye("no"))
            }, "Нет", 8, Jm),
            l("button", {
              disabled: g.value,
              onClick: p[19] || (p[19] = ($) => Ye("manual"))
            }, "Настроить самостоятельно", 8, Ym)
          ]),
          L.value ? (f(), h("div", Xm, [
            p[70] || (p[70] = l("h3", null, "Самостоятельная настройка", -1)),
            V.value.manual.commands.length ? (f(), h("pre", Zm, b(V.value.manual.commands.join(`
`)), 1)) : x("", !0),
            l("ol", null, [
              (f(!0), h(q, null, oe(V.value.manual.steps, ($) => (f(), h("li", { key: $ }, b($), 1))), 128))
            ]),
            l("details", null, [
              p[69] || (p[69] = l("summary", null, "Права мониторинга rpcd", -1)),
              l("pre", null, b(JSON.stringify(V.value.manual.acl, null, 2)), 1)
            ]),
            l("button", {
              onClick: p[20] || (p[20] = ($) => {
                A.value = "api", V.value = null;
              })
            }, "Указать данные API")
          ])) : x("", !0)
        ], 64)) : (f(), h(q, { key: 0 }, [
          l("div", Rm, [
            l("button", {
              class: Te({ on: A.value === "ssh" }),
              onClick: p[5] || (p[5] = ($) => A.value = "ssh")
            }, "Настроить автоматически", 2),
            l("button", {
              class: Te({ on: A.value === "api" }),
              onClick: p[6] || (p[6] = ($) => A.value = "api")
            }, "API уже настроен", 2)
          ]),
          l("form", {
            class: "gw-form",
            onSubmit: tt(Oe, ["prevent"])
          }, [
            l("label", null, [
              p[55] || (p[55] = M("Имя шлюза", -1)),
              H(l("input", {
                "onUpdate:modelValue": p[7] || (p[7] = ($) => v.value.name = $),
                placeholder: "Определится по модели роутера",
                maxlength: "100"
              }, null, 512), [
                [re, v.value.name]
              ])
            ]),
            A.value === "ssh" ? (f(), h(q, { key: 0 }, [
              l("label", null, [
                p[56] || (p[56] = M("Адрес роутера", -1)),
                H(l("input", {
                  "onUpdate:modelValue": p[8] || (p[8] = ($) => v.value.host = $),
                  required: "",
                  placeholder: "192.168.1.1"
                }, null, 512), [
                  [re, v.value.host]
                ])
              ]),
              l("div", Dm, [
                l("label", null, [
                  p[57] || (p[57] = M("SSH-порт", -1)),
                  H(l("input", {
                    "onUpdate:modelValue": p[9] || (p[9] = ($) => v.value.port = $),
                    required: "",
                    type: "number",
                    min: "1",
                    max: "65535"
                  }, null, 512), [
                    [re, v.value.port]
                  ])
                ]),
                l("label", null, [
                  p[58] || (p[58] = M("Логин", -1)),
                  H(l("input", {
                    "onUpdate:modelValue": p[10] || (p[10] = ($) => v.value.user = $),
                    required: "",
                    autocomplete: "username"
                  }, null, 512), [
                    [re, v.value.user]
                  ])
                ])
              ]),
              l("label", null, [
                p[59] || (p[59] = M("SSH-пароль", -1)),
                Ae(vt, {
                  modelValue: v.value.password,
                  "onUpdate:modelValue": p[11] || (p[11] = ($) => v.value.password = $),
                  required: v.value.user !== "root",
                  autocomplete: "off",
                  placeholder: "Оставьте пустым, если пароль root ещё не задан"
                }, null, 8, ["modelValue", "required"])
              ]),
              p[60] || (p[60] = l("p", { class: "gw-hint" }, "Сначала панель проверит устройство и покажет необходимые изменения. Проверка ничего не устанавливает.", -1))
            ], 64)) : (f(), h(q, { key: 1 }, [
              l("label", null, [
                p[61] || (p[61] = M("HTTPS API", -1)),
                H(l("input", {
                  "onUpdate:modelValue": p[12] || (p[12] = ($) => v.value.url = $),
                  required: "",
                  type: "url",
                  placeholder: "https://192.168.1.1/ubus"
                }, null, 512), [
                  [re, v.value.url]
                ])
              ]),
              l("label", null, [
                p[62] || (p[62] = M("Логин API", -1)),
                H(l("input", {
                  "onUpdate:modelValue": p[13] || (p[13] = ($) => v.value.username = $),
                  required: "",
                  autocomplete: "username"
                }, null, 512), [
                  [re, v.value.username]
                ])
              ]),
              l("label", null, [
                p[63] || (p[63] = M("Секрет API", -1)),
                Ae(vt, {
                  modelValue: v.value.password,
                  "onUpdate:modelValue": p[14] || (p[14] = ($) => v.value.password = $),
                  required: "",
                  autocomplete: "off"
                }, null, 8, ["modelValue"])
              ]),
              l("label", null, [
                p[64] || (p[64] = M("SHA-256 сертификата", -1)),
                H(l("input", {
                  "onUpdate:modelValue": p[15] || (p[15] = ($) => v.value.tls_sha256 = $),
                  placeholder: "Для собственного сертификата роутера"
                }, null, 512), [
                  [re, v.value.tls_sha256]
                ])
              ])
            ], 64)),
            l("div", Fm, [
              l("button", {
                class: "gw-primary",
                disabled: g.value
              }, b(g.value ? "Проверяем…" : A.value === "ssh" ? "Проверить роутер" : "Проверить и подключить"), 9, qm),
              l("button", {
                type: "button",
                onClick: p[16] || (p[16] = ($) => {
                  w.value = !1, e.bridge.close?.();
                }),
                disabled: g.value
              }, "Отмена", 8, Nm)
            ])
          ], 32)
        ], 64))
      ], 64)) : e.wizard ? x("", !0) : (f(), h(q, { key: 5 }, [
        B.value ? x("", !0) : (f(), h(q, { key: 0 }, [
          l("header", Qm, [
            l("div", null, [
              p[72] || (p[72] = l("span", { class: "gw-eyebrow" }, "СЕТЬ И МАРШРУТИЗАЦИЯ", -1)),
              p[73] || (p[73] = l("h1", null, "Шлюзы", -1)),
              l("p", null, "OpenWrt · " + b(u.value.length) + " подключений", 1)
            ]),
            l("button", {
              class: "gw-primary",
              onClick: p[21] || (p[21] = ($) => e.bridge.add?.())
            }, "Добавить шлюз")
          ]),
          u.value.length ? x("", !0) : (f(), h("div", e1, [
            p[74] || (p[74] = l("div", { class: "gw-empty-icon" }, "⌘", -1)),
            p[75] || (p[75] = l("h2", null, "Подключите ваш OpenWrt", -1)),
            p[76] || (p[76] = l("p", null, "Обзор сети, состояние служб и операции с понятным журналом.", -1)),
            l("button", {
              class: "gw-primary",
              onClick: p[22] || (p[22] = ($) => e.bridge.add?.())
            }, "Добавить шлюз")
          ])),
          u.value.length > 3 ? H((f(), h("input", {
            key: 1,
            "onUpdate:modelValue": p[23] || (p[23] = ($) => O.value = $),
            class: "gw-node-search",
            type: "search",
            "aria-label": "Поиск шлюзов",
            placeholder: "Найти шлюз по имени или адресу"
          }, null, 512)), [
            [re, O.value]
          ]) : x("", !0),
          N.value.length ? (f(), h("div", t1, [
            l("table", n1, [
              p[81] || (p[81] = l("thead", null, [
                l("tr", null, [
                  l("th", null, "Имя шлюза"),
                  l("th", null, "Адрес / OpenWrt"),
                  l("th", null, "Статус"),
                  l("th", null, "Нагрузка"),
                  l("th", null, "Трафик LAN / WAN")
                ])
              ], -1)),
              l("tbody", null, [
                (f(!0), h(q, null, oe(N.value, ($) => (f(), h("tr", {
                  key: $.id,
                  class: "server-table-row",
                  tabindex: "0",
                  role: "button",
                  onClick: (ce) => {
                    c.value = $.id, R.value = "overview", m.value = "";
                  },
                  onKeydown: [
                    sl(tt((ce) => {
                      c.value = $.id, R.value = "overview", m.value = "";
                    }, ["prevent"]), ["enter"]),
                    sl(tt((ce) => {
                      c.value = $.id, R.value = "overview", m.value = "";
                    }, ["prevent"]), ["space"])
                  ]
                }, [
                  l("td", s1, [
                    l("div", o1, [
                      p[77] || (p[77] = l("span", {
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
                      }, b($.name), 9, i1)
                    ])
                  ]),
                  l("td", a1, [
                    l("span", null, b($.host), 1),
                    l("small", null, "OpenWrt " + b($.monitor.board?.release?.version || "—"), 1)
                  ]),
                  l("td", null, [
                    l("span", {
                      class: Te(["gw-status", $.monitor.ok ? "good" : "warn"])
                    }, b($.monitor.ok ? $.monitor.stale ? "Данные устарели" : "На связи" : "Нет доступа к API"), 3)
                  ]),
                  l("td", r1, [
                    l("div", u1, [
                      l("span", null, [
                        p[78] || (p[78] = M("CPU ", -1)),
                        l("b", null, b($.monitor.cpu_pct == null ? "—" : $.monitor.cpu_pct + "%"), 1)
                      ]),
                      l("span", null, [
                        p[79] || (p[79] = M("RAM ", -1)),
                        l("b", null, b($.monitor.ram_pct == null ? "—" : $.monitor.ram_pct + "%"), 1)
                      ]),
                      l("span", null, [
                        p[80] || (p[80] = M("SoC ", -1)),
                        l("b", null, b($.monitor.temperature == null ? "—" : $.monitor.temperature + "°C"), 1)
                      ])
                    ])
                  ]),
                  l("td", d1, [
                    l("span", null, "LAN ↓ " + b(F($.monitor.traffic?.lan?.rx_bps)) + "/с · ↑ " + b(F($.monitor.traffic?.lan?.tx_bps)) + "/с", 1),
                    l("span", null, "WAN ↓ " + b(F($.monitor.traffic?.wan?.rx_bps)) + "/с · ↑ " + b(F($.monitor.traffic?.wan?.tx_bps)) + "/с", 1)
                  ])
                ], 40, l1))), 128))
              ])
            ])
          ])) : x("", !0)
        ], 64)),
        B.value ? (f(), h("section", c1, [
          l("button", {
            class: "gw-back-link",
            disabled: g.value,
            onClick: p[24] || (p[24] = ($) => {
              c.value = null, Q.value = !1;
            })
          }, "← Все шлюзы", 8, f1),
          Ae(Sh, {
            node: B.value,
            busy: g.value,
            onConsole: _i
          }, null, 8, ["node", "busy"]),
          y.value.ok ? x("", !0) : (f(), h("p", p1, b(y.value.error) + ". " + b(y.value.error_code === "permission" ? "Проверьте доступ в LuCI или укажите новый секрет во вкладке «Доступ»." : "Проверьте доступность API роутера. Панель повторит проверку автоматически."), 1)),
          B.value.bootstrap_state === "commit_pending" ? (f(), h("p", v1, "Шлюз подключён. Фиксация транзакции не подтверждена; завершите её во вкладке «Доступ».")) : x("", !0),
          Gt.value === !1 ? (f(), h("div", g1, [
            p[82] || (p[82] = l("span", null, [
              l("strong", null, "Пароль root не задан."),
              M(" Задайте пароль для защиты доступа к роутеру.")
            ], -1)),
            l("button", {
              type: "button",
              onClick: p[25] || (p[25] = ($) => qe("access"))
            }, "Открыть «Доступ»")
          ])) : x("", !0),
          l("div", h1, [
            (f(), h(q, null, oe(W, ($) => l("button", {
              key: $.id,
              class: Te({ on: R.value === $.id }),
              onClick: (ce) => qe($.id)
            }, b($.name), 11, m1)), 64))
          ]),
          R.value === "overview" ? (f(), h(q, { key: 3 }, [
            l("div", b1, [
              l("div", y1, [
                p[83] || (p[83] = l("span", null, "Загрузка CPU", -1)),
                l("strong", null, b(y.value.cpu_pct == null ? "—" : y.value.cpu_pct + "%"), 1)
              ]),
              l("div", w1, [
                p[84] || (p[84] = l("span", null, "Оперативная память", -1)),
                l("strong", null, b(y.value.ram_pct == null ? "—" : y.value.ram_pct + "%"), 1),
                l("small", null, b(F(y.value.ram_used)) + " / " + b(F(y.value.ram_total)), 1)
              ]),
              l("div", _1, [
                p[85] || (p[85] = l("span", null, "Свободное место", -1)),
                l("strong", null, b(F(y.value.storage_free)), 1),
                l("small", null, "из " + b(F(y.value.storage_total)), 1)
              ]),
              l("div", k1, [
                p[86] || (p[86] = l("span", null, "Время работы", -1)),
                l("strong", null, b(ue(y.value.uptime)), 1)
              ]),
              l("div", $1, [
                p[87] || (p[87] = l("span", null, "Температура", -1)),
                l("strong", null, b(y.value.temperature == null ? "Нет датчика" : y.value.temperature + "°C"), 1),
                y.value.temperature_support?.virtual ? (f(), h("small", C1, "Виртуальная машина")) : x("", !0),
                y.value.temperature_support?.package ? (f(), h("button", {
                  key: 1,
                  onClick: p[26] || (p[26] = ($) => {
                    Z.value = y.value.temperature_support.package, qe("packages");
                  })
                }, "Проверить пакет датчика")) : x("", !0)
              ])
            ]),
            Ae(mp, {
              monitor: y.value,
              "node-id": B.value.id,
              bridge: e.bridge
            }, null, 8, ["monitor", "node-id", "bridge"])
          ], 64)) : x("", !0),
          H((f(), me(Fp, {
            key: B.value.id,
            "node-id": B.value.id,
            bridge: e.bridge,
            collect: R.value === "overview"
          }, null, 8, ["node-id", "bridge", "collect"])), [
            [hn, R.value === "overview"]
          ]),
          R.value === "network" ? (f(), me(xf, {
            key: B.value.id,
            node: B.value,
            bridge: e.bridge,
            onChanged: fe
          }, null, 8, ["node", "bridge"])) : x("", !0),
          R.value === "wifi" ? (f(), me(vg, {
            key: B.value.id,
            node: B.value,
            bridge: e.bridge,
            onChanged: fe
          }, null, 8, ["node", "bridge"])) : x("", !0),
          R.value === "services" ? (f(), me(yh, {
            key: B.value.id,
            revision: ee.value,
            node: B.value,
            bridge: e.bridge,
            busy: g.value,
            updating: ae.value,
            onChanged: fe,
            onPending: rt,
            onResume: Be,
            onWebAccess: p[27] || (p[27] = ($) => Xe("ssclash", "web_access", void 0, void 0, $)),
            onCatalog: gs,
            onSettings: G,
            onHelp: p[28] || (p[28] = ($) => t.value = !0),
            onOpenAdguard: se,
            onAction: Xe,
            onFirewallRestart: p[29] || (p[29] = ($) => o.value = B.value),
            onUpdate: On
          }, null, 8, ["revision", "node", "bridge", "busy", "updating"])) : x("", !0),
          R.value === "backups" ? (f(), me(em, {
            key: B.value.id,
            node: B.value,
            bridge: e.bridge
          }, null, 8, ["node", "bridge"])) : x("", !0),
          o.value ? (f(), me(Um, {
            key: 8,
            node: o.value,
            bridge: e.bridge,
            onClose: p[30] || (p[30] = ($) => o.value = null),
            onChanged: fe
          }, null, 8, ["node", "bridge"])) : x("", !0),
          n.value ? (f(), me(ps, {
            key: 9,
            node: B.value,
            bridge: e.bridge,
            mode: n.value,
            onClose: p[31] || (p[31] = ($) => n.value = null),
            onChanged: fe
          }, null, 8, ["node", "bridge", "mode"])) : x("", !0),
          Q.value ? (f(), me(Re, {
            key: 10,
            title: "Установка служб",
            wide: !0,
            compact: !0,
            onClose: p[35] || (p[35] = ($) => {
              Q.value = !1, m.value = "";
            })
          }, {
            default: Ie(() => [
              p[93] || (p[93] = l("p", { class: "gw-hint" }, "Готовые комплекты с зависимостями для вашего OpenWrt. Скачивание на панель и установка на роутер выполняются отдельно.", -1)),
              g.value ? (f(), h("p", x1, "Получаем совместимые версии…")) : x("", !0),
              m.value ? (f(), h("p", S1, b(m.value), 1)) : x("", !0),
              l("div", T1, [
                (f(), h(q, null, oe(["podkop", "ssclash", "adguardhome"], ($) => l("details", {
                  key: $,
                  class: "gw-catalog-item"
                }, [
                  l("summary", V1, [
                    l("div", null, [
                      l("h3", null, b($ === "podkop" ? "Podkop" : $ === "ssclash" ? "SSClash-Go" : "AdGuard Home"), 1),
                      Ae(fs, { id: $ }, null, 8, ["id"])
                    ]),
                    y.value.services?.some((ce) => ce.id === $) ? (f(), h("span", P1, "Установлен")) : x("", !0)
                  ]),
                  l("div", U1, [
                    l("div", A1, [
                      l("label", E1, [
                        p[88] || (p[88] = M("Версия", -1)),
                        H(l("select", {
                          "onUpdate:modelValue": (ce) => r.value[$] = ce,
                          disabled: g.value
                        }, [
                          (f(!0), h(q, null, oe(d.value[$], (ce) => (f(), h("option", { key: ce }, b(ce), 1))), 128)),
                          d.value[$]?.length ? x("", !0) : (f(), h("option", M1, b(g.value ? "Загружаем версии…" : "Нет совместимых версий"), 1))
                        ], 8, I1), [
                          [xe, r.value[$]]
                        ])
                      ]),
                      l("div", O1, [
                        bl($) ? (f(), h("button", {
                          key: 1,
                          disabled: g.value || y.value.services?.some((ce) => ce.id === $),
                          class: "gw-primary",
                          onClick: (ce) => Xe($, "install", bl($).id)
                        }, "Установить", 8, D1)) : (f(), h("button", {
                          key: 0,
                          disabled: g.value || !r.value[$],
                          onClick: (ce) => yi($)
                        }, "Скачать комплект на панель", 8, R1)),
                        $ === "adguardhome" ? (f(), h("button", {
                          key: 2,
                          onClick: p[32] || (p[32] = (ce) => {
                            Q.value = !1, t.value = !0;
                          })
                        }, "Настроить DNS")) : x("", !0)
                      ])
                    ]),
                    l("p", F1, b(bl($) ? "Комплект сохранён на панели — установка доступна без GitHub." : "Панель скачает файлы и все совместимые зависимости."), 1),
                    $ === "adguardhome" ? (f(), h("p", q1, "Установка не переключает DNS и DHCP.")) : x("", !0),
                    y.value.services?.some((ce) => ce.id === $) ? (f(), h("p", N1, "Обновление установленной службы доступно в списке сервисов, если найдена новая совместимая версия.")) : x("", !0)
                  ])
                ])), 64))
              ]),
              l("section", H1, [
                p[91] || (p[91] = l("h3", null, "Резерв версий на панели", -1)),
                l("label", L1, [
                  H(l("input", {
                    "onUpdate:modelValue": p[33] || (p[33] = ($) => I.value = $),
                    type: "checkbox"
                  }, null, 512), [
                    [je, I.value]
                  ]),
                  p[89] || (p[89] = M(" Хранить установочные комплекты резервно", -1))
                ]),
                p[92] || (p[92] = l("p", { class: "gw-hint" }, "Резерв позволяет устанавливать сервисы при недоступном GitHub. Скачивание не запускает установку или обновление на роутере.", -1)),
                l("div", j1, [
                  H(l("select", {
                    "onUpdate:modelValue": p[34] || (p[34] = ($) => E.value = $),
                    "aria-label": "Количество резервных версий"
                  }, [...p[90] || (p[90] = [
                    l("option", { value: 2 }, "2 последние совместимые версии", -1),
                    l("option", { value: 3 }, "3 последние совместимые версии", -1)
                  ])], 512), [
                    [xe, E.value]
                  ]),
                  l("button", {
                    disabled: g.value,
                    onClick: bi
                  }, "Сохранить настройки", 8, W1)
                ]),
                X.value ? (f(), h("p", B1, b(X.value), 1)) : x("", !0)
              ])
            ]),
            _: 1
          })) : x("", !0),
          t.value ? (f(), me(Tu, {
            key: 11,
            node: B.value,
            bridge: e.bridge,
            onClose: p[36] || (p[36] = ($) => t.value = !1),
            onInstall: p[37] || (p[37] = ($) => {
              t.value = !1, gs();
            }),
            onStart: p[38] || (p[38] = ($) => {
              t.value = !1, Xe("adguardhome", "start");
            })
          }, null, 8, ["node", "bridge"])) : x("", !0),
          R.value === "packages" ? (f(), me(Xf, {
            key: B.value.id,
            node: B.value,
            bridge: e.bridge,
            "initial-query": Z.value,
            onChanged: fe
          }, null, 8, ["node", "bridge", "initial-query"])) : x("", !0),
          R.value === "logs" ? (f(), h("div", K1, [
            l("div", G1, [
              p[94] || (p[94] = l("h3", null, "Системный журнал", -1)),
              l("button", {
                disabled: g.value,
                onClick: p[39] || (p[39] = ($) => qe("logs"))
              }, "Обновить", 8, z1)
            ]),
            l("pre", J1, b(ne.value || "Нет записей"), 1)
          ])) : x("", !0),
          R.value === "access" ? (f(), h("section", Y1, [
            B.value.ssh_configured && (B.value.managed || B.value.ssh_user === "root") ? (f(), h("div", X1, [
              B.value.managed ? (f(), h("p", Z1, "RPC-компоненты и интерфейс LuCI Bot4VPS")) : x("", !0),
              l("div", Q1, [
                B.value.managed ? (f(), h("button", {
                  key: 0,
                  type: "button",
                  disabled: g.value,
                  onClick: pi
                }, "Обновить интеграцию Bot4VPS", 8, eb)) : x("", !0),
                l("button", {
                  type: "button",
                  disabled: g.value || B.value.ssh_user !== "root",
                  onClick: $i
                }, b(Gt.value === !1 ? "Задать пароль root" : "Сменить пароль root"), 9, tb)
              ])
            ])) : x("", !0),
            B.value.bootstrap_state === "commit_pending" ? (f(), h("button", {
              key: 1,
              disabled: g.value,
              onClick: Rn
            }, "Завершить фиксацию подключения", 8, nb)) : x("", !0),
            l("header", lb, [
              p[95] || (p[95] = l("div", null, [
                l("h3", null, "Доступ к шлюзу"),
                l("p", { class: "gw-hint" }, "Данные API и SSH для подключения панели")
              ], -1)),
              l("button", {
                class: "gw-danger",
                disabled: g.value,
                onClick: xi
              }, b(B.value.deletion_pending ? "Повторить отзыв и удаление" : "Удалить шлюз"), 9, sb)
            ]),
            !B.value.ssh_configured || B.value.ssh_user !== "root" ? (f(), h("p", ob, "Для смены пароля роутера сохраните SSH-доступ под root.")) : x("", !0),
            X.value ? (f(), h("p", ib, b(X.value), 1)) : x("", !0),
            l("div", ab, [
              l("form", {
                class: "gw-form",
                onSubmit: tt(wi, ["prevent"])
              }, [
                p[102] || (p[102] = l("h4", null, "API OpenWrt", -1)),
                l("p", rb, [
                  p[96] || (p[96] = M("Управление секретом: ", -1)),
                  l("a", {
                    href: B.value.access_url,
                    target: "_blank",
                    rel: "noopener noreferrer"
                  }, "LuCI → Службы → Bot4VPS ↗", 8, ub)
                ]),
                l("label", null, [
                  p[97] || (p[97] = M("Имя шлюза", -1)),
                  H(l("input", {
                    "onUpdate:modelValue": p[40] || (p[40] = ($) => v.value.name = $),
                    placeholder: "Определится по модели роутера",
                    maxlength: "100"
                  }, null, 512), [
                    [re, v.value.name]
                  ])
                ]),
                l("label", null, [
                  p[98] || (p[98] = M("Адрес API", -1)),
                  H(l("input", {
                    "onUpdate:modelValue": p[41] || (p[41] = ($) => v.value.url = $),
                    required: ""
                  }, null, 512), [
                    [re, v.value.url]
                  ])
                ]),
                l("label", null, [
                  p[99] || (p[99] = M("Логин API", -1)),
                  H(l("input", {
                    "onUpdate:modelValue": p[42] || (p[42] = ($) => v.value.username = $),
                    required: ""
                  }, null, 512), [
                    [re, v.value.username]
                  ])
                ]),
                l("label", null, [
                  p[100] || (p[100] = M("Новый секрет", -1)),
                  Ae(vt, {
                    modelValue: v.value.password,
                    "onUpdate:modelValue": p[43] || (p[43] = ($) => v.value.password = $),
                    required: "",
                    autocomplete: "off"
                  }, null, 8, ["modelValue"])
                ]),
                l("label", null, [
                  p[101] || (p[101] = M("SHA-256 сертификата", -1)),
                  H(l("input", {
                    "onUpdate:modelValue": p[44] || (p[44] = ($) => v.value.tls_sha256 = $)
                  }, null, 512), [
                    [re, v.value.tls_sha256]
                  ])
                ]),
                l("div", db, [
                  l("button", {
                    class: "gw-primary",
                    disabled: g.value
                  }, "Проверить и сохранить API", 8, cb)
                ])
              ], 32),
              l("form", {
                class: "gw-form",
                onSubmit: tt(ki, ["prevent"])
              }, [
                p[110] || (p[110] = l("h4", null, "SSH для консоли", -1)),
                p[111] || (p[111] = l("p", { class: "gw-hint" }, "Пароль хранится зашифрованным мастер-ключом панели.", -1)),
                l("div", fb, [
                  l("label", null, [
                    p[103] || (p[103] = M("SSH-логин", -1)),
                    H(l("input", {
                      "onUpdate:modelValue": p[45] || (p[45] = ($) => _.value.user = $),
                      required: ""
                    }, null, 512), [
                      [re, _.value.user]
                    ])
                  ]),
                  l("label", null, [
                    p[104] || (p[104] = M("SSH-порт", -1)),
                    H(l("input", {
                      "onUpdate:modelValue": p[46] || (p[46] = ($) => _.value.port = $),
                      type: "number",
                      min: "1",
                      max: "65535",
                      required: ""
                    }, null, 512), [
                      [re, _.value.port]
                    ])
                  ])
                ]),
                l("label", null, [
                  p[107] || (p[107] = M("Авторизация", -1)),
                  H(l("select", {
                    "onUpdate:modelValue": p[47] || (p[47] = ($) => _.value.auth_type = $)
                  }, [
                    p[105] || (p[105] = l("option", { value: "password" }, "Пароль", -1)),
                    p[106] || (p[106] = l("option", { value: "key" }, "SSH-ключ панели", -1)),
                    l("option", {
                      value: "none",
                      disabled: _.value.user !== "root"
                    }, "Без пароля (первый вход root)", 8, pb)
                  ], 512), [
                    [xe, _.value.auth_type]
                  ])
                ]),
                _.value.auth_type === "password" ? (f(), h("label", vb, [
                  p[108] || (p[108] = M("SSH-пароль", -1)),
                  Ae(vt, {
                    modelValue: _.value.password,
                    "onUpdate:modelValue": p[48] || (p[48] = ($) => _.value.password = $),
                    autocomplete: "off",
                    placeholder: B.value.ssh_auth_type === "password" && B.value.ssh_configured ? "Оставьте пустым, чтобы сохранить текущий" : ""
                  }, null, 8, ["modelValue", "placeholder"])
                ])) : _.value.auth_type === "key" ? (f(), h("label", gb, [
                  p[109] || (p[109] = M("Путь к SSH-ключу", -1)),
                  H(l("input", {
                    "onUpdate:modelValue": p[49] || (p[49] = ($) => _.value.key_path = $),
                    placeholder: "/opt/bot4vps/keys/имя_ключа"
                  }, null, 512), [
                    [re, _.value.key_path]
                  ])
                ])) : x("", !0),
                l("div", hb, [
                  l("button", {
                    class: "gw-primary",
                    disabled: g.value
                  }, "Проверить и сохранить SSH", 8, mb)
                ])
              ], 32)
            ])
          ])) : x("", !0),
          R.value === "network" ? (f(), h(q, { key: 15 }, [
            k.value.length ? (f(), h("section", bb, [
              p[113] || (p[113] = l("h3", null, "WireGuard", -1)),
              (f(!0), h(q, null, oe(k.value, ($) => (f(), h("div", {
                key: $.name,
                class: "gw-panel"
              }, [
                l("h3", null, b($.name), 1),
                $.peers.length ? x("", !0) : (f(), h("p", yb, "Пиры не настроены")),
                (f(!0), h(q, null, oe($.peers, (ce, ye) => (f(), h("div", {
                  key: ye,
                  style: { "margin-top": "12px" }
                }, [
                  l("span", {
                    class: Te(["gw-status", ce.recent_handshake ? "good" : "warn"])
                  }, b(ce.recent_handshake ? "Недавний handshake" : "Нет недавнего handshake"), 3),
                  l("p", null, b(ce.endpoint === "(none)" ? "Endpoint не определён" : ce.endpoint) + " · ↓ " + b(F(ce.rx_bytes)) + " · ↑ " + b(F(ce.tx_bytes)), 1)
                ]))), 128)),
                p[112] || (p[112] = l("p", { class: "gw-hint" }, "Handshake показывает обмен ключами за последние 3 минуты. Простаивающий туннель может не обмениваться пакетами.", -1))
              ]))), 128))
            ])) : x("", !0)
          ], 64)) : x("", !0)
        ])) : x("", !0)
      ], 64)),
      j.value ? (f(), me(Re, {
        key: 6,
        title: "Удаление шлюза",
        busy: g.value,
        onClose: p[51] || (p[51] = ($) => j.value = null)
      }, {
        default: Ie(() => [
          l("h2", null, "Удалить " + b(j.value.name) + "?", 1),
          l("ol", null, [
            (f(!0), h(q, null, oe(j.value.steps, ($) => (f(), h("li", { key: $ }, b($), 1))), 128))
          ]),
          l("p", null, "Сохранятся: " + b(j.value.preserved.join(", ")) + ".", 1),
          j.value.manual ? (f(), h("p", wb, "Для вручную настроенного API может потребоваться отзыв учётной записи в LuCI. Без подтверждения отзыва панель сохранит запись.")) : x("", !0),
          l("div", _b, [
            l("button", {
              class: "gw-primary",
              disabled: g.value,
              onClick: Si
            }, "Да, отозвать доступ и удалить", 8, kb),
            l("button", {
              disabled: g.value,
              onClick: p[50] || (p[50] = ($) => j.value = null)
            }, "Отмена", 8, $b)
          ])
        ]),
        _: 1
      }, 8, ["busy"])) : x("", !0),
      le.value ? (f(), me(dm, {
        key: 7,
        operation: le.value,
        busy: g.value,
        error: m.value,
        onApply: mi,
        onCancel: hi
      }, null, 8, ["operation", "busy", "error"])) : x("", !0)
    ], 2));
  }
});
function xb(e, t, n = !1, o = null) {
  const s = su(Cb, { bridge: t, wizard: n, initialPlan: o });
  return s.mount(e), () => s.unmount();
}
export {
  xb as mount
};
