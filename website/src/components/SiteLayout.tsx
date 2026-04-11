import { Outlet } from "react-router-dom";
import { Nav } from "@/components/Nav";
import { Footer } from "@/components/Footer";
import { Suspense } from "react";

interface SiteLayoutProps {
  showFooter?: boolean;
}
/**
 * Loading fallback component for lazy-loaded pages
 */
function PageLoadingFallback() {
  return (
    <div className="min-h-screen flex items-center justify-center">
      <div className="text-center">
        <div
          className="inline-block h-8 w-8 animate-spin rounded-full border-4 border-solid border-current border-r-transparent align-[-0.125em] motion-reduce:animate-[spin_1.5s_linear_infinite]"
          role="status"
        >
          <span className="!absolute !-m-px !h-px !w-px !overflow-hidden !whitespace-nowrap !border-0 !p-0 ![clip:rect(0,0,0,0)]">
            Loading...
          </span>
        </div>
        <p className="mt-4 text-[var(--text-muted)]">Loading page...</p>
      </div>
    </div>
  );
}
export function SiteLayout({ showFooter = true }: SiteLayoutProps) {
  return (
    <>
      <Nav />
      <Suspense fallback={<PageLoadingFallback />}>
        <Outlet />
      </Suspense>
      {showFooter ? <Footer /> : null}
    </>
  );
}
