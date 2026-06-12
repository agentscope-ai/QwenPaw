/** Navigate to the data connection add page in host plugin or standalone shell. */
export function navigateDataConnectionAdd(): void {
  const base = window.location.pathname.startsWith("/plugin/datapaw/")
    ? "/plugin/datapaw/datapaw/data-connection"
    : "/datapaw/data-connection";
  window.history.pushState({}, "", `${base}/add`);
  window.dispatchEvent(new PopStateEvent("popstate"));
}
