//! Native downloads for files served by the bundled local backend.

use std::{collections::HashMap, net::IpAddr, path::PathBuf, time::Duration};

use futures_util::TryStreamExt;
use reqwest::{
    header::{HeaderMap, HeaderName, HeaderValue},
    Url,
};
use serde::Deserialize;
use tokio::{
    fs::File,
    io::{AsyncWriteExt, BufWriter},
};

const BACKEND_DOWNLOAD_CONNECT_TIMEOUT: Duration = Duration::from_secs(30);
const BACKEND_DOWNLOAD_TOTAL_TIMEOUT: Duration = Duration::from_secs(30 * 60);

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct DownloadBackendFileRequest {
    url: String,
    file_path: String,
    headers: Option<HashMap<String, String>>,
}

/// Stream a local backend response to the user-selected file path without using system proxies.
#[tauri::command]
pub(crate) async fn download_backend_file(
    request: DownloadBackendFileRequest,
) -> Result<(), String> {
    let url = parse_local_backend_url(&request.url)?;
    let file_path = parse_file_path(&request.file_path)?;
    let headers = parse_headers(request.headers.unwrap_or_default())?;

    let response = reqwest::Client::builder()
        .no_proxy()
        .connect_timeout(BACKEND_DOWNLOAD_CONNECT_TIMEOUT)
        .timeout(BACKEND_DOWNLOAD_TOTAL_TIMEOUT)
        .build()
        .map_err(|err| format!("failed to create download client: {err}"))?
        .get(url)
        .headers(headers)
        .send()
        .await
        .map_err(|err| format!("download request failed: {err}"))?;

    if !response.status().is_success() {
        return Err(format!(
            "download request failed with status code {}",
            response.status()
        ));
    }

    let mut file = BufWriter::new(
        File::create(&file_path)
            .await
            .map_err(|err| format!("failed to create file: {err}"))?,
    );
    let mut stream = response.bytes_stream();

    while let Some(chunk) = stream
        .try_next()
        .await
        .map_err(|err| format!("failed to read response stream: {err}"))?
    {
        file.write_all(&chunk)
            .await
            .map_err(|err| format!("failed to write file: {err}"))?;
    }

    file.flush()
        .await
        .map_err(|err| format!("failed to flush file: {err}"))
}

fn parse_local_backend_url(url: &str) -> Result<Url, String> {
    let parsed = Url::parse(url).map_err(|err| format!("invalid download URL: {err}"))?;
    if parsed.scheme() != "http" {
        return Err("download URL protocol is not supported".into());
    }
    if !is_loopback_host(&parsed) {
        return Err("download URL must target the local backend".into());
    }
    Ok(parsed)
}

fn is_loopback_host(url: &Url) -> bool {
    match url.host_str() {
        Some(host) if host.eq_ignore_ascii_case("localhost") => true,
        Some(host) => host
            .trim_matches(['[', ']'])
            .parse::<IpAddr>()
            .map(|ip| ip.is_loopback())
            .unwrap_or(false),
        None => false,
    }
}

fn parse_file_path(file_path: &str) -> Result<PathBuf, String> {
    if file_path.trim().is_empty() {
        return Err("download file path is empty".into());
    }
    Ok(PathBuf::from(file_path))
}

fn parse_headers(headers: HashMap<String, String>) -> Result<HeaderMap, String> {
    let mut header_map = HeaderMap::new();
    for (name, value) in headers {
        let header_name = HeaderName::from_bytes(name.as_bytes())
            .map_err(|err| format!("invalid download header name: {err}"))?;
        let header_value = HeaderValue::from_str(&value)
            .map_err(|err| format!("invalid download header value: {err}"))?;
        header_map.insert(header_name, header_value);
    }
    Ok(header_map)
}

#[cfg(test)]
mod tests {
    use super::parse_local_backend_url;

    #[test]
    fn accepts_loopback_backend_urls() {
        assert!(parse_local_backend_url("http://127.0.0.1:54377/api/backups/id/export").is_ok());
        assert!(parse_local_backend_url("http://localhost:54377/api/workspace/download").is_ok());
        assert!(parse_local_backend_url("http://[::1]:54377/api/workspace/download").is_ok());
    }

    #[test]
    fn rejects_remote_download_urls() {
        assert!(parse_local_backend_url("https://example.com/file.zip").is_err());
        assert!(parse_local_backend_url("http://192.168.1.20/file.zip").is_err());
    }

    #[test]
    fn rejects_non_http_download_urls() {
        assert!(parse_local_backend_url("file:///C:/tmp/backup.zip").is_err());
        assert!(parse_local_backend_url("mailto:support@example.com").is_err());
    }
}
