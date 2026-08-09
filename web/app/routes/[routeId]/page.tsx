import { Suspense } from "react";

import { LusmakerApp } from "@/components/lusmaker-app";

export default async function RoutePage({
  params,
}: {
  params: Promise<{ routeId: string }>;
}) {
  const { routeId } = await params;
  return (
    <Suspense fallback={<div className="app-loading">Route laden…</div>}>
      <LusmakerApp view={{ kind: "route", id: routeId }} />
    </Suspense>
  );
}
