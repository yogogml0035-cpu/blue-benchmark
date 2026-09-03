"use client";

import { useEffect, useRef } from "react";
import styles from "./particle-field.module.css";

/**
 * Deterministic particle backdrop for the authentication surface.
 *
 * The field is drawn from a fixed seed, so every browser and every screenshot
 * renders the identical composition. It paints once on mount and again only
 * when the viewport resizes — there is no continuous animation loop, and a
 * static frame is kept under `prefers-reduced-motion`.
 */

const PARTICLE_COUNT = 190;
const TRAIL_COUNT = 14;

/** mulberry32 — small, fast, seedable PRNG for reproducible layouts. */
function createRandom(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6d2b79f5) | 0;
    let t = Math.imul(state ^ (state >>> 15), 1 | state);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

interface Palette {
  color: string;
  weight: number;
}

const PALETTE: Palette[] = [
  { color: "rgba(76, 154, 255, 0.9)", weight: 0.34 },
  { color: "rgba(232, 185, 63, 0.75)", weight: 0.18 },
  { color: "rgba(67, 201, 138, 0.7)", weight: 0.2 },
  { color: "rgba(237, 247, 255, 0.85)", weight: 0.28 },
];

function pickColor(random: () => number): string {
  let roll = random();
  for (const entry of PALETTE) {
    if (roll < entry.weight) return entry.color;
    roll -= entry.weight;
  }
  return PALETTE[0].color;
}

function paint(canvas: HTMLCanvasElement): void {
  const ctx = canvas.getContext("2d");
  if (!ctx) return;

  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const width = canvas.clientWidth;
  const height = canvas.clientHeight;
  if (width === 0 || height === 0) return;

  canvas.width = Math.round(width * dpr);
  canvas.height = Math.round(height * dpr);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

  const random = createRandom(0xa11ce);

  // Deep blue-black vertical gradient.
  const backdrop = ctx.createLinearGradient(0, 0, 0, height);
  backdrop.addColorStop(0, "#0b0d16");
  backdrop.addColorStop(0.5, "#0d1020");
  backdrop.addColorStop(1, "#080910");
  ctx.fillStyle = backdrop;
  ctx.fillRect(0, 0, width, height);

  // A faint nebula glow to give the field depth.
  const glow = ctx.createRadialGradient(
    width * 0.72,
    height * 0.3,
    0,
    width * 0.72,
    height * 0.3,
    Math.max(width, height) * 0.75,
  );
  glow.addColorStop(0, "rgba(54, 84, 168, 0.22)");
  glow.addColorStop(1, "rgba(0, 0, 0, 0)");
  ctx.fillStyle = glow;
  ctx.fillRect(0, 0, width, height);

  // Long streaking trails, like the prototype's particle motion frozen in time.
  for (let i = 0; i < TRAIL_COUNT; i += 1) {
    const x = random() * width;
    const y = random() * height;
    const length = 80 + random() * 220;
    const angle = -0.5 + random() * 1.0;
    const dx = Math.cos(angle) * length;
    const dy = Math.sin(angle) * length;
    const gradient = ctx.createLinearGradient(x, y, x + dx, y + dy);
    const color = pickColor(random);
    gradient.addColorStop(0, color);
    gradient.addColorStop(1, "rgba(0, 0, 0, 0)");
    ctx.strokeStyle = gradient;
    ctx.lineWidth = 1 + random() * 1.4;
    ctx.lineCap = "round";
    ctx.globalAlpha = 0.35 + random() * 0.4;
    ctx.beginPath();
    ctx.moveTo(x, y);
    ctx.lineTo(x + dx, y + dy);
    ctx.stroke();
  }

  // Scattered point particles.
  for (let i = 0; i < PARTICLE_COUNT; i += 1) {
    const x = random() * width;
    const y = random() * height;
    const radius = 0.6 + random() * 1.9;
    ctx.globalAlpha = 0.25 + random() * 0.65;
    ctx.fillStyle = pickColor(random);
    ctx.beginPath();
    ctx.arc(x, y, radius, 0, Math.PI * 2);
    ctx.fill();
  }

  ctx.globalAlpha = 1;
}

export function ParticleField(): React.JSX.Element {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    paint(canvas);

    let frame = 0;
    const handleResize = (): void => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => paint(canvas));
    };
    window.addEventListener("resize", handleResize);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("resize", handleResize);
    };
  }, []);

  return <canvas ref={canvasRef} className={styles.field} aria-hidden="true" />;
}
