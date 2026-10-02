import { notFound } from "next/navigation";
import { QaClient } from "../../e2e/qa-client";

export default function QaPage() {
  if (process.env.NODE_ENV === "production" || process.env.LUSMAKER_UI_QA !== "1") notFound();
  return <QaClient />;
}
