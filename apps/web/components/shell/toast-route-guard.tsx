"use client";

import { usePathname } from "next/navigation";
import { Suspense, useEffect, useRef } from "react";

import { dismissToastsOnNavigation } from "@/lib/toasts";

function Guard() {
  const pathname = usePathname();
  const previous = useRef(pathname);
  useEffect(() => {
    if (previous.current === pathname) return;
    previous.current = pathname;
    dismissToastsOnNavigation();
  }, [pathname]);
  return null;
}

/** Clears toasts when the page changes (D-022 #5). Renders nothing. */
export function ToastRouteGuard() {
  // The pathname of a dynamic route is only known at request time (see SideNav).
  return (
    <Suspense fallback={null}>
      <Guard />
    </Suspense>
  );
}
