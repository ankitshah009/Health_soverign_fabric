"use client";

import { useState, useRef, useCallback, useEffect } from "react";
import { Mic, Square, Loader2 } from "lucide-react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

type VoiceState = "idle" | "connecting" | "listening" | "speaking";

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

  const buttonBackground =
    voiceState === "idle"
      ? "var(--bg-surface)"
      : voiceState === "connecting"
      ? "var(--bg-elevated)"
      : voiceState === "listening"
      ? "var(--accent-primary)"
      : "var(--risk-low)";

  const buttonBorder =
    voiceState === "idle"
      ? "var(--accent-primary)"
      : voiceState === "connecting"
      ? "var(--accent-primary)"
      : voiceState === "listening"
      ? "var(--accent-primary)"
      : "var(--risk-low)";

  const showPulse = voiceState === "listening" || voiceState === "speaking";

  return (
    <div className="flex flex-col items-center gap-3">
      {/* Pulse ring container */}
      <div className="relative flex items-center justify-center">
        {showPulse && (
          <div
            className="absolute inset-0 rounded-full"
            style={{
              border: `2px solid ${voiceState === "listening" ? "var(--accent-primary)" : "var(--risk-low)"}`,
              animation: "voicePulse 1.5s ease-out infinite",
              width: "64px",
              height: "64px",
            }}
          />
        )}
        <style>{`
          @keyframes voicePulse {
            0% { transform: scale(1); opacity: 0.6; }
            100% { transform: scale(1.6); opacity: 0; }
          }
        `}</style>

        <button
          onClick={handleToggle}
          className="relative w-16 h-16 rounded-full flex items-center justify-center transition-all duration-200 z-10"
          style={{
            background: buttonBackground,
            border: `2px solid ${buttonBorder}`,
            cursor: "pointer",
          }}
          title={
            voiceState === "idle"
              ? "Start voice conversation"
              : "Stop voice conversation"
          }
        >
          {voiceState === "connecting" ? (
            <Loader2
              className="w-6 h-6 animate-spin"
              style={{ color: "var(--accent-primary)" }}
            />
          ) : voiceState === "idle" ? (
            <Mic
              className="w-6 h-6"
              style={{ color: "var(--accent-primary)" }}
            />
          ) : (
            <Square
              className="w-6 h-6"
              style={{ color: "var(--text-primary)" }}
            />
          )}
        </button>
      </div>

      {/* State label */}
      <span
        className="text-xs font-medium"
        style={{
          color:
            voiceState === "listening"
              ? "var(--accent-primary)"
              : voiceState === "speaking"
              ? "var(--risk-low)"
              : voiceState === "connecting"
              ? "var(--text-secondary)"
              : "var(--text-muted)",
        }}
      >
        {voiceState === "idle" && "Voice"}
        {voiceState === "connecting" && "Connecting..."}
        {voiceState === "listening" && "Listening..."}
        {voiceState === "speaking" && "Speaking..."}
      </span>

      {/* Transcript */}
      {transcript && (
        <div
          className="text-sm text-center max-w-full px-3 py-2 rounded-lg animate-fade-in"
          style={{
            color: "var(--text-secondary)",
            background: "var(--bg-surface)",
            border: "1px solid var(--border-subtle)",
            maxHeight: "80px",
            overflowY: "auto",
          }}
        >
          {transcript}
        </div>
      )}

      {/* Error */}
      {errorMsg && (
        <div
          className="text-xs text-center px-3 py-1.5 rounded-lg"
          style={{
            color: "var(--risk-critical)",
            background: "var(--risk-critical-bg)",
            border: "1px solid var(--risk-critical-border)",
          }}
        >
          {errorMsg}
        </div>
      )}
    </div>
  );
}
