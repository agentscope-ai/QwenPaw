//! Tauri command for opening vetted external URLs in the system browser.

use std::{collections::HashMap, net::IpAddr, time::Duration};

use reqwest::{
    header::{HeaderMap, HeaderName, HeaderValue},
    Url,
};
use serde::Deserialize;
use tauri_plugin_shell::ShellExt;

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
) -> Result<(), String> {
    let resolver_url = validate_html_resolver_url(&url)?;
    let request_headers = parse_headers(headers.unwrap_or_default())?;
    let response = reqwest::Client::builder()
        .no_proxy()
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

    #[allow(deprecated)]
    app.shell()
        .open(payload.uri, None)
        .map_err(|err| err.to_string())
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
