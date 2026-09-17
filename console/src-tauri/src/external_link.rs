//! Tauri command for opening vetted external URLs in the system browser.

use std::{collections::HashMap, net::IpAddr, time::Duration};

use reqwest::{
    header::{HeaderMap, HeaderName, HeaderValue},
    Url,
};
use serde::Deserialize;
use tauri_plugin_shell::ShellExt;

use crate::backend::{BackendScope, BackendSession, BackendState, DESKTOP_SESSION_HEADER};

// Keep in sync with console/src/utils/openExternalLink.ts.
const SUPPORTED_EXTERNAL_PREFIXES: [&str; 4] = ["http://", "https://", "mailto:", "tel:"];
const HTML_URI_PATH: &str = "/api/workspace/html-file-uri";

#[derive(Debug, Deserialize)]
struct HtmlFileUriResponse {
    uri: String,
}

/// Validate and open an external URL through the OS shell.
#[tauri::command]
pub(crate) fn open_external_link(app: tauri::AppHandle, url: String) -> Result<(), String> {
    if let Err(err) = validate_external_url(&url) {
        log::warn!("[external-link] command rejected: {err}");
        return Err(err);
    }

    #[allow(deprecated)]
    let open_result = app.shell().open(url.clone(), None);

    match open_result {
        Ok(()) => Ok(()),
        Err(err) => {
            log::warn!("[external-link] open failed: {err}");
            Err(err.to_string())
        }
    }
}

/// Resolve a vetted workspace HTML file through the local backend and open it.
#[tauri::command]
pub(crate) async fn open_workspace_html(
    app: tauri::AppHandle,
    url: String,
    headers: Option<HashMap<String, String>>,
    state: tauri::State<'_, BackendState>,
    webview: tauri::Webview,
    scope: tauri::ipc::CommandScope<BackendScope>,
) -> Result<(), String> {
    let session = state.authorized_session(&webview, &scope)?;
    let uri = resolve_workspace_html(&url, headers, &session).await?;
    #[allow(deprecated)]
    app.shell().open(uri, None).map_err(|err| err.to_string())
}

async fn resolve_workspace_html(
    url: &str,
    headers: Option<HashMap<String, String>>,
    session: &BackendSession,
) -> Result<String, String> {
    let resolver_url = validate_html_resolver_url(url)?;
    if resolver_url.origin().ascii_serialization() != session.origin
        || !resolver_url.username().is_empty()
        || resolver_url.password().is_some()
    {
        return Err("HTML resolver must target the current backend origin".into());
    }
    let mut request_headers = parse_headers(headers.unwrap_or_default())?;
    request_headers.insert(
        DESKTOP_SESSION_HEADER,
        HeaderValue::from_str(&session.token)
            .map_err(|_| "invalid desktop session credential".to_string())?,
    );
    let response = reqwest::Client::builder()
        .no_proxy()
        .redirect(reqwest::redirect::Policy::none())
        .timeout(Duration::from_secs(30))
        .build()
        .map_err(|err| format!("failed to create HTML resolver client: {err}"))?
        .get(resolver_url)
        .headers(request_headers)
        .send()
        .await
        .map_err(|err| format!("HTML resolver request failed: {err}"))?;

    if !response.status().is_success() {
        return Err(format!(
            "HTML resolver request failed with status code {}",
            response.status()
        ));
    }

    let response_body = response
        .bytes()
        .await
        .map_err(|err| format!("failed to read HTML resolver response: {err}"))?;
    let payload = serde_json::from_slice::<HtmlFileUriResponse>(&response_body)
        .map_err(|err| format!("invalid HTML resolver response: {err}"))?;
    validate_html_file_uri(&payload.uri)?;

    Ok(payload.uri)
}

/// Reject empty, ambiguous, or unsupported URL inputs before calling shell.open.
fn validate_external_url(url: &str) -> Result<(), String> {
    let trimmed_url = url.trim();
    if trimmed_url.is_empty() {
        return Err("external link is empty".into());
    }
    if trimmed_url != url {
        return Err("external link has leading or trailing whitespace".into());
    }
    if trimmed_url.chars().any(char::is_control) {
        return Err("external link contains control characters".into());
    }

    let lowercase_url = trimmed_url.to_ascii_lowercase();
    if SUPPORTED_EXTERNAL_PREFIXES
        .iter()
        .any(|prefix| lowercase_url.starts_with(prefix))
    {
        return Ok(());
    }

    Err("external link protocol is not supported".into())
}

fn validate_html_resolver_url(url: &str) -> Result<Url, String> {
    let parsed = Url::parse(url).map_err(|err| format!("invalid HTML resolver URL: {err}"))?;
    if parsed.scheme() != "http" || parsed.path() != HTML_URI_PATH {
        return Err("HTML resolver URL is not supported".into());
    }
    let is_loopback = match parsed.host_str() {
        Some(host) if host.eq_ignore_ascii_case("localhost") => true,
        Some(host) => host
            .trim_matches(['[', ']'])
            .parse::<IpAddr>()
            .map(|ip| ip.is_loopback())
            .unwrap_or(false),
        None => false,
    };
    if !is_loopback {
        return Err("HTML resolver must target the local backend".into());
    }
    Ok(parsed)
}

fn validate_html_file_uri(uri: &str) -> Result<(), String> {
    let parsed = Url::parse(uri).map_err(|err| format!("invalid HTML file URI: {err}"))?;
    if parsed.scheme() != "file" {
        return Err("HTML file URI protocol is not supported".into());
    }
    let lowercase_path = parsed.path().to_ascii_lowercase();
    if !lowercase_path.ends_with(".html") && !lowercase_path.ends_with(".htm") {
        return Err("HTML file URI must reference an HTML file".into());
    }
    Ok(())
}

fn parse_headers(headers: HashMap<String, String>) -> Result<HeaderMap, String> {
    let mut header_map = HeaderMap::new();
    for (name, value) in headers {
        let header_name = HeaderName::from_bytes(name.as_bytes())
            .map_err(|err| format!("invalid HTML resolver header name: {err}"))?;
        let header_value = HeaderValue::from_str(&value)
            .map_err(|err| format!("invalid HTML resolver header value: {err}"))?;
        header_map.insert(header_name, header_value);
    }
    Ok(header_map)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::{Read, Write};
    use std::net::TcpListener;

    #[test]
    fn html_resolver_authenticates_without_following_redirects() {
        let runtime = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .unwrap();
        for status in [200, 307] {
            let listener = TcpListener::bind("127.0.0.1:0").unwrap();
            let origin = format!("http://{}", listener.local_addr().unwrap());
            let server = std::thread::spawn(move || {
                let (mut stream, _) = listener.accept().unwrap();
                stream
                    .set_read_timeout(Some(Duration::from_secs(3)))
                    .unwrap();
                let mut bytes = [0; 4096];
                let length = stream.read(&mut bytes).unwrap();
                let request = String::from_utf8_lossy(&bytes[..length]).to_lowercase();
                let body = r#"{"uri":"file:///C:/fixture/preview.html"}"#;
                write!(stream, "HTTP/1.1 {status} Test\r\nContent-Length: {}\r\nLocation: http://127.0.0.1:9/foreign\r\nConnection: close\r\n\r\n{body}", body.len()).unwrap();
                request
            });
            let session = BackendSession {
                origin: origin.clone(),
                token: "native-fixture".into(),
                generation: "1".into(),
            };
            let headers = HashMap::from([
                ("Authorization".into(), "Bearer account-fixture".into()),
                ("X-Desktop-Session".into(), "stale-fixture".into()),
            ]);
            let result = runtime.block_on(resolve_workspace_html(
                &format!("{origin}{HTML_URI_PATH}?path=preview.html"),
                Some(headers),
                &session,
            ));
            if status == 200 {
                assert_eq!(result.unwrap(), "file:///C:/fixture/preview.html");
            } else {
                assert!(result.unwrap_err().contains("307"));
            }
            let request = server.join().unwrap();
            assert!(request.contains("x-desktop-session: native-fixture"));
            assert!(request.contains("authorization: bearer account-fixture"));
            assert!(!request.contains("stale-fixture"));
            for url in [
                "http://127.0.0.1:9/api/workspace/html-file-uri".to_string(),
                format!("{origin}/api/mcp"),
                origin.replace("http://", "http://user@") + HTML_URI_PATH,
            ] {
                assert!(runtime
                    .block_on(resolve_workspace_html(&url, None, &session))
                    .is_err());
            }
        }
    }
}
