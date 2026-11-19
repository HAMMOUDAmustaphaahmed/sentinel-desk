import { useEffect, useMemo, useRef, useState } from 'react'
import { Canvas, useFrame, useThree } from '@react-three/fiber'
import type { MotionValue } from 'framer-motion'
import { useReducedMotion } from 'framer-motion'
import * as THREE from 'three'

// What the scene shows: tickets (pale dots) and exceptions (red dots) arrive scattered.
// As the page scrolls, each one that belongs to an incident travels to it and a line
// ties it there. About a third never move: not every ticket is part of an outage.

// Colours in linear space; three.js converts them to sRGB for display.
const TICKET = [0.63, 0.7, 0.76]
const EXCEPTION = [1.0, 0.147, 0.147]
const SIGNAL = new THREE.Color('#c6f135')

const INCIDENTS: [number, number][] = [
  [0.4, 1.25],
  [2.5, 0.15],
  [0.9, -1.35],
]

function mulberry32(seed: number) {
  let a = seed
  return () => {
    a = (a + 0x6d2b79f5) | 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

const smoothstep = (a: number, b: number, x: number) => {
  const t = Math.min(1, Math.max(0, (x - a) / (b - a)))
  return t * t * (3 - 2 * t)
}

function build(count: number) {
  const rand = mulberry32(42)
  const scattered = new Float32Array(count * 3)
  const gathered = new Float32Array(count * 3)
  const colors = new Float32Array(count * 3)
  const owner = new Int8Array(count) // index of the incident, or -1 for an unrelated ticket

  for (let i = 0; i < count; i++) {
    const x = (rand() * 2 - 1) * 4.2 + 1.3
    const y = (rand() * 2 - 1) * 2.4
    scattered.set([x, y, (rand() * 2 - 1) * 0.8], i * 3)

    const linked = rand() < 0.68
    owner[i] = linked ? Math.floor(rand() * INCIDENTS.length) : -1
    if (linked) {
      const [cx, cy] = INCIDENTS[owner[i]]
      const radius = 0.12 + 0.5 * Math.sqrt(rand())
      const angle = rand() * Math.PI * 2
      gathered.set([cx + Math.cos(angle) * radius, cy + Math.sin(angle) * radius * 0.8, 0], i * 3)
    } else {
      gathered.set([x, y, 0], i * 3)
    }
    // Exceptions only ever belong to an incident; unrelated dots are all tickets.
    colors.set(linked && rand() < 0.45 ? EXCEPTION : TICKET, i * 3)
  }
  return { scattered, gathered, colors, owner }
}

function useDot() {
  const texture = useMemo(() => {
    const canvas = document.createElement('canvas')
    canvas.width = canvas.height = 64
    const ctx = canvas.getContext('2d')!
    ctx.fillStyle = '#fff'
    ctx.beginPath()
    ctx.arc(32, 32, 30, 0, Math.PI * 2)
    ctx.fill()
    return new THREE.CanvasTexture(canvas)
  }, [])
  useEffect(() => () => texture.dispose(), [texture])
  return texture
}

function Signals({ progress, count, reduced }: { progress: MotionValue<number>; count: number; reduced: boolean }) {
  const group = useRef<THREE.Group>(null)
  const points = useRef<THREE.BufferGeometry>(null)
  const lines = useRef<THREE.BufferGeometry>(null)
  const lineMaterial = useRef<THREE.LineBasicMaterial>(null)
  const nodeMaterial = useRef<THREE.PointsMaterial>(null)
  const eased = useRef(0)
  const dot = useDot()
  const { viewport, invalidate } = useThree()

  const data = useMemo(() => build(count), [count])
  const positions = useMemo(() => new Float32Array(data.scattered), [data])
  const linePositions = useMemo(() => new Float32Array(count * 6), [count])
  const nodePositions = useMemo(() => new Float32Array(INCIDENTS.flatMap(([x, y]) => [x, y, 0.05])), [])

  // With reduced motion the scene is not animated: it redraws only when the step changes.
  useEffect(() => {
    if (!reduced) return
    invalidate()
    return progress.on('change', () => invalidate())
  }, [reduced, progress, invalidate])

  useFrame((state, delta) => {
    const target = reduced ? (progress.get() > 0.4 ? 1 : 0) : progress.get()
    eased.current = reduced ? target : eased.current + (target - eased.current) * Math.min(1, delta * 5)
    const t = smoothstep(0.08, 0.85, eased.current)
    const drift = reduced ? 0 : 0.05 * (1 - t) + 0.008
    const time = state.clock.elapsedTime

    for (let i = 0; i < count; i++) {
      const j = i * 3
      const x = data.scattered[j] + (data.gathered[j] - data.scattered[j]) * t + Math.sin(time * 0.5 + i * 1.3) * drift
      const y = data.scattered[j + 1] + (data.gathered[j + 1] - data.scattered[j + 1]) * t + Math.cos(time * 0.4 + i * 2.1) * drift
      positions[j] = x
      positions[j + 1] = y
      positions[j + 2] = data.scattered[j + 2] * (1 - t)

      // One segment per dot, from the dot to its incident. Unrelated dots get a zero-length one.
      const k = i * 6
      const o = data.owner[i]
      linePositions[k] = x
      linePositions[k + 1] = y
      linePositions[k + 2] = positions[j + 2]
      linePositions[k + 3] = o < 0 ? x : INCIDENTS[o][0]
      linePositions[k + 4] = o < 0 ? y : INCIDENTS[o][1]
      linePositions[k + 5] = o < 0 ? positions[j + 2] : 0
    }
    points.current!.attributes.position.needsUpdate = true
    lines.current!.attributes.position.needsUpdate = true
    lineMaterial.current!.opacity = t * 0.16
    nodeMaterial.current!.opacity = t

    if (group.current) {
      // Fit the composition to the canvas: full size on a desktop, smaller and centred on a phone.
      const narrow = viewport.width < 7
      const scale = Math.min(viewport.width / (narrow ? 6.2 : 9.5), 1.15)
      group.current.scale.setScalar(scale)
      group.current.position.x = narrow ? -1.3 * scale : 0
    }
  })

  return (
    <group ref={group}>
      <lineSegments>
        <bufferGeometry ref={lines}>
          <bufferAttribute attach="attributes-position" args={[linePositions, 3]} />
        </bufferGeometry>
        <lineBasicMaterial ref={lineMaterial} color={SIGNAL} transparent opacity={0} depthWrite={false} />
      </lineSegments>
      <points>
        <bufferGeometry ref={points}>
          <bufferAttribute attach="attributes-position" args={[positions, 3]} />
          <bufferAttribute attach="attributes-color" args={[data.colors, 3]} />
        </bufferGeometry>
        <pointsMaterial size={0.06} map={dot} alphaTest={0.5} vertexColors sizeAttenuation />
      </points>
      <points>
        <bufferGeometry>
          <bufferAttribute attach="attributes-position" args={[nodePositions, 3]} />
        </bufferGeometry>
        <pointsMaterial ref={nodeMaterial} size={0.3} map={dot} color={SIGNAL} transparent opacity={0}
          alphaTest={0.01} sizeAttenuation depthWrite={false} />
      </points>
    </group>
  )
}

export default function SignalScene({ progress }: { progress: MotionValue<number> }) {
  const reduced = !!useReducedMotion()
  const holder = useRef<HTMLDivElement>(null)
  const [visible, setVisible] = useState(true)
  const count = useMemo(() => (window.innerWidth < 800 ? 320 : 640), [])

  // Off screen, the scene stops computing.
  useEffect(() => {
    const observer = new IntersectionObserver(([entry]) => setVisible(entry.isIntersecting))
    observer.observe(holder.current!)
    return () => observer.disconnect()
  }, [])

  return (
    <div ref={holder} className="lp-canvas" aria-hidden="true">
      <Canvas
        camera={{ position: [0, 0, 9], fov: 40 }}
        dpr={[1, 2]}
        gl={{ antialias: true, alpha: true, powerPreference: 'low-power' }}
        frameloop={reduced ? 'demand' : visible ? 'always' : 'never'}
      >
        <Signals progress={progress} count={count} reduced={reduced} />
      </Canvas>
    </div>
  )
}
