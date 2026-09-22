/**
 * Dev-only guard for backend contract regressions that a defensive UI fallback
 * would otherwise mask (e.g. a required `ConnectivityResult.valid` missing).
 *
 * The API-level contract assertions remain the real gate; this only makes the
 * regression visible in dev instead of silently degrading the UI. No-op in
 * production builds.
 */
export function devContractAssert(condition: boolean, message: string): void {
  if (!import.meta.env.DEV || condition) return;
  console.error(`[contract] ${message}`);
}
