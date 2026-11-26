// @__NO_SIDE_EFFECTS__
function Bn(e) {
  const t = /* @__PURE__ */ Object.create(null);
  for (const l of e.split(",")) t[l] = 1;
  return (l) => l in t;
}
const ye = {}, Qt = [], Ct = () => {
}, Qs = () => !1, nn = (e) => e.charCodeAt(0) === 111 && e.charCodeAt(1) === 110 && // uppercase letter
(e.charCodeAt(2) > 122 || e.charCodeAt(2) < 97), sn = (e) => e.startsWith("onUpdate:"), De = Object.assign, Kn = (e, t) => {
  const l = e.indexOf(t);
  l > -1 && e.splice(l, 1);
}, Ui = Object.prototype.hasOwnProperty, be = (e, t) => Ui.call(e, t), ce = Array.isArray, jt = (e) => rl(e) === "[object Map]", Rt = (e) => rl(e) === "[object Set]", ms = (e) => rl(e) === "[object Date]", fe = (e) => typeof e == "function", Ae = (e) => typeof e == "string", ht = (e) => typeof e == "symbol", Se = (e) => e !== null && typeof e == "object", Zs = (e) => (Se(e) || fe(e)) && fe(e.then) && fe(e.catch), eo = Object.prototype.toString, rl = (e) => eo.call(e), Pi = (e) => rl(e).slice(8, -1), to = (e) => rl(e) === "[object Object]", Gn = (e) => Ae(e) && e !== "NaN" && e[0] !== "-" && "" + parseInt(e, 10) === e, ml = /* @__PURE__ */ Bn(
  // the leading comma is intentional so empty string "" is also included
  ",key,ref,ref_for,ref_key,onVnodeBeforeMount,onVnodeMounted,onVnodeBeforeUpdate,onVnodeUpdated,onVnodeBeforeUnmount,onVnodeUnmounted"
), Ai = 1e4, on = (e) => {
  let t = /* @__PURE__ */ Object.create(null), l = 0;
  return ((o) => {
    const s = t[o];
    return s !== void 0 ? s : (++l > Ai && (t = /* @__PURE__ */ Object.create(null), l = 1), t[o] = e(o));
  });
}, Ii = /-\w/g, at = /* @__PURE__ */ on((e) => e.replace(Ii, (t) => t.slice(1).toUpperCase())), Mi = /\B([A-Z])/g, Dt = /* @__PURE__ */ on(
  (e) => e.replace(Mi, "-$1").toLowerCase()
), lo = /* @__PURE__ */ on((e) => e.charAt(0).toUpperCase() + e.slice(1)), bn = /* @__PURE__ */ on((e) => e ? `on${lo(e)}` : ""), je = (e, t) => !Object.is(e, t), Bl = (e, ...t) => {
  for (let l = 0; l < e.length; l++)
    e[l](...t);
}, no = (e, t, l, o = !1) => {
  Object.defineProperty(e, t, {
    configurable: !0,
    enumerable: !1,
    writable: o,
    value: l
  });
}, Al = (e) => {
  const t = parseFloat(e);
  return isNaN(t) ? e : t;
};
let bs;
const an = () => bs || (bs = typeof globalThis < "u" ? globalThis : typeof self < "u" ? self : typeof window < "u" ? window : typeof global < "u" ? global : {});
function Cl(e) {
  if (ce(e)) {
    const t = {};
    for (let l = 0; l < e.length; l++) {
      const o = e[l], s = Ae(o) ? Ni(o) : Cl(o);
      if (s)
        for (const i in s)
          t[i] = s[i];
    }
    return t;
  } else if (Ae(e) || Se(e))
    return e;
}
const Oi = /;(?![^(]*\))/g, Ri = /:([^]+)/, Di = /"(?:[^"\\]|\\[^])*"|'(?:[^'\\]|\\[^])*'|\\[^]|\/\*[^]*?\*\//g;
function Ni(e) {
  const t = {};
  return e.replace(Di, (l) => l.startsWith("/*") ? "" : l).split(Oi).forEach((l) => {
    if (l) {
      const o = l.split(Ri);
      o.length > 1 && (t[o[0].trim()] = o[1].trim());
    }
  }), t;
}
function Ue(e) {
  let t = "";
  if (Ae(e))
    t = e;
  else if (ce(e))
    for (let l = 0; l < e.length; l++) {
      const o = Ue(e[l]);
      o && (t += o + " ");
    }
  else if (Se(e))
    for (const l in e)
      e[l] && (t += l + " ");
  return t.trim();
}
const qi = "itemscope,allowfullscreen,disablepictureinpicture,disableremoteplayback,formnovalidate,ismap,nomodule,novalidate,playsinline,readonly", Hi = /* @__PURE__ */ Bn(qi);
function so(e) {
  return !!e || e === "";
}
function Fi(e, t, l) {
  if (e.length !== t.length) return !1;
  let o = !0;
  for (let s = 0; o && s < e.length; s++)
    o = mt(e[s], t[s], l);
  return o;
}
function ys(e, t, l) {
  if (e.size !== t.size) return !1;
  const o = Array.from(t), s = new Uint8Array(o.length);
  for (const i of e) {
    let a = -1;
    for (let r = 0; r < o.length; r++)
      if (!s[r] && mt(i, o[r], l)) {
        a = r;
        break;
      }
    if (a < 0) return !1;
    s[a] = 1;
  }
  return !0;
}
function Li(e, t, l) {
  let o = jt(e), s = jt(t);
  if (o || s || (o = Rt(e), s = Rt(t), o || s))
    return o && s ? ys(e, t, l) : !1;
  const i = Object.keys(e).length, a = Object.keys(t).length;
  if (i !== a)
    return !1;
  for (const r in e) {
    const c = be(e, r), g = be(t, r);
    if (c && !g || !c && g || !mt(e[r], t[r], l))
      return !1;
  }
  return _s(e) === _s(t);
}
function ws(e, t, l, o) {
  l || (l = [/* @__PURE__ */ new Map(), /* @__PURE__ */ new Map()]);
  const [s, i] = l;
  if (s.has(e) || i.has(t))
    return s.get(e) === t && i.get(t) === e;
  s.set(e, t), i.set(t, e);
  const a = o(e, t, l);
  return s.delete(e), i.delete(t), a;
}
function mt(e, t, l) {
  if (e === t) return !0;
  let o = ms(e), s = ms(t);
  return o || s ? o && s ? e.getTime() === t.getTime() : !1 : (o = ht(e), s = ht(t), o || s ? e === t : (o = ce(e), s = ce(t), o || s ? o && s ? ws(e, t, l, Fi) : !1 : (o = Se(e), s = Se(t), o || s ? !o || !s ? !1 : ws(e, t, l, Li) : String(e) === String(t))));
}
function zn(e, t) {
  return e.findIndex((l) => mt(l, t));
}
function _s(e) {
  return Object.getPrototypeOf(e) === null && e[Symbol.toPrimitive] == null && typeof e.toString != "function" && typeof e.valueOf != "function" ? rl(e) : String(e);
}
const oo = (e) => !!(e && e.__v_isRef === !0), w = (e) => Ae(e) ? e : e == null ? "" : ce(e) || Se(e) && (e.toString === eo || !fe(e.toString)) ? oo(e) ? w(e.value) : JSON.stringify(e, io, 2) : String(e), io = (e, t) => oo(t) ? io(e, t.value) : jt(t) ? {
  [`Map(${t.size})`]: [...t.entries()].reduce(
    (l, [o, s], i) => (l[yn(o, i) + " =>"] = s, l),
    {}
  )
} : Rt(t) ? {
  [`Set(${t.size})`]: [...t.values()].map((l) => yn(l))
} : ht(t) ? yn(t) : Se(t) && !ce(t) && !to(t) ? String(t) : t, yn = (e, t = "") => {
  var l;
  return (
    // Symbol.description in es2019+ so we need to cast here to pass
    // the lib: es2016 check
    ht(e) ? `Symbol(${(l = e.description) != null ? l : t})` : e
  );
};
let Fe;
class ji {
  // TODO isolatedDeclarations "__v_skip"
  constructor(t = !1) {
    this.detached = t, this._active = !0, this._on = 0, this.effects = [], this.cleanups = [], this._isPaused = !1, this._warnOnRun = !0, this.__v_skip = !0, !t && Fe && (Fe.active ? (this.parent = Fe, this.index = (Fe.scopes || (Fe.scopes = [])).push(
      this
    ) - 1) : (this._active = !1, this._warnOnRun = !1));
  }
  get active() {
    return this._active;
  }
  pause() {
    if (this._active) {
      this._isPaused = !0;
      let t, l;
      if (this.scopes) {
        const o = this.scopes.slice();
        for (t = 0, l = o.length; t < l; t++)
          o[t].pause();
      }
      for (t = 0, l = this.effects.length; t < l; t++)
        this.effects[t].pause();
    }
  }
  /**
   * Resumes the effect scope, including all child scopes and effects.
   */
  resume() {
    if (this._active && this._isPaused) {
      this._isPaused = !1;
      let t, l;
      if (this.scopes) {
        const s = this.scopes.slice();
        for (t = 0, l = s.length; t < l; t++)
          s[t].resume();
      }
      const o = this.effects.slice();
      for (t = 0, l = o.length; t < l; t++)
        o[t].resume();
    }
  }
  run(t) {
    if (this._active) {
      const l = Fe;
      try {
        return Fe = this, t();
      } finally {
        Fe = l;
      }
    }
  }
  /**
   * This should only be called on non-detached scopes
   * @internal
   */
  on() {
    ++this._on === 1 && (this.prevScope = Fe, Fe = this);
  }
  /**
   * This should only be called on non-detached scopes
   * @internal
   */
  off() {
    if (this._on > 0 && --this._on === 0) {
      if (Fe === this)
        Fe = this.prevScope;
      else {
        let t = Fe;
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
      let l, o;
      for (l = 0, o = this.effects.length; l < o; l++)
        this.effects[l].stop();
      for (this.effects.length = 0, l = 0, o = this.cleanups.length; l < o; l++)
        this.cleanups[l]();
      if (this.cleanups.length = 0, this.scopes) {
        const s = this.scopes.slice();
        for (l = 0, o = s.length; l < o; l++)
          s[l].stop(!0);
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
function Wi() {
  return Fe;
}
let Te;
const wn = /* @__PURE__ */ new WeakSet();
class ao {
  constructor(t) {
    this.fn = t, this.deps = void 0, this.depsTail = void 0, this.flags = 5, this.next = void 0, this.cleanup = void 0, this.scheduler = void 0, Fe && (Fe.active ? Fe.effects.push(this) : this.flags &= -2);
  }
  pause() {
    this.flags |= 64;
  }
  resume() {
    this.flags & 64 && (this.flags &= -65, wn.has(this) && (wn.delete(this), this.trigger()));
  }
  /**
   * @internal
   */
  notify() {
    this.flags & 2 && !(this.flags & 32) || this.flags & 8 || uo(this);
  }
  run() {
    if (!(this.flags & 1))
      return this.fn();
    this.flags |= 2, ks(this), co(this);
    const t = Te, l = gt;
    Te = this, gt = !0;
    try {
      return this.fn();
    } finally {
      fo(this), Te = t, gt = l, this.flags &= -3;
    }
  }
  stop() {
    if (this.flags & 1) {
      for (let t = this.deps; t; t = t.nextDep)
        Xn(t);
      this.deps = this.depsTail = void 0, ks(this), this.onStop && this.onStop(), this.flags &= -2;
    }
  }
  trigger() {
    this.flags & 64 ? wn.add(this) : this.scheduler ? this.scheduler() : this.runIfDirty();
  }
  /**
   * @internal
   */
  runIfDirty() {
    An(this) && this.run();
  }
  get dirty() {
    return An(this);
  }
}
let ro = 0, bl, yl;
function uo(e, t = !1) {
  if (e.flags |= 8, t) {
    e.next = yl, yl = e;
    return;
  }
  e.next = bl, bl = e;
}
function Jn() {
  ro++;
}
function Yn() {
  if (--ro > 0)
    return;
  if (yl) {
    let t = yl;
    for (yl = void 0; t; ) {
      const l = t.next;
      t.next = void 0, t.flags &= -9, t = l;
    }
  }
  let e;
  for (; bl; ) {
    let t = bl;
    for (bl = void 0; t; ) {
      const l = t.next;
      if (t.next = void 0, t.flags &= -9, t.flags & 1)
        try {
          t.trigger();
        } catch (o) {
          e || (e = o);
        }
      t = l;
    }
  }
  if (e) throw e;
}
function co(e) {
  for (let t = e.deps; t; t = t.nextDep)
    t.version = -1, t.prevActiveLink = t.dep.activeLink, t.dep.activeLink = t;
}
function fo(e) {
  let t, l = e.depsTail, o = l;
  for (; o; ) {
    const s = o.prevDep;
    o.version === -1 ? (o === l && (l = s), Xn(o), Bi(o)) : t = o, o.dep.activeLink = o.prevActiveLink, o.prevActiveLink = void 0, o = s;
  }
  e.deps = t, e.depsTail = l;
}
function An(e) {
  for (let t = e.deps; t; t = t.nextDep)
    if (t.dep.version !== t.version || t.dep.computed && (po(t.dep.computed) || t.dep.version !== t.version))
      return !0;
  return !!e._dirty;
}
function po(e) {
  if (e.flags & 4 && !(e.flags & 16) || (e.flags &= -17, e.globalVersion === xl) || (e.globalVersion = xl, !e.isSSR && e.flags & 128 && (!e.deps && !e._dirty || !An(e))))
    return;
  e.flags |= 2;
  const t = e.dep, l = Te, o = gt;
  Te = e, gt = !0;
  try {
    co(e);
    const s = e.fn(e._value);
    (t.version === 0 || je(s, e._value)) && (e.flags |= 128, e._value = s, t.version++);
  } catch (s) {
    throw t.version++, s;
  } finally {
    Te = l, gt = o, fo(e), e.flags &= -3;
  }
}
function Xn(e, t = !1) {
  const { dep: l, prevSub: o, nextSub: s } = e;
  if (o && (o.nextSub = s, e.prevSub = void 0), s && (s.prevSub = o, e.nextSub = void 0), l.subs === e && (l.subs = o, !o && l.computed)) {
    l.computed.flags &= -5;
    for (let i = l.computed.deps; i; i = i.nextDep)
      Xn(i, !0);
  }
  !t && !--l.sc && l.map && l.map.delete(l.key);
}
function Bi(e) {
  const { prevDep: t, nextDep: l } = e;
  t && (t.nextDep = l, e.prevDep = void 0), l && (l.prevDep = t, e.nextDep = void 0);
}
let gt = !0;
const vo = [];
function xt() {
  vo.push(gt), gt = !1;
}
function St() {
  const e = vo.pop();
  gt = e === void 0 ? !0 : e;
}
function ks(e) {
  const { cleanup: t } = e;
  if (e.cleanup = void 0, t) {
    const l = Te;
    Te = void 0;
    try {
      t();
    } finally {
      Te = l;
    }
  }
}
let xl = 0;
class Ki {
  constructor(t, l) {
    this.sub = t, this.dep = l, this.version = l.version, this.nextDep = this.prevDep = this.nextSub = this.prevSub = this.prevActiveLink = void 0;
  }
}
class rn {
  // TODO isolatedDeclarations "__v_skip"
  constructor(t) {
    this.computed = t, this.version = 0, this.activeLink = void 0, this.subs = void 0, this.map = void 0, this.key = void 0, this.sc = 0, this.__v_skip = !0;
  }
  track(t) {
    if (!Te || !gt || Te === this.computed)
      return;
    let l = this.activeLink;
    if (l === void 0 || l.sub !== Te)
      l = this.activeLink = new Ki(Te, this), Te.deps ? (l.prevDep = Te.depsTail, Te.depsTail.nextDep = l, Te.depsTail = l) : Te.deps = Te.depsTail = l, go(l);
    else if (l.version === -1 && (l.version = this.version, l.nextDep)) {
      const o = l.nextDep;
      o.prevDep = l.prevDep, l.prevDep && (l.prevDep.nextDep = o), l.prevDep = Te.depsTail, l.nextDep = void 0, Te.depsTail.nextDep = l, Te.depsTail = l, Te.deps === l && (Te.deps = o);
    }
    return l;
  }
  trigger(t) {
    this.version++, xl++, this.notify(t);
  }
  notify(t) {
    Jn();
    try {
      for (let l = this.subs; l; l = l.prevSub)
        l.sub.notify() && l.sub.dep.notify();
    } finally {
      Yn();
    }
  }
}
function go(e) {
  if (e.dep.sc++, e.sub.flags & 4) {
    const t = e.dep.computed;
    if (t && !e.dep.subs) {
      t.flags |= 20;
      for (let o = t.deps; o; o = o.nextDep)
        go(o);
    }
    const l = e.dep.subs;
    l !== e && (e.prevSub = l, l && (l.nextSub = e)), e.dep.subs = e;
  }
}
const In = /* @__PURE__ */ new WeakMap(), Zt = /* @__PURE__ */ Symbol(
  ""
), Mn = /* @__PURE__ */ Symbol(
  ""
), Sl = /* @__PURE__ */ Symbol(
  ""
);
function Ke(e, t, l) {
  if (gt && Te) {
    let o = In.get(e);
    o || In.set(e, o = /* @__PURE__ */ new Map());
    let s = o.get(l);
    s || (o.set(l, s = new rn()), s.map = o, s.key = l), s.track();
  }
}
function At(e, t, l, o, s, i) {
  const a = In.get(e);
  if (!a) {
    xl++;
    return;
  }
  const r = (c) => {
    c && c.trigger();
  };
  if (Jn(), t === "clear")
    a.forEach(r);
  else {
    const c = ce(e), g = c && Gn(l);
    if (c && l === "length") {
      const m = Number(o);
      a.forEach((y, T) => {
        (T === "length" || T === Sl || !ht(T) && T >= m) && r(y);
      });
    } else
      switch ((l !== void 0 || a.has(void 0)) && r(a.get(l)), g && r(a.get(Sl)), t) {
        case "add":
          c ? g && r(a.get("length")) : (r(a.get(Zt)), jt(e) && r(a.get(Mn)));
          break;
        case "delete":
          c || (r(a.get(Zt)), jt(e) && r(a.get(Mn)));
          break;
        case "set":
          jt(e) && r(a.get(Zt));
          break;
      }
  }
  Yn();
}
function ll(e) {
  const t = /* @__PURE__ */ $e(e);
  return t === e || (Ke(t, "iterate", Sl), /* @__PURE__ */ rt(e)) ? t : /* @__PURE__ */ Vt(e) ? /* @__PURE__ */ Wt(e) ? t.map((l) => Bt(ut(l))) : t.map(Bt) : t.map(ut);
}
function un(e) {
  return Ke(e = /* @__PURE__ */ $e(e), "iterate", Sl), e;
}
function _t(e, t) {
  return /* @__PURE__ */ Vt(e) ? Bt(/* @__PURE__ */ Wt(e) ? ut(t) : t) : ut(t);
}
const Gi = {
  __proto__: null,
  [Symbol.iterator]() {
    return _n(this, Symbol.iterator, (e) => _t(this, e));
  },
  concat(...e) {
    return ll(this).concat(
      ...e.map((t) => ce(t) ? ll(t) : t)
    );
  },
  entries() {
    return _n(this, "entries", (e) => (e[1] = _t(this, e[1]), e));
  },
  every(e, t) {
    return Et(this, "every", e, t, void 0, arguments);
  },
  filter(e, t) {
    return Et(
      this,
      "filter",
      e,
      t,
      (l) => l.map((o) => _t(this, o)),
      arguments
    );
  },
  find(e, t) {
    return Et(
      this,
      "find",
      e,
      t,
      (l) => _t(this, l),
      arguments
    );
  },
  findIndex(e, t) {
    return Et(this, "findIndex", e, t, void 0, arguments);
  },
  findLast(e, t) {
    return Et(
      this,
      "findLast",
      e,
      t,
      (l) => _t(this, l),
      arguments
    );
  },
  findLastIndex(e, t) {
    return Et(this, "findLastIndex", e, t, void 0, arguments);
  },
  // flat, flatMap could benefit from ARRAY_ITERATE but are not straight-forward to implement
  forEach(e, t) {
    return Et(this, "forEach", e, t, void 0, arguments);
  },
  includes(...e) {
    return kn(this, "includes", e);
  },
  indexOf(...e) {
    return kn(this, "indexOf", e);
  },
  join(e) {
    return ll(this).join(e);
  },
  // keys() iterator only reads `length`, no optimization required
  lastIndexOf(...e) {
    return kn(this, "lastIndexOf", e);
  },
  map(e, t) {
    return Et(this, "map", e, t, void 0, arguments);
  },
  pop() {
    return cl(this, "pop");
  },
  push(...e) {
    return cl(this, "push", e);
  },
  reduce(e, ...t) {
    return Cs(this, "reduce", e, t);
  },
  reduceRight(e, ...t) {
    return Cs(this, "reduceRight", e, t);
  },
  shift() {
    return cl(this, "shift");
  },
  // slice could use ARRAY_ITERATE but also seems to beg for range tracking
  some(e, t) {
    return Et(this, "some", e, t, void 0, arguments);
  },
  splice(...e) {
    return cl(this, "splice", e);
  },
  toReversed() {
    return ll(this).toReversed();
  },
  toSorted(e) {
    return ll(this).toSorted(e);
  },
  toSpliced(...e) {
    return ll(this).toSpliced(...e);
  },
  unshift(...e) {
    return cl(this, "unshift", e);
  },
  values() {
    return _n(this, "values", (e) => _t(this, e));
  }
};
function _n(e, t, l) {
  const o = un(e), s = o[t], i = s.call(o);
  if (o !== e && !/* @__PURE__ */ rt(e)) {
    if (i[Symbol.toStringTag] === "Array Iterator") {
      const a = Object.create(Object.getPrototypeOf(i));
      return a.next = () => $s(i.next(), l), s !== ho[t] && Object.defineProperties(a, {
        return: {
          get() {
            const r = i.return;
            return typeof r == "function" ? r.bind(i) : r;
          }
        },
        throw: {
          get() {
            const r = i.throw;
            return typeof r == "function" ? r.bind(i) : r;
          }
        }
      }), a;
    }
    i._next = i.next, i.next = () => $s(i._next(), l);
  }
  return i;
}
function $s(e, t) {
  return e.done || (e.value = t(e.value)), e;
}
const ho = Array.prototype;
function Et(e, t, l, o, s, i) {
  const a = un(e), r = a !== e && !/* @__PURE__ */ rt(e), c = a[t];
  if (c !== ho[t]) {
    const y = c.apply(e, i);
    return r ? ut(y) : y;
  }
  let g = l;
  a !== e && (r ? g = function(y, T) {
    return l.call(this, _t(e, y), T, e);
  } : l.length > 2 && (g = function(y, T) {
    return l.call(this, y, T, e);
  }));
  const m = c.call(a, g, o);
  return r && s ? s(m) : m;
}
function Cs(e, t, l, o) {
  const s = un(e), i = s !== e && !/* @__PURE__ */ rt(e);
  let a = l, r = !1;
  s !== e && (i ? (r = o.length === 0, a = function(g, m, y) {
    return r && (r = !1, g = _t(e, g)), l.call(this, g, _t(e, m), y, e);
  }) : l.length > 3 && (a = function(g, m, y) {
    return l.call(this, g, m, y, e);
  }));
  const c = s[t](a, ...o);
  return r ? _t(e, c) : c;
}
function kn(e, t, l) {
  const o = /* @__PURE__ */ $e(e);
  Ke(o, "iterate", Sl);
  const s = o[t](...l);
  return (s === -1 || s === !1) && /* @__PURE__ */ ts(l[0]) ? (l[0] = /* @__PURE__ */ $e(l[0]), o[t](...l)) : s;
}
function cl(e, t, l = []) {
  xt(), Jn();
  const o = (/* @__PURE__ */ $e(e))[t].apply(e, l);
  return Yn(), St(), o;
}
const zi = /* @__PURE__ */ Bn("__proto__,__v_isRef,__isVue"), mo = /* @__PURE__ */ new Set(
  /* @__PURE__ */ Object.getOwnPropertyNames(Symbol).filter((e) => e !== "arguments" && e !== "caller").map((e) => Symbol[e]).filter(ht)
);
function Ji(e) {
  ht(e) || (e = String(e));
  const t = /* @__PURE__ */ $e(this);
  return Ke(t, "has", e), t.hasOwnProperty(e);
}
class bo {
  constructor(t = !1, l = !1) {
    this._isReadonly = t, this._isShallow = l;
  }
  get(t, l, o) {
    if (l === "__v_skip") return t.__v_skip;
    const s = this._isReadonly, i = this._isShallow;
    if (l === "__v_isReactive")
      return !s;
    if (l === "__v_isReadonly")
      return s;
    if (l === "__v_isShallow")
      return i;
    if (l === "__v_raw")
      return o === (s ? i ? oa : ko : i ? _o : wo).get(t) || // receiver is not the reactive proxy, but has the same prototype
      // this means the receiver is a user proxy of the reactive proxy
      Object.getPrototypeOf(t) === Object.getPrototypeOf(o) ? t : void 0;
    const a = ce(t);
    if (!s) {
      let c;
      if (a && (c = Gi[l]))
        return c;
      if (l === "hasOwnProperty")
        return Ji;
    }
    const r = Reflect.get(
      t,
      l,
      // if this is a proxy wrapping a ref, return methods using the raw ref
      // as receiver so that we don't have to call `toRaw` on the ref in all
      // its class methods
      /* @__PURE__ */ ze(t) ? t : o
    );
    if ((ht(l) ? mo.has(l) : zi(l)) || (s || Ke(t, "get", l), i))
      return r;
    if (/* @__PURE__ */ ze(r)) {
      const c = a && Gn(l) ? r : r.value;
      return s && Se(c) ? /* @__PURE__ */ Rn(c) : c;
    }
    return Se(r) ? s ? /* @__PURE__ */ Rn(r) : /* @__PURE__ */ Zn(r) : r;
  }
}
class yo extends bo {
  constructor(t = !1) {
    super(!1, t);
  }
  set(t, l, o, s) {
    let i = t[l];
    const a = ce(t) && Gn(l);
    if (!this._isShallow) {
      const g = /* @__PURE__ */ Vt(i);
      if (!/* @__PURE__ */ rt(o) && !/* @__PURE__ */ Vt(o) && (i = /* @__PURE__ */ $e(i), o = /* @__PURE__ */ $e(o)), !a && /* @__PURE__ */ ze(i) && !/* @__PURE__ */ ze(o))
        return g || (i.value = o), !0;
    }
    const r = a ? Number(l) < t.length : be(t, l), c = Reflect.set(
      t,
      l,
      o,
      /* @__PURE__ */ ze(t) ? t : s
    );
    return t === /* @__PURE__ */ $e(s) && c && (r ? je(o, i) && At(t, "set", l, o) : At(t, "add", l, o)), c;
  }
  deleteProperty(t, l) {
    const o = be(t, l);
    t[l];
    const s = Reflect.deleteProperty(t, l);
    return s && o && At(t, "delete", l, void 0), s;
  }
  has(t, l) {
    const o = Reflect.has(t, l);
    return (!ht(l) || !mo.has(l)) && Ke(t, "has", l), o;
  }
  ownKeys(t) {
    return Ke(
      t,
      "iterate",
      ce(t) ? "length" : Zt
    ), Reflect.ownKeys(t);
  }
}
class Yi extends bo {
  constructor(t = !1) {
    super(!0, t);
  }
  set(t, l) {
    return !0;
  }
  deleteProperty(t, l) {
    return !0;
  }
}
const Xi = /* @__PURE__ */ new yo(), Qi = /* @__PURE__ */ new Yi(), Zi = /* @__PURE__ */ new yo(!0);
const On = (e) => e, Rl = (e) => Reflect.getPrototypeOf(e);
function ea(e, t, l) {
  return function(...o) {
    const s = this.__v_raw, i = /* @__PURE__ */ $e(s), a = jt(i), r = e === "entries" || e === Symbol.iterator && a, c = e === "keys" && a, g = s[e](...o), m = l ? On : t ? Bt : ut;
    return !t && Ke(
      i,
      "iterate",
      c ? Mn : Zt
    ), De(
      // inheriting all iterator properties
      Object.create(g),
      {
        // iterator protocol
        next() {
          const { value: y, done: T } = g.next();
          return T ? { value: y, done: T } : {
            value: r ? [m(y[0]), m(y[1])] : m(y),
            done: T
          };
        }
      }
    );
  };
}
function Dl(e) {
  return function(...t) {
    return e === "delete" ? !1 : e === "clear" ? void 0 : this;
  };
}
function ta(e, t) {
  const l = {
    get(s) {
      const i = this.__v_raw, a = /* @__PURE__ */ $e(i), r = /* @__PURE__ */ $e(s);
      e || (je(s, r) && Ke(a, "get", s), Ke(a, "get", r));
      const { has: c } = Rl(a), g = t ? On : e ? Bt : ut;
      if (c.call(a, s))
        return g(i.get(s));
      if (c.call(a, r))
        return g(i.get(r));
      i !== a && i.get(s);
    },
    get size() {
      const s = this.__v_raw;
      return !e && Ke(/* @__PURE__ */ $e(s), "iterate", Zt), s.size;
    },
    has(s) {
      const i = this.__v_raw, a = /* @__PURE__ */ $e(i), r = /* @__PURE__ */ $e(s);
      return e || (je(s, r) && Ke(a, "has", s), Ke(a, "has", r)), s === r ? i.has(s) : i.has(s) || i.has(r);
    },
    forEach(s, i) {
      const a = this, r = a.__v_raw, c = /* @__PURE__ */ $e(r), g = t ? On : e ? Bt : ut;
      return !e && Ke(c, "iterate", Zt), r.forEach((m, y) => s.call(i, g(m), g(y), a));
    }
  };
  return De(
    l,
    e ? {
      add: Dl("add"),
      set: Dl("set"),
      delete: Dl("delete"),
      clear: Dl("clear")
    } : {
      add(s) {
        const i = /* @__PURE__ */ $e(this), a = Rl(i), r = /* @__PURE__ */ $e(s), c = !t && !/* @__PURE__ */ rt(s) && !/* @__PURE__ */ Vt(s) ? r : s;
        return a.has.call(i, c) || je(s, c) && a.has.call(i, s) || je(r, c) && a.has.call(i, r) || (i.add(c), At(i, "add", c, c)), this;
      },
      set(s, i) {
        !t && !/* @__PURE__ */ rt(i) && !/* @__PURE__ */ Vt(i) && (i = /* @__PURE__ */ $e(i));
        const a = /* @__PURE__ */ $e(this), { has: r, get: c } = Rl(a);
        let g = r.call(a, s);
        g || (s = /* @__PURE__ */ $e(s), g = r.call(a, s));
        const m = c.call(a, s);
        return a.set(s, i), g ? je(i, m) && At(a, "set", s, i) : At(a, "add", s, i), this;
      },
      delete(s) {
        const i = /* @__PURE__ */ $e(this), { has: a, get: r } = Rl(i);
        let c = a.call(i, s);
        c || (s = /* @__PURE__ */ $e(s), c = a.call(i, s)), r && r.call(i, s);
        const g = i.delete(s);
        return c && At(i, "delete", s, void 0), g;
      },
      clear() {
        const s = /* @__PURE__ */ $e(this), i = s.size !== 0, a = s.clear();
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
    l[s] = ea(s, e, t);
  }), l;
}
function Qn(e, t) {
  const l = ta(e, t);
  return (o, s, i) => s === "__v_isReactive" ? !e : s === "__v_isReadonly" ? e : s === "__v_isShallow" ? t : s === "__v_raw" ? o : Reflect.get(
    be(l, s) && s in o ? l : o,
    s,
    i
  );
}
const la = {
  get: /* @__PURE__ */ Qn(!1, !1)
}, na = {
  get: /* @__PURE__ */ Qn(!1, !0)
}, sa = {
  get: /* @__PURE__ */ Qn(!0, !1)
};
const wo = /* @__PURE__ */ new WeakMap(), _o = /* @__PURE__ */ new WeakMap(), ko = /* @__PURE__ */ new WeakMap(), oa = /* @__PURE__ */ new WeakMap();
function ia(e) {
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
function Zn(e) {
  return /* @__PURE__ */ Vt(e) ? e : es(
    e,
    !1,
    Xi,
    la,
    wo
  );
}
// @__NO_SIDE_EFFECTS__
function aa(e) {
  return es(
    e,
    !1,
    Zi,
    na,
    _o
  );
}
// @__NO_SIDE_EFFECTS__
function Rn(e) {
  return es(
    e,
    !0,
    Qi,
    sa,
    ko
  );
}
function es(e, t, l, o, s) {
  if (!Se(e) || e.__v_raw && !(t && e.__v_isReactive) || e.__v_skip || !Object.isExtensible(e))
    return e;
  const i = s.get(e);
  if (i)
    return i;
  const a = ia(Pi(e));
  if (a === 0)
    return e;
  const r = new Proxy(
    e,
    a === 2 ? o : l
  );
  return s.set(e, r), r;
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
function rt(e) {
  return !!(e && e.__v_isShallow);
}
// @__NO_SIDE_EFFECTS__
function ts(e) {
  return e ? !!e.__v_raw : !1;
}
// @__NO_SIDE_EFFECTS__
function $e(e) {
  const t = e && e.__v_raw;
  return t ? /* @__PURE__ */ $e(t) : e;
}
function ra(e) {
  return !be(e, "__v_skip") && Object.isExtensible(e) && no(e, "__v_skip", !0), e;
}
const ut = (e) => Se(e) ? /* @__PURE__ */ Zn(e) : e, Bt = (e) => Se(e) ? /* @__PURE__ */ Rn(e) : e;
// @__NO_SIDE_EFFECTS__
function ze(e) {
  return e ? e.__v_isRef === !0 : !1;
}
// @__NO_SIDE_EFFECTS__
function H(e) {
  return ua(e, !1);
}
function ua(e, t) {
  return /* @__PURE__ */ ze(e) ? e : new da(e, t);
}
class da {
  constructor(t, l) {
    this.dep = new rn(), this.__v_isRef = !0, this.__v_isShallow = !1, this._rawValue = l ? t : /* @__PURE__ */ $e(t), this._value = l ? t : ut(t), this.__v_isShallow = l;
  }
  get value() {
    return this.dep.track(), this._value;
  }
  set value(t) {
    const l = this._rawValue, o = this.__v_isShallow || /* @__PURE__ */ rt(t) || /* @__PURE__ */ Vt(t);
    t = o ? t : /* @__PURE__ */ $e(t), je(t, l) && (this._rawValue = t, this._value = o ? t : ut(t), this.dep.trigger());
  }
}
function ca(e) {
  return /* @__PURE__ */ ze(e) ? e.value : e;
}
const fa = {
  get: (e, t, l) => t === "__v_raw" ? e : ca(Reflect.get(e, t, l)),
  set: (e, t, l, o) => {
    const s = e[t];
    return /* @__PURE__ */ ze(s) && !/* @__PURE__ */ ze(l) ? (s.value = l, !0) : Reflect.set(e, t, l, o);
  }
};
function $o(e) {
  return /* @__PURE__ */ Wt(e) ? e : new Proxy(e, fa);
}
class pa {
  constructor(t) {
    this.__v_isRef = !0, this._value = void 0;
    const l = this.dep = new rn(), { get: o, set: s } = t(l.track.bind(l), l.trigger.bind(l));
    this._get = o, this._set = s;
  }
  get value() {
    return this._value = this._get();
  }
  set value(t) {
    this._set(t);
  }
}
function va(e) {
  return new pa(e);
}
class ga {
  constructor(t, l, o) {
    this.fn = t, this.setter = l, this._value = void 0, this.dep = new rn(this), this.__v_isRef = !0, this.deps = void 0, this.depsTail = void 0, this.flags = 16, this.globalVersion = xl - 1, this.next = void 0, this.effect = this, this.__v_isReadonly = !l, this.isSSR = o;
  }
  /**
   * @internal
   */
  notify() {
    if (this.flags |= 16, !(this.flags & 8) && // avoid infinite self recursion
    Te !== this)
      return uo(this, !0), !0;
  }
  get value() {
    const t = this.dep.track();
    return po(this), t && (t.version = this.dep.version), this._value;
  }
  set value(t) {
    this.setter && this.setter(t);
  }
}
// @__NO_SIDE_EFFECTS__
function ha(e, t, l = !1) {
  let o, s;
  return fe(e) ? o = e : (o = e.get, s = e.set), new ga(o, s, l);
}
const Nl = {}, zl = /* @__PURE__ */ new WeakMap();
let Yt;
function ma(e, t = !1, l = Yt) {
  if (l) {
    let o = zl.get(l);
    o || zl.set(l, o = []), o.push(e);
  }
}
function ba(e, t, l = ye) {
  const { immediate: o, deep: s, once: i, scheduler: a, augmentJob: r, call: c } = l, g = (j) => s ? j : /* @__PURE__ */ rt(j) || s === !1 || s === 0 ? It(j, 1) : It(j);
  let m, y, T, E, B = !1, I = !1;
  if (/* @__PURE__ */ ze(e) ? (y = () => e.value, B = /* @__PURE__ */ rt(e)) : /* @__PURE__ */ Wt(e) ? (y = () => g(e), B = !0) : ce(e) ? (I = !0, B = e.some((j) => /* @__PURE__ */ Wt(j) || /* @__PURE__ */ rt(j)), y = () => e.map((j) => {
    if (/* @__PURE__ */ ze(j))
      return j.value;
    if (/* @__PURE__ */ Wt(j))
      return g(j);
    if (fe(j))
      return c ? c(j, 2) : j();
  })) : fe(e) ? t ? y = c ? () => c(e, 2) : e : y = () => {
    if (T) {
      xt();
      try {
        T();
      } finally {
        St();
      }
    }
    const j = Yt;
    Yt = m;
    try {
      return c ? c(e, 3, [E]) : e(E);
    } finally {
      Yt = j;
    }
  } : y = Ct, t && s) {
    const j = y, te = s === !0 ? 1 / 0 : s;
    y = () => It(j(), te);
  }
  const Q = Wi(), X = () => {
    m.stop(), Q && Q.active && Kn(Q.effects, m);
  };
  if (i && t) {
    const j = t;
    t = (...te) => {
      try {
        return j(...te);
      } finally {
        X();
      }
    };
  }
  let Z = I ? new Array(e.length).fill(Nl) : Nl;
  const le = (j) => {
    if (!(!(m.flags & 1) || !m.dirty && !j))
      if (t) {
        const te = m.run();
        if (j || s || B || (I ? te.some((O, S) => je(O, Z[S])) : je(te, Z))) {
          const O = Yt;
          xt();
          try {
            T && T(), Yt = m;
            const S = [
              te,
              // pass undefined as the old value when it's changed for the first time
              Z === Nl ? void 0 : I && Z[0] === Nl ? [] : Z,
              E
            ];
            Z = te, c ? c(t, 3, S) : (
              // @ts-expect-error
              t(...S)
            );
          } finally {
            Yt = O, St();
          }
        }
      } else
        m.run();
  };
  return r && r(le), m = new ao(y), m.scheduler = a ? () => a(le, !1) : le, E = (j) => ma(j, !1, m), T = m.onStop = () => {
    const j = zl.get(m);
    if (j) {
      if (c)
        c(j, 4);
      else
        for (const te of j) te();
      zl.delete(m);
    }
  }, t ? o ? le(!0) : Z = m.run() : a ? a(le.bind(null, !0), !0) : m.run(), X.pause = m.pause.bind(m), X.resume = m.resume.bind(m), X.stop = X, X;
}
function It(e, t = 1 / 0, l) {
  if (t <= 0 || !Se(e) || e.__v_skip || (l = l || /* @__PURE__ */ new Map(), (l.get(e) || 0) >= t))
    return e;
  if (l.set(e, t), t--, /* @__PURE__ */ ze(e))
    It(e.value, t, l);
  else if (ce(e))
    for (let o = 0; o < e.length; o++)
      It(e[o], t, l);
  else if (Rt(e) || jt(e))
    e.forEach((o) => {
      It(o, t, l);
    });
  else if (to(e)) {
    for (const o in e)
      It(e[o], t, l);
    for (const o of Object.getOwnPropertySymbols(e))
      Object.prototype.propertyIsEnumerable.call(e, o) && It(e[o], t, l);
  }
  return e;
}
function Il(e, t, l, o) {
  try {
    return o ? e(...o) : e();
  } catch (s) {
    dn(s, t, l);
  }
}
function bt(e, t, l, o) {
  if (fe(e)) {
    const s = Il(e, t, l, o);
    return s && Zs(s) && s.catch((i) => {
      dn(i, t, l, void 0, !0);
    }), s;
  }
  if (ce(e)) {
    const s = [];
    for (let i = 0; i < e.length; i++)
      s.push(bt(e[i], t, l, o));
    return s;
  }
}
function dn(e, t, l, o = !0, s = !1) {
  const i = t ? t.vnode : null, { errorHandler: a, throwUnhandledErrorInProduction: r } = t && t.appContext.config || ye;
  if (t) {
    let c = t.parent;
    const g = t.proxy, m = `https://vuejs.org/error-reference/#runtime-${l}`;
    for (; c; ) {
      const y = c.ec;
      if (y && !c.isUnmounted && // Async failures may outlive stopped scopes whose unmount effects
      // are deferred or discarded by Suspense.
      (!s || c.scope.active)) {
        for (let T = 0; T < y.length; T++)
          if (y[T](e, g, m) === !1)
            return;
      }
      c = c.parent;
    }
    if (a) {
      xt(), Il(a, null, 10, [
        e,
        g,
        m
      ]), St();
      return;
    }
  }
  ya(e, l, i, o, r);
}
function ya(e, t, l, o = !0, s = !1) {
  if (s)
    throw e;
  console.error(e);
}
const Ye = [];
let pt = -1;
const kt = [];
let Lt = null, nl = 0;
const Co = /* @__PURE__ */ Promise.resolve();
let Jl = null;
function ls(e) {
  const t = Jl || Co;
  return e ? t.then(this ? e.bind(this) : e) : t;
}
function wa(e) {
  let t = pt + 1, l = Ye.length;
  for (; t < l; ) {
    const o = t + l >>> 1, s = Ye[o], i = Vl(s);
    i < e || i === e && s.flags & 2 ? t = o + 1 : l = o;
  }
  return t;
}
function ns(e) {
  if (!(e.flags & 1)) {
    const t = Vl(e), l = Ye[Ye.length - 1];
    !l || // fast path when the job id is larger than the tail
    !(e.flags & 2) && t >= Vl(l) ? Ye.push(e) : Ye.splice(wa(t), 0, e), e.flags |= 1, xo();
  }
}
function xo() {
  Jl || (Jl = Co.then(To));
}
function _a(e) {
  if (!ce(e))
    Lt && e.id === -1 ? Lt.splice(nl + 1, 0, e) : e.flags & 1 || (kt.push(e), e.flags |= 1);
  else
    for (let t = 0; t < e.length; t++)
      kt.push(e[t]);
  xo();
}
function So(e, t, l, o = pt + 1) {
  for (; o < Ye.length; o++) {
    const s = Ye[o];
    if (s && s.flags & 2) {
      if (e && s.id !== e.uid || t !== void 0 && !(s.id >= t))
        continue;
      Ye.splice(o, 1), o = e ? o - 1 : pt, s.flags & 4 && (s.flags &= -2), s(), s.flags & 4 || (s.flags &= -2);
    }
  }
}
function Vo(e, t, l = 0) {
  if (kt.length) {
    let o = kt, s = 0;
    if (t) {
      o = [];
      for (let a = 0; a < kt.length; a++) {
        const r = kt[a];
        (r.i !== void 0 ? !r.i || r.i.uid < l : t.has(r)) ? kt[s++] = r : o.push(r);
      }
    }
    const i = [...new Set(o)].sort((a, r) => Vl(a) - Vl(r));
    if (kt.length = s, Lt) {
      for (let a = 0; a < i.length; a++)
        Lt.push(i[a]);
      return;
    }
    for (Lt = i, nl = 0; nl < Lt.length; nl++) {
      const a = Lt[nl];
      a.flags & 4 && (a.flags &= -2), a.flags & 8 || a(), a.flags &= -2;
    }
    Lt = null, nl = 0;
  }
}
let $n = !1;
function ka(e, t) {
  if ($n) {
    e();
    return;
  }
  const l = t === void 0 ? void 0 : new Set(kt);
  e(), $n = !0;
  try {
    So(void 0, t), Vo(void 0, l, t);
  } finally {
    $n = !1;
  }
}
const Vl = (e) => e.id == null ? e.flags & 2 ? -1 : 1 / 0 : e.id;
function To(e) {
  try {
    for (pt = 0; pt < Ye.length; pt++) {
      const t = Ye[pt];
      t && !(t.flags & 8) && (t.flags & 4 && (t.flags &= -2), Il(
        t,
        t.i,
        t.i ? 15 : 14
      ), t.flags & 4 || (t.flags &= -2));
    }
  } finally {
    for (; pt < Ye.length; pt++) {
      const t = Ye[pt];
      t && (t.flags &= -2);
    }
    pt = -1, Ye.length = 0, Vo(), Jl = null, (Ye.length || kt.length) && To();
  }
}
let Ge = null, Eo = null;
function Yl(e) {
  const t = Ge;
  return Ge = e, Eo = e && e.type.__scopeId || null, t;
}
function Re(e, t = Ge, l) {
  if (!t || e._n)
    return e;
  const o = (...s) => {
    o._d && Ds(-1);
    const i = Yl(t), a = Ot.length;
    let r;
    try {
      r = e(...s);
    } finally {
      for (let c = Ot.length; c > a; c--) us();
      Yl(i), o._d && Ds(1);
    }
    return r;
  };
  return o._n = !0, o._c = !0, o._d = !0, o;
}
function F(e, t) {
  if (Ge === null)
    return e;
  const l = gn(Ge), o = e.dirs || (e.dirs = []);
  for (let s = 0; s < t.length; s++) {
    let [i, a, r, c = ye] = t[s];
    i && (fe(i) && (i = {
      mounted: i,
      updated: i
    }), i.deep && It(a), o.push({
      dir: i,
      instance: l,
      value: a,
      oldValue: void 0,
      arg: r,
      modifiers: c
    }));
  }
  return e;
}
function zt(e, t, l, o) {
  let s = e;
  if (o === "beforeMount")
    e._mount = e;
  else if (o === "beforeUpdate") {
    const r = t && t._mount;
    r && (r._latest = e, e._mount = r);
  } else if (o === "mounted") {
    const r = e._latest;
    e._mount = e._latest = void 0, r && (s = r, r._mount = void 0);
  }
  const i = s.dirs, a = t && t.dirs;
  for (let r = 0; r < i.length; r++) {
    let c = i[r];
    a ? c.oldValue = a[r].value : o === "mounted" && c.oldValue !== void 0 && (c = De({}, c, { oldValue: void 0 }));
    let g = c.dir[o];
    g && (xt(), bt(g, l, 8, [
      e.el,
      c,
      s,
      t
    ]), St());
  }
}
function $a(e, t) {
  if (Qe) {
    let l = Qe.provides;
    const o = Qe.parent && Qe.parent.provides;
    o === l && (l = Qe.provides = Object.create(o)), l[e] = t;
  }
}
function Kl(e, t, l = !1) {
  const o = si();
  if (o || ol) {
    let s = ol ? ol._context.provides : o ? o.parent == null || o.ce ? o.vnode.appContext && o.vnode.appContext.provides : o.parent.provides : void 0;
    if (s && e in s)
      return s[e];
    if (arguments.length > 1)
      return l && fe(t) ? t.call(o && o.proxy) : t;
  }
}
const Ca = /* @__PURE__ */ Symbol.for("v-scx"), xa = () => Kl(Ca);
function Sa(e, t) {
  return ss(
    e,
    null,
    { flush: "sync" }
  );
}
function Xe(e, t, l) {
  return ss(e, t, l);
}
function ss(e, t, l = ye) {
  const { immediate: o, deep: s, flush: i, once: a } = l, r = De({}, l), c = t && o || !t && i !== "post";
  let g;
  if (Pl) {
    if (i === "sync") {
      const E = xa();
      g = E.__watcherHandles || (E.__watcherHandles = []);
    } else if (!c) {
      const E = () => {
      };
      return E.stop = Ct, E.resume = Ct, E.pause = Ct, E;
    }
  }
  const m = Qe;
  r.call = (E, B, I) => bt(E, m, B, I);
  let y = !1;
  i === "post" ? r.scheduler = (E) => {
    E.i = m, Be(E, m && m.suspense);
  } : i !== "sync" && (y = !0, r.scheduler = (E, B) => {
    B ? E() : ns(E);
  }), r.augmentJob = (E) => {
    t && (E.flags |= 4), y && (E.flags |= 2, m && (E.id = m.uid, E.i = m));
  };
  const T = ba(e, t, r);
  return Pl && (g ? g.push(T) : c && T()), T;
}
function Va(e, t, l) {
  const o = this.proxy, s = Ae(e) ? e.includes(".") ? Uo(o, e) : () => o[e] : e.bind(o, o);
  let i;
  fe(t) ? i = t : (i = t.handler, l = t);
  const a = Ml(this), r = ss(s, i.bind(o), l);
  return a(), r;
}
function Uo(e, t) {
  const l = t.split(".");
  return () => {
    let o = e;
    for (let s = 0; s < l.length && o; s++)
      o = o[l[s]];
    return o;
  };
}
const Ft = /* @__PURE__ */ new WeakMap(), Po = /* @__PURE__ */ Symbol("_vte"), cn = (e) => e.__isTeleport, Xt = (e) => e && (e.disabled || e.disabled === ""), Ta = (e) => e && (e.defer || e.defer === ""), xs = (e) => typeof SVGElement < "u" && e instanceof SVGElement, Ss = (e) => typeof MathMLElement == "function" && e instanceof MathMLElement, Dn = (e, t) => {
  const l = e && e.to;
  return Ae(l) ? t ? t(l) : null : l;
}, Ea = {
  name: "Teleport",
  __isTeleport: !0,
  process(e, t, l, o, s, i, a, r, c, g) {
    const {
      mc: m,
      pc: y,
      pbc: T,
      o: { insert: E, querySelector: B, createText: I, createComment: Q, parentNode: X }
    } = g, Z = Xt(t.props);
    let { dynamicChildren: le } = t;
    const j = (S, k, R) => {
      S.shapeFlag & 16 && m(
        S.children,
        k,
        R,
        s,
        i,
        a,
        r,
        c
      );
    }, te = (S = t) => {
      const k = Xt(S.props), R = S.target = Dn(S.props, B), z = Nn(R, S, I, E);
      R && (a !== "svg" && xs(R) ? a = "svg" : a !== "mathml" && Ss(R) && (a = "mathml"), s && s.isCE && (s.ce._teleportTargets || (s.ce._teleportTargets = /* @__PURE__ */ new Set())).add(R), k || (j(S, R, z), vl(S, !1)));
    }, O = (S) => {
      const k = () => {
        if (Ft.get(S) === k) {
          if (Ft.delete(S), Xt(S.props)) {
            const R = X(S.el) || l;
            j(S, R, S.anchor), vl(S, !0);
          }
          te(S);
        }
      };
      Ft.set(S, k), Be(k, i);
    };
    if (e == null) {
      const S = t.el = I(""), k = t.anchor = I("");
      if (E(S, l, o), E(k, l, o), Ta(t.props) || i && i.pendingBranch) {
        O(t);
        return;
      }
      Z && (j(t, l, k), vl(t, !0)), te();
    } else {
      t.el = e.el;
      const S = t.anchor = e.anchor, k = Ft.get(e);
      if (k) {
        k.flags |= 8, Ft.delete(e), O(t);
        return;
      }
      t.targetStart = e.targetStart;
      const R = t.target = e.target, z = t.targetAnchor = e.targetAnchor, pe = Xt(e.props), he = pe ? l : R, Pe = pe ? S : z;
      if (a === "svg" || xs(R) ? a = "svg" : (a === "mathml" || Ss(R)) && (a = "mathml"), le ? (T(
        e.dynamicChildren,
        le,
        he,
        s,
        i,
        a,
        r
      ), rs(e, t, !0)) : c || y(
        e,
        t,
        he,
        Pe,
        s,
        i,
        a,
        r,
        !1
      ), Z)
        pe ? t.props && e.props && t.props.to !== e.props.to && (t.props.to = e.props.to) : ql(
          t,
          l,
          S,
          g,
          1
        );
      else if ((t.props && t.props.to) !== (e.props && e.props.to)) {
        const Me = Dn(t.props, B);
        Me && (t.target = Me, ql(
          t,
          Me,
          null,
          g,
          0
        ));
      } else pe && ql(
        t,
        R,
        z,
        g,
        1
      );
      vl(t, Z);
    }
  },
  remove(e, t, l, { um: o, o: { remove: s } }, i) {
    const {
      shapeFlag: a,
      children: r,
      anchor: c,
      targetStart: g,
      targetAnchor: m,
      target: y,
      props: T
    } = e, E = Xt(T), B = i || !E, I = Ft.get(e);
    if (I && (I.flags |= 8, Ft.delete(e)), y && (s(g), s(m)), i && s(c), !I && (E || y) && a & 16)
      for (let Q = 0; Q < r.length; Q++) {
        const X = r[Q];
        o(
          X,
          t,
          l,
          B,
          !!X.dynamicChildren
        );
      }
  },
  move: ql,
  hydrate: Ua
};
function ql(e, t, l, { o: { insert: o }, m: s }, i = 2) {
  i === 0 && (e.targetStart && o(e.targetStart, t, l), o(e.targetAnchor, t, l), l = e.targetAnchor);
  const { el: a, anchor: r, shapeFlag: c, children: g, props: m } = e, y = i === 2;
  if (y && o(a, t, l), !Ft.has(e) && (!y || Xt(m)) && c & 16)
    for (let T = 0; T < g.length; T++)
      s(
        g[T],
        t,
        l,
        2
      );
  y && o(r, t, l);
}
function Ua(e, t, l, o, s, i, {
  o: { nextSibling: a, parentNode: r, querySelector: c, insert: g, createText: m }
}, y) {
  function T(Q, X) {
    let Z = X;
    for (; Z; ) {
      if (Z && Z.nodeType === 8) {
        if (Z.data === "teleport start anchor")
          t.targetStart = Z;
        else if (Z.data === "teleport anchor") {
          t.targetAnchor = Z, Q._lpa = t.targetAnchor && a(t.targetAnchor);
          break;
        }
      }
      Z = a(Z);
    }
  }
  function E(Q, X) {
    X.anchor = y(
      a(Q),
      X,
      r(Q),
      l,
      o,
      s,
      i
    );
  }
  const B = t.target = Dn(
    t.props,
    c
  ), I = Xt(t.props);
  if (B) {
    const Q = B._lpa || B.firstChild;
    t.shapeFlag & 16 && (I ? (T(B, Q), E(e, t), t.targetAnchor || Nn(
      B,
      t,
      m,
      g,
      // if target is the same as the main view, insert anchors before current node
      // to avoid hydrating mismatch
      r(e) === B ? e : null
    )) : (t.anchor = a(e), T(B, Q), t.targetAnchor || Nn(B, t, m, g), y(
      Q && a(Q),
      t,
      B,
      l,
      o,
      s,
      i
    ))), vl(t, I);
  } else I && t.shapeFlag & 16 && (E(e, t), t.targetStart = e, t.targetAnchor = a(e));
  return t.anchor && a(t.anchor);
}
const Pa = Ea;
function vl(e, t) {
  const l = e.ctx;
  l && l.ut && (t ? l.ut(e.el, e.anchor) : l.ut(e.targetStart, e.targetAnchor));
}
function Nn(e, t, l, o, s = null) {
  const i = t.targetStart = l(""), a = t.targetAnchor = l("");
  return i[Po] = a, e && (o(i, e, s), o(a, e, s)), a;
}
const Cn = /* @__PURE__ */ Symbol("_leaveCb");
function Aa(e) {
  let t = e[0];
  if (e.length > 1) {
    for (const l of e)
      if (l.type !== dt) {
        t = l;
        break;
      }
  }
  return t;
}
function Ao(e) {
  if (!os(e))
    return cn(e.type) && e.children ? Aa(e.children) : e;
  if (e.component)
    return e.component.subTree;
  const { shapeFlag: t, children: l } = e;
  if (l) {
    if (t & 16)
      return l[0];
    if (t & 32 && fe(l.default))
      return l.default();
  }
}
function wl(e, t) {
  if (e.shapeFlag & 6 && e.component) {
    e.transition = t;
    const l = e.component.subTree;
    wl(
      cn(l.type) && Ao(l) || l,
      t
    );
  } else if (e.shapeFlag & 128) {
    const l = e.suspense;
    if (l) {
      const o = l.isHydrating ? l.pendingBranch : l.activeBranch;
      o && wl(o, t.clone(o));
    } else
      e.ssContent.transition = t.clone(e.ssContent), e.ssFallback.transition = t.clone(e.ssFallback);
  } else if (e.transition = t, e.type === N && ce(e.children)) {
    const l = Lo(e.children, !1);
    l && wl(l, t);
  }
}
function qn(e) {
  if (e.component)
    return qn(e.component.subTree);
  if (e.type === N) {
    const t = ce(e.children) && Lo(e.children, !1);
    return t ? qn(t) : void 0;
  }
  if (e.type !== dt)
    return e;
}
// @__NO_SIDE_EFFECTS__
function He(e, t) {
  return fe(e) ? (
    // #8236: extend call and options.name access are considered side-effects
    // by Rollup, so we have to wrap it in a pure-annotated IIFE.
    De({ name: e.name }, t, { setup: e })
  ) : e;
}
function Io(e) {
  e.ids = [e.ids[0] + e.ids[2]++ + "-", 0, 0];
}
function Vs(e, t) {
  let l;
  return !!((l = Object.getOwnPropertyDescriptor(e, t)) && !l.configurable);
}
const Xl = /* @__PURE__ */ new WeakMap();
function _l(e, t, l, o, s = !1) {
  if (ce(e)) {
    e.forEach(
      (I, Q) => _l(
        I,
        t && (ce(t) ? t[Q] : t),
        l,
        o,
        s
      )
    );
    return;
  }
  if (sl(o) && !s) {
    o.shapeFlag & 512 && o.type.__asyncResolved && o.component.subTree.component && _l(e, t, l, o.component.subTree);
    return;
  }
  const i = o.shapeFlag & 4 ? gn(o.component) : o.el, a = s ? null : i, { i: r, r: c } = e, g = t && t.r, m = r.refs === ye ? r.refs = {} : r.refs, y = r.setupState, T = /* @__PURE__ */ $e(y), E = y === ye ? Qs : (I) => Vs(m, I) ? !1 : be(T, I), B = (I, Q) => !(Q && Vs(m, Q));
  if (g != null && g !== c) {
    if (Ts(t), Ae(g))
      m[g] = null, E(g) && (y[g] = null);
    else if (/* @__PURE__ */ ze(g)) {
      const I = t;
      B(g, I.k) && (g.value = null), I.k && (m[I.k] = null);
    }
  }
  if (fe(c))
    Il(c, r, 12, [a, m]);
  else {
    const I = Ae(c), Q = /* @__PURE__ */ ze(c);
    if (I || Q) {
      const X = () => {
        if (e.f) {
          const Z = I ? E(c) ? y[c] : m[c] : B() || !e.k ? c.value : m[e.k];
          if (s)
            ce(Z) && Kn(Z, i);
          else if (ce(Z))
            Z.includes(i) || Z.push(i);
          else if (I)
            m[c] = [i], E(c) && (y[c] = m[c]);
          else {
            const le = [i];
            B(c, e.k) && (c.value = le), e.k && (m[e.k] = le);
          }
        } else I ? (m[c] = a, E(c) && (y[c] = a)) : Q && (B(c, e.k) && (c.value = a), e.k && (m[e.k] = a));
      };
      if (a) {
        const Z = () => {
          X(), Xl.delete(e);
        };
        Z.id = -1, Xl.set(e, Z), Be(Z, l);
      } else
        Ts(e), X();
    }
  }
}
function Ts(e) {
  const t = Xl.get(e);
  t && (t.flags |= 8, Xl.delete(e));
}
an().requestIdleCallback;
an().cancelIdleCallback;
const sl = (e) => !!e.type.__asyncLoader, os = (e) => e.type.__isKeepAlive;
function Ia(e, t) {
  Mo(e, "a", t);
}
function Ma(e, t) {
  Mo(e, "da", t);
}
function Mo(e, t, l = Qe) {
  const o = e.__wdc || (e.__wdc = () => {
    let s = l;
    for (; s; ) {
      if (s.isDeactivated)
        return;
      s = s.parent;
    }
    return e();
  });
  if (Tl(t, o, l), l) {
    let s = l.parent;
    for (; s && s.parent; )
      os(s.parent.vnode) && Oa(o, t, l, s), s = s.parent;
  }
}
function Oa(e, t, l, o) {
  const s = Tl(
    t,
    e,
    o,
    !0
    /* prepend */
  ), i = Tl(
    "um",
    () => Kn(o[t], s),
    l
  );
  i.flags = 16;
}
function Tl(e, t, l = Qe, o = !1) {
  if (l) {
    const s = l[e] || (l[e] = []), i = t.__weh || (t.__weh = (...a) => {
      xt();
      const r = Ml(l), c = bt(t, l, e, a);
      return r(), St(), c;
    });
    return o ? s.unshift(i) : s.push(i), i;
  }
}
const Nt = (e) => (t, l = Qe) => {
  (!Pl || e === "sp") && Tl(e, (...o) => t(...o), l);
}, Ra = Nt("bm"), ct = Nt("m"), Da = Nt(
  "bu"
), Na = Nt("u"), Oo = Nt(
  "bum"
), qt = Nt("um"), qa = Nt(
  "sp"
), Ha = Nt("rtg"), Fa = Nt("rtc");
function La(e, t = Qe) {
  Tl("ec", e, t);
}
const ja = /* @__PURE__ */ Symbol.for("v-ndc");
function se(e, t, l, o) {
  let s;
  const i = l, a = ce(e);
  if (a || Ae(e)) {
    const r = a && /* @__PURE__ */ Wt(e);
    let c = !1, g = !1;
    r && (c = !/* @__PURE__ */ rt(e), g = /* @__PURE__ */ Vt(e), e = un(e)), s = new Array(e.length);
    for (let m = 0, y = e.length; m < y; m++)
      s[m] = t(
        c ? g ? Bt(ut(e[m])) : ut(e[m]) : e[m],
        m,
        void 0,
        i
      );
  } else if (typeof e == "number")
    if (!Number.isInteger(e) || e < 0)
      s = [];
    else {
      s = new Array(e);
      for (let r = 0; r < e; r++)
        s[r] = t(r + 1, r, void 0, i);
    }
  else if (Se(e))
    if (e[Symbol.iterator])
      s = Array.from(
        e,
        (r, c) => t(r, c, void 0, i)
      );
    else {
      const r = Object.keys(e);
      s = new Array(r.length);
      for (let c = 0, g = r.length; c < g; c++) {
        const m = r[c];
        s[c] = t(e[m], m, c, i);
      }
    }
  else
    s = [];
  return s;
}
function Wa(e, t, l, o, s, i) {
  if (l == null && (l = {}), Ge.ce || Ge.parent && sl(Ge.parent) && Ge.parent.ce) {
    const g = l, m = Object.keys(g).length > 0;
    return p(), ge(
      N,
      null,
      [Ee("slot", g, o)],
      m ? -2 : 64
    );
  }
  let a = e[t];
  a && a._c && (a._d = !1);
  const r = Ot.length;
  p();
  let c;
  try {
    const g = a && Ro(a(l)), m = l.key || i || // slot content array of a dynamic conditional slot may have a branch
    // key attached in the `createSlots` helper, respect that
    g && g.key;
    c = ge(
      N,
      {
        key: (m && !ht(m) ? m : `_${t}`) + // #7256 force differentiate fallback content from actual content
        (!g && o ? "_fb" : "")
      },
      g || (o ? o() : []),
      g && e._ === 1 ? 64 : -2
    );
  } catch (g) {
    for (let m = Ot.length; m > r; m--) us();
    throw g;
  } finally {
    a && a._c && (a._d = !0);
  }
  return c.scopeId && (c.slotScopeIds = [c.scopeId + "-s"]), c;
}
function Ro(e) {
  return e.some((t) => vn(t) ? !(t.type === dt || t.type === N && !Ro(t.children)) : !0) ? e : null;
}
const Hn = (e) => e ? oi(e) ? gn(e) : Hn(e.parent) : null, kl = (
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
    $parent: (e) => Hn(e.parent),
    $root: (e) => Hn(e.root),
    $host: (e) => e.ce,
    $emit: (e) => e.emit,
    $options: (e) => No(e),
    $forceUpdate: (e) => e.f || (e.f = () => {
      ns(e.update);
    }),
    $nextTick: (e) => e.n || (e.n = ls.bind(e.proxy)),
    $watch: (e) => Va.bind(e)
  })
), xn = (e, t) => e !== ye && !e.__isScriptSetup && be(e, t), Ba = {
  get({ _: e }, t) {
    if (t === "__v_skip")
      return !0;
    const { ctx: l, setupState: o, data: s, props: i, accessCache: a, type: r, appContext: c } = e;
    if (t[0] !== "$") {
      const T = a[t];
      if (T !== void 0)
        switch (T) {
          case 1:
            return o[t];
          case 2:
            return s[t];
          case 4:
            return l[t];
          case 3:
            return i[t];
        }
      else {
        if (xn(o, t))
          return a[t] = 1, o[t];
        if (s !== ye && be(s, t))
          return a[t] = 2, s[t];
        if (be(i, t))
          return a[t] = 3, i[t];
        if (l !== ye && be(l, t))
          return a[t] = 4, l[t];
        Fn && (a[t] = 0);
      }
    }
    const g = kl[t];
    let m, y;
    if (g)
      return t === "$attrs" && Ke(e.attrs, "get", ""), g(e);
    if (
      // css module (injected by vue-loader)
      (m = r.__cssModules) && (m = m[t])
    )
      return m;
    if (l !== ye && be(l, t))
      return a[t] = 4, l[t];
    if (
      // global properties
      y = c.config.globalProperties, be(y, t)
    )
      return y[t];
  },
  set({ _: e }, t, l) {
    const { data: o, setupState: s, ctx: i } = e;
    return xn(s, t) ? (s[t] = l, !0) : o !== ye && be(o, t) ? (o[t] = l, !0) : be(e.props, t) || t[0] === "$" && t.slice(1) in e ? !1 : (i[t] = l, !0);
  },
  has({
    _: { data: e, setupState: t, accessCache: l, ctx: o, appContext: s, props: i, type: a }
  }, r) {
    let c;
    return !!(l[r] || e !== ye && r[0] !== "$" && be(e, r) || xn(t, r) || be(i, r) || be(o, r) || be(kl, r) || be(s.config.globalProperties, r) || (c = a.__cssModules) && c[r]);
  },
  defineProperty(e, t, l) {
    return l.get != null ? e._.accessCache[t] = 0 : be(l, "value") && this.set(e, t, l.value, null), Reflect.defineProperty(e, t, l);
  }
};
function Es(e) {
  return ce(e) ? e.reduce(
    (t, l) => (t[l] = null, t),
    {}
  ) : e;
}
let Fn = !0;
function Ka(e) {
  const t = No(e), l = e.proxy, o = e.ctx;
  Fn = !1, t.beforeCreate && Us(t.beforeCreate, e, "bc");
  const {
    // state
    data: s,
    computed: i,
    methods: a,
    watch: r,
    provide: c,
    inject: g,
    // lifecycle
    created: m,
    beforeMount: y,
    mounted: T,
    beforeUpdate: E,
    updated: B,
    activated: I,
    deactivated: Q,
    beforeDestroy: X,
    beforeUnmount: Z,
    destroyed: le,
    unmounted: j,
    render: te,
    renderTracked: O,
    renderTriggered: S,
    errorCaptured: k,
    serverPrefetch: R,
    // public API
    expose: z,
    inheritAttrs: pe,
    // assets
    components: he,
    directives: Pe,
    filters: Me
  } = t;
  if (g && Ga(g, o, null), a)
    for (const d in a) {
      const u = a[d];
      fe(u) && (o[d] = u.bind(l));
    }
  if (s) {
    const d = s.call(l, l);
    Se(d) && (e.data = /* @__PURE__ */ Zn(d));
  }
  if (Fn = !0, i)
    for (const d in i) {
      const u = i[d], v = fe(u) ? u.bind(l, l) : fe(u.get) ? u.get.bind(l, l) : Ct, _ = !fe(u) && fe(u.set) ? u.set.bind(l) : Ct, K = _e({
        get: v,
        set: _
      });
      Object.defineProperty(o, d, {
        enumerable: !0,
        configurable: !0,
        get: () => K.value,
        set: (Ve) => K.value = Ve
      });
    }
  if (r)
    for (const d in r)
      Do(r[d], o, l, d);
  if (c) {
    const d = fe(c) ? c.call(l) : c;
    Reflect.ownKeys(d).forEach((u) => {
      $a(u, d[u]);
    });
  }
  m && Us(m, e, "c");
  function U(d, u) {
    ce(u) ? u.forEach((v) => d(v.bind(l))) : u && d(u.bind(l));
  }
  if (U(Ra, y), U(ct, T), U(Da, E), U(Na, B), U(Ia, I), U(Ma, Q), U(La, k), U(Fa, O), U(Ha, S), U(Oo, Z), U(qt, j), U(qa, R), ce(z))
    if (z.length) {
      const d = e.exposed || (e.exposed = {});
      z.forEach((u) => {
        Object.defineProperty(d, u, {
          get: () => l[u],
          set: (v) => l[u] = v,
          enumerable: !0
        });
      });
    } else e.exposed || (e.exposed = {});
  te && e.render === Ct && (e.render = te), pe != null && (e.inheritAttrs = pe), he && (e.components = he), Pe && (e.directives = Pe), R && Io(e);
}
function Ga(e, t, l = Ct) {
  ce(e) && (e = Ln(e));
  for (const o in e) {
    const s = e[o];
    let i;
    Se(s) ? "default" in s ? i = Kl(
      s.from || o,
      s.default,
      !0
    ) : i = Kl(s.from || o) : i = Kl(s), /* @__PURE__ */ ze(i) ? Object.defineProperty(t, o, {
      enumerable: !0,
      configurable: !0,
      get: () => i.value,
      set: (a) => i.value = a
    }) : t[o] = i;
  }
}
function Us(e, t, l) {
  bt(
    ce(e) ? e.map((o) => o.bind(t.proxy)) : e.bind(t.proxy),
    t,
    l
  );
}
function Do(e, t, l, o) {
  let s = o.includes(".") ? Uo(l, o) : () => l[o];
  if (Ae(e)) {
    const i = t[e];
    fe(i) && Xe(s, i);
  } else if (fe(e))
    Xe(s, e.bind(l));
  else if (Se(e))
    if (ce(e))
      e.forEach((i) => Do(i, t, l, o));
    else {
      const i = fe(e.handler) ? e.handler.bind(l) : t[e.handler];
      fe(i) && Xe(s, i, e);
    }
}
function No(e) {
  const t = e.type, { mixins: l, extends: o } = t, {
    mixins: s,
    optionsCache: i,
    config: { optionMergeStrategies: a }
  } = e.appContext, r = i.get(t);
  let c;
  return r ? c = r : !s.length && !l && !o ? c = t : (c = {}, s.length && s.forEach(
    (g) => Ql(c, g, a, !0)
  ), Ql(c, t, a)), Se(t) && i.set(t, c), c;
}
function Ql(e, t, l, o = !1) {
  const { mixins: s, extends: i } = t;
  i && Ql(e, i, l, !0), s && s.forEach(
    (a) => Ql(e, a, l, !0)
  );
  for (const a in t)
    if (!(o && a === "expose")) {
      const r = za[a] || l && l[a];
      e[a] = r ? r(e[a], t[a]) : t[a];
    }
  return e;
}
const za = {
  data: Ps,
  props: As,
  emits: As,
  // objects
  methods: gl,
  computed: gl,
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
  components: gl,
  directives: gl,
  // watch
  watch: Ya,
  // provide / inject
  provide: Ps,
  inject: Ja
};
function Ps(e, t) {
  return t ? e ? function() {
    return De(
      fe(e) ? e.call(this, this) : e,
      fe(t) ? t.call(this, this) : t
    );
  } : t : e;
}
function Ja(e, t) {
  return gl(Ln(e), Ln(t));
}
function Ln(e) {
  if (ce(e)) {
    const t = {};
    for (let l = 0; l < e.length; l++)
      t[e[l]] = e[l];
    return t;
  }
  return e;
}
function Je(e, t) {
  return e ? [...new Set([].concat(e, t))] : t;
}
function gl(e, t) {
  return e ? De(/* @__PURE__ */ Object.create(null), e, t) : t;
}
function As(e, t) {
  return e ? ce(e) && ce(t) ? [.../* @__PURE__ */ new Set([...e, ...t])] : De(
    /* @__PURE__ */ Object.create(null),
    Es(e),
    Es(t ?? {})
  ) : t;
}
function Ya(e, t) {
  if (!e) return t;
  if (!t) return e;
  const l = De(/* @__PURE__ */ Object.create(null), e);
  for (const o in t)
    l[o] = Je(e[o], t[o]);
  return l;
}
function qo() {
  return {
    app: null,
    config: {
      isNativeTag: Qs,
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
let Xa = 0;
function Qa(e, t) {
  return function(o, s = null) {
    fe(o) || (o = De({}, o)), s != null && !Se(s) && (s = null);
    const i = qo(), a = /* @__PURE__ */ new WeakSet(), r = [];
    let c = !1;
    const g = i.app = {
      _uid: Xa++,
      _component: o,
      _props: s,
      _container: null,
      _context: i,
      _instance: null,
      version: Tr,
      get config() {
        return i.config;
      },
      set config(m) {
      },
      use(m, ...y) {
        return a.has(m) || (m && fe(m.install) ? (a.add(m), m.install(g, ...y)) : fe(m) && (a.add(m), m(g, ...y))), g;
      },
      mixin(m) {
        return i.mixins.includes(m) || i.mixins.push(m), g;
      },
      component(m, y) {
        return y ? (i.components[m] = y, g) : i.components[m];
      },
      directive(m, y) {
        return y ? (i.directives[m] = y, g) : i.directives[m];
      },
      mount(m, y, T) {
        if (!c) {
          const E = g._ceVNode || Ee(o, s);
          return E.appContext = i, T === !0 ? T = "svg" : T === !1 && (T = void 0), e(E, m, T), c = !0, g._container = m, m.__vue_app__ = g, gn(E.component);
        }
      },
      onUnmount(m) {
        r.push(m);
      },
      unmount() {
        c && (bt(
          r,
          g._instance,
          16
        ), e(null, g._container), delete g._container.__vue_app__);
      },
      provide(m, y) {
        return i.provides[m] = y, g;
      },
      runWithContext(m) {
        const y = ol;
        ol = g;
        try {
          return m();
        } finally {
          ol = y;
        }
      }
    };
    return g;
  };
}
let ol = null;
function Za(e, t, l = ye) {
  const o = si(), s = at(t), i = Dt(t), a = Ho(e, s), r = va((c, g) => {
    let m, y = ye, T;
    return Sa(() => {
      const E = e[s];
      je(m, E) && (m = E, g());
    }), {
      get() {
        return c(), l.get ? l.get(m) : m;
      },
      set(E) {
        const B = l.set ? l.set(E) : E;
        if (!je(B, m) && !(y !== ye && je(E, y)))
          return;
        const I = o.vnode.props, Q = !!(I && // check if parent has passed v-model
        (t in I || s in I || i in I) && (`onUpdate:${t}` in I || `onUpdate:${s}` in I || `onUpdate:${i}` in I));
        Q || (m = E, g()), o.emit(`update:${t}`, B), je(E, y) && (je(E, B) && !je(B, T) || // #13524: browsers differ in when they flush microtasks between
        // event listeners. If a v-model listener emits an intermediate value
        // and a following listener restores the model to its previous prop
        // value before parent updates are flushed, the parent render can be
        // deduped as having no prop change. Force a local update so DOM state
        // such as an input's value is synchronized back to the current model.
        Q && y !== ye && !je(B, m)) && g(), y = E, T = B;
      }
    };
  });
  return r[Symbol.iterator] = () => {
    let c = 0;
    return {
      next() {
        return c < 2 ? { value: c++ ? a || ye : r, done: !1 } : { done: !0 };
      }
    };
  }, r;
}
const Ho = (e, t) => t === "modelValue" || t === "model-value" ? e.modelModifiers : e[`${t}Modifiers`] || e[`${at(t)}Modifiers`] || e[`${Dt(t)}Modifiers`];
function er(e, t, ...l) {
  if (e.isUnmounted) return;
  const o = e.vnode.props || ye;
  let s = l;
  const i = t.startsWith("update:"), a = i && Ho(o, t.slice(7));
  a && (a.trim && (s = l.map((m) => Ae(m) ? m.trim() : m)), a.number && (s = s.map(Al)));
  let r, c = o[r = bn(t)] || // also try camelCase event handler (#2249)
  o[r = bn(at(t))];
  !c && i && (c = o[r = bn(Dt(t))]), c && bt(
    c,
    e,
    6,
    s
  );
  const g = o[r + "Once"];
  if (g) {
    if (!e.emitted)
      e.emitted = {};
    else if (e.emitted[r])
      return;
    e.emitted[r] = !0, bt(
      g,
      e,
      6,
      s
    );
  }
}
const tr = /* @__PURE__ */ new WeakMap();
function Fo(e, t, l = !1) {
  const o = l ? tr : t.emitsCache, s = o.get(e);
  if (s !== void 0)
    return s;
  const i = e.emits;
  let a = {}, r = !1;
  if (!fe(e)) {
    const c = (g) => {
      const m = Fo(g, t, !0);
      m && (r = !0, De(a, m));
    };
    !l && t.mixins.length && t.mixins.forEach(c), e.extends && c(e.extends), e.mixins && e.mixins.forEach(c);
  }
  return !i && !r ? (Se(e) && o.set(e, null), null) : (ce(i) ? i.forEach((c) => a[c] = null) : De(a, i), Se(e) && o.set(e, a), a);
}
function fn(e, t) {
  return !e || !nn(t) ? !1 : (t = t.slice(2), t = t === "Once" ? t : t.replace(/Once$/, ""), be(e, t[0].toLowerCase() + t.slice(1)) || be(e, Dt(t)) || be(e, t));
}
function Is(e) {
  const {
    type: t,
    vnode: l,
    proxy: o,
    withProxy: s,
    propsOptions: [i],
    slots: a,
    attrs: r,
    emit: c,
    render: g,
    renderCache: m,
    props: y,
    data: T,
    setupState: E,
    ctx: B,
    inheritAttrs: I
  } = e, Q = Yl(e);
  let X, Z;
  try {
    if (l.shapeFlag & 4) {
      const j = s || o, te = j;
      X = $t(
        g.call(
          te,
          j,
          m,
          y,
          E,
          T,
          B
        )
      ), Z = r;
    } else {
      const j = t;
      X = $t(
        j.length > 1 ? j(
          y,
          { attrs: r, slots: a, emit: c }
        ) : j(
          y,
          null
        )
      ), Z = t.props ? r : lr(r);
    }
  } catch (j) {
    Ot.length = 0, dn(j, e, 1), X = Ee(dt);
  }
  let le = X;
  if (Z && I !== !1) {
    const j = Object.keys(Z), { shapeFlag: te } = le;
    j.length && te & 7 && (i && j.some(sn) && (Z = nr(
      Z,
      i
    )), le = il(le, Z, !1, !0));
  }
  if (l.dirs && (le = il(le, null, !1, !0), le.dirs = le.dirs ? le.dirs.concat(l.dirs) : l.dirs), l.transition) {
    const j = cn(le.type) && Ao(le) || le;
    wl(j, l.transition);
  }
  return X = le, Yl(Q), X;
}
function Lo(e, t = !0) {
  let l;
  for (let o = 0; o < e.length; o++) {
    const s = e[o];
    if (vn(s)) {
      if (s.type !== dt || s.children === "v-if") {
        if (l)
          return;
        l = s;
      }
    } else
      return;
  }
  return l;
}
const lr = (e) => {
  let t;
  for (const l in e)
    (l === "class" || l === "style" || nn(l)) && ((t || (t = {}))[l] = e[l]);
  return t;
}, nr = (e, t) => {
  const l = {};
  for (const o in e)
    (!sn(o) || !(o.slice(9) in t)) && (l[o] = e[o]);
  return l;
};
function sr(e, t, l) {
  const { props: o, children: s, component: i } = e, { props: a, children: r, patchFlag: c } = t, g = i.emitsOptions;
  if (t.dirs || t.transition)
    return !0;
  if (l && c >= 0) {
    if (c & 1024)
      return !0;
    if (c & 16)
      return o ? Ms(o, a, g) : !!a;
    if (c & 8) {
      const m = t.dynamicProps;
      for (let y = 0; y < m.length; y++) {
        const T = m[y];
        if (jo(a, o, T) && !fn(g, T))
          return !0;
      }
    }
  } else
    return (s || r) && (!r || !r.$stable) ? !0 : o === a ? !1 : o ? a ? Ms(o, a, g) : !0 : !!a;
  return !1;
}
function Ms(e, t, l) {
  const o = Object.keys(t);
  if (o.length !== Object.keys(e).length)
    return !0;
  for (let s = 0; s < o.length; s++) {
    const i = o[s];
    if (!be(e, i) || jo(t, e, i) && !fn(l, i))
      return !0;
  }
  return !1;
}
function jo(e, t, l) {
  const o = e[l], s = t[l];
  return l === "style" && Se(o) && Se(s) ? !mt(o, s) : o !== s;
}
function or({ vnode: e, parent: t, suspense: l }, o) {
  for (; t; ) {
    const s = t.subTree;
    if (s.suspense && s.suspense.activeBranch === e && (s.suspense.vnode.el = s.el = o, e = s), s === e)
      (e = t.vnode).el = o, t = t.parent;
    else
      break;
  }
  l && l.activeBranch === e && (l.vnode.el = o);
}
const Wo = {}, Bo = () => Object.create(Wo), Ko = (e) => Object.getPrototypeOf(e) === Wo;
function ir(e, t, l, o = !1) {
  const s = {}, i = Bo();
  e.propsDefaults = /* @__PURE__ */ Object.create(null), Go(e, t, s, i);
  for (const a in e.propsOptions[0])
    a in s || (s[a] = void 0);
  l ? e.props = o ? s : /* @__PURE__ */ aa(s) : e.type.props ? e.props = s : e.props = i, e.attrs = i;
}
function ar(e, t, l, o) {
  const {
    props: s,
    attrs: i,
    vnode: { patchFlag: a }
  } = e, r = /* @__PURE__ */ $e(s), [c] = e.propsOptions;
  let g = !1;
  if (
    // always force full diff in dev
    // - #1942 if hmr is enabled with sfc component
    // - vite#872 non-sfc component used by sfc component
    (o || a > 0) && !(a & 16)
  ) {
    if (a & 8) {
      const m = e.vnode.dynamicProps;
      for (let y = 0; y < m.length; y++) {
        let T = m[y];
        if (fn(e.emitsOptions, T))
          continue;
        const E = t[T];
        if (c)
          if (be(i, T))
            E !== i[T] && (i[T] = E, g = !0);
          else {
            const B = at(T);
            s[B] = jn(
              c,
              r,
              B,
              E,
              e,
              !1
            );
          }
        else
          E !== i[T] && (i[T] = E, g = !0);
      }
    }
  } else {
    Go(e, t, s, i) && (g = !0);
    let m;
    for (const y in r)
      (!t || // for camelCase
      !be(t, y) && // it's possible the original props was passed in as kebab-case
      // and converted to camelCase (#955)
      ((m = Dt(y)) === y || !be(t, m))) && (c ? l && // for camelCase
      (l[y] !== void 0 || // for kebab-case
      l[m] !== void 0) && (s[y] = jn(
        c,
        r,
        y,
        void 0,
        e,
        !0
      )) : delete s[y]);
    if (i !== r)
      for (const y in i)
        (!t || !be(t, y)) && (delete i[y], g = !0);
  }
  g && At(e.attrs, "set", "");
}
function Go(e, t, l, o) {
  const [s, i] = e.propsOptions;
  let a = !1, r;
  if (t)
    for (let c in t) {
      if (ml(c))
        continue;
      const g = t[c];
      let m;
      s && be(s, m = at(c)) ? !i || !i.includes(m) ? l[m] = g : (r || (r = {}))[m] = g : fn(e.emitsOptions, c) || (!(c in o) || g !== o[c]) && (o[c] = g, a = !0);
    }
  if (i) {
    const c = /* @__PURE__ */ $e(l), g = r || ye;
    for (let m = 0; m < i.length; m++) {
      const y = i[m];
      l[y] = jn(
        s,
        c,
        y,
        g[y],
        e,
        !be(g, y)
      );
    }
  }
  return a;
}
function jn(e, t, l, o, s, i) {
  const a = e[l];
  if (a != null) {
    const r = be(a, "default");
    if (r && o === void 0) {
      const c = a.default;
      if (a.type !== Function && !a.skipFactory && fe(c)) {
        const { propsDefaults: g } = s;
        if (l in g)
          o = g[l];
        else {
          const m = Ml(s);
          o = g[l] = c.call(
            null,
            t
          ), m();
        }
      } else
        o = c;
      s.ce && s.ce._setProp(l, o);
    }
    a[
      0
      /* shouldCast */
    ] && (i && !r ? o = !1 : a[
      1
      /* shouldCastTrue */
    ] && (o === "" || o === Dt(l)) && (o = !0));
  }
  return o;
}
const rr = /* @__PURE__ */ new WeakMap();
function zo(e, t, l = !1) {
  const o = l ? rr : t.propsCache, s = o.get(e);
  if (s)
    return s;
  const i = e.props, a = {}, r = [];
  let c = !1;
  if (!fe(e)) {
    const m = (y) => {
      c = !0;
      const [T, E] = zo(y, t, !0);
      De(a, T), E && r.push(...E);
    };
    !l && t.mixins.length && t.mixins.forEach(m), e.extends && m(e.extends), e.mixins && e.mixins.forEach(m);
  }
  if (!i && !c)
    return Se(e) && o.set(e, Qt), Qt;
  if (ce(i))
    for (let m = 0; m < i.length; m++) {
      const y = at(i[m]);
      Os(y) && (a[y] = ye);
    }
  else if (i)
    for (const m in i) {
      const y = at(m);
      if (Os(y)) {
        const T = i[m], E = a[y] = ce(T) || fe(T) ? { type: T } : De({}, T), B = E.type;
        let I = !1, Q = !0;
        if (ce(B))
          for (let X = 0; X < B.length; ++X) {
            const Z = B[X], le = fe(Z) && Z.name;
            if (le === "Boolean") {
              I = !0;
              break;
            } else le === "String" && (Q = !1);
          }
        else
          I = fe(B) && B.name === "Boolean";
        E[
          0
          /* shouldCast */
        ] = I, E[
          1
          /* shouldCastTrue */
        ] = Q, (I || be(E, "default")) && r.push(y);
      }
    }
  const g = [a, r];
  return Se(e) && o.set(e, g), g;
}
function Os(e) {
  return e[0] !== "$" && !ml(e);
}
const is = (e) => e === "_" || e === "_ctx" || e === "$stable", as = (e) => ce(e) ? e.map($t) : [$t(e)], ur = (e, t, l) => {
  if (t._n)
    return t;
  const o = Re((...s) => as(t(...s)), l);
  return o._c = !1, o;
}, Jo = (e, t, l) => {
  const o = e._ctx;
  for (const s in e) {
    if (is(s)) continue;
    const i = e[s];
    if (fe(i))
      t[s] = ur(s, i, o);
    else if (i != null) {
      const a = as(i);
      t[s] = () => a;
    }
  }
}, Yo = (e, t) => {
  const l = as(t);
  e.slots.default = () => l;
}, Xo = (e, t, l) => {
  for (const o in t)
    (l || !is(o)) && (e[o] = t[o]);
}, dr = (e, t, l) => {
  const o = e.slots = Bo();
  if (e.vnode.shapeFlag & 32) {
    const s = t._;
    s ? (Xo(o, t, l), l && no(o, "_", s, !0)) : Jo(t, o);
  } else t && Yo(e, t);
}, cr = (e, t, l) => {
  const { vnode: o, slots: s } = e;
  let i = !0, a = ye;
  if (o.shapeFlag & 32) {
    const r = t._;
    r ? l && r === 1 ? i = !1 : Xo(s, t, l) : (i = !t.$stable, Jo(t, s)), a = t;
  } else t && (Yo(e, t), a = { default: 1 });
  if (i)
    for (const r in s)
      !is(r) && a[r] == null && delete s[r];
}, Be = mr;
function fr(e) {
  return pr(e);
}
function pr(e, t) {
  const l = an();
  l.__VUE__ = !0;
  const {
    insert: o,
    remove: s,
    patchProp: i,
    createElement: a,
    createText: r,
    createComment: c,
    setText: g,
    setElementText: m,
    parentNode: y,
    nextSibling: T,
    setScopeId: E = Ct,
    insertStaticContent: B
  } = e, I = (b, C, P, L = null, M = null, D = null, G = void 0, J = null, Y = !!C.dynamicChildren) => {
    if (b === C)
      return;
    b && !fl(b, C) && (L = ot(b), Ve(b, M, D, !0), b = null), C.patchFlag === -2 && (Y = !1, C.dynamicChildren = null), C.dynamicChildren && b && b.dynamicChildren && b.dynamicChildren.hasOnce && (C.dynamicChildren === Qt && (C.dynamicChildren = []), C.dynamicChildren.hasOnce = !0);
    const { type: q, ref: oe, shapeFlag: ee } = C;
    switch (q) {
      case pn:
        Q(b, C, P, L);
        break;
      case dt:
        X(b, C, P, L);
        break;
      case Vn:
        b == null && Z(C, P, L, G);
        break;
      case N:
        he(
          b,
          C,
          P,
          L,
          M,
          D,
          G,
          J,
          Y
        );
        break;
      default:
        ee & 1 ? te(
          b,
          C,
          P,
          L,
          M,
          D,
          G,
          J,
          Y
        ) : ee & 6 ? Pe(
          b,
          C,
          P,
          L,
          M,
          D,
          G,
          J,
          Y
        ) : (ee & 64 || ee & 128) && q.process(
          b,
          C,
          P,
          L,
          M,
          D,
          G,
          J,
          Y,
          yt
        );
    }
    oe != null && M ? _l(oe, b && b.ref, D, C || b, !C) : oe == null && b && b.ref != null && _l(b.ref, null, D, b, !0);
  }, Q = (b, C, P, L) => {
    if (b == null)
      o(
        C.el = r(C.children),
        P,
        L
      );
    else {
      const M = C.el = b.el;
      C.children !== b.children && g(M, C.children);
    }
  }, X = (b, C, P, L) => {
    b == null ? o(
      C.el = c(C.children || ""),
      P,
      L
    ) : C.el = b.el;
  }, Z = (b, C, P, L) => {
    [b.el, b.anchor] = B(
      b.children,
      C,
      P,
      L,
      b.el,
      b.anchor
    );
  }, le = ({ el: b, anchor: C }, P, L) => {
    let M;
    for (; b && b !== C; )
      M = T(b), o(b, P, L), b = M;
    o(C, P, L);
  }, j = ({ el: b, anchor: C }) => {
    let P;
    for (; b && b !== C; )
      P = T(b), s(b), b = P;
    s(C);
  }, te = (b, C, P, L, M, D, G, J, Y) => {
    if (C.type === "svg" ? G = "svg" : C.type === "math" && (G = "mathml"), b == null)
      O(
        C,
        P,
        L,
        M,
        D,
        G,
        J,
        Y
      );
    else {
      const q = b.el && b.el._isVueCE ? b.el : null;
      try {
        q && q._beginPatch(), R(
          b,
          C,
          M,
          D,
          G,
          J,
          Y
        );
      } finally {
        q && q._endPatch();
      }
    }
  }, O = (b, C, P, L, M, D, G, J) => {
    let Y, q;
    const { props: oe, shapeFlag: ee, transition: ae, dirs: ie } = b;
    if (Y = b.el = a(
      b.type,
      D,
      oe && oe.is,
      oe
    ), ee & 8 ? m(Y, b.children) : ee & 16 && k(
      b.children,
      Y,
      null,
      L,
      M,
      Sn(b, D),
      G,
      J
    ), ie && zt(b, null, L, "created"), S(Y, b, b.scopeId, G, L), oe) {
      for (const ve in oe)
        ve !== "value" && !ml(ve) && i(Y, ve, null, oe[ve], D, L);
      "value" in oe && i(Y, "value", null, oe.value, D), (q = oe.onVnodeBeforeMount) && wt(q, L, b);
    }
    ie && zt(b, null, L, "beforeMount");
    const de = vr(M, ae);
    de ? ae.beforeEnter(Y) : ae && !ae.persisted && (Y[hr] = !0), o(Y, C, P), ((q = oe && oe.onVnodeMounted) || de || ie) && Be(() => {
      q && wt(q, L, b), de && ae.enter(Y), ie && zt(b, null, L, "mounted");
    }, M);
  }, S = (b, C, P, L, M) => {
    if (P && E(b, P), L)
      for (let D = 0; D < L.length; D++)
        E(b, L[D]);
    if (M) {
      let D = M.subTree;
      if (C === D || Zo(D.type) && (D.ssContent === C || D.ssFallback === C)) {
        const G = M.vnode;
        S(
          b,
          G,
          G.scopeId,
          G.slotScopeIds,
          M.parent
        );
      }
    }
  }, k = (b, C, P, L, M, D, G, J, Y = 0) => {
    for (let q = Y; q < b.length; q++) {
      const oe = b[q] = J ? Pt(b[q]) : $t(b[q]);
      I(
        null,
        oe,
        C,
        P,
        L,
        M,
        D,
        G,
        J
      );
    }
  }, R = (b, C, P, L, M, D, G) => {
    const J = C.el = b.el;
    let { patchFlag: Y, dynamicChildren: q, dirs: oe } = C;
    Y |= b.patchFlag & 16;
    const ee = b.props || ye, ae = C.props || ye;
    let ie;
    if (P && Jt(P, !1), (ie = ae.onVnodeBeforeUpdate) && wt(ie, P, C, b), oe && zt(C, b, P, "beforeUpdate"), P && Jt(P, !0), // #6385 the old vnode may be a user-wrapped non-isomorphic block
    // Force full diff when block metadata is unstable.
    q && (!b.dynamicChildren || b.dynamicChildren.length !== q.length) && (Y = 0, G = !1, q = null), (ee.innerHTML && ae.innerHTML == null || ee.textContent && ae.textContent == null) && m(J, ""), q ? z(
      b.dynamicChildren,
      q,
      J,
      P,
      L,
      Sn(C, M),
      D
    ) : G || u(
      b,
      C,
      J,
      null,
      P,
      L,
      Sn(C, M),
      D,
      !1
    ), Y > 0) {
      if (Y & 16)
        pe(J, ee, ae, P, M);
      else if (Y & 2 && ee.class !== ae.class && i(J, "class", null, ae.class, M), Y & 4 && i(J, "style", ee.style, ae.style, M), Y & 8) {
        const de = C.dynamicProps;
        for (let ve = 0; ve < de.length; ve++) {
          const ke = de[ve], Ie = ee[ke], Oe = ae[ke];
          (Oe !== Ie || ke === "value") && i(J, ke, Ie, Oe, M, P);
        }
      }
      Y & 1 && b.children !== C.children && m(J, C.children);
    } else !G && q == null && pe(J, ee, ae, P, M);
    ((ie = ae.onVnodeUpdated) || oe) && Be(() => {
      ie && wt(ie, P, C, b), oe && zt(C, b, P, "updated");
    }, L);
  }, z = (b, C, P, L, M, D, G) => {
    for (let J = 0; J < C.length; J++) {
      const Y = b[J], q = C[J], oe = Y.el || $l(Y), ee = (
        // oldVNode may be an errored async setup() component inside Suspense
        // which will not have a mounted element
        oe && // - In the case of a Fragment, we need to provide the actual parent
        // of the Fragment itself so it can move its children.
        (Y.type === N || // - In the case of different nodes, there is going to be a replacement
        // which also requires the correct parent container
        !fl(Y, q) || // - In the case of a component, it could contain anything.
        Y.shapeFlag & 198) ? y(oe) : (
          // In other cases, the parent container is not actually used so we
          // just pass the block element here to avoid a DOM parentNode call.
          P
        )
      );
      I(
        Y,
        q,
        ee,
        null,
        L,
        M,
        D,
        G,
        !0
      );
    }
  }, pe = (b, C, P, L, M) => {
    if (C !== P) {
      if (C !== ye)
        for (const D in C)
          !ml(D) && !(D in P) && i(
            b,
            D,
            C[D],
            null,
            M,
            L
          );
      for (const D in P) {
        if (ml(D)) continue;
        const G = P[D], J = C[D];
        G !== J && D !== "value" && i(b, D, J, G, M, L);
      }
      "value" in P && i(b, "value", C.value, P.value, M);
    }
  }, he = (b, C, P, L, M, D, G, J, Y) => {
    const q = C.el = b ? b.el : r(""), oe = C.anchor = b ? b.anchor : r("");
    let { patchFlag: ee, dynamicChildren: ae, slotScopeIds: ie } = C;
    ie && (J = J ? J.concat(ie) : ie), b == null ? (o(q, P, L), o(oe, P, L), k(
      // #10007
      // such fragment like `<></>` will be compiled into
      // a fragment which doesn't have a children.
      // In this case fallback to an empty array
      C.children || [],
      P,
      oe,
      M,
      D,
      G,
      J,
      Y
    )) : ee > 0 && ee & 64 && ae && // #2715 the previous fragment could've been a BAILed one as a result
    // of renderSlot() with no valid children
    b.dynamicChildren && b.dynamicChildren.length === ae.length ? (z(
      b.dynamicChildren,
      ae,
      P,
      M,
      D,
      G,
      J
    ), // #2080 if the stable fragment has a key, it's a <template v-for> that may
    //  get moved around. Make sure all root level vnodes inherit el.
    // #2134 or if it's a component root, it may also get moved around
    // as the component is being moved.
    (C.key != null || M && C === M.subTree) && rs(
      b,
      C,
      !0
      /* shallow */
    )) : u(
      b,
      C,
      P,
      oe,
      M,
      D,
      G,
      J,
      Y
    );
  }, Pe = (b, C, P, L, M, D, G, J, Y) => {
    C.slotScopeIds = J, b == null ? C.shapeFlag & 512 ? M.ctx.activate(
      C,
      P,
      L,
      G,
      Y
    ) : Me(
      C,
      P,
      L,
      M,
      D,
      G,
      Y
    ) : ne(b, C, Y);
  }, Me = (b, C, P, L, M, D, G) => {
    const J = b.component = kr(
      b,
      L,
      M
    );
    if (os(b) && (J.ctx.renderer = yt), $r(J, !1, G), J.asyncDep) {
      if (M && M.registerDep(
        J,
        U,
        G,
        D
      ), !b.el) {
        const Y = J.subTree = Ee(dt);
        X(null, Y, C, P), b.placeholder = Y.el;
      }
    } else
      U(
        J,
        b,
        C,
        P,
        M,
        D,
        G
      );
  }, ne = (b, C, P) => {
    const L = C.component = b.component;
    if (sr(b, C, P))
      if (L.asyncDep && !L.asyncResolved) {
        C.el = b.el, C.placeholder = b.placeholder, d(L, C, P);
        return;
      } else
        L.next = C, L.update();
    else
      C.el = b.el, C.placeholder = b.placeholder, L.vnode = C;
  }, U = (b, C, P, L, M, D, G) => {
    const J = () => {
      if (b.isMounted) {
        let { next: ee, bu: ae, u: ie, parent: de, vnode: ve } = b;
        {
          const Ce = Qo(b);
          if (Ce) {
            ee && (ee.el = ve.el, d(b, ee, G)), Ce.asyncDep.then(() => {
              const ft = () => {
                b.job.flags & 8 || (M && M.pendingBranch ? Be(ft, M) : q());
              };
              ft.flags = 48, Be(ft, M);
            });
            return;
          }
        }
        let ke = ee, Ie;
        Jt(b, !1), ee ? (ee.el = ve.el, d(b, ee, G)) : ee = ve, ae && Bl(ae), (Ie = ee.props && ee.props.onVnodeBeforeUpdate) && wt(Ie, de, ee, ve), Jt(b, !0);
        const Oe = Is(b), et = b.subTree;
        b.subTree = Oe, I(
          et,
          Oe,
          // parent may have changed if it's in a teleport. a root that is a
          // pending async component only has its placeholder comment
          y(
            et.el || $l(et)
          ),
          // anchor may have changed if it's in a fragment
          ot(et),
          b,
          M,
          D
        ), ee.el = Oe.el, ke === null && or(b, Oe.el), ie && Be(ie, M), (Ie = ee.props && ee.props.onVnodeUpdated) && Be(
          () => wt(Ie, de, ee, ve),
          M
        );
      } else {
        let ee;
        const { el: ae, props: ie } = C, { bm: de, m: ve, parent: ke, root: Ie, type: Oe } = b, et = sl(C);
        Jt(b, !1), de && Bl(de), !et && (ee = ie && ie.onVnodeBeforeMount) && wt(ee, ke, C), Jt(b, !0);
        {
          Ie.ce && Ie.ce._hasShadowRoot() && Ie.ce._injectChildStyle(
            Oe,
            b.parent ? b.parent.type : void 0
          );
          const Ce = b.subTree = Is(b);
          I(
            null,
            Ce,
            P,
            L,
            b,
            M,
            D
          ), C.el = Ce.el;
        }
        if (ve && Be(ve, M), !et && (ee = ie && ie.onVnodeMounted)) {
          const Ce = C;
          Be(
            () => wt(ee, ke, Ce),
            M
          );
        }
        (C.shapeFlag & 256 || ke && sl(ke.vnode) && ke.vnode.shapeFlag & 256) && b.a && Be(b.a, M), b.isMounted = !0, C = P = L = null;
      }
    };
    b.scope.on();
    const Y = b.effect = new ao(J);
    b.scope.off();
    const q = b.update = Y.run.bind(Y), oe = b.job = Y.runIfDirty.bind(Y);
    oe.i = b, oe.id = b.uid, Y.scheduler = () => ns(oe), Jt(b, !0), q();
  }, d = (b, C, P) => {
    C.component = b;
    const L = b.vnode.props;
    b.vnode = C, b.next = null, ar(b, C.props, L, P), cr(b, C.children, P), xt(), So(b), St();
  }, u = (b, C, P, L, M, D, G, J, Y = !1) => {
    const q = b && b.children, oe = b ? b.shapeFlag : 0, ee = C.children, { patchFlag: ae, shapeFlag: ie } = C;
    if (ae > 0) {
      if (ae & 128) {
        _(
          q,
          ee,
          P,
          L,
          M,
          D,
          G,
          J,
          Y
        );
        return;
      } else if (ae & 256) {
        v(
          q,
          ee,
          P,
          L,
          M,
          D,
          G,
          J,
          Y
        );
        return;
      }
    }
    ie & 8 ? (oe & 16 && st(q, M, D), ee !== q && m(P, ee)) : oe & 16 ? ie & 16 ? _(
      q,
      ee,
      P,
      L,
      M,
      D,
      G,
      J,
      Y
    ) : st(q, M, D, !0) : (oe & 8 && m(P, ""), ie & 16 && k(
      ee,
      P,
      L,
      M,
      D,
      G,
      J,
      Y
    ));
  }, v = (b, C, P, L, M, D, G, J, Y) => {
    b = b || Qt, C = C || Qt;
    const q = b.length, oe = C.length, ee = Math.min(q, oe);
    let ae;
    for (ae = 0; ae < ee; ae++) {
      const ie = C[ae] = Y ? Pt(C[ae]) : $t(C[ae]);
      I(
        b[ae],
        ie,
        P,
        null,
        M,
        D,
        G,
        J,
        Y
      );
    }
    q > oe ? st(
      b,
      M,
      D,
      !0,
      !1,
      ee
    ) : k(
      C,
      P,
      L,
      M,
      D,
      G,
      J,
      Y,
      ee
    );
  }, _ = (b, C, P, L, M, D, G, J, Y) => {
    let q = 0;
    const oe = C.length;
    let ee = b.length - 1, ae = oe - 1;
    for (; q <= ee && q <= ae; ) {
      const ie = b[q], de = C[q] = Y ? Pt(C[q]) : $t(C[q]);
      if (fl(ie, de))
        I(
          ie,
          de,
          P,
          null,
          M,
          D,
          G,
          J,
          Y
        );
      else
        break;
      q++;
    }
    for (; q <= ee && q <= ae; ) {
      const ie = b[ee], de = C[ae] = Y ? Pt(C[ae]) : $t(C[ae]);
      if (fl(ie, de))
        I(
          ie,
          de,
          P,
          null,
          M,
          D,
          G,
          J,
          Y
        );
      else
        break;
      ee--, ae--;
    }
    if (q > ee) {
      if (q <= ae) {
        const ie = ae + 1, de = ie < oe ? C[ie].el : L;
        for (; q <= ae; )
          I(
            null,
            C[q] = Y ? Pt(C[q]) : $t(C[q]),
            P,
            de,
            M,
            D,
            G,
            J,
            Y
          ), q++;
      }
    } else if (q > ae)
      for (; q <= ee; )
        Ve(b[q], M, D, !0), q++;
    else {
      const ie = q, de = q, ve = /* @__PURE__ */ new Map();
      for (q = de; q <= ae; q++) {
        const we = C[q] = Y ? Pt(C[q]) : $t(C[q]);
        we.key != null && ve.set(we.key, q);
      }
      let ke, Ie = 0;
      const Oe = ae - de + 1;
      let et = !1, Ce = 0;
      const ft = new Array(Oe);
      for (q = 0; q < Oe; q++) ft[q] = 0;
      for (q = ie; q <= ee; q++) {
        const we = b[q];
        if (Ie >= Oe) {
          Ve(we, M, D, !0);
          continue;
        }
        let it;
        if (we.key != null)
          it = ve.get(we.key);
        else
          for (ke = de; ke <= ae; ke++)
            if (ft[ke - de] === 0 && fl(we, C[ke])) {
              it = ke;
              break;
            }
        it === void 0 ? Ve(we, M, D, !0) : (ft[it - de] = q + 1, it >= Ce ? Ce = it : et = !0, I(
          we,
          C[it],
          P,
          null,
          M,
          D,
          G,
          J,
          Y
        ), Ie++);
      }
      const ul = et ? gr(ft) : Qt;
      for (ke = ul.length - 1, q = Oe - 1; q >= 0; q--) {
        const we = de + q, it = C[we], el = C[we + 1], Tt = we + 1 < oe ? (
          // #13559, #14173 fallback to el placeholder for unresolved async component
          el.el || $l(el)
        ) : L;
        ft[q] === 0 ? I(
          null,
          it,
          P,
          Tt,
          M,
          D,
          G,
          J,
          Y
        ) : et && (ke < 0 || q !== ul[ke] ? K(it, P, Tt, 2) : ke--);
      }
    }
  }, K = (b, C, P, L, M = null) => {
    const { el: D, type: G, transition: J, children: Y, shapeFlag: q } = b;
    if (q & 6) {
      K(b.component.subTree, C, P, L);
      return;
    }
    if (q & 128) {
      b.suspense.move(C, P, L);
      return;
    }
    if (q & 64) {
      G.move(b, C, P, yt);
      return;
    }
    if (G === N) {
      o(D, C, P);
      for (let ee = 0; ee < Y.length; ee++)
        K(Y[ee], C, P, L);
      o(b.anchor, C, P);
      return;
    }
    if (G === Vn) {
      le(b, C, P);
      return;
    }
    if (L !== 2 && q & 1 && J)
      if (L === 0)
        J.persisted && !D[Cn] ? o(D, C, P) : (J.beforeEnter(D), o(D, C, P), Be(() => J.enter(D), M));
      else {
        const { leave: ee, delayLeave: ae, afterLeave: ie } = J, de = () => {
          b.ctx.isUnmounted ? s(D) : o(D, C, P);
        }, ve = () => {
          const ke = D._isLeaving || !!D[Cn];
          D._isLeaving && D[Cn](
            !0
            /* cancelled */
          ), J.persisted && !ke ? de() : ee(D, () => {
            de(), ie && ie();
          });
        };
        ae ? ae(D, de, ve) : ve();
      }
    else
      o(D, C, P);
  }, Ve = (b, C, P, L = !1, M = !1) => {
    const {
      type: D,
      props: G,
      ref: J,
      children: Y,
      dynamicChildren: q,
      shapeFlag: oe,
      patchFlag: ee,
      dirs: ae,
      cacheIndex: ie,
      memo: de
    } = b;
    if ((ee === -2 || q && q.hasOnce) && (M = !1), J != null && (xt(), _l(J, null, P, b, !0), St()), ie != null && (!b.ctx || b.ctx === C) && (C.renderCache[ie] = void 0), oe & 256 && C.ctx.deactivate(b))
      return;
    const ve = oe & 1 && ae, ke = !sl(b);
    let Ie;
    if (ke && (Ie = G && G.onVnodeBeforeUnmount) && wt(Ie, C, b), oe & 6)
      Ht(b.component, P, L);
    else {
      if (oe & 128) {
        b.suspense.unmount(P, L);
        return;
      }
      ve && zt(b, null, C, "beforeUnmount"), oe & 64 ? b.type.remove(
        b,
        C,
        P,
        yt,
        L
      ) : q && // #5154
      // when v-once is used inside a block, setBlockTracking(-1) marks the
      // parent block with hasOnce: true
      // so that it doesn't take the fast path during unmount - otherwise
      // components nested in v-once are never unmounted.
      !q.hasOnce && // #1153: fast path should not be taken for non-stable (v-for) fragments
      (D !== N || ee > 0 && ee & 64) ? st(
        q,
        C,
        P,
        !1,
        !0
      ) : (D === N && ee & 384 || !M && oe & 16) && st(Y, C, P), L && W(b);
    }
    const Oe = de != null && ie == null;
    (ke && (Ie = G && G.onVnodeUnmounted) || ve || Oe) && Be(() => {
      Ie && wt(Ie, C, b), ve && zt(b, null, C, "unmounted"), Oe && (b.el = null);
    }, P);
  }, W = (b) => {
    const { type: C, el: P, anchor: L, transition: M } = b, D = C === N;
    if (D && !M) {
      Ne(P, L);
      return;
    }
    if (C === Vn) {
      j(b), M && !M.persisted && M.afterLeave && M.afterLeave();
      return;
    }
    const G = D ? qn(b) : b, J = () => {
      D ? y(P) && Ne(P, L) : s(P), M && !M.persisted && M.afterLeave && M.afterLeave();
    };
    if (G && G.shapeFlag & 1 && M && !M.persisted) {
      const { leave: Y, delayLeave: q } = M, oe = G.el, ee = () => Y(oe, J);
      q ? q(oe, J, ee) : ee();
    } else
      J();
  }, Ne = (b, C) => {
    let P;
    for (; b !== C; )
      P = T(b), s(b), b = P;
    s(C);
  }, Ht = (b, C, P) => {
    const { bum: L, scope: M, job: D, subTree: G, um: J, m: Y, a: q } = b;
    Rs(Y), Rs(q), L && Bl(L), M.stop(), D ? (D.flags |= 8, Ve(G, b, C, P)) : G && (G.transition = b.vnode.transition, Ve(G, b, C, P)), J && Be(J, C);
    const oe = () => {
      b.isUnmounted = !0;
    };
    oe.flags = 16, Be(oe, C);
  }, st = (b, C, P, L = !1, M = !1, D = 0) => {
    for (let G = D; G < b.length; G++)
      Ve(b[G], C, P, L, M);
  }, ot = (b) => {
    if (b.shapeFlag & 6)
      return ot(b.component.subTree);
    if (b.shapeFlag & 128)
      return b.suspense.next();
    const C = T(b.anchor || b.el), P = C && C[Po];
    return P ? T(P) : C;
  }, Gt = (b, C, P) => {
    const L = b && C._vnode ? void 0 : b && b.component ? b.component.uid : _r();
    ka(() => {
      b == null ? C._vnode && Ve(C._vnode, null, null, !0) : I(
        C._vnode || null,
        b,
        C,
        null,
        null,
        null,
        P
      ), C._vnode = b;
    }, L);
  }, yt = {
    p: I,
    um: Ve,
    m: K,
    r: W,
    mt: Me,
    mc: k,
    pc: u,
    pbc: z,
    n: ot,
    o: e
  };
  return {
    render: Gt,
    hydrate: void 0,
    createApp: Qa(Gt)
  };
}
function Sn({ type: e, props: t }, l) {
  return l === "svg" && e === "foreignObject" || l === "mathml" && e === "annotation-xml" && t && t.encoding && t.encoding.includes("html") ? void 0 : l;
}
function Jt({ effect: e, job: t }, l) {
  l ? (e.flags |= 32, t.flags |= 4) : (e.flags &= -33, t.flags &= -5);
}
function vr(e, t) {
  return (!e || e && !e.pendingBranch) && t && !t.persisted;
}
function rs(e, t, l = !1) {
  const o = e.children, s = t.children;
  if (ce(o) && ce(s))
    for (let i = 0; i < o.length; i++) {
      const a = o[i];
      let r = s[i];
      r.shapeFlag & 1 && !r.dynamicChildren && ((r.patchFlag <= 0 || r.patchFlag === 32) && (r = s[i] = Pt(s[i]), r.el = a.el), !l && r.patchFlag !== -2 && rs(a, r)), r.type === pn && (r.patchFlag === -1 && (r = s[i] = Pt(r)), r.el = a.el), r.type === dt && !r.el && (r.el = a.el);
    }
}
function gr(e) {
  const t = e.slice(), l = [0];
  let o, s, i, a, r;
  const c = e.length;
  for (o = 0; o < c; o++) {
    const g = e[o];
    if (g !== 0) {
      if (s = l[l.length - 1], e[s] < g) {
        t[o] = s, l.push(o);
        continue;
      }
      for (i = 0, a = l.length - 1; i < a; )
        r = i + a >> 1, e[l[r]] < g ? i = r + 1 : a = r;
      g < e[l[i]] && (i > 0 && (t[o] = l[i - 1]), l[i] = o);
    }
  }
  for (i = l.length, a = l[i - 1]; i-- > 0; )
    l[i] = a, a = t[a];
  return l;
}
function Qo(e) {
  const t = e.subTree.component;
  if (t)
    return t.asyncDep && !t.asyncResolved ? t : Qo(t);
}
function Rs(e) {
  if (e)
    for (let t = 0; t < e.length; t++)
      e[t].flags |= 8;
}
function $l(e) {
  if (e.placeholder)
    return e.placeholder;
  const t = e.component;
  if (t)
    return $l(t.subTree);
  const l = e.suspense;
  return l && l.activeBranch ? $l(l.activeBranch) : null;
}
const Zo = (e) => e.__isSuspense, hr = /* @__PURE__ */ Symbol("_deferredEnter");
function mr(e, t) {
  t && t.pendingBranch ? ce(e) ? t.effects.push(...e) : t.effects.push(e) : _a(e);
}
const N = /* @__PURE__ */ Symbol.for("v-fgt"), pn = /* @__PURE__ */ Symbol.for("v-txt"), dt = /* @__PURE__ */ Symbol.for("v-cmt"), Vn = /* @__PURE__ */ Symbol.for("v-stc"), Ot = [];
let lt = null;
function p(e = !1) {
  Ot.push(lt = e ? null : []);
}
function us() {
  Ot.pop(), lt = Ot[Ot.length - 1] || null;
}
let El = 1;
function Ds(e, t = !1) {
  El += e, e < 0 && lt && t && (lt.hasOnce = !0);
}
function ei(e) {
  return e.dynamicChildren = El > 0 ? lt || Qt : null, us(), El > 0 && lt && lt.push(e), e;
}
function h(e, t, l, o, s, i) {
  return ei(
    n(
      e,
      t,
      l,
      o,
      s,
      i,
      !0
    )
  );
}
function ge(e, t, l, o, s) {
  return ei(
    Ee(
      e,
      t,
      l,
      o,
      s,
      !0
    )
  );
}
function vn(e) {
  return e ? e.__v_isVNode === !0 : !1;
}
function fl(e, t) {
  return e.type === t.type && e.key === t.key;
}
const ti = ({ key: e }) => e ?? null, Gl = ({
  ref: e,
  ref_key: t,
  ref_for: l
}) => (typeof e == "number" && (e = "" + e), e != null ? Ae(e) || /* @__PURE__ */ ze(e) || fe(e) ? { i: Ge, r: e, k: t, f: !!l } : e : null);
function n(e, t = null, l = null, o = 0, s = null, i = e === N ? 0 : 1, a = !1, r = !1) {
  const c = {
    __v_isVNode: !0,
    __v_skip: !0,
    type: e,
    props: t,
    key: t && ti(t),
    ref: t && Gl(t),
    scopeId: Eo,
    slotScopeIds: null,
    children: l,
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
    ctx: Ge
  };
  return r ? (Zl(c, l), i & 128 && e.normalize(c)) : l && (c.shapeFlag |= Ae(l) ? 8 : 16), El > 0 && // avoid a block node from tracking itself
  !a && // has current parent block
  lt && // presence of a patch flag indicates this node needs patching on updates.
  // component nodes also should always be patched, because even if the
  // component doesn't need to update, it needs to persist the instance on to
  // the next vnode so that it can be properly unmounted later.
  (c.patchFlag > 0 || i & 6) && // the EVENTS flag is only for hydration and if it is the only flag, the
  // vnode should not be considered dynamic due to handler caching.
  c.patchFlag !== 32 && lt.push(c), c;
}
const Ee = br;
function br(e, t = null, l = null, o = 0, s = null, i = !1) {
  if ((!e || e === ja) && (e = dt), vn(e)) {
    const r = il(
      e,
      t,
      !0
      /* mergeRef: true */
    );
    return l && Zl(r, l), El > 0 && !i && lt && (r.shapeFlag & 6 ? lt[lt.indexOf(e)] = r : lt.push(r)), r.patchFlag = -2, r;
  }
  if (Vr(e) && (e = e.__vccOpts), t) {
    t = yr(t);
    let { class: r, style: c } = t;
    r && !Ae(r) && (t.class = Ue(r)), Se(c) && (/* @__PURE__ */ ts(c) && !ce(c) && (c = De({}, c)), t.style = Cl(c));
  }
  const a = Ae(e) ? 1 : Zo(e) ? 128 : cn(e) ? 64 : Se(e) ? 4 : fe(e) ? 2 : 0;
  return n(
    e,
    t,
    l,
    o,
    s,
    a,
    i,
    !0
  );
}
function yr(e) {
  return e ? /* @__PURE__ */ ts(e) ? De({}, e) : Ko(e) ? De({}, e[ai] || e) : e : null;
}
function il(e, t, l = !1, o = !1) {
  const { props: s, ref: i, patchFlag: a, children: r, transition: c } = e, g = t ? li(s || {}, t) : s, m = {
    __v_isVNode: !0,
    __v_skip: !0,
    type: e.type,
    props: g,
    key: g && ti(g),
    ref: t && t.ref ? (
      // #2078 in the case of <component :is="vnode" ref="extra"/>
      // if the vnode itself already has a ref, cloneVNode will need to merge
      // the refs so the single vnode can be set on multiple refs
      l && i ? ce(i) ? i.concat(Gl(t)) : [i, Gl(t)] : Gl(t)
    ) : i,
    scopeId: e.scopeId,
    slotScopeIds: e.slotScopeIds,
    children: r,
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
    ssContent: e.ssContent && il(e.ssContent),
    ssFallback: e.ssFallback && il(e.ssFallback),
    placeholder: e.placeholder,
    el: e.el,
    anchor: e.anchor,
    ctx: e.ctx,
    ce: e.ce,
    cacheIndex: e.cacheIndex
  };
  return c && o && wl(
    m,
    c.clone(m)
  ), m;
}
function A(e = " ", t = 0) {
  return Ee(pn, null, e, t);
}
function V(e = "", t = !1) {
  return t ? (p(), ge(dt, null, e)) : Ee(dt, null, e);
}
function $t(e) {
  return e == null || typeof e == "boolean" ? Ee(dt) : ce(e) ? Ee(
    N,
    null,
    // #3666, avoid reference pollution when reusing vnode
    e.slice()
  ) : vn(e) ? Pt(e) : Ee(pn, null, String(e));
}
function Pt(e) {
  return e.el === null && e.patchFlag !== -1 || e.memo ? e : il(e);
}
function Zl(e, t) {
  let l = 0;
  const { shapeFlag: o } = e;
  if (t == null)
    t = null;
  else if (ce(t))
    l = 16;
  else if (typeof t == "object")
    if (o & 65) {
      const s = t.default;
      s && (s._c && (s._d = !1), Zl(e, s()), s._c && (s._d = !0));
      return;
    } else {
      l = 32;
      const s = t._;
      !s && !Ko(t) ? t._ctx = Ge : s === 3 && Ge && (Ge.slots._ === 1 ? t._ = 1 : (t._ = 2, e.patchFlag |= 1024));
    }
  else if (fe(t)) {
    if (o & 65) {
      Zl(e, { default: t });
      return;
    }
    t = { default: t, _ctx: Ge }, l = 32;
  } else
    t = String(t), o & 64 ? (l = 16, t = [A(t)]) : l = 8;
  e.children = t, e.shapeFlag |= l;
}
function li(...e) {
  const t = {};
  for (let l = 0; l < e.length; l++) {
    const o = e[l];
    for (const s in o)
      if (s === "class")
        t.class !== o.class && (t.class = Ue([t.class, o.class]));
      else if (s === "style")
        t.style = Cl([t.style, o.style]);
      else if (nn(s)) {
        const i = t[s], a = o[s];
        a && i !== a && !(ce(i) && i.includes(a)) ? t[s] = i ? [].concat(i, a) : a : a == null && i == null && // mergeProps({ 'onUpdate:modelValue': undefined }) should not retain
        // the model listener.
        !sn(s) && (t[s] = a);
      } else s !== "" && (t[s] = o[s]);
  }
  return t;
}
function wt(e, t, l, o = null) {
  bt(e, t, 7, [
    l,
    o
  ]);
}
const wr = /* @__PURE__ */ qo();
let ni = 0;
function _r() {
  return ni;
}
function kr(e, t, l) {
  const o = e.type, s = (t ? t.appContext : e.appContext) || wr, i = {
    uid: ni++,
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
    scope: new ji(
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
    propsOptions: zo(o, s),
    emitsOptions: Fo(o, s),
    // emit
    emit: null,
    // to be set immediately
    emitted: null,
    // props default value
    propsDefaults: ye,
    // inheritAttrs
    inheritAttrs: o.inheritAttrs,
    // state
    ctx: ye,
    data: ye,
    props: ye,
    attrs: ye,
    slots: ye,
    refs: ye,
    setupState: ye,
    setupContext: null,
    // suspense related
    suspense: l,
    suspenseId: l ? l.pendingId : 0,
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
  return i.ctx = { _: i }, i.root = t ? t.root : i, i.emit = er.bind(null, i), e.ce && e.ce(i), i;
}
let Qe = null;
const si = () => Qe || Ge;
let en, Ul;
{
  const e = an(), t = (l, o) => {
    let s;
    return (s = e[l]) || (s = e[l] = []), s.push(o), (i) => {
      s.length > 1 ? s.forEach((a) => a(i)) : s[0](i);
    };
  };
  en = t(
    "__VUE_INSTANCE_SETTERS__",
    (l) => Qe = l
  ), Ul = t(
    "__VUE_SSR_SETTERS__",
    (l) => Pl = l
  );
}
const Ml = (e) => {
  const t = Qe;
  return en(e), e.scope.on(), () => {
    e.scope.off(), en(t);
  };
}, Ns = () => {
  Qe && Qe.scope.off(), en(null);
};
function oi(e) {
  return e.vnode.shapeFlag & 4;
}
let Pl = !1;
function $r(e, t = !1, l = !1) {
  t && Ul(t);
  const { props: o, children: s } = e.vnode, i = oi(e);
  ir(e, o, i, t), dr(e, s, l || t);
  const a = i ? Cr(e, t) : void 0;
  return t && Ul(!1), a;
}
function Cr(e, t) {
  const l = e.type;
  e.accessCache = /* @__PURE__ */ Object.create(null), e.proxy = new Proxy(e.ctx, Ba);
  const { setup: o } = l;
  if (o) {
    xt();
    const s = e.setupContext = o.length > 1 ? Sr(e) : null, i = Ml(e), a = Il(
      o,
      e,
      0,
      [
        e.props,
        s
      ]
    ), r = Zs(a);
    if (St(), i(), (r || e.sp) && !sl(e) && Io(e), r) {
      if (a.then(Ns, Ns), t)
        return a.then((c) => {
          Ul(!0);
          try {
            qs(e, c, t);
          } finally {
            Ul(!1);
          }
        }).catch((c) => {
          dn(c, e, 0, void 0, !0), e.ssrRender = (g, m) => m("<!---->");
        });
      e.asyncDep = a;
    } else
      qs(e, a);
  } else
    ii(e);
}
function qs(e, t, l) {
  fe(t) ? e.type.__ssrInlineRender ? e.ssrRender = t : e.render = t : Se(t) && (e.setupState = $o(t)), ii(e);
}
function ii(e, t, l) {
  const o = e.type;
  e.render || (e.render = o.render || Ct);
  {
    const s = Ml(e);
    xt();
    try {
      Ka(e);
    } finally {
      St(), s();
    }
  }
}
const ai = /* @__PURE__ */ Symbol(), xr = {
  get(e, t) {
    return Ke(e, "get", ""), t === ai ? e : e[t];
  }
};
function Sr(e) {
  const t = (l) => {
    e.exposed = l || {};
  };
  return {
    attrs: new Proxy(e.attrs, xr),
    slots: e.slots,
    emit: e.emit,
    expose: t
  };
}
function gn(e) {
  return e.exposed ? e.exposeProxy || (e.exposeProxy = new Proxy($o(ra(e.exposed)), {
    get(t, l) {
      if (l in t)
        return t[l];
      if (l in kl)
        return kl[l](e);
    },
    has(t, l) {
      return l in t || l in kl;
    }
  })) : e.proxy;
}
function Vr(e) {
  return fe(e) && "__vccOpts" in e;
}
const _e = (e, t) => /* @__PURE__ */ ha(e, t, Pl), Tr = "3.5.46";
let Wn;
const Hs = typeof window < "u" && window.trustedTypes;
if (Hs)
  try {
    Wn = /* @__PURE__ */ Hs.createPolicy("vue", {
      createHTML: (e) => e
    });
  } catch {
  }
const ri = Wn ? (e) => Wn.createHTML(e) : (e) => e, Er = "http://www.w3.org/2000/svg", Ur = "http://www.w3.org/1998/Math/MathML", Ut = typeof document < "u" ? document : null, Fs = Ut && /* @__PURE__ */ Ut.createElement("template"), Pr = {
  insert: (e, t, l) => {
    t.insertBefore(e, l || null);
  },
  remove: (e) => {
    const t = e.parentNode;
    t && t.removeChild(e);
  },
  createElement: (e, t, l, o) => {
    const s = t === "svg" ? Ut.createElementNS(Er, e) : t === "mathml" ? Ut.createElementNS(Ur, e) : l ? Ut.createElement(e, { is: l }) : Ut.createElement(e);
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
  insertStaticContent(e, t, l, o, s, i) {
    const a = l ? l.previousSibling : t.lastChild;
    if (s && (s === i || s.nextSibling))
      for (; t.insertBefore(s.cloneNode(!0), l), !(s === i || !(s = s.nextSibling)); )
        ;
    else {
      Fs.innerHTML = ri(
        o === "svg" ? `<svg>${e}</svg>` : o === "mathml" ? `<math>${e}</math>` : e
      );
      const r = Fs.content;
      if (o === "svg" || o === "mathml") {
        const c = r.firstChild;
        for (; c.firstChild; )
          r.appendChild(c.firstChild);
        r.removeChild(c);
      }
      t.insertBefore(r, l);
    }
    return [
      // first
      a ? a.nextSibling : t.firstChild,
      // last
      l ? l.previousSibling : t.lastChild
    ];
  }
}, Ar = /* @__PURE__ */ Symbol("_vtc");
function Ir(e, t, l) {
  const o = e[Ar];
  o && (t = (t ? [t, ...o] : [...o]).join(" ")), t == null ? e.removeAttribute("class") : l ? e.setAttribute("class", t) : e.className = t;
}
const tn = /* @__PURE__ */ Symbol("_vod"), ui = /* @__PURE__ */ Symbol("_vsh"), Hl = {
  // used for prop mismatch check during hydration
  name: "show",
  beforeMount(e, { value: t }, { transition: l }) {
    e[tn] = e.style.display === "none" ? "" : e.style.display, l && t ? l.beforeEnter(e) : pl(e, t);
  },
  mounted(e, { value: t }, { transition: l }) {
    l && t && l.enter(e);
  },
  updated(e, { value: t, oldValue: l }, { transition: o }) {
    !t != !l && (o ? t ? (o.beforeEnter(e), pl(e, !0), o.enter(e)) : o.leave(e, () => {
      pl(e, !1);
    }) : pl(e, t));
  },
  beforeUnmount(e, { value: t }) {
    pl(e, t);
  }
};
function pl(e, t) {
  e.style.display = t ? e[tn] : "none", e[ui] = !t;
}
const Mr = /* @__PURE__ */ Symbol(""), Or = /(?:^|;)\s*display\s*:/;
function Rr(e, t, l) {
  const o = e.style, s = Ae(l);
  let i = !1;
  if (l && !s) {
    if (t)
      if (Ae(t))
        for (const a of t.split(";")) {
          const r = a.slice(0, a.indexOf(":")).trim();
          l[r] == null && hl(o, r, "");
        }
      else
        for (const a in t)
          l[a] == null && hl(o, a, "");
    for (const a in l) {
      a === "display" && (i = !0);
      const r = l[a];
      r != null ? Nr(
        e,
        a,
        !Ae(t) && t ? t[a] : void 0,
        r
      ) || hl(o, a, r) : hl(o, a, "");
    }
  } else if (s) {
    if (t !== l) {
      const a = o[Mr];
      a && (l += ";" + a), o.cssText = l, i = Or.test(l);
    }
  } else t && e.removeAttribute("style");
  tn in e && ((!s || t !== l) && (e[tn] = i ? o.display : ""), e[ui] && (o.display = "none"));
}
const Fl = /\s*!important$/;
function hl(e, t, l) {
  if (ce(l))
    l.forEach((o) => hl(e, t, o));
  else if (l == null && (l = ""), t.startsWith("--"))
    Fl.test(l) ? e.setProperty(t, l.replace(Fl, ""), "important") : e.setProperty(t, l);
  else {
    const o = Dr(e, t);
    Fl.test(l) ? e.setProperty(
      Dt(o),
      l.replace(Fl, ""),
      "important"
    ) : e[o] = l;
  }
}
const Ls = ["Webkit", "Moz", "ms"], Tn = {};
function Dr(e, t) {
  const l = Tn[t];
  if (l)
    return l;
  let o = at(t);
  if (o !== "filter" && o in e)
    return Tn[t] = o;
  o = lo(o);
  for (let s = 0; s < Ls.length; s++) {
    const i = Ls[s] + o;
    if (i in e)
      return Tn[t] = i;
  }
  return t;
}
function Nr(e, t, l, o) {
  return e.tagName === "TEXTAREA" && (t === "width" || t === "height") && Ae(o) && l === o;
}
const js = "http://www.w3.org/1999/xlink";
function Ws(e, t, l, o, s, i = Hi(t)) {
  o && t.startsWith("xlink:") ? l == null ? e.removeAttributeNS(js, t.slice(6, t.length)) : e.setAttributeNS(js, t, l) : l == null || i && !so(l) ? e.removeAttribute(t) : e.setAttribute(
    t,
    i ? "" : ht(l) ? String(l) : l
  );
}
function Bs(e, t, l, o, s) {
  if (t === "innerHTML" || t === "textContent") {
    l != null && (e[t] = t === "innerHTML" ? ri(l) : l);
    return;
  }
  const i = e.tagName;
  if (t === "value" && i !== "PROGRESS" && // custom elements may use _value internally
  !i.includes("-")) {
    const r = i === "OPTION" ? e.getAttribute("value") || "" : e.value, c = l == null ? (
      // #11647: value should be set as empty string for null and undefined,
      // but <input type="checkbox"> should be set as 'on'.
      e.type === "checkbox" ? "on" : ""
    ) : String(l);
    (r !== c || !("_value" in e)) && (e.value = c), l == null && e.removeAttribute(t), e._value = l;
    return;
  }
  let a = !1;
  if (l === "" || l == null) {
    const r = typeof e[t];
    r === "boolean" ? l = so(l) : l == null && r === "string" ? (l = "", a = !0) : r === "number" && (l = 0, a = !0);
  }
  try {
    e[t] = l;
  } catch {
  }
  a && e.removeAttribute(s || t);
}
function Mt(e, t, l, o) {
  e.addEventListener(t, l, o);
}
function qr(e, t, l, o) {
  e.removeEventListener(t, l, o);
}
const Ks = /* @__PURE__ */ Symbol("_vei");
function Hr(e, t, l, o, s = null) {
  const i = e[Ks] || (e[Ks] = {}), a = i[t];
  if (o && a)
    a.value = o;
  else {
    const [r, c] = jr(t);
    if (o) {
      const g = i[t] = Kr(
        o,
        s
      );
      Mt(e, r, g, c);
    } else a && (qr(e, r, a, c), i[t] = void 0);
  }
}
const Fr = /(Once|Passive|Capture)$/, Lr = /^on:?(?:Once|Passive|Capture)$/;
function jr(e) {
  let t, l;
  for (; (l = e.match(Fr)) && !Lr.test(e); )
    t || (t = {}), e = e.slice(0, e.length - l[1].length), t[l[1].toLowerCase()] = !0;
  return [e[2] === ":" ? e.slice(3) : Dt(e.slice(2)), t];
}
let En = 0;
const Wr = /* @__PURE__ */ Promise.resolve(), Br = () => En || (Wr.then(() => En = 0), En = Date.now());
function Kr(e, t) {
  const l = (o) => {
    if (!o._vts)
      o._vts = Date.now();
    else if (o._vts <= l.attached)
      return;
    const s = l.value;
    if (ce(s)) {
      const i = o.stopImmediatePropagation;
      o.stopImmediatePropagation = () => {
        i.call(o), o._stopped = !0;
      };
      const a = s.slice(), r = [o];
      for (let c = 0; c < a.length && !o._stopped; c++) {
        const g = a[c];
        g && bt(
          g,
          t,
          5,
          r
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
  return l.value = e, l.attached = Br(), l;
}
const Gs = (e) => e.charCodeAt(0) === 111 && e.charCodeAt(1) === 110 && // lowercase letter
e.charCodeAt(2) > 96 && e.charCodeAt(2) < 123, Gr = (e, t, l, o, s, i) => {
  const a = s === "svg";
  t === "class" ? Ir(e, o, a) : t === "style" ? Rr(e, l, o) : nn(t) ? sn(t) || Hr(e, t, l, o, i) : (t[0] === "." ? (t = t.slice(1), !0) : t[0] === "^" ? (t = t.slice(1), !1) : zr(e, t, o, a)) ? (Bs(e, t, o), !e.tagName.includes("-") && (t === "value" || t === "checked" || t === "selected") && Ws(e, t, o, a, i, t !== "value")) : /* #11081 force set props for possible async custom element */ e._isVueCE && // #12408 check if it's declared prop or it's async custom element
  (Jr(e, t) || // @ts-expect-error _def is private
  e._def.__asyncLoader && (/[A-Z]/.test(t) || !Ae(o))) ? Bs(e, at(t), o, i, t) : (t === "true-value" ? e._trueValue = o : t === "false-value" && (e._falseValue = o), Ws(e, t, o, a));
};
function zr(e, t, l, o) {
  if (o)
    return !!(t === "innerHTML" || t === "textContent" || t in e && Gs(t) && fe(l));
  if (t === "spellcheck" || t === "draggable" || t === "translate" || t === "autocorrect" || t === "sandbox" && e.tagName === "IFRAME" || t === "form" || t === "list" && e.tagName === "INPUT" || t === "type" && e.tagName === "TEXTAREA")
    return !1;
  if (t === "width" || t === "height") {
    const s = e.tagName;
    if (s === "IMG" || s === "VIDEO" || s === "CANVAS" || s === "SOURCE")
      return !1;
  }
  return Gs(t) && Ae(l) ? !1 : t in e;
}
function Jr(e, t) {
  const l = (
    // @ts-expect-error _def is private
    e._def.props
  );
  if (!l)
    return !1;
  const o = at(t);
  return Array.isArray(l) ? l.some((s) => at(s) === o) : Object.keys(l).some((s) => at(s) === o);
}
const Kt = (e) => {
  const t = e.props["onUpdate:modelValue"] || !1;
  return ce(t) ? (l) => Bl(t, l) : t;
};
function Yr(e) {
  e.target.composing = !0;
}
function zs(e) {
  const t = e.target;
  t.composing && (t.composing = !1, t.dispatchEvent(new Event("input")));
}
const nt = /* @__PURE__ */ Symbol("_assign"), Ll = /* @__PURE__ */ Symbol("_initialValue");
function Un(e, t, l) {
  return t && (e = e.trim()), l && (e = Al(e)), e;
}
const re = {
  created(e, { modifiers: { lazy: t, trim: l, number: o } }, s) {
    e.parentNode && (e.type === "text" ? e[Ll] = e.defaultValue.replace(/[\r\n]/g, "") : e.type === "textarea" && (e[Ll] = e.defaultValue.replace(/\r\n?/g, `
`))), e[nt] = Kt(s);
    const i = o || s.props && s.props.type === "number";
    Mt(e, t ? "change" : "input", (a) => {
      a.target.composing || e[nt](Un(e.value, l, i));
    }), (l || i) && Mt(e, "change", () => {
      e.value = Un(e.value, l, i);
    }), t || (Mt(e, "compositionstart", Yr), Mt(e, "compositionend", zs), Mt(e, "change", zs));
  },
  // set value on mounted so it's after min/max for type="range"
  mounted(e, { value: t, modifiers: { trim: l, number: o } }) {
    const s = t ?? "", i = e[Ll];
    delete e[Ll], i !== void 0 && (e.type === "text" || e.type === "textarea") && e.value !== i ? e[nt](Un(e.value, l, o)) : e.value = s;
  },
  beforeUpdate(e, { value: t, oldValue: l, modifiers: { lazy: o, trim: s, number: i } }, a) {
    if (e[nt] = Kt(a), e.composing) return;
    const r = (i || e.type === "number") && !/^0\d/.test(e.value) ? Al(e.value) : e.value, c = t ?? "";
    if (r === c)
      return;
    const g = e.getRootNode();
    (g instanceof Document || g instanceof ShadowRoot) && g.activeElement === e && e.type !== "range" && (o && t === l || s && e.value.trim() === c) || (e.value = c);
  }
}, We = {
  // #4096 array checkboxes need to be deep traversed
  deep: !0,
  created(e, t, l) {
    e[nt] = Kt(l), Mt(e, "change", () => {
      const o = e._modelValue, s = al(e), i = e.checked, a = e[nt];
      if (ce(o)) {
        const r = zn(o, s), c = r !== -1;
        if (i && !c)
          a(o.concat(s));
        else if (!i && c) {
          const g = [...o];
          g.splice(r, 1), a(g);
        }
      } else if (Rt(o)) {
        const r = new Set(o);
        i ? r.add(s) : r.delete(s), a(r);
      } else
        a(di(e, i));
    });
  },
  // set initial checked on mount to wait for true-value/false-value
  mounted: Js,
  beforeUpdate(e, t, l) {
    e[nt] = Kt(l), Js(e, t, l);
  }
};
function Js(e, { value: t, oldValue: l }, o) {
  e._modelValue = t;
  let s;
  if (ce(t))
    s = zn(t, o.props.value) > -1;
  else if (Rt(t))
    s = t.has(o.props.value);
  else {
    if (t === l) return;
    s = mt(t, di(e, !0));
  }
  e.checked !== s && (e.checked = s);
}
const Xr = {
  created(e, { value: t }, l) {
    e.checked = mt(t, l.props.value), e[nt] = Kt(l), Mt(e, "change", () => {
      e[nt](al(e));
    });
  },
  beforeUpdate(e, { value: t, oldValue: l }, o) {
    e[nt] = Kt(o), t !== l && (e.checked = mt(t, o.props.value));
  }
}, xe = {
  // <select multiple> value need to be deep traversed
  deep: !0,
  created(e, { value: t, modifiers: { number: l } }, o) {
    e._modelValue = t, Mt(e, "change", () => {
      const s = Array.prototype.filter.call(e.options, (c) => c.selected).map(
        (c) => l ? Al(al(c)) : al(c)
      ), i = e.multiple, a = i ? Rt(e._modelValue) ? new Set(s) : s : s[0], r = e._pendingValue = [
        i,
        i ? ce(a) ? s.slice() : s : a
      ];
      try {
        e[nt](a);
      } finally {
        ls(() => {
          e._pendingValue === r && (e._pendingValue = void 0);
        });
      }
    }), e[nt] = Kt(o);
  },
  // set value in mounted & updated because <select> relies on its children
  // <option>s.
  mounted(e, { value: t, modifiers: { number: l } }) {
    Ys(e, t, l);
  },
  beforeUpdate(e, { value: t }, l) {
    e._modelValue = t, e[nt] = Kt(l);
  },
  updated(e, { value: t, modifiers: { number: l } }) {
    const o = e._pendingValue;
    e._pendingValue = void 0, (!o || o[0] !== e.multiple || !Qr(t, o[1], o[0])) && Ys(e, t, l);
  }
};
function Qr(e, t, l) {
  if (!l || ce(e)) return mt(e, t);
  if (Rt(e)) {
    if (e.size !== t.length) return !1;
    for (const o of t)
      if (!e.has(o)) return !1;
    return !0;
  }
  return !1;
}
function Ys(e, t, l = !1) {
  const o = e.multiple, s = ce(t);
  if (!(o && !s && !Rt(t))) {
    for (let i = 0, a = e.options.length; i < a; i++) {
      const r = e.options[i], c = al(r);
      if (o)
        if (s) {
          const g = typeof c;
          g === "string" || g === "number" ? r.selected = t.some((m) => String(m) === String(c)) : r.selected = zn(t, c) > -1;
        } else
          r.selected = t.has(c) || l && typeof c == "string" && t.has(Al(c));
      else if (mt(al(r), t)) {
        e.selectedIndex !== i && (e.selectedIndex = i);
        return;
      }
    }
    !o && e.selectedIndex !== -1 && (e.selectedIndex = -1);
  }
}
function al(e) {
  return "_value" in e ? e._value : e.value;
}
function di(e, t) {
  const l = t ? "_trueValue" : "_falseValue";
  return l in e ? e[l] : t;
}
const Zr = {
  created(e, t, l) {
    jl(e, t, l, null, "created");
  },
  mounted(e, t, l) {
    jl(e, t, l, null, "mounted");
  },
  beforeUpdate(e, t, l, o) {
    jl(e, t, l, o, "beforeUpdate");
  },
  updated(e, t, l, o) {
    jl(e, t, l, o, "updated");
  }
};
function eu(e, t) {
  switch (e) {
    case "SELECT":
      return xe;
    case "TEXTAREA":
      return re;
    default:
      switch (t) {
        case "checkbox":
          return We;
        case "radio":
          return Xr;
        default:
          return re;
      }
  }
}
function jl(e, t, l, o, s) {
  const a = eu(
    e.tagName,
    l.props && l.props.type
  )[s];
  a && a(e, t, l, o);
}
const tu = ["ctrl", "shift", "alt", "meta"], lu = {
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
  exact: (e, t) => tu.some((l) => e[`${l}Key`] && !t.includes(l))
}, Ze = (e, t) => {
  if (!e) return e;
  const l = e._withMods || (e._withMods = {}), o = t.join(".");
  return l[o] || (l[o] = ((s, ...i) => {
    for (let a = 0; a < t.length; a++) {
      const r = lu[t[a]];
      if (r && r(s, t)) return;
    }
    return e(s, ...i);
  }));
}, nu = {
  esc: "escape",
  space: " ",
  up: "arrow-up",
  left: "arrow-left",
  right: "arrow-right",
  down: "arrow-down",
  delete: "backspace"
}, ln = (e, t) => {
  const l = e._withKeys || (e._withKeys = {}), o = t.join(".");
  return l[o] || (l[o] = ((s) => {
    if (!("key" in s))
      return;
    const i = Dt(s.key);
    if (t.some(
      (a) => a === i || nu[a] === i
    ))
      return e(s);
  }));
}, su = /* @__PURE__ */ De({ patchProp: Gr }, Pr);
let Xs;
function ou() {
  return Xs || (Xs = fr(su));
}
const iu = ((...e) => {
  const t = ou().createApp(...e), { mount: l } = t;
  return t.mount = (o) => {
    const s = ru(o);
    if (!s) return;
    const i = t._component;
    !fe(i) && !i.render && !i.template && (i.template = s.innerHTML), s.nodeType === 1 && (s.textContent = "");
    const a = l(s, !1, au(s));
    return s instanceof Element && (s.removeAttribute("v-cloak"), s.setAttribute("data-v-app", "")), a;
  }, t;
});
function au(e) {
  if (e instanceof SVGElement)
    return "svg";
  if (typeof MathMLElement == "function" && e instanceof MathMLElement)
    return "mathml";
}
function ru(e) {
  return Ae(e) ? document.querySelector(e) : e;
}
const uu = [
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
], du = ["title"], cu = { class: "gw-project-links" }, fu = ["aria-label", "href"], pu = ["href", "title"], ds = /* @__PURE__ */ He({
  __name: "ProjectInfo",
  props: {
    id: {},
    compact: { type: Boolean },
    help: { type: Boolean }
  },
  emits: ["help"],
  setup(e, { emit: t }) {
    const l = e, o = t, s = _e(() => uu.find((a) => a.id === l.id)), i = _e(() => s.value?.repository.split("/")[0]);
    return (a, r) => s.value ? (p(), h("div", {
      key: 0,
      class: Ue(["gw-project-info", { compact: e.compact }])
    }, [
      n("p", {
        title: s.value.description
      }, w(s.value.description), 9, du),
      n("div", cu, [
        n("a", {
          "aria-label": "Автор проекта: " + s.value.author,
          href: "https://github.com/" + i.value,
          target: "_blank",
          rel: "noopener noreferrer"
        }, w(s.value.author), 9, fu),
        r[1] || (r[1] = n("span", { "aria-hidden": "true" }, "·", -1)),
        n("a", {
          href: "https://github.com/" + s.value.repository,
          title: s.value.repository,
          target: "_blank",
          rel: "noopener noreferrer"
        }, "GitHub ↗", 8, pu),
        e.help ? (p(), h("button", {
          key: 0,
          type: "button",
          onClick: r[0] || (r[0] = (c) => o("help"))
        }, "Помощь")) : V("", !0)
      ])
    ], 2)) : V("", !0);
  }
}), vu = { class: "gw-shell gw-dialog-overlay" }, gu = ["aria-label"], hu = { class: "gw-dialog-header" }, mu = ["disabled"], qe = /* @__PURE__ */ He({
  __name: "GatewayDialog",
  props: {
    title: {},
    busy: { type: Boolean },
    wide: { type: Boolean },
    compact: { type: Boolean }
  },
  emits: ["close"],
  setup(e, { emit: t }) {
    const l = e, o = t, s = /* @__PURE__ */ H();
    let i = null;
    function a() {
      l.busy || o("close");
    }
    function r(c) {
      if (c.key === "Escape" && (c.preventDefault(), c.stopImmediatePropagation(), a()), c.key !== "Tab" || !s.value) return;
      const g = [...s.value.querySelectorAll('button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea:not(:disabled),a[href],summary,[tabindex="0"]')].filter((T) => T.getClientRects().length), m = g[0], y = g[g.length - 1];
      if (!m) {
        c.preventDefault(), s.value.focus();
        return;
      }
      c.shiftKey && (document.activeElement === m || document.activeElement === s.value) ? (c.preventDefault(), y.focus()) : !c.shiftKey && (document.activeElement === y || !s.value.contains(document.activeElement)) && (c.preventDefault(), m.focus());
    }
    return ct(async () => {
      i = document.activeElement, document.addEventListener("keydown", r, !0), await ls(), s.value?.focus();
    }), qt(() => {
      document.removeEventListener("keydown", r, !0), i?.isConnected && i.focus();
    }), (c, g) => (p(), ge(Pa, { to: "body" }, [
      n("div", vu, [
        n("section", {
          ref_key: "dialog",
          ref: s,
          class: Ue(["gw-panel gw-dialog", { "gw-dialog-wide": e.wide, "gw-dialog-compact": e.compact }]),
          role: "dialog",
          "aria-modal": "true",
          "aria-label": e.title,
          tabindex: "-1"
        }, [
          n("header", hu, [
            n("h2", null, w(e.title), 1),
            n("button", {
              type: "button",
              "aria-label": "Закрыть диалог",
              disabled: e.busy,
              onClick: a
            }, "×", 8, mu)
          ]),
          Wa(c.$slots, "default")
        ], 10, gu)
      ])
    ]));
  }
}), bu = {
  key: 0,
  class: "gw-error"
}, yu = { key: 1 }, wu = { class: "gw-notice" }, _u = {
  key: 0,
  class: "gw-error"
}, ku = { class: "gw-setup-steps" }, $u = {
  key: 1,
  class: "gw-notice"
}, Cu = { class: "gw-actions" }, xu = ["disabled"], Su = ["href"], Vu = { class: "gw-hint" }, Tu = ["href"], Eu = /* @__PURE__ */ He({
  __name: "AdGuardSetup",
  props: {
    node: {},
    bridge: {}
  },
  emits: ["close", "install", "start"],
  setup(e, { emit: t }) {
    const l = e, o = t, s = /* @__PURE__ */ H(null), i = /* @__PURE__ */ H(""), a = (r) => "http://" + (l.node.host.includes(":") ? "[" + l.node.host + "]" : l.node.host) + ":" + r + "/";
    return ct(async () => {
      try {
        s.value = await l.bridge.request("/api/gateways/" + encodeURIComponent(l.node.id) + "/adguard");
      } catch (r) {
        i.value = r.message;
      }
    }), (r, c) => (p(), ge(qe, {
      title: "AdGuard Home: установка и настройка DNS",
      wide: !0,
      onClose: c[2] || (c[2] = (g) => o("close"))
    }, {
      default: Re(() => [
        Ee(ds, { id: "adguardhome" }),
        i.value ? (p(), h("p", bu, w(i.value), 1)) : V("", !0),
        !s.value && !i.value ? (p(), h("p", yu, "Проверяем роутер…")) : V("", !0),
        s.value ? (p(), h(N, { key: 2 }, [
          n("div", wu, [
            n("strong", null, w(s.value.installed ? "AdGuard Home установлен" : "Установка из официального GitHub-релиза"), 1),
            n("p", null, "Свободное место: " + w(s.value.free_bytes == null ? "Не определено" : (s.value.free_bytes / 1048576).toFixed(0) + " МБ") + ". Бинарный файл и журнал запросов требуют места; для небольшого flash рекомендуется внешнее хранилище.", 1),
            n("p", null, "Занятые порты: " + w(s.value.occupied_ports.filter((g) => [53, 54, 80, 443, 3e3, 5353, 8080].includes(g.port)).map((g) => g.port + "/" + g.protocol).join(", ") || "Не обнаружены") + ".", 1)
          ]),
          s.value.setup_port_busy && !s.value.configured ? (p(), h("p", _u, "Порт 3000 занят. Перед первым запуском освободите его через консоль или настройки службы.")) : V("", !0),
          n("ol", ku, [
            (p(!0), h(N, null, se(s.value.steps, (g, m) => (p(), h("li", { key: m }, w(g), 1))), 128))
          ]),
          s.value.dns_dependencies.length ? (p(), h("p", $u, "Найдены зависимости DNS: " + w(s.value.dns_dependencies.join("; ")) + ". До их изменения остановка и удаление сервиса запрещены.", 1)) : V("", !0),
          n("div", Cu, [
            s.value.installed ? e.node.monitor.services?.some((g) => g.id === "adguardhome" && g.running) ? V("", !0) : (p(), h("button", {
              key: 1,
              disabled: s.value.setup_port_busy && !s.value.configured,
              class: "gw-primary",
              onClick: c[1] || (c[1] = (g) => o("start"))
            }, "Запустить сервис", 8, xu)) : (p(), h("button", {
              key: 0,
              class: "gw-primary",
              onClick: c[0] || (c[0] = (g) => o("install"))
            }, "Выбрать версию и установить")),
            s.value.installed ? (p(), h("a", {
              key: 2,
              href: a(s.value.web_port),
              target: "_blank",
              rel: "noopener noreferrer"
            }, w(s.value.configured ? "Открыть AdGuard Home" : "Открыть мастер на порту 3000") + " ↗", 9, Su)) : V("", !0)
          ]),
          n("p", Vu, [
            c[3] || (c[3] = A("Официальные инструкции: ", -1)),
            (p(!0), h(N, null, se(s.value.sources, (g) => (p(), h("a", {
              key: g.url,
              href: g.url,
              target: "_blank",
              rel: "noopener noreferrer"
            }, w(g.name) + " ↗ ", 9, Tu))), 128))
          ])
        ], 64)) : V("", !0)
      ]),
      _: 1
    }));
  }
}), Uu = {
  key: 0,
  class: "gw-error",
  role: "alert"
}, Pu = { class: "gw-change-list" }, Au = {
  key: 0,
  class: "gw-notice"
}, Iu = { class: "gw-notice" }, Mu = { class: "gw-actions" }, Ou = ["disabled"], Ru = ["disabled"], Du = { class: "gw-check" }, Nu = {
  key: 0,
  class: "gw-notice"
}, qu = { class: "gw-two" }, Hu = ["disabled"], Fu = ["disabled"], Lu = { key: 0 }, ju = ["value"], Wu = ["value"], Bu = {
  key: 1,
  class: "gw-notice"
}, Ku = { class: "gw-two" }, Gu = { class: "gw-check" }, zu = { class: "gw-two" }, Ju = { class: "gw-check" }, Yu = { class: "gw-check" }, Xu = { class: "gw-check" }, Qu = {
  key: 0,
  class: "gw-notice"
}, Zu = {
  class: "gw-tabs",
  "aria-label": "Разделы firewall"
}, ed = { class: "gw-policy-grid" }, td = ["onUpdate:modelValue"], ld = { class: "gw-policy-grid" }, nd = ["onUpdate:modelValue"], sd = { class: "gw-two" }, od = ["onUpdate:modelValue"], id = ["onUpdate:modelValue"], ad = ["open", "onInput", "onChange"], rd = { class: "gw-rule-fields" }, ud = ["onClick"], dd = {
  key: 0,
  class: "gw-hint"
}, cd = ["onUpdate:modelValue"], fd = { class: "gw-two" }, pd = ["onUpdate:modelValue"], vd = ["value"], gd = ["onUpdate:modelValue"], hd = ["value"], md = { class: "gw-two" }, bd = ["onUpdate:modelValue"], yd = ["value"], wd = ["onUpdate:modelValue"], _d = { class: "gw-two" }, kd = ["onUpdate:modelValue"], $d = ["onUpdate:modelValue"], Cd = {
  key: 0,
  class: "gw-hint"
}, xd = { class: "gw-section-header" }, Sd = ["disabled"], Vd = {
  key: 0,
  class: "gw-notice"
}, Td = {
  key: 1,
  class: "gw-hint"
}, Ed = ["open", "onInput", "onChange"], Ud = { class: "gw-rule-fields" }, Pd = ["onClick"], Ad = ["onUpdate:modelValue"], Id = { class: "gw-two" }, Md = ["onUpdate:modelValue"], Od = ["value"], Rd = ["onUpdate:modelValue"], Dd = ["value"], Nd = { class: "gw-two" }, qd = ["onUpdate:modelValue"], Hd = ["onUpdate:modelValue"], Fd = { class: "gw-two" }, Ld = ["onUpdate:modelValue"], jd = ["onUpdate:modelValue"], Wd = ["onUpdate:modelValue"], Bd = { class: "gw-two" }, Kd = ["onUpdate:modelValue"], Gd = ["onUpdate:modelValue"], zd = {
  key: 2,
  class: "gw-hint"
}, Jd = { class: "gw-actions" }, Yd = ["disabled"], Xd = ["disabled"], Qd = { key: 3 }, ci = /* @__PURE__ */ He({
  __name: "RouterSettings",
  props: {
    node: {},
    bridge: {},
    mode: {},
    iface: {}
  },
  emits: ["close", "changed"],
  setup(e, { emit: t }) {
    const l = e, o = t, s = /* @__PURE__ */ H(null), i = /* @__PURE__ */ H({}), a = /* @__PURE__ */ H(null), r = /* @__PURE__ */ H(!1), c = /* @__PURE__ */ H(""), g = /* @__PURE__ */ H("general"), m = /* @__PURE__ */ H([]), y = /* @__PURE__ */ H(/* @__PURE__ */ new Set()), T = /* @__PURE__ */ H([]), E = /* @__PURE__ */ H(/* @__PURE__ */ new Set()), B = ["id", "name", "src", "dest", "src_ip", "dest_ip", "proto", "src_dport", "dest_port", "enabled", "reflection"], I = { dhcp: "DHCP-сервер", dns: "DNS роутера", firewall: "Настройки firewall" }, Q = (U) => String(U || "").split(/[\s,]+/).filter(Boolean), X = (U) => Array.isArray(U) ? U.join(", ") : U || "", Z = () => "/api/gateways/" + encodeURIComponent(l.node.id), le = (U, d, u = "POST") => l.bridge.request(Z() + U, { method: u, headers: { "Content-Type": "application/json" }, body: JSON.stringify(d) });
    function j(U) {
      const d = s.value.dns.find((u) => u.id === U) || {};
      i.value = { ...d, port: d.port ?? "53", server: X(d.server), cachesize: d.cachesize ?? "150", domain: d.domain || "", local: d.local || "", noresolv: d.noresolv === "1", rebind_protection: d.rebind_protection !== "0", domainneeded: d.domainneeded === "1", boguspriv: d.boguspriv !== "0" };
    }
    async function te() {
      r.value = !0;
      try {
        if (s.value = await l.bridge.request(Z() + "/network"), l.mode === "dns") j(s.value.dns[0]?.id);
        else if (l.mode === "dhcp") {
          const U = s.value.dhcp.find((d) => d.interface === l.iface);
          i.value = { ignore: !U || U.ignore === "1", start: U?.start ?? "100", limit: U?.limit ?? "150", leasetime: U?.leasetime || "12h", dns: X(U?.dns) };
        } else {
          const U = s.value.firewall;
          i.value = { redirectsSupported: Array.isArray(U.redirects), redirects: (U.redirects || []).filter((d) => !d.target || d.target === "DNAT").map((d) => ({ ...d })), defaults: { input: "REJECT", output: "ACCEPT", forward: "REJECT", ...U.defaults }, zones: U.zones.map((d) => ({ ...d })), rules: U.rules.map((d) => ({ ...d, editable: !d.target || ["ACCEPT", "REJECT", "DROP"].includes(d.target) })) };
        }
      } catch (U) {
        c.value = U.message;
      } finally {
        r.value = !1;
      }
    }
    function O(U) {
      const d = i.value.rules[U];
      d.id && m.value.push(d.id), i.value.rules.splice(U, 1);
    }
    function S(U) {
      U.id && y.value.add(U.id);
    }
    function k() {
      g.value = "rules", i.value.rules.push({ name: "", src: "lan", dest: "", proto: "tcp", dest_port: "", target: "ACCEPT", enabled: "1", editable: !0 });
    }
    function R() {
      g.value = "redirects", i.value.redirects.push({ name: "", src: "wan", dest: "lan", proto: ["tcp", "udp"], src_dport: "", dest_ip: "", dest_port: "", enabled: "1", reflection: "1" });
    }
    function z(U) {
      const d = i.value.redirects[U];
      d.id && T.value.push(d.id), i.value.redirects.splice(U, 1);
    }
    function pe(U) {
      U.id && E.value.add(U.id);
    }
    function he(U, d) {
      const u = {};
      for (const v of d) U[v] !== void 0 && (u[v] = U[v] === "" ? null : U[v]);
      return u;
    }
    async function Pe(U = l.mode) {
      r.value = !0, c.value = "";
      try {
        const d = { config_hash: s.value.settings_hash }, u = i.value;
        U === "dhcp" && Object.assign(d, { interface: l.iface, settings: { ignore: u.ignore ? "1" : "0", start: String(u.start), limit: String(u.limit), leasetime: u.leasetime, dns: Q(u.dns) } }), U === "dns" && Object.assign(d, { section: u.id, settings: { port: String(u.port), server: Q(u.server), cachesize: String(u.cachesize), domain: u.domain || null, local: u.local || null, noresolv: u.noresolv ? "1" : "0", rebind_protection: u.rebind_protection ? "1" : "0", domainneeded: u.domainneeded ? "1" : "0", boguspriv: u.boguspriv ? "1" : "0" } }), U === "firewall" && Object.assign(d, { settings: he(u.defaults, ["input", "output", "forward", "synflood_protect"]), zones: u.zones.map((v) => he(v, ["id", "input", "output", "forward", "masq", "mtu_fix"])), rules: u.rules.filter((v) => !v.id || y.value.has(v.id)).map((v) => he(v, ["id", "name", "src", "dest", "src_ip", "dest_ip", "proto", "dest_port", "target", "enabled"])), deleted_rules: m.value }), U === "firewall" && u.redirectsSupported && Object.assign(d, { redirects: u.redirects.filter((v) => !v.id || E.value.has(v.id)).map((v) => he(v, B)), deleted_redirects: T.value }), a.value = await le("/network/plan", { action: U, data: d });
      } catch (d) {
        c.value = d.message;
      } finally {
        r.value = !1;
      }
    }
    async function Me() {
      r.value = !0;
      try {
        const U = a.value, d = await le("/router-operations", { plan_token: U.plan_token, confirmed: !0 });
        a.value = null, o("close"), l.bridge.task({ taskId: d.task_id, title: U.title, cancellable: !1, onDone: async () => o("changed") });
      } catch (U) {
        c.value = U.message;
      } finally {
        r.value = !1;
      }
    }
    function ne() {
      const U = a.value?.plan_token;
      a.value = null, c.value = "", U && le("/operation-plans/" + encodeURIComponent(U), {}, "DELETE").catch((d) => {
        c.value = d.message;
      });
    }
    return ct(() => {
      te();
    }), (U, d) => (p(), ge(qe, {
      title: a.value ? "Проверка изменений" : I[e.mode] + (e.iface ? " · " + e.iface : ""),
      wide: !0,
      busy: r.value,
      onClose: d[21] || (d[21] = (u) => a.value ? ne() : o("close"))
    }, {
      default: Re(() => [
        c.value ? (p(), h("p", Uu, w(c.value), 1)) : V("", !0),
        a.value ? (p(), h(N, { key: 1 }, [
          n("ul", Pu, [
            (p(!0), h(N, null, se(a.value.summary, (u, v) => (p(), h("li", { key: v }, w(u), 1))), 128))
          ]),
          a.value.warnings?.length ? (p(), h("section", Au, [
            d[22] || (d[22] = n("h3", null, "Последствия изменений", -1)),
            n("ul", null, [
              (p(!0), h(N, null, se(a.value.warnings, (u, v) => (p(), h("li", { key: v }, w(u), 1))), 128))
            ])
          ])) : V("", !0),
          n("p", Iu, "Если панель не подтвердит результат в течение " + w(a.value.rollback_seconds) + " секунд, роутер вернёт прежнюю конфигурацию. Изменения, сделанные параллельно в LuCI, не будут перезаписаны.", 1),
          n("div", Mu, [
            n("button", {
              class: "gw-primary",
              disabled: r.value,
              onClick: Me
            }, "Да, применить", 8, Ou),
            n("button", {
              disabled: r.value,
              onClick: ne
            }, "Назад", 8, Ru)
          ])
        ], 64)) : s.value ? (p(), h("form", {
          key: 2,
          class: "gw-form",
          onSubmit: d[20] || (d[20] = Ze((u) => Pe(), ["prevent"]))
        }, [
          e.mode === "dhcp" ? (p(), h(N, { key: 0 }, [
            n("label", Du, [
              F(n("input", {
                "onUpdate:modelValue": d[0] || (d[0] = (u) => i.value.ignore = u),
                type: "checkbox"
              }, null, 512), [
                [We, i.value.ignore]
              ]),
              A(" Выключить DHCP-сервер на " + w(e.iface), 1)
            ]),
            i.value.ignore ? V("", !0) : (p(), h("p", Nu, "В одном сегменте должен работать один DHCP-сервер. При наличии основного роутера оставьте DHCP здесь выключенным.")),
            n("div", qu, [
              n("label", null, [
                d[23] || (d[23] = A("Начальный адрес (смещение в подсети)", -1)),
                F(n("input", {
                  "onUpdate:modelValue": d[1] || (d[1] = (u) => i.value.start = u),
                  type: "number",
                  min: "0",
                  disabled: i.value.ignore,
                  required: ""
                }, null, 8, Hu), [
                  [re, i.value.start]
                ])
              ]),
              n("label", null, [
                d[24] || (d[24] = A("Количество адресов", -1)),
                F(n("input", {
                  "onUpdate:modelValue": d[2] || (d[2] = (u) => i.value.limit = u),
                  type: "number",
                  min: "1",
                  disabled: i.value.ignore,
                  required: ""
                }, null, 8, Fu), [
                  [re, i.value.limit]
                ])
              ])
            ]),
            n("label", null, [
              d[25] || (d[25] = A("Время аренды", -1)),
              F(n("input", {
                "onUpdate:modelValue": d[3] || (d[3] = (u) => i.value.leasetime = u),
                placeholder: "12h"
              }, null, 512), [
                [re, i.value.leasetime]
              ])
            ]),
            n("label", null, [
              d[26] || (d[26] = A("DNS для DHCP-клиентов (IPv4)", -1)),
              F(n("input", {
                "onUpdate:modelValue": d[4] || (d[4] = (u) => i.value.dns = u),
                placeholder: "Пусто — адрес роутера"
              }, null, 512), [
                [re, i.value.dns]
              ]),
              d[27] || (d[27] = n("small", null, "Меняется только DHCP option 6. Другие опции, статические аренды и настройки IPv6 сохраняются. Клиенты получат изменение при обновлении аренды.", -1))
            ])
          ], 64)) : V("", !0),
          e.mode === "dns" ? (p(), h(N, { key: 1 }, [
            d[40] || (d[40] = n("p", { class: "gw-hint" }, "DNS подключения WAN задаётся в его настройках. Здесь — локальный DNS-сервис dnsmasq и серверы, на которые он отправляет запросы.", -1)),
            s.value.dns.length > 1 ? (p(), h("label", Lu, [
              d[28] || (d[28] = A("Экземпляр dnsmasq", -1)),
              n("select", {
                value: i.value.id,
                onChange: d[5] || (d[5] = (u) => j(u.target.value))
              }, [
                (p(!0), h(N, null, se(s.value.dns, (u) => (p(), h("option", {
                  key: u.id,
                  value: u.id
                }, w(u.id), 9, Wu))), 128))
              ], 40, ju)
            ])) : V("", !0),
            s.value.dns.length ? (p(), h(N, { key: 2 }, [
              n("div", Ku, [
                n("label", null, [
                  d[29] || (d[29] = A("Порт DNS", -1)),
                  F(n("input", {
                    "onUpdate:modelValue": d[6] || (d[6] = (u) => i.value.port = u),
                    type: "number",
                    min: "0",
                    max: "65535",
                    required: ""
                  }, null, 512), [
                    [re, i.value.port]
                  ]),
                  d[30] || (d[30] = n("small", null, "53 — обычный DNS; 0 отключает только DNS.", -1))
                ]),
                n("label", null, [
                  d[31] || (d[31] = A("Размер кэша", -1)),
                  F(n("input", {
                    "onUpdate:modelValue": d[7] || (d[7] = (u) => i.value.cachesize = u),
                    type: "number",
                    min: "0",
                    required: ""
                  }, null, 512), [
                    [re, i.value.cachesize]
                  ])
                ])
              ]),
              n("label", null, [
                d[32] || (d[32] = A("Внешние DNS-серверы", -1)),
                F(n("textarea", {
                  "onUpdate:modelValue": d[8] || (d[8] = (u) => i.value.server = u),
                  rows: "3",
                  placeholder: `1.1.1.1
127.0.0.1#5353
/example.org/192.168.1.2`
                }, null, 512), [
                  [re, i.value.server]
                ]),
                d[33] || (d[33] = n("small", null, "По одному серверу на строку; адрес#порт, /домен/адрес#порт.", -1))
              ]),
              n("label", Gu, [
                F(n("input", {
                  "onUpdate:modelValue": d[9] || (d[9] = (u) => i.value.noresolv = u),
                  type: "checkbox"
                }, null, 512), [
                  [We, i.value.noresolv]
                ]),
                d[34] || (d[34] = A(" Использовать только указанные upstream (не получать DNS от WAN)", -1))
              ]),
              n("div", zu, [
                n("label", null, [
                  d[35] || (d[35] = A("Локальный домен", -1)),
                  F(n("input", {
                    "onUpdate:modelValue": d[10] || (d[10] = (u) => i.value.domain = u),
                    placeholder: "lan"
                  }, null, 512), [
                    [re, i.value.domain]
                  ])
                ]),
                n("label", null, [
                  d[36] || (d[36] = A("Локальная зона", -1)),
                  F(n("input", {
                    "onUpdate:modelValue": d[11] || (d[11] = (u) => i.value.local = u),
                    placeholder: "/lan/"
                  }, null, 512), [
                    [re, i.value.local]
                  ])
                ])
              ]),
              n("label", Ju, [
                F(n("input", {
                  "onUpdate:modelValue": d[12] || (d[12] = (u) => i.value.rebind_protection = u),
                  type: "checkbox"
                }, null, 512), [
                  [We, i.value.rebind_protection]
                ]),
                d[37] || (d[37] = A(" Защита DNS rebinding", -1))
              ]),
              n("label", Yu, [
                F(n("input", {
                  "onUpdate:modelValue": d[13] || (d[13] = (u) => i.value.domainneeded = u),
                  type: "checkbox"
                }, null, 512), [
                  [We, i.value.domainneeded]
                ]),
                d[38] || (d[38] = A(" Не отправлять имена без домена", -1))
              ]),
              n("label", Xu, [
                F(n("input", {
                  "onUpdate:modelValue": d[14] || (d[14] = (u) => i.value.boguspriv = u),
                  type: "checkbox"
                }, null, 512), [
                  [We, i.value.boguspriv]
                ]),
                d[39] || (d[39] = A(" Не отправлять обратные запросы частных адресов", -1))
              ]),
              i.value.nftset || i.value.ipset ? (p(), h("p", Qu, "dnsmasq использует наборы для маршрутизации. При переходе на AdGuard Home сохраните путь запросов через dnsmasq для нужных доменов.")) : V("", !0)
            ], 64)) : (p(), h("p", Bu, "dnsmasq не настроен. Сначала установите или настройте его в LuCI."))
          ], 64)) : V("", !0),
          e.mode === "firewall" ? (p(), h(N, { key: 2 }, [
            d[85] || (d[85] = n("p", { class: "gw-hint" }, "Основные политики, зоны, правила трафика и перенаправления портов. Расширенные параметры и специальные правила NAT сохраняются.", -1)),
            n("nav", Zu, [
              n("button", {
                type: "button",
                class: Ue({ on: g.value === "general" }),
                onClick: d[15] || (d[15] = (u) => g.value = "general")
              }, "Общие настройки", 2),
              n("button", {
                type: "button",
                class: Ue({ on: g.value === "zones" }),
                onClick: d[16] || (d[16] = (u) => g.value = "zones")
              }, "Зоны (" + w(i.value.zones.length) + ")", 3),
              n("button", {
                type: "button",
                class: Ue({ on: g.value === "rules" }),
                onClick: d[17] || (d[17] = (u) => g.value = "rules")
              }, "Правила трафика (" + w(i.value.rules.length) + ")", 3),
              n("button", {
                type: "button",
                class: Ue({ on: g.value === "redirects" }),
                onClick: d[18] || (d[18] = (u) => g.value = "redirects")
              }, "Перенаправление портов (" + w(i.value.redirects.length) + ")", 3)
            ]),
            F(n("section", null, [
              d[42] || (d[42] = n("h3", null, "Политики по умолчанию", -1)),
              d[43] || (d[43] = n("p", { class: "gw-hint" }, "Применяются к трафику, для которого не задано отдельное правило.", -1)),
              n("div", ed, [
                (p(), h(N, null, se(["input", "output", "forward"], (u) => n("label", { key: u }, [
                  A(w({ input: "Входящие", output: "Исходящие", forward: "Пересылка" }[u]), 1),
                  F(n("select", {
                    "onUpdate:modelValue": (v) => i.value.defaults[u] = v
                  }, [...d[41] || (d[41] = [
                    n("option", null, "ACCEPT", -1),
                    n("option", null, "REJECT", -1),
                    n("option", null, "DROP", -1)
                  ])], 8, td), [
                    [xe, i.value.defaults[u]]
                  ])
                ])), 64))
              ])
            ], 512), [
              [Hl, g.value === "general"]
            ]),
            F(n("section", null, [
              d[49] || (d[49] = n("h3", null, "Зоны", -1)),
              d[50] || (d[50] = n("p", { class: "gw-hint" }, "Политики для групп сетевых интерфейсов. Правила отдельных соединений находятся на вкладке «Правила трафика».", -1)),
              (p(!0), h(N, null, se(i.value.zones, (u) => (p(), h("article", {
                key: u.id,
                class: "gw-settings-row"
              }, [
                n("h4", null, w(u.name) + " · " + w(X(u.network)), 1),
                n("div", ld, [
                  (p(), h(N, null, se(["input", "output", "forward"], (v) => n("label", { key: v }, [
                    A(w({ input: "Входящие", output: "Исходящие", forward: "Пересылка" }[v]), 1),
                    F(n("select", {
                      "onUpdate:modelValue": (_) => u[v] = _
                    }, [...d[44] || (d[44] = [
                      n("option", null, "ACCEPT", -1),
                      n("option", null, "REJECT", -1),
                      n("option", null, "DROP", -1)
                    ])], 8, nd), [
                      [xe, u[v]]
                    ])
                  ])), 64))
                ]),
                n("div", sd, [
                  n("label", null, [
                    d[46] || (d[46] = A("NAT (маскарадинг)", -1)),
                    F(n("select", {
                      "onUpdate:modelValue": (v) => u.masq = v
                    }, [...d[45] || (d[45] = [
                      n("option", { value: void 0 }, "По умолчанию", -1),
                      n("option", { value: "1" }, "Включён", -1),
                      n("option", { value: "0" }, "Выключен", -1)
                    ])], 8, od), [
                      [xe, u.masq]
                    ])
                  ]),
                  n("label", null, [
                    d[48] || (d[48] = A("Коррекция MSS", -1)),
                    F(n("select", {
                      "onUpdate:modelValue": (v) => u.mtu_fix = v
                    }, [...d[47] || (d[47] = [
                      n("option", { value: void 0 }, "По умолчанию", -1),
                      n("option", { value: "1" }, "Включён", -1),
                      n("option", { value: "0" }, "Выключен", -1)
                    ])], 8, id), [
                      [xe, u.mtu_fix]
                    ])
                  ])
                ])
              ]))), 128))
            ], 512), [
              [Hl, g.value === "zones"]
            ]),
            F(n("section", null, [
              n("header", { class: "gw-section-header" }, [
                d[51] || (d[51] = n("h3", null, "Правила трафика", -1)),
                n("button", {
                  type: "button",
                  onClick: k
                }, "Добавить правило")
              ]),
              (p(!0), h(N, null, se(i.value.rules, (u, v) => (p(), h("details", {
                key: u.id || v,
                open: !u.id,
                class: "gw-settings-rule",
                onInput: (_) => S(u),
                onChange: (_) => S(u)
              }, [
                n("summary", null, [
                  n("strong", null, w(u.name || u.id || "Новое правило"), 1),
                  n("span", null, w(u.src || "Роутер") + " → " + w(u.dest || "Роутер") + " · " + w(X(u.proto) || "all") + " " + w(u.dest_port || "") + " · " + w(u.target || "ACCEPT"), 1),
                  n("small", null, w(u.enabled === "0" ? "Выключено" : "Включено"), 1)
                ]),
                n("div", rd, [
                  n("button", {
                    type: "button",
                    class: "gw-danger",
                    onClick: (_) => O(Number(v))
                  }, "Удалить правило", 8, ud),
                  u.editable ? (p(), h(N, { key: 1 }, [
                    n("label", null, [
                      d[52] || (d[52] = A("Название", -1)),
                      F(n("input", {
                        "onUpdate:modelValue": (_) => u.name = _
                      }, null, 8, cd), [
                        [re, u.name]
                      ])
                    ]),
                    n("div", fd, [
                      n("label", null, [
                        d[55] || (d[55] = A("Исходная зона", -1)),
                        F(n("select", {
                          "onUpdate:modelValue": (_) => u.src = _
                        }, [
                          d[53] || (d[53] = n("option", { value: "" }, "Сам роутер", -1)),
                          d[54] || (d[54] = n("option", { value: "*" }, "Любая", -1)),
                          (p(!0), h(N, null, se(i.value.zones, (_) => (p(), h("option", {
                            key: _.id,
                            value: _.name
                          }, w(_.name), 9, vd))), 128))
                        ], 8, pd), [
                          [xe, u.src]
                        ])
                      ]),
                      n("label", null, [
                        d[58] || (d[58] = A("Зона назначения", -1)),
                        F(n("select", {
                          "onUpdate:modelValue": (_) => u.dest = _
                        }, [
                          d[56] || (d[56] = n("option", { value: "" }, "Сам роутер", -1)),
                          d[57] || (d[57] = n("option", { value: "*" }, "Любая", -1)),
                          (p(!0), h(N, null, se(i.value.zones, (_) => (p(), h("option", {
                            key: _.id,
                            value: _.name
                          }, w(_.name), 9, hd))), 128))
                        ], 8, gd), [
                          [xe, u.dest]
                        ])
                      ])
                    ]),
                    n("div", md, [
                      n("label", null, [
                        d[64] || (d[64] = A("Протокол", -1)),
                        F(n("select", {
                          "onUpdate:modelValue": (_) => u.proto = _
                        }, [
                          Array.isArray(u.proto) ? (p(), h("option", {
                            key: 0,
                            value: u.proto
                          }, w(X(u.proto)), 9, yd)) : V("", !0),
                          d[59] || (d[59] = n("option", null, "tcp", -1)),
                          d[60] || (d[60] = n("option", null, "udp", -1)),
                          d[61] || (d[61] = n("option", null, "icmp", -1)),
                          d[62] || (d[62] = n("option", null, "icmpv6", -1)),
                          d[63] || (d[63] = n("option", null, "all", -1))
                        ], 8, bd), [
                          [xe, u.proto]
                        ])
                      ]),
                      n("label", null, [
                        d[65] || (d[65] = A("Порт назначения", -1)),
                        F(n("input", {
                          "onUpdate:modelValue": (_) => u.dest_port = _,
                          placeholder: "443 или 1000-2000"
                        }, null, 8, wd), [
                          [re, u.dest_port]
                        ])
                      ])
                    ]),
                    n("div", _d, [
                      n("label", null, [
                        d[67] || (d[67] = A("Действие", -1)),
                        F(n("select", {
                          "onUpdate:modelValue": (_) => u.target = _
                        }, [...d[66] || (d[66] = [
                          n("option", null, "ACCEPT", -1),
                          n("option", null, "REJECT", -1),
                          n("option", null, "DROP", -1)
                        ])], 8, kd), [
                          [xe, u.target]
                        ])
                      ]),
                      n("label", null, [
                        d[69] || (d[69] = A("Состояние", -1)),
                        F(n("select", {
                          "onUpdate:modelValue": (_) => u.enabled = _
                        }, [...d[68] || (d[68] = [
                          n("option", { value: void 0 }, "Включено по умолчанию", -1),
                          n("option", { value: "1" }, "Включено", -1),
                          n("option", { value: "0" }, "Выключено", -1)
                        ])], 8, $d), [
                          [xe, u.enabled]
                        ])
                      ])
                    ])
                  ], 64)) : (p(), h("p", dd, w(u.target) + " · Расширенное правило. Редактирование доступно в LuCI.", 1))
                ])
              ], 40, ad))), 128)),
              i.value.rules.length ? V("", !0) : (p(), h("p", Cd, "Правила трафика не настроены."))
            ], 512), [
              [Hl, g.value === "rules"]
            ]),
            F(n("section", null, [
              n("header", xd, [
                d[70] || (d[70] = n("h3", null, "Перенаправление портов", -1)),
                n("button", {
                  type: "button",
                  disabled: !i.value.redirectsSupported,
                  onClick: R
                }, "Добавить перенаправление", 8, Sd)
              ]),
              i.value.redirectsSupported ? (p(), h("p", Td, "Внешний порт → IP устройства и внутренний порт. Изменения применяются после проверки плана.")) : (p(), h("p", Vd, "Обновите интеграцию Bot4VPS на шлюзе для управления перенаправлениями портов.")),
              (p(!0), h(N, null, se(i.value.redirects, (u, v) => (p(), h("details", {
                key: u.id || v,
                open: !u.id,
                class: "gw-settings-rule",
                onInput: (_) => pe(u),
                onChange: (_) => pe(u)
              }, [
                n("summary", null, [
                  n("strong", null, w(u.name || u.id || "Новое перенаправление"), 1),
                  n("span", null, w(u.src) + ":" + w(u.src_dport) + " → " + w(u.dest_ip || "Роутер") + ":" + w(u.dest_port || u.src_dport) + " · " + w(X(u.proto) || "TCP и UDP"), 1),
                  n("small", null, w(u.enabled === "0" ? "Выключено" : "Включено"), 1)
                ]),
                n("div", Ud, [
                  n("button", {
                    type: "button",
                    class: "gw-danger",
                    onClick: (_) => z(Number(v))
                  }, "Удалить перенаправление", 8, Pd),
                  n("label", null, [
                    d[71] || (d[71] = A("Название", -1)),
                    F(n("input", {
                      "onUpdate:modelValue": (_) => u.name = _
                    }, null, 8, Ad), [
                      [re, u.name]
                    ])
                  ]),
                  n("div", Id, [
                    n("label", null, [
                      d[72] || (d[72] = A("Исходная зона", -1)),
                      F(n("select", {
                        "onUpdate:modelValue": (_) => u.src = _
                      }, [
                        (p(!0), h(N, null, se(i.value.zones, (_) => (p(), h("option", {
                          key: _.id,
                          value: _.name
                        }, w(_.name), 9, Od))), 128))
                      ], 8, Md), [
                        [xe, u.src]
                      ])
                    ]),
                    n("label", null, [
                      d[73] || (d[73] = A("Зона назначения", -1)),
                      F(n("select", {
                        "onUpdate:modelValue": (_) => u.dest = _
                      }, [
                        (p(!0), h(N, null, se(i.value.zones, (_) => (p(), h("option", {
                          key: _.id,
                          value: _.name
                        }, w(_.name), 9, Dd))), 128))
                      ], 8, Rd), [
                        [xe, u.dest]
                      ])
                    ])
                  ]),
                  n("div", Nd, [
                    n("label", null, [
                      d[74] || (d[74] = A("Внешний порт", -1)),
                      F(n("input", {
                        "onUpdate:modelValue": (_) => u.src_dport = _,
                        placeholder: "443 или 1000-2000"
                      }, null, 8, qd), [
                        [re, u.src_dport]
                      ])
                    ]),
                    n("label", null, [
                      d[75] || (d[75] = A("IP устройства назначения", -1)),
                      F(n("input", {
                        "onUpdate:modelValue": (_) => u.dest_ip = _,
                        placeholder: "192.168.1.10"
                      }, null, 8, Hd), [
                        [re, u.dest_ip]
                      ])
                    ])
                  ]),
                  n("div", Fd, [
                    n("label", null, [
                      d[76] || (d[76] = A("Внутренний порт", -1)),
                      F(n("input", {
                        "onUpdate:modelValue": (_) => u.dest_port = _,
                        placeholder: "Пусто — внешний порт"
                      }, null, 8, Ld), [
                        [re, u.dest_port]
                      ])
                    ]),
                    n("label", null, [
                      d[78] || (d[78] = A("Протокол", -1)),
                      F(n("select", {
                        "onUpdate:modelValue": (_) => u.proto = _
                      }, [...d[77] || (d[77] = [
                        n("option", { value: ["tcp", "udp"] }, "TCP и UDP", -1),
                        n("option", { value: "tcp" }, "TCP", -1),
                        n("option", { value: "udp" }, "UDP", -1)
                      ])], 8, jd), [
                        [xe, u.proto]
                      ])
                    ])
                  ]),
                  n("label", null, [
                    d[79] || (d[79] = A("Разрешённый IP источника", -1)),
                    F(n("input", {
                      "onUpdate:modelValue": (_) => u.src_ip = _,
                      placeholder: "Пусто — любой адрес; можно CIDR"
                    }, null, 8, Wd), [
                      [re, u.src_ip]
                    ])
                  ]),
                  n("div", Bd, [
                    n("label", null, [
                      d[81] || (d[81] = A("Состояние", -1)),
                      F(n("select", {
                        "onUpdate:modelValue": (_) => u.enabled = _
                      }, [...d[80] || (d[80] = [
                        n("option", { value: void 0 }, "Включено по умолчанию", -1),
                        n("option", { value: "1" }, "Включено", -1),
                        n("option", { value: "0" }, "Выключено", -1)
                      ])], 8, Kd), [
                        [xe, u.enabled]
                      ])
                    ]),
                    n("label", null, [
                      d[83] || (d[83] = A("NAT loopback", -1)),
                      F(n("select", {
                        "onUpdate:modelValue": (_) => u.reflection = _
                      }, [...d[82] || (d[82] = [
                        n("option", { value: void 0 }, "По умолчанию", -1),
                        n("option", { value: "1" }, "Включён", -1),
                        n("option", { value: "0" }, "Выключен", -1)
                      ])], 8, Gd), [
                        [xe, u.reflection]
                      ]),
                      d[84] || (d[84] = n("small", null, "Доступ из LAN через внешний адрес.", -1))
                    ])
                  ])
                ])
              ], 40, Ed))), 128)),
              i.value.redirectsSupported && !i.value.redirects.length ? (p(), h("p", zd, "Перенаправления не настроены.")) : V("", !0)
            ], 512), [
              [Hl, g.value === "redirects"]
            ])
          ], 64)) : V("", !0),
          n("div", Jd, [
            n("button", {
              class: "gw-primary",
              disabled: r.value || e.mode === "dns" && !s.value.dns.length
            }, "Проверить изменения", 8, Yd),
            n("button", {
              type: "button",
              disabled: r.value,
              onClick: d[19] || (d[19] = (u) => o("close"))
            }, "Закрыть", 8, Xd)
          ])
        ], 32)) : r.value ? (p(), h("p", Qd, "Получаем конфигурацию…")) : V("", !0)
      ]),
      _: 1
    }, 8, ["title", "busy"]));
  }
}), Zd = { class: "gw-password" }, ec = ["type"], tc = ["aria-label", "title", "aria-pressed"], vt = /* @__PURE__ */ He({
  inheritAttrs: !1,
  __name: "PasswordInput",
  props: {
    modelValue: { required: !0 },
    modelModifiers: {}
  },
  emits: ["update:modelValue"],
  setup(e) {
    const t = Za(e, "modelValue"), l = /* @__PURE__ */ H(!1);
    return Xe(t, (o) => {
      o || (l.value = !1);
    }), (o, s) => (p(), h("span", Zd, [
      F(n("input", li(o.$attrs, {
        "onUpdate:modelValue": s[0] || (s[0] = (i) => t.value = i),
        type: l.value ? "text" : "password",
        spellcheck: "false",
        autocapitalize: "off"
      }), null, 16, ec), [
        [Zr, t.value]
      ]),
      n("button", {
        type: "button",
        class: "gw-password-eye",
        "aria-label": l.value ? "Скрыть введённое" : "Показать введённое",
        title: l.value ? "Скрыть введённое" : "Показать введённое",
        "aria-pressed": l.value,
        onClick: s[1] || (s[1] = Ze((i) => l.value = !l.value, ["prevent"]))
      }, "👁", 8, tc)
    ]));
  }
}), lc = { class: "gw-network" }, nc = { class: "gw-section-header" }, sc = { class: "gw-actions" }, oc = ["disabled"], ic = ["disabled"], ac = {
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
}, Cc = { class: "gw-two" }, xc = ["readonly"], Sc = { key: 0 }, Vc = ["value"], Tc = { class: "gw-two" }, Ec = { class: "gw-two" }, Uc = { class: "gw-network-extra" }, Pc = { class: "gw-two" }, Ac = { class: "gw-check" }, Ic = { class: "gw-check" }, Mc = {
  key: 0,
  class: "gw-check"
}, Oc = { key: 4 }, Rc = { class: "gw-section-header" }, Dc = { class: "gw-section-header" }, Nc = ["onClick"], qc = ["onUpdate:modelValue"], Hc = { class: "gw-two" }, Fc = ["onUpdate:modelValue"], Lc = ["onUpdate:modelValue"], jc = ["onUpdate:modelValue"], Wc = { class: "gw-two" }, Bc = ["onUpdate:modelValue"], Kc = { class: "gw-check" }, Gc = ["onUpdate:modelValue"], zc = {
  key: 5,
  class: "gw-error",
  role: "alert"
}, Jc = { class: "gw-actions" }, Yc = ["disabled"], Xc = ["disabled"], Qc = ["disabled"], Zc = { class: "gw-section-header" }, ef = ["onClick"], tf = { class: "gw-two" }, lf = ["onUpdate:modelValue"], nf = ["onUpdate:modelValue"], sf = ["value"], of = { class: "gw-two" }, af = ["onUpdate:modelValue"], rf = ["onUpdate:modelValue"], uf = { class: "gw-two" }, df = ["onUpdate:modelValue"], cf = ["onUpdate:modelValue"], ff = { class: "gw-check" }, pf = ["onUpdate:modelValue"], vf = {
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
}, kf = { class: "gw-actions" }, $f = ["disabled"], Cf = ["disabled"], xf = /* @__PURE__ */ He({
  __name: "NetworkEditor",
  props: {
    node: {},
    bridge: {}
  },
  emits: ["changed"],
  setup(e, { emit: t }) {
    const l = e, o = t, s = /* @__PURE__ */ H({ interfaces: [], routes: [], devices: [] }), i = /* @__PURE__ */ H(!1), a = /* @__PURE__ */ H(!1), r = /* @__PURE__ */ H(""), c = /* @__PURE__ */ H(null), g = /* @__PURE__ */ H(null), m = /* @__PURE__ */ H(""), y = /* @__PURE__ */ H(null), T = /* @__PURE__ */ H(!1), E = /* @__PURE__ */ H([]), B = _e(() => [.../* @__PURE__ */ new Set([...s.value.devices || [], ...y.value?.device ? [y.value.device] : []])]);
    let I = !0;
    const Q = () => "/api/gateways/" + encodeURIComponent(l.node.id), X = (d, u, v = "POST") => l.bridge.request(Q() + d, { method: v, headers: { "Content-Type": "application/json" }, body: JSON.stringify(u) }), Z = (d) => Array.isArray(d) ? d.join(", ") : d || "", le = (d) => d.split(/[\s,]+/).filter(Boolean), j = (d) => d === "" || d == null ? null : String(d);
    function te(d) {
      return l.node.monitor.interfaces?.find((u) => u.name === d.name) || d;
    }
    function O(d) {
      return d.ipaddr === l.node.host || d.runtime_addresses?.includes(l.node.host);
    }
    async function S() {
      i.value = !0, r.value = "";
      try {
        const d = await l.bridge.request(Q() + "/network");
        I && (s.value = d);
      } catch (d) {
        I && (r.value = d.message);
      } finally {
        I && (i.value = !1);
      }
    }
    async function k(d) {
      if (!a.value) {
        a.value = !0, r.value = "";
        try {
          await d();
        } catch (u) {
          r.value = u.message;
        } finally {
          a.value = !1;
        }
      }
    }
    function R(d) {
      r.value = "", y.value = {
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
        peers: (d?.peers || []).map((u) => ({ ...u, allowed_ips: Z(u.allowed_ips), preshared_key: "", route_allowed_ips: u.route_allowed_ips === "1" }))
      };
    }
    async function z(d, u) {
      await k(async () => {
        const v = await X("/network/plan", { action: d, data: { ...u, config_hash: s.value.config_hash } });
        y.value = null, T.value = !1, c.value = v;
      });
    }
    async function pe() {
      const d = y.value, u = {
        proto: d.proto,
        device: j(d.device),
        dns: le(d.dns),
        metric: j(d.metric),
        mtu: j(d.mtu),
        auto: d.auto ? "1" : "0",
        defaultroute: d.defaultroute ? "1" : "0",
        peerdns: d.peerdns ? "1" : "0"
      };
      d.proto === "static" && Object.assign(u, { ipaddr: d.ipaddr, netmask: d.netmask, gateway: j(d.gateway) }), d.proto === "pppoe" && (u.username = d.username, d.password && (u.password = d.password));
      const v = { interface: d.name, settings: u };
      d.proto === "wireguard" && (u.addresses = le(d.addresses), u.listen_port = j(d.listen_port), d.private_key && (u.private_key = d.private_key), v.peers = d.peers.map((_) => {
        const K = {
          public_key: _.public_key,
          endpoint_host: j(_.endpoint_host),
          endpoint_port: j(_.endpoint_port),
          allowed_ips: le(_.allowed_ips || ""),
          persistent_keepalive: j(_.persistent_keepalive),
          route_allowed_ips: _.route_allowed_ips ? "1" : "0",
          description: j(_.description)
        };
        return _.id && (K.id = _.id), _.preshared_key && (K.preshared_key = _.preshared_key), K;
      })), await z("edit", v);
    }
    function he() {
      r.value = "", E.value = s.value.routes.map((d) => ({
        interface: d.interface || "",
        target: d.target || "",
        netmask: d.netmask || "255.255.255.255",
        gateway: d.gateway || "",
        metric: d.metric || "",
        table: d.table || "",
        onlink: d.onlink === "1"
      })), T.value = !0;
    }
    function Pe() {
      E.value.push({ interface: s.value.interfaces[0]?.name || "", target: "", netmask: "", gateway: "", metric: "", table: "", onlink: !1 });
    }
    async function Me() {
      await z("routes", { routes: E.value.map((d) => ({
        interface: d.interface,
        target: d.target,
        netmask: j(d.netmask),
        gateway: j(d.gateway),
        metric: j(d.metric),
        table: j(d.table),
        onlink: d.onlink ? "1" : "0"
      })) });
    }
    async function ne() {
      await k(async () => {
        const d = c.value, u = await X("/router-operations", { plan_token: d.plan_token, confirmed: !0 });
        c.value = null, l.bridge.task({
          taskId: u.task_id,
          title: d.title + (d.interface ? " " + d.interface : ""),
          cancellable: !1,
          onDone: async () => {
            await S(), o("changed");
          }
        });
      });
    }
    function U() {
      const d = c.value?.plan_token;
      c.value = null, r.value = "", d && X("/operation-plans/" + encodeURIComponent(d), {}, "DELETE").catch((u) => {
        r.value = u.message;
      });
    }
    return ct(() => {
      S();
    }), qt(() => {
      I = !1, y.value = null;
    }), (d, u) => (p(), h(N, null, [
      n("section", lc, [
        n("header", nc, [
          u[26] || (u[26] = n("div", null, [
            n("h3", null, "Подключения"),
            n("p", { class: "gw-hint" }, "LAN, WAN и туннели · настройки и состояние")
          ], -1)),
          n("div", sc, [
            n("button", {
              disabled: i.value || a.value,
              onClick: S
            }, "Обновить", 8, oc),
            n("button", {
              disabled: i.value || a.value || !s.value.config_hash,
              onClick: u[0] || (u[0] = (v) => R())
            }, "Добавить подключение", 8, ic)
          ])
        ]),
        r.value && !y.value && !T.value && !c.value ? (p(), h("p", ac, w(r.value), 1)) : V("", !0),
        n("div", {
          class: "gw-interface-list",
          "aria-busy": i.value
        }, [
          (p(!0), h(N, null, se(s.value.interfaces, (v) => (p(), h("article", {
            key: v.name,
            class: "gw-interface"
          }, [
            n("div", uc, [
              n("h4", null, w(v.name), 1),
              O(v) ? (p(), h("small", dc, "Доступ к панели")) : V("", !0)
            ]),
            n("div", cc, [
              n("span", null, w(v.proto) + " · " + w(v.device || v.runtime_device || "—"), 1),
              n("strong", null, w(te(v).addresses?.join(", ") || v.runtime_addresses?.join(", ") || v.ipaddr || Z(v.addresses) || "Без адреса"), 1),
              v.gateway ? (p(), h("small", fc, "Шлюз " + w(v.gateway), 1)) : V("", !0)
            ]),
            n("div", pc, [
              n("span", {
                class: Ue(["gw-status", te(v).up ? "good" : "warn"])
              }, w(te(v).up ? "Подключён" : te(v).pending ? "Подключается" : "Отключён"), 3)
            ]),
            n("div", vc, [
              n("button", {
                disabled: a.value,
                onClick: (_) => R(v)
              }, "Настроить", 8, gc),
              n("button", {
                disabled: a.value,
                onClick: (_) => {
                  m.value = v.name, g.value = "dhcp";
                }
              }, "DHCP", 8, hc),
              te(v).up ? (p(), h("button", {
                key: 0,
                disabled: a.value,
                onClick: (_) => z("reconnect", { interface: v.name })
              }, "Переподключить", 8, mc)) : V("", !0),
              n("button", {
                disabled: a.value || O(v) && te(v).up,
                title: O(v) ? "Интерфейс доступа изменяется через форму с откатом" : "",
                onClick: (_) => z(te(v).up ? "down" : "up", { interface: v.name })
              }, w(te(v).up ? "Отключить" : "Подключить"), 9, bc)
            ])
          ]))), 128))
        ], 8, rc),
        s.value.interfaces.length ? V("", !0) : (p(), h("p", yc, w(i.value ? "Получаем состояние сети…" : "Интерфейсы не найдены."), 1)),
        n("header", wc, [
          u[27] || (u[27] = n("div", null, [
            n("h3", null, "Статические маршруты IPv4"),
            n("p", { class: "gw-hint" }, "Автоматические маршруты создаются протоколами подключений")
          ], -1)),
          n("button", {
            disabled: a.value || i.value || !s.value.config_hash,
            onClick: he
          }, "Настроить маршруты", 8, _c)
        ]),
        s.value.routes.length ? (p(), h("div", kc, [
          n("table", null, [
            u[28] || (u[28] = n("thead", null, [
              n("tr", null, [
                n("th", null, "Сеть"),
                n("th", null, "Через шлюз"),
                n("th", null, "Интерфейс"),
                n("th", null, "Метрика")
              ])
            ], -1)),
            n("tbody", null, [
              (p(!0), h(N, null, se(s.value.routes, (v) => (p(), h("tr", {
                key: v.id
              }, [
                n("td", null, [
                  A(w(v.target), 1),
                  n("small", null, w(v.netmask), 1)
                ]),
                n("td", null, w(v.gateway || "Напрямую"), 1),
                n("td", null, w(v.interface), 1),
                n("td", null, w(v.metric || "0"), 1)
              ]))), 128))
            ])
          ])
        ])) : (p(), h("p", $c, "Статические маршруты не заданы."))
      ]),
      g.value ? (p(), ge(ci, {
        key: 0,
        node: e.node,
        bridge: e.bridge,
        mode: g.value,
        iface: g.value === "dhcp" ? m.value : void 0,
        onClose: u[1] || (u[1] = (v) => g.value = null),
        onChanged: u[2] || (u[2] = (v) => {
          S(), o("changed");
        })
      }, null, 8, ["node", "bridge", "mode", "iface"])) : V("", !0),
      y.value ? (p(), ge(qe, {
        key: 1,
        title: y.value.existing ? "Настройка " + y.value.name : "Новое подключение",
        wide: !0,
        busy: a.value,
        onClose: u[23] || (u[23] = (v) => {
          y.value = null, r.value = "";
        })
      }, {
        default: Re(() => [
          n("form", {
            class: "gw-form gw-network-form",
            onSubmit: Ze(pe, ["prevent"])
          }, [
            n("div", Cc, [
              n("label", null, [
                u[29] || (u[29] = A("Имя интерфейса", -1)),
                F(n("input", {
                  "onUpdate:modelValue": u[3] || (u[3] = (v) => y.value.name = v),
                  required: "",
                  pattern: "[A-Za-z][A-Za-z0-9_]{0,30}",
                  readonly: y.value.existing,
                  placeholder: "wan, lan, wg0"
                }, null, 8, xc), [
                  [re, y.value.name]
                ])
              ]),
              n("label", null, [
                u[31] || (u[31] = A("Протокол", -1)),
                F(n("select", {
                  "onUpdate:modelValue": u[4] || (u[4] = (v) => y.value.proto = v)
                }, [...u[30] || (u[30] = [
                  n("option", { value: "dhcp" }, "DHCP-клиент", -1),
                  n("option", { value: "static" }, "Статический адрес", -1),
                  n("option", { value: "pppoe" }, "PPPoE", -1),
                  n("option", { value: "wireguard" }, "WireGuard", -1),
                  n("option", { value: "none" }, "Без протокола", -1)
                ])], 512), [
                  [xe, y.value.proto]
                ])
              ])
            ]),
            y.value.proto !== "wireguard" ? (p(), h("label", Sc, [
              u[33] || (u[33] = A("Сетевое устройство", -1)),
              F(n("select", {
                "onUpdate:modelValue": u[5] || (u[5] = (v) => y.value.device = v)
              }, [
                u[32] || (u[32] = n("option", { value: "" }, "Автоматически", -1)),
                (p(!0), h(N, null, se(B.value, (v) => (p(), h("option", {
                  key: v,
                  value: v
                }, w(v), 9, Vc))), 128))
              ], 512), [
                [xe, y.value.device]
              ])
            ])) : V("", !0),
            y.value.proto === "static" ? (p(), h(N, { key: 1 }, [
              n("div", Tc, [
                n("label", null, [
                  u[34] || (u[34] = A("IPv4-адрес", -1)),
                  F(n("input", {
                    "onUpdate:modelValue": u[6] || (u[6] = (v) => y.value.ipaddr = v),
                    required: "",
                    placeholder: "192.168.1.2"
                  }, null, 512), [
                    [re, y.value.ipaddr]
                  ])
                ]),
                n("label", null, [
                  u[35] || (u[35] = A("Маска подсети", -1)),
                  F(n("input", {
                    "onUpdate:modelValue": u[7] || (u[7] = (v) => y.value.netmask = v),
                    required: "",
                    placeholder: "255.255.255.0"
                  }, null, 512), [
                    [re, y.value.netmask]
                  ])
                ])
              ]),
              n("label", null, [
                u[36] || (u[36] = A("IPv4-шлюз", -1)),
                F(n("input", {
                  "onUpdate:modelValue": u[8] || (u[8] = (v) => y.value.gateway = v),
                  placeholder: "192.168.1.1"
                }, null, 512), [
                  [re, y.value.gateway]
                ])
              ])
            ], 64)) : V("", !0),
            y.value.proto === "pppoe" ? (p(), h(N, { key: 2 }, [
              n("label", null, [
                u[37] || (u[37] = A("Логин PPPoE", -1)),
                F(n("input", {
                  "onUpdate:modelValue": u[9] || (u[9] = (v) => y.value.username = v),
                  required: "",
                  autocomplete: "off"
                }, null, 512), [
                  [re, y.value.username]
                ])
              ]),
              n("label", null, [
                u[38] || (u[38] = A("Пароль PPPoE", -1)),
                Ee(vt, {
                  modelValue: y.value.password,
                  "onUpdate:modelValue": u[10] || (u[10] = (v) => y.value.password = v),
                  autocomplete: "off",
                  required: !y.value.has_password,
                  placeholder: y.value.has_password ? "Пустое поле сохраняет текущий пароль" : ""
                }, null, 8, ["modelValue", "required", "placeholder"])
              ])
            ], 64)) : V("", !0),
            y.value.proto === "wireguard" ? (p(), h(N, { key: 3 }, [
              n("label", null, [
                u[39] || (u[39] = A("Приватный ключ WireGuard", -1)),
                Ee(vt, {
                  modelValue: y.value.private_key,
                  "onUpdate:modelValue": u[11] || (u[11] = (v) => y.value.private_key = v),
                  autocomplete: "off",
                  required: !y.value.has_private_key,
                  placeholder: y.value.has_private_key ? "Пустое поле сохраняет текущий ключ" : ""
                }, null, 8, ["modelValue", "required", "placeholder"])
              ]),
              n("div", Ec, [
                n("label", null, [
                  u[40] || (u[40] = A("Адреса туннеля", -1)),
                  F(n("input", {
                    "onUpdate:modelValue": u[12] || (u[12] = (v) => y.value.addresses = v),
                    required: "",
                    placeholder: "10.10.0.2/24"
                  }, null, 512), [
                    [re, y.value.addresses]
                  ])
                ]),
                n("label", null, [
                  u[41] || (u[41] = A("Порт WireGuard", -1)),
                  F(n("input", {
                    "onUpdate:modelValue": u[13] || (u[13] = (v) => y.value.listen_port = v),
                    type: "number",
                    min: "1",
                    max: "65535",
                    placeholder: "Автоматически"
                  }, null, 512), [
                    [re, y.value.listen_port]
                  ])
                ])
              ])
            ], 64)) : V("", !0),
            n("label", null, [
              u[42] || (u[42] = A("DNS-серверы", -1)),
              F(n("input", {
                "onUpdate:modelValue": u[14] || (u[14] = (v) => y.value.dns = v),
                placeholder: "1.1.1.1, 8.8.8.8"
              }, null, 512), [
                [re, y.value.dns]
              ]),
              u[43] || (u[43] = n("small", null, "Несколько адресов разделяются пробелами или запятыми", -1))
            ]),
            n("details", Uc, [
              u[49] || (u[49] = n("summary", null, "Дополнительные параметры", -1)),
              n("div", Pc, [
                n("label", null, [
                  u[44] || (u[44] = A("Метрика маршрута", -1)),
                  F(n("input", {
                    "onUpdate:modelValue": u[15] || (u[15] = (v) => y.value.metric = v),
                    type: "number",
                    min: "0",
                    placeholder: "По умолчанию"
                  }, null, 512), [
                    [re, y.value.metric]
                  ])
                ]),
                n("label", null, [
                  u[45] || (u[45] = A("MTU", -1)),
                  F(n("input", {
                    "onUpdate:modelValue": u[16] || (u[16] = (v) => y.value.mtu = v),
                    type: "number",
                    min: "576",
                    max: "65535",
                    placeholder: "По умолчанию"
                  }, null, 512), [
                    [re, y.value.mtu]
                  ])
                ])
              ]),
              n("label", Ac, [
                F(n("input", {
                  "onUpdate:modelValue": u[17] || (u[17] = (v) => y.value.auto = v),
                  type: "checkbox"
                }, null, 512), [
                  [We, y.value.auto]
                ]),
                u[46] || (u[46] = A(" Подключать при загрузке роутера", -1))
              ]),
              n("label", Ic, [
                F(n("input", {
                  "onUpdate:modelValue": u[18] || (u[18] = (v) => y.value.defaultroute = v),
                  type: "checkbox"
                }, null, 512), [
                  [We, y.value.defaultroute]
                ]),
                u[47] || (u[47] = A(" Использовать маршрут по умолчанию", -1))
              ]),
              y.value.proto === "dhcp" || y.value.proto === "pppoe" ? (p(), h("label", Mc, [
                F(n("input", {
                  "onUpdate:modelValue": u[19] || (u[19] = (v) => y.value.peerdns = v),
                  type: "checkbox"
                }, null, 512), [
                  [We, y.value.peerdns]
                ]),
                u[48] || (u[48] = A(" Получать DNS от подключения", -1))
              ])) : V("", !0)
            ]),
            y.value.proto === "wireguard" ? (p(), h("section", Oc, [
              n("header", Rc, [
                u[50] || (u[50] = n("h3", null, "Пиры WireGuard", -1)),
                n("button", {
                  type: "button",
                  onClick: u[20] || (u[20] = (v) => y.value.peers.push({ public_key: "", allowed_ips: "", endpoint_host: "", endpoint_port: "", persistent_keepalive: "", preshared_key: "", route_allowed_ips: !0 }))
                }, "Добавить пир")
              ]),
              (p(!0), h(N, null, se(y.value.peers, (v, _) => (p(), h("article", {
                key: v.id || _,
                class: "gw-peer-form"
              }, [
                n("div", Dc, [
                  n("h4", null, "Пир " + w(Number(_) + 1), 1),
                  n("button", {
                    type: "button",
                    onClick: (K) => y.value.peers.splice(_, 1)
                  }, "Удалить пир", 8, Nc)
                ]),
                n("label", null, [
                  u[51] || (u[51] = A("Публичный ключ", -1)),
                  F(n("input", {
                    "onUpdate:modelValue": (K) => v.public_key = K,
                    required: "",
                    autocomplete: "off"
                  }, null, 8, qc), [
                    [re, v.public_key]
                  ])
                ]),
                n("div", Hc, [
                  n("label", null, [
                    u[52] || (u[52] = A("Endpoint", -1)),
                    F(n("input", {
                      "onUpdate:modelValue": (K) => v.endpoint_host = K,
                      placeholder: "vpn.example.org"
                    }, null, 8, Fc), [
                      [re, v.endpoint_host]
                    ])
                  ]),
                  n("label", null, [
                    u[53] || (u[53] = A("Порт", -1)),
                    F(n("input", {
                      "onUpdate:modelValue": (K) => v.endpoint_port = K,
                      type: "number",
                      min: "1",
                      max: "65535"
                    }, null, 8, Lc), [
                      [re, v.endpoint_port]
                    ])
                  ])
                ]),
                n("label", null, [
                  u[54] || (u[54] = A("Разрешённые сети", -1)),
                  F(n("input", {
                    "onUpdate:modelValue": (K) => v.allowed_ips = K,
                    required: "",
                    placeholder: "0.0.0.0/0, ::/0"
                  }, null, 8, jc), [
                    [re, v.allowed_ips]
                  ])
                ]),
                n("div", Wc, [
                  n("label", null, [
                    u[55] || (u[55] = A("Keepalive, секунд", -1)),
                    F(n("input", {
                      "onUpdate:modelValue": (K) => v.persistent_keepalive = K,
                      type: "number",
                      min: "0",
                      max: "65535",
                      placeholder: "25"
                    }, null, 8, Bc), [
                      [re, v.persistent_keepalive]
                    ])
                  ]),
                  n("label", null, [
                    u[56] || (u[56] = A("Общий ключ, необязательно", -1)),
                    Ee(vt, {
                      modelValue: v.preshared_key,
                      "onUpdate:modelValue": (K) => v.preshared_key = K,
                      autocomplete: "off",
                      placeholder: v.has_preshared_key ? "Пустое поле сохраняет текущий ключ" : ""
                    }, null, 8, ["modelValue", "onUpdate:modelValue", "placeholder"])
                  ])
                ]),
                n("label", Kc, [
                  F(n("input", {
                    "onUpdate:modelValue": (K) => v.route_allowed_ips = K,
                    type: "checkbox"
                  }, null, 8, Gc), [
                    [We, v.route_allowed_ips]
                  ]),
                  u[57] || (u[57] = A(" Создать маршруты для разрешённых сетей", -1))
                ])
              ]))), 128))
            ])) : V("", !0),
            u[58] || (u[58] = n("p", { class: "gw-hint" }, "Перед применением вы увидите изменения. Если панель не подтвердит доступность, роутер восстановит прежнюю сеть.", -1)),
            r.value ? (p(), h("p", zc, w(r.value), 1)) : V("", !0),
            n("div", Jc, [
              n("button", {
                class: "gw-primary",
                disabled: a.value
              }, "Проверить изменения", 8, Yc),
              n("button", {
                type: "button",
                disabled: a.value,
                onClick: u[21] || (u[21] = (v) => y.value = null)
              }, "Отмена", 8, Xc),
              y.value.existing ? (p(), h("button", {
                key: 0,
                type: "button",
                disabled: a.value,
                onClick: u[22] || (u[22] = (v) => z("delete", { interface: y.value.name }))
              }, "Удалить интерфейс", 8, Qc)) : V("", !0)
            ])
          ], 32)
        ]),
        _: 1
      }, 8, ["title", "busy"])) : V("", !0),
      T.value ? (p(), ge(qe, {
        key: 2,
        title: "Статические маршруты IPv4",
        wide: !0,
        busy: a.value,
        onClose: u[25] || (u[25] = (v) => {
          T.value = !1, r.value = "";
        })
      }, {
        default: Re(() => [
          n("form", {
            class: "gw-form",
            onSubmit: Ze(Me, ["prevent"])
          }, [
            (p(!0), h(N, null, se(E.value, (v, _) => (p(), h("article", {
              key: _,
              class: "gw-route-form"
            }, [
              n("div", Zc, [
                n("h4", null, "Маршрут " + w(Number(_) + 1), 1),
                n("button", {
                  type: "button",
                  onClick: (K) => E.value.splice(_, 1)
                }, "Удалить маршрут", 8, ef)
              ]),
              n("div", tf, [
                n("label", null, [
                  u[59] || (u[59] = A("Сеть назначения", -1)),
                  F(n("input", {
                    "onUpdate:modelValue": (K) => v.target = K,
                    required: "",
                    placeholder: "10.20.0.0/24"
                  }, null, 8, lf), [
                    [re, v.target]
                  ])
                ]),
                n("label", null, [
                  u[60] || (u[60] = A("Интерфейс", -1)),
                  F(n("select", {
                    "onUpdate:modelValue": (K) => v.interface = K
                  }, [
                    (p(!0), h(N, null, se(s.value.interfaces, (K) => (p(), h("option", {
                      key: K.name,
                      value: K.name
                    }, w(K.name), 9, sf))), 128))
                  ], 8, nf), [
                    [xe, v.interface]
                  ])
                ])
              ]),
              n("div", of, [
                n("label", null, [
                  u[61] || (u[61] = A("Через шлюз", -1)),
                  F(n("input", {
                    "onUpdate:modelValue": (K) => v.gateway = K,
                    placeholder: "Напрямую, если пусто"
                  }, null, 8, af), [
                    [re, v.gateway]
                  ])
                ]),
                n("label", null, [
                  u[62] || (u[62] = A("Маска, если в адресе нет /префикса", -1)),
                  F(n("input", {
                    "onUpdate:modelValue": (K) => v.netmask = K,
                    placeholder: "255.255.255.0"
                  }, null, 8, rf), [
                    [re, v.netmask]
                  ])
                ])
              ]),
              n("div", uf, [
                n("label", null, [
                  u[63] || (u[63] = A("Метрика", -1)),
                  F(n("input", {
                    "onUpdate:modelValue": (K) => v.metric = K,
                    type: "number",
                    min: "0"
                  }, null, 8, df), [
                    [re, v.metric]
                  ])
                ]),
                n("label", null, [
                  u[64] || (u[64] = A("Таблица маршрутов", -1)),
                  F(n("input", {
                    "onUpdate:modelValue": (K) => v.table = K,
                    type: "number",
                    min: "0",
                    placeholder: "Основная"
                  }, null, 8, cf), [
                    [re, v.table]
                  ])
                ])
              ]),
              n("label", ff, [
                F(n("input", {
                  "onUpdate:modelValue": (K) => v.onlink = K,
                  type: "checkbox"
                }, null, 8, pf), [
                  [We, v.onlink]
                ]),
                u[65] || (u[65] = A(" Шлюз доступен напрямую", -1))
              ])
            ]))), 128)),
            n("button", {
              type: "button",
              onClick: Pe
            }, "Добавить маршрут"),
            E.value.length ? V("", !0) : (p(), h("p", vf, "Статические маршруты будут отсутствовать. Автоматические маршруты сохраняются.")),
            r.value ? (p(), h("p", gf, w(r.value), 1)) : V("", !0),
            n("div", hf, [
              n("button", {
                class: "gw-primary",
                disabled: a.value
              }, "Проверить изменения", 8, mf),
              n("button", {
                type: "button",
                disabled: a.value,
                onClick: u[24] || (u[24] = (v) => T.value = !1)
              }, "Отмена", 8, bf)
            ])
          ], 32)
        ]),
        _: 1
      }, 8, ["busy"])) : V("", !0),
      c.value ? (p(), ge(qe, {
        key: 3,
        title: "Проверка сетевых изменений",
        busy: a.value,
        onClose: U
      }, {
        default: Re(() => [
          n("h3", null, w(c.value.title) + " " + w(c.value.interface), 1),
          n("ul", yf, [
            (p(!0), h(N, null, se(c.value.summary, (v, _) => (p(), h("li", { key: _ }, w(v), 1))), 128))
          ]),
          c.value.address_changes ? (p(), h("p", wf, [
            u[66] || (u[66] = A("Адрес подключения изменится на ", -1)),
            n("strong", null, w(c.value.new_api_host), 1),
            u[67] || (u[67] = A(". Панель проверит новый адрес и сохранит его после успешного применения.", -1))
          ])) : V("", !0),
          n("p", null, "Роутер ждёт подтверждения до " + w(c.value.rollback_seconds) + " секунд. Если панель потеряет связь, прежняя конфигурация будет восстановлена автоматически.", 1),
          r.value ? (p(), h("p", _f, w(r.value), 1)) : V("", !0),
          n("div", kf, [
            n("button", {
              class: "gw-primary",
              disabled: a.value,
              onClick: ne
            }, "Да, применить изменения", 8, $f),
            n("button", {
              disabled: a.value,
              onClick: U
            }, "Отмена", 8, Cf)
          ])
        ]),
        _: 1
      }, 8, ["busy"])) : V("", !0)
    ], 64));
  }
}), Sf = { class: "gw-packages" }, Vf = { class: "gw-section-header" }, Tf = { class: "gw-hint" }, Ef = ["disabled"], Uf = {
  key: 0,
  class: "gw-error",
  role: "alert"
}, Pf = { class: "gw-package-filters" }, Af = { class: "gw-segment" }, If = ["disabled"], Mf = {
  key: 1,
  class: "gw-notice"
}, Of = ["aria-busy"], Rf = { class: "gw-package-table" }, Df = { key: 0 }, Nf = {
  key: 0,
  class: "gw-status good"
}, qf = ["disabled", "onClick"], Hf = {
  key: 2,
  class: "gw-hint"
}, Ff = { class: "gw-pagination" }, Lf = { class: "gw-hint" }, jf = { class: "gw-actions" }, Wf = ["disabled"], Bf = ["disabled"], Kf = { class: "gw-plan-output" }, Gf = {
  key: 0,
  class: "gw-error",
  role: "alert"
}, zf = { class: "gw-actions" }, Jf = ["disabled"], Yf = ["disabled"], Xf = /* @__PURE__ */ He({
  __name: "PackageManager",
  props: {
    node: {},
    bridge: {},
    initialQuery: {}
  },
  emits: ["changed"],
  setup(e, { emit: t }) {
    const l = e, o = t, s = /* @__PURE__ */ H(l.initialQuery || ""), i = /* @__PURE__ */ H(!1), a = /* @__PURE__ */ H(!1), r = /* @__PURE__ */ H(!1), c = /* @__PURE__ */ H(""), g = /* @__PURE__ */ H({ items: [], total: 0, offset: 0, has_indexes: !1 }), m = /* @__PURE__ */ H(null);
    let y, T = 0;
    const E = () => "/api/gateways/" + encodeURIComponent(l.node.id), B = (O, S, k = "POST") => l.bridge.request(E() + O, { method: k, headers: { "Content-Type": "application/json" }, body: JSON.stringify(S) });
    async function I(O = 0) {
      const S = ++T;
      a.value = !0, c.value = "";
      try {
        const k = await l.bridge.request(E() + "/packages?query=" + encodeURIComponent(s.value) + "&installed=" + i.value + "&offset=" + O);
        S === T && (g.value = k);
      } catch (k) {
        S === T && (c.value = k.message);
      } finally {
        S === T && (a.value = !1);
      }
    }
    async function Q(O) {
      const S = await B("/router-operations", { plan_token: O.plan_token, confirmed: !0 });
      m.value = null, l.bridge.task({
        taskId: S.task_id,
        title: O.action === "refresh" ? "Обновление списка пакетов" : "Установка " + O.package,
        cancellable: !1,
        onDone: async () => {
          await I(), o("changed");
        }
      });
    }
    async function X() {
      if (!r.value) {
        r.value = !0, c.value = "";
        try {
          const O = await B("/packages/plan", { action: "refresh" });
          await Q(O);
        } catch (O) {
          c.value = O.message;
        } finally {
          r.value = !1;
        }
      }
    }
    async function Z(O) {
      if (!r.value) {
        r.value = !0, c.value = "";
        try {
          m.value = await B("/packages/plan", { action: "install", package: O });
        } catch (S) {
          c.value = S.message;
        } finally {
          r.value = !1;
        }
      }
    }
    async function le() {
      if (!r.value) {
        r.value = !0, c.value = "";
        try {
          await Q(m.value);
        } catch (O) {
          c.value = O.message;
        } finally {
          r.value = !1;
        }
      }
    }
    function j(O) {
      i.value = O, I();
    }
    function te() {
      const O = m.value?.plan_token;
      m.value = null, c.value = "", O && B("/operation-plans/" + encodeURIComponent(O), {}, "DELETE").catch((S) => {
        c.value = S.message;
      });
    }
    return Xe(s, () => {
      y && clearTimeout(y), y = setTimeout(() => {
        I();
      }, 300);
    }), ct(() => {
      I();
    }), qt(() => {
      T++, y && clearTimeout(y);
    }), (O, S) => (p(), h(N, null, [
      n("section", Sf, [
        n("header", Vf, [
          n("div", null, [
            S[6] || (S[6] = n("h3", null, "Пакетный менеджер", -1)),
            n("p", Tf, w(g.value.manager || "OpenWrt") + " · " + w(g.value.installed_count ?? "—") + " установленных пакетов", 1)
          ]),
          n("button", {
            disabled: r.value,
            onClick: X
          }, "Обновить список пакетов", 8, Ef)
        ]),
        S[8] || (S[8] = n("p", { class: "gw-hint" }, "Обновляется каталог репозиториев. Установленные пакеты и прошивка автоматически не обновляются.", -1)),
        c.value && !m.value ? (p(), h("div", Uf, w(c.value), 1)) : V("", !0),
        n("div", Pf, [
          n("div", Af, [
            n("button", {
              class: Ue({ on: !i.value }),
              onClick: S[0] || (S[0] = (k) => j(!1))
            }, "Доступные", 2),
            n("button", {
              class: Ue({ on: i.value }),
              onClick: S[1] || (S[1] = (k) => j(!0))
            }, "Установленные", 2)
          ]),
          n("form", {
            onSubmit: S[3] || (S[3] = Ze((k) => I(), ["prevent"]))
          }, [
            F(n("input", {
              "onUpdate:modelValue": S[2] || (S[2] = (k) => s.value = k),
              type: "search",
              "aria-label": "Поиск пакетов",
              placeholder: "Название или описание пакета…",
              maxlength: "100"
            }, null, 512), [
              [re, s.value]
            ]),
            n("button", { disabled: a.value }, "Найти", 8, If)
          ], 32)
        ]),
        !g.value.has_indexes && !a.value ? (p(), h("p", Mf, "Список доступных пакетов ещё не загружен. Нажмите «Обновить список пакетов» — ход загрузки появится в журнале.")) : V("", !0),
        n("div", {
          class: "gw-table-wrap",
          "aria-busy": a.value
        }, [
          n("table", Rf, [
            S[7] || (S[7] = n("thead", null, [
              n("tr", null, [
                n("th", null, "Пакет"),
                n("th", null, "Версия"),
                n("th")
              ])
            ], -1)),
            n("tbody", null, [
              (p(!0), h(N, null, se(g.value.items, (k) => (p(), h("tr", {
                key: k.name
              }, [
                n("td", null, [
                  n("strong", null, w(k.name), 1),
                  n("small", null, w(k.description), 1)
                ]),
                n("td", null, [
                  n("span", null, w(k.installed_version || k.version), 1),
                  k.installed_version && k.installed_version !== k.version ? (p(), h("small", Df, "В каталоге: " + w(k.version), 1)) : V("", !0)
                ]),
                n("td", null, [
                  k.installed_version ? (p(), h("span", Nf, "Установлен")) : (p(), h("button", {
                    key: 1,
                    disabled: r.value || a.value,
                    onClick: (R) => Z(k.name)
                  }, "Установить", 8, qf))
                ])
              ]))), 128))
            ])
          ])
        ], 8, Of),
        g.value.items.length ? V("", !0) : (p(), h("p", Hf, w(a.value ? "Загружаем пакеты…" : s.value ? "По вашему запросу пакеты не найдены." : "Пакетов в этом списке нет."), 1)),
        n("footer", Ff, [
          n("span", Lf, w(a.value ? "Загрузка…" : g.value.total ? g.value.offset + 1 + "–" + Math.min(g.value.offset + g.value.items.length, g.value.total) + " из " + g.value.total : "0 пакетов"), 1),
          n("div", jf, [
            n("button", {
              disabled: a.value || g.value.offset === 0,
              onClick: S[4] || (S[4] = (k) => I(Math.max(0, g.value.offset - 40)))
            }, "Назад", 8, Wf),
            n("button", {
              disabled: a.value || g.value.offset + 40 >= g.value.total,
              onClick: S[5] || (S[5] = (k) => I(g.value.offset + 40))
            }, "Далее", 8, Bf)
          ])
        ])
      ]),
      m.value ? (p(), ge(qe, {
        key: 0,
        title: "Установить " + m.value.package + "?",
        busy: r.value,
        onClose: te
      }, {
        default: Re(() => [
          S[9] || (S[9] = n("p", null, "Пакетный менеджер рассчитает и установит необходимые зависимости из настроенных репозиториев роутера.", -1)),
          n("pre", Kf, w(m.value.summary.join(`
`)), 1),
          S[10] || (S[10] = n("p", { class: "gw-hint" }, "Установочные скрипты пакетов могут менять настройки и запускать службы. Автоматическая замена уже установленных пакетов отключена.", -1)),
          c.value ? (p(), h("p", Gf, w(c.value), 1)) : V("", !0),
          n("div", zf, [
            n("button", {
              class: "gw-primary",
              disabled: r.value,
              onClick: le
            }, "Да, установить", 8, Jf),
            n("button", {
              disabled: r.value,
              onClick: te
            }, "Отмена", 8, Yf)
          ])
        ]),
        _: 1
      }, 8, ["title", "busy"])) : V("", !0)
    ], 64));
  }
}), Qf = { class: "gw-traffic-overview" }, Zf = { class: "gw-section-header" }, ep = { class: "gw-traffic-tools" }, tp = {
  key: 0,
  value: 900
}, lp = {
  key: 0,
  class: "gw-chart-note"
}, np = { class: "gw-traffic-grid" }, sp = { class: "gw-section-header" }, op = { class: "gw-traffic-speeds" }, ip = { class: "gw-rx" }, ap = { class: "gw-tx" }, rp = ["onPointermove", "onPointerleave"], up = ["aria-label"], dp = ["y1", "y2"], cp = ["d"], fp = ["d"], pp = {
  key: 0,
  class: "gw-chart-empty"
}, vp = {
  key: 1,
  class: "gw-chart-tip"
}, gp = { class: "gw-traffic-total" }, hp = { class: "gw-hint gw-counter-note" }, mp = /* @__PURE__ */ He({
  __name: "TrafficCharts",
  props: {
    monitor: {},
    nodeId: {},
    bridge: {}
  },
  setup(e) {
    const t = ["lan", "wan"], l = e, o = /* @__PURE__ */ H(null), s = /* @__PURE__ */ H({ lan: null, wan: null }), i = /* @__PURE__ */ H(null), a = /* @__PURE__ */ H(""), r = /* @__PURE__ */ H(!1), c = _e({
      get: () => o.value ?? (r.value ? 900 : 3600),
      set: (O) => {
        o.value = O;
      }
    });
    let g = !0, m = 0, y;
    async function T() {
      if (!l.bridge || !l.nodeId) return;
      const O = ++m;
      try {
        const S = await l.bridge.request("/api/gateways/" + encodeURIComponent(l.nodeId) + "/traffic?seconds=" + c.value);
        g && O === m && Array.isArray(S.traffic_history) && (i.value = S.traffic_history, r.value = Array.isArray(S.available_periods) && S.available_periods.includes(900), a.value = "");
      } catch (S) {
        g && O === m && (a.value = S instanceof Error ? S.message : String(S));
      }
    }
    Xe([c, () => l.nodeId], () => {
      s.value = { lan: null, wan: null }, i.value = null, T();
    }, { immediate: !0 }), ct(() => {
      y = setInterval(() => {
        document.hidden || T();
      }, 3e4);
    }), qt(() => {
      g = !1, m++, clearInterval(y);
    });
    const E = (O, S = !1) => {
      if (O == null) return "—";
      const k = ["Б", "КБ", "МБ", "ГБ", "ТБ"];
      let R = Number(O), z = 0;
      for (; R >= 1024 && z < k.length - 1; )
        R /= 1024, z++;
      return (R < 10 ? R.toFixed(1) : Math.round(R)) + " " + k[z] + (S ? "/с" : "");
    }, B = _e(() => {
      const O = i.value ?? l.monitor.traffic_history ?? [], S = O.at(-1)?.at || Date.now() / 1e3;
      return O.filter((k) => k.at >= S - c.value);
    }), I = _e(() => B.value.at(-1)?.at || l.monitor.checked_at || Date.now() / 1e3), Q = _e(() => I.value - c.value), X = (O) => new Date(O * 1e3).toLocaleString("ru-RU", c.value >= 43200 ? { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" } : { hour: "2-digit", minute: "2-digit" });
    function Z(O) {
      return Math.max(1, ...B.value.flatMap((S) => [S[O]?.rx_bps || 0, S[O]?.tx_bps || 0]));
    }
    function le(O, S) {
      let k = "", R = !1;
      const z = Z(O);
      return B.value.forEach((pe) => {
        const he = pe[O]?.[S];
        if (typeof he != "number") {
          R = !1;
          return;
        }
        const Pe = 10 + (pe.at - Q.value) / c.value * 580, Me = 132 - he / z * 112;
        k += (R ? " L" : " M") + Pe.toFixed(1) + " " + Me.toFixed(1), R = !0;
      }), k;
    }
    function j(O, S) {
      if (!B.value.length) {
        s.value[S] = null;
        return;
      }
      const k = O.currentTarget.getBoundingClientRect(), R = Q.value + Math.max(0, Math.min(1, (O.clientX - k.left) / k.width)) * c.value;
      s.value[S] = B.value.reduce((z, pe, he) => Math.abs(pe.at - R) < Math.abs(B.value[z].at - R) ? he : z, 0);
    }
    function te(O) {
      const S = s.value[O];
      return S == null ? null : B.value[S];
    }
    return (O, S) => (p(), h("section", Qf, [
      n("header", Zf, [
        S[6] || (S[6] = n("h3", null, "Трафик сети", -1)),
        n("div", ep, [
          S[5] || (S[5] = n("p", { class: "gw-hint" }, "Скорость и объём данных через LAN и WAN", -1)),
          F(n("select", {
            "onUpdate:modelValue": S[0] || (S[0] = (k) => c.value = k),
            "aria-label": "Период графиков"
          }, [
            r.value ? (p(), h("option", tp, "15 минут")) : V("", !0),
            S[1] || (S[1] = n("option", { value: 3600 }, "Час", -1)),
            S[2] || (S[2] = n("option", { value: 21600 }, "6 часов", -1)),
            S[3] || (S[3] = n("option", { value: 43200 }, "12 часов", -1)),
            S[4] || (S[4] = n("option", { value: 86400 }, "Сутки", -1))
          ], 512), [
            [xe, c.value]
          ])
        ])
      ]),
      a.value ? (p(), h("p", lp, w(a.value), 1)) : V("", !0),
      n("div", np, [
        (p(), h(N, null, se(t, (k) => n("article", {
          key: k,
          class: "gw-panel gw-traffic-card"
        }, [
          n("header", sp, [
            n("h3", null, w(k.toUpperCase()), 1),
            n("span", {
              class: Ue(["gw-status", e.monitor.traffic?.[k]?.up ? "good" : "warn"])
            }, w(e.monitor.traffic?.[k]?.up ? "Подключён" : "Отключён"), 3)
          ]),
          n("div", op, [
            n("span", ip, "↓ " + w(E(e.monitor.traffic?.[k]?.rx_bps, !0)), 1),
            n("span", ap, "↑ " + w(E(e.monitor.traffic?.[k]?.tx_bps, !0)), 1)
          ]),
          n("div", {
            class: "gw-traffic-plot",
            onPointermove: (R) => j(R, k),
            onPointerleave: (R) => s.value[k] = null
          }, [
            (p(), h("svg", {
              viewBox: "0 0 600 148",
              preserveAspectRatio: "none",
              role: "img",
              "aria-label": "Скорость трафика " + k.toUpperCase()
            }, [
              (p(), h(N, null, se([20, 76, 132], (R) => n("line", {
                key: R,
                x1: "10",
                y1: R,
                x2: "590",
                y2: R,
                class: "gw-chart-grid"
              }, null, 8, dp)), 64)),
              n("path", {
                d: le(k, "rx_bps"),
                class: "gw-chart-rx"
              }, null, 8, cp),
              n("path", {
                d: le(k, "tx_bps"),
                class: "gw-chart-tx"
              }, null, 8, fp)
            ], 8, up)),
            B.value.length < 2 ? (p(), h("div", pp, "Накапливаем данные графика")) : V("", !0),
            te(k) ? (p(), h("div", vp, w(new Date(te(k).at * 1e3).toLocaleTimeString()) + " · ↓ " + w(E(te(k)[k]?.rx_bps, !0)) + " · ↑ " + w(E(te(k)[k]?.tx_bps, !0)), 1)) : V("", !0)
          ], 40, rp),
          n("div", gp, [
            n("div", null, [
              S[7] || (S[7] = n("span", null, "Получено", -1)),
              n("strong", null, w(E(e.monitor.traffic?.[k]?.rx_bytes)), 1)
            ]),
            n("div", null, [
              S[8] || (S[8] = n("span", null, "Передано", -1)),
              n("strong", null, w(E(e.monitor.traffic?.[k]?.tx_bytes)), 1)
            ])
          ])
        ])), 64))
      ]),
      n("p", hp, "Графики: " + w(X(Q.value)) + " — " + w(X(I.value)) + ". Объём данных — с последней загрузки / сброса счётчиков", 1)
    ]));
  }
});
function Le(e) {
  if (e == null || e === "" || typeof e == "boolean") return null;
  const t = Number(e);
  return Number.isFinite(t) ? t : null;
}
function cs(e, t) {
  return !Number.isInteger(e) || e < 1 ? null : t === "2g" ? e <= 14 ? e === 14 ? 2484 : 2407 + e * 5 : null : t === "6g" ? e <= 233 ? e === 2 ? 5935 : 5950 + e * 5 : null : t === "5g" && e <= 196 ? (e >= 182 ? 4e3 : 5e3) + e * 5 : null;
}
function bp(e, t) {
  const l = e?.frequencies?.length ? e.frequencies : t?.frequencies || [], o = Le(t?.frequency) || Le(l[0]?.mhz || l[0]?.frequency), s = t?.band || (o ? o < 3e3 ? "2g" : o >= 5925 ? "6g" : "5g" : null);
  return (e?.networks || []).map((i) => {
    let a = Le(i.channel), r = Le(i.frequency) || Le(i.mhz);
    const c = ["2g", "5g", "6g"].includes(String(i.band)) ? String(i.band) : [2, 5, 6].includes(Number(i.band)) ? String(i.band) + "g" : s;
    if (!r && a) {
      const m = l.find((y) => {
        const T = Le(y.mhz || y.frequency);
        return Le(y.channel) === a && (!c || T != null && (T < 3e3 ? "2g" : T >= 5925 ? "6g" : "5g") === c);
      });
      r = Le(m?.mhz || m?.frequency) || cs(a, c);
    }
    !a && r && (a = r === 2484 ? 14 : r === 5935 ? 2 : (r - (r < 3e3 ? 2407 : r >= 5955 ? 5950 : r < 5e3 ? 4e3 : 5e3)) / 5);
    let g = Le(i.signal);
    return g != null && g >= 2147483648 && g <= 4294967295 && (g -= 4294967296), { ...i, ssid: String(i.ssid ?? ""), bssid: String(i.bssid ?? ""), channel: a, frequency: r, signal: g };
  }).sort((i, a) => (a.signal ?? -200) - (i.signal ?? -200));
}
function Wl(e, t) {
  return e > 1e3 ? e : cs(e, t < 3e3 ? "2g" : t >= 5925 ? "6g" : "5g") || t;
}
function yp(e) {
  const t = e.ht_operation || {}, l = String(t.secondary_channel_offset || "").toLowerCase();
  let o = l === "above" || l === "below" ? 40 : 20, s = e.frequency + (l === "above" ? 10 : l === "below" ? -10 : 0), i = !!e.ht_operation && Le(t.channel_width) != null || ["above", "below"].includes(l);
  for (const a of ["vht_operation", "he_operation", "eht_operation"]) {
    const r = e[a], c = Le(r?.channel_width);
    if (r && c === 20 && o === 20 && (i = !0), !r || c == null || c <= (a === "vht_operation" ? 40 : 20)) continue;
    const g = Le(r.center_freq_1), m = Le(r.center_freq_2);
    if (g != null) {
      if (c === 8080 && m != null)
        return [g, m].map((y) => ({ center: Wl(y, e.frequency), width: 80, known: !0 }));
      if ([40, 80, 160, 320].includes(c)) {
        if (o = c, s = Wl(g, e.frequency), i = !0, (c === 160 || c === 320) && m != null && m > 0) {
          const y = Wl(m, e.frequency);
          (c === 320 || Math.abs(y - s) === 40) && (s = y);
        }
        if (c === 80 && m != null && m !== 0) {
          const y = Wl(m, e.frequency), T = Math.abs(y - s);
          if (T === 40)
            o = 160, s = y;
          else if (T > 40) return [s, y].map((E) => ({ center: E, width: 80, known: !0 }));
        }
      }
    }
  }
  return [{ center: s, width: o, known: i }];
}
const wp = { class: "gw-channel-charts" }, _p = { class: "gw-spectrum-card" }, kp = { class: "gw-spectrum-plot" }, $p = ["viewBox"], Cp = ["y1", "x2", "y2"], xp = ["y"], Sp = ["x"], Vp = { key: 1 }, Tp = ["x", "y"], Ep = ["aria-label", "onMouseenter", "onFocus"], Up = ["x", "y", "width", "height", "fill"], Pp = ["x1", "x2"], Ap = ["opacity", "aria-label", "onMouseenter", "onFocus", "onClick", "onKeydown"], Ip = ["d", "fill", "stroke", "stroke-width"], Mp = ["x", "y"], Op = ["x"], Rp = ["x"], Dp = {
  key: 0,
  class: "gw-spectrum-empty"
}, Np = {
  class: "gw-spectrum-detail",
  role: "status",
  "aria-live": "polite"
}, qp = ["title"], Hp = {
  class: "gw-spectrum-key",
  "aria-label": "Легенда графика"
}, Fp = { key: 0 }, Lp = { key: 2 }, jp = { class: "gw-spectrum-legend" }, Wp = ["aria-pressed", "onMouseenter", "onFocus", "onClick"], Bp = /* @__PURE__ */ He({
  __name: "WirelessChannels",
  props: {
    data: {},
    radio: {}
  },
  setup(e) {
    const t = e, l = /* @__PURE__ */ H(null), o = /* @__PURE__ */ H(null), s = /* @__PURE__ */ H(null), i = _e(() => o.value || l.value), a = window.matchMedia("(max-width:600px)"), r = /* @__PURE__ */ H(a.matches), c = () => {
      r.value = a.matches;
    };
    ct(() => a.addEventListener("change", c)), qt(() => a.removeEventListener("change", c));
    const g = _e(() => r.value ? 520 : 900), m = 48, y = _e(() => g.value - 48), T = 26, E = 244, B = (ne) => typeof ne == "number" && Number.isFinite(ne);
    function I(ne) {
      let U = 0;
      for (const d of ne) U = U * 31 + d.charCodeAt(0) >>> 0;
      return `hsl(${(Math.imul(U, 2654435761) >>> 0) % 360} 65% 56%)`;
    }
    const Q = _e(() => (t.data.networks || []).filter((ne) => B(ne.frequency) && B(ne.signal)).map((ne, U) => ({ ...ne, id: (ne.bssid || U) + ":" + ne.frequency, color: I(ne.bssid || ne.ssid || String(U)), segments: yp(ne) })).sort((ne, U) => ne.signal - U.signal));
    Xe(() => t.data.networks, () => {
      l.value && !Q.value.some((ne) => ne.id === l.value) && (l.value = null), o.value = null, s.value = null;
    });
    const X = _e(() => {
      const ne = /* @__PURE__ */ new Map(), U = (d, u) => (ne.has(d) || ne.set(d, { frequency: d, channel: u, count: 0, busy_pct: null, noise: null }), ne.get(d));
      for (const d of t.data.frequencies || []) {
        const u = Le(d.mhz || d.frequency);
        u != null && U(u, d.channel);
      }
      for (const d of t.data.networks || []) B(d.frequency) && U(d.frequency, d.channel).count++;
      for (const d of t.data.survey || []) {
        const u = Le(d.frequency);
        if (u == null) continue;
        const v = u < 3e3 ? "2g" : u >= 5925 ? "6g" : "5g", _ = u === 2484 ? 14 : u === 5935 ? 2 : (u - (v === "2g" ? 2407 : v === "6g" ? 5950 : u < 5e3 ? 4e3 : 5e3)) / 5;
        Object.assign(U(u, _), d, { busy_pct: Le(d.busy_pct) });
      }
      return [...ne.values()].sort((d, u) => d.frequency - u.frequency);
    }), Z = _e(() => {
      const ne = [...X.value.map((U) => U.frequency), ...Q.value.flatMap((U) => U.segments.flatMap((d) => [d.center - d.width / 2, d.center + d.width / 2]))];
      return ne.length ? [Math.min(...ne) - 5, Math.max(...ne) + 5] : [2400, 2490];
    }), le = (ne) => m + (ne - Z.value[0]) / Math.max(1, Z.value[1] - Z.value[0]) * (y.value - m), j = (ne) => E - (Math.max(-100, Math.min(-20, ne)) + 100) / 80 * (E - T), te = (ne) => E - Math.max(0, Math.min(100, ne)) / 100 * (E - T), O = _e(() => X.value.filter((ne, U) => U % Math.max(1, Math.ceil(X.value.length / (r.value ? 8 : 18))) === 0)), S = _e(() => X.value.some((ne) => B(ne.busy_pct))), k = _e(() => Math.max(3, Math.min(20, (y.value - m) / Math.max(1, X.value.length) * 0.5))), R = _e(() => X.value.find((ne) => ne.in_use)?.frequency || Le(t.radio?.frequency) || cs(Number(t.radio?.runtime_channel || t.radio?.channel), t.radio?.band)), z = _e(() => Q.value.find((ne) => ne.id === i.value));
    function pe(ne, U) {
      const d = le(U.center - U.width / 2), u = le(U.center + U.width / 2), v = j(ne.signal), _ = Math.min((u - d) / 4, (y.value - m) * 5 / (Z.value[1] - Z.value[0]));
      return `M${d},${E} L${d + _},${v} L${u - _},${v} L${u},${E} Z`;
    }
    const he = (ne) => ne.segments.every((U) => U.known) ? ne.segments.map((U) => U.width).join("+") + " МГц" : "ширина неизвестна (контур 20 МГц)", Pe = (ne) => {
      l.value = l.value === ne.id ? null : ne.id;
    }, Me = _e(() => z.value ? `${z.value.ssid || "Скрытая сеть"} · канал ${z.value.channel} · ${z.value.signal} dBm · ${he(z.value)}` : s.value ? `Канал ${s.value.channel} · ${s.value.frequency} МГц · ${s.value.busy_pct == null ? "нет измерения занятости" : "занятость " + s.value.busy_pct + "%"}${s.value.noise == null ? "" : " · шум " + s.value.noise + " dBm"} · сетей: ${s.value.count}` : "Наведите на сеть или столбик. Нажмите на название сети, чтобы выделить её.");
    return (ne, U) => (p(), h("section", wp, [
      n("article", _p, [
        n("header", null, [
          U[7] || (U[7] = n("h3", null, "Wi-Fi каналы и соседние сети", -1)),
          n("span", null, w(Q.value.length) + " сетей на графике", 1)
        ]),
        n("div", kp, [
          (p(), h("svg", {
            viewBox: `0 0 ${g.value} 282`,
            role: "img",
            "aria-label": "Каналы и уровень сигнала соседних Wi-Fi сетей",
            onMouseleave: U[4] || (U[4] = (d) => {
              o.value = null, s.value = null;
            })
          }, [
            (p(), h(N, null, se([-100, -80, -60, -40, -20], (d) => n("g", { key: d }, [
              n("line", {
                x1: m,
                y1: j(d),
                x2: y.value,
                y2: j(d),
                class: "gw-spectrum-grid"
              }, null, 8, Cp),
              n("text", {
                x: "40",
                y: j(d) + 4,
                "text-anchor": "end"
              }, w(d), 9, xp)
            ])), 64)),
            U[8] || (U[8] = n("text", {
              x: "8",
              y: "14"
            }, "dBm", -1)),
            S.value ? (p(), h("text", {
              key: 0,
              x: g.value - 8,
              y: "14",
              "text-anchor": "end"
            }, "%", 8, Sp)) : V("", !0),
            S.value ? (p(), h("g", Vp, [
              (p(), h(N, null, se([0, 25, 50, 75, 100], (d) => n("text", {
                key: d,
                x: y.value + 8,
                y: te(d) + 4
              }, w(d), 9, Tp)), 64))
            ])) : V("", !0),
            (p(!0), h(N, null, se(X.value.filter((d) => B(d.busy_pct)), (d) => (p(), h("g", {
              key: d.frequency,
              class: "gw-spectrum-occupancy",
              tabindex: "0",
              role: "button",
              "aria-label": `Канал ${d.channel}, занятость ${d.busy_pct}%`,
              onMouseenter: (u) => {
                s.value = d, o.value = null;
              },
              onMouseleave: U[0] || (U[0] = (u) => s.value = null),
              onFocus: (u) => {
                s.value = d, o.value = null;
              },
              onBlur: U[1] || (U[1] = (u) => s.value = null)
            }, [
              n("rect", {
                x: le(d.frequency) - k.value / 2,
                y: te(d.busy_pct),
                width: k.value,
                height: Math.max(1, E - te(d.busy_pct)),
                rx: "2",
                fill: d.busy_pct >= 70 ? "#e4b56c" : "#62c7a7",
                "fill-opacity": "0.45"
              }, null, 8, Up)
            ], 40, Ep))), 128)),
            R.value ? (p(), h("line", {
              key: 2,
              x1: le(R.value),
              y1: T,
              x2: le(R.value),
              y2: E,
              class: "gw-spectrum-current"
            }, null, 8, Pp)) : V("", !0),
            (p(!0), h(N, null, se(Q.value, (d) => (p(), h("g", {
              key: d.id,
              opacity: i.value && i.value !== d.id ? 0.2 : 1,
              class: "gw-spectrum-peer",
              tabindex: "0",
              role: "button",
              "aria-label": `${d.ssid || "Скрытая сеть"}, канал ${d.channel}, ${d.signal} dBm`,
              onMouseenter: (u) => {
                o.value = d.id, s.value = null;
              },
              onMouseleave: U[2] || (U[2] = (u) => o.value = null),
              onFocus: (u) => {
                o.value = d.id, s.value = null;
              },
              onBlur: U[3] || (U[3] = (u) => o.value = null),
              onClick: (u) => Pe(d),
              onKeydown: [
                ln(Ze((u) => Pe(d), ["prevent"]), ["enter"]),
                ln(Ze((u) => Pe(d), ["prevent"]), ["space"])
              ]
            }, [
              (p(!0), h(N, null, se(d.segments, (u, v) => (p(), h("path", {
                key: v,
                d: pe(d, u),
                fill: d.color,
                "fill-opacity": "0.13",
                stroke: d.color,
                "stroke-width": i.value === d.id ? 3 : 1.5
              }, null, 8, Ip))), 128)),
              n("text", {
                x: le(d.frequency),
                y: j(d.signal) - 5,
                "text-anchor": "middle",
                style: Cl({ fill: d.color }),
                class: "gw-spectrum-ssid"
              }, w((d.ssid || "Скрытая сеть").slice(0, r.value ? 12 : 20)), 13, Mp)
            ], 40, Ap))), 128)),
            (p(!0), h(N, null, se(O.value, (d) => (p(), h("g", {
              key: d.frequency
            }, [
              n("text", {
                x: le(d.frequency),
                y: "263",
                "text-anchor": "middle"
              }, w(d.channel), 9, Op)
            ]))), 128)),
            n("text", {
              x: y.value,
              y: "279",
              "text-anchor": "end"
            }, "Канал", 8, Rp)
          ], 40, $p)),
          Q.value.length ? V("", !0) : (p(), h("p", Dp, w(e.data.networks?.length ? "Сети найдены, но драйвер не сообщил канал или уровень сигнала." : "Соседние сети не найдены"), 1))
        ]),
        n("div", Np, [
          n("span", { title: Me.value }, w(Me.value), 9, qp)
        ]),
        n("div", Hp, [
          U[13] || (U[13] = n("span", null, [
            n("i", { class: "gw-key-line" }),
            A("Контуры — сигнал сетей, шкала слева (dBm)")
          ], -1)),
          R.value ? (p(), h("span", Fp, [...U[9] || (U[9] = [
            n("i", { class: "gw-key-current" }, null, -1),
            A("Пунктир — текущий канал", -1)
          ])])) : V("", !0),
          S.value ? (p(), h(N, { key: 1 }, [
            U[10] || (U[10] = n("span", null, [
              n("i", { class: "gw-key-busy" }),
              A("Зелёный — занятость менее 70%")
            ], -1)),
            U[11] || (U[11] = n("span", null, [
              n("i", { class: "gw-key-crowded" }),
              A("Жёлтый — занятость от 70%")
            ], -1)),
            U[12] || (U[12] = n("span", null, "Столбики — занятость эфира, шкала справа (%)", -1))
          ], 64)) : (p(), h("span", Lp, "Измерения занятости от драйвера отсутствуют"))
        ]),
        n("div", jp, [
          (p(!0), h(N, null, se(Q.value, (d) => (p(), h("button", {
            key: d.id,
            class: Ue({ on: l.value === d.id }),
            "aria-pressed": l.value === d.id,
            onMouseenter: (u) => {
              o.value = d.id, s.value = null;
            },
            onMouseleave: U[5] || (U[5] = (u) => o.value = null),
            onFocus: (u) => {
              o.value = d.id, s.value = null;
            },
            onBlur: U[6] || (U[6] = (u) => o.value = null),
            onClick: (u) => Pe(d)
          }, [
            n("i", {
              style: Cl({ background: d.color })
            }, null, 4),
            n("span", null, w(d.ssid || "Скрытая сеть"), 1),
            n("small", null, w(d.signal) + " dBm", 1)
          ], 42, Wp))), 128))
        ]),
        U[14] || (U[14] = n("p", { class: "gw-chart-note" }, "Высота контура — сила сигнала, ширина — полоса сети. Если ширина неизвестна, показан контур 20 МГц. Занятость измеряется драйвером; число сетей не заменяет это измерение.", -1))
      ])
    ]));
  }
}), Kp = { class: "gw-wireless" }, Gp = { class: "gw-section-header" }, zp = ["disabled"], Jp = {
  key: 0,
  class: "gw-error",
  role: "alert"
}, Yp = {
  key: 1,
  class: "gw-hint"
}, Xp = { class: "gw-section-header" }, Qp = { class: "gw-hint" }, Zp = { key: 0 }, ev = { class: "gw-actions" }, tv = ["disabled", "onClick"], lv = ["disabled", "onClick"], nv = { class: "gw-table-wrap" }, sv = { class: "gw-check" }, ov = { class: "gw-two" }, iv = ["value"], av = ["value", "disabled"], rv = ["value"], uv = { class: "gw-two" }, dv = ["value"], cv = ["value"], fv = ["value"], pv = ["value"], vv = { class: "gw-rule-fields" }, gv = { class: "gw-check" }, hv = ["onUpdate:modelValue"], mv = ["onUpdate:modelValue"], bv = ["onUpdate:modelValue"], yv = ["value"], wv = ["value"], _v = { key: 0 }, kv = {
  key: 1,
  class: "gw-hint"
}, $v = { class: "gw-wifi-networks" }, Cv = ["onUpdate:modelValue", "value"], xv = { class: "gw-two" }, Sv = { class: "gw-check" }, Vv = ["onUpdate:modelValue"], Tv = { class: "gw-check" }, Ev = ["onUpdate:modelValue"], Uv = {
  key: 0,
  class: "gw-error",
  role: "alert"
}, Pv = { class: "gw-actions" }, Av = ["disabled"], Iv = ["disabled"], Mv = { class: "gw-change-list" }, Ov = { class: "gw-hint" }, Rv = {
  key: 0,
  class: "gw-error",
  role: "alert"
}, Dv = { class: "gw-actions" }, Nv = ["disabled"], qv = ["disabled"], Hv = { class: "gw-section-header" }, Fv = { class: "gw-hint" }, Lv = ["disabled"], jv = {
  key: 0,
  class: "gw-error",
  role: "alert"
}, Wv = {
  class: "gw-tabs",
  "aria-label": "Результаты сканирования"
}, Bv = { class: "gw-table-wrap" }, Kv = {
  key: 0,
  class: "gw-hint"
}, Gv = /* @__PURE__ */ He({
  __name: "WirelessEditor",
  props: {
    node: {},
    bridge: {}
  },
  emits: ["changed"],
  setup(e, { emit: t }) {
    const l = e, o = t, s = /* @__PURE__ */ H({ radios: [], networks: [] }), i = /* @__PURE__ */ H(!1), a = /* @__PURE__ */ H(!1), r = /* @__PURE__ */ H(""), c = /* @__PURE__ */ H(null), g = /* @__PURE__ */ H(null), m = /* @__PURE__ */ H(!1), y = /* @__PURE__ */ H(null), T = /* @__PURE__ */ H(null), E = /* @__PURE__ */ H(""), B = /* @__PURE__ */ H("channels");
    let I = !0;
    const Q = () => "/api/gateways/" + encodeURIComponent(l.node.id), X = (u, v, _ = "POST") => l.bridge.request(Q() + u, { method: _, headers: { "Content-Type": "application/json" }, body: JSON.stringify(v) }), Z = (u) => Array.isArray(u) ? u : u ? String(u).split(/\s+/) : [], le = { none: "Без защиты", psk2: "WPA2-PSK", "psk2+ccmp": "WPA2-PSK (CCMP)", "psk-mixed": "WPA/WPA2-PSK", sae: "WPA3-SAE", "sae-mixed": "WPA2/WPA3", "sae+ccmp": "WPA3-SAE (CCMP)", "sae-mixed+ccmp": "WPA2/WPA3 (CCMP)" }, j = (u) => typeof u == "number" ? (u / 1e3).toFixed(3) + " ГГц" : "—", te = (u) => ({ "2g": "2,4 ГГц", "5g": "5 ГГц", "6g": "6 ГГц" })[u.band] || j(u.frequency), O = _e(() => bp(T.value, y.value));
    function S(u) {
      return u.encryption?.enabled ? u.encryption.wpa?.length ? "WPA " + u.encryption.wpa.join("/") : "Защищена" : "Открытая";
    }
    async function k() {
      i.value = !0, r.value = "";
      try {
        const u = await l.bridge.request(Q() + "/wireless");
        I && (s.value = u);
      } catch (u) {
        I && (r.value = u.message);
      } finally {
        I && (i.value = !1);
      }
    }
    function R(u) {
      r.value = "", c.value = {
        ...u,
        original: u,
        disabled: u.disabled === "1",
        channel: u.channel || "auto",
        country: u.country || "",
        txpower: u.txpower || "",
        htmode: u.htmode || "NOHT",
        interfaces: u.interfaces.map((v) => ({ ...v, original: v, disabled: v.disabled === "1", hidden: v.hidden === "1", isolate: v.isolate === "1", network: Z(v.network), ssid: v.ssid || "", encryption: v.encryption || "none", key: "" }))
      };
    }
    const z = (u) => {
      try {
        return new Intl.DisplayNames(["ru"], { type: "region" }).of(u) || u;
      } catch {
        return u;
      }
    }, pe = (u) => {
      const v = /^(HT|VHT|HE|EHT)(\d+)$/.exec(u);
      return v ? `${v[2]} МГц · Wi-Fi ${{ HT: "4 (HT)", VHT: "5 (VHT)", HE: "6 (HE)", EHT: "7 (EHT)" }[v[1]]}` : "20 МГц · без расширений HT";
    };
    function he() {
      c.value = null, r.value = "";
    }
    function Pe(u, v, _, K = []) {
      const Ve = {};
      for (const W of _) {
        const Ne = K.includes(W) ? u[W] ? "1" : "0" : u[W] === "" ? null : u[W], Ht = K.includes(W) ? v[W] === "1" ? "1" : "0" : W === "network" ? Z(v[W]) : v[W] ?? (W === "channel" ? "auto" : W === "encryption" ? "none" : W === "htmode" ? "NOHT" : null);
        JSON.stringify(Ne) !== JSON.stringify(Ht) && (Ve[W] = Ne);
      }
      return Ve;
    }
    async function Me() {
      a.value = !0, r.value = "";
      try {
        const u = c.value, v = {
          config_hash: s.value.config_hash,
          radio: u.name,
          settings: Pe(u, u.original, ["disabled", "channel", "country", "txpower", "htmode"], ["disabled"]),
          interfaces: u.interfaces.map((_) => {
            const K = Pe(_, _.original, ["disabled", "ssid", "encryption", "hidden", "isolate", "network"], ["disabled", "hidden", "isolate"]);
            return _.key && _.encryption !== "none" && (K.key = _.key), { id: _.id, settings: K };
          }).filter((_) => Object.keys(_.settings).length)
        };
        g.value = await X("/network/plan", { action: "wireless", data: v });
        for (const _ of u.interfaces) _.key = "";
      } catch (u) {
        r.value = u.message;
      } finally {
        a.value = !1;
      }
    }
    function ne() {
      const u = g.value?.plan_token;
      g.value = null, r.value = "", u && X("/operation-plans/" + encodeURIComponent(u), {}, "DELETE").catch((v) => {
        r.value = v.message;
      });
    }
    async function U() {
      a.value = !0, r.value = "";
      try {
        const u = await X("/router-operations", { plan_token: g.value.plan_token, confirmed: !0 });
        g.value = null, he(), l.bridge.task({ taskId: u.task_id, title: "Настройка Wi-Fi", cancellable: !1, onDone: async () => {
          await k(), o("changed");
        } });
      } catch (u) {
        r.value = u.message;
      } finally {
        a.value = !1;
      }
    }
    async function d(u) {
      if (!m.value) {
        y.value?.name !== u.name && (T.value = null), y.value = u, m.value = !0, E.value = "";
        try {
          const v = await X("/wireless/" + encodeURIComponent(u.name) + "/scan", {});
          I && (T.value = v);
        } catch (v) {
          I && (E.value = v.message);
        } finally {
          I && (m.value = !1);
        }
      }
    }
    return ct(() => {
      k();
    }), qt(() => {
      I = !1, c.value = null;
    }), (u, v) => (p(), h(N, null, [
      n("section", Kp, [
        n("header", Gp, [
          v[9] || (v[9] = n("div", null, [
            n("h3", null, "Беспроводные сети"),
            n("p", { class: "gw-hint" }, "Радиомодули, сети Wi-Fi и обзор каналов")
          ], -1)),
          n("button", {
            disabled: i.value || a.value,
            onClick: k
          }, "Обновить", 8, zp)
        ]),
        r.value && !c.value && !g.value ? (p(), h("p", Jp, w(r.value), 1)) : V("", !0),
        !s.value.radios.length && !r.value ? (p(), h("p", Yp, w(i.value ? "Получаем настройки Wi-Fi…" : "На шлюзе нет настроенных радиомодулей Wi-Fi."), 1)) : V("", !0),
        (p(!0), h(N, null, se(s.value.radios, (_) => (p(), h("section", {
          key: _.name,
          class: "gw-radio"
        }, [
          n("header", Xp, [
            n("div", null, [
              n("h3", null, w(_.name) + " · " + w(te(_)), 1),
              n("p", Qp, [
                A(w(_.up ? "Работает" : _.disabled === "1" ? "Выключен" : "Не активен") + " · Канал " + w(_.runtime_channel || _.channel || "Авто"), 1),
                _.htmode ? (p(), h("span", Zp, " · " + w(_.htmode), 1)) : V("", !0)
              ])
            ]),
            n("div", ev, [
              n("button", {
                disabled: a.value || m.value || !_.up,
                onClick: (K) => d(_)
              }, "Просмотр каналов", 8, tv),
              n("button", {
                disabled: a.value || m.value,
                onClick: (K) => R(_)
              }, "Настроить Wi-Fi", 8, lv)
            ])
          ]),
          n("div", nv, [
            n("table", null, [
              v[10] || (v[10] = n("thead", null, [
                n("tr", null, [
                  n("th", null, "Сеть"),
                  n("th", null, "Режим"),
                  n("th", null, "Защита"),
                  n("th", null, "Подключение"),
                  n("th", null, "Состояние")
                ])
              ], -1)),
              n("tbody", null, [
                (p(!0), h(N, null, se(_.interfaces, (K) => (p(), h("tr", {
                  key: K.id
                }, [
                  n("td", null, [
                    n("strong", null, w(K.ssid || K.id), 1),
                    n("small", null, w(K.ifname || K.id), 1)
                  ]),
                  n("td", null, w(K.mode === "ap" ? "Точка доступа" : K.mode === "sta" ? "Клиент" : K.mode), 1),
                  n("td", null, w(le[K.encryption || "none"] || K.encryption), 1),
                  n("td", null, w(Z(K.network).join(", ") || "Без привязки"), 1),
                  n("td", null, [
                    n("span", {
                      class: Ue(["gw-status", _.up && K.disabled !== "1" ? "good" : "warn"])
                    }, w(K.disabled === "1" ? "Выключена" : _.up ? "Включена" : "Не активна"), 3)
                  ])
                ]))), 128))
              ])
            ])
          ])
        ]))), 128))
      ]),
      c.value && !g.value ? (p(), ge(qe, {
        key: 0,
        title: "Настройки Wi-Fi · " + c.value.name,
        wide: !0,
        compact: !0,
        busy: a.value,
        onClose: he
      }, {
        default: Re(() => [
          n("form", {
            class: "gw-form",
            onSubmit: Ze(Me, ["prevent"])
          }, [
            n("label", sv, [
              F(n("input", {
                "onUpdate:modelValue": v[0] || (v[0] = (_) => c.value.disabled = _),
                type: "checkbox"
              }, null, 512), [
                [We, c.value.disabled]
              ]),
              v[11] || (v[11] = A(" Выключить радиомодуль", -1))
            ]),
            n("div", ov, [
              n("label", null, [
                v[13] || (v[13] = A("Канал", -1)),
                F(n("select", {
                  "onUpdate:modelValue": v[1] || (v[1] = (_) => c.value.channel = _)
                }, [
                  v[12] || (v[12] = n("option", { value: "auto" }, "Автоматически", -1)),
                  c.value.channel !== "auto" && !c.value.frequencies.some((_) => String(_.channel) === c.value.channel) ? (p(), h("option", {
                    key: 0,
                    value: c.value.channel
                  }, w(c.value.channel) + " (текущий)", 9, iv)) : V("", !0),
                  (p(!0), h(N, null, se(c.value.frequencies, (_) => (p(), h("option", {
                    key: _.channel,
                    value: String(_.channel),
                    disabled: _.restricted
                  }, w(_.channel) + " · " + w(j(_.mhz || _.frequency)) + w(_.restricted ? " · Недоступен" : ""), 9, av))), 128))
                ], 512), [
                  [xe, c.value.channel]
                ])
              ]),
              n("label", null, [
                v[14] || (v[14] = A("Ширина канала", -1)),
                F(n("select", {
                  "onUpdate:modelValue": v[2] || (v[2] = (_) => c.value.htmode = _)
                }, [
                  (p(!0), h(N, null, se([.../* @__PURE__ */ new Set([c.value.original.htmode || "NOHT", ...c.value.htmodes])], (_) => (p(), h("option", {
                    key: String(_),
                    value: _
                  }, w(pe(String(_))), 9, rv))), 128))
                ], 512), [
                  [xe, c.value.htmode]
                ])
              ])
            ]),
            v[28] || (v[28] = n("p", { class: "gw-hint gw-mode-help" }, "HT — Wi-Fi 4, VHT — Wi-Fi 5, HE — Wi-Fi 6, EHT — Wi-Fi 7. Более широкая полоса может повысить скорость, но занимает больше эфира; на загруженных 2,4 ГГц обычно удобнее 20 МГц.", -1)),
            n("div", uv, [
              n("label", null, [
                v[17] || (v[17] = A("Страна", -1)),
                F(n("select", {
                  "onUpdate:modelValue": v[3] || (v[3] = (_) => c.value.country = _),
                  "aria-label": "Страна"
                }, [
                  v[15] || (v[15] = n("option", { value: "" }, "По умолчанию", -1)),
                  v[16] || (v[16] = n("option", { value: "00" }, "00 · Всемирный регуляторный домен", -1)),
                  c.value.country && c.value.country !== "00" && !c.value.countries?.some((_) => _.code === c.value.country) ? (p(), h("option", {
                    key: 0,
                    value: c.value.country,
                    disabled: ""
                  }, w(c.value.country) + " · текущее значение", 9, dv)) : V("", !0),
                  (p(!0), h(N, null, se(c.value.countries || [], (_) => (p(), h("option", {
                    key: _.code,
                    value: _.code
                  }, w(_.code) + " · " + w(z(_.code)), 9, cv))), 128))
                ], 512), [
                  [xe, c.value.country]
                ])
              ]),
              n("label", null, [
                v[19] || (v[19] = A("Мощность передатчика", -1)),
                F(n("select", {
                  "onUpdate:modelValue": v[4] || (v[4] = (_) => c.value.txpower = _),
                  "aria-label": "Мощность передатчика"
                }, [
                  v[18] || (v[18] = n("option", { value: "" }, "Автоматически", -1)),
                  c.value.txpower && !c.value.txpowers?.some((_) => String(_.dbm) === String(c.value.txpower)) ? (p(), h("option", {
                    key: 0,
                    value: c.value.txpower,
                    disabled: ""
                  }, w(c.value.txpower) + " dBm · текущее значение", 9, fv)) : V("", !0),
                  (p(!0), h(N, null, se(c.value.txpowers || [], (_) => (p(), h("option", {
                    key: _.dbm,
                    value: String(_.dbm)
                  }, w(_.dbm) + " dBm · " + w(_.mw) + " мВт", 9, pv))), 128))
                ], 512), [
                  [xe, c.value.txpower]
                ]),
                v[20] || (v[20] = n("small", null, "Только значения драйвера; ограничения выбранной страны применяет OpenWrt.", -1))
              ])
            ]),
            v[29] || (v[29] = n("h3", null, "Сети на радиомодуле", -1)),
            (p(!0), h(N, null, se(c.value.interfaces, (_) => (p(), h("details", {
              key: _.id,
              class: "gw-wifi-form",
              open: ""
            }, [
              n("summary", null, w(_.ssid || _.id) + " · " + w(_.mode === "ap" ? "Точка доступа" : _.mode === "sta" ? "Клиент" : _.mode), 1),
              n("div", vv, [
                n("label", gv, [
                  F(n("input", {
                    "onUpdate:modelValue": (K) => _.disabled = K,
                    type: "checkbox"
                  }, null, 8, hv), [
                    [We, _.disabled]
                  ]),
                  v[21] || (v[21] = A(" Выключить эту сеть", -1))
                ]),
                n("label", null, [
                  v[22] || (v[22] = A("Имя сети (SSID)", -1)),
                  F(n("input", {
                    "onUpdate:modelValue": (K) => _.ssid = K,
                    required: "",
                    maxlength: "32"
                  }, null, 8, mv), [
                    [re, _.ssid]
                  ])
                ]),
                n("label", null, [
                  v[23] || (v[23] = A("Защита", -1)),
                  F(n("select", {
                    "onUpdate:modelValue": (K) => _.encryption = K
                  }, [
                    le[_.original.encryption] ? V("", !0) : (p(), h("option", {
                      key: 0,
                      value: _.original.encryption
                    }, w(_.original.encryption) + " (текущая)", 9, yv)),
                    (p(), h(N, null, se(le, (K, Ve) => n("option", {
                      key: Ve,
                      value: Ve
                    }, w(K), 9, wv)), 64))
                  ], 8, bv), [
                    [xe, _.encryption]
                  ])
                ]),
                _.encryption !== "none" && le[_.encryption] ? (p(), h("label", _v, [
                  v[24] || (v[24] = A("Пароль Wi-Fi", -1)),
                  Ee(vt, {
                    modelValue: _.key,
                    "onUpdate:modelValue": (K) => _.key = K,
                    autocomplete: "new-password",
                    minlength: "8",
                    maxlength: "64",
                    required: !_.has_key,
                    placeholder: _.has_key ? "Оставьте пустым, чтобы сохранить текущий" : ""
                  }, null, 8, ["modelValue", "onUpdate:modelValue", "required", "placeholder"])
                ])) : V("", !0),
                _.encryption === "none" ? (p(), h("p", kv, "Сеть будет открытой, сохранённый пароль будет удалён.")) : V("", !0),
                n("fieldset", $v, [
                  v[25] || (v[25] = n("legend", null, "Сетевые подключения", -1)),
                  (p(!0), h(N, null, se(s.value.networks, (K) => (p(), h("label", {
                    key: K,
                    class: "gw-check"
                  }, [
                    F(n("input", {
                      "onUpdate:modelValue": (Ve) => _.network = Ve,
                      type: "checkbox",
                      value: K
                    }, null, 8, Cv), [
                      [We, _.network]
                    ]),
                    A(" " + w(K), 1)
                  ]))), 128))
                ]),
                n("div", xv, [
                  n("label", Sv, [
                    F(n("input", {
                      "onUpdate:modelValue": (K) => _.hidden = K,
                      type: "checkbox"
                    }, null, 8, Vv), [
                      [We, _.hidden]
                    ]),
                    v[26] || (v[26] = A(" Скрыть SSID", -1))
                  ]),
                  n("label", Tv, [
                    F(n("input", {
                      "onUpdate:modelValue": (K) => _.isolate = K,
                      type: "checkbox"
                    }, null, 8, Ev), [
                      [We, _.isolate]
                    ]),
                    v[27] || (v[27] = A(" Изолировать клиентов", -1))
                  ])
                ])
              ])
            ]))), 128)),
            v[30] || (v[30] = n("p", { class: "gw-hint" }, "Применение временно отключит беспроводных клиентов. При потере доступа панель не подтвердит изменения, и роутер восстановит прежний Wi-Fi.", -1)),
            r.value ? (p(), h("p", Uv, w(r.value), 1)) : V("", !0),
            n("div", Pv, [
              n("button", {
                class: "gw-primary",
                disabled: a.value
              }, "Проверить изменения", 8, Av),
              n("button", {
                type: "button",
                disabled: a.value,
                onClick: he
              }, "Отмена", 8, Iv)
            ])
          ], 32)
        ]),
        _: 1
      }, 8, ["title", "busy"])) : V("", !0),
      g.value ? (p(), ge(qe, {
        key: 1,
        title: "Проверка изменений Wi-Fi",
        busy: a.value,
        onClose: ne
      }, {
        default: Re(() => [
          n("ul", Mv, [
            (p(!0), h(N, null, se(g.value.summary, (_, K) => (p(), h("li", { key: K }, w(_), 1))), 128))
          ]),
          n("p", Ov, "Откат при отсутствии подтверждения: " + w(g.value.rollback_seconds) + " секунд.", 1),
          r.value ? (p(), h("p", Rv, w(r.value), 1)) : V("", !0),
          n("div", Dv, [
            n("button", {
              class: "gw-primary",
              disabled: a.value,
              onClick: U
            }, "Да, применить", 8, Nv),
            n("button", {
              disabled: a.value,
              onClick: ne
            }, "Назад", 8, qv)
          ])
        ]),
        _: 1
      }, 8, ["busy"])) : V("", !0),
      y.value ? (p(), ge(qe, {
        key: 2,
        title: "Обзор каналов · " + y.value.name,
        wide: !0,
        busy: m.value,
        onClose: v[8] || (v[8] = (_) => y.value = null)
      }, {
        default: Re(() => [
          n("header", Hv, [
            n("p", Fv, w(m.value ? "Сканируем эфир…" : T.value ? "Последнее сканирование: " + new Date(T.value.scanned_at * 1e3).toLocaleTimeString("ru-RU") : E.value ? "Сканирование не выполнено" : "Ожидание запуска сканирования"), 1),
            n("button", {
              disabled: m.value,
              onClick: v[5] || (v[5] = (_) => d(y.value))
            }, w(m.value ? "Сканирование…" : "Сканировать снова"), 9, Lv)
          ]),
          v[32] || (v[32] = n("p", { class: "gw-hint" }, "Во время сканирования Wi-Fi может ненадолго замедлиться. Список показывает сети, видимые этому роутеру.", -1)),
          E.value ? (p(), h("p", jv, w(E.value), 1)) : V("", !0),
          T.value ? (p(), h(N, { key: 1 }, [
            n("nav", Wv, [
              n("button", {
                class: Ue({ on: B.value === "channels" }),
                onClick: v[6] || (v[6] = (_) => B.value = "channels")
              }, "Каналы", 2),
              n("button", {
                class: Ue({ on: B.value === "networks" }),
                onClick: v[7] || (v[7] = (_) => B.value = "networks")
              }, "Соседние сети (" + w(O.value.length) + ")", 3)
            ]),
            B.value === "channels" ? (p(), ge(Bp, {
              key: 0,
              data: { ...T.value, networks: O.value },
              radio: y.value
            }, null, 8, ["data", "radio"])) : (p(), h(N, { key: 1 }, [
              n("div", Bv, [
                n("table", null, [
                  v[31] || (v[31] = n("thead", null, [
                    n("tr", null, [
                      n("th", null, "Сеть"),
                      n("th", null, "Канал"),
                      n("th", null, "Частота"),
                      n("th", null, "Сигнал"),
                      n("th", null, "Защита")
                    ])
                  ], -1)),
                  n("tbody", null, [
                    (p(!0), h(N, null, se(O.value, (_) => (p(), h("tr", {
                      key: _.bssid + ":" + _.frequency
                    }, [
                      n("td", null, [
                        A(w(_.ssid || "Скрытая сеть"), 1),
                        n("small", null, w(_.bssid), 1)
                      ]),
                      n("td", null, w(_.channel), 1),
                      n("td", null, w(j(_.frequency)), 1),
                      n("td", null, w(_.signal == null ? "—" : _.signal + " dBm"), 1),
                      n("td", null, w(S(_)), 1)
                    ]))), 128))
                  ])
                ])
              ]),
              O.value.length ? V("", !0) : (p(), h("p", Kv, "Соседние сети не найдены."))
            ], 64))
          ], 64)) : V("", !0)
        ]),
        _: 1
      }, 8, ["title", "busy"])) : V("", !0)
    ], 64));
  }
}), zv = { class: "gw-section-header" }, Jv = { class: "gw-actions" }, Yv = ["disabled"], Xv = ["disabled"], Qv = {
  class: "gw-hint",
  "aria-live": "polite"
}, Zv = {
  key: 0,
  class: "gw-hint",
  role: "status"
}, eg = { class: "gw-service-list" }, tg = { class: "gw-service-info" }, lg = { key: 1 }, ng = ["title"], sg = ["title"], og = {
  key: 0,
  class: "gw-next-version"
}, ig = { class: "gw-service-state" }, ag = { class: "gw-service-actions" }, rg = ["disabled", "onClick"], ug = ["disabled", "onClick"], dg = ["disabled", "title", "onClick"], cg = ["disabled", "onClick"], fg = ["disabled", "onClick"], pg = ["disabled", "onClick"], vg = ["disabled", "onClick"], gg = {
  key: 0,
  class: "gw-hint"
}, hg = { class: "gw-version-field" }, mg = ["disabled"], bg = {
  key: 0,
  class: "gw-error",
  role: "alert"
}, yg = { class: "gw-actions" }, wg = ["disabled"], _g = ["disabled"], kg = /* @__PURE__ */ He({
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
    const l = e, o = t, s = /* @__PURE__ */ H({}), i = /* @__PURE__ */ H(!1), a = /* @__PURE__ */ H(""), r = /* @__PURE__ */ H(null), c = _e(() => l.node.monitor.services || []), g = { dnsmasq: "Локальный DNS и DHCP", firewall: "Защита роутера и правила трафика", podkop: "Выборочная маршрутизация через sing-box", ssclash: "Clash / Mihomo и правила маршрутизации", adguardhome: "Фильтрация DNS и блокировка рекламы" }, m = /* @__PURE__ */ H(null), y = /* @__PURE__ */ H(!1), T = /* @__PURE__ */ H("");
    function E(O) {
      const S = s.value[O.id]?.fingerprint;
      S && (T.value = "", m.value = { id: O.id, name: O.name, fingerprint: S, version: "" });
    }
    async function B() {
      const O = m.value, S = l.node.id;
      if (!(!O || y.value)) {
        y.value = !0, T.value = "";
        try {
          await l.bridge.request("/api/gateways/" + encodeURIComponent(S) + "/services/" + O.id + "/version", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ version: O.version, fingerprint: O.fingerprint, confirmed: !0 }) }), m.value = null, await te();
        } catch (k) {
          T.value = k instanceof Error ? k.message : String(k);
        } finally {
          y.value = !1;
        }
      }
    }
    let I = 0;
    qt(() => {
      I++;
    });
    function Q(O) {
      return l.updating?.[O] || (s.value[O]?.stage ? { stage: s.value[O].stage, task_id: s.value[O]?.task_id || void 0 } : void 0);
    }
    function X(O) {
      return Q(O)?.stage === "prepare" ? "Подготовка…" : Q(O)?.stage === "apply" ? "Обновление…" : Q(O)?.stage === "review" ? s.value[O]?.plan ? "Продолжить обновление" : "Ожидает подтверждения" : "Обновить до " + s.value[O]?.latest;
    }
    function Z(O) {
      return l.busy || i.value || !!a.value || !!Q(O) && !(Q(O)?.stage === "review" && s.value[O]?.plan);
    }
    function le(O) {
      const S = s.value[O]?.plan;
      Q(O)?.stage === "review" && S ? o("resume", S) : o("update", O);
    }
    function j(O) {
      if (["dnsmasq", "firewall"].includes(O)) return "";
      if (i.value) return "Проверяю обновления…";
      if (a.value) return "Не удалось проверить обновления";
      const S = s.value[O];
      return S?.available ? "Есть обновление до " + S.latest : S?.status === "current_cached" ? "Актуальная среди сохранённых версий" : S?.warning ? "Проверка не завершена" : S?.status === "newer" ? "Установленная версия новее доступного релиза" : S?.current && S.latest ? "Актуальная версия" : "Обновления не проверены";
    }
    async function te(O = !1) {
      const S = ++I;
      O || (i.value = !0), a.value = "";
      try {
        const k = await l.bridge.request("/api/gateways/" + encodeURIComponent(l.node.id) + "/service-updates");
        if (S === I) {
          s.value = k.services || {}, r.value = k.checked_at || Math.floor(Date.now() / 1e3);
          for (const [R, z] of Object.entries(s.value)) z.task_id && z.stage && o("pending", R, { stage: z.stage, task_id: z.task_id });
        }
      } catch (k) {
        S === I && (a.value = k instanceof Error ? k.message : String(k));
      } finally {
        S === I && (i.value = !1);
      }
    }
    return Xe(() => l.revision, () => {
      te(!0);
    }), Xe(() => l.node.id, () => {
      s.value = {}, r.value = null, m.value = null, te();
    }, { immediate: !0 }), (O, S) => (p(), h(N, null, [
      n("header", zv, [
        S[6] || (S[6] = n("div", null, [
          n("h3", null, "Сервисы из GitHub"),
          n("p", { class: "gw-hint" }, "Podkop, SSClash-Go и AdGuard Home · версии и резервные комплекты")
        ], -1)),
        n("div", Jv, [
          n("button", {
            disabled: e.busy || i.value,
            onClick: S[0] || (S[0] = (k) => te())
          }, w(i.value ? "Проверяю…" : "Проверить обновления"), 9, Yv),
          n("button", {
            class: "gw-primary",
            disabled: e.busy,
            onClick: S[1] || (S[1] = (k) => o("catalog"))
          }, "Установить сервис", 8, Xv)
        ])
      ]),
      n("p", Qv, w(i.value ? "Проверяю установленные версии и совместимые официальные релизы…" : a.value ? "Проверка не завершена." : r.value ? "Проверено в " + new Date(r.value * 1e3).toLocaleTimeString("ru-RU") : "Версии ещё не проверены."), 1),
      a.value ? (p(), h("p", Zv, w(a.value), 1)) : V("", !0),
      S[9] || (S[9] = n("div", {
        class: "gw-service-columns",
        "aria-hidden": "true"
      }, [
        n("span", null, "Сервис"),
        n("span", null, "Версия"),
        n("span", null, "Статус"),
        n("span", null, "Действия")
      ], -1)),
      n("div", eg, [
        (p(!0), h(N, null, se(c.value, (k) => (p(), h("article", {
          key: k.id,
          class: "gw-service-row"
        }, [
          n("div", tg, [
            n("h3", null, w(k.name), 1),
            ["podkop", "ssclash", "adguardhome"].includes(k.id) ? (p(), ge(ds, {
              key: 0,
              id: k.id,
              compact: "",
              help: k.id === "adguardhome",
              onHelp: S[2] || (S[2] = (R) => o("help"))
            }, null, 8, ["id", "help"])) : (p(), h("p", lg, w(g[k.id]), 1)),
            s.value[k.id]?.warning ? (p(), h("p", {
              key: 2,
              class: "gw-hint gw-version-warning",
              role: "status",
              title: s.value[k.id]?.warning || void 0
            }, w(s.value[k.id]?.warning), 9, ng)) : V("", !0)
          ]),
          n("div", {
            class: "gw-service-versions",
            title: (s.value[k.id]?.installed_version || s.value[k.id]?.current || k.version || "—") + (s.value[k.id]?.available ? " → " + s.value[k.id]?.latest : "")
          }, [
            n("span", null, w(s.value[k.id]?.installed_version || s.value[k.id]?.current || k.version || "—"), 1),
            s.value[k.id]?.available ? (p(), h("span", og, "→ " + w(s.value[k.id]?.latest), 1)) : V("", !0)
          ], 8, sg),
          n("div", ig, [
            n("span", {
              class: Ue(["gw-status", k.running ? "good" : "warn"])
            }, w(k.running ? "Работает" : "Остановлена"), 3),
            j(k.id) ? (p(), h("span", {
              key: 0,
              class: Ue(["gw-status", i.value || a.value || s.value[k.id]?.warning || s.value[k.id]?.available ? "warn" : "good"])
            }, w(j(k.id)), 3)) : V("", !0)
          ]),
          n("div", ag, [
            ["ssclash", "adguardhome"].includes(k.id) && !s.value[k.id]?.current && s.value[k.id]?.fingerprint ? (p(), h("button", {
              key: 0,
              disabled: e.busy || i.value || y.value,
              onClick: (R) => E(k)
            }, "Указать установленную версию", 8, rg)) : V("", !0),
            n("button", {
              disabled: e.busy,
              onClick: (R) => k.id === "adguardhome" ? o("openAdguard") : o("settings", k)
            }, w(k.id === "adguardhome" ? "Открыть AdGuard Home" : "Настроить" + (["podkop", "ssclash"].includes(k.id) ? " ↗" : "")), 9, ug),
            e.node.monitor.capabilities?.controls?.available ? (p(), h(N, { key: 1 }, [
              s.value[k.id]?.available || Q(k.id) ? (p(), h("button", {
                key: 0,
                class: "gw-update-button",
                disabled: Z(k.id),
                title: "Обновить до " + s.value[k.id]?.latest,
                onClick: (R) => le(k.id)
              }, w(X(k.id)), 9, dg)) : V("", !0),
              k.id === "ssclash" && k.managed ? (p(), h("button", {
                key: 1,
                disabled: e.busy || !!Q(k.id),
                onClick: (R) => o("webAccess", k.web_scope === "wan" ? "lan" : "wan")
              }, w(k.web_scope === "wan" ? "Только LAN" : "Доступ из WAN"), 9, cg)) : V("", !0),
              k.running || k.id === "firewall" ? (p(), h("button", {
                key: 2,
                disabled: e.busy || !!Q(k.id),
                onClick: (R) => k.id === "firewall" ? o("firewallRestart") : o("action", k.id, "restart")
              }, "Перезапустить", 8, fg)) : V("", !0),
              ["dnsmasq", "firewall"].includes(k.id) ? V("", !0) : (p(), h("button", {
                key: 3,
                disabled: e.busy || !!Q(k.id),
                onClick: (R) => o("action", k.id, k.running ? "stop" : "start")
              }, w(k.running ? "Остановить" : "Запустить"), 9, pg)),
              ["podkop", "ssclash"].includes(k.id) || k.id === "adguardhome" && k.managed ? (p(), h("button", {
                key: 4,
                class: "gw-danger",
                disabled: e.busy || !!Q(k.id),
                onClick: (R) => o("action", k.id, "remove")
              }, "Удалить", 8, vg)) : V("", !0)
            ], 64)) : V("", !0)
          ])
        ]))), 128)),
        c.value.length ? V("", !0) : (p(), h("p", gg, "Установленные сервисы пока не определены."))
      ]),
      m.value ? (p(), ge(qe, {
        key: 1,
        title: "Установленная версия · " + m.value.name,
        onClose: S[5] || (S[5] = (k) => !y.value && (m.value = null))
      }, {
        default: Re(() => [
          S[8] || (S[8] = n("p", { class: "gw-hint" }, "Укажите версию, которая сейчас показана в интерфейсе сервиса. Сохраняется только запись о версии; сервис и настройки не меняются.", -1)),
          n("label", hg, [
            S[7] || (S[7] = A("Установленная версия", -1)),
            F(n("input", {
              "onUpdate:modelValue": S[3] || (S[3] = (k) => m.value.version = k),
              placeholder: "Например, 7.7.4",
              inputmode: "decimal",
              disabled: y.value
            }, null, 8, mg), [
              [
                re,
                m.value.version,
                void 0,
                { trim: !0 }
              ]
            ])
          ]),
          T.value ? (p(), h("p", bg, w(T.value), 1)) : V("", !0),
          n("div", yg, [
            n("button", {
              class: "gw-primary",
              disabled: y.value || !/^v?[0-9]+[.][0-9]+[.][0-9]+$/.test(m.value.version),
              onClick: B
            }, w(y.value ? "Сохраняю…" : "Подтвердить версию"), 9, wg),
            n("button", {
              disabled: y.value,
              onClick: S[4] || (S[4] = (k) => m.value = null)
            }, "Отмена", 8, _g)
          ])
        ]),
        _: 1
      }, 8, ["title"])) : V("", !0)
    ], 64));
  }
}), $g = { class: "gw-header" }, Cg = { class: "gw-eyebrow" }, xg = { class: "gw-title-with-icon" }, Sg = { class: "gw-actions" }, Vg = ["disabled"], Tg = ["href"], Eg = /* @__PURE__ */ He({
  __name: "GatewayHeader",
  props: {
    node: {},
    busy: { type: Boolean }
  },
  emits: ["console"],
  setup(e, { emit: t }) {
    const l = t;
    return (o, s) => (p(), h("header", $g, [
      n("div", null, [
        n("span", Cg, "OPENWRT " + w(e.node.monitor.board?.release?.version), 1),
        n("h2", xg, [
          s[1] || (s[1] = n("span", {
            class: "gw-router-icon",
            "aria-hidden": "true"
          }, [
            n("svg", {
              viewBox: "0 0 24 24",
              width: "20",
              height: "20"
            }, [
              n("rect", {
                x: "3",
                y: "11",
                width: "18",
                height: "9",
                rx: "2"
              }),
              n("path", { d: "M7 11V5m10 6V5M5 6a10 10 0 0 1 14 0M8 8a6 6 0 0 1 8 0M7 16h.01M11 16h.01" })
            ])
          ], -1)),
          A(w(e.node.name), 1)
        ]),
        n("p", null, w(e.node.monitor.board?.model || e.node.host) + " · " + w(e.node.host), 1)
      ]),
      n("div", Sg, [
        n("button", {
          "aria-label": "Открыть консоль шлюза",
          disabled: e.busy,
          onClick: s[0] || (s[0] = (i) => l("console"))
        }, "Консоль", 8, Vg),
        n("a", {
          href: e.node.luci_url,
          target: "_blank",
          rel: "noopener noreferrer"
        }, "LuCI ↗", 8, Tg)
      ])
    ]));
  }
}), Ug = { class: "gw-backups" }, Pg = { class: "gw-section-header" }, Ag = ["disabled"], Ig = {
  key: 0,
  class: "gw-notice"
}, Mg = {
  key: 1,
  class: "gw-error",
  role: "alert"
}, Og = {
  key: 2,
  class: "gw-notice"
}, Rg = { class: "gw-backup-restore" }, Dg = { class: "gw-section-header" }, Ng = { class: "gw-backup-upload" }, qg = ["disabled"], Hg = ["disabled"], Fg = { class: "gw-backup-picker" }, Lg = ["disabled"], jg = {
  key: 0,
  value: ""
}, Wg = ["value"], Bg = ["disabled"], Kg = {
  key: 3,
  class: "gw-notice gw-backup-reboot"
}, Gg = { class: "gw-actions" }, zg = ["disabled"], Jg = ["href"], Yg = ["href"], Xg = {
  key: 0,
  class: "gw-error",
  role: "alert"
}, Qg = { key: 1 }, Zg = { class: "gw-change-list" }, eh = { class: "gw-actions" }, th = ["disabled"], lh = ["disabled"], nh = /* @__PURE__ */ He({
  __name: "GatewayBackups",
  props: {
    node: {},
    bridge: {}
  },
  setup(e) {
    const t = e, l = /* @__PURE__ */ H([]), o = /* @__PURE__ */ H(""), s = /* @__PURE__ */ H(!1), i = /* @__PURE__ */ H(!1), a = /* @__PURE__ */ H(""), r = /* @__PURE__ */ H(null), c = /* @__PURE__ */ H(null), g = /* @__PURE__ */ H(!1), m = /* @__PURE__ */ H(null);
    let y = !0, T;
    const E = "/api/gateways/" + encodeURIComponent(t.node.id) + "/backups", B = (k, R) => t.bridge.request(k, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(R) }), I = (k) => k < 1024 * 1024 ? Math.round(k / 1024) + " КБ" : (k / 1024 / 1024).toFixed(1) + " МБ";
    function Q() {
      m.value?.click();
    }
    async function X() {
      try {
        const k = await t.bridge.request(E);
        if (!y) return;
        l.value = k.items, i.value = k.available, r.value = k.task?.id || null, g.value = k.reboot_required === !0, l.value.some((R) => R.id === o.value) || (o.value = l.value[0]?.id || ""), r.value && (T = setTimeout(X, 2e3));
      } catch (k) {
        y && (a.value = k instanceof Error ? k.message : String(k));
      }
    }
    function Z(k, R, z) {
      r.value = k, t.bridge.task({ taskId: k, title: R, cancellable: !1, onDone: async () => {
        if (y) {
          try {
            const pe = await t.bridge.request("/api/tasks/" + encodeURIComponent(k));
            pe.result?.success === !1 && (a.value = pe.result.error || "Операция завершилась с ошибкой");
          } catch (pe) {
            a.value = pe instanceof Error ? pe.message : String(pe);
          }
          clearTimeout(T), await X();
        }
      } }), clearTimeout(T), T = setTimeout(X, 2e3);
    }
    async function le() {
      s.value = !0, a.value = "";
      try {
        const k = await B(E + "/create", {});
        y && Z(k.task_id, "Резервная копия настроек OpenWrt", "create");
      } catch (k) {
        a.value = k instanceof Error ? k.message : String(k);
      } finally {
        s.value = !1;
      }
    }
    async function j(k) {
      const R = k.target, z = R.files?.[0];
      if (z) {
        s.value = !0, a.value = "";
        try {
          const pe = new FormData();
          pe.append("file", z);
          const he = await t.bridge.request(E + "/upload", { method: "POST", body: pe });
          if (!y) return;
          await X(), o.value = he.archive.id;
        } catch (pe) {
          a.value = pe instanceof Error ? pe.message : String(pe);
        } finally {
          R.value = "", s.value = !1;
        }
      }
    }
    async function te(k) {
      s.value = !0, a.value = "";
      try {
        const R = await B(E + "/plan", { action: k, archive_id: k === "restore" ? o.value : null });
        y ? c.value = R : t.bridge.request(E + "/plans/" + encodeURIComponent(R.plan_token), { method: "DELETE" }).catch(() => {
        });
      } catch (R) {
        a.value = R instanceof Error ? R.message : String(R);
      } finally {
        s.value = !1;
      }
    }
    async function O() {
      if (c.value) {
        s.value = !0;
        try {
          await t.bridge.request(E + "/plans/" + encodeURIComponent(c.value.plan_token), { method: "DELETE" }), c.value = null;
        } catch (k) {
          a.value = k instanceof Error ? k.message : String(k);
        } finally {
          s.value = !1;
        }
      }
    }
    async function S() {
      if (!c.value) return;
      s.value = !0, a.value = "";
      const k = c.value;
      try {
        const R = await B(E + "/apply", { plan_token: k.plan_token, confirmed: !0 });
        y && (c.value = null, Z(R.task_id, k.action === "restore" ? "Восстановление настроек OpenWrt" : "Перезагрузка шлюза", k.action));
      } catch (R) {
        a.value = R instanceof Error ? R.message : String(R);
      } finally {
        s.value = !1;
      }
    }
    return ct(X), Oo(() => {
      y = !1, clearTimeout(T), c.value && t.bridge.request(E + "/plans/" + encodeURIComponent(c.value.plan_token), { method: "DELETE" }).catch(() => {
      });
    }), (k, R) => (p(), h(N, null, [
      n("section", Ug, [
        n("header", Pg, [
          R[4] || (R[4] = n("div", null, [
            n("h3", null, "Резервные копии"),
            n("p", { class: "gw-hint" }, "Штатный архив настроек OpenWrt. Прошивка и пакеты в копию не входят.")
          ], -1)),
          n("button", {
            class: "gw-primary",
            disabled: s.value || !!r.value || !i.value,
            onClick: le
          }, "Создать копию на панели", 8, Ag)
        ]),
        i.value ? V("", !0) : (p(), h("p", Ig, "Для создания и восстановления нужен управляемый API Bot4VPS. Настройте его во вкладке «Доступ».")),
        a.value && !c.value ? (p(), h("p", Mg, w(a.value), 1)) : V("", !0),
        r.value ? (p(), h("p", Og, [
          R[5] || (R[5] = A("Выполняется операция шлюза. ", -1)),
          n("button", {
            onClick: R[0] || (R[0] = (z) => Z(r.value, "Операция резервного копирования"))
          }, "Показать задачу")
        ])) : V("", !0),
        n("div", Rg, [
          n("header", Dg, [
            R[6] || (R[6] = n("div", null, [
              n("h3", null, "Восстановление"),
              n("p", { class: "gw-hint" }, "Выберите любую копию на панели или загрузите свой архив из LuCI.")
            ], -1)),
            n("div", Ng, [
              n("button", {
                disabled: s.value || !!r.value,
                onClick: Q
              }, "Загрузить свой архив", 8, qg),
              n("input", {
                ref_key: "uploadInput",
                ref: m,
                type: "file",
                accept: ".tar.gz,.tgz",
                hidden: "",
                disabled: s.value || !!r.value,
                onChange: j
              }, null, 40, Hg)
            ])
          ]),
          n("div", Fg, [
            n("label", null, [
              R[7] || (R[7] = A("Архив на панели", -1)),
              F(n("select", {
                "onUpdate:modelValue": R[1] || (R[1] = (z) => o.value = z),
                disabled: s.value || !!r.value
              }, [
                l.value.length ? V("", !0) : (p(), h("option", jg, "Сохранённых копий пока нет")),
                (p(!0), h(N, null, se(l.value, (z) => (p(), h("option", {
                  key: z.id,
                  value: z.id
                }, w(z.filename) + " · " + w(I(z.size)), 9, Wg))), 128))
              ], 8, Lg), [
                [xe, o.value]
              ])
            ]),
            n("button", {
              disabled: s.value || !!r.value || !o.value || !i.value,
              onClick: R[2] || (R[2] = (z) => te("restore"))
            }, "Восстановить", 8, Bg)
          ]),
          R[8] || (R[8] = n("p", { class: "gw-hint" }, "Копии общие для всех шлюзов. Архив содержит настройки и может содержать пароли и ключи. Скачать или удалить копии можно в «Файлы → Копии шлюзов».", -1))
        ]),
        g.value ? (p(), h("div", Kg, [
          R[9] || (R[9] = n("p", null, "Файлы настроек восстановлены. Для применения требуется перезагрузка.", -1)),
          n("div", Gg, [
            n("button", {
              disabled: s.value || !!r.value,
              onClick: R[3] || (R[3] = (z) => te("reboot"))
            }, "Перезагрузить и применить", 8, zg),
            n("a", {
              href: e.node.luci_url,
              target: "_blank",
              rel: "noopener noreferrer"
            }, "Открыть LuCI ↗", 8, Jg)
          ])
        ])) : (p(), h("a", {
          key: 4,
          class: "gw-hint",
          href: e.node.luci_url,
          target: "_blank",
          rel: "noopener noreferrer"
        }, "Открыть LuCI ↗", 8, Yg))
      ]),
      c.value ? (p(), ge(qe, {
        key: 0,
        title: c.value.action === "restore" ? "План восстановления" : "Подтверждение перезагрузки",
        busy: s.value,
        onClose: O
      }, {
        default: Re(() => [
          a.value ? (p(), h("p", Xg, w(a.value), 1)) : V("", !0),
          c.value.action === "restore" ? (p(), h("p", Qg, [
            n("strong", null, w(c.value.filename), 1),
            A(" · " + w(c.value.files) + " файлов", 1)
          ])) : V("", !0),
          n("ul", Zg, [
            (p(!0), h(N, null, se(c.value.warnings, (z) => (p(), h("li", { key: z }, w(z), 1))), 128))
          ]),
          n("div", eh, [
            n("button", {
              class: "gw-primary",
              disabled: s.value,
              onClick: S
            }, w(c.value.action === "restore" ? "Да, восстановить настройки" : "Да, перезагрузить шлюз"), 9, th),
            n("button", {
              disabled: s.value,
              onClick: O
            }, "Отмена", 8, lh)
          ])
        ]),
        _: 1
      }, 8, ["title", "busy"])) : V("", !0)
    ], 64));
  }
}), sh = {
  key: 0,
  class: "gw-error",
  role: "alert"
}, oh = { key: 1 }, ih = { key: 0 }, ah = {
  key: 4,
  class: "gw-notice"
}, rh = { key: 5 }, uh = { key: 6 }, dh = { class: "gw-actions" }, ch = ["disabled"], fh = ["disabled"], ph = /* @__PURE__ */ He({
  __name: "OperationPlan",
  props: {
    operation: {},
    busy: { type: Boolean },
    error: {}
  },
  emits: ["apply", "cancel"],
  setup(e, { emit: t }) {
    const l = t, o = { install: "Установка", update: "Обновление", web_access: "Доступ веб-панели", remove: "Удаление", start: "Запуск", stop: "Остановка", restart: "Перезапуск" };
    return (s, i) => (p(), ge(qe, {
      title: "План операции",
      busy: e.busy,
      onClose: i[2] || (i[2] = (a) => l("cancel"))
    }, {
      default: Re(() => [
        e.error ? (p(), h("p", sh, w(e.error), 1)) : V("", !0),
        n("h2", null, w(o[e.operation.action]) + " " + w(e.operation.service) + " " + w(e.operation.version || ""), 1),
        e.operation.network_check ? (p(), h("p", oh, "После действия панель проверит API и состояние службы. Если подтверждение не придёт, будет выполнено восстановление.")) : V("", !0),
        e.operation.action === "remove" ? (p(), h(N, { key: 2 }, [
          i[3] || (i[3] = n("h3", null, "Будет удалено", -1)),
          n("ul", null, [
            (p(!0), h(N, null, se(e.operation.removed, (a) => (p(), h("li", { key: a }, w(a), 1))), 128))
          ])
        ], 64)) : V("", !0),
        ["install", "update"].includes(e.operation.action) ? (p(), h(N, { key: 3 }, [
          i[4] || (i[4] = n("p", null, "Файлы передаются с панели. GitHub на роутере не используется.", -1)),
          e.operation.action === "update" ? (p(), h("p", ih, "Конфигурация и автозапуск сохраняются. Работающая служба будет остановлена на время обновления и запущена снова. Подготовлен резерв исходной версии для отката.")) : V("", !0),
          n("ul", null, [
            (p(!0), h(N, null, se(e.operation.changes, (a) => (p(), h("li", {
              key: a.package
            }, w(a.package) + ": " + w(a.before || "не установлен") + " → " + w(a.after), 1))), 128))
          ])
        ], 64)) : V("", !0),
        e.operation.warnings?.length ? (p(), h("section", ah, [
          i[5] || (i[5] = n("h3", null, "Последствия изменений", -1)),
          n("ul", null, [
            (p(!0), h(N, null, se(e.operation.warnings, (a) => (p(), h("li", { key: a }, w(a), 1))), 128))
          ])
        ])) : V("", !0),
        e.operation.preserved.length ? (p(), h("p", rh, "Сохранятся: " + w(e.operation.preserved.join(", ")) + ".", 1)) : V("", !0),
        e.operation.keep_backup ? (p(), h("p", uh, "Конфигурация сохраняется в резервную копию; путь будет в журнале.")) : V("", !0),
        n("div", dh, [
          n("button", {
            class: "gw-primary",
            disabled: e.busy,
            onClick: i[0] || (i[0] = (a) => l("apply"))
          }, "Да, выполнить показанный план", 8, ch),
          n("button", {
            disabled: e.busy,
            onClick: i[1] || (i[1] = (a) => l("cancel"))
          }, "Отмена", 8, fh)
        ])
      ]),
      _: 1
    }, 8, ["busy"]));
  }
}), vh = {
  key: 0,
  class: "gw-error",
  role: "alert"
}, gh = { class: "gw-actions" }, hh = ["disabled"], mh = ["disabled"], bh = /* @__PURE__ */ He({
  __name: "IntegrationUpdate",
  props: {
    plan: {},
    busy: { type: Boolean },
    error: {}
  },
  emits: ["apply", "cancel"],
  setup(e, { emit: t }) {
    const l = t;
    return (o, s) => (p(), ge(qe, {
      title: "Обновление интеграции · " + e.plan.name,
      compact: !0,
      busy: e.busy,
      onClose: s[2] || (s[2] = (i) => l("cancel"))
    }, {
      default: Re(() => [
        e.error ? (p(), h("p", vh, w(e.error), 1)) : V("", !0),
        (p(!0), h(N, null, se(e.plan.warnings, (i) => (p(), h("p", {
          key: i,
          class: "gw-notice"
        }, w(i), 1))), 128)),
        n("details", null, [
          n("summary", null, "Компоненты для обновления (" + w(e.plan.files.length) + ")", 1),
          n("ul", null, [
            (p(!0), h(N, null, se(e.plan.files, (i) => (p(), h("li", { key: i }, w(i), 1))), 128))
          ])
        ]),
        n("div", gh, [
          n("button", {
            class: "gw-primary",
            disabled: e.busy,
            onClick: s[0] || (s[0] = (i) => l("apply"))
          }, "Да, обновить интеграцию", 8, hh),
          n("button", {
            disabled: e.busy,
            onClick: s[1] || (s[1] = (i) => l("cancel"))
          }, "Отмена", 8, mh)
        ])
      ]),
      _: 1
    }, 8, ["title", "busy"]));
  }
}), yh = { class: "gw-pin-detail" }, wh = { class: "gw-actions" }, _h = ["disabled"], kh = ["disabled"], $h = /* @__PURE__ */ He({
  __name: "TlsTrust",
  props: {
    change: {},
    busy: { type: Boolean }
  },
  emits: ["apply", "cancel"],
  setup(e, { emit: t }) {
    const l = t;
    return (o, s) => (p(), ge(qe, {
      title: "Изменение доверия HTTPS",
      busy: e.busy,
      onClose: s[2] || (s[2] = (i) => l("cancel"))
    }, {
      default: Re(() => [
        n("div", yh, [
          s[5] || (s[5] = n("p", null, "Изменяется сохранённый отпечаток сертификата API.", -1)),
          n("p", null, [
            s[3] || (s[3] = A("Прежний: ", -1)),
            n("code", null, w(e.change.previous), 1)
          ]),
          n("p", null, [
            s[4] || (s[4] = A("Новый: ", -1)),
            n("code", null, w(e.change.next || "Проверка стандартной цепочки сертификатов"), 1)
          ]),
          s[6] || (s[6] = n("p", null, "Подтвердите изменение после проверки сертификата роутера.", -1))
        ]),
        n("div", wh, [
          n("button", {
            class: "gw-primary",
            disabled: e.busy,
            onClick: s[0] || (s[0] = (i) => l("apply"))
          }, "Да, принять изменение", 8, _h),
          n("button", {
            disabled: e.busy,
            onClick: s[1] || (s[1] = (i) => l("cancel"))
          }, "Отмена", 8, kh)
        ])
      ]),
      _: 1
    }, 8, ["busy"]));
  }
}), Ch = {
  key: 0,
  class: "gw-error",
  role: "alert"
}, xh = {
  key: 1,
  class: "gw-hint"
}, Sh = { class: "gw-change-list" }, Vh = {
  key: 0,
  class: "gw-notice"
}, Th = { class: "gw-notice" }, Eh = { class: "gw-actions" }, Uh = ["disabled"], Ph = ["disabled"], Ah = ["disabled"], Ih = /* @__PURE__ */ He({
  __name: "FirewallRestart",
  props: {
    node: {},
    bridge: {}
  },
  emits: ["close", "changed"],
  setup(e, { emit: t }) {
    const l = e, o = t, s = /* @__PURE__ */ H(!1), i = /* @__PURE__ */ H(""), a = /* @__PURE__ */ H(null), r = "/api/gateways/" + encodeURIComponent(l.node.id), c = (T, E, B = "POST") => l.bridge.request(r + T, {
      method: B,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(E)
    });
    async function g() {
      s.value = !0, i.value = "";
      try {
        const T = await l.bridge.request(r + "/network");
        if (!T.settings_hash) throw new Error("Не удалось прочитать актуальные настройки firewall");
        a.value = await c("/network/plan", { action: "firewall_restart", data: { config_hash: T.settings_hash } });
      } catch (T) {
        i.value = T.message;
      } finally {
        s.value = !1;
      }
    }
    async function m() {
      if (!(s.value || !a.value)) {
        s.value = !0, i.value = "";
        try {
          const T = a.value, E = await c("/router-operations", { plan_token: T.plan_token, confirmed: !0 });
          a.value = null, o("close"), l.bridge.task({ taskId: E.task_id, title: T.title, cancellable: !1, onDone: async () => o("changed") });
        } catch (T) {
          i.value = T.message;
        } finally {
          s.value = !1;
        }
      }
    }
    async function y() {
      if (!s.value) {
        s.value = !0, i.value = "";
        try {
          a.value && await c("/operation-plans/" + encodeURIComponent(a.value.plan_token), {}, "DELETE"), a.value = null, o("close");
        } catch (T) {
          i.value = T.message;
        } finally {
          s.value = !1;
        }
      }
    }
    return ct(() => {
      g();
    }), (T, E) => (p(), ge(qe, {
      title: "Перезапуск firewall",
      busy: s.value,
      onClose: y
    }, {
      default: Re(() => [
        i.value ? (p(), h("p", Ch, w(i.value), 1)) : V("", !0),
        s.value && !a.value ? (p(), h("p", xh, "Получаем план перезапуска…")) : V("", !0),
        a.value ? (p(), h(N, { key: 2 }, [
          n("ul", Sh, [
            (p(!0), h(N, null, se(a.value.summary, (B, I) => (p(), h("li", { key: I }, w(B), 1))), 128))
          ]),
          a.value.warnings?.length ? (p(), h("ul", Vh, [
            (p(!0), h(N, null, se(a.value.warnings, (B, I) => (p(), h("li", { key: I }, w(B), 1))), 128))
          ])) : V("", !0),
          n("p", Th, "Панель проверит связь. Если подтверждение не придёт в течение " + w(a.value.rollback_seconds) + " секунд, роутер восстановит прежнюю конфигурацию.", 1)
        ], 64)) : V("", !0),
        n("div", Eh, [
          a.value ? (p(), h("button", {
            key: 0,
            class: "gw-primary",
            disabled: s.value,
            onClick: m
          }, "Перезапустить", 8, Uh)) : i.value ? (p(), h("button", {
            key: 1,
            disabled: s.value,
            onClick: g
          }, "Повторить", 8, Ph)) : V("", !0),
          n("button", {
            disabled: s.value,
            onClick: y
          }, "Отмена", 8, Ah)
        ])
      ]),
      _: 1
    }, 8, ["busy"]));
  }
}), Mh = {
  key: 0,
  class: "gw-error",
  role: "alert"
}, Oh = { key: 0 }, Rh = {
  key: 1,
  class: "gw-error",
  role: "alert"
}, Dh = { class: "gw-actions" }, Nh = ["disabled"], qh = { class: "gw-tabs" }, Hh = { class: "gw-two" }, Fh = { class: "gw-actions" }, Lh = ["disabled"], jh = ["disabled"], Wh = { class: "gw-detected" }, Bh = { key: 0 }, Kh = {
  key: 0,
  class: "gw-root-warning"
}, Gh = { class: "gw-panel" }, zh = { key: 0 }, Jh = { key: 1 }, Yh = { class: "gw-actions" }, Xh = ["disabled"], Qh = ["disabled"], Zh = ["disabled"], em = {
  key: 1,
  class: "gw-panel"
}, tm = { key: 0 }, lm = { class: "gw-header" }, nm = {
  key: 0,
  class: "gw-empty"
}, sm = {
  key: 2,
  class: "server-table-wrap gw-server-table-wrap"
}, om = { class: "server-table gw-server-table" }, im = ["onClick", "onKeydown"], am = { class: "server-name-cell" }, rm = { class: "gw-server-identity" }, um = ["title"], dm = { class: "server-host-cell" }, cm = { class: "gw-server-sensors" }, fm = { class: "gw-card-stats" }, pm = { class: "gw-server-traffic" }, vm = {
  key: 1,
  class: "gw-detail"
}, gm = ["disabled"], hm = {
  key: 0,
  class: "gw-error"
}, mm = {
  key: 1,
  class: "gw-hint"
}, bm = {
  key: 2,
  class: "gw-root-warning",
  role: "status"
}, ym = { class: "gw-tabs" }, wm = ["onClick"], _m = { class: "gw-metrics" }, km = { class: "gw-panel" }, $m = { class: "gw-panel" }, Cm = { class: "gw-panel" }, xm = { class: "gw-panel" }, Sm = { class: "gw-panel" }, Vm = { key: 0 }, Tm = { class: "gw-clients-section" }, Em = { class: "gw-section-header" }, Um = { class: "gw-table-wrap" }, Pm = {
  key: 0,
  class: "gw-hint"
}, Am = {
  key: 1,
  class: "gw-pagination"
}, Im = { class: "gw-hint" }, Mm = { class: "gw-actions" }, Om = ["disabled"], Rm = { "aria-live": "polite" }, Dm = ["disabled"], Nm = {
  key: 0,
  class: "gw-hint",
  role: "status"
}, qm = {
  key: 1,
  class: "gw-error",
  role: "alert"
}, Hm = { class: "gw-catalog-list" }, Fm = { class: "gw-catalog-summary" }, Lm = {
  key: 0,
  class: "gw-status good"
}, jm = { class: "gw-catalog-body" }, Wm = { class: "gw-catalog-controls" }, Bm = { class: "gw-field" }, Km = ["onUpdate:modelValue", "disabled"], Gm = {
  key: 0,
  value: ""
}, zm = { class: "gw-actions" }, Jm = ["disabled", "onClick"], Ym = ["disabled", "onClick"], Xm = { class: "gw-hint" }, Qm = {
  key: 0,
  class: "gw-hint"
}, Zm = {
  key: 1,
  class: "gw-hint"
}, e1 = { class: "gw-reserve-settings" }, t1 = { class: "gw-check" }, l1 = { class: "gw-actions" }, n1 = ["disabled"], s1 = {
  key: 0,
  class: "gw-hint",
  role: "status"
}, o1 = {
  key: 13,
  class: "gw-panel"
}, i1 = { class: "gw-actions" }, a1 = ["disabled"], r1 = { class: "gw-log" }, u1 = {
  key: 14,
  class: "gw-access"
}, d1 = {
  key: 0,
  class: "gw-section-header gw-access-tools"
}, c1 = {
  key: 0,
  class: "gw-hint"
}, f1 = { class: "gw-actions" }, p1 = ["disabled"], v1 = ["disabled"], g1 = ["disabled"], h1 = { class: "gw-section-header" }, m1 = ["disabled"], b1 = {
  key: 2,
  class: "gw-hint"
}, y1 = {
  key: 3,
  class: "gw-hint",
  role: "status"
}, w1 = { class: "gw-access-columns" }, _1 = { class: "gw-hint" }, k1 = ["href"], $1 = { class: "gw-actions" }, C1 = ["disabled"], x1 = { class: "gw-two" }, S1 = ["disabled"], V1 = { key: 0 }, T1 = { key: 1 }, E1 = { class: "gw-actions" }, U1 = ["disabled"], P1 = {
  key: 0,
  style: { "margin-top": "24px" }
}, A1 = {
  key: 0,
  class: "gw-hint"
}, I1 = {
  key: 0,
  class: "gw-hint"
}, M1 = { class: "gw-actions" }, O1 = ["disabled"], R1 = ["disabled"], Pn = "bot4vps_gateway_location", D1 = /* @__PURE__ */ He({
  __name: "Gateways",
  props: {
    bridge: {},
    wizard: { type: Boolean },
    initialPlan: {}
  },
  setup(e) {
    const t = /* @__PURE__ */ H(!1), l = /* @__PURE__ */ H(null), o = /* @__PURE__ */ H(null), s = e;
    function i() {
      if (s.wizard || !s.initialPlan?.restore_location || s.initialPlan?.return_node_id) return null;
      try {
        const x = JSON.parse(sessionStorage.getItem(Pn) || "null");
        return x && typeof x.nodeId == "string" && ["overview", "network", "wifi", "services", "packages", "backups", "logs", "access"].includes(x.tab) ? x : null;
      } catch {
        return null;
      }
    }
    const a = i(), r = /* @__PURE__ */ H([]), c = /* @__PURE__ */ H(s.wizard ? null : s.initialPlan?.return_node_id || a?.nodeId || null), g = /* @__PURE__ */ H(!1), m = /* @__PURE__ */ H(""), y = /* @__PURE__ */ H(s.wizard), T = /* @__PURE__ */ H("ssh"), E = /* @__PURE__ */ H(s.initialPlan), B = /* @__PURE__ */ H(!1), I = /* @__PURE__ */ H(a?.tab || "overview"), Q = /* @__PURE__ */ H(""), X = /* @__PURE__ */ H("");
    Xe([c, I], ([x, f]) => {
      if (!s.wizard)
        try {
          x ? sessionStorage.setItem(Pn, JSON.stringify({ nodeId: x, tab: f })) : sessionStorage.removeItem(Pn);
        } catch {
        }
    }, { immediate: !0 });
    const Z = /* @__PURE__ */ H(""), le = /* @__PURE__ */ H(0), j = /* @__PURE__ */ H(null), te = /* @__PURE__ */ H(null), O = /* @__PURE__ */ H(!1), S = /* @__PURE__ */ H(!1), k = /* @__PURE__ */ H(3), R = /* @__PURE__ */ H(null), z = /* @__PURE__ */ H({}), pe = /* @__PURE__ */ new Set(), he = (x, f) => x + ":" + f;
    function Pe(x) {
      const f = /* @__PURE__ */ new Set();
      let $ = !1;
      for (const ue of x) for (const me of ue.service_update_tasks || [])
        f.add(me.task_id), z.value[he(ue.id, me.service)] = { stage: me.stage, task_id: me.task_id };
      for (const [ue, me] of Object.entries(z.value)) me.stage !== "review" && me.task_id && !f.has(me.task_id) && (delete z.value[ue], ue.startsWith((W.value?.id || "") + ":") && ($ = !0));
      $ && I.value === "services" && le.value++;
    }
    const Me = _e(() => Object.fromEntries(Object.entries(z.value).filter(([x]) => x.startsWith((W.value?.id || "") + ":")).map(([x, f]) => [x.split(":").at(-1), f]))), ne = /* @__PURE__ */ H(!1), U = /* @__PURE__ */ H([]), d = /* @__PURE__ */ H({ podkop: [], ssclash: [], adguardhome: [] }), u = /* @__PURE__ */ H({ podkop: "", ssclash: "", adguardhome: "" }), v = /* @__PURE__ */ H({ name: "", host: "", port: 22, user: "root", password: "", url: "", username: "", tls_sha256: "" });
    Xe(T, () => {
      v.value.password = "";
    });
    const _ = /* @__PURE__ */ H({ user: "root", port: 22, auth_type: "password", password: "", key_path: "" }), K = /* @__PURE__ */ H(null), Ve = /* @__PURE__ */ H(null), W = _e(() => r.value.find((x) => x.id === c.value)), Ne = /* @__PURE__ */ H({ current_password: "", password: "", confirmation: "" }), Ht = /* @__PURE__ */ H(!1), st = /* @__PURE__ */ H(""), ot = /* @__PURE__ */ H(), Gt = _e(() => ot.value && ot.value.id === W.value?.id ? ot.value.configured : W.value?.root_password_configured);
    let yt = 0;
    async function hn() {
      const x = W.value;
      if (!x || x.ssh_user !== "root" || !x.ssh_configured) return;
      const f = ++yt;
      try {
        const $ = await s.bridge.request("/api/gateways/" + x.id + "/root-password");
        ie && W.value?.id === x.id && f === yt && (ot.value = { id: x.id, configured: $.configured });
      } catch {
      }
    }
    Xe(() => W.value?.id, () => {
      ot.value = void 0, Ht.value = !1, Ne.value = { current_password: "", password: "", confirmation: "" }, hn();
    });
    const b = _e(() => W.value?.monitor || {}), C = _e(() => Object.values(b.value.wireguard || {})), P = /* @__PURE__ */ H(""), L = /* @__PURE__ */ H(""), M = /* @__PURE__ */ H(1), D = 20, G = _e(() => (b.value.clients || []).filter((x) => [x.hostname, x.ipaddr, x.macaddr].join(" ").toLowerCase().includes(L.value.toLowerCase()))), J = _e(() => Math.max(1, Math.ceil(G.value.length / D))), Y = _e(() => G.value.slice((M.value - 1) * D, M.value * D));
    Xe(L, () => {
      M.value = 1;
    }), Xe(J, (x) => {
      M.value = Math.min(M.value, x);
    }), Xe(c, () => {
      L.value = "", M.value = 1;
    });
    function q(x) {
      x.id === "firewall" ? l.value = "firewall" : x.id === "dnsmasq" ? l.value = "dns" : x.id === "adguardhome" ? t.value = !0 : Oe(x);
    }
    const oe = _e(() => r.value.filter((x) => (x.name + " " + x.host + " " + (x.monitor.board?.model || "")).toLowerCase().includes(P.value.toLowerCase()))), ee = [{ id: "overview", name: "Обзор" }, { id: "network", name: "Сеть" }, { id: "wifi", name: "Wi-Fi" }, { id: "services", name: "Службы" }, { id: "packages", name: "Пакеты" }, { id: "backups", name: "Резервные копии" }, { id: "logs", name: "Журнал" }, { id: "access", name: "Доступ" }];
    let ae, ie = !0;
    const de = (x, f, $ = "POST") => s.bridge.request(x, { method: $, headers: { "Content-Type": "application/json" }, body: JSON.stringify(f) }), ve = (x) => x == null ? "—" : x > 1073741824 ? (x / 1073741824).toFixed(1) + " ГБ" : x > 1048576 ? (x / 1048576).toFixed(1) + " МБ" : x > 1024 ? (x / 1024).toFixed(1) + " КБ" : x + " Б", ke = (x) => x ? Math.floor(x / 86400) + " д " + Math.floor(x % 86400 / 3600) + " ч" : "—";
    async function Ie() {
      const x = W.value;
      if (!x) return;
      const f = window.open("about:blank", "_blank");
      try {
        const $ = await s.bridge.request("/api/gateways/" + encodeURIComponent(x.id) + "/adguard"), me = "http://" + (x.host.includes(":") ? "[" + x.host + "]" : x.host) + ":" + ($.web_port || 3e3) + "/";
        f ? (f.opener = null, f.location.href = me) : m.value = "Браузер заблокировал открытие сервиса";
      } catch ($) {
        f?.close(), m.value = $ instanceof Error ? $.message : String($);
      }
    }
    function Oe(x) {
      x.id === "ssclash" || x.id === "adguardhome" ? window.open(et(x), "_blank", "noopener,noreferrer") : window.open(new URL("/cgi-bin/luci/admin/services/" + (x.id === "podkop" ? "podkop" : ""), W.value.luci_url).href, "_blank", "noopener,noreferrer");
    }
    function et(x) {
      const f = W.value.host.includes(":") ? "[" + W.value.host + "]" : W.value.host, $ = Number(x.web_port) || (x.id === "adguardhome" ? 3e3 : 9091);
      return (x.web_https ? "https://" : "http://") + f + ":" + $ + "/";
    }
    async function Ce() {
      try {
        const x = await s.bridge.request("/api/gateways");
        if (x.enabled === !1) {
          s.bridge.navigate("dashboard");
          return;
        }
        r.value = x.gateways || [], c.value && !r.value.some((f) => f.id === c.value) && (c.value = null, I.value = "overview"), Pe(r.value), s.bridge.changed();
      } catch (x) {
        m.value = x.message;
      }
    }
    async function ft() {
      if (!(document.hidden || g.value || y.value))
        try {
          const x = await s.bridge.request("/api/gateways/status");
          if (!ie || !Array.isArray(x.gateways)) return;
          if (x.gateways.length !== r.value.length || x.gateways.some((f) => !r.value.some(($) => $.id === f.id))) {
            await Ce();
            return;
          }
          for (const f of x.gateways) {
            const $ = r.value.find((ue) => ue.id === f.id);
            $.monitor = { ...$.monitor, ...f.monitor };
          }
          Pe(x.gateways);
        } catch (x) {
          ie && (m.value = x instanceof Error ? x.message : String(x));
        }
    }
    function ul() {
      !document.hidden && !y.value && !s.wizard && (Ce(), hn());
    }
    async function we(x) {
      if (!g.value) {
        g.value = !0, m.value = "";
        try {
          await x();
        } catch (f) {
          m.value = f.message;
        } finally {
          g.value = !1;
        }
      }
    }
    async function it() {
      await we(async () => {
        if (T.value === "api") {
          const f = await de("/api/gateways/manual", {
            name: v.value.name,
            url: v.value.url,
            username: v.value.username,
            password: v.value.password,
            tls_sha256: v.value.tls_sha256 || null
          });
          v.value.password = "", y.value = !1, c.value = f.id, await Ce(), s.bridge.navigate("gateways"), s.bridge.close?.();
          return;
        }
        const x = await de("/api/gateways/probe", {
          name: v.value.name,
          host: v.value.host,
          port: Number(v.value.port),
          user: v.value.user,
          password: v.value.password,
          auth_type: "password"
        });
        if (v.value.password = "", x.node_type !== "openwrt") throw new Error("На этом устройстве OpenWrt не обнаружен. Добавьте его в разделе «Серверы».");
        E.value = x;
      });
    }
    async function el(x) {
      await we(async () => {
        const f = await de("/api/gateways/bootstrap/" + encodeURIComponent(E.value.draft_token), { decision: x });
        if (x === "no") {
          E.value = null, y.value = !1, s.bridge.close?.();
          return;
        }
        if (x === "manual") {
          B.value = !0;
          return;
        }
        y.value = !1, s.bridge.task({
          taskId: f.task_id,
          title: "Подключение шлюза",
          cancellable: !1,
          onDone: async ($) => {
            ($.status === "success" || $.status === "success_warn") && (await Ce(), s.bridge.navigate("gateways"));
          },
          renderResult: ($, ue) => {
            const me = document.createElement("p");
            me.textContent = ["success", "success_warn"].includes($.status) ? $.status === "success_warn" ? "Шлюз подключён и сохранён. Есть предупреждения — проверьте журнал задачи и вкладку «Доступ». Повторное подключение не требуется." : "Управление доступом: LuCI → Службы → Bot4VPS. Секрет в журнал не записывается." : "Подключение не завершено. Проверьте журнал и настройки роутера.", ue.replaceChildren(me);
          }
        }), s.bridge.close?.();
      });
    }
    async function Tt(x) {
      l.value = null, t.value = !1, I.value = x, m.value = "", X.value = "", O.value = !1, x === "logs" && W.value && await we(async () => {
        Q.value = (await s.bridge.request("/api/gateways/" + W.value.id + "/logs")).output;
      }), x === "access" && W.value && (v.value.name = W.value.name, v.value.url = W.value.api_url, v.value.username = W.value.api_username, v.value.tls_sha256 = W.value.tls_sha256 || "", v.value.password = "", _.value = { user: W.value.ssh_user || "root", port: W.value.ssh_port || 22, auth_type: W.value.ssh_auth_type || "password", password: "", key_path: "" });
    }
    async function dl(x, f, $, ue, me) {
      const tt = W.value?.id;
      tt && await we(async () => {
        const tl = await de("/api/gateways/" + tt + "/services/" + x + "/plan", { action: f, keep_backup: !0, bundle_id: $ || null, rollback_bundle_id: ue || null, web_scope: me || null });
        if (!ie || W.value?.id !== tt) {
          await de("/api/gateways/" + tt + "/operation-plans/" + encodeURIComponent(tl.plan_token), {}, "DELETE");
          return;
        }
        te.value = tl, R.value = tt, ne.value = O.value, O.value = !1;
      });
    }
    function fs(x, f, $, ue) {
      const me = he(x, f);
      z.value[me] = { stage: ue, task_id: $ }, !pe.has($) && (pe.add($), s.bridge.task({ taskId: $, title: ue === "prepare" ? "Подготовка обновления " + f : "Обновление " + f, cancellable: !1, onDone: async () => {
        try {
          const tt = await s.bridge.request("/api/tasks/" + encodeURIComponent($));
          if (z.value[me]?.task_id && z.value[me].task_id !== $) return;
          if (!tt.success) {
            ie && W.value?.id === x && (m.value = tt.error || "Обновление завершилось с ошибкой. Проверьте журнал задачи."), delete z.value[me];
            return;
          }
          if (ue === "prepare") {
            if (!ie || W.value?.id !== x) {
              delete z.value[me];
              return;
            }
            const tl = JSON.parse(tt.result.output);
            if (tl.review_prepared) {
              const Ei = await s.bridge.request("/api/gateways/" + x + "/services/" + f + "/update-plan?task_id=" + encodeURIComponent($));
              if (z.value[me]?.task_id && z.value[me].task_id !== $) return;
              if (!ie || W.value?.id !== x) {
                delete z.value[me];
                return;
              }
              ps(Ei);
            } else await dl(f, "update", tl.bundle_id, tl.rollback_bundle_id);
            te.value?.action === "update" && te.value.service === f && R.value === x ? z.value[me] = { stage: "review", task_id: te.value.preparation_task_id || $ } : delete z.value[me];
          } else
            delete z.value[me], ie && (await Ce(), await Ol(), le.value++);
        } catch (tt) {
          (!z.value[me]?.task_id || z.value[me].task_id === $) && delete z.value[me], ie && W.value?.id === x && (m.value = tt instanceof Error ? tt.message : String(tt));
        }
      } }));
    }
    function ps(x) {
      const f = W.value?.id;
      !f || x.node_id && x.node_id !== f || (te.value = x, R.value = f, z.value[he(f, x.service)] = { stage: "review", task_id: x.preparation_task_id || void 0 });
    }
    function fi(x, f) {
      W.value && f.task_id && (z.value[he(W.value.id, x)] = { stage: f.stage, task_id: f.task_id });
    }
    async function pi(x) {
      const f = W.value?.id;
      if (!f || g.value || z.value[he(f, x)]) return;
      const $ = he(f, x);
      z.value[$] = { stage: "prepare" }, await we(async () => {
        try {
          const ue = await de("/api/gateways/" + f + "/services/" + x + "/update-bundle", {});
          fs(f, x, ue.task_id, "prepare");
        } catch (ue) {
          throw delete z.value[$], ue;
        }
      });
    }
    async function vi() {
      await we(async () => {
        const x = await de("/api/gateways/" + W.value.id + "/bootstrap/finalize", {});
        s.bridge.task({ taskId: x.task_id, title: "Фиксация подключения", cancellable: !1, onDone: Ce });
      });
    }
    async function gi() {
      const x = W.value;
      x && await we(async () => {
        const f = await de("/api/gateways/" + x.id + "/integration/plan", {});
        Ve.value = { ...f, nodeId: x.id, name: x.name };
      });
    }
    function hi() {
      const x = Ve.value;
      Ve.value = null, x && de("/api/gateways/" + x.nodeId + "/integration/plans/" + encodeURIComponent(x.plan_token), {}, "DELETE").catch((f) => {
        m.value = f instanceof Error ? f.message : String(f);
      });
    }
    async function mi() {
      const x = Ve.value;
      x && await we(async () => {
        const f = await de("/api/gateways/" + x.nodeId + "/integration", { plan_token: x.plan_token, confirmed: !0 });
        Ve.value = null, s.bridge.task({ taskId: f.task_id, title: "Обновление интеграции Bot4VPS", cancellable: !1, onDone: async () => {
          ie && (await Ce(), le.value++);
        } });
      });
    }
    async function bi() {
      const x = te.value?.plan_token, f = R.value || W.value?.id;
      te.value?.action === "update" && f && delete z.value[he(f, te.value.service)];
      const $ = te.value?.action === "update";
      if (te.value = null, R.value = null, m.value = "", ne.value && (O.value = !0), ne.value = !1, x && f)
        try {
          await de("/api/gateways/" + encodeURIComponent(f) + "/operation-plans/" + encodeURIComponent(x), {}, "DELETE");
        } catch (ue) {
          m.value = ue instanceof Error ? ue.message : String(ue);
        } finally {
          $ && le.value++;
        }
    }
    async function yi() {
      const x = te.value, f = R.value || W.value?.id;
      !x || !f || await we(async () => {
        const $ = await de("/api/gateways/" + f + "/operations", { plan_token: x.plan_token, confirmed: !0 }), ue = x.service;
        if (te.value = null, R.value = null, x.action === "update") {
          fs(f, ue, $.task_id, "apply");
          return;
        }
        s.bridge.task({
          taskId: $.task_id,
          title: "Операция: " + ue,
          cancellable: !1,
          onDone: async () => {
            await Ce(), await Ol(), le.value++;
          },
          onResultClosed: (me) => {
            ie && W.value?.id === f && ue === "adguardhome" && x.action === "install" && ["success", "success_warn"].includes(me.status) && (t.value = !0);
          }
        });
      });
    }
    async function Ol() {
      const x = await s.bridge.request("/api/gateways/reserve");
      S.value = x.settings.enabled, k.value = x.settings.keep, U.value = x.bundles;
    }
    async function vs() {
      O.value = !0, await we(async () => {
        await Ol(), await Promise.all(["podkop", "ssclash", "adguardhome"].map(async (x) => {
          const f = await s.bridge.request("/api/gateways/catalog/" + x + "?node_id=" + encodeURIComponent(W.value.id));
          d.value[x] = f.versions, f.versions.includes(u.value[x]) || (u.value[x] = f.versions[0] || "");
        }));
      });
    }
    async function wi() {
      await we(async () => {
        await de("/api/gateways/reserve", { enabled: S.value, keep: Number(k.value) }, "PUT"), X.value = S.value ? "Резервирование включено. Службы на роутере не устанавливаются и не обновляются." : "Автоматическое резервирование отключено. Сохранённые резервные версии останутся на панели.";
      });
    }
    async function _i(x) {
      await we(async () => {
        const f = await de("/api/gateways/" + W.value.id + "/bundles", { profile: x, version: u.value[x] });
        s.bridge.task({
          taskId: f.task_id,
          title: "Подготовка комплекта " + x,
          cancellable: !1,
          onDone: async () => {
            await Ol();
          }
        });
      });
    }
    function mn(x) {
      return U.value.find((f) => f.profile === x && f.version === u.value[x] && f.platform.release?.version === b.value.board?.release?.version && f.platform.release?.target === b.value.board?.release?.target && f.complete);
    }
    async function ki() {
      const x = W.value?.id;
      if (!x) return;
      const f = W.value.tls_sha256, $ = v.value.tls_sha256 || null;
      if (f && f !== $) {
        K.value = { nodeId: x, previous: f, next: $ };
        return;
      }
      await gs(!1);
    }
    async function gs(x) {
      const f = W.value?.id;
      !f || x && K.value?.nodeId !== f || (K.value = null, await we(async () => {
        await de("/api/gateways/" + f + "/credentials", {
          name: v.value.name,
          url: v.value.url,
          username: v.value.username,
          password: v.value.password,
          tls_sha256: v.value.tls_sha256 || null,
          tls_pin_confirmed: x
        }, "PUT"), v.value.password = "", X.value = "Доступ проверен и сохранён", await Ce();
      }));
    }
    async function $i() {
      if (!W.value.ssh_configured) {
        await Tt("access"), m.value = "Сначала сохраните SSH-доступ для консоли.";
        return;
      }
      await we(async () => {
        await s.bridge.console?.(W.value);
      });
    }
    async function Ci() {
      await we(async () => {
        const x = await de("/api/gateways/" + W.value.id + "/ssh", { ..._.value, password: _.value.password || null }, "PUT");
        ++yt, ot.value = { id: x.id, configured: x.root_password_configured }, _.value.password = "", X.value = "SSH-доступ проверен и сохранён.", await Ce();
      });
    }
    function xi() {
      st.value = "", Ne.value = { current_password: "", password: "", confirmation: "" }, Ht.value = !0;
    }
    function hs() {
      Ne.value = { current_password: "", password: "", confirmation: "" }, Ht.value = !1;
    }
    async function Si() {
      const x = W.value;
      if (!(!x || g.value)) {
        if (st.value = "", Ne.value.password !== Ne.value.confirmation) {
          st.value = "Пароли не совпадают.";
          return;
        }
        g.value = !0;
        try {
          const f = await de("/api/gateways/" + x.id + "/root-password", Ne.value, "PUT");
          ++yt, ot.value = { id: x.id, configured: f.root_password_configured }, hs(), X.value = f.ssh_auth_type === "key" ? "Пароль root изменён. Консоль подключается по SSH-ключу." : "Пароль root и SSH для консоли обновлены.", await Ce(), W.value?.id === x.id && (_.value.auth_type = f.ssh_auth_type);
        } catch (f) {
          st.value = f.message;
        } finally {
          g.value = !1;
        }
      }
    }
    async function Vi() {
      await we(async () => {
        j.value = await s.bridge.request("/api/gateways/" + W.value.id + "/deletion-plan");
      });
    }
    async function Ti() {
      await we(async () => {
        const x = await de("/api/gateways/" + W.value.id, { confirmed: !0, plan_token: j.value.plan_token }, "DELETE");
        j.value = null, s.bridge.task({
          taskId: x.task_id,
          title: "Удаление шлюза и отзыв API",
          cancellable: !1,
          onDone: async () => {
            c.value = null, await Ce();
          },
          renderResult: (f, $) => {
            const ue = document.createElement("p");
            ue.textContent = f.status === "success" ? "Удаление шлюза завершено. Результат очистки Bot4VPS — в журнале задачи. Настройки роутера и установленные службы сохранены." : "Отзыв доступа или очистка интеграции не завершены. Запись шлюза сохранена; проверьте журнал задачи.", $.replaceChildren(ue);
          }
        });
      });
    }
    return ct(() => {
      s.wizard || (Ce().then(() => {
        if (ie && W.value) return Tt(I.value);
      }), ae = setInterval(() => {
        ft();
      }, 5e3), document.addEventListener("visibilitychange", ul));
    }), qt(() => {
      ie = !1, ae && clearInterval(ae), document.removeEventListener("visibilitychange", ul), v.value.password = "", _.value.password = "";
    }), (x, f) => (p(), h("div", {
      class: Ue(["gw-shell", { "gw-wizard": e.wizard }])
    }, [
      m.value ? (p(), h("div", Mh, w(m.value), 1)) : V("", !0),
      Ve.value ? (p(), ge(bh, {
        key: 1,
        plan: Ve.value,
        busy: g.value,
        error: m.value,
        onCancel: hi,
        onApply: mi
      }, null, 8, ["plan", "busy", "error"])) : V("", !0),
      K.value ? (p(), ge($h, {
        key: 2,
        change: K.value,
        busy: g.value,
        onCancel: f[0] || (f[0] = ($) => K.value = null),
        onApply: f[1] || (f[1] = ($) => gs(!0))
      }, null, 8, ["change", "busy"])) : V("", !0),
      Ht.value ? (p(), ge(qe, {
        key: 3,
        title: Gt.value === !1 ? "Задать пароль root" : "Сменить пароль root",
        busy: g.value,
        compact: "",
        onClose: hs
      }, {
        default: Re(() => [
          n("form", {
            class: "gw-form",
            onSubmit: Ze(Si, ["prevent"])
          }, [
            Gt.value !== !1 ? (p(), h("label", Oh, [
              f[55] || (f[55] = A("Текущий пароль", -1)),
              Ee(vt, {
                modelValue: Ne.value.current_password,
                "onUpdate:modelValue": f[2] || (f[2] = ($) => Ne.value.current_password = $),
                required: "",
                autocomplete: "current-password",
                disabled: g.value
              }, null, 8, ["modelValue", "disabled"])
            ])) : V("", !0),
            n("label", null, [
              f[56] || (f[56] = A("Новый пароль", -1)),
              Ee(vt, {
                modelValue: Ne.value.password,
                "onUpdate:modelValue": f[3] || (f[3] = ($) => Ne.value.password = $),
                required: "",
                autocomplete: "new-password",
                disabled: g.value
              }, null, 8, ["modelValue", "disabled"])
            ]),
            n("label", null, [
              f[57] || (f[57] = A("Повторите пароль", -1)),
              Ee(vt, {
                modelValue: Ne.value.confirmation,
                "onUpdate:modelValue": f[4] || (f[4] = ($) => Ne.value.confirmation = $),
                required: "",
                autocomplete: "new-password",
                disabled: g.value
              }, null, 8, ["modelValue", "disabled"])
            ]),
            st.value ? (p(), h("p", Rh, w(st.value), 1)) : V("", !0),
            n("div", Dh, [
              n("button", {
                class: "gw-primary",
                disabled: g.value
              }, w(g.value ? "Сохраняем…" : "Сохранить"), 9, Nh)
            ])
          ], 32)
        ]),
        _: 1
      }, 8, ["title", "busy"])) : V("", !0),
      y.value ? (p(), h(N, { key: 4 }, [
        f[74] || (f[74] = n("header", { class: "gw-header" }, [
          n("div", null, [
            n("span", { class: "gw-eyebrow" }, "НОВОЕ ПОДКЛЮЧЕНИЕ"),
            n("h2", null, "Добавить шлюз"),
            n("p", null, "Подключение OpenWrt к вашей инфраструктуре")
          ])
        ], -1)),
        E.value ? (p(), h(N, { key: 1 }, [
          n("div", Wh, [
            f[68] || (f[68] = n("span", { class: "gw-status good" }, "OpenWrt обнаружен", -1)),
            n("h3", null, w(E.value.board.model), 1),
            E.value.name ? (p(), h("p", Bh, "Имя шлюза: " + w(E.value.name), 1)) : V("", !0),
            n("p", null, w(E.value.board.release?.version) + " · " + w(E.value.board.release?.target), 1)
          ]),
          E.value.board.root_password_configured === !1 ? (p(), h("div", Kh, "Пароль root не задан. После подключения задайте его во вкладке «Доступ».")) : V("", !0),
          n("div", Gh, [
            f[70] || (f[70] = n("h3", null, "Для подключения панель выполнит", -1)),
            n("ul", null, [
              (p(!0), h(N, null, se(E.value.missing_packages, ($) => (p(), h("li", { key: $ }, [
                f[69] || (f[69] = A("Установит пакет ", -1)),
                n("strong", null, w($), 1)
              ]))), 128)),
              E.value.missing_packages?.length ? V("", !0) : (p(), h("li", zh, "Необходимые пакеты уже установлены")),
              (p(!0), h(N, null, se(E.value.changes, ($) => (p(), h("li", { key: $ }, w($), 1))), 128)),
              E.value.https_configuration_required ? (p(), h("li", Jh, "Включит HTTPS на адресе LAN")) : V("", !0)
            ]),
            f[71] || (f[71] = n("p", { class: "gw-hint" }, "Прошивка и установленные пакеты не обновляются. Сетевые интерфейсы не перенастраиваются. Ход настройки будет виден в журнале.", -1))
          ]),
          n("div", Yh, [
            n("button", {
              class: "gw-primary",
              disabled: g.value,
              onClick: f[17] || (f[17] = ($) => el("automatic"))
            }, "Да, настроить автоматически", 8, Xh),
            n("button", {
              disabled: g.value,
              onClick: f[18] || (f[18] = ($) => el("no"))
            }, "Нет", 8, Qh),
            n("button", {
              disabled: g.value,
              onClick: f[19] || (f[19] = ($) => el("manual"))
            }, "Настроить самостоятельно", 8, Zh)
          ]),
          B.value ? (p(), h("div", em, [
            f[73] || (f[73] = n("h3", null, "Самостоятельная настройка", -1)),
            E.value.manual.commands.length ? (p(), h("pre", tm, w(E.value.manual.commands.join(`
`)), 1)) : V("", !0),
            n("ol", null, [
              (p(!0), h(N, null, se(E.value.manual.steps, ($) => (p(), h("li", { key: $ }, w($), 1))), 128))
            ]),
            n("details", null, [
              f[72] || (f[72] = n("summary", null, "Права мониторинга rpcd", -1)),
              n("pre", null, w(JSON.stringify(E.value.manual.acl, null, 2)), 1)
            ]),
            n("button", {
              onClick: f[20] || (f[20] = ($) => {
                T.value = "api", E.value = null;
              })
            }, "Указать данные API")
          ])) : V("", !0)
        ], 64)) : (p(), h(N, { key: 0 }, [
          n("div", qh, [
            n("button", {
              class: Ue({ on: T.value === "ssh" }),
              onClick: f[5] || (f[5] = ($) => T.value = "ssh")
            }, "Настроить автоматически", 2),
            n("button", {
              class: Ue({ on: T.value === "api" }),
              onClick: f[6] || (f[6] = ($) => T.value = "api")
            }, "API уже настроен", 2)
          ]),
          n("form", {
            class: "gw-form",
            onSubmit: Ze(it, ["prevent"])
          }, [
            n("label", null, [
              f[58] || (f[58] = A("Имя шлюза", -1)),
              F(n("input", {
                "onUpdate:modelValue": f[7] || (f[7] = ($) => v.value.name = $),
                placeholder: "Определится по модели роутера",
                maxlength: "100"
              }, null, 512), [
                [re, v.value.name]
              ])
            ]),
            T.value === "ssh" ? (p(), h(N, { key: 0 }, [
              n("label", null, [
                f[59] || (f[59] = A("Адрес роутера", -1)),
                F(n("input", {
                  "onUpdate:modelValue": f[8] || (f[8] = ($) => v.value.host = $),
                  required: "",
                  placeholder: "192.168.1.1"
                }, null, 512), [
                  [re, v.value.host]
                ])
              ]),
              n("div", Hh, [
                n("label", null, [
                  f[60] || (f[60] = A("SSH-порт", -1)),
                  F(n("input", {
                    "onUpdate:modelValue": f[9] || (f[9] = ($) => v.value.port = $),
                    required: "",
                    type: "number",
                    min: "1",
                    max: "65535"
                  }, null, 512), [
                    [re, v.value.port]
                  ])
                ]),
                n("label", null, [
                  f[61] || (f[61] = A("Логин", -1)),
                  F(n("input", {
                    "onUpdate:modelValue": f[10] || (f[10] = ($) => v.value.user = $),
                    required: "",
                    autocomplete: "username"
                  }, null, 512), [
                    [re, v.value.user]
                  ])
                ])
              ]),
              n("label", null, [
                f[62] || (f[62] = A("SSH-пароль", -1)),
                Ee(vt, {
                  modelValue: v.value.password,
                  "onUpdate:modelValue": f[11] || (f[11] = ($) => v.value.password = $),
                  required: v.value.user !== "root",
                  autocomplete: "off",
                  placeholder: "Оставьте пустым, если пароль root ещё не задан"
                }, null, 8, ["modelValue", "required"])
              ]),
              f[63] || (f[63] = n("p", { class: "gw-hint" }, "Сначала панель проверит устройство и покажет необходимые изменения. Проверка ничего не устанавливает.", -1))
            ], 64)) : (p(), h(N, { key: 1 }, [
              n("label", null, [
                f[64] || (f[64] = A("HTTPS API", -1)),
                F(n("input", {
                  "onUpdate:modelValue": f[12] || (f[12] = ($) => v.value.url = $),
                  required: "",
                  type: "url",
                  placeholder: "https://192.168.1.1/ubus"
                }, null, 512), [
                  [re, v.value.url]
                ])
              ]),
              n("label", null, [
                f[65] || (f[65] = A("Логин API", -1)),
                F(n("input", {
                  "onUpdate:modelValue": f[13] || (f[13] = ($) => v.value.username = $),
                  required: "",
                  autocomplete: "username"
                }, null, 512), [
                  [re, v.value.username]
                ])
              ]),
              n("label", null, [
                f[66] || (f[66] = A("Секрет API", -1)),
                Ee(vt, {
                  modelValue: v.value.password,
                  "onUpdate:modelValue": f[14] || (f[14] = ($) => v.value.password = $),
                  required: "",
                  autocomplete: "off"
                }, null, 8, ["modelValue"])
              ]),
              n("label", null, [
                f[67] || (f[67] = A("SHA-256 сертификата", -1)),
                F(n("input", {
                  "onUpdate:modelValue": f[15] || (f[15] = ($) => v.value.tls_sha256 = $),
                  placeholder: "Для собственного сертификата роутера"
                }, null, 512), [
                  [re, v.value.tls_sha256]
                ])
              ])
            ], 64)),
            n("div", Fh, [
              n("button", {
                class: "gw-primary",
                disabled: g.value
              }, w(g.value ? "Проверяем…" : T.value === "ssh" ? "Проверить роутер" : "Проверить и подключить"), 9, Lh),
              n("button", {
                type: "button",
                onClick: f[16] || (f[16] = ($) => {
                  y.value = !1, e.bridge.close?.();
                }),
                disabled: g.value
              }, "Отмена", 8, jh)
            ])
          ], 32)
        ], 64))
      ], 64)) : e.wizard ? V("", !0) : (p(), h(N, { key: 5 }, [
        W.value ? V("", !0) : (p(), h(N, { key: 0 }, [
          n("header", lm, [
            n("div", null, [
              f[75] || (f[75] = n("span", { class: "gw-eyebrow" }, "СЕТЬ И МАРШРУТИЗАЦИЯ", -1)),
              f[76] || (f[76] = n("h1", null, "Шлюзы", -1)),
              n("p", null, "OpenWrt · " + w(r.value.length) + " подключений", 1)
            ]),
            n("button", {
              class: "gw-primary",
              onClick: f[21] || (f[21] = ($) => e.bridge.add?.())
            }, "Добавить шлюз")
          ]),
          r.value.length ? V("", !0) : (p(), h("div", nm, [
            f[77] || (f[77] = n("div", { class: "gw-empty-icon" }, "⌘", -1)),
            f[78] || (f[78] = n("h2", null, "Подключите ваш OpenWrt", -1)),
            f[79] || (f[79] = n("p", null, "Обзор сети, состояние служб и операции с понятным журналом.", -1)),
            n("button", {
              class: "gw-primary",
              onClick: f[22] || (f[22] = ($) => e.bridge.add?.())
            }, "Добавить шлюз")
          ])),
          r.value.length > 3 ? F((p(), h("input", {
            key: 1,
            "onUpdate:modelValue": f[23] || (f[23] = ($) => P.value = $),
            class: "gw-node-search",
            type: "search",
            "aria-label": "Поиск шлюзов",
            placeholder: "Найти шлюз по имени или адресу"
          }, null, 512)), [
            [re, P.value]
          ]) : V("", !0),
          oe.value.length ? (p(), h("div", sm, [
            n("table", om, [
              f[84] || (f[84] = n("thead", null, [
                n("tr", null, [
                  n("th", null, "Имя шлюза"),
                  n("th", null, "Адрес / OpenWrt"),
                  n("th", null, "Статус"),
                  n("th", null, "Нагрузка"),
                  n("th", null, "Трафик LAN / WAN")
                ])
              ], -1)),
              n("tbody", null, [
                (p(!0), h(N, null, se(oe.value, ($) => (p(), h("tr", {
                  key: $.id,
                  class: "server-table-row",
                  tabindex: "0",
                  role: "button",
                  onClick: (ue) => {
                    c.value = $.id, I.value = "overview", m.value = "";
                  },
                  onKeydown: [
                    ln(Ze((ue) => {
                      c.value = $.id, I.value = "overview", m.value = "";
                    }, ["prevent"]), ["enter"]),
                    ln(Ze((ue) => {
                      c.value = $.id, I.value = "overview", m.value = "";
                    }, ["prevent"]), ["space"])
                  ]
                }, [
                  n("td", am, [
                    n("div", rm, [
                      f[80] || (f[80] = n("span", {
                        class: "gw-router-icon",
                        "aria-hidden": "true"
                      }, [
                        n("svg", {
                          viewBox: "0 0 24 24",
                          width: "20",
                          height: "20"
                        }, [
                          n("rect", {
                            x: "3",
                            y: "11",
                            width: "18",
                            height: "9",
                            rx: "2"
                          }),
                          n("path", { d: "M7 11V5m10 6V5M5 6a10 10 0 0 1 14 0M8 8a6 6 0 0 1 8 0M7 16h.01M11 16h.01" })
                        ])
                      ], -1)),
                      n("strong", {
                        title: $.name
                      }, w($.name), 9, um)
                    ])
                  ]),
                  n("td", dm, [
                    n("span", null, w($.host), 1),
                    n("small", null, "OpenWrt " + w($.monitor.board?.release?.version || "—"), 1)
                  ]),
                  n("td", null, [
                    n("span", {
                      class: Ue(["gw-status", $.monitor.ok ? "good" : "warn"])
                    }, w($.monitor.ok ? $.monitor.stale ? "Данные устарели" : "На связи" : "Нет доступа к API"), 3)
                  ]),
                  n("td", cm, [
                    n("div", fm, [
                      n("span", null, [
                        f[81] || (f[81] = A("CPU ", -1)),
                        n("b", null, w($.monitor.cpu_pct == null ? "—" : $.monitor.cpu_pct + "%"), 1)
                      ]),
                      n("span", null, [
                        f[82] || (f[82] = A("RAM ", -1)),
                        n("b", null, w($.monitor.ram_pct == null ? "—" : $.monitor.ram_pct + "%"), 1)
                      ]),
                      n("span", null, [
                        f[83] || (f[83] = A("SoC ", -1)),
                        n("b", null, w($.monitor.temperature == null ? "—" : $.monitor.temperature + "°C"), 1)
                      ])
                    ])
                  ]),
                  n("td", pm, [
                    n("span", null, "LAN ↓ " + w(ve($.monitor.traffic?.lan?.rx_bps)) + "/с · ↑ " + w(ve($.monitor.traffic?.lan?.tx_bps)) + "/с", 1),
                    n("span", null, "WAN ↓ " + w(ve($.monitor.traffic?.wan?.rx_bps)) + "/с · ↑ " + w(ve($.monitor.traffic?.wan?.tx_bps)) + "/с", 1)
                  ])
                ], 40, im))), 128))
              ])
            ])
          ])) : V("", !0)
        ], 64)),
        W.value ? (p(), h("section", vm, [
          n("button", {
            class: "gw-back-link",
            disabled: g.value,
            onClick: f[24] || (f[24] = ($) => {
              c.value = null, O.value = !1;
            })
          }, "← Все шлюзы", 8, gm),
          Ee(Eg, {
            node: W.value,
            busy: g.value,
            onConsole: $i
          }, null, 8, ["node", "busy"]),
          b.value.ok ? V("", !0) : (p(), h("p", hm, w(b.value.error) + ". " + w(b.value.error_code === "permission" ? "Проверьте доступ в LuCI или укажите новый секрет во вкладке «Доступ»." : "Проверьте доступность API роутера. Панель повторит проверку автоматически."), 1)),
          W.value.bootstrap_state === "commit_pending" ? (p(), h("p", mm, "Шлюз подключён. Фиксация транзакции не подтверждена; завершите её во вкладке «Доступ».")) : V("", !0),
          Gt.value === !1 ? (p(), h("div", bm, [
            f[85] || (f[85] = n("span", null, [
              n("strong", null, "Пароль root не задан."),
              A(" Задайте пароль для защиты доступа к роутеру.")
            ], -1)),
            n("button", {
              type: "button",
              onClick: f[25] || (f[25] = ($) => Tt("access"))
            }, "Открыть «Доступ»")
          ])) : V("", !0),
          n("div", ym, [
            (p(), h(N, null, se(ee, ($) => n("button", {
              key: $.id,
              class: Ue({ on: I.value === $.id }),
              onClick: (ue) => Tt($.id)
            }, w($.name), 11, wm)), 64))
          ]),
          I.value === "overview" ? (p(), h(N, { key: 3 }, [
            n("div", _m, [
              n("div", km, [
                f[86] || (f[86] = n("span", null, "Загрузка CPU", -1)),
                n("strong", null, w(b.value.cpu_pct == null ? "—" : b.value.cpu_pct + "%"), 1)
              ]),
              n("div", $m, [
                f[87] || (f[87] = n("span", null, "Оперативная память", -1)),
                n("strong", null, w(b.value.ram_pct == null ? "—" : b.value.ram_pct + "%"), 1),
                n("small", null, w(ve(b.value.ram_used)) + " / " + w(ve(b.value.ram_total)), 1)
              ]),
              n("div", Cm, [
                f[88] || (f[88] = n("span", null, "Свободное место", -1)),
                n("strong", null, w(ve(b.value.storage_free)), 1),
                n("small", null, "из " + w(ve(b.value.storage_total)), 1)
              ]),
              n("div", xm, [
                f[89] || (f[89] = n("span", null, "Время работы", -1)),
                n("strong", null, w(ke(b.value.uptime)), 1)
              ]),
              n("div", Sm, [
                f[90] || (f[90] = n("span", null, "Температура", -1)),
                n("strong", null, w(b.value.temperature == null ? "Нет датчика" : b.value.temperature + "°C"), 1),
                b.value.temperature_support?.virtual ? (p(), h("small", Vm, "Виртуальная машина")) : V("", !0),
                b.value.temperature_support?.package ? (p(), h("button", {
                  key: 1,
                  onClick: f[26] || (f[26] = ($) => {
                    Z.value = b.value.temperature_support.package, Tt("packages");
                  })
                }, "Проверить пакет датчика")) : V("", !0)
              ])
            ]),
            Ee(mp, {
              monitor: b.value,
              "node-id": W.value.id,
              bridge: e.bridge
            }, null, 8, ["monitor", "node-id", "bridge"])
          ], 64)) : V("", !0),
          I.value === "network" ? (p(), h(N, { key: 4 }, [
            (p(), ge(xf, {
              key: W.value.id,
              node: W.value,
              bridge: e.bridge,
              onChanged: Ce
            }, null, 8, ["node", "bridge"])),
            n("section", Tm, [
              n("header", Em, [
                n("div", null, [
                  n("h3", null, [
                    f[91] || (f[91] = A("DHCP-клиенты ", -1)),
                    n("small", null, w(b.value.clients?.length || 0), 1)
                  ]),
                  f[92] || (f[92] = n("p", { class: "gw-hint" }, "Аренда DHCP не подтверждает текущую доступность клиента.", -1))
                ]),
                F(n("input", {
                  "onUpdate:modelValue": f[27] || (f[27] = ($) => L.value = $),
                  type: "search",
                  "aria-label": "Поиск DHCP-клиентов",
                  placeholder: "Имя, IP или MAC"
                }, null, 512), [
                  [re, L.value]
                ])
              ]),
              n("div", Um, [
                n("table", null, [
                  f[93] || (f[93] = n("thead", null, [
                    n("tr", null, [
                      n("th", null, "Клиент"),
                      n("th", null, "IP-адрес"),
                      n("th", null, "MAC-адрес")
                    ])
                  ], -1)),
                  n("tbody", null, [
                    (p(!0), h(N, null, se(Y.value, ($) => (p(), h("tr", {
                      key: $.macaddr + ":" + $.ipaddr
                    }, [
                      n("td", null, w($.hostname || "Без имени"), 1),
                      n("td", null, w($.ipaddr), 1),
                      n("td", null, w($.macaddr), 1)
                    ]))), 128))
                  ])
                ])
              ]),
              G.value.length ? V("", !0) : (p(), h("p", Pm, w(L.value ? "Клиенты не найдены" : "Нет данных об арендах"), 1)),
              G.value.length ? (p(), h("footer", Am, [
                n("span", Im, w((M.value - 1) * D + 1) + "–" + w(Math.min(M.value * D, G.value.length)) + " из " + w(G.value.length), 1),
                n("div", Mm, [
                  n("button", {
                    disabled: M.value === 1,
                    onClick: f[28] || (f[28] = ($) => M.value--)
                  }, "Назад", 8, Om),
                  n("span", Rm, w(M.value) + " / " + w(J.value), 1),
                  n("button", {
                    disabled: M.value >= J.value,
                    onClick: f[29] || (f[29] = ($) => M.value++)
                  }, "Далее", 8, Dm)
                ])
              ])) : V("", !0)
            ])
          ], 64)) : V("", !0),
          I.value === "wifi" ? (p(), ge(Gv, {
            key: W.value.id,
            node: W.value,
            bridge: e.bridge,
            onChanged: Ce
          }, null, 8, ["node", "bridge"])) : V("", !0),
          I.value === "services" ? (p(), ge(kg, {
            key: W.value.id,
            revision: le.value,
            node: W.value,
            bridge: e.bridge,
            busy: g.value,
            updating: Me.value,
            onPending: fi,
            onResume: ps,
            onWebAccess: f[30] || (f[30] = ($) => dl("ssclash", "web_access", void 0, void 0, $)),
            onCatalog: vs,
            onSettings: q,
            onHelp: f[31] || (f[31] = ($) => t.value = !0),
            onOpenAdguard: Ie,
            onAction: dl,
            onFirewallRestart: f[32] || (f[32] = ($) => o.value = W.value),
            onUpdate: pi
          }, null, 8, ["revision", "node", "bridge", "busy", "updating"])) : V("", !0),
          I.value === "backups" ? (p(), ge(nh, {
            key: W.value.id,
            node: W.value,
            bridge: e.bridge
          }, null, 8, ["node", "bridge"])) : V("", !0),
          o.value ? (p(), ge(Ih, {
            key: 8,
            node: o.value,
            bridge: e.bridge,
            onClose: f[33] || (f[33] = ($) => o.value = null),
            onChanged: Ce
          }, null, 8, ["node", "bridge"])) : V("", !0),
          l.value ? (p(), ge(ci, {
            key: 9,
            node: W.value,
            bridge: e.bridge,
            mode: l.value,
            onClose: f[34] || (f[34] = ($) => l.value = null),
            onChanged: Ce
          }, null, 8, ["node", "bridge", "mode"])) : V("", !0),
          O.value ? (p(), ge(qe, {
            key: 10,
            title: "Установка служб",
            wide: !0,
            compact: !0,
            onClose: f[38] || (f[38] = ($) => {
              O.value = !1, m.value = "";
            })
          }, {
            default: Re(() => [
              f[99] || (f[99] = n("p", { class: "gw-hint" }, "Готовые комплекты с зависимостями для вашего OpenWrt. Скачивание на панель и установка на роутер выполняются отдельно.", -1)),
              g.value ? (p(), h("p", Nm, "Получаем совместимые версии…")) : V("", !0),
              m.value ? (p(), h("p", qm, w(m.value), 1)) : V("", !0),
              n("div", Hm, [
                (p(), h(N, null, se(["podkop", "ssclash", "adguardhome"], ($) => n("details", {
                  key: $,
                  class: "gw-catalog-item"
                }, [
                  n("summary", Fm, [
                    n("div", null, [
                      n("h3", null, w($ === "podkop" ? "Podkop" : $ === "ssclash" ? "SSClash-Go" : "AdGuard Home"), 1),
                      Ee(ds, { id: $ }, null, 8, ["id"])
                    ]),
                    b.value.services?.some((ue) => ue.id === $) ? (p(), h("span", Lm, "Установлен")) : V("", !0)
                  ]),
                  n("div", jm, [
                    n("div", Wm, [
                      n("label", Bm, [
                        f[94] || (f[94] = A("Версия", -1)),
                        F(n("select", {
                          "onUpdate:modelValue": (ue) => u.value[$] = ue,
                          disabled: g.value
                        }, [
                          (p(!0), h(N, null, se(d.value[$], (ue) => (p(), h("option", { key: ue }, w(ue), 1))), 128)),
                          d.value[$]?.length ? V("", !0) : (p(), h("option", Gm, w(g.value ? "Загружаем версии…" : "Нет совместимых версий"), 1))
                        ], 8, Km), [
                          [xe, u.value[$]]
                        ])
                      ]),
                      n("div", zm, [
                        mn($) ? (p(), h("button", {
                          key: 1,
                          disabled: g.value || b.value.services?.some((ue) => ue.id === $),
                          class: "gw-primary",
                          onClick: (ue) => dl($, "install", mn($).id)
                        }, "Установить", 8, Ym)) : (p(), h("button", {
                          key: 0,
                          disabled: g.value || !u.value[$],
                          onClick: (ue) => _i($)
                        }, "Скачать комплект на панель", 8, Jm)),
                        $ === "adguardhome" ? (p(), h("button", {
                          key: 2,
                          onClick: f[35] || (f[35] = (ue) => {
                            O.value = !1, t.value = !0;
                          })
                        }, "Настроить DNS")) : V("", !0)
                      ])
                    ]),
                    n("p", Xm, w(mn($) ? "Комплект сохранён на панели — установка доступна без GitHub." : "Панель скачает файлы и все совместимые зависимости."), 1),
                    $ === "adguardhome" ? (p(), h("p", Qm, "Установка не переключает DNS и DHCP.")) : V("", !0),
                    b.value.services?.some((ue) => ue.id === $) ? (p(), h("p", Zm, "Обновление установленной службы доступно в списке сервисов, если найдена новая совместимая версия.")) : V("", !0)
                  ])
                ])), 64))
              ]),
              n("section", e1, [
                f[97] || (f[97] = n("h3", null, "Резерв версий на панели", -1)),
                n("label", t1, [
                  F(n("input", {
                    "onUpdate:modelValue": f[36] || (f[36] = ($) => S.value = $),
                    type: "checkbox"
                  }, null, 512), [
                    [We, S.value]
                  ]),
                  f[95] || (f[95] = A(" Хранить установочные комплекты резервно", -1))
                ]),
                f[98] || (f[98] = n("p", { class: "gw-hint" }, "Резерв позволяет устанавливать сервисы при недоступном GitHub. Скачивание не запускает установку или обновление на роутере.", -1)),
                n("div", l1, [
                  F(n("select", {
                    "onUpdate:modelValue": f[37] || (f[37] = ($) => k.value = $),
                    "aria-label": "Количество резервных версий"
                  }, [...f[96] || (f[96] = [
                    n("option", { value: 2 }, "2 последние совместимые версии", -1),
                    n("option", { value: 3 }, "3 последние совместимые версии", -1)
                  ])], 512), [
                    [xe, k.value]
                  ]),
                  n("button", {
                    disabled: g.value,
                    onClick: wi
                  }, "Сохранить настройки", 8, n1)
                ]),
                X.value ? (p(), h("p", s1, w(X.value), 1)) : V("", !0)
              ])
            ]),
            _: 1
          })) : V("", !0),
          t.value ? (p(), ge(Eu, {
            key: 11,
            node: W.value,
            bridge: e.bridge,
            onClose: f[39] || (f[39] = ($) => t.value = !1),
            onInstall: f[40] || (f[40] = ($) => {
              t.value = !1, vs();
            }),
            onStart: f[41] || (f[41] = ($) => {
              t.value = !1, dl("adguardhome", "start");
            })
          }, null, 8, ["node", "bridge"])) : V("", !0),
          I.value === "packages" ? (p(), ge(Xf, {
            key: W.value.id,
            node: W.value,
            bridge: e.bridge,
            "initial-query": Z.value,
            onChanged: Ce
          }, null, 8, ["node", "bridge", "initial-query"])) : V("", !0),
          I.value === "logs" ? (p(), h("div", o1, [
            n("div", i1, [
              f[100] || (f[100] = n("h3", null, "Системный журнал", -1)),
              n("button", {
                disabled: g.value,
                onClick: f[42] || (f[42] = ($) => Tt("logs"))
              }, "Обновить", 8, a1)
            ]),
            n("pre", r1, w(Q.value || "Нет записей"), 1)
          ])) : V("", !0),
          I.value === "access" ? (p(), h("section", u1, [
            W.value.ssh_configured && (W.value.managed || W.value.ssh_user === "root") ? (p(), h("div", d1, [
              W.value.managed ? (p(), h("p", c1, "RPC-компоненты и интерфейс LuCI Bot4VPS")) : V("", !0),
              n("div", f1, [
                W.value.managed ? (p(), h("button", {
                  key: 0,
                  type: "button",
                  disabled: g.value,
                  onClick: gi
                }, "Обновить интеграцию Bot4VPS", 8, p1)) : V("", !0),
                n("button", {
                  type: "button",
                  disabled: g.value || W.value.ssh_user !== "root",
                  onClick: xi
                }, w(Gt.value === !1 ? "Задать пароль root" : "Сменить пароль root"), 9, v1)
              ])
            ])) : V("", !0),
            W.value.bootstrap_state === "commit_pending" ? (p(), h("button", {
              key: 1,
              disabled: g.value,
              onClick: vi
            }, "Завершить фиксацию подключения", 8, g1)) : V("", !0),
            n("header", h1, [
              f[101] || (f[101] = n("div", null, [
                n("h3", null, "Доступ к шлюзу"),
                n("p", { class: "gw-hint" }, "Данные API и SSH для подключения панели")
              ], -1)),
              n("button", {
                class: "gw-danger",
                disabled: g.value,
                onClick: Vi
              }, w(W.value.deletion_pending ? "Повторить отзыв и удаление" : "Удалить шлюз"), 9, m1)
            ]),
            !W.value.ssh_configured || W.value.ssh_user !== "root" ? (p(), h("p", b1, "Для смены пароля роутера сохраните SSH-доступ под root.")) : V("", !0),
            X.value ? (p(), h("p", y1, w(X.value), 1)) : V("", !0),
            n("div", w1, [
              n("form", {
                class: "gw-form",
                onSubmit: Ze(ki, ["prevent"])
              }, [
                f[108] || (f[108] = n("h4", null, "API OpenWrt", -1)),
                n("p", _1, [
                  f[102] || (f[102] = A("Управление секретом: ", -1)),
                  n("a", {
                    href: W.value.access_url,
                    target: "_blank",
                    rel: "noopener noreferrer"
                  }, "LuCI → Службы → Bot4VPS ↗", 8, k1)
                ]),
                n("label", null, [
                  f[103] || (f[103] = A("Имя шлюза", -1)),
                  F(n("input", {
                    "onUpdate:modelValue": f[43] || (f[43] = ($) => v.value.name = $),
                    placeholder: "Определится по модели роутера",
                    maxlength: "100"
                  }, null, 512), [
                    [re, v.value.name]
                  ])
                ]),
                n("label", null, [
                  f[104] || (f[104] = A("Адрес API", -1)),
                  F(n("input", {
                    "onUpdate:modelValue": f[44] || (f[44] = ($) => v.value.url = $),
                    required: ""
                  }, null, 512), [
                    [re, v.value.url]
                  ])
                ]),
                n("label", null, [
                  f[105] || (f[105] = A("Логин API", -1)),
                  F(n("input", {
                    "onUpdate:modelValue": f[45] || (f[45] = ($) => v.value.username = $),
                    required: ""
                  }, null, 512), [
                    [re, v.value.username]
                  ])
                ]),
                n("label", null, [
                  f[106] || (f[106] = A("Новый секрет", -1)),
                  Ee(vt, {
                    modelValue: v.value.password,
                    "onUpdate:modelValue": f[46] || (f[46] = ($) => v.value.password = $),
                    required: "",
                    autocomplete: "off"
                  }, null, 8, ["modelValue"])
                ]),
                n("label", null, [
                  f[107] || (f[107] = A("SHA-256 сертификата", -1)),
                  F(n("input", {
                    "onUpdate:modelValue": f[47] || (f[47] = ($) => v.value.tls_sha256 = $)
                  }, null, 512), [
                    [re, v.value.tls_sha256]
                  ])
                ]),
                n("div", $1, [
                  n("button", {
                    class: "gw-primary",
                    disabled: g.value
                  }, "Проверить и сохранить API", 8, C1)
                ])
              ], 32),
              n("form", {
                class: "gw-form",
                onSubmit: Ze(Ci, ["prevent"])
              }, [
                f[116] || (f[116] = n("h4", null, "SSH для консоли", -1)),
                f[117] || (f[117] = n("p", { class: "gw-hint" }, "Пароль хранится зашифрованным мастер-ключом панели.", -1)),
                n("div", x1, [
                  n("label", null, [
                    f[109] || (f[109] = A("SSH-логин", -1)),
                    F(n("input", {
                      "onUpdate:modelValue": f[48] || (f[48] = ($) => _.value.user = $),
                      required: ""
                    }, null, 512), [
                      [re, _.value.user]
                    ])
                  ]),
                  n("label", null, [
                    f[110] || (f[110] = A("SSH-порт", -1)),
                    F(n("input", {
                      "onUpdate:modelValue": f[49] || (f[49] = ($) => _.value.port = $),
                      type: "number",
                      min: "1",
                      max: "65535",
                      required: ""
                    }, null, 512), [
                      [re, _.value.port]
                    ])
                  ])
                ]),
                n("label", null, [
                  f[113] || (f[113] = A("Авторизация", -1)),
                  F(n("select", {
                    "onUpdate:modelValue": f[50] || (f[50] = ($) => _.value.auth_type = $)
                  }, [
                    f[111] || (f[111] = n("option", { value: "password" }, "Пароль", -1)),
                    f[112] || (f[112] = n("option", { value: "key" }, "SSH-ключ панели", -1)),
                    n("option", {
                      value: "none",
                      disabled: _.value.user !== "root"
                    }, "Без пароля (первый вход root)", 8, S1)
                  ], 512), [
                    [xe, _.value.auth_type]
                  ])
                ]),
                _.value.auth_type === "password" ? (p(), h("label", V1, [
                  f[114] || (f[114] = A("SSH-пароль", -1)),
                  Ee(vt, {
                    modelValue: _.value.password,
                    "onUpdate:modelValue": f[51] || (f[51] = ($) => _.value.password = $),
                    autocomplete: "off",
                    placeholder: W.value.ssh_auth_type === "password" && W.value.ssh_configured ? "Оставьте пустым, чтобы сохранить текущий" : ""
                  }, null, 8, ["modelValue", "placeholder"])
                ])) : _.value.auth_type === "key" ? (p(), h("label", T1, [
                  f[115] || (f[115] = A("Путь к SSH-ключу", -1)),
                  F(n("input", {
                    "onUpdate:modelValue": f[52] || (f[52] = ($) => _.value.key_path = $),
                    placeholder: "/opt/bot4vps/keys/имя_ключа"
                  }, null, 512), [
                    [re, _.value.key_path]
                  ])
                ])) : V("", !0),
                n("div", E1, [
                  n("button", {
                    class: "gw-primary",
                    disabled: g.value
                  }, "Проверить и сохранить SSH", 8, U1)
                ])
              ], 32)
            ])
          ])) : V("", !0),
          I.value === "network" ? (p(), h(N, { key: 15 }, [
            C.value.length ? (p(), h("section", P1, [
              f[119] || (f[119] = n("h3", null, "WireGuard", -1)),
              (p(!0), h(N, null, se(C.value, ($) => (p(), h("div", {
                key: $.name,
                class: "gw-panel"
              }, [
                n("h3", null, w($.name), 1),
                $.peers.length ? V("", !0) : (p(), h("p", A1, "Пиры не настроены")),
                (p(!0), h(N, null, se($.peers, (ue, me) => (p(), h("div", {
                  key: me,
                  style: { "margin-top": "12px" }
                }, [
                  n("span", {
                    class: Ue(["gw-status", ue.recent_handshake ? "good" : "warn"])
                  }, w(ue.recent_handshake ? "Недавний handshake" : "Нет недавнего handshake"), 3),
                  n("p", null, w(ue.endpoint === "(none)" ? "Endpoint не определён" : ue.endpoint) + " · ↓ " + w(ve(ue.rx_bytes)) + " · ↑ " + w(ve(ue.tx_bytes)), 1)
                ]))), 128)),
                f[118] || (f[118] = n("p", { class: "gw-hint" }, "Handshake показывает обмен ключами за последние 3 минуты. Простаивающий туннель может не обмениваться пакетами.", -1))
              ]))), 128))
            ])) : V("", !0)
          ], 64)) : V("", !0)
        ])) : V("", !0)
      ], 64)),
      j.value ? (p(), ge(qe, {
        key: 6,
        title: "Удаление шлюза",
        busy: g.value,
        onClose: f[54] || (f[54] = ($) => j.value = null)
      }, {
        default: Re(() => [
          n("h2", null, "Удалить " + w(j.value.name) + "?", 1),
          n("ol", null, [
            (p(!0), h(N, null, se(j.value.steps, ($) => (p(), h("li", { key: $ }, w($), 1))), 128))
          ]),
          n("p", null, "Сохранятся: " + w(j.value.preserved.join(", ")) + ".", 1),
          j.value.manual ? (p(), h("p", I1, "Для вручную настроенного API может потребоваться отзыв учётной записи в LuCI. Без подтверждения отзыва панель сохранит запись.")) : V("", !0),
          n("div", M1, [
            n("button", {
              class: "gw-primary",
              disabled: g.value,
              onClick: Ti
            }, "Да, отозвать доступ и удалить", 8, O1),
            n("button", {
              disabled: g.value,
              onClick: f[53] || (f[53] = ($) => j.value = null)
            }, "Отмена", 8, R1)
          ])
        ]),
        _: 1
      }, 8, ["busy"])) : V("", !0),
      te.value ? (p(), ge(ph, {
        key: 7,
        operation: te.value,
        busy: g.value,
        error: m.value,
        onApply: yi,
        onCancel: bi
      }, null, 8, ["operation", "busy", "error"])) : V("", !0)
    ], 2));
  }
});
function N1(e, t, l = !1, o = null) {
  const s = iu(D1, { bridge: t, wizard: l, initialPlan: o });
  return s.mount(e), () => s.unmount();
}
export {
  N1 as mount
};
