"use client";

import { useState, useRef, useCallback, useEffect } from "react";
import { Mic, Square, Loader2 } from "lucide-react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

type VoiceState = "idle" | "connecting" | "listening" | "thinking" | "speaking";

// AudioWorklet processor source as a blob URL
function createWorkletBlobUrl(): string {
  const processorCode = `
    class PcmCaptureProcessor extends AudioWorkletProcessor {
      process(inputs) {
        const input = inputs[0];
        if (input && input[0] && input[0].length > 0) {
          this.port.postMessage(input[0]);
        }
        return true;
      }
    }
    registerProcessor("pcm-capture-processor", PcmCaptureProcessor);
  `;
  const blob = new Blob([processorCode], { type: "application/javascript" });
  return URL.createObjectURL(blob);
}

function resampleTo24kHz(inputBuffer: Float32Array, inputSampleRate: number): Float32Array {
  if (inputSampleRate === 24000) return inputBuffer;

  const ratio = inputSampleRate / 24000;
  const outputLength = Math.round(inputBuffer.length / ratio);
  const output = new Float32Array(outputLength);

  for (let i = 0; i < outputLength; i++) {
    const srcIndex = i * ratio;
    const srcIndexFloor = Math.floor(srcIndex);
    const srcIndexCeil = Math.min(srcIndexFloor + 1, inputBuffer.length - 1);
    const fraction = srcIndex - srcIndexFloor;
    output[i] =
      inputBuffer[srcIndexFloor] * (1 - fraction) +
      inputBuffer[srcIndexCeil] * fraction;
  }

  return output;
}

function float32ToBase64Pcm16(float32: Float32Array): string {
  const pcm16 = new Int16Array(float32.length);
  for (let i = 0; i < float32.length; i++) {
    const s = Math.max(-1, Math.min(1, float32[i]));
    pcm16[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  const bytes = new Uint8Array(pcm16.buffer);
  let binary = "";
  for (let i = 0; i < bytes.length; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary);
}

function base64ToFloat32Pcm(base64: string): Float32Array {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i);
  }
  const pcm16 = new Int16Array(bytes.buffer);
  const float32 = new Float32Array(pcm16.length);
  for (let i = 0; i < pcm16.length; i++) {
    float32[i] = pcm16[i] / (pcm16[i] < 0 ? 0x8000 : 0x7fff);
  }
  return float32;
}

interface VoiceButtonProps {
  autoStart?: boolean;
}

// State metadata: label, color, icon context
const STATE_META: Record<VoiceState, { label: string; color: string }> = {
  idle:       { label: "Tap to speak",     color: "var(--text-muted)" },
  connecting: { label: "Connecting…",      color: "var(--text-secondary)" },
  listening:  { label: "Listening",        color: "var(--accent-primary)" },
  thinking:   { label: "Thinking",         color: "var(--accent-primary)" },
  speaking:   { label: "Speaking",         color: "var(--risk-low)" },
};

export default function VoiceButton({ autoStart = false }: VoiceButtonProps) {
  const [voiceState, setVoiceState] = useState<VoiceState>("idle");
  const autoStartedRef = useRef(false);
  const [transcript, setTranscript] = useState("");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const workletNodeRef = useRef<AudioWorkletNode | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const silentGainRef = useRef<GainNode | null>(null);
  const playbackContextRef = useRef<AudioContext | null>(null);
  const playbackQueueRef = useRef<Float32Array[]>([]);
  const isPlayingRef = useRef(false);
  const workletUrlRef = useRef<string | null>(null);

  // Clean up resources
  const cleanup = useCallback(() => {
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    if (workletNodeRef.current) {
      workletNodeRef.current.disconnect();
      workletNodeRef.current = null;
    }
    if (mediaStreamRef.current) {
      mediaStreamRef.current.getTracks().forEach((t) => t.stop());
      mediaStreamRef.current = null;
    }
    if (silentGainRef.current) {
      silentGainRef.current.disconnect();
      silentGainRef.current = null;
    }
    if (audioContextRef.current) {
      audioContextRef.current.close();
      audioContextRef.current = null;
    }
    if (playbackContextRef.current) {
      playbackContextRef.current.close();
      playbackContextRef.current = null;
    }
    if (workletUrlRef.current) {
      URL.revokeObjectURL(workletUrlRef.current);
      workletUrlRef.current = null;
    }
    playbackQueueRef.current = [];
    isPlayingRef.current = false;
  }, []);

  useEffect(() => {
    return cleanup;
  }, [cleanup]);

  // Play queued audio buffers sequentially
  const playNextBuffer = useCallback(function playNextBuffer() {
    if (playbackQueueRef.current.length === 0) {
      isPlayingRef.current = false;
      setVoiceState((prev) => (prev === "speaking" ? "listening" : prev));
      return;
    }

    isPlayingRef.current = true;
    const buffer = playbackQueueRef.current.shift()!;

    if (!playbackContextRef.current) {
      playbackContextRef.current = new AudioContext({ sampleRate: 24000 });
    }

    const ctx = playbackContextRef.current;
    const audioBuffer = ctx.createBuffer(1, buffer.length, 24000);
    audioBuffer.getChannelData(0).set(buffer);

    const source = ctx.createBufferSource();
    source.buffer = audioBuffer;
    source.connect(ctx.destination);
    source.onended = () => {
      playNextBuffer();
    };
    source.start();
  }, []);

  const queueAudioForPlayback = useCallback(
    (audioData: Float32Array) => {
      playbackQueueRef.current.push(audioData);
      if (!isPlayingRef.current) {
        setVoiceState("speaking");
        playNextBuffer();
      }
    },
    [playNextBuffer]
  );

  const handleToggle = useCallback(async () => {
    if (voiceState !== "idle") {
      // Disconnect
      cleanup();
      setVoiceState("idle");
      setTranscript("");
      return;
    }

    setErrorMsg(null);
    setVoiceState("connecting");
    setTranscript("");

    try {
      // Get microphone access
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          sampleRate: 24000,
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
        },
      });
      mediaStreamRef.current = stream;

      // Set up audio capture context
      const audioCtx = new AudioContext({ sampleRate: stream.getAudioTracks()[0].getSettings().sampleRate || 48000 });
      audioContextRef.current = audioCtx;

      // Create worklet blob URL once
      if (!workletUrlRef.current) {
        workletUrlRef.current = createWorkletBlobUrl();
      }

      await audioCtx.audioWorklet.addModule(workletUrlRef.current);

      const source = audioCtx.createMediaStreamSource(stream);
      const workletNode = new AudioWorkletNode(audioCtx, "pcm-capture-processor");
      workletNodeRef.current = workletNode;
      source.connect(workletNode);
      const silentGain = audioCtx.createGain();
      silentGain.gain.value = 0;
      silentGainRef.current = silentGain;
      workletNode.connect(silentGain);
      silentGain.connect(audioCtx.destination);

      // Build WebSocket URL
      const wsProtocol = API_BASE.startsWith("https") ? "wss" : "ws";
      const wsHost = API_BASE.replace(/^https?:\/\//, "");
      const wsUrl = `${wsProtocol}://${wsHost}/api/voice`;

      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        setVoiceState("listening");

        // Stream mic audio to WebSocket
        workletNode.port.onmessage = (e: MessageEvent) => {
          if (ws.readyState !== WebSocket.OPEN) return;
          const float32: Float32Array = e.data;
          const resampled = resampleTo24kHz(float32, audioCtx.sampleRate);
          const base64 = float32ToBase64Pcm16(resampled);

          ws.send(
            JSON.stringify({
              type: "input_audio_buffer.append",
              audio: base64,
            })
          );
        };
      };

      ws.onmessage = (e: MessageEvent) => {
        try {
          const msg = JSON.parse(e.data);

          if (msg.type === "response.output_audio.delta" && msg.delta) {
            const audioData = base64ToFloat32Pcm(msg.delta);
            queueAudioForPlayback(audioData);
          }

          if (msg.type === "response.output_audio_transcript.delta" && msg.delta) {
            setTranscript((prev) => prev + msg.delta);
          }

          if (msg.type === "response.output_audio_transcript.done") {
            // Full transcript received; response finished
          }

          if (msg.type === "response.done") {
            setTranscript("");
          }

          if (msg.type === "error") {
            setErrorMsg(msg.error?.message || "Voice connection error");
            cleanup();
            setVoiceState("idle");
          }
        } catch {
          // skip unparseable
        }
      };

      ws.onerror = () => {
        setErrorMsg("WebSocket connection failed");
        cleanup();
        setVoiceState("idle");
      };

      ws.onclose = () => {
        cleanup();
        setVoiceState("idle");
      };
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Failed to start voice";
      if (message.includes("Permission") || message.includes("NotAllowed")) {
        setErrorMsg("Microphone access denied. Please allow microphone access.");
      } else {
        setErrorMsg(message);
      }
      cleanup();
      setVoiceState("idle");
    }
  }, [voiceState, cleanup, queueAudioForPlayback]);

  // Auto-start voice when opened via FAB — one click, not two
  useEffect(() => {
    if (autoStart && !autoStartedRef.current && voiceState === "idle") {
      autoStartedRef.current = true;
      handleToggle();
    }
  }, [autoStart, voiceState, handleToggle]);

  const isActive = voiceState !== "idle";
  const isListening = voiceState === "listening";
  const isSpeaking = voiceState === "speaking";
  const isConnecting = voiceState === "connecting";
  const showPulse = isListening || isSpeaking;
  const meta = STATE_META[voiceState];

  return (
    <div className="flex flex-col items-center gap-5">
      {/*
        Keyframes injected here so they live alongside the component
        and are gated with @media (prefers-reduced-motion: no-preference).
        The globals.css reduced-motion block also catches them as a fallback.
      */}
      <style>{`
        @media (prefers-reduced-motion: no-preference) {
          @keyframes voicePulse {
            0%   { transform: scale(1);   opacity: 0.55; }
            100% { transform: scale(1.9); opacity: 0; }
          }
          @keyframes voicePulse2 {
            0%   { transform: scale(1);   opacity: 0.30; }
            100% { transform: scale(2.4); opacity: 0; }
          }
          @keyframes voiceBlink {
            0%, 100% { opacity: 1; }
            50%       { opacity: 0; }
          }
        }
      `}</style>

      {/* ── Button + concentric pulse rings ─────── */}
      <div className="relative flex items-center justify-center" style={{ width: 80, height: 80 }}>
        {/* Outer slow ring — only when listening/speaking */}
        {showPulse && (
          <span
            aria-hidden="true"
            style={{
              position: "absolute",
              inset: 0,
              borderRadius: "50%",
              border: `1.5px solid ${isListening ? "var(--accent-primary)" : "var(--risk-low)"}`,
              animation: "voicePulse2 2.2s cubic-bezier(0.4,0,0.6,1) infinite 0.6s",
            }}
          />
        )}
        {/* Inner fast ring */}
        {showPulse && (
          <span
            aria-hidden="true"
            style={{
              position: "absolute",
              inset: 0,
              borderRadius: "50%",
              border: `2px solid ${isListening ? "var(--accent-primary)" : "var(--risk-low)"}`,
              animation: "voicePulse 1.8s cubic-bezier(0.4,0,0.6,1) infinite",
            }}
          />
        )}

        {/* Core button */}
        <button
          onClick={handleToggle}
          className="relative z-10 flex items-center justify-center btn-press focus-ring"
          style={{
            width: 80,
            height: 80,
            borderRadius: "50%",
            background: isActive
              ? isListening
                ? "var(--accent-primary)"
                : isSpeaking
                ? "var(--risk-low-bg)"
                : "var(--bg-elevated)"
              : "var(--bg-surface)",
            border: isActive
              ? `2px solid ${isListening ? "var(--accent-primary)" : isSpeaking ? "var(--risk-low)" : "var(--border-strong)"}`
              : "2px solid var(--border-default)",
            boxShadow: isListening
              ? "0 0 0 4px rgba(43,130,240,0.16), 0 4px 20px rgba(43,130,240,0.22)"
              : isSpeaking
              ? "0 0 0 4px rgba(16,185,129,0.12), 0 4px 20px rgba(16,185,129,0.16)"
              : "var(--shadow-md)",
            cursor: "pointer",
            transition: "background 0.2s ease, border-color 0.2s ease, box-shadow 0.3s ease",
          }}
          aria-label={
            voiceState === "idle"
              ? "Start voice conversation with Sovereign Advocate"
              : voiceState === "connecting"
              ? "Connecting to voice advocate…"
              : voiceState === "listening"
              ? "Stop voice conversation (currently listening)"
              : "Stop voice conversation (Sovereign is speaking)"
          }
          aria-pressed={isActive}
          title={isActive ? "Stop voice conversation" : "Start voice conversation"}
        >
          {isConnecting ? (
            <Loader2
              className="w-7 h-7 animate-spin"
              style={{ color: "var(--accent-primary)" }}
              aria-hidden="true"
            />
          ) : isActive ? (
            /* Stop affordance — filled square, always clear */
            <Square
              className="w-6 h-6"
              style={{
                color: isListening ? "var(--bg-base)" : "var(--text-primary)",
                fill: isListening ? "var(--bg-base)" : "none",
              }}
              aria-hidden="true"
            />
          ) : (
            <Mic
              className="w-7 h-7"
              style={{ color: "var(--accent-primary)" }}
              aria-hidden="true"
            />
          )}
        </button>
      </div>

      {/* ── State label + sub-copy ───────────────── */}
      <div className="text-center space-y-1" style={{ minHeight: "2.5rem" }}>
        <p
          className="type-subtitle"
          style={{
            color: meta.color,
            transition: "color 0.2s ease",
          }}
          aria-live="polite"
          aria-atomic="true"
        >
          {meta.label}
        </p>
        {voiceState === "idle" && (
          <p className="type-caption" style={{ color: "var(--text-muted)" }}>
            Tell me what happened with your bill
          </p>
        )}
        {isConnecting && (
          <p className="type-caption" style={{ color: "var(--text-muted)" }}>
            Establishing secure connection…
          </p>
        )}
      </div>

      {/* ── Live transcript ──────────────────────── */}
      {transcript && (
        <div
          className="animate-fade-in w-full px-4 py-3 rounded-xl"
          style={{
            color: "var(--text-secondary)",
            background: "var(--bg-surface)",
            border: "1px solid var(--border-subtle)",
            fontSize: "0.8125rem",
            lineHeight: 1.55,
            maxHeight: 96,
            overflowY: "auto",
          }}
          aria-live="polite"
        >
          {transcript}
        </div>
      )}

      {/* ── Error ───────────────────────────────── */}
      {errorMsg && (
        <div
          className="animate-fade-in w-full px-3 py-2.5 rounded-xl"
          style={{
            color: "var(--risk-critical)",
            background: "var(--risk-critical-bg)",
            border: "1px solid var(--risk-critical-border)",
            fontSize: "0.8125rem",
          }}
          role="alert"
        >
          {errorMsg}
        </div>
      )}
    </div>
  );
}
