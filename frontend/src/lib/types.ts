// Types matching the actual backend response shapes

export interface ExtractedData {
  damage_type?: string;
  estimated_cost?: number;
  vehicle_info?: string;
  incident_details?: string;
  document_type?: string;
  key_findings?: string[];
  [key: string]: unknown;
}

export interface FraudSignal {
  signal_name: string;
  description: string;
  severity: "low" | "medium" | "high";
  confidence: number;
}

export interface FraudScore {
  overall_score: number;
  risk_level: "low" | "medium" | "high" | "critical";
  signals: FraudSignal[];
  explanation: string;
}

export interface CoverageResult {
  policy_number: string;
  coverage_type: string;
  coverage_limit: number;
  deductible: number;
  covered: boolean;
  explanation: string;
}

export interface PayoutRecommendation {
  recommended_amount: number;
  confidence: number;
  rationale: string;
  comparable_claims: string[];
}

export interface SimulationResult {
  approval_probability: number;
  dispute_risk: number;
  fraud_escalation_likelihood: number | string;
  financial_exposure: number;
  historical_comparison: string;
  recommended_action: string;
}

export interface RiskAssessment {
  action_risk_level: string;
  identity_confidence: number;
  document_authenticity_confidence: number;
  fraud_concern_level: number;
  approval_threshold: number;
  recommended_action: string;
  fraud_score: number;
  monetary_value: number;
  money_movement: boolean;
  reasoning: string;
}

export interface EvidenceSummary {
  identity_confidence: number;
  fraud_score: number;
  policy_check: string;
}

export interface DecisionReceipt {
  receipt_id: string;
  claim_id: string;
  action: string;
  requested_by: string;
  approved_by: string;
  identity_confidence: number;
  fraud_score: number;
  policy_check: string;
  simulation_summary: string;
  timestamp: string;
  signature_hash: string;
  payout_amount?: number;
  notes?: string;
}

export type ClaimStatus =
  | "submitted"
  | "processing"
  | "pending_review"
  | "analyzed"
  | "ready"
  | "needs_consent"
  | "auto_approved"
  | "approved"
  | "denied"
  | "escalated"
  | "blocked"
  | "error";

export interface ClaimData {
  id: string;
  status: ClaimStatus;
  claimant_name: string;
  incident_description: string;
  policy_number: string;
  file_path: string;
  file_type: string;
  created_at: string;
  extracted_data: ExtractedData | null;
  fraud_score: number | FraudScore | null;
  risk_level: string | null;
  coverage_result: CoverageResult | null;
  payout_recommendation: PayoutRecommendation | null;
  simulation_result: SimulationResult | null;
  risk_assessment: RiskAssessment | null;
  decision: string | null;
  decision_by: string | null;
  decision_at: string | null;
  receipt: DecisionReceipt | null;
  /** Fraud signals extracted from investigation events (populated client-side). */
  fraud_signals?: FraudSignal[];
}

export interface ApprovalRequest {
  claim_id: string;
  decision: "approve" | "deny" | "escalate";
  approver_name: string;
  notes?: string;
}

export interface AuditEntry {
  id: number;
  claim_id: string;
  action: string;
  actor: string;
  details: Record<string, unknown>;
  timestamp: string;
}

export interface InvestigationEvent {
  event_type: string;
  message: string;
  status: string;
  data?: Record<string, unknown>;
  timestamp: string;
}

export interface Evidence {
  claim_id: string;
  status: string;
  claimant_name: string;
  incident_description: string;
  policy_number: string;
  file_type: string;
  created_at: string;
  extracted_data: ExtractedData | null;
  fraud_assessment: Record<string, unknown>;
  coverage_result: CoverageResult | null;
  payout_recommendation: PayoutRecommendation | null;
  simulation_result: SimulationResult | null;
  risk_assessment: RiskAssessment | null;
}

// Chat types
export interface ToolCall {
  id: string;
  name: string;
  arguments: Record<string, unknown>;
  result?: string;
}

export interface ChatMessage {
  role: "user" | "assistant" | "tool";
  content: string;
  toolCalls?: ToolCall[];
  isStreaming?: boolean;
}

export type ChatEventType =
  | "text_delta"
  | "tool_call"
  | "tool_result"
  | "done"
  | "error";

export interface ChatEvent {
  type: ChatEventType;
  content?: string;
  tool_call?: {
    id: string;
    name: string;
    arguments: Record<string, unknown>;
  };
  tool_result?: {
    id: string;
    result: string;
  };
  error?: string;
}

// Pipeline stepper types
export type PipelineStage =
  | "intake"
  | "vision_ai"
  | "coverage"
  | "fraud"
  | "payout"
  | "simulate"
  | "risk_eval";

export type StepState = "pending" | "active" | "complete" | "error";

export interface PipelineStep {
  id: PipelineStage;
  label: string;
  state: StepState;
}
