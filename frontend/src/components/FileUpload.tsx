"use client";

import Image from "next/image";
import { useCallback, useState, useRef, useEffect } from "react";
import { Upload, File, X, Check } from "lucide-react";

interface FileUploadProps {
  onFileSelect: (file: File) => void;
  selectedFile: File | null;
  onRemove: () => void;
}

export default function FileUpload({
  onFileSelect,
  selectedFile,
  onRemove,
}: FileUploadProps) {
  const [isDragging, setIsDragging] = useState(false);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleFile = useCallback(
    (file: File) => {
      onFileSelect(file);
      if (file.type.startsWith("image/")) {
        const url = URL.createObjectURL(file);
        setPreviewUrl((prev) => {
          if (prev) {
            URL.revokeObjectURL(prev);
          }

          return url;
        });
      } else {
        setPreviewUrl((prev) => {
          if (prev) {
            URL.revokeObjectURL(prev);
          }

          return null;
        });
      }
    },
    [onFileSelect]
  );

  useEffect(() => {
    return () => {
      if (previewUrl) {
        URL.revokeObjectURL(previewUrl);
      }
    };
  }, [previewUrl]);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setIsDragging(false);
      const file = e.dataTransfer.files[0];
      if (file) handleFile(file);
    },
    [handleFile]
  );

  const handleInputChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file) handleFile(file);
    },
    [handleFile]
  );

  const handleRemove = useCallback(() => {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    setPreviewUrl(null);
    onRemove();
    if (inputRef.current) inputRef.current.value = "";
  }, [previewUrl, onRemove]);

  const formatFileSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  if (selectedFile) {
    return (
      <div
        className="rounded-xl p-4"
        style={{
          background: "var(--bg-elevated)",
          border: "1px solid var(--border-default)",
        }}
      >
        <div className="flex items-start gap-4">
          {/* Preview */}
          {previewUrl ? (
            <div
              className="relative w-20 h-20 rounded-xl overflow-hidden flex-shrink-0"
              style={{ background: "var(--bg-base)" }}
            >
              <Image
                src={previewUrl}
                alt="Preview"
                fill
                unoptimized
                sizes="80px"
                className="object-cover"
              />
            </div>
          ) : (
            <div
              className="w-20 h-20 rounded-xl flex-shrink-0 flex items-center justify-center"
              style={{ background: "var(--bg-base)" }}
            >
              <File
                className="w-8 h-8"
                style={{ color: "var(--text-muted)" }}
              />
            </div>
          )}

          {/* Info */}
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium truncate" style={{ color: "var(--text-primary)" }}>
              {selectedFile.name}
            </p>
            <p className="text-xs mt-1" style={{ color: "var(--text-secondary)" }}>
              {formatFileSize(selectedFile.size)} &middot;{" "}
              {selectedFile.type || "Unknown type"}
            </p>
            <div className="flex items-center gap-1 mt-2 text-xs" style={{ color: "var(--risk-low)" }}>
              <Check className="w-3.5 h-3.5" />
              Ready to upload
            </div>
          </div>

          {/* Remove */}
          <button
            type="button"
            onClick={handleRemove}
            className="flex-shrink-0 p-1.5 rounded-lg transition-colors hover:opacity-75"
            style={{ color: "var(--text-secondary)" }}
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      </div>
    );
  }

  return (
    <div
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      onClick={() => inputRef.current?.click()}
      className="relative border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-all"
      style={{
        borderColor: isDragging ? "var(--accent-primary)" : "var(--border-default)",
        background: isDragging ? "var(--accent-primary-bg)" : "transparent",
        boxShadow: isDragging ? "0 0 20px var(--accent-primary-border)" : "none",
      }}
    >
      <input
        ref={inputRef}
        type="file"
        onChange={handleInputChange}
        accept="image/*,.pdf"
        className="hidden"
      />
      <Upload
        className="w-10 h-10 mx-auto mb-3"
        style={{ color: isDragging ? "var(--accent-primary)" : "var(--text-muted)" }}
      />
      <p className="text-sm mb-1" style={{ color: "var(--text-secondary)" }}>
        <span className="font-medium" style={{ color: "var(--accent-primary)" }}>Click to upload</span> or
        drag and drop
      </p>
      <p className="text-xs" style={{ color: "var(--text-muted)" }}>
        Images (PNG, JPG, WEBP) or PDF &mdash; up to 10MB
      </p>
    </div>
  );
}
