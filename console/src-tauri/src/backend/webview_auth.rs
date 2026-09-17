//! Authenticate requests inside WebView2 without changing frontend transports.

use tauri::{Manager, WebviewWindow};
use webview2_com::Microsoft::Web::WebView2::Win32::*;
use webview2_com::{take_pwstr, WebResourceRequestedEventHandler};
use windows::core::{Interface, BOOL, HSTRING, PWSTR};

use super::{BackendState, DESKTOP_SESSION_HEADER};

pub(crate) fn install(window: &WebviewWindow) -> Result<(), String> {
    let app = window.app_handle().clone();
    *app.state::<BackendState>().webview_auth.lock().unwrap() = None;
    let handle = app.clone();
    // with_webview may dispatch to the UI thread. Never wait for it on that
    // thread; backend_port remains unavailable until installation completes.
    let dispatched = window.with_webview(move |platform| {
        let result = (|| -> windows::core::Result<()> {
            unsafe {
                let core = platform.controller().CoreWebView2()?;
                let environment = platform.environment();
                // Older filters omit Worker requests. Unsupported runtimes
                // must report a startup error instead of partially authenticating.
                core.cast::<ICoreWebView2_22>()?
                    .AddWebResourceRequestedFilterWithRequestSourceKinds(
                        &HSTRING::from("*"),
                        COREWEBVIEW2_WEB_RESOURCE_CONTEXT_ALL,
                        COREWEBVIEW2_WEB_RESOURCE_REQUEST_SOURCE_KINDS_ALL,
                    )?;
                let state_handle = handle.clone();
                let mut event_token = 0;
                core.add_WebResourceRequested(
                    &WebResourceRequestedEventHandler::create(Box::new(move |_, args| {
                        let Some(args) = args else { return Ok(()) };
                        let result = (|| -> windows::core::Result<()> {
                            let request = args.Request()?;
                            let mut uri = PWSTR::null();
                            request.Uri(&mut uri)?;
                            let url = tauri::Url::parse(&take_pwstr(uri)).ok();
                            let headers = request.Headers()?;
                            let name = HSTRING::from(DESKTOP_SESSION_HEADER);
                            let mut supplied = BOOL::default();
                            headers.Contains(&name, &mut supplied)?;
                            let session = state_handle.state::<BackendState>().session().ok();
                            let target = session.as_ref().filter(|session| {
                                url.as_ref().is_some_and(|url| {
                                    url.username().is_empty()
                                        && url.password().is_none()
                                        && url.origin().ascii_serialization() == session.origin
                                })
                            });
                            if let Some(session) = target {
                                headers.SetHeader(&name, &HSTRING::from(&session.token))?;
                            } else if supplied.as_bool() {
                                // Removing a header is insufficient on redirected
                                // WebView2 requests: reject before transmission.
                                args.SetResponse(&environment.CreateWebResourceResponse(
                                    None,
                                    403,
                                    &HSTRING::from("Desktop credential target denied"),
                                    &HSTRING::from("Cache-Control: no-store"),
                                )?)?;
                            }
                            Ok(())
                        })();
                        if let Err(error) = result {
                            log::error!("[backend] WebView authentication failed: {error}");
                            args.SetResponse(&environment.CreateWebResourceResponse(
                                None,
                                503,
                                &HSTRING::from("Desktop authentication unavailable"),
                                &HSTRING::from("Cache-Control: no-store"),
                            )?)?;
                        }
                        Ok(())
                    })),
                    &mut event_token,
                )?;
            }
            Ok(())
        })()
        .map_err(|error| format!("Unable to initialize Desktop authentication. Update Microsoft Edge WebView2 Runtime: {error}"));
        *handle.state::<BackendState>().webview_auth.lock().unwrap() = Some(result);
    });
    if let Err(error) = dispatched {
        let message = format!("Unable to install Desktop authentication: {error}");
        *app.state::<BackendState>().webview_auth.lock().unwrap() = Some(Err(message.clone()));
        return Err(message);
    }
    Ok(())
}
