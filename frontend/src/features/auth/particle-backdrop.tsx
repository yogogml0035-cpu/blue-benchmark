"use client";

import { useEffect, useRef } from "react";
import styles from "./particle-backdrop.module.css";

/**
 * Living recreation of the approved prototype artwork: four nested ribbons of
 * dust (electric blue / gold / green / white, outermost first) sweep from the
 * lower left up across the top-left of the auth surface, leaving the right
 * third dark for the panel. Ribbons are modeled as Catmull-Rom splines through
 * control points measured from the prototype PNG this component replaces.
 *
 * Rendering is split for performance: a static dust layer (~24k particles,
 * deterministic seed) is painted once per resize onto an offscreen canvas;
 * every frame the visible canvas replays that layer under ~2.3k live
 * particles that drift along their ribbon and twinkle. `prefers-reduced-motion`
 * paints a single static frame and never starts the RAF loop; the loop also
 * pauses while the tab is hidden.
 */

type Rgb = readonly [number, number, number];
type Vec2 = { readonly x: number; readonly y: number };

interface BandSpec {
  /** Fractional control points (x/width, y/height) measured from the prototype. */
  points: readonly Vec2[];
  /** Normal scatter at the crest, as a fraction of canvas height. */
  sigma: number;
  /** Dust / live particle counts at the 1918x1064 reference area. */
  dust: number;
  live: number;
  /** Color stops along normalized arc length. */
  stops: readonly { at: number; rgb: Rgb }[];
}

const REFERENCE_AREA = 1918 * 1064;

const BANDS: readonly BandSpec[] = [
  {
    // Outer electric-blue ribbon: the widest sweep, crest near the top edge.
    points: [
      { x: -0.08, y: 0.74 },
      { x: 0.02, y: 0.54 },
      { x: 0.13, y: 0.37 },
      { x: 0.25, y: 0.23 },
      { x: 0.36, y: 0.13 },
      { x: 0.44, y: 0.075 },
      { x: 0.485, y: 0.055 },
      { x: 0.52, y: 0.075 },
      { x: 0.545, y: 0.13 },
      { x: 0.55, y: 0.22 },
      { x: 0.53, y: 0.34 },
      { x: 0.495, y: 0.47 },
      { x: 0.462, y: 0.58 },
      { x: 0.44, y: 0.68 },
      { x: 0.425, y: 0.77 },
    ],
    sigma: 0.034,
    dust: 7200,
    live: 640,
    stops: [
      { at: 0, rgb: [28, 88, 220] },
      { at: 0.3, rgb: [40, 130, 250] },
      { at: 0.5, rgb: [64, 185, 255] },
      { at: 0.72, rgb: [42, 145, 250] },
      { at: 1, rgb: [26, 98, 215] },
    ],
  },
  {
    // Gold ribbon, nested inside the blue one.
    points: [
      { x: -0.06, y: 0.88 },
      { x: 0.02, y: 0.72 },
      { x: 0.1, y: 0.585 },
      { x: 0.18, y: 0.475 },
      { x: 0.25, y: 0.4 },
      { x: 0.3, y: 0.365 },
      { x: 0.335, y: 0.36 },
      { x: 0.36, y: 0.385 },
      { x: 0.375, y: 0.44 },
      { x: 0.385, y: 0.52 },
      { x: 0.375, y: 0.62 },
      { x: 0.355, y: 0.74 },
      { x: 0.325, y: 0.87 },
      { x: 0.3, y: 1.0 },
    ],
    sigma: 0.036,
    dust: 6400,
    live: 600,
    stops: [
      { at: 0, rgb: [204, 120, 22] },
      { at: 0.32, rgb: [248, 168, 32] },
      { at: 0.52, rgb: [255, 208, 74] },
      { at: 0.75, rgb: [248, 162, 28] },
      { at: 1, rgb: [214, 126, 24] },
    ],
  },
  {
    // Green ribbon; the prototype fades it toward the bottom edge.
    points: [
      { x: -0.04, y: 1.0 },
      { x: 0.03, y: 0.84 },
      { x: 0.1, y: 0.68 },
      { x: 0.16, y: 0.545 },
      { x: 0.21, y: 0.45 },
      { x: 0.245, y: 0.395 },
      { x: 0.265, y: 0.375 },
      { x: 0.285, y: 0.4 },
      { x: 0.29, y: 0.47 },
      { x: 0.285, y: 0.57 },
      { x: 0.27, y: 0.68 },
      { x: 0.25, y: 0.8 },
      { x: 0.23, y: 0.92 },
      { x: 0.215, y: 1.0 },
    ],
    sigma: 0.038,
    dust: 4900,
    live: 520,
    stops: [
      { at: 0, rgb: [16, 150, 116] },
      { at: 0.35, rgb: [22, 200, 150] },
      { at: 0.55, rgb: [62, 222, 168] },
      { at: 0.8, rgb: [24, 172, 128] },
      { at: 1, rgb: [16, 140, 108] },
    ],
  },
  {
    // Innermost white-hot ribbon: the visual anchor of the composition.
    points: [
      { x: 0.02, y: 1.0 },
      { x: 0.08, y: 0.87 },
      { x: 0.13, y: 0.76 },
      { x: 0.175, y: 0.675 },
      { x: 0.22, y: 0.615 },
      { x: 0.255, y: 0.59 },
      { x: 0.28, y: 0.585 },
      { x: 0.3, y: 0.6 },
      { x: 0.31, y: 0.645 },
      { x: 0.31, y: 0.71 },
      { x: 0.3, y: 0.79 },
      { x: 0.285, y: 0.88 },
      { x: 0.27, y: 0.97 },
    ],
    sigma: 0.042,
    dust: 4700,
    live: 560,
    stops: [
      { at: 0, rgb: [178, 222, 202] },
      { at: 0.35, rgb: [226, 242, 236] },
      { at: 0.55, rgb: [248, 252, 255] },
      { at: 0.8, rgb: [230, 244, 242] },
      { at: 1, rgb: [180, 220, 202] },
    ],
  },
];

/** mulberry32 — small, fast, seedable PRNG so every load paints the same sky. */
function createRandom(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6d2b79f5) | 0;
    let t = Math.imul(state ^ (state >>> 15), 1 | state);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function gaussian(random: () => number): number {
  const a = Math.max(random(), 1e-9);
  const b = random();
  return Math.sqrt(-2 * Math.log(a)) * Math.cos(2 * Math.PI * b);
}

function clamp01(value: number): number {
  return value < 0 ? 0 : value > 1 ? 1 : value;
}

function smoothstep(edge0: number, edge1: number, value: number): number {
  const u = clamp01((value - edge0) / (edge1 - edge0));
  return u * u * (3 - 2 * u);
}

function mixRgb(a: Rgb, b: Rgb, k: number): Rgb {
  return [a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k, a[2] + (b[2] - a[2]) * k];
}

function rgba(rgb: Rgb, alpha: number): string {
  return `rgba(${Math.round(rgb[0])},${Math.round(rgb[1])},${Math.round(rgb[2])},${alpha.toFixed(3)})`;
}

/** Band color at normalized arc length t. */
function colorAt(stops: BandSpec["stops"], t: number): Rgb {
  for (let i = 1; i < stops.length; i += 1) {
    if (t <= stops[i].at) {
      const span = stops[i].at - stops[i - 1].at;
      const k = span <= 0 ? 0 : (t - stops[i - 1].at) / span;
      return mixRgb(stops[i - 1].rgb, stops[i].rgb, k);
    }
  }
  return stops[stops.length - 1].rgb;
}

/** Arc-length parameterized Catmull-Rom spline through fractional points. */
class Ribbon {
  /** Flat LUT: x, y, nx, ny per sample. */
  private readonly lut: Float32Array;
  private readonly cumulative: Float32Array;
  private readonly count: number;
  private readonly total: number;

  constructor(points: readonly Vec2[], width: number, height: number) {
    const samplesPerSegment = 24;
    const pts: Vec2[] = [points[0], ...points, points[points.length - 1]];
    const sampled: number[] = [];
    for (let i = 0; i < points.length - 1; i += 1) {
      const p0 = pts[i];
      const p1 = pts[i + 1];
      const p2 = pts[i + 2];
      const p3 = pts[i + 3];
      for (let s = 0; s < samplesPerSegment; s += 1) {
        const u = s / samplesPerSegment;
        const u2 = u * u;
        const u3 = u2 * u;
        const x = 0.5 * (2 * p1.x + (-p0.x + p2.x) * u + (2 * p0.x - 5 * p1.x + 4 * p2.x - p3.x) * u2 + (-p0.x + 3 * p1.x - 3 * p2.x + p3.x) * u3);
        const y = 0.5 * (2 * p1.y + (-p0.y + p2.y) * u + (2 * p0.y - 5 * p1.y + 4 * p2.y - p3.y) * u2 + (-p0.y + 3 * p1.y - 3 * p2.y + p3.y) * u3);
        sampled.push(x * width, y * height);
      }
    }
    const last = points[points.length - 1];
    sampled.push(last.x * width, last.y * height);

    this.count = sampled.length / 2;
    this.lut = new Float32Array(this.count * 4);
    this.cumulative = new Float32Array(this.count);
    let distance = 0;
    for (let i = 0; i < this.count; i += 1) {
      const x = sampled[i * 2];
      const y = sampled[i * 2 + 1];
      if (i > 0) {
        distance += Math.hypot(x - sampled[i * 2 - 2], y - sampled[i * 2 - 1]);
      }
      this.cumulative[i] = distance;
      this.lut[i * 4] = x;
      this.lut[i * 4 + 1] = y;
    }
    this.total = distance;
    for (let i = 0; i < this.count; i += 1) {
      const prev = Math.max(i - 1, 0);
      const next = Math.min(i + 1, this.count - 1);
      const tx = this.lut[next * 4] - this.lut[prev * 4];
      const ty = this.lut[next * 4 + 1] - this.lut[prev * 4 + 1];
      const len = Math.hypot(tx, ty) || 1;
      this.lut[i * 4 + 2] = -ty / len;
      this.lut[i * 4 + 3] = tx / len;
    }
  }

  /** Highest point of the ribbon (minimum y), as normalized arc length. */
  crestT(): number {
    let best = 0;
    for (let i = 1; i < this.count; i += 1) {
      if (this.lut[i * 4 + 1] < this.lut[best * 4 + 1]) best = i;
    }
    return this.cumulative[best] / this.total;
  }

  /** Number of LUT samples. */
  sampleCount(): number {
    return this.count;
  }

  /** Normalized arc length at LUT sample `index`. */
  tAt(index: number): number {
    const i = Math.min(Math.max(index, 0), this.count - 1);
    return this.cumulative[i] / this.total;
  }

  /** Add LUT samples [start, end) of the core line to `ctx`'s current path. */
  pathSegment(ctx: CanvasRenderingContext2D, start: number, end: number): void {
    ctx.moveTo(this.lut[start * 4], this.lut[start * 4 + 1]);
    for (let i = start + 1; i < end; i += 1) {
      ctx.lineTo(this.lut[i * 4], this.lut[i * 4 + 1]);
    }
  }

  /** Point + unit normal at normalized arc length t, written into `out`. */
  sample(t: number, out: Float32Array): void {
    const target = clamp01(t) * this.total;
    let lo = 0;
    let hi = this.count - 1;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (this.cumulative[mid] < target) lo = mid + 1;
      else hi = mid;
    }
    const i = Math.max(lo, 1);
    const seg = this.cumulative[i] - this.cumulative[i - 1] || 1;
    const k = (target - this.cumulative[i - 1]) / seg;
    out[0] = this.lut[(i - 1) * 4] + (this.lut[i * 4] - this.lut[(i - 1) * 4]) * k;
    out[1] = this.lut[(i - 1) * 4 + 1] + (this.lut[i * 4 + 1] - this.lut[(i - 1) * 4 + 1]) * k;
    out[2] = this.lut[i * 4 + 2];
    out[3] = this.lut[i * 4 + 3];
  }
}

interface PreparedBand {
  ribbon: Ribbon;
  crest: number;
  spec: BandSpec;
  /** Static dust, stride 8: t, normalOffset, brightness, size, spriteIdx, r, g, b. */
  dust: Float32Array;
  /** Live particles, stride 8: t, drift, normalOffset, size, phase, twinkle, alpha, bright. */
  live: Float32Array;
  /** Soft glow sprites: [crest-tinted, bright-tinted]. */
  sprites: HTMLCanvasElement[];
  /** Dust sprites sampled along the arc; index = t bucket. */
  dustSprites: HTMLCanvasElement[];
}

function makeSprite(rgb: Rgb, coreAlpha: number): HTMLCanvasElement {
  const sprite = document.createElement("canvas");
  sprite.width = 32;
  sprite.height = 32;
  const ctx = sprite.getContext("2d");
  if (!ctx) return sprite;
  const gradient = ctx.createRadialGradient(16, 16, 0, 16, 16, 16);
  gradient.addColorStop(0, rgba(rgb, coreAlpha));
  gradient.addColorStop(0.22, rgba(rgb, coreAlpha * 0.55));
  gradient.addColorStop(0.55, rgba(rgb, coreAlpha * 0.16));
  gradient.addColorStop(1, rgba(rgb, 0));
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, 32, 32);
  return sprite;
}

/** Width of the ribbon (relative to sigma) along t: narrow tails, wide crest. */
function widthProfile(t: number): number {
  return 0.45 + 0.55 * Math.pow(Math.sin(Math.PI * clamp01(t)), 0.75);
}

/** Alpha window: fade the ribbon ends in/out so drifting particles never pop. */
function endWindow(t: number): number {
  return smoothstep(0, 0.05, t) * (1 - smoothstep(0.94, 1, t));
}

/** Crest hot-zone boost along t. */
function crestBoost(crest: number, t: number): number {
  const d = t - crest;
  return Math.exp(-(d * d) / 0.018);
}

function buildBands(width: number, height: number, scale: number): PreparedBand[] {
  const random = createRandom(0x51ea4d);
  const bands: PreparedBand[] = [];
  for (const spec of BANDS) {
    const ribbon = new Ribbon(spec.points, width, height);
    const crest = ribbon.crestT();

    // Dust, stride 8: t, normalOffset, brightness, size, spriteIdx, r, g, b.
    // Three components: a dense thread lying on the line (the luminous core),
    // a filament hugging it, and a wide faint halo — matching the prototype's
    // glowing-crest look.
    const dustCount = Math.round(spec.dust * scale);
    const dust = new Float32Array(dustCount * 8);
    for (let i = 0; i < dust.length; i += 8) {
      const t = random();
      const roll = random();
      const isThread = roll < 0.26;
      const isFilament = !isThread && roll < 0.66;
      const spreadPx = spec.sigma * height * widthProfile(t);
      const offset = gaussian(random) * spreadPx * (isThread ? 0.16 : isFilament ? 0.32 : 2.2 + random() * 1.8);
      const rgb = colorAt(spec.stops, t);
      const boost = crestBoost(crest, t);
      const lit = mixRgb(rgb, [235, 245, 255], Math.min(random() * 0.15 + boost * 0.25, 0.5));
      // Brightness decays with distance from the core line.
      const proximity = Math.exp(-(offset * offset) / (2 * spreadPx * spreadPx * 0.09));
      dust[i] = t;
      dust[i + 1] = offset;
      dust[i + 2] =
        (isThread ? 0.7 + random() * 0.5 : isFilament ? 0.7 + random() * 0.5 : 0.16 + random() * 0.24) *
        (0.35 + 0.65 * proximity) *
        (1 + 1.2 * boost);
      dust[i + 3] = isThread ? 0.7 + random() * 0.7 : isFilament ? 0.8 + random() * 0.8 : 0.9 + random() * 1.0;
      dust[i + 4] = isThread && boost > 0.4 && random() < 0.4 ? 1 : 0;
      dust[i + 5] = lit[0];
      dust[i + 6] = lit[1];
      dust[i + 7] = lit[2];
    }

    const live = new Float32Array(Math.round(spec.live * scale) * 8);
    for (let i = 0; i < live.length; i += 8) {
      live[i] = random(); // t
      live[i + 1] = 0.004 + random() * 0.02; // drift speed, t/s
      live[i + 2] = gaussian(random) * spec.sigma * height * 0.55; // normal offset
      live[i + 3] = 0.9 + random() * 1.5; // core size, CSS px
      live[i + 4] = random() * Math.PI * 2; // twinkle phase
      live[i + 5] = 0.5 + random() * 1.7; // twinkle speed, rad/s
      live[i + 6] = 0.35 + random() * 0.5; // base alpha
      live[i + 7] = random() < 0.3 ? 1 : 0; // bright sprite variant
    }

    bands.push({
      ribbon,
      crest,
      spec,
      dust,
      live,
      sprites: [
        makeSprite(colorAt(spec.stops, crest), 0.9),
        makeSprite(mixRgb(colorAt(spec.stops, crest), [240, 250, 255], 0.55), 0.95),
      ],
      dustSprites: [0, 0.25, 0.5, 0.75, 1].map((at) =>
        makeSprite(colorAt(spec.stops, at), 0.8),
      ),
    });
  }
  return bands;
}

/** Soft halo wash behind each crest, like the prototype's glowing core. */
function paintCrestGlows(
  ctx: CanvasRenderingContext2D,
  bands: readonly PreparedBand[],
  width: number,
  height: number,
): void {
  const sample = new Float32Array(4);
  const glows: readonly { rgb: Rgb; radius: number; alpha: number }[] = [
    { rgb: [30, 120, 235], radius: 0.22, alpha: 0.23 },
    { rgb: [255, 200, 80], radius: 0.15, alpha: 0.25 },
    { rgb: [40, 205, 155], radius: 0.12, alpha: 0.17 },
    { rgb: [235, 246, 255], radius: 0.14, alpha: 0.2 },
  ];
  for (let i = 0; i < glows.length; i += 1) {
    bands[i].ribbon.sample(bands[i].crest, sample);
    const gradient = ctx.createRadialGradient(sample[0], sample[1], 0, sample[0], sample[1], glows[i].radius * width);
    gradient.addColorStop(0, rgba(glows[i].rgb, glows[i].alpha));
    gradient.addColorStop(1, rgba(glows[i].rgb, 0));
    ctx.fillStyle = gradient;
    ctx.fillRect(0, 0, width, height);
  }
}

/** Luminous underwash: a soft stroke following each ribbon so the dust sits
    on a continuous glowing band instead of floating on bare navy. Tails fade
    via the same end window as the dust. */
function paintRibbonWash(ctx: CanvasRenderingContext2D, bands: readonly PreparedBand[], height: number): void {
  const chunkSize = 6;
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  for (const band of bands) {
    const samples = band.ribbon.sampleCount();
    for (let start = 0; start < samples - 1; start += chunkSize) {
      const end = Math.min(start + chunkSize, samples - 1);
      const tMid = band.ribbon.tAt((start + end) / 2);
      const boost = crestBoost(band.crest, tMid);
      const spreadPx = band.spec.sigma * height * widthProfile(tMid);
      const rgb = colorAt(band.spec.stops, tMid);
      ctx.beginPath();
      band.ribbon.pathSegment(ctx, start, end);
      ctx.strokeStyle = rgba(mixRgb(rgb, [230, 242, 255], boost * 0.2), (0.05 + 0.09 * boost) * endWindow(tMid));
      ctx.lineWidth = Math.max(spreadPx * (0.55 + 0.35 * widthProfile(tMid)), 6);
      ctx.shadowBlur = spreadPx * 0.5;
      ctx.shadowColor = rgba(rgb, 0.25);
      ctx.stroke();
    }
    ctx.shadowBlur = 0;
    ctx.shadowColor = "transparent";
  }
}

/** Ambient star dust across the surface, densest on the artwork side. */
function paintAmbient(ctx: CanvasRenderingContext2D, width: number, height: number, scale: number): void {
  const random = createRandom(0xa7b13d);
  const count = Math.round(750 * scale);
  for (let i = 0; i < count; i += 1) {
    const x = random() * width;
    const y = random() * height;
    const tint: Rgb = random() < 0.7 ? [140, 172, 214] : [196, 216, 240];
    ctx.fillStyle = rgba(tint, 0.04 + random() * 0.13);
    ctx.fillRect(x, y, 0.4 + random() * 0.9, 0.4 + random() * 0.9);
  }
}

/** Paint the full static dust layer (background + bands) onto `ctx`. */
function paintBase(ctx: CanvasRenderingContext2D, width: number, height: number, scale: number): PreparedBand[] {
  const bands = buildBands(width, height, scale);

  const backdrop = ctx.createLinearGradient(0, 0, width * 0.9, height);
  backdrop.addColorStop(0, "#0e2d55");
  backdrop.addColorStop(0.45, "#071d38");
  backdrop.addColorStop(1, "#030d1c");
  ctx.fillStyle = backdrop;
  ctx.fillRect(0, 0, width, height);

  paintCrestGlows(ctx, bands, width, height);
  paintRibbonWash(ctx, bands, height);
  paintAmbient(ctx, width, height, scale);

  const sample = new Float32Array(4);
  const random = createRandom(0x9e3779);
  for (const band of bands) {
    for (let i = 0; i < band.dust.length; i += 8) {
      const t = band.dust[i];
      band.ribbon.sample(t, sample);
      const x = sample[0] + sample[2] * band.dust[i + 1];
      const y = sample[1] + sample[3] * band.dust[i + 1];
      const alpha =
        band.dust[i + 2] * (0.7 + 0.6 * random()) * endWindow(t) * (0.62 + 0.38 * crestBoost(band.crest, t));
      const rgb: Rgb = [band.dust[i + 5], band.dust[i + 6], band.dust[i + 7]];
      const size = band.dust[i + 3];
      if (band.dust[i + 4] > 0) {
        // Crest filament sparkles get the soft sprite so they glow.
        const bucket = Math.min(4, Math.floor(t * 5));
        ctx.globalAlpha = Math.min(alpha, 0.9);
        ctx.drawImage(band.dustSprites[bucket], x - size * 1.9, y - size * 1.9, size * 3.8, size * 3.8);
      } else {
        ctx.fillStyle = rgba(rgb, Math.min(alpha, 0.8));
        ctx.fillRect(x, y, size, size);
      }
    }
  }
  ctx.globalAlpha = 1;
  return bands;
}

export default function ParticleBackdrop(): React.JSX.Element {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d", { alpha: false });
    if (!ctx) return;
    const baseCanvas = document.createElement("canvas");
    const baseCtx = baseCanvas.getContext("2d", { alpha: false });
    if (!baseCtx) return;

    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
    // TS7 does not propagate the null guards above into the closures below;
    // these explicitly-typed aliases carry the guarantee.
    const view: HTMLCanvasElement = canvas;
    const paint: CanvasRenderingContext2D = ctx;
    const base: CanvasRenderingContext2D = baseCtx;
    const sample = new Float32Array(4);
    const staticTime = 7.3;
    let bands: PreparedBand[] = [];
    let dpr = 1;
    let raf = 0;
    let running = false;
    let lastTime = 0;
    let animationTime = 0;

    function drawFrame(time: number): void {
      paint.setTransform(1, 0, 0, 1, 0, 0);
      paint.globalCompositeOperation = "source-over";
      paint.drawImage(baseCanvas, 0, 0);
      paint.setTransform(dpr, 0, 0, dpr, 0, 0);
      paint.globalCompositeOperation = "lighter";
      for (const band of bands) {
        const { live, sprites, crest } = band;
        for (let i = 0; i < live.length; i += 8) {
          let t = live[i] + live[i + 1] * time;
          t -= Math.floor(t);
          band.ribbon.sample(t, sample);
          const breathe = 1 + 0.22 * Math.sin(live[i + 4] * 1.7 + time * 0.35);
          const x = sample[0] + sample[2] * live[i + 2] * breathe;
          const y = sample[1] + sample[3] * live[i + 2] * breathe;
          const twinkle = 0.62 + 0.38 * Math.sin(live[i + 4] + time * live[i + 5]);
          const alpha = live[i + 6] * endWindow(t) * (0.55 + 0.45 * crestBoost(crest, t)) * twinkle;
          if (alpha <= 0.015) continue;
          const size = live[i + 3] * (3.4 + 1.2 * Math.sin(live[i + 4] * 0.9 + time * 0.22));
          paint.globalAlpha = alpha;
          paint.drawImage(sprites[live[i + 7]], x - size / 2, y - size / 2, size, size);
        }
      }
      paint.globalAlpha = 1;
      paint.globalCompositeOperation = "source-over";
    }

    function rebuild(): void {
      const width = view.clientWidth;
      const height = view.clientHeight;
      if (width === 0 || height === 0) return;
      dpr = Math.min(window.devicePixelRatio || 1, 1.5);
      view.width = Math.round(width * dpr);
      view.height = Math.round(height * dpr);
      baseCanvas.width = view.width;
      baseCanvas.height = view.height;
      const scale = Math.min(Math.max(Math.sqrt((width * height) / REFERENCE_AREA), 0.55), 1.6);
      base.setTransform(dpr, 0, 0, dpr, 0, 0);
      bands = paintBase(base, width, height, scale);
      if (reduceMotion.matches) drawFrame(staticTime);
    }

    function tick(now: number): void {
      animationTime += Math.min(Math.max((now - lastTime) / 1000, 0), 0.1);
      lastTime = now;
      drawFrame(animationTime);
      raf = requestAnimationFrame(tick);
    }

    function start(): void {
      if (running || reduceMotion.matches) return;
      running = true;
      lastTime = performance.now();
      raf = requestAnimationFrame(tick);
    }

    function stop(): void {
      running = false;
      cancelAnimationFrame(raf);
    }

    let resizeTimer = 0;
    function onResize(): void {
      window.clearTimeout(resizeTimer);
      resizeTimer = window.setTimeout(rebuild, 120);
    }
    function onVisibility(): void {
      if (document.hidden) stop();
      else start();
    }
    function onMotionPreference(): void {
      if (reduceMotion.matches) {
        stop();
        drawFrame(staticTime);
      } else {
        start();
      }
    }

    rebuild();
    start();
    window.addEventListener("resize", onResize);
    document.addEventListener("visibilitychange", onVisibility);
    reduceMotion.addEventListener("change", onMotionPreference);

    return () => {
      stop();
      window.clearTimeout(resizeTimer);
      window.removeEventListener("resize", onResize);
      document.removeEventListener("visibilitychange", onVisibility);
      reduceMotion.removeEventListener("change", onMotionPreference);
    };
  }, []);

  return <canvas ref={canvasRef} className={styles.canvas} aria-hidden="true" />;
}
