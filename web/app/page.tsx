import { Suspense } from "react";

import { LusmakerApp } from "@/components/lusmaker-app";

export default function HomePage() {
  return (
    <Suspense fallback={<div className="app-loading">Lusmaker laden…</div>}>
      <LusmakerApp />
    </Suspense>
  );
}
