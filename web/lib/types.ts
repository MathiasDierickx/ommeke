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
    kwaliteit?: RouteQuality;
  } | null;
  kwaliteit?: RouteQuality;
};

export type RouteQuality = {
  kassei_m?: number;
  offroad_pct?: number;
  populair_pct?: number;
};

export type NearbyClimb = {
  id: string;
  naam: string;
  km: number;
  hm: number;
};

export type RouteAdjustment = {
  target_km?: number;
  voeg_klimmen_toe?: string[];
  verwijder_klimmen?: string[];
  vermijd_plaatsen?: string[];
  sta_plaatsen_toe?: string[];
  doel?: "hm" | "offroad" | "toeren" | "kort";
};

export type SharedRoute = {
  name: string;
  activity: "fietsen" | "trail";
  region?: string;
  climbs: string[];
  total_km?: number;
  elevation_gain_m?: number;
  geometry?: RouteGeometry | null;
  kwaliteit?: RouteQuality;
};

export type RouteGeometry = {
  points: [number, number][];
  climbs: { lat: number; lon: number; id: string }[];
  start: { lat: number; lon: number; label?: string } | null;
  elevation?: { km: number; ele: number }[];
};
