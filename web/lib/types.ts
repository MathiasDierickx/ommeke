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
  geometry?: RouteGeometry | null;
  computed?: {
    kwaliteit?: {
      kassei_m?: number;
      offroad_pct?: number;
      populair_pct?: number;
    };
  } | null;
};

export type RouteGeometry = {
  points: [number, number][];
  climbs: { lat: number; lon: number; id: string }[];
  start: { lat: number; lon: number; label?: string } | null;
  elevation?: { km: number; ele: number }[];
};
