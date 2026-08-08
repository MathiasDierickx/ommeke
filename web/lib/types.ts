export type AuthSession = {
  accessToken: string;
  idToken: string;
  refreshToken?: string;
  expiresAt: number;
  email?: string;
  name?: string;
};

export type Conversation = {
  id: string;
  title: string;
  preview: string;
  created_at: string;
  updated_at: string;
};

export type ChatMessage = {
  id: string;
  conversation_id: string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
  route_ids?: string[];
};

export type Route = {
  id: string;
  revision: number;
  name: string;
  created?: string;
  start?: string;
  activity: "fietsen" | "trail";
  region?: string;
  climbs: string[];
  total_km?: number;
  elevation_gain_m?: number;
  ready: boolean;
  download_url?: string;
  preview_url?: string;
};
