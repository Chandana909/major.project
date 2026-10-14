import { Component, type ErrorInfo, type ReactNode } from "react";
import { Canvas } from "@react-three/fiber";
import { OrbitControls } from "@react-three/drei";
import { webglAvailable } from "./layout";

class SceneBoundary extends Component<{ fallback: ReactNode; children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError(): { failed: boolean } {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.warn("3D view unavailable:", error.message, info.componentStack);
  }

  render(): ReactNode {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}

interface SceneFrameProps {
  label: string;
  height?: number;
  camera?: [number, number, number];
  autoRotate?: boolean;
  fallback?: ReactNode;
  children: ReactNode;
}

/** A 3D view with orbit controls, a dark background and a fallback when WebGL is missing. */
export function SceneFrame({ label, height = 420, camera = [0, 7, 15], autoRotate = true, fallback, children }: SceneFrameProps) {
  const fallbackView = (
    <div className="scene-fallback" style={{ height }} role="note">
      {fallback ?? <span>This 3D view needs WebGL, which this browser does not provide. The tables on this page show the same data.</span>}
    </div>
  );
  if (!webglAvailable()) return fallbackView;
  return (
    <SceneBoundary fallback={fallbackView}>
      <div className="scene" style={{ height }} role="img" aria-label={label}>
        <Canvas dpr={[1, 2]} camera={{ position: camera, fov: 45, near: 0.1, far: 200 }} gl={{ antialias: true }}>
          <color attach="background" args={["#060a14"]} />
          <fog attach="fog" args={["#060a14", 18, 42]} />
          <ambientLight intensity={0.35} />
          <directionalLight position={[6, 12, 8]} intensity={1.1} />
          <pointLight position={[-8, 6, -6]} intensity={40} color="#818cf8" />
          {children}
          <OrbitControls
            makeDefault
            enablePan={false}
            autoRotate={autoRotate}
            autoRotateSpeed={0.35}
            minDistance={5}
            maxDistance={32}
            maxPolarAngle={Math.PI / 2.05}
          />
        </Canvas>
        <div className="scene-hint">Drag to turn · scroll to zoom</div>
      </div>
    </SceneBoundary>
  );
}
