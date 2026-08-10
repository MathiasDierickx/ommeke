import type { Metadata } from "next";

import { SharedRouteView } from "@/components/shared-route";

export const metadata: Metadata = {
  title: "Gedeelde route — Lusmaker",
  description: "Bekijk een gedeelde fiets- of traillus.",
};

export default async function SharedRoutePage({
  params,
}: {
  params: Promise<{ token: string }>;
}) {
  const { token } = await params;
  return <SharedRouteView token={token} />;
}
