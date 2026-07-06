import { redirect } from "next/navigation";

/**
 * Root page redirects to the Dashboard (Requirement 8.1: Dashboard as primary entry point).
 */
export default function Home() {
  redirect("/dashboard");
}
