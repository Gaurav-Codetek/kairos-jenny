// Jenny's camera: her video tile in the meeting, drawn on a 1280×720 canvas.
// At rest: her name and status, with a ring that moves with her voice. When she shows something: the scene itself
// (the same scene JSON as her Stage in Kairos), staged in — frame, then normal, then the values, then the focus,
// then the note — with what she names lit up as she says it.
(() => {
  const W = 1280;
  const H = 720;
  const SAFE = 0.74; // a scene's 720 rows drawn into the middle ~530: what survives Meet's crop of a wide tile
  // Kairos's light theme (frontend/app/globals.css): white surface, ink text, indigo brand.
  const C = {
    bg: "#FFFFFF", panel: "#F3F4F6", ink: "#1A1D24", ink2: "#4A4F59", muted: "#737780", hair: "#E4E6EA",
    brand: "#5148E0", deep: "#3F37C9", context: "#CFCCF7", band: "rgba(81,72,224,0.10)", warn: "#93650A",
    glow: "rgba(81,72,224,0.14)", note: "#E7E5FC",
  };
  // categorical, in fixed order (deep enough to read on white, distinct for colour-blind viewers); sequential = one hue
  const SERIES = ["#5148E0", "#C9501C", "#14805C", "#A86F00"];
  const OTHER = "#9A9EA6";
  const FONT = '"Segoe UI", "Helvetica Neue", Arial, sans-serif';
  const ease = (t) => 1 - Math.pow(1 - Math.max(0, Math.min(1, t)), 3);
  const now = () => performance.now() / 1000;

  let g = null;
  let src = {};
  let scene = null;
  let sceneAt = 0;
  let status = "listening";
  let spokeAt = 0;
  let lit = null; // keys lit by her words

  function attach(canvas, sources) {
    g = canvas.getContext("2d");
    src = sources;
    setInterval(frame, 40);
  }

  function text(t, x, y, size, color, weight = 400, align = "left", maxW) {
    g.font = `${weight} ${size}px ${FONT}`;
    g.fillStyle = color;
    g.textAlign = align;
    g.textBaseline = "alphabetic";
    let s = String(t ?? "");
    if (maxW) while (s.length > 1 && g.measureText(s).width > maxW) s = s.slice(0, -2) + "…";
    g.fillText(s, x, y);
    return g.measureText(s).width;
  }
  function rrect(x, y, w, h, r) {
    g.beginPath();
    g.roundRect ? g.roundRect(x, y, w, h, r) : g.rect(x, y, w, h);
  }
  const fmt = (v) =>
    Math.abs(v) >= 1e5 ? `${(v / 1e5).toFixed(1)}L` : Math.abs(v) >= 1000 ? Math.round(v).toLocaleString() : `${+(+v).toFixed(2)}`;

  // ── her, at rest ──
  function avatar(cx, cy, r, level) {
    if (level > 0.02) {
      g.beginPath();
      g.arc(cx, cy, r + 10 + level * 26, 0, Math.PI * 2);
      g.fillStyle = C.glow;
      g.fill();
    }
    const grad = g.createLinearGradient(cx - r, cy - r, cx + r, cy + r);
    grad.addColorStop(0, C.brand);
    grad.addColorStop(1, C.deep);
    g.beginPath();
    g.arc(cx, cy, r, 0, Math.PI * 2);
    g.fillStyle = grad;
    g.fill();
    text("J", cx, cy + r * 0.36, r * 1.05, "#fff", 700, "center");
  }

  const STATUS = { listening: "Listening", thinking: "Looking into it", speaking: "Speaking" };

  function idle(level) {
    avatar(W / 2, 290, 112, level);
    text("Jenny", W / 2, 470, 58, C.ink, 700, "center");
    text("Kairos AI assistant", W / 2, 512, 26, C.muted, 400, "center");
    const label = level > 0.02 ? STATUS.speaking : STATUS[status] || status;
    g.font = `500 22px ${FONT}`;
    const w = g.measureText(label).width + 44;
    rrect(W / 2 - w / 2, 548, w, 40, 20);
    g.fillStyle = C.panel;
    g.fill();
    g.beginPath();
    g.arc(W / 2 - w / 2 + 20, 568, 5, 0, Math.PI * 2);
    g.fillStyle = status === "thinking" ? C.warn : C.brand;
    g.fill();
    text(label, W / 2 + 6, 576, 22, C.ink2, 500, "center");
  }

  function badge(level) {
    avatar(1214, 560, 30, level);
    text("Jenny", 1170, 568, 22, C.ink2, 600, "right");
  }

  // ── scenes ──
  function header(s, t) {
    g.globalAlpha = ease(t / 0.25);
    text(s.title, 60, 82, 38, C.ink, 700, "left", 1100);
    text(s.subtitle || "", 60, 118, 22, C.muted, 400, "left", 1100);
    g.globalAlpha = 1;
  }

  function focusKeys(s) {
    return lit && lit.length ? new Set(lit) : new Set(s.focus || []);
  }

  function note(s, key, x, y, t) {
    const a = (s.annotations || []).find((n) => n.key === key || n.key == null);
    if (!a || t < 1.15) return;
    g.globalAlpha = ease((t - 1.15) / 0.3);
    g.font = `600 20px ${FONT}`;
    const w = g.measureText(a.text).width + 28;
    rrect(x, y - 24, w, 34, 17);
    g.fillStyle = C.note;
    g.fill();
    text(a.text, x + 14, y - 1, 20, C.ink, 600);
    g.globalAlpha = 1;
  }

  function hatch(x, y, w, h, color = C.context) {
    g.save();
    rrect(x, y, w, h, 4);
    g.clip();
    g.strokeStyle = color;
    g.lineWidth = 3;
    for (let i = -h; i < w; i += 9) {
      g.beginPath();
      g.moveTo(x + i, y + h);
      g.lineTo(x + i + h, y);
      g.stroke();
    }
    g.restore();
  }

  function breakdown(s, t) {
    const rows = (s.data.rows || []).slice(0, 7); // Meet crops a tile's edges: seven rows stay clear of them
    const max = Math.max(...rows.map((r) => Math.max(r.value || 0, r.usual || 0)), 1e-9) * 1.1;
    const on = focusKeys(s);
    const any = on.size > 0;
    const top = 160;
    const rowH = Math.min(62, 480 / Math.max(rows.length, 1));
    const x0 = 330;
    const span = 560;
    rows.forEach((r, i) => {
      const y = top + i * rowH;
      const hot = !any || on.has(r.key);
      g.globalAlpha = ease(t / 0.25);
      text(r.label, 60, y + rowH * 0.62, 24, hot ? C.ink : C.muted, hot ? 600 : 400, "left", 250);
      g.globalAlpha = 1;
      const w = span * ((r.value || 0) / max) * ease((t - 0.4 - i * 0.05) / 0.55);
      const by = y + rowH * 0.22;
      const bh = rowH * 0.56;
      if (r.low_volume) hatch(x0, by, Math.max(w, 2), bh);
      else {
        rrect(x0, by, Math.max(w, 2), bh, 4);
        g.fillStyle = hot ? C.brand : C.context;
        g.fill();
      }
      if (r.usual != null && t > 0.2) {
        const ux = x0 + span * (r.usual / max);
        g.globalAlpha = ease((t - 0.2) / 0.25) * (hot ? 1 : 0.45);
        g.fillStyle = C.ink;
        g.fillRect(ux - 1.5, y + rowH * 0.12, 3, rowH * 0.76);
        g.globalAlpha = 1;
      }
      if (t > 0.6) {
        g.globalAlpha = ease((t - 0.6) / 0.3);
        // the value sits past the bar — and past its usual mark when the bar falls short of it
        const vx = Math.max(x0 + w, r.usual != null ? x0 + span * (r.usual / max) : 0) + 16;
        const vw = text(r.display || fmt(r.value), vx, y + rowH * 0.62, 24, hot ? C.ink : C.muted, 600);
        if (r.usual_display) text(`usual ${r.usual_display}`, vx + vw + 12, y + rowH * 0.62, 18, C.muted, 400);
        g.globalAlpha = 1;
        if (hot && any) note(s, r.key, vx + vw + (r.usual_display ? 150 : 16), y + rowH * 0.62, t);
      }
    });
  }

  function hours(s, t) {
    const rows = (s.data.rows || []).slice(0, 24);
    const max = Math.max(...rows.map((r) => Math.max(r.value || 0, r.high || 0, r.usual || 0)), 1e-9) * 1.12;
    const on = focusKeys(s);
    const any = on.size > 0;
    const x0 = 60;
    const x1 = 1220;
    const y0 = 170;
    const y1 = 620;
    const step = (x1 - x0) / Math.max(rows.length, 1);
    const y = (v) => y1 - (y1 - y0) * (v / max);
    rows.forEach((r, i) => {
      const hot = !any || on.has(r.key);
      const cx = x0 + step * i + step / 2;
      const bw = Math.min(56, step * 0.6);
      if (r.low != null && r.high != null && t > 0.2) {
        g.globalAlpha = ease((t - 0.2) / 0.25);
        g.fillStyle = C.band;
        g.fillRect(cx - bw * 0.8, y(r.high), bw * 1.6, y(r.low) - y(r.high));
        g.globalAlpha = 1;
      }
      const v = (r.value || 0) * ease((t - 0.4 - i * 0.04) / 0.55);
      rrect(cx - bw / 2, y(v), bw, y1 - y(v), 4);
      g.fillStyle = hot ? C.brand : C.context;
      g.fill();
      if (r.usual != null && t > 0.2) {
        g.fillStyle = C.ink;
        g.globalAlpha = hot ? 0.9 : 0.4;
        g.fillRect(cx - bw * 0.75, y(r.usual) - 1.5, bw * 1.5, 3);
        g.globalAlpha = 1;
      }
      text(r.label, cx, y1 + 30, 18, hot ? C.ink2 : C.muted, hot ? 600 : 400, "center");
      if (hot && any && t > 0.95) {
        text(r.display || fmt(r.value), cx, y(Math.max(r.value || 0, r.high || 0)) - 12, 22, C.ink, 700, "center");
        note(s, r.key, Math.min(cx + bw, 980), y0 - 6, t);
      }
    });
  }

  function trend(s, t) {
    const typ = s.data.typical || [];
    const today = s.data.today || [];
    if (typ.length < 2) return;
    const x0 = 60;
    const x1 = 1100;
    const y0 = 160;
    const y1 = 620;
    const hi = Math.max(...typ.map((p) => Math.max(p[1], p[3])), ...today.map((p) => p[1]), 1e-9) * 1.08;
    const X = (h) => x0 + (x1 - x0) * (h / 24);
    const Y = (v) => y1 - (y1 - y0) * (v / hi);
    [0, 6, 12, 18, 24].forEach((h) => {
      g.fillStyle = C.hair;
      g.fillRect(X(h), y0, 1, y1 - y0);
      text(["12 am", "6 am", "noon", "6 pm", "12 am"][h / 6], X(h), y1 + 30, 18, C.muted, 400, "center");
    });
    if (t > 0.2) {
      g.globalAlpha = ease((t - 0.2) / 0.3);
      g.beginPath();
      typ.forEach((p, i) => (i ? g.lineTo(X(p[0]), Y(p[3])) : g.moveTo(X(p[0]), Y(p[3]))));
      [...typ].reverse().forEach((p) => g.lineTo(X(p[0]), Y(p[2])));
      g.closePath();
      g.fillStyle = C.band;
      g.fill();
      g.setLineDash([8, 8]);
      g.beginPath();
      typ.forEach((p, i) => (i ? g.lineTo(X(p[0]), Y(p[1])) : g.moveTo(X(p[0]), Y(p[1]))));
      g.strokeStyle = C.muted;
      g.lineWidth = 2;
      g.stroke();
      g.setLineDash([]);
      g.globalAlpha = 1;
    }
    const frac = ease((t - 0.4) / 0.9);
    const n = Math.max(1, Math.floor(today.length * frac));
    g.beginPath();
    today.slice(0, n).forEach((p, i) => (i ? g.lineTo(X(p[0]), Y(p[1])) : g.moveTo(X(p[0]), Y(p[1]))));
    g.strokeStyle = C.brand;
    g.lineWidth = 4;
    g.lineJoin = "round";
    g.stroke();
    if (frac >= 1 && today.length) {
      const p = today[today.length - 1];
      g.beginPath();
      g.arc(X(p[0]), Y(p[1]), 8, 0, Math.PI * 2);
      g.fillStyle = C.brand;
      g.fill();
      text(s.data.actual_display || "", X(p[0]) + 16, Y(p[1]) + 8, 26, C.ink, 700);
      if (s.data.expected_display) text(`usual ${s.data.expected_display}`, X(p[0]) + 16, Y(p[1]) + 36, 18, C.muted);
    }
  }

  const short = (v) =>
    v == null ? "–" : Math.abs(v) >= 1e5 ? `${(v / 1e5).toFixed(1)}L` : Math.abs(v) >= 1000 ? Math.round(v).toLocaleString()
      : Math.abs(v) >= 10 ? `${Math.round(v)}`
        : Math.abs(v) < 1 && v !== 0 ? `${(v * 100).toFixed(1)}%` : `${+(+v).toFixed(2)}`;

  // label positions pushed apart so none overlaps (keeps their order)
  function spread(ys, gap) {
    const order = ys.map((y, i) => [y, i]).filter((d) => d[0] != null).sort((a, b) => a[0] - b[0]);
    for (let k = 1; k < order.length; k++) order[k][0] = Math.max(order[k][0], order[k - 1][0] + gap);
    const out = ys.slice();
    order.forEach(([y, i]) => (out[i] = y));
    return out;
  }

  function legend(items, x, y) {
    let at = x;
    items.forEach((it) => {
      g.globalAlpha = it.dim ? 0.4 : 1;
      g.fillStyle = it.color;
      g.fillRect(at, y - 8, 22, 5);
      at += 30 + text(it.label, at + 30, y, 18, C.ink2, 500) + 26;
    });
    g.globalAlpha = 1;
  }

  // change over time: a line per category over days (a panel per metric, each with its own axis)
  function series(s, t) {
    const xs = s.data.x || [];
    const labels = s.data.x_labels || xs;
    const panels = (s.data.panels || []).slice(0, 2);
    if (!xs.length || !panels.length) return;
    const on = focusKeys(s);
    const litLines = new Set(panels[0].lines.map((l) => l.key).filter((k) => on.has(k)));
    const litX = xs.findIndex((x) => on.has(`x:${x}`));
    const x0 = 120;
    const x1 = 1040;
    const X = (i) => x0 + (x1 - x0) * (xs.length > 1 ? i / (xs.length - 1) : 0.5);
    legend(panels[0].lines.map((l, i) => ({ label: l.label, color: SERIES[i % 4], dim: litLines.size && !litLines.has(l.key) })), 60, 158);
    const top = 190;
    const ph = (600 - top) / panels.length;
    panels.forEach((p, pi) => {
      const y0 = top + pi * ph + (panels.length > 1 ? 28 : 6);
      const y1 = top + (pi + 1) * ph - 10;
      if (panels.length > 1) text(p.metric_label, 60, y0 - 8, 18, C.muted, 600);
      const vals = p.lines.flatMap((l) => l.values.filter((v) => v != null));
      const hi = Math.max(...vals, 1e-9) * 1.1;
      const Y = (v) => y1 - (y1 - y0) * (v / hi);
      [0, 0.5, 1].forEach((f) => {
        g.fillStyle = C.hair;
        g.fillRect(x0, Y(hi * f), x1 - x0, 1);
        text(short(hi * f), x0 - 12, Y(hi * f) + 6, 16, C.muted, 400, "right");
      });
      if (litX >= 0) {
        g.fillStyle = C.band;
        g.fillRect(X(litX) - 22, y0, 44, y1 - y0);
      }
      const frac = ease((t - 0.4) / 0.9);
      const ends = spread(p.lines.map((ln) => {
        const last = ln.values.reduce((a, v, i) => (v != null ? i : a), -1);
        return last < 0 ? null : Y(ln.values[last]) + 7;
      }), 24);
      p.lines.forEach((ln, li) => {
        const pts = ln.values.map((v, i) => [i, v]).filter((d) => d[1] != null);
        if (!pts.length) return;
        const hot = !litLines.size || litLines.has(ln.key);
        g.globalAlpha = hot ? 1 : 0.25;
        const n = Math.max(1, Math.ceil(pts.length * frac));
        g.beginPath();
        pts.slice(0, n).forEach(([i, v], k) => (k ? g.lineTo(X(i), Y(v)) : g.moveTo(X(i), Y(v))));
        g.strokeStyle = SERIES[li % 4];
        g.lineWidth = hot && litLines.size ? 5 : 3.5;
        g.lineJoin = "round";
        g.stroke();
        pts.slice(0, n).forEach(([i, v]) => {
          g.beginPath();
          g.arc(X(i), Y(v), i === litX ? 8 : 5, 0, Math.PI * 2);
          g.fillStyle = SERIES[li % 4];
          g.fill();
        });
        if (frac >= 1) {
          const [li2, lv] = pts[pts.length - 1];
          text(ln.label, X(li2) + 14, ends[li] ?? Y(lv) + 7, 19, C.ink, 600, "left", 200);
          if (litX >= 0 && ln.values[litX] != null && hot)
            text(short(ln.values[litX]), X(litX), Y(ln.values[litX]) - 14, 20, C.ink, 700, "center");
        }
        g.globalAlpha = 1;
      });
      if (pi === panels.length - 1) {
        const step = labels.length > 8 ? Math.ceil(labels.length / 7) : 1;
        labels.forEach((l, i) => {
          if (i % step && i !== labels.length - 1) return;
          text(l, X(i), y1 + 30, 17, i === litX ? C.ink : C.muted, i === litX ? 700 : 400, "center");
        });
      }
    });
  }

  // a pattern in a grid: one hue, light (less) to deep indigo (more); hatched where nothing was recorded
  function heat(v) {
    const a = [238, 240, 253];
    const b = [63, 55, 201];
    return `rgb(${a.map((c, i) => Math.round(c + (b[i] - c) * v)).join(",")})`;
  }

  function heatmap(s, t) {
    const rows = (s.data.rows || []).slice(0, 10);
    const cols = s.data.cols || [];
    const cells = s.data.cells || [];
    if (!rows.length || !cols.length) return;
    const lo = s.data.min ?? 0;
    const hi = s.data.max ?? 1;
    const on = focusKeys(s);
    const x0 = 240;
    const x1 = 1220;
    const y0 = 180;
    const cw = (x1 - x0) / cols.length;
    const ch = Math.min(52, (600 - y0) / rows.length);
    const every = cols.length > 12 ? 3 : 1;
    cols.forEach((c, j) => {
      if (j % every) return;
      text(c.label, x0 + cw * j + cw / 2, y0 - 10, 15, on.has(c.key) ? C.ink : C.muted, on.has(c.key) ? 700 : 400, "center");
    });
    rows.forEach((r, i) => {
      const y = y0 + i * ch;
      text(r.label, x0 - 14, y + ch * 0.62, 19, on.has(r.key) ? C.ink : C.ink2, on.has(r.key) ? 700 : 400, "right", 170);
      cols.forEach((c, j) => {
        const k = ease((t - 0.4 - (i * cols.length + j) * 0.003) / 0.3);
        if (k <= 0) return;
        const v = (cells[i] || [])[j];
        const hot = !on.size || on.has(r.key) || on.has(c.key);
        g.globalAlpha = k * (hot ? 1 : 0.3);
        const x = x0 + cw * j + 1;
        if (v == null) hatch(x, y + 1, cw - 2, ch - 2);
        else {
          rrect(x, y + 1, cw - 2, ch - 2, 3);
          g.fillStyle = heat(hi > lo ? (v - lo) / (hi - lo) : 0.5);
          g.fill();
        }
        if (on.has(r.key) && on.has(c.key)) {
          g.strokeStyle = C.ink;
          g.lineWidth = 3;
          rrect(x, y + 1, cw - 2, ch - 2, 3);
          g.stroke();
        }
        g.globalAlpha = 1;
      });
    });
    const ly = y0 + rows.length * ch + 34;
    text("less", x0, ly, 16, C.muted);
    for (let i = 0; i < 20; i++) {
      g.fillStyle = heat(i / 19);
      g.fillRect(x0 + 44 + i * 8, ly - 12, 8, 14);
    }
    text("more", x0 + 214, ly, 16, C.muted);
  }

  // two measures per slice
  function scatter(s, t) {
    const pts = (s.data.points || []).slice(0, 40);
    if (!pts.length) return;
    const on = focusKeys(s);
    const x0 = 140;
    const x1 = 1040;
    const y0 = 170;
    const y1 = 580;
    const xh = Math.max(...pts.map((p) => p.x), 1e-9) * 1.08;
    const yl = Math.min(0, ...pts.map((p) => p.y));
    const yh = Math.max(...pts.map((p) => p.y), 1e-9) * 1.12;
    const X = (v) => x0 + (x1 - x0) * (v / xh);
    const Y = (v) => y1 - (y1 - y0) * ((v - yl) / (yh - yl));
    [0, 0.5, 1].forEach((f) => {
      g.fillStyle = C.hair;
      g.fillRect(x0, Y(yl + (yh - yl) * f), x1 - x0, 1);
      g.fillRect(X(xh * f), y0, 1, y1 - y0);
      text(short(yl + (yh - yl) * f), x0 - 12, Y(yl + (yh - yl) * f) + 6, 16, C.muted, 400, "right");
      text(short(xh * f), X(xh * f), y1 + 26, 16, C.muted, 400, "center");
    });
    text(`${s.data.x_label || ""} →`, x1, y1 + 54, 18, C.ink2, 500, "right");
    text(`↑ ${s.data.y_label || ""}`, x0, y0 - 14, 18, C.ink2, 500);
    const big = new Set([...pts].sort((a, b) => b.x - a.x).slice(0, 4).map((p) => p.key));
    pts.forEach((p, i) => {
      const k = ease((t - 0.4 - i * 0.02) / 0.3);
      if (k <= 0) return;
      const hot = !on.size || on.has(p.key);
      g.globalAlpha = k * (hot ? 1 : 0.3);
      g.beginPath();
      g.arc(X(p.x), Y(p.y), (on.has(p.key) ? 13 : 9) * k, 0, Math.PI * 2);
      g.fillStyle = SERIES[0];
      g.fill();
      g.strokeStyle = C.bg;
      g.lineWidth = 2;
      g.stroke();
      if (on.has(p.key) || (!on.size && big.has(p.key)))
        text(p.label, X(p.x) + 18, Y(p.y) + 7, 19, C.ink, on.has(p.key) ? 700 : 500);
      g.globalAlpha = 1;
    });
  }

  // above or below its usual, either side of zero
  function deviation(s, t) {
    const rows = (s.data.rows || []).slice(0, 8);
    if (!rows.length) return;
    const lim = Math.max(...rows.map((r) => Math.abs(r.pct || 0)), 1) * 1.1;
    const on = focusKeys(s);
    const mid = 720;
    const half = 380;
    const top = 190;
    const rowH = Math.min(56, 420 / rows.length);
    g.fillStyle = SERIES[1];
    g.fillRect(60, 152, 18, 10);
    const lw = text("below its usual", 86, 162, 17, C.ink2);
    g.fillStyle = SERIES[0];
    g.fillRect(86 + lw + 26, 152, 18, 10);
    text("above its usual", 86 + lw + 52, 162, 17, C.ink2);
    g.fillStyle = C.muted;
    g.fillRect(mid, top - 8, 2, rows.length * rowH + 8);
    rows.forEach((r, i) => {
      const y = top + i * rowH;
      const pct = r.pct || 0;
      const hot = !on.size || on.has(r.key);
      g.globalAlpha = hot ? 1 : 0.35;
      text(r.label, 60, y + rowH * 0.62, 22, hot ? C.ink : C.muted, on.has(r.key) ? 700 : 400, "left", 260);
      const w = half * (Math.abs(pct) / lim) * ease((t - 0.4 - i * 0.05) / 0.5);
      const bx = pct >= 0 ? mid + 2 : mid - w;
      const by = y + rowH * 0.2;
      const bh = rowH * 0.6;
      if (r.low_volume) hatch(bx, by, Math.max(w, 2), bh, pct >= 0 ? SERIES[0] : SERIES[1]);
      else {
        rrect(bx, by, Math.max(w, 2), bh, 4);
        g.fillStyle = pct >= 0 ? SERIES[0] : SERIES[1];
        g.fill();
      }
      if (t > 0.9) text(`${pct > 0 ? "+" : ""}${pct.toFixed(1)}%`, pct >= 0 ? mid + w + 14 : mid - w - 14, y + rowH * 0.62, 21, C.ink, 700, pct >= 0 ? "left" : "right");
      g.globalAlpha = 1;
      if (on.has(r.key)) note(s, r.key, 900, y + rowH * 0.62, t);
    });
  }

  // part of the whole: one 100% bar
  function share(s, t) {
    const parts = s.data.parts || [];
    if (!parts.length) return;
    const on = focusKeys(s);
    const x0 = 60;
    const span = 1160;
    const color = (p, i) => (p.key === "Other" ? OTHER : SERIES[i % 4]);
    let at = x0;
    const k = ease((t - 0.4) / 0.8);
    parts.forEach((p, i) => {
      const w = span * p.share * k;
      g.globalAlpha = !on.size || on.has(p.key) ? 1 : 0.3;
      g.fillStyle = color(p, i);
      g.fillRect(at, 200, Math.max(w - 3, 0), 90);
      if (w > 90 && k >= 1) text(`${(p.share * 100).toFixed(0)}%`, at + 16, 256, 26, p.key === "Other" ? C.ink : "#FFFFFF", 700);
      at += w;
      g.globalAlpha = 1;
    });
    if (t < 0.9) return;
    g.globalAlpha = ease((t - 0.9) / 0.3);
    parts.forEach((p, i) => {
      const col = i % 2;
      const y = 360 + Math.floor(i / 2) * 64;
      const x = x0 + col * 600;
      const dim = on.size && !on.has(p.key);
      g.globalAlpha *= dim ? 0.4 : 1;
      rrect(x, y - 20, 22, 22, 4);
      g.fillStyle = color(p, i);
      g.fill();
      text(p.label, x + 36, y - 2, 23, on.has(p.key) ? C.ink : C.ink2, on.has(p.key) ? 700 : 500, "left", 300);
      text(`${(p.share * 100).toFixed(1)}%`, x + 430, y - 2, 23, C.ink, 700, "right");
      text(short(p.value), x + 540, y - 2, 18, C.muted, 400, "right");
      g.globalAlpha = ease((t - 0.9) / 0.3);
    });
    g.globalAlpha = 1;
  }

  function figure(label, display, usual, st, x, y, t) {
    g.globalAlpha = ease((t - 0.3) / 0.4);
    if (label) text(label, x, y - 150, 24, C.muted, 500, "left", 540);
    text(display || "", x, y, 128, C.ink, 700, "left", 560);
    const words = { above: "above normal", below: "below normal", normal: "within normal" }[st] || "";
    if (words) text(words, x, y + 56, 26, st === "normal" ? C.ink2 : C.warn, 600);
    if (usual) text(`usual by now ${usual}`, x, y + 96, 24, C.muted);
    g.globalAlpha = 1;
  }

  function draw(s, t) {
    header(s, t);
    if (s.kind === "breakdown") breakdown(s, t);
    else if (s.kind === "hours") hours(s, t);
    else if (s.kind === "trend") trend(s, t);
    else if (s.kind === "series") series(s, t);
    else if (s.kind === "heatmap") heatmap(s, t);
    else if (s.kind === "scatter") scatter(s, t);
    else if (s.kind === "deviation") deviation(s, t);
    else if (s.kind === "share") share(s, t);
    else if (s.kind === "number") figure("", s.data.display, s.data.usual_display, s.data.status, 60, 400, t);
    else if (s.kind === "compare")
      (s.data.items || []).slice(0, 2).forEach((it, i) => figure(it.label, it.display, it.usual_display, it.status, 60 + i * 600, 420, t));
  }

  // ── each frame ──
  function frame() {
    if (!g) return;
    const level = src.level ? src.level() : 0;
    const p = src.progress ? src.progress() : null;
    if (p) {
      spokeAt = now();
      if (scene && window.__jennyCues) {
        const f = window.__jennyCues.focusAt(p.text, p.p, scene.entities || []);
        if (f) lit = f;
      }
    }
    g.fillStyle = C.bg;
    g.fillRect(0, 0, W, H);
    const fresh = scene && (now() - sceneAt < 90 || now() - spokeAt < 30);
    if (fresh) {
      // Meet fills a wide stage tile by cropping the top and bottom of her video (on a 2.7:1 stage only rows ~120–600
      // show), which cut off the title and axes and blew up the middle. So the scene is drawn smaller, centred in that
      // band: whole on a wide stage, with white margins on a 16:9 tile.
      g.save();
      g.translate(W / 2, H / 2);
      g.scale(SAFE, SAFE);
      g.translate(-W / 2, -H / 2);
      draw(scene, now() - sceneAt);
      g.restore();
      badge(level);
    } else {
      idle(level);
    }
  }

  window.__jennyCamera = {
    attach,
    scene(s) {
      scene = s;
      sceneAt = now();
      lit = null;
    },
    status(s) {
      status = s;
    },
  };
})();
