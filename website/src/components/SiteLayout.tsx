import { Outlet } from "react-router-dom";
import { Nav } from "@/components/Nav";
import { Footer } from "@/components/Footer";

interface SiteLayoutProps {
  showFooter?: boolean;
}

export function SiteLayout({ showFooter = true }: SiteLayoutProps) {
  return (
    <>
      <Nav />
      <Outlet />
      {showFooter ? <Footer /> : null}
    </>
  );
}
