import { Suspense } from "react";

import { LusmakerApp } from "@/components/lusmaker-app";

export default async function ConversationPage({
  params,
}: {
  params: Promise<{ conversationId: string }>;
}) {
  const { conversationId } = await params;
  return (
    <Suspense fallback={<div className="app-loading">Gesprek laden…</div>}>
      <LusmakerApp view={{ kind: "conversation", id: conversationId }} />
    </Suspense>
  );
}
