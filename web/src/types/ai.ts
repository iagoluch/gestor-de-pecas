export interface AIStatus {
  enabled: boolean;
  configured: boolean;
  available: boolean;
  model: string;
  cooldown?: AICooldown;
}

export interface AICooldown {
  active: boolean;
  retry_after_seconds: number;
  blocked_until: string | null;
}

export interface AIConversation {
  id: number;
  user_id: number;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface AIMessage {
  id: number;
  conversation_id: number;
  role: "user" | "assistant";
  content: string;
  model?: string | null;
  created_at: string;
  metadata?: Record<string, unknown>;
}

export interface AIConversationDetail extends AIConversation {
  messages: AIMessage[];
}

export interface AIReportArtifact {
  id: string;
  name: string;
  type: string;
  period_start?: string;
  period_end?: string;
  size_bytes?: number;
  status: string;
  download_url: string;
  telegram_available?: boolean;
  telegram_destination_id?: number;
}

export type AIStreamEvent =
  | { event: "status"; data: { message: string; user_message_id?: number } }
  | { event: "delta"; data: { content: string } }
  | { event: "artifact"; data: AIReportArtifact }
  | { event: "done"; data: { message: AIMessage; conversation_id: number; tool_rounds: number; artifacts?: AIReportArtifact[] } }
  | { event: "error"; data: { code: string; message: string; retryable?: boolean; request_id?: string | null; retry_after_seconds?: number; blocked_until?: string | null } };
